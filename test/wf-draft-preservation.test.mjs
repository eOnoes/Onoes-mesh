import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import { readFile } from 'node:fs/promises';

const source = await readFile(new URL('../public/app.js', import.meta.url), 'utf8');
const html = await readFile(new URL('../public/index.html', import.meta.url), 'utf8');
const fields = ['title', 'description', 'label'];
const saved = { id: 'task-a', title: 'Saved title', description: 'Saved description', label: 'Saved label',
  status: 'open', revision: 3, proposal: { command: 'node lib/slow-command.mjs', cwd: '.' },
  proposalStatus: 'running', execution: { id: 'run-a', state: 'running', result: null } };
const draft = { title: 'Unsaved title', description: 'Unsaved description', label: 'Unsaved label' };
const flush = () => new Promise(resolve => setImmediate(resolve));
function deferred() { let resolve; const promise = new Promise(r => { resolve = r; }); return { promise, resolve }; }

function harness() {
  let ids;
  class Element {
    constructor() { this.children = []; this.attrs = {}; this.events = {}; this.value = ''; this.textContent = ''; }
    setAttribute(k, v) { this.attrs[k] = v; } getAttribute(k) { return this.attrs[k]; }
    addEventListener(k, v) { this.events[k] = v; } append(...els) { this.children.push(...els); }
    replaceChildren(...els) { this.children = els; } focus() {}
    reset() { for (const field of fields) ids.get('edit-' + field).value = ''; }
  }
  ids = new Map([...html.matchAll(/\bid="([^"]+)"/g)].map(m => [m[1], new Element()]));
  const timers = new Map(); let timerId = 0; const calls = []; const queue = [];
  const context = vm.createContext({ document: { visibilityState: 'visible', addEventListener() {},
    getElementById: id => ids.get(id), createElement: () => new Element(),
    querySelectorAll: selector => selector.startsWith('form ') ? [...ids.values()] : [] },
    navigator: { onLine: true }, window: { addEventListener() {} },
    sessionStorage: { getItem() {}, setItem() {}, removeItem() {} }, AbortController, Date,
    setTimeout(fn, ms) { const id = ++timerId; timers.set(id, { fn, ms }); return id; },
    clearTimeout(id) { timers.delete(id); }, setInterval() {},
    async fetch(route, options) {
      calls.push({ route, method: options.method ?? 'GET', body: options.body && JSON.parse(options.body) });
      assert.ok(queue.length, 'Unexpected request: ' + route);
      const item = queue.shift(); return { status: item.status ?? 200, ok: (item.status ?? 200) < 400,
        text: async () => item.bodyPromise ? await item.bodyPromise : JSON.stringify(item.body) };
    } });
  vm.runInContext(source.replace(/export /g, ''), context);
  vm.runInContext("admitted = true; demo = { csrfToken: 'c'.repeat(43), expiresAt: Date.now() + 60000 }; commands = [{ id: 'm3-slow', command: 'node lib/slow-command.mjs', cwd: '.' }];", context);
  const run = code => vm.runInContext(code, context);
  return { ids, calls, queue, run,
    select(task) { context.fixture = structuredClone(task); run('selectTask(fixture)'); },
    type(values = draft) { for (const field of fields) { const el = ids.get('edit-' + field); el.value = values[field]; el.events.input?.({ target: el }); } },
    values() { return Object.fromEntries(fields.map(f => [f, ids.get('edit-' + f).value])); },
    async poll(...items) {
      queue.push(...items); const timer = [...timers].find(([, t]) => t.ms === 200);
      assert.ok(timer, 'The actual running watch must schedule a poll'); timers.delete(timer[0]); timer[1].fn(); await flush();
    },
    async event(id, kind) { ids.get(id).events[kind]({ preventDefault() {} }); await flush(); }
  };
}

test('actual watch preserves all three drafts through two consumed running bodies and terminal list refresh; Save uses current revision once', async () => {
  const ui = harness(); ui.select(saved); ui.type();
  for (const revision of [4, 5]) {
    const body = deferred(); await ui.poll({ bodyPromise: body.promise });
    assert.deepEqual(ui.values(), draft);
    body.resolve(JSON.stringify({ task: { ...saved, revision } })); await flush();
    assert.deepEqual(ui.values(), draft);
    assert.match(ui.ids.get('task-identity').textContent, new RegExp('revision ' + revision));
    assert.equal(ui.ids.get('cancel-command').disabled, false);
  }
  const terminal = { ...saved, revision: 6, proposalStatus: 'completed', execution: { id: 'run-a', state: 'completed',
    result: { rootExitCode: 0, cleanupVerified: true, cancelled: false, stdout: 'Real result fixture', stderr: '' } } };
  await ui.poll({ body: { task: terminal } }, { body: { tasks: [terminal] } });
  assert.deepEqual(ui.values(), draft);
  assert.match(ui.ids.get('execution-result').textContent, /Real result fixture/);
  assert.equal(ui.ids.get('cancel-command').disabled, true);
  const persisted = { ...terminal, ...draft, revision: 7 };
  ui.queue.push({ body: { task: persisted } }, { body: { tasks: [persisted] } });
  await ui.event('edit-form', 'submit');
  const writes = ui.calls.filter(c => c.method === 'PATCH');
  assert.equal(writes.length, 1); assert.deepEqual(writes[0].body, { ...draft, status: 'open', revision: 6 });
  assert.deepEqual(ui.values(), draft); assert.match(ui.ids.get('message').textContent, /Task saved.*revision 7/);
});

test('clean fields update passively; explicit Reload and another task replace drafts; conflict never reports success', async () => {
  const ui = harness(); ui.select(saved); ui.type({ ...draft, label: saved.label });
  const changed = { ...saved, revision: 4, label: 'Updated saved label' };
  await ui.poll({ body: { task: changed } });
  assert.deepEqual(ui.values(), { ...draft, label: changed.label });
  ui.queue.push({ status: 409, body: { error: 'Task revision conflict' } });
  await ui.event('edit-form', 'submit');
  assert.match(ui.ids.get('message').textContent, /Task revision conflict/);
  assert.doesNotMatch(ui.ids.get('message').textContent, /Task saved/);
  assert.deepEqual(ui.values(), { ...draft, label: changed.label });
  ui.queue.push({ body: { task: changed } }, { body: { tasks: [changed] } });
  await ui.event('reload-task', 'click'); assert.deepEqual(ui.values(), Object.fromEntries(fields.map(f => [f, changed[f]])));
  ui.type(); ui.select({ ...changed, id: 'task-b', title: 'Other task', execution: null, proposalStatus: 'pending' });
  assert.equal(ui.values().title, 'Other task'); assert.equal(ui.values().description, saved.description);
});

for (const fence of ['privacy', 'replacement-session', 'task', 'run']) test('consumed delayed poll cannot restore drafts across ' + fence + ' fence', async () => {
  const ui = harness(); ui.select(saved); ui.type(); const body = deferred(); await ui.poll({ bodyPromise: body.promise });
  if (fence === 'privacy' || fence === 'replacement-session') {
    ui.run("clearPrivate('Session lost')"); assert.deepEqual(ui.values(), { title: '', description: '', label: '' });
    if (fence === 'replacement-session') {
      ui.run("admitted = true; demo = { csrfToken: 'd'.repeat(43), expiresAt: Date.now() + 60000 }");
      ui.select({ ...saved, id: 'task-b', title: 'New session task', execution: null, proposalStatus: 'pending' }); ui.type({ ...draft, title: 'New session draft' });
    }
  } else {
    ui.select({ ...saved, id: fence === 'task' ? 'task-b' : saved.id,
      title: 'New selection', execution: { ...saved.execution, id: 'run-b' } }); ui.type({ ...draft, title: 'New selection draft' });
  }
  const before = ui.values(); body.resolve(JSON.stringify({ task: { ...saved, revision: 99 } })); await flush();
  assert.deepEqual(ui.values(), before); assert.doesNotMatch(ui.ids.get('task-identity').textContent, /revision 99/);
});
