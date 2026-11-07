import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import {mockUI,bodyFor} from './app-ui-fixture.mjs';

const response = body => ({ status: 200, ok: true, text: async () => JSON.stringify(body) });
const flush = async () => { for (let i = 0; i < 10; i++) await new Promise(resolve => setImmediate(resolve)); };
const session = { csrfToken: 'c'.repeat(43), expiresAt: Date.now() + 60000 };
const fresh = { id: 'synthetic-task', title: 'Synthetic composition check', description: '', label: '', status: 'open', revision: 1 };
const pending = { ...fresh, revision: 2, proposal: { command: 'node lib/slow-command.mjs', cwd: '.' }, proposalStatus: 'pending', execution: null };
const running = { ...pending, revision: 3, proposalStatus: 'running', execution: { id: 'synthetic-current-run', state: 'running', result: null } };
const terminal = { ...running, revision: 4, proposalStatus: 'failed', execution: { ...running.execution, state: 'failed', result: {
  status: 'FAIL', cancelled: true, rootExitCode: 1, cleanupVerified: true, error: 'synthetic cancellation', stdout: 'synthetic captured start output', stderr: '' } } };
function harness(task, cancelResponse) {
  const timers = new Map(); let timerId = 0;
  const ui=mockUI({responder:async(route,options)=>{
    if (route.endsWith('/bootstrap')) return response(session);
    if (route === '/api/health') return response({ state: 'ok', persistence: 'sqlite', activity: { source: 'none' } });
    if (route === '/api/commands') return response({ commands: [{ id: 'm3-slow', ...pending.proposal }] });
    if (route.endsWith('/approve')) { task = running; return response({ task }); }
    if (route.endsWith('/cancel')) { await cancelResponse; task = terminal; return response({ task }); }
    if (route === '/api/tasks') return response({ tasks: [task] });
    if (route === '/api/tasks/synthetic-task') return response({ task });
    return response(bodyFor(route));
  }});
  ui.context.setTimeout=(fn,ms)=>{timers.set(++timerId,{fn,ms});return timerId;};
  ui.context.clearTimeout=id=>timers.delete(id);
  return {...ui,timers,run:code=>vm.runInContext(code,ui.context),setTask:value=>{task=value;}};
}
async function admit(ui) { ui.ids.get('demo-start').events.click(); await flush(); ui.ids.get('tasks').children[0].events.click(); await flush(); }

test('M3 UI selects a fresh task without an execution and keeps decisions disabled', async () => {
  const ui = harness(fresh); await admit(ui);
  assert.equal(ui.run('selected.id'), fresh.id); assert.equal(ui.ids.get('execution-result').textContent, 'Not run. No process result exists for this proposal.');
  assert.equal(ui.ids.get('propose-command').disabled, false);
  for (const decision of ['approve','deny','cancel']) assert.equal(ui.ids.get(`${decision}-command`).disabled, true);
});

test('M3 UI releases Approve lock, Cancel targets current run and stays honest pending actual response', async () => {
  let release; const cancellation = new Promise(resolve => { release = resolve; });
  const ui = harness(pending, cancellation); await admit(ui);
  ui.ids.get('approve-command').events.click(); await flush();
  assert.equal(ui.run('busy'), false); assert.equal(ui.ids.get('cancel-command').disabled, false);
  assert.equal(ui.ids.get('propose-command').disabled, true); assert.equal(ui.ids.get('approve-command').disabled, true);
  ui.ids.get('cancel-command').events.click(); await flush();
  assert.equal(ui.ids.get('cancel-command').disabled, true);
  assert.match(ui.ids.get('proposal-state').textContent, /Cancellation requested.*still running/);
  assert.match(ui.ids.get('execution-result').textContent, /State: running.*\nProcess result not yet known/);
  assert.doesNotMatch(ui.ids.get('execution-result').textContent, /Cancel request observed: true|Cleanup verified: true/);
  const request = ui.requests.find(r => r.route.endsWith('/cancel'));
  assert.equal(request.route, '/api/tasks/synthetic-task/cancel');
  assert.deepEqual(JSON.parse(request.options.body), { revision: 3, runId: 'synthetic-current-run' });
  release(); await flush();
  assert.match(ui.ids.get('execution-result').textContent, /State: failed\nCancel request observed: true\nExit code: 1\nCleanup verified: true/);
  assert.match(ui.ids.get('execution-result').textContent, /synthetic captured start output/);
  assert.match(ui.ids.get('proposal-state').textContent,/^Cancelled.*owned cleanup verified/);
  assert.equal(ui.ids.get('cancel-command').disabled, true); assert.equal(ui.ids.get('propose-command').disabled, false);
  ui.events.offline(); assert.equal(ui.ids.get('execution-result').textContent, '');
});

test('M3 UI reads a reopened running result without approving and ignores delayed cancel after private clearance', async () => {
  const ui = harness(running); await admit(ui);
  assert.equal(ui.ids.get('cancel-command').disabled, false);
  ui.setTask(terminal);
  const timer = [...ui.timers.entries()].find(([,timer]) => timer.ms === 200);
  ui.timers.delete(timer[0]); timer[1].fn(); await flush();
  assert.match(ui.ids.get('execution-result').textContent, /Cancel request observed: true/);
  assert.equal(ui.requests.some(r => r.route.endsWith('/approve')), false);
  let release; const delayed = new Promise(resolve => { release = resolve; });
  const cleared = harness(running, delayed); await admit(cleared);
  cleared.ids.get('cancel-command').events.click(); await flush(); cleared.events.offline();
  release(); await flush();
  assert.equal(cleared.ids.get('execution-result').textContent, ''); assert.equal(cleared.ids.get('tasks').children.length, 0);
  assert.equal(cleared.ids.get('cancel-command').disabled, true); assert.equal(cleared.run('selected'), undefined);
});


test('a cancellation flag without verified cleanup never claims the owned work stopped',async()=>{
  for(const cleanup of [false,undefined]){
    const task=structuredClone(terminal);task.execution.result.cleanupVerified=cleanup;
    const ui=harness(task);await admit(ui);
    assert.match(ui.ids.get('proposal-state').textContent,/Cancellation unconfirmed/);
    assert.doesNotMatch(ui.ids.get('proposal-state').textContent,/^Cancelled/);
    assert.match(ui.ids.get('proposal-state').textContent,/may still be running/);
    assert.match(ui.ids.get('execution-result').textContent,/Cancel request observed: true/);
  }
});
