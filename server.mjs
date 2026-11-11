import {withRelaySource} from './lib/connection-observations.mjs';
import {createMindRecallClient,recallInput} from './lib/mind-recall.mjs';
import {automationPolicy} from './lib/workroom-automation-store.mjs';
import {readNemotronQualification} from './lib/nemotron-qualification.mjs';
import {createNemotronClient} from './lib/nemotron-client.mjs';
import {createNemotronRuntime} from './lib/nemotron-runtime.mjs';
import {DatabaseSync} from 'node:sqlite';
import {createModelOperationStore} from './lib/model-operation-store.mjs';
import {createSupervisedInference,createPendingNemotronInference} from './lib/supervised-inference.mjs';
import {createSupervisorObservation} from './lib/supervisor-observation.mjs';
import http from 'node:http';
import {createTeamRunner} from './lib/workroom-automation.mjs';
import {createNativeWorkerBinding} from './lib/workroom-native-binding.mjs';
import {withNims} from './lib/nims-link.mjs';
import { releaseInfo } from './lib/release-info.mjs';
import {requestAudit} from './lib/request-audit.mjs';
import {createDshApprovalClient,captureDshResult} from './lib/dsh-approval.mjs';
import { sendTaskMessage, syncTaskReplies, sendTaskHandoff } from './lib/workroom.mjs';
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
import { createRelayHttpLink } from './lib/relay-http.mjs';
import { createNodeProbeReader } from './lib/node-probes.mjs';
import { createLocalInference, createDisabledLocalAdapter } from './lib/local-inference.mjs';
import {createRookRuntime} from './lib/workroom-rook.mjs';
import {writerQuiescenceBlockers} from './lib/workroom-claim-policy.mjs';

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
staticFiles.set('/workroom.mjs', ['public/workroom.mjs', 'text/javascript']);
staticFiles.set('/agent-workspace.mjs', ['public/agent-workspace.mjs', 'text/javascript']);
staticFiles.set('/mind-workspace.mjs', ['public/mind-workspace.mjs', 'text/javascript']);
staticFiles.set('/relay-conversation.mjs', ['public/relay-conversation.mjs', 'text/javascript']);
staticFiles.set('/relay-task-progress.mjs', ['public/relay-task-progress.mjs', 'text/javascript']);
staticFiles.set('/lead-policy.mjs', ['public/lead-policy.mjs', 'text/javascript']);
staticFiles.set('/workroom-plan.mjs', ['public/workroom-plan.mjs', 'text/javascript']);
staticFiles.set('/workroom-status.mjs', ['public/workroom-status.mjs', 'text/javascript']);
staticFiles.set('/workroom-drag.mjs', ['public/workroom-drag.mjs', 'text/javascript']);
staticFiles.set('/workroom-view.mjs', ['public/workroom-view.mjs', 'text/javascript']);
staticFiles.set('/workroom-edit.mjs', ['public/workroom-edit.mjs', 'text/javascript']);
staticFiles.set('/workroom-load.mjs', ['public/workroom-load.mjs', 'text/javascript']);
staticFiles.set('/session-entry.mjs', ['public/session-entry.mjs', 'text/javascript']);
staticFiles.set('/workroom-columns-v2.mjs', ['public/workroom.mjs', 'text/javascript']);
staticFiles.set('/workroom-columns-v2.css', ['public/styles.css', 'text/css']);
staticFiles.set('/mesh-design-v3.css', ['public/styles.css', 'text/css']);
staticFiles.set('/mesh-tokens-v3.css', ['shared/tokens.css', 'text/css']);
staticFiles.set('/mesh-theme-v3.mjs', ['public/theme.mjs', 'text/javascript']);
staticFiles.set('/mesh-workroom-v3.mjs', ['public/workroom.mjs', 'text/javascript']);
const relayAssets = new Set(['slash-commands.json','slash-commands-openclaw.json']);
for (const [file, type] of [
  ['manifest.webmanifest', 'application/manifest+json'], ['icon.svg', 'image/svg+xml'],
  ['pwa-register.mjs', 'text/javascript'], ['sw.js', 'text/javascript'],
]) staticFiles.set('/' + file, ['public/' + file, type]);
staticFiles.set('/shared/tokens.css', ['shared/tokens.css', 'text/css']);
staticFiles.set('/text-size.mjs', ['public/text-size.mjs', 'text/javascript']);
staticFiles.set('/agents.json', ['public/agents.json', 'application/json']);
staticFiles.set('/chat.json', ['public/chat.json', 'application/json']);
staticFiles.set('/inference.json', ['public/inference.json', 'application/json']);
staticFiles.set('/control.mjs', ['public/control.mjs', 'text/javascript']);
staticFiles.set('/control-models.mjs', ['public/control-models.mjs', 'text/javascript']);
staticFiles.set('/chat.mjs', ['public/chat.mjs', 'text/javascript']);
staticFiles.set('/theme.mjs', ['public/theme.mjs', 'text/javascript']);
staticFiles.set('/rail.mjs', ['public/rail.mjs', 'text/javascript']);
staticFiles.set('/auto-admit.mjs', ['public/auto-admit.mjs', 'text/javascript']);
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
export async function startApp({ port = 0, dataDir = 'data/mesh', registryPath, activitySource = 'disposable_fixture', serviceConfig = {}, inferenceConfig, inferenceTestReader, nodeProbeTestOptions, mindRecallTestOptions, localInferenceTestOptions, supervisedInferenceTestOptions, rookRuntimeTestOptions, nativeWorkerOptions, sessionTtlMs = 300000, sessionNow, relayEnabled = process.env.MESH_RELAY === '1' } = {}) {
  // Process configuration only. Standalone wins over ambient Relay enablement
  // and never constructs the native node reader or imports inference workers.
  const standalone = process.env.MESH_STANDALONE === '1';
  if (rookRuntimeTestOptions !== undefined && (!standalone || rookRuntimeTestOptions?.source !== 'disposable_fixture'
      || Object.keys(rookRuntimeTestOptions).some(key => !['source','identity','verifyIdentity','enabled','now','schedule','cancel','previousOwnerGone','ownerPid','transport'].includes(key))))
    throw Error('Rook runtime seam is synthetic standalone testing only.');
  if(mindRecallTestOptions!==undefined&&(!standalone||mindRecallTestOptions?.source!=='disposable_fixture'||Object.keys(mindRecallTestOptions).sort().join(',')!=='baseUrl,source,token'))throw Error('Mind recall seam is synthetic standalone testing only.');
  const mindRecall=mindRecallTestOptions?createMindRecallClient(mindRecallTestOptions):null;
  if (!Number.isSafeInteger(port) || port < 0 || port > 65535) throw new Error('A valid loopback port is required.');
  // The demo cap used to be 5 minutes, which is unusable for an operator: every pause
  // expired the session and the UI disabled itself. The manager underneath already
  // caps at 24 h (integer(ttlMs, 1, 86_400_000) in trial-session.mjs), so this only
  // lifts startApp's stricter demo bound. The default TTL is still 5 minutes.
  if (!Number.isSafeInteger(sessionTtlMs) || sessionTtlMs < 1 || sessionTtlMs > 86_400_000) throw new Error('Session lifetime must be 1..86400000 ms (24 h).');
  if (typeof dataDir !== 'string' || !/^(?:test[\\/]app03-[a-zA-Z0-9_-]+|data[\\/][a-zA-Z0-9_-]+)$/.test(dataDir)) throw new Error('An owned data/ directory or disposable test/app03- directory is required.');
  if (Object.keys(serviceConfig).length || inferenceConfig !== undefined) throw new Error('Live connections are outside APP03.');
  if (!['local_registry', 'disposable_fixture', 'frozen_manager_projection'].includes(activitySource)) throw new Error('Invalid activity source label.');
  if (registryPath && (typeof registryPath !== 'string' || /^[a-z][a-z0-9+.-]*:\/\//i.test(registryPath))) throw new Error('Invalid local registry path.');
  if (inferenceTestReader !== undefined && typeof inferenceTestReader !== 'function') throw new Error('Invalid test observation reader.');
  if (typeof relayEnabled !== 'boolean') throw new Error('Invalid Relay mode.');
  if (standalone) relayEnabled = false;
  // Trusted process injection, never HTTP/CLI/environment configuration. The
  // normal launcher supplies nothing, so production enrollment stays off.
  if (nativeWorkerOptions !== undefined && !relayEnabled)
    throw new Error('Native worker connections require Mesh team routing; standalone cannot enroll one.');
  const nativeWorker = createNativeWorkerBinding(nativeWorkerOptions);
  // A native enrollment may narrow its workspace to an owned subfolder, never
  // widen the existing qualification beyond this checkout or through a link.
  if(nativeWorker)await confinedPath(nativeWorker.workspace);
  // Trusted fixture seam only. No HTTP/CLI/environment adapter selection.
  if (localInferenceTestOptions !== undefined && (!localInferenceTestOptions ||
      Object.keys(localInferenceTestOptions).some(k => !['adapter', 'now'].includes(k)) ||
      localInferenceTestOptions.adapter?.source !== 'disposable_fixture')) throw new Error('Invalid inference fixture.');
  const observeSupervisor = createSupervisorObservation({enabled:!standalone && process.env.MESH_MODEL_OBSERVATION==='1'});
  let localInference = standalone
    ? createLocalInference({adapter:createDisabledLocalAdapter('STANDALONE_NOT_CONFIGURED')})
    : localInferenceTestOptions ? createLocalInference(localInferenceTestOptions) : createPendingNemotronInference();
  if(supervisedInferenceTestOptions && (supervisedInferenceTestOptions.qualification?.source!=='disposable_fixture'||Object.keys(supervisedInferenceTestOptions).some(k=>!['client','qualification','verifyResident','chatImpl','now'].includes(k))))throw Error('Invalid supervised model fixture');
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
  const release = releaseInfo(ROOT, dataDir);
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
  // No production identity/transport is enrolled here. Activation is a separate owner gate.
  const rookRuntime = store ? createRookRuntime({store: store.workroom.rook, flow: store.workroom.flow,
    board: () => store.workroom.list(), ...rookRuntimeTestOptions,
    enabled: process.env.MESH_SIMPLE_FLOW === '1' && rookRuntimeTestOptions?.enabled === true}) : null;
  let modelDatabase;
  if(!standalone && supervisedInferenceTestOptions && store){modelDatabase=new DatabaseSync(filename);localInference=createSupervisedInference({...supervisedInferenceTestOptions,operations:createModelOperationStore(modelDatabase)});}
  else if(!standalone && process.env.MESH_NEMOTRON_CONTROL==='1' && store){
    try{
      modelDatabase=new DatabaseSync(filename);const qualification=readNemotronQualification(modelDatabase,ROOT);
      if(!qualification)throw Error('Qualification required');
      const client=createNemotronClient(qualification),runtime=createNemotronRuntime({client});
      localInference=createSupervisedInference({operations:createModelOperationStore(modelDatabase),client,qualification,...runtime});
    }catch{modelDatabase?.close();modelDatabase=undefined;localInference=createPendingNemotronInference();}
  }
  // Gate G2 = A: the shell talks to the LIVE Relay over HTTP instead of driving a
  // modified copy of it. Staged behind an explicit flag so the default path is
  // byte-for-byte what it was; `child` stays until R8d deletes the fork.
  //
  // The token defaults to Relay's own gate key on this PC. Mesh holds it server-side
  // and never returns it to a browser; if the file is missing the bridge reports 503
  // rather than falling back to an unauthenticated call.
  const relayMode = String(process.env.MESH_RELAY_MODE ?? 'child').toLowerCase();
  const dshApprovals=relayEnabled && relayMode==='http'?createDshApprovalClient({origin:process.env.MESH_DSH_APPROVAL_ORIGIN||'http://127.0.0.1:4123',tokenFile:process.env.MESH_DSH_TOKEN_FILE||'D:/Dev/Onoes-Relay/.private/dsh.key'}):null;
  const baseRelay = relayMode === 'http'
    ? await createRelayHttpLink({
      baseUrl: process.env.MESH_RELAY_URL ?? 'http://127.0.0.1:8787',
      tokenFile: process.env.MESH_RELAY_TOKEN_FILE ?? 'D:\\Dev\\Onoes-Relay\\.private\\relay.key',
    })
    : await createRelayLink({ root: ROOT, directory, confine: confinedPath, store, enabled: relayEnabled });
  const relay=relayEnabled&&!standalone&&process.env.MESH_NIMS==='1'?withNims(baseRelay,{root:nativeWorker?.workspace??ROOT,workroom:store.workroom}):baseRelay;
  const teamRunner=relayEnabled&&!standalone?createTeamRunner({workroom:store.workroom,relay,root:nativeWorker?.workspace??ROOT,simpleFlow:process.env.MESH_SIMPLE_FLOW==='1',nativeWorker,nativeObserver:nativeWorker}):null;
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
  const connections = withRelaySource(createConnectionReader({ config: serviceConfig, inferenceReader: inference, ...(relayEnabled ? { relayReader: () => relay.snapshot() } : {}) }),relayMode==='http'?'live_relay_http':'isolated_relay');
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
        if (hosts.length !== 1 || req.headers.host !== `127.0.0.1:${server.address().port}`) {
          // Diagnosable on purpose: a 403 from here is a rewritten or duplicated Host,
          // and without the values the operator only sees an empty "Forbidden" page.
          try {
            console.log(JSON.stringify({ event: 'app_host_denied', ...requestAudit(req),
              hostCount: hosts.length,
              expected: `127.0.0.1:${server.address().port}`, at: new Date().toISOString() }));
          } catch { /* never break the response */ }
          deny(403);
          return;
        }
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
      if (route === '/api/release' && ['GET', 'HEAD'].includes(req.method)) return send(200, release);
      if (route === '/api/worker-activity' && ['GET', 'HEAD'].includes(req.method)) return send(200, await activity(configuredRegistry));
      if (route === '/api/service-connections' && ['GET', 'HEAD'].includes(req.method)) return send(200, await connections());
      if (route === '/api/inference-observation' && ['GET', 'HEAD'].includes(req.method)) return send(200, await inference());
      if (route.startsWith('/api/inference/')) {
        const sessionId = (req.headers.cookie ?? '').split(';').map(s => s.trim()).find(s => s.startsWith(SESSION_COOKIE_NAME + '='))?.slice(SESSION_COOKIE_NAME.length + 1);
        const admitted = () => Boolean(manager.authorize(sessionId, { mutation: true, csrfToken: req.headers['x-trial-csrf'] }));
        if (route === '/api/inference/status' && ['GET', 'HEAD'].includes(req.method)) return send(200, {...await localInference.status(), modelObservation:await observeSupervisor()});
        const receiptId = /^\/api\/inference\/receipt\/([0-9a-f-]{36})$/.exec(route)?.[1];
        if (receiptId && ['GET', 'HEAD'].includes(req.method)) return send(200, localInference.receipt(receiptId, sessionId));
        if (req.method !== 'POST') throw new TaskError(405, 'Method not allowed.');
        const action = /^\/api\/inference\/propose-(load|stop|unload|recover)$/.exec(route)?.[1];
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
      if(route==='/api/mind/status'&&req.method==='GET')return send(200,{configured:Boolean(mindRecall),source:mindRecall?'disposable_fixture':'not_configured'});
      if(route==='/api/mind/recall'&&req.method==='POST'){
        const body=recallInput(context.body);
        if(!mindRecall)throw new TaskError(503,'Onoes-Mind reader is not connected. Saved Workroom context remains available.');
        const result=await mindRecall.recall(body);if(!current())return;
        return send(200,result);
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
      if(route==='/api/workroom/claim-next'){
        if(req.method!=='POST')throw new TaskError(405,'Method not allowed.');
        if(!store||executionPersistenceFailed)throw new TaskError(503,'Workroom unavailable.');
        if(process.env.MESH_SIMPLE_FLOW!=='1')throw new TaskError(409,'Managed claims unavailable.');
        if(!context.body||Object.keys(context.body).length)throw new TaskError(400,'Scheduled claim accepts no overrides.');
        return send(200,{sweep:store.workroom.flow.scheduledSweep()});
      }
      if(route==='/api/workroom/rook'&&req.method==='GET'){
        if(!store||executionPersistenceFailed)throw new TaskError(503,'Workroom unavailable.');
        const connection=rookRuntime?.status()??{id:'rook',status:'unavailable',reason:'Rook state is unavailable.'};
        const tasks=store.workroom.list(),titles=new Map(tasks.map(t=>[t.id,t.title]));
        const assignmentHolds=writerQuiescenceBlockers(tasks).map(hold=>({...hold,title:titles.get(hold.taskId)}));
        return send(200,{schema:'mesh-rook-board/v1',observedAt:new Date().toISOString(),managedFlowEnabled:process.env.MESH_SIMPLE_FLOW==='1',sweep:{...store.workroom.flow.sweepStatus(),schedulerInstalled:connection.scheduler?.installed??false,schedulerEnabled:connection.scheduler?.enabled??false},connection,assignmentHolds,reports:rookRuntime?.reports()??[],cards:tasks.filter(t=>t.flow?.claim).map(t=>({taskId:t.id,title:t.title,stage:t.workroom.stage,flow:t.flow}))});
      }
      const workroomRoute = /^\/api\/workroom(?:\/([0-9a-f-]{36})(?:\/(message|progress|sync|apply-update|handoff|apply-review|approval|reconcile|plan|automation|apply-assignment|owner-review|intake|claim))?)?$/.exec(route);
      if (workroomRoute) {
        if (!store || executionPersistenceFailed) throw new TaskError(503, 'Workroom unavailable.');
        const id=workroomRoute[1];
        if(req.method==='GET' && !workroomRoute[2]) return send(200,id?{task:store.workroom.get(id),teamPolicy:{...automationPolicy(ROOT),...(process.env.MESH_SIMPLE_FLOW==='1'?{simpleFlow:true}:{})}}:{tasks:store.workroom.list(),teamPolicy:{...automationPolicy(ROOT),...(process.env.MESH_SIMPLE_FLOW==='1'?{simpleFlow:true}:{})}});
        if(!id) throw new TaskError(405,'Method not allowed.');
        if(workroomRoute[2]==='claim'&&req.method==='GET')return send(200,{flow:store.workroom.get(id).flow??null});
        if(workroomRoute[2]==='owner-review'&&req.method==='POST')return send(200,store.workroom.ownerReview(id,context.body));
        if(workroomRoute[2]==='claim'&&req.method==='POST'){if(process.env.MESH_SIMPLE_FLOW!=='1')throw new TaskError(409,'Managed claims unavailable.');return send(200,{flow:store.workroom.flow.claim(id,context.body)});}
        if(workroomRoute[2]==='intake'&&req.method==='POST'){if(process.env.MESH_SIMPLE_FLOW!=='1')throw new TaskError(409,'Managed intake unavailable.');if(JSON.stringify(context.body)!=='{}')throw new TaskError(400,'No intake overrides allowed.');return send(200,{flow:store.workroom.flow.enqueue(id)});}
        if(workroomRoute[2]==='apply-assignment'&&req.method==='POST')return send(200,store.workroom.applyAssignment(id,context.body));
        if(workroomRoute[2]==='automation'&&req.method==='POST'){if(!teamRunner)throw new TaskError(503,'Connected team runner unavailable.');const agents=['pause','close'].includes(context.body?.action)?[]:await relay.agents();if(!current())return;return send(200,teamRunner.action(id,context.body,agents));}
        if(workroomRoute[2]==='plan' && req.method==='PATCH'){
          if(context.body?.state==='locked'){
            const agents=await relay.agents();
            if(!current())return;
            if(agents.find(a=>a.id===context.body.workerId)?.backend==='codex')throw new TaskError(409,'Nims is read-only; choose a coding builder.');
            if([context.body.workerId,context.body.reviewerId].some(id=>!agents.some(a=>a.id===id&&a.conversation_id&&['hermes','a2a','codex'].includes(a.backend))))throw new TaskError(409,'Choose currently connected builder/reviewer peers. Tool/repository qualification still needs inspection.');
          }
          return send(200,store.workroom.savePlan(id,context.body));
        }
        if(workroomRoute[2]==='reconcile' && req.method==='POST'){
          if(!dshApprovals)throw new TaskError(503,'Native task reconciliation requires the live DeepSeek connection.');
          const body=context.body;
          if(!body || Object.keys(body).sort().join(',')!=='peerTaskId,sendId' || typeof body.sendId!=='string' || body.sendId.length>100)throw new TaskError(400,'Select the saved send and its exact native task.');
          const source=store.workroom.sendBinding(id,body.sendId);
          const outcome=await dshApprovals.readTaskOutcome(source,body.peerTaskId);
          if(!current())throw new TaskError(403,'Session expired. No reconciliation was recorded.');
          return send(200,store.workroom.recordSendOutcome(id,source.id,outcome));
        }
        if(workroomRoute[2]==='approval' && ['GET','POST'].includes(req.method)){
          const task=store.workroom.get(id);const source=task.messages.filter(m=>m.agentId==='dsh' && m.state==='accepted').at(-1);
          if(!source || !dshApprovals)return send(200,{supported:false,pending:null,reason:'No accepted DeepSeek handoff is available for approval.'});
          const scope={...source,taskId:id};
          if(req.method==='GET'){
            const state=await dshApprovals.inspect(scope);if(!current())throw new TaskError(403,'Session expired.');
            captureDshResult(store.workroom,id,source,state.task);
            return send(200,{supported:state.supported,pending:state.pending?{...state.pending,canApprove:state.pending.canApprove && store.workroom.canApproveHandoff(id,source.id)}:null,sendId:source.id,reason:state.reason||'',task:store.workroom.get(id)});
          }
          const body=context.body;
          if(!body || Object.keys(body).sort().join(',')!=='decision,requestId,sendId' || body.sendId!==source.id || typeof body.requestId!=='string' || body.requestId.length>100 || !['allow_once','reject'].includes(body.decision))throw new TaskError(400,'Select the exact displayed approval request.');
          if(body.decision==='allow_once' && !store.workroom.canApproveHandoff(id,source.id))throw new TaskError(409,'Task changed; this handoff cannot be approved. You can still deny it.');
          if(!current())throw new TaskError(403,'Session expired.');
          let result;
          try{result=await dshApprovals.decide(scope,body,()=>{
            if(!current())throw new TaskError(403,'Session expired.');
            const latest=store.workroom.get(id).messages.filter(m=>m.agentId==='dsh' && m.state==='accepted').at(-1);
            if(body.decision==='allow_once' && (latest?.id!==source.id || !store.workroom.canApproveHandoff(id,source.id)))throw new TaskError(409,'Task changed before the decision; approval refused.');
          });}catch(error){
            if(error.code!=='DSH_DECISION_UNCONFIRMED')throw error;
            if(!current())throw new TaskError(403,'Session expired. Refresh the existing request before another decision.');
            return send(202,{decisionStatus:'unconfirmed',task:store.workroom.get(id)});
          }
          if(!current())throw new TaskError(403,'Session expired after the decision. Refresh; do not approve a different request.');
          captureDshResult(store.workroom,id,source,result.result?.task);
          return send(200,{decision:result.decision,duplicate:result.duplicate,task:store.workroom.get(id)});
        }
        if(req.method==='PATCH' && !workroomRoute[2]) return send(200,{task:store.workroom.save(id,context.body)});
        if(req.method==='PATCH' && workroomRoute[2]==='progress')return send(200,{task:store.workroom.saveProgress(id,context.body)});
        if(req.method==='POST' && workroomRoute[2]==='apply-update')return send(200,store.workroom.applyAgentUpdate(id,context.body));
        if(req.method==='POST' && workroomRoute[2]==='apply-review')return send(200,store.workroom.applyAgentReview(id,context.body));
        if(req.method==='POST' && workroomRoute[2]==='handoff'){
          if(typeof relay.taskMessage!=='function')throw new TaskError(503,'Team handoffs require live Relay.');
          return send(200,await sendTaskHandoff({workroom:store.workroom,taskId:id,body:context.body,relay,admitted:current}));
        }
        if(req.method==='POST' && workroomRoute[2]==='sync'){
          if(!context.body || Object.keys(context.body).length)throw new TaskError(400,'Reply refresh accepts no configuration.');
          if(typeof relay.nativeRead!=='function')throw new TaskError(503,'Live Relay is unavailable.');
          return send(200,await syncTaskReplies({workroom:store.workroom,taskId:id,relay,admitted:current}));
        }
        if(req.method==='POST' && workroomRoute[2]==='message') {
          if(typeof relay.taskMessage!=='function') throw new TaskError(503,'Task messaging requires live Relay.');
          return send(200,await sendTaskMessage({workroom:store.workroom,taskId:id,body:context.body,relay,admitted:current}));
        }
        throw new TaskError(405,'Method not allowed.');
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
  catch (e) { await nativeWorker?.close().catch(()=>{});await teamRunner?.close();await rookRuntime?.close();await localInference.close?.();modelDatabase?.close();await relay.close(); store?.close(); throw e; }
  guard = createTrialHttpGuard({ manager, port: server.address().port });
  rookRuntime?.start();
  return { server, rookRuntime, mode: standalone ? 'standalone' : 'mesh', url: `http://127.0.0.1:${server.address().port}`, close: async () => {
    const closed = new Promise((resolve, reject) => server.close(e => e ? reject(e) : resolve()));
    server.closeAllConnections(); await closed;
    let nativeCloseFailed=false;
    try { await nativeWorker?.close(); } catch { nativeCloseFailed=true; }
    await rookRuntime?.close();await teamRunner?.close(); await relay.close(); await Promise.allSettled([...executions]);await localInference.close?.();modelDatabase?.close(); store?.close();
    if(nativeCloseFailed)throw new Error('Native worker transport cleanup could not be confirmed.');
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
