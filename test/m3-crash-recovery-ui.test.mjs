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
test('M3 Workroom explains unknown interruption, enables explicit new proposal only, and clears recovery on suspension', async () => {
  const ids = new Map([...html.matchAll(/\bid="([^"]+)"/g)].map(m => [m[1], new Element()]));
  const forms = [...ids.values()]; const documentEvents = {}; const storage = new Map(); const requests = [];
  const document = { visibilityState: 'visible', addEventListener: (name, fn) => { documentEvents[name] = fn; },
    getElementById: id => ids.get(id), createElement: () => new Element(),
    querySelectorAll: selector => selector.startsWith('form ') ? forms : [] };
  let task = { id: 'recovery-task', title: 'Interrupted', description: '', label: '', status: 'open', revision: 4,
    proposal: { command: 'node --version', cwd: '.' }, proposalStatus: 'failed',
    execution: { id: 'recovery-run', state: 'failed', finishedAt: '2026-10-03T00:00:00.000Z', result: {
      status: 'UNKNOWN', outcome: 'unknown', reason: 'server_restart', rootPid: null, rootExitCode: null,
      timedOut: null, cleanupVerified: null, stdout: null, stderr: null } } };
  const session = { csrfToken: 'r'.repeat(43), expiresAt: Date.now() + 60000 };
  const context = vm.createContext({ document, navigator: { onLine: true }, window: { addEventListener() {} },
    sessionStorage: { getItem: k => storage.get(k), setItem: (k, v) => storage.set(k, v), removeItem: k => storage.delete(k) },
    AbortController, setTimeout, clearTimeout, setInterval() {}, Date, fetch: async (route, options) => {
      requests.push({ route, options }); let body = {};
      if (route.endsWith('/bootstrap')) body = session;
      if (route === '/api/health') body = { state: 'ok', persistence: 'sqlite', activity: { source: 'none' } };
      if (route === '/api/commands') body = { commands: [{ id: 'node-version', command: 'node --version', cwd: '.' }] };
      if (route.endsWith('/proposal')) { task = { ...task, proposalStatus: 'pending', execution: null, revision: task.revision + 1 }; body = { task }; }
      if (route === '/api/tasks') body = { tasks: [task] };
      return { status: route.endsWith('/bootstrap') ? 201 : 200, ok: true, text: async () => JSON.stringify(body) };
    } });
  vm.runInContext(source.replace(/export /g, ''), context);
  const flush = async () => { for (let i = 0; i < 10; i++) await new Promise(resolve => setImmediate(resolve)); };
  ids.get('demo-start').events.click(); await flush(); ids.get('tasks').children[0].events.click();
  assert.match(ids.get('proposal-state').textContent, /Interrupted by server restart.*outcome unknown.*No automatic retry.*Save a new proposal/);
  const result = ids.get('execution-result').textContent;
  assert.match(result, /Run recovery-run\nState: failed\nOutcome: unknown/);
  for (const field of ['PID','Exit code','Cleanup verified','Timeout','stdout','stderr']) assert.ok(result.includes(field + ': unknown'));
  assert.doesNotMatch(result, /PASS|Completed|Cleanup verified: true|Exit code: 0|null/);
  assert.equal(ids.get('propose-command').disabled, false);
  assert.equal(ids.get('approve-command').disabled, true); assert.equal(ids.get('deny-command').disabled, true);
  assert.equal(requests.filter(request => /\/approve$|\/proposal$/.test(request.route)).length, 0);
  ids.get('proposal-form').events.submit({ preventDefault() {} }); await flush();
  const mutations = requests.filter(request => request.options.method === 'POST' && !request.route.endsWith('/bootstrap'));
  assert.equal(mutations.length, 1); assert.equal(mutations[0].route, '/api/tasks/recovery-task/proposal');
  assert.deepEqual(JSON.parse(mutations[0].options.body), { proposal: { command: 'node --version', cwd: '.' }, revision: 4 });
  assert.equal(ids.get('approve-command').disabled, false); assert.match(ids.get('proposal-state').textContent, /Pending · not executed/);
  assert.equal(ids.get('execution-result').textContent, 'Pending · not run. No process result exists for this proposal.');
  document.visibilityState = 'hidden'; documentEvents.visibilitychange();
  assert.equal(ids.get('tasks').children.length, 0); assert.equal(ids.get('execution-result').textContent, '');
  assert.equal(ids.get('proposal-state').textContent, ''); assert.equal(storage.size, 0);
});
