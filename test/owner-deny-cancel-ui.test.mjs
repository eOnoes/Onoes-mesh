import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import { readFile } from 'node:fs/promises';

const source = await readFile(new URL('../public/app.js', import.meta.url), 'utf8');
const html = await readFile(new URL('../public/index.html', import.meta.url), 'utf8');
const task = { id: 'disposable-task', title: 'Decision check', description: '', label: '', status: 'open', revision: 2,
  proposal: { command: 'node --version', cwd: '.' }, proposalStatus: 'pending', execution: null };

function harness() {
  class Element {
    constructor() { this.children = []; this.attrs = {}; this.events = {}; this.value = ''; this.textContent = ''; }
    setAttribute(k, v) { this.attrs[k] = v; } getAttribute(k) { return this.attrs[k]; }
    addEventListener(k, v) { this.events[k] = v; } append(...els) { this.children.push(...els); }
    replaceChildren(...els) { this.children = els; } reset() {} focus() {}
  }
  const ids = new Map([...html.matchAll(/\bid="([^"]+)"/g)].map(m => [m[1], new Element()]));
  const context = vm.createContext({ document: { visibilityState: 'visible', addEventListener() {},
    getElementById: id => ids.get(id), createElement: () => new Element(),
    querySelectorAll: selector => selector.startsWith('form ') ? [...ids.values()] : [] },
    navigator: { onLine: true }, window: { addEventListener() {} },
    sessionStorage: { getItem() {}, setItem() {}, removeItem() {} }, AbortController, Date,
    setTimeout() { return 1; }, clearTimeout() {}, setInterval() {},
    fetch() { throw new Error('Rendering must not invoke execution APIs'); } });
  vm.runInContext(source.replace(/export /g, ''), context);
  vm.runInContext("admitted = true; demo = { csrfToken: 'c'.repeat(43), expiresAt: Date.now() + 60000 }; commands = [{ id: 'node-version', command: 'node --version', cwd: '.' }];", context);
  return { ids, select(value) { context.fixture = value; vm.runInContext('selectTask(fixture)', context); },
    run(code) { vm.runInContext(code, context); } };
}

test('explicit labels and denial explain no execution and no applicable cancellation/cleanup', () => {
  assert.match(html, /id="deny-command"[^>]*>Deny proposal \(do not run\)<\/button>/);
  assert.match(html, /id="cancel-command"[^>]*>Cancel running command<\/button>/);
  const ui = harness(); ui.select(task);
  assert.equal(ui.ids.get('deny-command').disabled, false);
  assert.equal(ui.ids.get('cancel-command').disabled, true);
  ui.select({ ...task, proposalStatus: 'denied' });
  assert.match(ui.ids.get('proposal-state').textContent, /no execution record created.*before execution.*not applicable/);
  assert.match(ui.ids.get('execution-result').textContent, /Not run.*denied before execution.*Cancellation and process cleanup: not applicable/);
  assert.doesNotMatch(ui.ids.get('execution-result').textContent, /Cancelled: true|Cleanup verified: true/);
  for (const id of ['approve-command', 'deny-command', 'cancel-command']) assert.equal(ui.ids.get(id).disabled, true);
});

test('terminal cancellation uses strict cleanup evidence; false, absent and nonboolean never claim verification', () => {
  const ui = harness();
  for (const [cleanupVerified, label, value] of [[true, 'verified', 'true'], [false, 'not verified', 'false'],
    [undefined, 'unknown', 'unknown'], [null, 'unknown', 'unknown'], ['true', 'unknown', 'unknown']]) {
    ui.select({ ...task, proposalStatus: 'failed', execution: { id: 'disposable-run', state: 'failed',
      result: { cancelled: true, cleanupVerified, rootExitCode: 1, error: 'cancelled', stdout: 'captured output', stderr: '' } } });
    assert.equal(ui.ids.get('proposal-state').textContent, `Cancelled — cleanup ${label}`);
    assert.match(ui.ids.get('execution-result').textContent, new RegExp(`Cleanup verified: ${value}\\n`));
    assert.equal(ui.ids.get('cancel-command').disabled, true);
  }
  ui.select({ ...task, proposalStatus: 'running', execution: { id: 'disposable-run', state: 'running', result: null } });
  assert.equal(ui.ids.get('cancel-command').disabled, false);
  assert.equal(ui.ids.get('deny-command').disabled, true);
  ui.run("cancellingRun = 'disposable-run'; selectTask(selected)");
  assert.match(ui.ids.get('proposal-state').textContent, /Cancellation requested.*cleanup pending.*still running/);
  assert.doesNotMatch(ui.ids.get('execution-result').textContent, /Cancelled: true|Cleanup verified: true/);
});

test('ordinary completion and interrupted unknown do not borrow positive cleanup claims', () => {
  const ui = harness();
  for (const cleanupVerified of [false, undefined]) {
    ui.select({ ...task, proposalStatus: 'completed', execution: { id: 'disposable-run', state: 'completed',
      result: { cancelled: false, cleanupVerified, rootExitCode: 0, stdout: '', stderr: '' } } });
    assert.doesNotMatch(ui.ids.get('proposal-state').textContent, /cleanup verified/);
  }
  ui.select({ ...task, proposalStatus: 'failed', execution: { id: 'disposable-run', state: 'failed',
    result: { status: 'UNKNOWN', cancelled: true, cleanupVerified: true } } });
  assert.match(ui.ids.get('proposal-state').textContent, /outcome unknown/);
  assert.match(ui.ids.get('execution-result').textContent, /Cleanup verified: unknown/);
  assert.doesNotMatch(ui.ids.get('proposal-state').textContent, /Cancelled — cleanup verified/);
});
