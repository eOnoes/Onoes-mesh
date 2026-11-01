import http from 'node:http';
import { access, mkdir, realpath, lstat, readFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { openTaskStore, TaskError } from './lib/task-store.mjs';
import { createConnectionReader, readFixedInference, normalizeInference } from './lib/service-connections.mjs';
import { createTrialSessionManager, createTrialHttpGuard, SESSION_COOKIE_NAME } from './lib/trial-session.mjs';

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
const staticFiles = new Map([['/', ['public/index.html', 'text/html']], ['/app.js', ['public/app.js', 'text/javascript']], ['/styles.css', ['public/styles.css', 'text/css']], ['/sw.js', ['public/sw.js', 'text/javascript']], ['/shell-cache-policy.mjs', ['public/shell-cache-policy-browser-v2.mjs', 'text/javascript']], ['/manifest.webmanifest', ['public/manifest.webmanifest', 'application/manifest+json']], ['/icon.svg', ['public/icon.svg', 'image/svg+xml']], ['/pwa-register.mjs', ['public/pwa-register.mjs', 'text/javascript']]]);
// Served from a new directory, so registered separately rather than added to the map
// literal above - test/pwa05.test.mjs pins that literal's exact text.
staticFiles.set('/shared/tokens.css', ['shared/tokens.css', 'text/css']);
staticFiles.set('/text-size.mjs', ['public/text-size.mjs', 'text/javascript']);
staticFiles.set('/agents.json', ['public/agents.json', 'application/json']);
staticFiles.set('/chat.json', ['public/chat.json', 'application/json']);
staticFiles.set('/chat.mjs', ['public/chat.mjs', 'text/javascript']);
staticFiles.set('/theme.mjs', ['public/theme.mjs', 'text/javascript']);
staticFiles.set('/rail.mjs', ['public/rail.mjs', 'text/javascript']);
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
export async function startApp({ port = 0, dataDir, registryPath, activitySource = 'disposable_fixture', serviceConfig = {}, inferenceConfig, inferenceTestReader, sessionTtlMs = 300000, sessionNow } = {}) {
  if (port !== 0) throw new Error('APP03 requires an assigned loopback port.');
  if (!Number.isSafeInteger(sessionTtlMs) || sessionTtlMs < 1 || sessionTtlMs > 300000) throw new Error('APP03 demo lifetime must be 1..300000 ms.');
  if (typeof dataDir !== 'string' || !/^test[\\/]app03-[a-zA-Z0-9_-]+$/.test(dataDir)) throw new Error('APP03 requires an owned synthetic data subtree.');
  if (Object.keys(serviceConfig).length || inferenceConfig !== undefined) throw new Error('Live connections are outside APP03.');
  if (!['local_registry', 'disposable_fixture', 'frozen_manager_projection'].includes(activitySource)) throw new Error('Invalid activity source label.');
  if (registryPath && (typeof registryPath !== 'string' || /^[a-z][a-z0-9+.-]*:\/\//i.test(registryPath))) throw new Error('Invalid local registry path.');
  if (inferenceTestReader !== undefined && typeof inferenceTestReader !== 'function') throw new Error('Invalid test observation reader.');
  const fixedInferenceConfig = inferenceConfig === undefined ? undefined : structuredClone(inferenceConfig);
  const directory = await confinedPath(dataDir);
  const filename = await confinedPath(path.join(directory, 'tasks.sqlite'));
  const configuredRegistry = registryPath ? await confinedPath(registryPath) : undefined;
  if (configuredRegistry && !configuredRegistry.startsWith(directory + path.sep)) throw new Error('Registry must be in the owned synthetic subtree.');
  const manager = createTrialSessionManager({ ttlMs: sessionTtlMs, maxSessions: 32, ...(sessionNow ? { now: sessionNow } : {}) });
  await mkdir(directory, { recursive: true });
  let store;
  try { store = openTaskStore(filename); } catch { /* Preserve invalid data; serve a visible failure. */ }
  // Server-only test seam; CLI and HTTP never accept a reader or module path.
  // Validate again at the HTTP seam, including deliberately hostile test readers.
  const inference = async () => {
    const nowIso = new Date().toISOString();
    try {
      const value = inferenceTestReader ? await inferenceTestReader({config:fixedInferenceConfig,nowIso}) : await readFixedInference({ modulePath: path.join(ROOT, 'lib/inference-observation.mjs'), confine: confinedPath, config: fixedInferenceConfig, nowIso });
      return normalizeInference(value,nowIso);
    } catch { return normalizeInference({schemaVersion:'mesh-inference-observation/v1',observedAt:nowIso,status:'unavailable',nodes:[],errors:[]},nowIso); }
  };
  const connections = createConnectionReader({ config: serviceConfig, inferenceReader: inference });
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
        'Content-Security-Policy': "default-src 'self'; connect-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'" });
      res.end(req.method === 'HEAD' ? undefined : type === 'application/json' ? JSON.stringify(body) : body);
    };
    try {
      const origin = `http://127.0.0.1:${server.address().port}`;
      const route = req.url;
      if (route === '/api/trial-session/bootstrap') { await guard.bootstrap(req, res); return; }
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
        url: origin, integrations: 'not_connected',
        activity: { adapter: await adapterStatus(), registry: configuredRegistry ? 'configured' : 'not_configured', source: configuredRegistry ? activitySource : 'none' }
      });
      if (route === '/api/worker-activity' && ['GET', 'HEAD'].includes(req.method)) return send(200, await activity(configuredRegistry));
      if (route === '/api/service-connections' && ['GET', 'HEAD'].includes(req.method)) return send(200, await connections());
      if (route === '/api/inference-observation' && ['GET', 'HEAD'].includes(req.method)) return send(200, await inference());
      const taskRoute = /^\/api\/tasks(?:\/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}))?$/.exec(route);
      if (!taskRoute) throw new TaskError(404, 'Route not found.');
      if (!store) throw new TaskError(503, 'Persistence unavailable. Existing data has been preserved.');
      const id = taskRoute[1];
      if (['GET', 'HEAD'].includes(req.method)) {
        if (!id) return send(200, { tasks: store.list() });
        const task = store.get(id); if (!task) throw new TaskError(404, 'Task not found.');
        return send(200, { task });
      }
      if (req.method === 'POST' && !id) { if (!current()) return; return send(201, { task: store.create(context.body) }); }
      if (req.method === 'PATCH' && id) { if (!current()) return; return send(200, { task: store.update(id, context.body) }); }
      throw new TaskError(405, 'Method not allowed.');
    } catch (e) {
      if (!res.headersSent) send(e instanceof TaskError ? e.status : 503, { error: e instanceof TaskError ? e.message : 'Local operation unavailable. Data has not been reset.' });
    }
  });
  server.requestTimeout = 10000;
  server.headersTimeout = 10000;
  server.on('clientError', (_error, socket) => {
    if (socket.writable) socket.end('HTTP/1.1 400 Bad Request\r\nCache-Control: no-store\r\nPragma: no-cache\r\nContent-Length: 0\r\nConnection: close\r\n\r\n');
    else socket.destroy();
  });
  try { await new Promise((resolve, reject) => { server.once('error', reject); server.listen(port, '127.0.0.1', resolve); }); }
  catch (e) { store?.close(); throw e; }
  guard = createTrialHttpGuard({ manager, port: server.address().port });
  return { server, url: `http://127.0.0.1:${server.address().port}`, close: async () => {
    const closed = new Promise((resolve, reject) => server.close(e => e ? reject(e) : resolve()));
    server.closeAllConnections(); await closed; store?.close();
  } };
}

// The bounded owned preview launcher is test/app03-preview.mjs (npm start).
