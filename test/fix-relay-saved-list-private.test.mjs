import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import { readFile } from 'node:fs/promises';

const source = await readFile(new URL('../public/app.js', import.meta.url), 'utf8');
const html = await readFile(new URL('../public/index.html', import.meta.url), 'utf8');
const task = { id: '11111111-1111-4111-8111-111111111111', title: 'Private native task', description: 'Real transport is qualified separately', status: 'open', revision: 1 };
const flush = async () => { for (let i = 0; i < 12; i++) await new Promise(resolve => setImmediate(resolve)); };
function harness() {
  let focused, hold, tasks = [];
  const requests = [], events = {};
  class Element {
    constructor(id) { this.id = id; this.children = []; this.attrs = {}; this.events = {}; this.textContent = ''; this.value = ''; }
    setAttribute(k, v) { this.attrs[k] = v; } getAttribute(k) { return this.attrs[k]; }
    addEventListener(k, f) { this.events[k] = f; } append(...v) { this.children.push(...v); }
    replaceChildren(...v) { this.children = v; } reset() {} focus() { focused = this.id; }
  }
  const ids = new Map([...html.matchAll(/\bid="([^"]+)"/g)].map(m => [m[1], new Element(m[1])]));
  const tabs = [...html.matchAll(/<button role="tab" id="([^"]+)" aria-controls="([^"]+)"/g)].map(m => { const e = ids.get(m[1]); e.attrs['aria-controls'] = m[2]; return e; });
  const storage = new Map();
  const document = { visibilityState: 'visible', getElementById: id => ids.get(id), createElement: () => new Element(), querySelectorAll: s => s === '[role=tab]' ? tabs : s.startsWith('form ') ? [...ids.values()] : [], addEventListener: (k, f) => { events[k] = f; } };
  let instance = 0;
  const context = vm.createContext({ document, navigator: { onLine: true }, window: { location: { origin: 'http://127.0.0.1:12345' }, addEventListener: (k, f) => { events[k] = f; } },
    sessionStorage: { getItem: k => storage.get(k), setItem: (k, v) => storage.set(k, v), removeItem: k => storage.delete(k) }, crypto: { randomUUID: () => `frame-${++instance}` }, AbortController, setTimeout, clearTimeout, setInterval: () => {}, Date,
    fetch: async (route, options) => {
      requests.push({ route, options });
      let body = {}, status = 200;
      if (route.endsWith('bootstrap')) { status = 201; body = { csrfToken: 'b'.repeat(43), expiresAt: Date.now() + 60000 }; }
      if (route.endsWith('logout')) status = 204;
      if (route === '/api/health') body = { state: 'ok', persistence: 'sqlite', activity: { source: 'none' } };
      if (route === '/api/tasks') body = { tasks: [...tasks] };
      if (route === '/api/tasks/' + task.id) body = { task };
      if (route === '/api/relay/shell') body = { html: '<html><head></head>MOCK native document</html>' };
      const pending = hold?.route === route ? hold : undefined;
      if (pending) { hold = undefined; pending.started = true; if (pending.stage === 'fetch') await pending.promise; }
      return { status, ok: true, text: async () => { if (pending?.stage === 'text') await pending.promise; return JSON.stringify(body); } };
    } });
  vm.runInContext(source.replace(/export /g, ''), context);
  const open = async () => {
    ids.get('relay-open').events.click(); await flush();
    ids.get('relay-terminal').contentWindow = {};
  };
  const send = (overrides = {}) => events.message({ source: ids.get('relay-terminal').contentWindow, origin: 'http://127.0.0.1:12345', data: { type: 'mesh_relay_select', taskId: task.id, instance: `frame-${instance}` }, ...overrides });
  return { ids, events, context, document, requests, storage, open, send, focus: () => focused, tasks: value => { tasks = value; },
    hold: (route, stage) => { let release; hold = { route, stage, promise: new Promise(resolve => { release = resolve; }) }; const pending = hold; return { release, started: () => pending.started }; } };
}
async function admitted() {
  const ui = harness(); ui.ids.get('demo-start').events.click(); await flush(); ui.ids.get('tab-relay').events.click(); await ui.open(); return ui;
}
function privateCleared(ui) {
  assert.equal(ui.ids.get('tasks').children.length, 0);
  assert.equal(ui.ids.get('task-identity').textContent, '');
  assert.equal(ui.ids.get('edit-form').hidden, true);
  assert.equal(ui.ids.get('relay-terminal').srcdoc, '');
  assert.equal(ui.ids.get('relay-links').children.length, 0);
  assert.doesNotMatch(ui.ids.get('inspection-heading').textContent, /Private native task/);
}
test('Native handoff loads a fresh saved row, selects it and focuses inspection without extra writes', async () => {
  const ui = await admitted(); ui.tasks([task]); const before = ui.requests.length; ui.send(); await flush();
  assert.deepEqual(ui.requests.slice(before).map(r => r.route), ['/api/tasks/' + task.id, '/api/tasks']);
  assert.ok(ui.requests.slice(before).every(r => !r.options.method));
  assert.equal(ui.ids.get('tasks').children.length, 1);
  assert.equal(ui.ids.get('tasks').children[0].attrs['aria-pressed'], 'true');
  assert.match(ui.ids.get('task-identity').textContent, new RegExp(task.id));
  assert.equal(ui.focus(), 'inspection-heading');
  assert.equal(ui.ids.get('relay-terminal').hidden, true);
});
for (const route of ['/api/tasks/' + task.id, '/api/tasks']) for (const stage of ['fetch', 'text']) {
  for (const clearance of ['logout', 'offline', 'expiry', 'hidden', 'freeze', 'replacement']) {
    test(`Native pending ${route.endsWith(task.id) ? 'task' : 'list'} ${stage}: ${clearance} cannot revive private data`, async () => {
      const ui = await admitted(); ui.tasks([task]); const pending = ui.hold(route, stage); ui.send(); await flush(); assert.equal(pending.started(), true);
      if (clearance === 'logout') await vm.runInContext("api('/api/trial-session/logout', {method:'POST',body:'{}'}).finally(() => clearPrivate('Logout'))", ui.context);
      else if (clearance === 'expiry') vm.runInContext('demo.expiresAt = Date.now() - 1; proofAvailable()', ui.context);
      else if (clearance === 'hidden') { ui.document.visibilityState = 'hidden'; ui.events.visibilitychange(); }
      else if (clearance === 'freeze') ui.events.freeze();
      else ui.events.offline();
      privateCleared(ui);
      // Replacement session reads an empty board. The old response carries the
      // original private row and must not overwrite or clear the new proof.
      ui.tasks([]);
      if (clearance === 'replacement') {
        await vm.runInContext("demo = {csrfToken:'c'.repeat(43),expiresAt:Date.now()+60000}; admitted = true; loadTasks()", ui.context);
      }
      pending.release(); await flush(); privateCleared(ui);
      if (clearance === 'replacement') assert.equal(vm.runInContext('admitted && demo.csrfToken', ui.context), 'c'.repeat(43));
      assert.equal(ui.ids.get('tab-workroom').attrs['aria-selected'], 'false', 'Stale handoff cannot activate Workroom');
    });
  }
}
test('Foreign origin/source, stale frame, invalid type/id and a closed native frame cannot initiate a read', async () => {
  const ui = await admitted(); const before = ui.requests.length;
  ui.send({ source: {} }); ui.send({ origin: 'http://evil.test' });
  for (const data of [{ type: 'mesh_relay_select', instance: 'old', taskId: task.id }, { type: 'other', instance: 'frame-1', taskId: task.id }, { type: 'mesh_relay_select', instance: 'frame-1', taskId: '../private' }]) ui.send({ data });
  ui.ids.get('relay-close').events.click(); ui.send(); await flush(); assert.equal(ui.requests.length, before);
});
for (const replacement of ['close', 'new-document', 'new-window']) test(`Task response from ${replacement} native frame cannot select or fetch the board`, async () => {
  const ui = await admitted(); const pending = ui.hold('/api/tasks/' + task.id, 'text'); const before = ui.requests.length; ui.send(); await flush();
  if (replacement === 'close') ui.ids.get('relay-close').events.click();
  if (replacement === 'new-document') vm.runInContext("relayTerminalInstance = 'replacement'", ui.context);
  if (replacement === 'new-window') ui.ids.get('relay-terminal').contentWindow = {};
  pending.release(); await flush(); assert.equal(ui.ids.get('task-identity').textContent, '');
  assert.deepEqual(ui.requests.slice(before).map(r => r.route), ['/api/tasks/' + task.id]);
});
