import http from 'node:http';
import { access, mkdir, realpath, lstat, readFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { createHash } from 'node:crypto';
import { openTaskStore, TaskError } from './lib/task-store.mjs';
import { commandChoices, ProposalError } from './lib/command-proposals.mjs';
import { prepareExecution, executeOwned } from './lib/command-execution.mjs';
import { createConnectionReader, readFixedInference, normalizeInference, emptyInference } from './lib/service-connections.mjs';
import { createTrialSessionManager, createTrialHttpGuard, SESSION_COOKIE_NAME } from './lib/trial-session.mjs';
import { createRelayLink } from './lib/relay-link.mjs';
import { createNodeProbeReader } from './lib/node-probes.mjs';
import { createLocalInference, createDisabledLocalAdapter } from './lib/local-inference.mjs';

export const ROOT = path.dirname(fileURLToPath(import.meta.url));
export async function confinedPath(value) {
  const target = path.resolve(ROOT, value);
  const relative = path.relative(ROOT, target);
  if (relative.startsWith('..') || path.isAbsolute(relative)) throw new Error('Path outside trial root.');
  let current = ROOT;
  for (const segment of relative.split(path.sep).filter(Boolean)) {
    current = path.join(current, segment);
    try { if ((await lstat(current)).isSymbolicLink()) throw new Error('Links are not allowed.'); }
    catch (e) { if (e.code !== 'ENOENT') throw e; }
  }
  const realRoot = await realpath(ROOT);
  const resolvedRoot = path.resolve(ROOT);
  if (realRoot.toLowerCase() !== resolvedRoot.toLowerCase()) throw new Error('Linked trial root is not allowed.');
  return target;
}
const staticFiles = new Map([['/', ['public/index.html', 'text/html']], ['/app.js', ['public/app.js', 'text/javascript']], ['/styles.css', ['public/styles.css', 'text/css']]]);
const relayAssets = new Set(['slash-commands.json','slash-commands-openclaw.json']);
for (const [file, type] of [
  ['manifest.webmanifest', 'application/manifest+json'], ['icon.svg', 'image/svg+xml'],
  ['pwa-register.mjs', 'text/javascript'], ['sw.js', 'text/javascript'],
]) staticFiles.set('/' + file, ['public/' + file, type]);
staticFiles.set('/shell-cache-policy.mjs', ['public/shell-cache-policy-browser-v2.mjs', 'text/javascript']);
const snapshot = state => ({ schemaVersion: 'mesh-worker-activity/v1', state, observedAt: new Date().toISOString(), workers: [] });
const modulePath = path.join(ROOT, 'lib/worker-activity.mjs');
async function adapterStatus() {
  try { await access(modulePath); return 'present'; }
  catch (e) { return e.code === 'ENOENT' ? 'awaiting_integration' : 'unavailable'; }
}
async function activity(registryPath) {
  try { await access(modulePath); } catch (e) { return snapshot(e.code === 'ENOENT' ? 'not_configured' : 'unavailable'); }
  try {
    await confinedPath(modulePath);
    if (registryPath) await confinedPath(registryPath);
    const { readWorkerActivity } = await import(pathToFileURL(modulePath).href);
    return await readWorkerActivity({ registryPath, nowIso: new Date().toISOString(), staleAfterMs: 600000 });
  } catch { return snapshot('unavailable'); }
}
export async function startApp({ port = 0, dataDir = 'data/mesh', registryPath, activitySource = 'disposable_fixture', serviceConfig = {}, inferenceConfig, inferenceTestReader, nodeProbeTestOptions, localInferenceTestOptions, sessionTtlMs = 300000, sessionNow, relayEnabled = process.env.MESH_RELAY === '1' } = {}) {
  // Process configuration only. Standalone wins over ambient Relay enablement
  // and never constructs the native node reader or imports inference workers.
  const standalone = process.env.MESH_STANDALONE === '1';
  if (!Number.isSafeInteger(port) || port < 0 || port > 65535) throw new Error('A valid loopback port is required.');
  if (!Number.isSafeInteger(sessionTtlMs) || sessionTtlMs < 1 || sessionTtlMs > 300000) throw new Error('APP03 demo lifetime must be 1..300000 ms.');
  if (typeof dataDir !== 'string' || !/^(?:test[\\/]app03-[a-zA-Z0-9_-]+|data[\\/][a-zA-Z0-9_-]+)$/.test(dataDir)) throw new Error('An owned data/ directory or disposable test/app03- directory is required.');
  if (Object.keys(serviceConfig).length || inferenceConfig !== undefined) throw new Error('Live connections are outside APP03.');
  if (!['local_registry', 'disposable_fixture', 'frozen_manager_projection'].includes(activitySource)) throw new Error('Invalid activity source label.');
  if (registryPath && (typeof registryPath !== 'string' || /^[a-z][a-z0-9+.-]*:\/\//i.test(registryPath))) throw new Error('Invalid local registry path.');
  if (inferenceTestReader !== undefined && typeof inferenceTestReader !== 'function') throw new Error('Invalid test observation reader.');
  if (typeof relayEnabled !== 'boolean') throw new Error('Invalid Relay mode.');
  if (standalone) relayEnabled = false;
  // Trusted fixture seam only. No HTTP/CLI/environment adapter selection.
  if (localInferenceTestOptions !== undefined && (!localInferenceTestOptions ||
      Object.keys(localInferenceTestOptions).some(k => !['adapter', 'now'].includes(k)) ||
      localInferenceTestOptions.adapter?.source !== 'disposable_fixture')) throw new Error('Invalid inference fixture.');
  const localInference = createLocalInference(standalone
    ? { adapter: createDisabledLocalAdapter('STANDALONE_NOT_CONFIGURED') } : localInferenceTestOptions);
  // Trusted in-process tests only; HTTP cannot supply any probe configuration.
  if (nodeProbeTestOptions !== undefined && (!nodeProbeTestOptions ||
      Object.keys(nodeProbeTestOptions).some(key => !['spawnImpl', 'clock', 'monotonic'].includes(key)) ||
      Object.values(nodeProbeTestOptions).some(value => typeof value !== 'function')))
    throw new Error('Invalid test node probe hooks.');
  const absentNodes = () => ({ schemaVersion: 'mesh-node-probes/v1', observedAt: new Date().toISOString(),
    status: 'not_configured', source: 'none', scope: 'standalone', nodes: [] });
  const nodeProbes = standalone ? { snapshot: absentNodes, refresh: async () => absentNodes() }
    : createNodeProbeReader(nodeProbeTestOptions);
  const fixedInferenceConfig = inferenceConfig === undefined ? undefined : structuredClone(inferenceConfig);
  const directory = await confinedPath(dataDir);
  const filename = await confinedPath(path.join(directory, 'tasks.sqlite'));
  const configuredRegistry = registryPath ? await confinedPath(registryPath) : undefined;
  if (configuredRegistry && !configuredRegistry.startsWith(directory + path.sep)) throw new Error('Registry must be in the owned synthetic subtree.');
  const manager = createTrialSessionManager({ ttlMs: sessionTtlMs, maxSessions: 32, ...(sessionNow ? { now: sessionNow } : {}) });
  await mkdir(directory, { recursive: true });
  let store;
  const executions = new Set();
  const activeRuns = new Map();
  let executionPersistenceFailed = false;
  try { store = openTaskStore(filename); } catch { /* Preserve invalid data; serve a visible failure. */ }
  const relay = await createRelayLink({ root: ROOT, directory, confine: confinedPath, store, enabled: relayEnabled });
  // Only hashes of fixed source code/CSS authorize the existing native HTML.
  // srcdoc receives that HTML via an admitted API read, never a public route.
  let relayScriptHashes = '', relayStyleHashes = '';
  try {
    const html = await readFile(await confinedPath('service_roots/relay/static/index.html'), 'utf8');
    const hashes = tag => [...html.matchAll(new RegExp(`<${tag}>([\\s\\S]*?)<\\/${tag}>`, 'g'))]
      .map(m => `'sha256-${createHash('sha256').update(m[1].replace(/\r\n?/g, '\n')).digest('base64')}'`).join(' ');
    relayScriptHashes = hashes('script'); relayStyleHashes = hashes('style');
  } catch { /* Absent Relay remains a supported disconnected app state. */ }
  // Server-only test seam; CLI and HTTP never accept a reader or module path.
  // Validate again at the HTTP seam, including deliberately hostile test readers.
  const inference = async () => {
    const nowIso = new Date().toISOString();
    if (standalone) return emptyInference('not_configured', nowIso);
    try {
      const value = inferenceTestReader ? await inferenceTestReader({config:fixedInferenceConfig,nowIso}) : await readFixedInference({ modulePath: path.join(ROOT, 'lib/inference-observation.mjs'), confine: confinedPath, config: fixedInferenceConfig, nowIso });
      return normalizeInference(value,nowIso);
    } catch { return normalizeInference({schemaVersion:'mesh-inference-observation/v1',observedAt:nowIso,status:'unavailable',nodes:[],errors:[]},nowIso); }
  };
  const connections = createConnectionReader({ config: serviceConfig, inferenceReader: inference, ...(relayEnabled ? { relayReader: () => relay.snapshot() } : {}) });
  let guard;
  const server = http.createServer(async (req, res) => {
    let context;
    const deny = code => { res.writeHead(code, { 'Cache-Control': 'no-store', 'Pragma': 'no-cache' }); res.end(); };
    const current = () => {
      if (!context) return true;
      const sessionId = (req.headers.cookie ?? '').split(';').map(s => s.trim()).find(s => s.startsWith(SESSION_COOKIE_NAME + '='))?.slice(SESSION_COOKIE_NAME.length + 1);
      // The guard already validated headers and consumed the body. Recheck the
      // same server-owned manager/proof after every asynchronous observation.
      const admission = manager.authorize(sessionId, { mutation: true, csrfToken: req.headers['x-trial-csrf'] });
      if (!admission) { deny(401); return false; }
      return true;
    };
    const send = (code, body, type = 'application/json', isPublic = false) => {
      if (!current()) return;
      res.writeHead(code, { 'Content-Type': `${type}; charset=utf-8`, 'Cache-Control': 'no-store',
        ...(isPublic ? { 'Cache-Control': 'public, max-age=0' } : { 'Pragma': 'no-cache' }),
        'X-Content-Type-Options': 'nosniff', 'Referrer-Policy': 'no-referrer',
        'Content-Security-Policy': `default-src 'self'; connect-src 'self'; script-src 'self' ${relayScriptHashes}; style-src 'self' ${relayStyleHashes}; img-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'` });
      res.end(req.method === 'HEAD' ? undefined : type === 'application/json' && !Buffer.isBuffer(body) ? JSON.stringify(body) : body);
    };
    try {
      const origin = `http://127.0.0.1:${server.address().port}`;
      const route = req.url;
      if (route === '/api/trial-session/bootstrap') { await guard.bootstrap(req, res); return; }
      if (route === '/api/trial-session/recovery-challenge') { await guard.recoveryChallenge(req, res); return; }
      if (route === '/api/trial-session/recovery-complete') { await guard.recoveryComplete(req, res); return; }
      if (route === '/api/trial-session/logout') { await guard.logout(req, res); return; }
      if (route === '/api' || route.startsWith('/api/')) {
        context = await guard.authorize(req, res);
        if (!context) return;
        if (!current()) return;
      } else {
        const hosts = req.rawHeaders.filter((v, i) => i % 2 === 0 && v.toLowerCase() === 'host');
        if (hosts.length !== 1 || req.headers.host !== `127.0.0.1:${server.address().port}`) { deny(403); return; }
        if (['GET', 'HEAD'].includes(req.method) && staticFiles.has(route)) {
          const [file, type] = staticFiles.get(route); return send(200, await readFile(path.join(ROOT, file)), type, true);
        }
        deny(404); return;
      }
      if (route === '/api/health' && ['GET', 'HEAD'].includes(req.method)) return send(store ? 200 : 503, {
        state: store ? 'ok' : 'unavailable', persistence: store ? 'sqlite' : 'unavailable', scope: 'local_trial',
        url: origin, integrations: 'not_connected', mode: standalone ? 'standalone' : 'mesh',
        activity: { adapter: await adapterStatus(), registry: configuredRegistry ? 'configured' : 'not_configured', source: configuredRegistry ? activitySource : 'none' }
      });
      if (route === '/api/worker-activity' && ['GET', 'HEAD'].includes(req.method)) return send(200, await activity(configuredRegistry));
      if (route === '/api/service-connections' && ['GET', 'HEAD'].includes(req.method)) return send(200, await connections());
      if (route === '/api/inference-observation' && ['GET', 'HEAD'].includes(req.method)) return send(200, await inference());
      if (route.startsWith('/api/inference/')) {
        const sessionId = (req.headers.cookie ?? '').split(';').map(s => s.trim()).find(s => s.startsWith(SESSION_COOKIE_NAME + '='))?.slice(SESSION_COOKIE_NAME.length + 1);
        const admitted = () => Boolean(manager.authorize(sessionId, { mutation: true, csrfToken: req.headers['x-trial-csrf'] }));
        if (route === '/api/inference/status' && ['GET', 'HEAD'].includes(req.method)) return send(200, await localInference.status());
        const receiptId = /^\/api\/inference\/receipt\/([0-9a-f-]{36})$/.exec(route)?.[1];
        if (receiptId && ['GET', 'HEAD'].includes(req.method)) return send(200, localInference.receipt(receiptId, sessionId));
        if (req.method !== 'POST') throw new TaskError(405, 'Method not allowed.');
        const action = /^\/api\/inference\/propose-(load|stop|unload)$/.exec(route)?.[1];
        if (action) return send(201, await localInference.propose(action, context.body, sessionId, admitted));
        if (route === '/api/inference/approve') return send(200, await localInference.approve(context.body, sessionId, admitted));
        if (route === '/api/inference/chat') {
          const controller = new AbortController();
          const abort = () => controller.abort();
          res.once('close', abort);
          try { return send(200, await localInference.chat(context.body, admitted, controller.signal)); }
          finally { res.off('close', abort); }
        }
        throw new TaskError(404, 'Route not found.');
      }
      if (route === '/api/node-probes' && ['GET', 'HEAD'].includes(req.method)) return send(200, nodeProbes.snapshot());
      if (route === '/api/node-probes/refresh') {
        if (req.method !== 'POST') throw new TaskError(405, 'Method not allowed.');
        if (!context.body || Object.keys(context.body).length) throw new TaskError(400, 'Node refresh accepts no configuration.');
        if (!current()) return;
        // One reader per server; concurrent callers share the fixed native read.
        return send(200, await nodeProbes.refresh());
      }
      if (route === '/api/commands' && ['GET', 'HEAD'].includes(req.method)) return send(200, { commands: commandChoices });
      if (route === '/api/relay' && ['GET', 'HEAD'].includes(req.method)) return send(200, await relay.snapshot());
      if (route === '/api/relay/shell' && ['GET', 'HEAD'].includes(req.method)) return send(200, { html: await relay.shell() });
      const relayAsset = /^\/api\/relay\/static\/([a-z.-]+)$/.exec(route)?.[1];
      if (relayAsset && relayAssets.has(relayAsset) && ['GET','HEAD'].includes(req.method))
        return send(200, await readFile(await confinedPath('service_roots/relay/static/'+relayAsset)), relayAsset.endsWith('.svg') ? 'image/svg+xml' : 'application/json');
      if (route === '/api/relay/native/api/agents' && req.method === 'GET') return send(200, await relay.agents());
      if (route === '/api/relay/native/api/auth' && req.method === 'GET') return send(200, await relay.nativeRead('/api/auth'));
      if (route === '/api/relay/native/api/agents/mesh/sessions' && req.method === 'GET') return send(200, await relay.nativeRead('/api/agents/mesh/sessions'));
      if (route.startsWith('/api/relay/native/')) throw new TaskError(403, 'This Relay control is unavailable in Mesh-only mode.');
      if (route === '/api/relay/message') {
        if (req.method !== 'POST') throw new TaskError(405, 'Method not allowed.');
        if (!store || executionPersistenceFailed) throw new TaskError(503, 'Workroom persistence unavailable.');
        const sessionId = (req.headers.cookie ?? '').split(';').map(s => s.trim()).find(s => s.startsWith(SESSION_COOKIE_NAME + '='))?.slice(SESSION_COOKIE_NAME.length + 1);
        const admitted = () => Boolean(manager.authorize(sessionId, { mutation: true, csrfToken: req.headers['x-trial-csrf'] }));
        return send(200, await relay.message(context.body, admitted));
      }
      if (route === '/api/relay/reconnect') {
        if (req.method !== 'POST') throw new TaskError(405, 'Method not allowed.');
        if (!context.body || Object.keys(context.body).length) throw new TaskError(400, 'Reconnect accepts no configuration.');
        if (!current()) return;
        return send(200, await relay.reconnect());
      }
      const cancelRoute = /^\/api\/tasks\/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\/cancel$/.exec(route);
      if (cancelRoute) {
        if (req.method !== 'POST') throw new TaskError(405, 'Method not allowed.');
        if (!store || executionPersistenceFailed) throw new TaskError(503, 'Persistence unavailable. Existing data has been preserved.');
        const id = cancelRoute[1];
        const runId = store.cancelTarget(id, context.body);
        const active = activeRuns.get(runId);
        if (!active || active.taskId !== id) throw new TaskError(409, 'Run is no longer owned here. Reload current task.');
        if (!current()) return;
        // Revoke only this attempt, then await its existing promise and durable
        // result. Until then the store honestly remains running/result unknown.
        active.controller.abort();
        await active.operation;
        if (executionPersistenceFailed) throw new TaskError(503, 'Execution result persistence unavailable.');
        return send(200, { task: store.get(id) });
      }
      const decisionRoute = /^\/api\/tasks\/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\/(approve|deny)$/.exec(route);
      if (decisionRoute) {
        if (req.method !== 'POST') throw new TaskError(405, 'Method not allowed.');
        if (!store || executionPersistenceFailed) throw new TaskError(503, 'Persistence unavailable. Existing data has been preserved.');
        const id = decisionRoute[1]; const approved = decisionRoute[2] === 'approve';
        const task = store.get(id);
        if (!task) throw new TaskError(404, 'Task not found.');
        // Replay bypasses preparation and execution, behind the same HTTP guard.
        if (approved) {
          const replay = store.approvalReplay(id, context.body);
          if (replay) return send(200, { task: replay });
        }
        // Preparation cannot launch. Recheck session after filesystem awaits;
        // the transaction either claims this revision or replays its winner.
        const plan = approved ? await prepareExecution(task.proposal) : undefined;
        if (!current()) return;
        const claimed = store.decide(id, context.body, approved, plan);
        if (!approved || claimed.replayed) return send(200, { task: claimed.task });
        const runId = claimed.task.execution.id;
        store.running(id, runId); // A failed durable transition launches nothing.
        const controller = new AbortController();
        const operation = (async () => {
          let result;
          try { result = await executeOwned(plan, { signal: controller.signal }); }
          catch (error) { result = { status: 'FAIL', rootPid: null, rootExitCode: null, timedOut: false,
            cleanupVerified: false, error: error.message, stdout: '', stderr: '' }; }
          try { store.finish(id, runId, result); }
          catch (error) {
            executionPersistenceFailed = true;
            console.error(JSON.stringify({ event: 'mesh_execution_persistence_failed', runId, result, error: error.message }));
          }
        })();
        activeRuns.set(runId, { taskId: id, controller, operation });
        executions.add(operation); operation.finally(() => { executions.delete(operation); activeRuns.delete(runId); });
        return send(202, { task: store.get(id) });
      }
      const proposalRoute = /^\/api\/tasks\/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\/proposal$/.exec(route);
      if (proposalRoute) {
        if (req.method !== 'POST') throw new TaskError(405, 'Method not allowed.');
        if (!store || executionPersistenceFailed) throw new TaskError(503, 'Persistence unavailable. Existing data has been preserved.');
        if (!current()) return;
        return send(200, { task: store.propose(proposalRoute[1], context.body) });
      }
      const taskRoute = /^\/api\/tasks(?:\/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}))?$/.exec(route);
      if (!taskRoute) throw new TaskError(404, 'Route not found.');
      if (!store) throw new TaskError(503, 'Persistence unavailable. Existing data has been preserved.');
      const id = taskRoute[1];
      if (['GET', 'HEAD'].includes(req.method)) {
        if (!id) return send(200, { tasks: store.list() });
        const task = store.get(id); if (!task) throw new TaskError(404, 'Task not found.');
        return send(200, { task });
      }
      if (executionPersistenceFailed) throw new TaskError(503, 'Execution persistence unavailable. Existing data has been preserved.');
      if (req.method === 'POST' && !id) { if (!current()) return; return send(201, { task: store.create(context.body) }); }
      if (req.method === 'PATCH' && id) { if (!current()) return; return send(200, { task: store.update(id, context.body) }); }
      throw new TaskError(405, 'Method not allowed.');
    } catch (e) {
      if (!res.headersSent) send(e instanceof TaskError || e instanceof ProposalError ? e.status : 503, { error: e instanceof TaskError || e instanceof ProposalError ? e.message : 'Local operation unavailable. Data has not been reset.' });
    }
  });
  server.requestTimeout = 10000;
  server.headersTimeout = 10000;
  server.on('clientError', (_error, socket) => {
    if (socket.writable) socket.end('HTTP/1.1 400 Bad Request\r\nCache-Control: no-store\r\nPragma: no-cache\r\nContent-Length: 0\r\nConnection: close\r\n\r\n');
    else socket.destroy();
  });
  try { await new Promise((resolve, reject) => { server.once('error', reject); server.listen(port, '127.0.0.1', resolve); }); }
  catch (e) { await relay.close(); store?.close(); throw e; }
  guard = createTrialHttpGuard({ manager, port: server.address().port });
  return { server, mode: standalone ? 'standalone' : 'mesh', url: `http://127.0.0.1:${server.address().port}`, close: async () => {
    const closed = new Promise((resolve, reject) => server.close(e => e ? reject(e) : resolve()));
    server.closeAllConnections(); await closed; await relay.close(); await Promise.allSettled([...executions]); store?.close();
  } };
}

// The existing bounded preview may still import startApp. Direct startup uses
// the same application and store, with a stable directory across restarts.
if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const app = await startApp({
    port: Number(process.env.MESH_PORT ?? 3000),
    dataDir: process.env.MESH_DATA_DIR ?? 'data/mesh',
    relayEnabled: process.env.MESH_RELAY === '1',
  });
  console.log(JSON.stringify({ event: 'mesh_listening', pid: process.pid, url: app.url,
    dataDir: process.env.MESH_DATA_DIR ?? 'data/mesh', mode: app.mode }));
  let stopping = false;
  for (const signal of ['SIGINT', 'SIGTERM']) process.once(signal, async () => {
    if (stopping) return;
    stopping = true;
    await app.close();
  });
}
