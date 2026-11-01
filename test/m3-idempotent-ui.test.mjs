import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import { readFile } from 'node:fs/promises';

const source = await readFile(new URL('../public/app.js', import.meta.url), 'utf8');
const html = await readFile(new URL('../public/index.html', import.meta.url), 'utf8');
class Element {
  constructor() { this.children = []; this.attrs = {}; this.events = {}; this.textContent = ''; this.value = ''; this.disabled = false; }
  setAttribute(k, v) { this.attrs[k] = v; } getAttribute(k) { return this.attrs[k]; }
  addEventListener(k, f) { this.events[k] = f; } append(...els) { this.children.push(...els); }
  replaceChildren(...els) { this.children = els; } reset() {} focus() {}
}
function uiHarness({ stored, responder } = {}) {
  const ids = new Map([...html.matchAll(/\bid="([^"]+)"/g)].map(m => [m[1], new Element()]));
  const forms = ['create-title','create-description','create-label','edit-title','edit-description','edit-label','toggle-status','reload-task','refresh'].map(id => ids.get(id));
  const tabs = [...html.matchAll(/<button role="tab" id="([^"]+)" aria-controls="([^"]+)"/g)].map(m => { const el = ids.get(m[1]); el.attrs['aria-controls'] = m[2]; return el; });
  const groups = new Map(['.activity-workers','.activity-state, .activity-source','.service-connections','.service-status','.inference-state','.inference-errors','.activity-source','.activity-state'].map(s => [s, [new Element()]]));
  const storage = new Map(stored ? [['mesh.synthetic-demo.proof.v1', JSON.stringify(stored)]] : []);
  const requests = []; const events = {}; const intervals = []; const documentEvents = {}; const document = { visibilityState: 'visible', addEventListener: (name, fn) => { documentEvents[name] = fn; }, getElementById: id => ids.get(id), createElement: () => new Element(), querySelectorAll: s => s === '[role=tab]' ? tabs : s.startsWith('form ') ? forms : groups.get(s) ?? [] };
  const context = vm.createContext({ document, navigator: { onLine: true }, window: { addEventListener: (e, f) => { events[e] = f; } }, sessionStorage: { getItem: k => storage.get(k), setItem: (k, v) => storage.set(k, v), removeItem: k => storage.delete(k) }, AbortController, setTimeout, clearTimeout, setInterval: f => { intervals.push(f); }, Date, fetch: async (route, options) => { requests.push({ route, options }); return responder ? responder(route, options) : response(200, {}); } });
  vm.runInContext(source.replace(/export /g, ''), context);
  return { ids, forms, tabs, storage, requests, events, documentEvents, document, intervals, context };
}
const response = (status, body) => ({ status, ok: status >= 200 && status < 300, text: async () => JSON.stringify(body) });
const flush = async () => { for (let i = 0; i < 10; i++) await new Promise(r => setImmediate(r)); };
function bodyFor(route) {
  if (route === '/api/tasks') return { tasks: [] };
  if (route === '/api/health') return { state: 'ok', persistence: 'sqlite', activity: { source: 'none' } };
  return {};
}

const storedTask = { id: 'synthetic-task', title: 'Saved result', description: '', label: '', status: 'open', revision: 4,
  proposal: { command: 'node --version', cwd: '.' }, proposalStatus: 'completed',
  execution: { id: 'synthetic-run', state: 'completed', result: { rootExitCode: 0, cleanupVerified: true, error: null,
    stdout: 'synthetic captured output', stderr: '' } } };
const session = { csrfToken: 'm'.repeat(43), expiresAt: Date.now() + 60000 };
function readBody(route) {
  if (route === '/api/tasks') return { tasks: [storedTask] };
  if (route === '/api/commands') return { commands: [{ id: 'node-version', command: 'node --version', cwd: '.' }] };
  return bodyFor(route);
}
async function admittedUI() {
  const ui = uiHarness({ responder: route => response(route.endsWith('bootstrap') ? 201 : 200,
    route.endsWith('bootstrap') ? session : readBody(route)) });
  ui.ids.get('demo-start').events.click(); await flush();
  ui.ids.get('tasks').children[0].events.click();
  assert.match(ui.ids.get('execution-result').textContent, /synthetic-run/);
  return ui;
}

test('M3 UI: ordinary navigation clears private state, preserves nonce only, rechecks admission, reads existing run without approval', async () => {
  const ui = await admittedUI();
  ui.events.beforeunload(); ui.events.pagehide({ persisted: false });
  ui.document.visibilityState = 'hidden'; ui.documentEvents.visibilitychange();
  assert.equal(ui.ids.get('tasks').children.length, 0); assert.equal(ui.ids.get('execution-result').textContent, '');
  assert.equal(ui.ids.get('refresh').disabled, true);
  assert.equal(ui.storage.size, 1);
  const stored = JSON.parse([...ui.storage.values()][0]); assert.deepEqual(stored, session);
  assert.deepEqual(Object.keys(stored).sort(), ['csrfToken','expiresAt']);
  let release; let first = true; const health = new Promise(resolve => { release = resolve; });
  const reloaded = uiHarness({ stored, responder: async route => {
    if (first) { first = false; assert.equal(route, '/api/health'); await health; }
    return response(200, readBody(route));
  } });
  assert.equal(reloaded.ids.get('tasks').children.length, 0); assert.equal(reloaded.ids.get('refresh').disabled, true);
  reloaded.events.pageshow({ persisted: false }); release(); await flush();
  assert.equal(reloaded.ids.get('refresh').disabled, false);
  reloaded.ids.get('tasks').children[0].events.click();
  assert.match(reloaded.ids.get('execution-result').textContent, /Run synthetic-run[\s\S]*synthetic captured output/);
  assert.equal(reloaded.ids.get('approve-command').disabled, true);
  assert.equal(reloaded.requests.every(r => !r.options.method || r.options.method === 'GET'), true);
  ui.events.pageshow({ persisted: true });
  assert.equal(ui.storage.size, 0); assert.equal(ui.ids.get('execution-result').textContent, '');
});

test('M3 UI: suspension, restored pages and cancelled navigation keep privacy clearance; invalidated server proof cannot reopen a run', async () => {
  for (const mode of ['hidden', 'restored', 'cancelled-navigation', 'freeze']) {
    const ui = await admittedUI();
    if (mode === 'cancelled-navigation') ui.events.beforeunload();
    if (mode === 'hidden' || mode === 'cancelled-navigation') {
      ui.document.visibilityState = 'hidden'; ui.documentEvents.visibilitychange();
    } else if (mode === 'freeze') ui.documentEvents.freeze();
    else { ui.events.beforeunload(); ui.events.pagehide({ persisted: true }); }
    assert.equal(ui.storage.size, 0); assert.equal(ui.ids.get('execution-result').textContent, '');
    assert.equal(ui.ids.get('tasks').children.length, 0);
  }
  const rejected = uiHarness({ stored: session, responder: () => response(401, {}) });
  await flush(); assert.equal(rejected.storage.size, 0); assert.equal(rejected.ids.get('tasks').children.length, 0);
  assert.equal(rejected.requests.length, 1); assert.equal(rejected.requests[0].route, '/api/health');
});
