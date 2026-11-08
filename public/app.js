import {createAdmissionPeers} from './session-entry.mjs';
import { renderAgentWorkspace } from './agent-workspace.mjs';
import { createMindWorkspace } from './mind-workspace.mjs';
import { createRelayChat } from './chat.mjs';
let clearWorkroom = () => {};
const $ = id => document.getElementById(id);
const tabs = [...document.querySelectorAll('[role=tab]')];
function activate(tab, focus = false) {
  for (const t of tabs) {
    const selected = t === tab;
    t.setAttribute('aria-selected', String(selected)); t.tabIndex = selected ? 0 : -1;
    $(t.getAttribute('aria-controls')).hidden = !selected;
  }
  if (focus) tab.focus();
}
for (const tab of tabs) {
  tab.addEventListener('click', () => activate(tab));
  tab.addEventListener('keydown', e => {
    let index = tabs.indexOf(tab);
    if (e.key === 'ArrowRight' || e.key === 'ArrowDown') index = (index + 1) % tabs.length;
    else if (e.key === 'ArrowLeft' || e.key === 'ArrowUp') index = (index + tabs.length - 1) % tabs.length;
    else if (e.key === 'Home') index = 0;
    else if (e.key === 'End') index = tabs.length - 1;
    else return;
    e.preventDefault(); activate(tabs[index], true);
  });
}
// Workspace links select a panel only; they never admit a session or dispatch work.
function activateLinkedWorkspace() {
  const name = /^#(overview|relay|inference|workroom|agent|mind|control)$/.exec(window.location?.hash ?? '')?.[1];
  if (name) activate($('tab-' + name));
}
activateLinkedWorkspace();
window.addEventListener('hashchange', activateLinkedWorkspace);
const menuMedia = typeof window.matchMedia === 'function'
  ? window.matchMedia('(max-width: 760px)')
  : { matches: false, addEventListener() {} };
function setMenu(open) {
  const narrow = menuMedia.matches;
  // The drawer opens at EVERY width, not just under 760px.
  //
  // It used to be `open && narrow`, because Mesh was a two-column grid on desktop with a
  // permanent sidebar. The design is now an 820px window whose navigation slides in over
  // the content - and all seven tabs live inside that nav, so gating it on viewport width
  // left a desktop user with no navigation at all. When wide, the inline styles below are
  // removed and the `body.menu-open .nav-wrap` rule in public/styles.css does the work.
  const show = open;
  document.body.classList.toggle('menu-open', show);
  const opener = $('menu-open');
  if (opener) opener.setAttribute('aria-expanded', String(show));
  const scrim = $('menu-scrim');
  if (scrim) scrim.hidden = !show;
  const nav = document.querySelector('.nav-wrap');
  if (nav) {
    if (!narrow) {
      nav.style.removeProperty('left');
      nav.style.removeProperty('transform');
    } else if (show) {
      nav.style.setProperty('left', '0px', 'important');
      nav.style.setProperty('transform', 'none', 'important');
    } else {
      nav.style.setProperty('left', '-110vw', 'important');
      nav.style.setProperty('transform', 'none', 'important');
    }
  }
}
menuMedia.addEventListener('change', () => setMenu(false));
const menuOpen = $('menu-open');
const menuClose = $('menu-close');
const menuScrim = $('menu-scrim');
if (menuOpen) menuOpen.addEventListener('click', () => setMenu(true));
if (menuClose) menuClose.addEventListener('click', () => setMenu(false));
if (menuScrim) menuScrim.addEventListener('click', () => setMenu(false));
for (const tab of tabs) tab.addEventListener('click', () => setMenu(false));
let selected; let busy = false; let commands = []; let staleSelection = false;
let watchedRun; let cancellingRun;
let relaySnapshot;
let relayTerminalInstance;
let localModelObservation;
let localInferenceSnapshot; let localInferenceProposal; let localInferenceReceivedAt = 0;
// Only task-session nonce + expiry and the intentional-lock preference survive refresh. Cookie IDs,
// actors, grants, tasks and API bodies never enter browser storage.
const nonceKey = 'mesh.synthetic-demo.proof.v1';
let demo; let admitted = false; let generation = 0;
let sessionRecoveryError = '';
let automaticEntry, automaticAccess=false, workspaceLocked=false;
try { workspaceLocked=sessionStorage.getItem('mesh.workspace.locked.v1')==='1'; } catch {}
let savedDemo;
// Privacy clearance runs in lifecycle handlers; it does not depend on a timer.
let lifecycleSuspended = document.visibilityState === 'hidden';
const admissionPeers = typeof BroadcastChannel==='function' ? createAdmissionPeers({readProof:()=>admitted&&!workspaceLocked&&!lifecycleSuspended&&proofAvailable()?demo:null}) : null;
let navigationProof; let normalNavigation = false;
const relayChat = createRelayChat({request:api});
const mindWorkspace = createMindWorkspace({root:$('mind-workspace'),request:api,openTask:id=>{
  if (!admitted || !proofAvailable()) return;
  activate($('tab-workroom'));
  window.dispatchEvent(new CustomEvent('mesh-open-task',{detail:{id}}));
}});
try {
  const raw = sessionStorage.getItem(nonceKey);
  if (raw && raw.length <= 128) {
    const value = JSON.parse(raw);
    if (value && Object.keys(value).sort().join(',') === 'csrfToken,expiresAt' && typeof value.csrfToken === 'string' && /^[A-Za-z0-9_-]{43}$/.test(value.csrfToken) && Number.isSafeInteger(value.expiresAt) && value.expiresAt > Date.now() && value.expiresAt <= Date.now() + 86400000) savedDemo = value;
  }
} catch { /* An invalid or inaccessible stored demo is never admission. */ }
function applyLocalStubs() {
  if (admitted) return;
  const relayState = document.getElementById('relay-state');
  if (relayState) relayState.textContent = 'SYNTHETIC. No Relay conversation. A real message is not sent.';
  // When the gate has admitted this browser the composer talks to Relay for real, so it
  // must not be stubbed out. Without the gate cookie (unit tests, browser fixtures) the
  // old synthetic behaviour is unchanged.
  const gated = (() => { try { return String(document.cookie || '').includes('mesh_gate=1'); } catch { return false; } })();
  const liveComposer = new Set(['relay-send','relay-text','relay-message-id']);
  for (const id of ['relay-open','relay-close','relay-reconnect','relay-send','relay-new','relay-text','relay-message-id','node-probes-refresh']) {
    const el = document.getElementById(id);
    if (el) el.disabled = !(gated && liveComposer.has(id));
  }
  const refreshNodes = document.getElementById('node-probes-refresh');
  if (refreshNodes) refreshNodes.textContent = 'Refresh nodes (not on this PC)';
  for (const el of document.querySelectorAll('.service-status')) el.textContent = 'SYNTHETIC. Not connected on this PC.';
}
function controls() {
  mindWorkspace.setAvailable(!busy && !lifecycleSuspended && admitted && navigator.onLine);
  document.querySelectorAll('form button, form input, form textarea, form select, #refresh, #agent-refresh, #node-probes-refresh').forEach(el => { el.disabled = busy || lifecycleSuspended || !admitted || !navigator.onLine; });
  if (nodeProbeSnapshot?.status === 'not_configured') $('node-probes-refresh').disabled = true;
  $('node-probes-refresh').textContent = nodeProbeSnapshot?.status === 'not_configured' ? 'Machine checks unavailable in this instance' : 'Check machine status';
  const executing = ['approved','running'].includes(selected?.proposalStatus);
  $('propose-command').disabled = busy || lifecycleSuspended || !admitted || !navigator.onLine || !selected || !commands.length || executing || staleSelection;
  $('proposal-command').disabled = $('propose-command').disabled;
  for (const id of ['approve-command','deny-command']) $(id).disabled = busy || lifecycleSuspended || !admitted || !navigator.onLine || staleSelection || selected?.proposalStatus !== 'pending';
  $('cancel-command').disabled = busy || lifecycleSuspended || !admitted || !navigator.onLine || staleSelection || selected?.proposalStatus !== 'running';
  $('demo-start').disabled = busy || lifecycleSuspended || admitted || !navigator.onLine;
  $('demo-start').hidden=automaticAccess&&admitted;
  $('demo-start').textContent=(automaticAccess||workspaceLocked)?'Reconnect workspace':'Start local session';
  $('demo-end').textContent=automaticAccess?'Lock workspace':'End local session';
  for (const workspace of ['workroom', 'relay']) {
    $(workspace + '-session-recovery').hidden = admitted;
    $(workspace + '-session-start').disabled = $('demo-start').disabled;
    $(workspace + '-session-state').textContent = $('demo-state').textContent + (sessionRecoveryError ? ' ' + sessionRecoveryError : '') + (automaticAccess?' Use Reconnect workspace if needed. Saved tasks are safe.':' Choose Start fresh local session to verify access with the server. Saved tasks have not been deleted.');
  }
  $('demo-end').disabled = busy || lifecycleSuspended || !demo || !navigator.onLine;
  for (const id of ['relay-open','relay-close','relay-reconnect']) $(id).disabled = busy || lifecycleSuspended || !admitted || !navigator.onLine;
  for (const id of ['relay-send','relay-text','relay-message-id','relay-new']) $(id).disabled = busy || lifecycleSuspended || !admitted || !navigator.onLine || relaySnapshot?.status !== 'fresh';
  $('relay-new').disabled = true;
  applyLocalStubs();
  localInferenceControls();
  relayChat.setAvailable(!lifecycleSuspended && admitted && navigator.onLine,busy);
}
function clearPrivate(reason) {
  relayChat.clear();
  mindWorkspace.clear();
  clearWorkroom();
  generation++; admitted = false; try { $('demo-start').classList.remove('ok'); } catch { } demo = undefined; selected = undefined; staleSelection = false;
  watchedRun = undefined; cancellingRun = undefined;
  localInferenceSnapshot = undefined; localInferenceProposal = undefined;
  $('local-inference-prompt').value = ''; $('local-inference-response').textContent = '';
  $('local-inference-receipt').textContent = ''; renderLocalInference(undefined);
  try { sessionStorage.removeItem(nonceKey); } catch { /* Memory-only demo remains possible. */ }
  $('create-form').reset(); $('edit-form').reset(); $('edit-form').hidden = true; $('no-selection').hidden = false;
  commands = []; $('proposal-form').reset(); $('proposal-form').hidden = true;
  $('proposal-command').replaceChildren(); $('proposal-state').textContent = ''; $('proposal-value').textContent = '';
  $('execution-result').textContent = '';
  $('inspection-heading').textContent = 'Inspect and edit';
  $('result-heading').textContent = 'Command proposal and execution result';
  for (const id of ['task-identity','task-status']) $(id).textContent = '';
  for (const id of ['total-count','open-count','done-count']) $(id).textContent = 'Locked';
  $('tasks').replaceChildren(); $('empty-board').textContent = 'Start a local task session to view saved tasks.';
  $('app-state').textContent = 'Private app status unavailable.';
  $('release-state').textContent = 'Release details available after connecting.';
  $('agent-workspace').replaceChildren();
  document.querySelectorAll('.activity-workers').forEach(el => el.replaceChildren());
  document.querySelectorAll('.activity-state, .activity-source').forEach(el => { el.textContent = 'Private observations unavailable; no live connections.'; });
  renderConnections(undefined); renderInference(undefined); renderNodeProbes(undefined);
  renderRelay(undefined); $('relay-text').value = ''; $('relay-message-id').value = '';
  relayTerminalInstance = undefined;
  $('relay-terminal').hidden = true; $('relay-terminal').srcdoc = ''; $('relay-terminal').src = 'about:blank';
  $('demo-state').textContent = reason; message('Private data unavailable until verified local task session admission.'); controls();
}
function proofAvailable() {
  if (lifecycleSuspended) { clearPrivate('Page inactive. Start a fresh local task session when visible.'); return false; }
  if (!navigator.onLine) { clearPrivate('Offline. Private data cleared; reconnect and start a local task session.'); return false; }
  // A locked read during admission must not invalidate the in-flight bootstrap.
  // Missing proof still refuses the request; private state was already cleared.
  if (!demo) return false;
  if (Date.now() >= demo.expiresAt) { clearPrivate(workspaceLocked?'Workspace locked. Choose Reconnect workspace to open saved tasks.':'Session expired. Reconnecting will reopen saved tasks.'); return false; }
  return true;
}
function currentDemo(expectedDemo, expectedGeneration) {
  // A stale request must never clear the proof/UI of a replacement session.
  return expectedGeneration === generation && expectedDemo === demo && proofAvailable();
}
function message(text, error = false) {
  $('message').textContent = text; $('message').className = error ? 'error' : 'success';
  const createNotice = $('workroom-create-status');
  if (createNotice?.closest('dialog')?.open) createNotice.textContent = text;
  if (!admitted) sessionRecoveryError = error ? text : '';
  if (error) {
    const workspace = ['workroom', 'relay'].find(name => $('tab-' + name).getAttribute('aria-selected') === 'true');
    if (!admitted && workspace) { controls(); $(workspace + '-session-state').focus(); }
    else $('message').focus();
  }
}
async function api(route, options = {}) {
  const bootstrap = route === '/api/trial-session/bootstrap';
  const admission = bootstrap || route === '/api/trial-session/recovery-challenge' || route === '/api/trial-session/recovery-complete';
  if (!admission && !proofAvailable()) throw new Error('Local task session admission required.');
  const requestGeneration = generation;
  const requestDemo = demo;
  const sameRequest = () => requestGeneration === generation && requestDemo === demo;
  const checkRequest = () => {
    if (!sameRequest() || lifecycleSuspended || !navigator.onLine || (!admission && !currentDemo(requestDemo, requestGeneration))) throw new Error('Demo changed or expired while request was pending.');
  };
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), route === '/api/inference/chat' ? 18000 : /^\/api\/workroom\/.+\/(message|sync|handoff|approval)$/.test(route) ? 15000 : route === '/api/inference/approve' ? 8000 : 2500);
  try {
    checkRequest();
    const requestOptions = { ...options, signal: controller.signal, cache: 'no-store', credentials: 'same-origin', headers: { 'Content-Type': 'application/json', ...options.headers, ...(!admission ? { 'X-Trial-CSRF': requestDemo.csrfToken } : {}) } };
    let response = await fetch(route, requestOptions);
    checkRequest();
    // Bootstrap is called by manual Start or authorized automatic entry. Its 401 expires
    // an invalid cookie; retry once so restart recovery takes one click.
    //
    // The retry has to wait a beat. The 401 carries a clearing Set-Cookie for the
    // stale session; retrying in the same tick can beat the cookie jar, in which case
    // the server sees the dead cookie again and answers 403 — which surfaces to the
    // operator as "Invalid local task session admission response." That is the exact
    // failure this delay removes.
    if (bootstrap && response.status === 401) {
      await new Promise(resolve => setTimeout(resolve, 120));
      checkRequest();
      response = await fetch(route, requestOptions);
      checkRequest();
      // Still refused with the dead cookie attached: ask the server to clear it,
      // then try once more. Clearing is explicit, never assumed.
      if (response.status === 403) {
        await fetch('/api/trial-session/logout', { method: 'POST', credentials: 'same-origin', cache: 'no-store' }).catch(() => {});
        response = await fetch(route, requestOptions);
        checkRequest();
      }
    }
    // The guarded admission flow can request recovery of a live
    // cookie whose old proof was cleared. Bootstrap's guard stays intact.
    if (bootstrap && response.status === 403) return { recoveryRequired: true };
    if (response.status === 401 || response.status === 403) {
      clearPrivate('Session rejected or expired. Private data cleared. Start a local session again.');
      throw new Error('Local task session authorization rejected.');
    }
    if (!response.ok) {
      if (response.status === 409 && bootstrap) throw new Error('Local session already active. Start a fresh local session after clearing this tab.');
      const rawError = await response.text(); checkRequest();
      if (response.status === 409 && route.startsWith('/api/tasks/')) { staleSelection = true; controls(); }
      let errorBody;
      if (rawError.length <= 4096) { try { errorBody = JSON.parse(rawError); } catch { /* Empty guard denials are expected. */ } }
      throw new Error(typeof errorBody?.error === 'string' ? errorBody.error : `Local request refused (${response.status}).`);
    }
    if (response.status === 204 || options.method === 'HEAD') return undefined;
    const raw = await response.text();
    checkRequest();
    if (raw.length > 262144) throw new Error('Response too large.');
    let body; try { body = JSON.parse(raw); } catch { throw new Error('Local app returned an invalid response.'); }
    return body;
  } catch (e) {
    if (e.name === 'AbortError' || e instanceof TypeError) { if (sameRequest()) clearPrivate('Local app unreachable. Private data cleared; reconnect and start a local task session.'); throw new Error('Local app unreachable or observation timed out.'); }
    throw e;
  } finally { clearTimeout(timer); }
}
function selectTask(task, preserveDrafts = false) {
  if (!admitted || !proofAvailable()) return;
  // Passive observations update saved state while retaining this task's dirty inputs.
  for (const field of ['title', 'description', 'label']) {
    const input = $(`edit-${field}`);
    if (!preserveDrafts || selected?.id !== task.id || input.value === selected[field]) input.value = task[field];
  }
  selected = task; staleSelection = false; $('no-selection').hidden = true; $('edit-form').hidden = false;
  $('inspection-heading').textContent = `Inspect: ${task.title}`;
  $('result-heading').textContent = `Proposal and result: ${task.title}`;
  $('task-identity').textContent = `Task ${task.id} · revision ${task.revision}`;
  $('task-status').textContent = `Saved status: ${task.status}`;
  $('toggle-status').textContent = task.status === 'done' ? 'Reopen task' : 'Mark done';
  $('proposal-form').hidden = false;
  const proposalMessages = { pending: 'Pending · not executed. Approve authorizes this exact saved command.',
    approved: 'Approved · awaiting owned execution.', running: 'Running · awaiting process result and verified cleanup.',
    completed: 'Completed · inspect the process result and cleanup below.', failed: 'Failed · inspect the process result and cleanup below.',
    denied: 'Denied · no executor invoked and no execution record created for this proposal. Denial happens before execution; cancellation and process cleanup are not applicable.' };
  const run = task.execution;
  const cleanup = run?.result?.cleanupVerified === true ? 'true' : run?.result?.cleanupVerified === false ? 'false' : 'unknown';
  const cancellation = run?.result?.cancelled === true && ['completed', 'failed'].includes(run.state) ?
    cleanup === 'true' ? 'Cancelled · owned cleanup verified.' :
      `Cancellation unconfirmed · cleanup ${cleanup === 'false' ? 'not verified' : 'unknown'}; work may still be running. No automatic retry.` : undefined;
  const interrupted = run?.state === 'failed' && run.result?.status === 'UNKNOWN';
  $('proposal-state').textContent = interrupted ?
    'Interrupted by server restart · outcome unknown. No automatic retry. Save a new proposal, then deliberately Approve to run again.' :
    task.proposal ? proposalMessages[task.proposalStatus] ?? 'Execution state unavailable.' : 'No proposal saved. Proposing grants no execution approval.';
  if (!interrupted && cancellation) $('proposal-state').textContent = cancellation;
  if (!interrupted && !cancellation && task.proposalStatus === 'completed' && cleanup === 'true') $('proposal-state').textContent = 'Completed · exit code 0 · owned cleanup verified.';
  if (run && cancellingRun === run.id && run.state === 'running') $('proposal-state').textContent = 'Cancellation requested · cleanup pending; still running until the owned bridge reports its result and cleanup.';
  $('proposal-value').textContent = task.proposal ? JSON.stringify(task.proposal) : '';
  $('execution-result').textContent = run ? `Run ${run.id}\nState: ${run.state}\n` + (interrupted ?
    `Outcome: unknown\nInterrupted by server restart. Process result was not recorded.\nPID: unknown\nExit code: unknown\nCleanup verified: unknown\nTimeout: unknown\nstdout: unknown\nstderr: unknown\nRecovery recorded at: ${run.finishedAt}\nNo automatic retry. Save a new proposal to request another execution.` : run.result ?
    `Cancel request observed: ${run.result.cancelled === true ? 'true' : run.result.cancelled === false ? 'false' : 'unknown'}\nExit code: ${run.result.rootExitCode ?? 'unknown'}\nCleanup verified: ${cleanup}\nError: ${run.result.error ?? 'none'}\nstdout:\n${run.result.stdout}\nstderr:\n${run.result.stderr}` : 'Process result not yet known.') :
    task.proposalStatus === 'pending' ? 'Pending · not run. No process result exists for this proposal.' : task.proposalStatus === 'denied' ?
      'Not run. This proposal was denied before execution. No process result exists for this proposal. Cancellation and process cleanup: not applicable.' : 'Not run. No process result exists for this proposal.';
  const choice = commands.find(entry => entry.command === task.proposal?.command && entry.cwd === task.proposal?.cwd);
  if (choice) $('proposal-command').value = choice.id;
  controls();
  if (task.proposalStatus === 'running') watchExecution(task);
}
function watchExecution(task) {
  if (watchedRun?.runId === task.execution.id && watchedRun.taskId === task.id && watchedRun.generation === generation) return;
  const watch = { taskId: task.id, runId: task.execution.id, generation, demo };
  watchedRun = watch;
  // Poll independently of action() so the running task's Cancel stays usable.
  void (async () => {
    try {
      while (watchedRun === watch && selected?.id === watch.taskId && selected?.execution?.id === watch.runId && selected.proposalStatus === 'running') {
        await new Promise(resolve => setTimeout(resolve, 200));
        if (watchedRun !== watch || !admitted || !currentDemo(watch.demo, watch.generation)) return;
        if (busy) continue;
        const current = (await api(`/api/tasks/${watch.taskId}`)).task;
        if (busy) continue;
        if (watchedRun !== watch || selected?.id !== watch.taskId || selected?.execution?.id !== watch.runId || !admitted || !currentDemo(watch.demo, watch.generation)) return;
        selectTask(current, true);
        if (current.proposalStatus !== 'running') { await loadTasks(); message($('proposal-state').textContent, current.proposalStatus === 'failed'); }
      }
    } catch (e) { if (currentDemo(watch.demo, watch.generation)) message(e.message, true); }
    finally { if (watchedRun === watch) watchedRun = undefined; }
  })();
}
function renderCommands(body) {
  commands = Array.isArray(body?.commands) && body.commands.every(entry =>
    typeof entry.id === 'string' && typeof entry.command === 'string' && entry.cwd === '.') ? body.commands : [];
  const previous = $('proposal-command').value;
  $('proposal-command').replaceChildren();
  for (const entry of commands) {
    const option = document.createElement('option'); option.value = entry.id; option.textContent = entry.command;
    $('proposal-command').append(option);
  }
  const choice = commands.find(entry => entry.command === selected?.proposal?.command) ?? commands.find(entry => entry.id === previous) ?? commands[0];
  if (choice) $('proposal-command').value = choice.id;
  $('command-state').textContent = commands.length ? 'Working directory: . (fixed repository root).' : 'Command whitelist unavailable. Proposing is disabled.';
  controls();
}
async function loadTasks() {
  const loadGeneration = generation;
  const loadDemo = demo;
  const { tasks } = await api('/api/tasks');
  if (!admitted || !currentDemo(loadDemo, loadGeneration)) return;
  $('total-count').textContent = String(tasks.length);
  $('open-count').textContent = String(tasks.filter(t => t.status === 'open').length);
  $('done-count').textContent = String(tasks.filter(t => t.status === 'done').length);
  $('empty-board').textContent = tasks.length ? 'Choose a saved task to inspect.' : 'No tasks yet. Create your first task.';
  $('tasks').replaceChildren();
  for (const task of tasks) {
    const button = document.createElement('button'); button.type = 'button';
    button.setAttribute('aria-pressed', String(task.id === selected?.id));
    const title = document.createElement('b'); title.textContent = task.title;
    const detail = document.createElement('small'); detail.textContent = `${task.status} · ${task.label || 'No assignment label'} · revision ${task.revision}`;
    button.append(title, detail); button.addEventListener('click', () => {
      if (!admitted || !currentDemo(loadDemo, loadGeneration)) return;
      if (busy) return;
      selectTask(task);
      for (const b of $('tasks').children) b.setAttribute('aria-pressed', String(b === button));
      message('Saved task loaded.');
      // Only deliberate selection moves focus/viewport; polling and refresh do not.
      $('inspection-heading').focus();
    }); $('tasks').append(button);
  }
  if (selected) {
    const current = tasks.find(task => task.id === selected.id);
    if (current) selectTask(current, true);
  }
}
function taskFields(prefix, status) {
  return { title: $(`${prefix}-title`).value, description: $(`${prefix}-description`).value, label: $(`${prefix}-label`).value, status };
}
async function action(operation) {
  if (busy) return; busy = true;
  controls();
  try { await operation(); } catch (e) { message(e.message, true); }
  finally { busy = false; controls(); automaticEntry?.recover(); }
}
$('create-form').addEventListener('submit', e => { e.preventDefault(); action(async () => {
  const { task } = await api('/api/tasks', { method: 'POST', body: JSON.stringify({...taskFields('create', 'open'),owner:$('create-owner').value}) });
  $('create-form').reset(); selectTask(task); await loadTasks(); message('Task created and saved to SQLite.');
  if ($('workroom-create-status')?.closest('dialog')?.open) window.dispatchEvent(new CustomEvent('mesh-task-created', { detail: { id: task.id } }));
  else $('inspection-heading').focus();
}); });
$('view-result').addEventListener('click', () => $('result-heading').focus());
$('back-to-details').addEventListener('click', () => $('inspection-heading').focus());
async function save(status) {
  const { task } = await api(`/api/tasks/${selected.id}`, { method: 'PATCH', body: JSON.stringify({ ...taskFields('edit', status), revision: selected.revision }) });
  selectTask(task); await loadTasks(); message(`Task saved · ${task.status} · revision ${task.revision}.`);
}
$('edit-form').addEventListener('submit', e => { e.preventDefault(); action(() => save(selected.status)); });
$('toggle-status').addEventListener('click', () => action(() => save(selected.status === 'done' ? 'open' : 'done')));
$('reload-task').addEventListener('click', () => action(async () => {
  selectTask((await api(`/api/tasks/${selected.id}`)).task); await loadTasks(); message('Current revision loaded.');
}));
$('proposal-form').addEventListener('submit', e => { e.preventDefault(); action(async () => {
  const choice = commands.find(entry => entry.id === $('proposal-command').value);
  if (!selected || !choice) throw new Error('Select a saved task and a whitelisted command.');
  const { task } = await api(`/api/tasks/${selected.id}/proposal`, { method: 'POST', body: JSON.stringify({
    proposal: { command: choice.command, cwd: choice.cwd }, revision: selected.revision
  }) });
  selectTask(task); await loadTasks(); message('Proposal saved · pending · not executed.');
}); });
for (const decision of ['approve','deny']) $(`${decision}-command`).addEventListener('click', () => action(async () => {
  if (!selected || selected.proposalStatus !== 'pending') throw new Error('Reload a current pending proposal.');
  const { task } = await api(`/api/tasks/${selected.id}/${decision}`, { method: 'POST', body: JSON.stringify({ revision: selected.revision }) });
  selectTask(task); await loadTasks();
  message(decision === 'approve' ? 'Approved. Waiting for the actual owned process result.' : 'Denied. No command ran.');
}));
$('cancel-command').addEventListener('click', () => action(async () => {
  if (!selected || selected.proposalStatus !== 'running') throw new Error('Reload a current running task.');
  const taskId = selected.id; const runId = selected.execution.id; const revision = selected.revision;
  cancellingRun = runId; selectTask(selected);
  try {
    const { task } = await api(`/api/tasks/${taskId}/cancel`, { method: 'POST', body: JSON.stringify({ revision, runId }) });
    selectTask(task); await loadTasks(); message($('proposal-state').textContent, task.proposalStatus === 'failed');
  } finally { cancellingRun = undefined; }
}));

let connectionSnapshot; let inferenceSnapshot;
let nodeProbeSnapshot; let nodeProbeReceivedAt = 0; let nodeProbeRequest = 0;
const probeTick = () => globalThis.performance?.now() ?? Date.now();
const observationStatuses = new Set(['not_configured','disabled','fresh','partial','stale','unavailable','unauthorized','unsupported','invalid']);
function age(value, now = Date.now()) {
  const ms = Date.parse(value);
  return !Number.isFinite(ms) || ms > now ? 'age unknown' : Math.floor((now-ms)/1000) + 's elapsed since observation';
}
function paragraph(parent, text) {
  const el = document.createElement('p'); el.textContent = text; parent.append(el); return el;
}
function details(value) {
  if (value === null || value === undefined) return 'unknown';
  if (typeof value !== 'object') return String(value);
  if (Array.isArray(value)) return value.length ? value.map(details).join('; ') : 'none observed';
  return Object.entries(value).map(([key,v]) => key + ': ' + details(v)).join(' · ') || 'unknown';
}
export function renderConnections(snapshot) {
  connectionSnapshot = snapshot;
  const valid = snapshot?.schemaVersion === 'mesh-service-connections/v1' && Array.isArray(snapshot.services) && snapshot.services.length === 4 && ['relay','inference','agent','mind'].every(id => snapshot.services.filter(s => s.id === id && observationStatuses.has(s.status)).length === 1);
  const services = valid ? snapshot.services : [];
  for (const box of document.querySelectorAll('.service-connections')) {
    box.replaceChildren();
    if (!valid) paragraph(box, 'Service observations unavailable. Previous success cleared.');
    const meanings={
      relay:['Relay bridge','Conversation history and agent observations come through this bridge; reachability is not task completion.'],
      inference:['Legacy inference adapter','Read-only PC and model-supervisor observations are separate in Inference and Control. This adapter status does not mean no model is running.'],
      agent:['Standalone Agent adapter','The Agent tab separately shows Relay peers and saved Workroom handoffs. A listed peer is not proof of coding access.'],
      mind:['Legacy Mind adapter','Saved task context comes from Workroom. The separate Onoes-Mind reader has its own connection check in Mind.']
    };
    for(const s of services){
      const [label,meaning]=meanings[s.id];
      paragraph(box,label+': last observation '+s.status+' · source: '+s.source+' · checked '+(s.observedAt||'at an unknown time')+' · probe '+s.elapsedMs+'ms · errors: '+(s.errors.map(e=>e.code).join(', ')||'none')+(s.source==='disposable_fixture'?' · TEST ONLY; real service not connected':''));
      paragraph(box,meaning);
    }
  }
  for (const el of document.querySelectorAll('.service-status')) {
    const s = services.find(s=>s.id === el.getAttribute('data-service'));
    el.textContent = s ? 'Connection: ' + s.status + ' · ' + s.source + ' · errors: ' + (s.errors.map(e=>e.code).join(', ') || 'none') : 'Connection unavailable. Previous success cleared.';
  }
}
export function renderInference(snapshot) {
  inferenceSnapshot = snapshot;
  const valid = snapshot?.schemaVersion === 'mesh-inference-observation/v1' && observationStatuses.has(snapshot.status) && Array.isArray(snapshot.nodes) && Array.isArray(snapshot.errors);
  const box = $('inference-nodes'); box.replaceChildren();
  for (const el of document.querySelectorAll('.inference-state')) el.textContent = valid ? 'Inference status at observation: ' + snapshot.status + ' · observed at ' + snapshot.observedAt + ' · ' + age(snapshot.observedAt) : 'Inference unavailable. Previous measurements cleared.';
  for (const el of document.querySelectorAll('.inference-errors')) el.textContent = valid ? 'Errors: ' + (snapshot.errors.map(e=>e.code + (e.nodeId === null ? '' : ' (' + e.nodeId + ')')).join(', ') || 'none') : 'Errors: observation_unavailable';
  if (!valid || snapshot.nodes.length === 0) { paragraph(box, 'No configured node observations available. Hardware and model residency unknown.'); return; }
  for (const n of snapshot.nodes) {
    const card = document.createElement('article'); card.className = 'node-observation';
    const title = document.createElement('h3'); title.textContent = n.label + ' (' + n.id + ')'; card.append(title);
    paragraph(card, 'Status at observation: ' + n.status + ' · source: ' + n.source + ' · ' + age(n.observedAt));
    paragraph(card, 'Observed at: ' + (n.observedAt ?? 'unknown') + ' · observation capability: ' + n.capabilities.observation + ' · load/unload: unavailable');
    paragraph(card, 'Expected hardware: ' + details(n.hardware.expected));
    paragraph(card, 'Observed hardware: ' + details(n.hardware.observed));
    paragraph(card, 'Verified model fields: ' + (n.models.length ? details(n.models) : 'none observed; residency unknown'));
    if (n.source === 'disposable_fixture') paragraph(card, 'TEST ONLY: disposable observation; no real hardware or model claim.');
    box.append(card);
  }
}

function renderSupervisorModels(value) {
  const root=$('local-model-catalog');
  localModelObservation=undefined;root.replaceChildren();
  if(value?.schemaVersion!=='mesh-supervisor-observation/v1' || value.source!=='local_supervisor' || !Array.isArray(value.models)) {
    root.textContent='Model observations unavailable. Connect and refresh local status.';return;
  }
  if(!Number.isSafeInteger(value.expiresAt) || value.expiresAt<=Date.now() || value.expiresAt>Date.now()+5000) {
    root.textContent='Model observations expired. Refresh local status.';return;
  }
  localModelObservation=value;root.textContent='';
  const labels={reported_loaded:'Reported loaded',ready:'Available to load',loading_unconfirmed:'Supervisor loading · target not confirmed',unavailable:'Not available',unknown:'Status unknown'};
  const reasons={engine_not_built:'engine files missing',model_files_missing:'model files missing',preflight_failed:'readiness check failed',observation_unavailable:'status could not be verified'};
  for(const row of value.models.slice(0,4)) {
    const line=document.createElement('p');line.className='fine';
    line.textContent=String(row.label).slice(0,100)+' · '+(labels[row.state]||'Status unknown')+(row.reason?' · '+(reasons[row.reason]||'status unavailable'):'');root.append(line);
  }
}
function localInferenceControls() {
  if(localModelObservation && localModelObservation.expiresAt<=Date.now()) {
    localModelObservation=undefined;$('local-model-catalog').replaceChildren();$('local-model-catalog').textContent='Model observations expired. Refresh local status.';
  }
  const s = localInferenceSnapshot;
  const locked = busy || lifecycleSuspended || !admitted || !navigator.onLine;
  const fresh = s?.observedAt && Date.now() - Date.parse(s.observedAt) >= 0 &&
    Date.now() - Date.parse(s.observedAt) < s.freshForMs &&
    probeTick() - localInferenceReceivedAt < s.freshForMs;
  const reason = locked ? 'Start a local session; wait for the current request to finish.' :
    (['NATIVE_QUALIFICATION_REQUIRED','NEMOTRON_QUALIFICATION_REQUIRED'].includes(s?.controls?.reason)
      ? 'Local model controls are not qualified yet. PC readings above remain available.'
      : s?.controls?.reason === 'ORIGINAL_OPERATION_PENDING' ? 'An earlier model command needs verification. Refresh status, or resolve it when available. The original command will not be repeated.' : s?.controls?.reason) || (!fresh ? 'Observation expired or unavailable. Refresh local status.' : '');
  $('local-inference-refresh').disabled = locked;
  $('local-inference-refresh').title = locked ? reason : 'Read this PC status without executing a control.';
  for (const name of ['load', 'stop', 'unload', 'recover', 'chat']) {
    const enabled = !locked && fresh && s?.controls?.[name] === true;
    const ids = name === 'chat' ? ['local-inference-send', 'local-inference-prompt'] : ['local-inference-' + name];
    for (const id of ids) { $(id).disabled = !enabled; $(id).title = enabled ? '' : reason || name + ' is unavailable in state ' + s?.state; }
  }
  $('local-inference-recover').hidden = !s || s.profile?.id !== 'nemotron-bolt-local' || s.operation?.state !== 'UNKNOWN' || s.operation?.reason === 'OUTCOME_FENCED';
  const proposalValid = localInferenceProposal && localInferenceProposal.expiresAt > Date.now() &&
    localInferenceProposal.revision === s?.revision;
  $('local-inference-approve').disabled = locked || !fresh || !proposalValid;
  $('local-inference-approve').title = proposalValid ? reason : 'Create a fresh proposal before confirming.';
  $('local-inference-dismiss').disabled = locked || !localInferenceProposal;
  $('local-inference-dismiss').title = locked ? reason : 'Dismiss without executing.';
  $('local-inference-confirmation').hidden = !localInferenceProposal;
  $('local-inference-reason').textContent = reason || 'Controls apply only to the fixed local profile. Stop and Unload both terminate the owned runtime.';
  $('local-inference-chat-state').textContent = $('local-inference-send').disabled
    ? 'Chat unavailable. ' + (reason || 'Requires a verified RUNNING runtime.') : 'Chat ready · session only.';
}
export function renderLocalInference(snapshot) {
  renderSupervisorModels(snapshot?.modelObservation);
  const valid = snapshot?.schemaVersion === 'mesh-local-inference/v1' && snapshot.nodeId === 'this-pc' &&
    ['qwen38-flash-next-q6','nemotron-bolt-local'].includes(snapshot.profile?.id) && snapshot.controls;
  localInferenceSnapshot = valid ? snapshot : undefined;
  localInferenceReceivedAt = probeTick();
  $('local-inference-state').textContent = valid
    ? `[${snapshot.state}] · this-pc · ${snapshot.source} · observation ${snapshot.observedAt ?? 'UNAVAILABLE'} · ${snapshot.freshness}`
    : 'UNAVAILABLE · Start a local session and refresh local status.';
  $('local-inference-profile').textContent = valid && ['RUNNING','OWNED'].includes(snapshot.state) && ['VERIFIED','OWNED'].includes(snapshot.runtime?.status)
    ? `${snapshot.profile.model} · ${snapshot.runtimeId}${snapshot.runtime.status==='OWNED'?' · owned process; health unverified':''}`
    : 'No verified model connection. PC readings above remain available.';
  $('local-inference-identity').textContent = valid ? 'Runtime identity: ' + details(snapshot.runtime) : 'Runtime identity UNKNOWN';
  if(valid && snapshot.profile.id==='nemotron-bolt-local' && snapshot.operation)$('local-inference-receipt').textContent=details(snapshot.operation);
  $('local-inference-telemetry').textContent = valid ? 'Telemetry: ' + details(snapshot.telemetry)
    : 'CPU UNKNOWN · RAM UNKNOWN · GPU UNAVAILABLE · VRAM UNAVAILABLE';
  localInferenceControls();
}
async function refreshLocalInference() {
  try { renderLocalInference(await api('/api/inference/status')); }
  catch (error) { renderLocalInference(undefined); throw error; }
}
$('local-inference-refresh').addEventListener('click', () => action(refreshLocalInference));
for (const name of ['load', 'stop', 'unload', 'recover']) $('local-inference-' + name).addEventListener('click', () => action(async () => {
  localInferenceProposal = undefined;
  try {
    const { proposal } = await api('/api/inference/propose-' + name, { method: 'POST', body: '{}' });
    localInferenceProposal = proposal;
    $('local-inference-proposal').textContent = proposal.action === 'recover' ? 'Resolve the earlier unknown command without repeating it. Its outcome stays unknown; the supervisor must confirm no active command and prevent delayed execution.' : `Confirm ${proposal.action} · ${proposal.profile.model} · ${proposal.profile.runtimeId} · ${proposal.profile.nodeId} · expires ${new Date(proposal.expiresAt).toISOString()}. No action has executed.`;
  } catch (error) { renderLocalInference(undefined); throw error; }
}));
$('local-inference-dismiss').addEventListener('click', () => { localInferenceProposal = undefined; localInferenceControls(); });
$('local-inference-approve').addEventListener('click', () => action(async () => {
  if (!localInferenceProposal || localInferenceProposal.expiresAt <= Date.now()) throw new Error('Create a fresh proposal.');
  const proposalId = localInferenceProposal.id; localInferenceProposal = undefined;
  try {
    const result = await api('/api/inference/approve', { method: 'POST', body: JSON.stringify({ proposalId, confirm: true }) });
    // Read the redacted server receipt back; no prompt or response enters it.
    const { receipt } = await api('/api/inference/receipt/' + result.receipt.id);
    $('local-inference-receipt').textContent = details(receipt);
    await refreshLocalInference();
  } catch (error) { renderLocalInference(undefined); throw error; }
}));
$('local-inference-chat-form').addEventListener('submit', event => {
  event.preventDefault(); action(async () => {
    const prompt = $('local-inference-prompt').value;
    $('local-inference-prompt').value = ''; $('local-inference-response').textContent = '';
    try {
      const result = await api('/api/inference/chat', { method: 'POST', body: JSON.stringify({ prompt }) });
      $('local-inference-response').textContent = result.response;
      await refreshLocalInference();
    } catch (error) { renderLocalInference(undefined); throw error; }
  });
});

export function renderNodeProbes(snapshot, receivedAt = probeTick()) {
  if (snapshot !== nodeProbeSnapshot) nodeProbeReceivedAt = receivedAt;
  nodeProbeSnapshot = snapshot;
  const box = $('tailnet-nodes'); box.replaceChildren();
  if (snapshot?.schemaVersion === 'mesh-node-probes/v1' && snapshot.status === 'not_configured' &&
      snapshot.source === 'none' && Array.isArray(snapshot.nodes) && snapshot.nodes.length === 0) {
    paragraph(box, 'Node observation is not configured in standalone mode. No tailnet probes run.'); return;
  }
  const valid = snapshot?.schemaVersion === 'mesh-node-probes/v1' &&
    ['native_tailscale_cli', 'disposable_transport'].includes(snapshot.source) &&
    Array.isArray(snapshot.nodes) && snapshot.nodes.length === 2 &&
    snapshot.nodes[0].id === 'pc' && snapshot.nodes[1].id === 'laptop';
  if (!valid) { paragraph(box, 'Node observation unavailable. No online or offline result established.'); return; }
  const elapsed = Math.max(0, probeTick() - nodeProbeReceivedAt);
  for (const n of snapshot.nodes) {
    const card = document.createElement('article'); card.className = 'node-observation';
    card.setAttribute('data-node-id', n.id);
    const title = document.createElement('h3'); title.textContent = n.label + ' (' + n.id + ')'; card.append(title);
    paragraph(card, n.dnsName + ' · ' + n.tailscaleIp);
    // Local aging never refreshes the CLI or advances last-success timestamps.
    const successAge = n.lastSuccessAt === null ? Infinity :
      Math.max(0, Date.parse(snapshot.observedAt) - Date.parse(n.lastSuccessAt)) + elapsed;
    const hasObservation = typeof n.tailscaleOnline === 'boolean' ||
      (typeof n.lastSuccessAt === 'string' && Number.isFinite(Date.parse(n.lastSuccessAt)));
    const status = !hasObservation ? (n.lastProbeAt === null ? 'not_checked' : 'unavailable') : n.tailscaleOnline === true && successAge >= snapshot.limits.staleGraceMs ? 'expired' : successAge >= snapshot.limits.staleGraceMs ? 'offline' :
      n.status === 'ready' && successAge >= snapshot.limits.freshMs ? 'stale' : n.status;
    // Busy is presentation-only unless the node status source explicitly supplies it.
    const presentations = { ready: ['Online', 'online'], offline: ['Offline', 'offline'],
      busy: ['Busy', 'busy'], stale: ['Stale', 'stale'], expired: ['Check expired', 'stale'], unavailable: ['Unavailable', 'neutral'], not_checked: ['Not checked', 'neutral'] };
    const presentation = Object.hasOwn(presentations, status) ? presentations[status] : [status, 'neutral'];
    const statusLine = document.createElement('p');
    const statusWord = document.createElement('span');
    statusWord.textContent = presentation[0];
    statusWord.className = 'node-status node-status--' +
      (n.observationAvailability === 'available' ? presentation[1] : 'neutral');
    statusLine.append(hasObservation && n.observationAvailability === 'unavailable'
      ? 'Observation unavailable · cached status: ' : 'Status: ', statusWord,
      !hasObservation ? ' · no machine status result available' : n.observationAvailability === 'unavailable'
      ? ' · offline not established by this read' : ' · cached Tailscale Online: ' + n.tailscaleOnline);
    card.append(statusLine);
    paragraph(card, 'Last probe: ' + (n.lastProbeAt ?? 'never') + ' · Last success (Online=true): ' + (n.lastSuccessAt ?? 'never'));
    paragraph(card, 'Observation: ' + n.observationAvailability + ' · source: ' + snapshot.source + ' · local probe completion timestamps');
    paragraph(card, 'Packet reachability: unknown · Inference readiness: unknown · Model readiness: unknown');
    paragraph(card, 'Errors at last probe: ' + (n.errors.map(e => e.code).join(', ') || 'none') + (hasObservation && status !== n.status ? ' · observation_expired' : ''));
    if (snapshot.source === 'disposable_transport') paragraph(card, 'TEST ONLY: controlled transport; no native tailnet claim.');
    box.append(card);
  }
}
async function refreshNodeProbes() {
  if (!admitted || !proofAvailable() || $('panel-inference').hidden) return;
  const request = ++nodeProbeRequest, requestDemo = demo, requestGeneration = generation;
  const snapshot = await api('/api/node-probes/refresh', { method: 'POST', body: '{}' });
  if (request !== nodeProbeRequest || !currentDemo(requestDemo, requestGeneration)) return;
  renderNodeProbes(snapshot);
}

export async function refresh() {
  if (!admitted || !proofAvailable()) return;
  const refreshGeneration = generation;
  const refreshDemo = demo;
  const probeRequest = ++nodeProbeRequest;
  const results = await Promise.allSettled([
    api('/api/health'),
    loadTasks(),
    api('/api/worker-activity'),
    api('/api/service-connections'),
    api('/api/inference-observation'),
    api('/api/commands'),
    api('/api/relay'),
    api('/api/node-probes'),
    api('/api/inference/status'),
    api('/api/release'),
    api('/api/workroom')
  ]);
  if (!admitted || !currentDemo(refreshDemo, refreshGeneration)) return;
  const failed = results.some(r => r.status === 'rejected');
  const health = results[0].status === 'fulfilled' ? results[0].value : undefined;
  $('app-state').textContent = health ? `App: ${health.state} · persistence: ${health.persistence} · ${health.url}` : 'App / persistence unavailable. Existing data has been preserved.';
  const release = results[9].status === 'fulfilled' ? results[9].value : undefined;
  $('release-state').textContent = release ? `Mesh ${release.version} · build ${release.build} · ${release.qualification}\nSaved board: ${release.database}\nStarted: ${release.startedAt}\n${release.note}` : 'Release details unavailable. Existing data has been preserved.';
  const sources = {
    none: 'No registry configured.',
    local_registry: 'Configured local registry observation; source not independently qualified.',
    disposable_fixture: 'Disposable sanitized test fixture; these rows are not real worker activity.',
    frozen_manager_projection: 'Frozen sanitized manager projection; historical observation, not current activity.'
  };
  document.querySelectorAll('.activity-source').forEach(el => { el.textContent = `${sources[health?.activity?.source] ?? 'Activity source unknown.'} No live process polling. Reported models are unverified metadata.`; });
  if (results[1].status === 'rejected') {
    for (const id of ['total-count', 'open-count', 'done-count']) $(id).textContent = 'Unknown';
    $('tasks').replaceChildren(); $('empty-board').textContent = 'Task data unavailable. Existing data has been preserved.';
  }
  const activity = results[2].status === 'fulfilled' ? results[2].value : undefined;
  const notes = {
    ok: 'Local file read successfully; freshness does not prove process liveness or progress.',
    not_configured: health?.activity?.adapter === 'awaiting_integration' ? 'activity adapter awaiting integration' : 'Worker registry not configured; activity unknown.',
    unavailable: 'Current activity unknown; file or observation time unavailable.',
    invalid: 'Registry invalid; current activity unknown.',
    stale: 'Stale observation; recorded process states are not current activity.'
  };
  const state = activity ? `Activity: ${activity.state} · ${notes[activity.state]} · read at ${activity.observedAt}` : 'Activity unavailable. Previous rows cleared; current activity unknown.';
  document.querySelectorAll('.activity-state').forEach(el => { el.textContent = state; });
  const fields = ['runId', 'cli', 'title', 'node', 'taskId', 'processState', 'requestedModel', 'observedModel', 'startedAt', 'lastObservedAt', 'lastProgressAt', 'resultState', 'freshness'];
  for (const box of document.querySelectorAll('.activity-workers')) {
    box.replaceChildren();
    for (const worker of activity?.workers ?? []) {
      const record = document.createElement('p');
      record.textContent = fields.map(key => `${key}: ${worker[key] ?? 'unknown'}`).join('\n');
      box.append(record);
    }
    if (!activity?.workers.length) {
      const empty = document.createElement('p');
      empty.textContent = activity?.state === 'ok' ? 'No worker records in this observed file.' : 'No current worker activity available.';
      box.append(empty);
    }
  }
  try { renderConnections(results[3].status === 'fulfilled' ? results[3].value : undefined); } catch { renderConnections(undefined); }
  try { renderInference(results[4].status === 'fulfilled' ? results[4].value : undefined); } catch { renderInference(undefined); }
  renderCommands(results[5].status === 'fulfilled' ? results[5].value : undefined);
  renderRelay(results[6].status === 'fulfilled' ? results[6].value : undefined);
  mindWorkspace.setTasks(results[10].status === 'fulfilled' ? results[10].value.tasks : undefined);
  renderAgentWorkspace($('agent-workspace'), results[6].status === 'fulfilled' ? results[6].value : undefined,
    results[10].status === 'fulfilled' ? results[10].value.tasks : undefined, id => {
      if (!admitted || !currentDemo(refreshDemo, refreshGeneration)) return;
      activate($('tab-workroom'));
      window.dispatchEvent(new CustomEvent('mesh-open-task', {detail:{id}}));
    }, results[10].status === 'fulfilled' ? results[10].value.teamPolicy : undefined);
  if (probeRequest === nodeProbeRequest) renderNodeProbes(results[7].status === 'fulfilled' ? results[7].value : undefined);
  renderLocalInference(results[8].status === 'fulfilled' ? results[8].value : undefined);
  const linkedId = /^#task=([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})$/.exec(window.location?.hash ?? '')?.[1];
  if (linkedId && selected?.id !== linkedId) {
    const task = (await api(`/api/tasks/${linkedId}`)).task;
    if (!currentDemo(refreshDemo, refreshGeneration)) return;
    selectTask(task); activate($('tab-workroom'));
  }
  message(failed ? results.find(r => r.status === 'rejected').reason.message : 'Local app status and saved tasks refreshed.', failed);
}
// Visible inference status is a read-only observation, never a model action.
let inferencePollPending=false;
setInterval(async()=>{
  if(inferencePollPending || busy || lifecycleSuspended || !navigator.onLine || !admitted ||
     !proofAvailable() || $('tab-inference').getAttribute('aria-selected')!=='true')return;
  const admissionDemo=demo,admissionGeneration=generation;inferencePollPending=true;
  try {
    const value=await api('/api/inference/status',{method:'GET'});
    if(currentDemo(admissionDemo,admissionGeneration))renderLocalInference(value);
  } catch {if(currentDemo(admissionDemo,admissionGeneration))renderLocalInference(undefined);}
  finally {inferencePollPending=false;}
},4000);
// Age display advances locally; this timer performs no requests or effects.
setInterval(() => {
  if (demo && !proofAvailable()) return;
  controls();
  try { renderConnections(connectionSnapshot); } catch { renderConnections(undefined); }
  try { renderInference(inferenceSnapshot); } catch { renderInference(undefined); }
  try { renderNodeProbes(nodeProbeSnapshot); } catch { renderNodeProbes(undefined); }
  applyLocalStubs();
}, 1000);
$('refresh').addEventListener('click', () => action(refresh));
$('agent-refresh').addEventListener('click', () => action(refresh));
$('node-probes-refresh').addEventListener('click', () => action(refreshNodeProbes));
function renderRelay(snapshot) {
  relaySnapshot = snapshot;
  const referenceDemo = demo; const referenceGeneration = generation;
  $('relay-links').replaceChildren();
  $('relay-state').textContent = snapshot?.status === 'fresh'
    ? `Actual isolated Relay connected · conversation ${snapshot.conversationId}${snapshot.pending?.length ? ' · Unlinked messages: '+snapshot.pending.join(', ')+'. Retry the same message id and text.' : ''}`
    : snapshot?.error ?? 'Relay is not configured. Enable the isolated Relay runtime on the server.';
  for (const link of snapshot?.links ?? []) {
    const button = document.createElement('button'); button.type = 'button';
    button.textContent = `${link.messageId} → ${link.taskId}`;
    button.disabled = !admitted || lifecycleSuspended || !navigator.onLine;
    button.addEventListener('click', () => action(async () => {
      if (!admitted || !currentDemo(referenceDemo, referenceGeneration)) return;
      const task = (await api(`/api/tasks/${link.taskId}`)).task;
      if (!currentDemo(referenceDemo, referenceGeneration)) return;
      selectTask(task); activate($('tab-workroom')); message(`Relay task ${task.id} selected.`);
    }));
    $('relay-links').append(button);
  }
  controls();
}
// Ordinary Relay submission belongs only to chat.mjs. Workroom handoffs keep their
// explicit task-bound API and must never share this form's submit event.
$('relay-new').addEventListener('click', () => {
  if (!admitted || !proofAvailable() || busy) return;
  $('relay-message-id').value = ''; $('relay-text').value = ''; message('New Relay message. Sending creates a new task identity.');
});
$('relay-open').addEventListener('click', () => action(async () => {
  if (!admitted || !proofAvailable()) return;
  const terminalDemo = demo; const terminalGeneration = generation;
  try { sessionStorage.setItem(nonceKey, JSON.stringify(demo)); } catch { message('Browser session storage unavailable for the native Relay terminal.', true); return; }
  const shell = await api('/api/relay/shell');
  if (!currentDemo(terminalDemo, terminalGeneration)) return;
  if (typeof shell?.html !== 'string' || shell.html.length > 200000 || !shell.html.includes('<head>')) throw new Error('Invalid actual Relay HTML response.');
  relayTerminalInstance = crypto.randomUUID();
  $('relay-terminal').srcdoc = shell.html.replace('<head>', `<head><meta name="mesh-terminal-instance" content="${relayTerminalInstance}">`);
  $('relay-terminal').hidden = false;
}));
$('relay-close').addEventListener('click', () => { relayTerminalInstance = undefined; $('relay-terminal').hidden = true; $('relay-terminal').srcdoc = ''; $('relay-terminal').src = 'about:blank'; });
window.addEventListener('message', event => {
  if (!admitted || !proofAvailable() || event.source !== $('relay-terminal').contentWindow || event.origin !== window.location.origin ||
      !relayTerminalInstance || event.data?.instance !== relayTerminalInstance || event.data?.type !== 'mesh_relay_select' || typeof event.data.taskId !== 'string' || !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(event.data.taskId)) return;
  const referenceDemo = demo; const referenceGeneration = generation;
  const referenceInstance = relayTerminalInstance;
  const currentReference = () => currentDemo(referenceDemo, referenceGeneration) &&
    referenceInstance === relayTerminalInstance && event.source === $('relay-terminal').contentWindow;
  action(async () => {
    const task = (await api(`/api/tasks/${event.data.taskId}`)).task;
    if (!currentReference()) return;
    selectTask(task);
    await loadTasks();
    if (!currentReference()) return;
    activate($('tab-workroom')); relayTerminalInstance = undefined; $('relay-terminal').srcdoc = ''; $('relay-terminal').hidden = true;
    $('inspection-heading').focus();
  });
});
$('relay-reconnect').addEventListener('click', () => action(async () => {
  renderRelay(await api('/api/relay/reconnect', { method: 'POST', body: '{}' }));
  message(relaySnapshot?.status === 'fresh' ? 'Relay reconnected; saved task references recovered.' : $('relay-state').textContent, relaySnapshot?.status !== 'fresh');
}));
function startSession() { return action(async () => {
  const startGeneration = generation;
  let session = await admissionPeers?.request();
  if (startGeneration !== generation || lifecycleSuspended || !navigator.onLine) return;
  if (!session) session = await api('/api/trial-session/bootstrap', { method: 'POST', body: '{}' });
  if (startGeneration !== generation || lifecycleSuspended || !navigator.onLine) return;
  if (session?.recoveryRequired === true) {
    const fresh = await api('/api/trial-session/recovery-challenge', { method: 'POST', body: '{}' });
    if (startGeneration !== generation || lifecycleSuspended || !navigator.onLine) return;
    // This deadline uses the server clock, which may differ from the phone clock.
    // Completion enforces the server's short lifetime, cookie binding and one-use nonce.
    if (typeof fresh?.challenge !== 'string' || !/^[A-Za-z0-9_-]{43}$/.test(fresh.challenge) || !Number.isSafeInteger(fresh.expiresAt) || fresh.expiresAt <= 0) throw new Error('Invalid local recovery challenge.');
    session = await api('/api/trial-session/recovery-complete', { method: 'POST', body: '{}', headers: { 'X-Trial-CSRF': fresh.challenge } });
    if (startGeneration !== generation || lifecycleSuspended || !navigator.onLine) return;
  }
  if (typeof session?.csrfToken !== 'string' || !/^[A-Za-z0-9_-]{43}$/.test(session.csrfToken) || !Number.isSafeInteger(session.expiresAt) || session.expiresAt <= Date.now() || session.expiresAt > Date.now() + 86400000) throw new Error('Invalid local task session admission response.');
  demo = { csrfToken: session.csrfToken, expiresAt: session.expiresAt };
  try { sessionStorage.setItem(nonceKey, JSON.stringify(demo)); } catch { /* RAM only if storage is unavailable. */ }
  const admissionDemo = demo; const admissionGeneration = generation;
  await api('/api/health');
  if (!currentDemo(admissionDemo, admissionGeneration)) return;
  admitted = true; try { $('demo-start').classList.add('ok'); } catch { }
  sessionRecoveryError = '';
  $('demo-state').textContent = automaticAccess?'Workspace connected through authorized Tailscale access. Agent actions still require an explicit send.':'Local task access verified by server. No human identity or execution approval.';
  automaticEntry?.verified(demo.expiresAt);
  await refresh();
}); }
for (const id of ['demo-start', 'workroom-session-start', 'relay-session-start']) $(id).addEventListener('click', () => { workspaceLocked=false;try{sessionStorage.removeItem('mesh.workspace.locked.v1');}catch{} automaticEntry?.retry(); return startSession(); });
$('demo-end').addEventListener('click', () => { workspaceLocked=true;try{sessionStorage.setItem('mesh.workspace.locked.v1','1');}catch{} automaticEntry?.pause(); return action(async () => {
  const endDemo = demo; const endGeneration = generation;
  let ended = false;
  try { await api('/api/trial-session/logout', { method: 'POST', body: '{}' }); ended = true; }
  finally {
    if (endGeneration === generation && endDemo === demo) {
      clearPrivate('Local task session ended locally. Private data cleared.');
      if (ended) controls();
    }
  }
}); });
window.addEventListener('offline', () => { automaticEntry?.suspend(); clearPrivate('Offline. Private data cleared; reconnect and start a local task session.'); message('Private board unavailable offline.', true); });
window.addEventListener('online', () => { controls(); automaticEntry?.resume(); });
function lifecyclePrivacy(suspended) {
  lifecycleSuspended = suspended;
  if(suspended)automaticEntry?.suspend();
  savedDemo = undefined;
  clearPrivate(suspended
    ? 'Page inactive. Private data and session proof cleared.'
    : 'Page resumed. Start a fresh local task session; the previous proof was cleared.');
  if(!suspended)automaticEntry?.resume();
  if (suspended && normalNavigation && navigationProof && navigationProof.expiresAt > Date.now()) {
    try { sessionStorage.setItem(nonceKey, JSON.stringify(navigationProof)); } catch { /* RAM only. */ }
  }
}
document.addEventListener?.('visibilitychange', () => {
  const hidden = document.visibilityState === 'hidden';
  if (!hidden) { navigationProof = undefined; normalNavigation = false; }
  lifecyclePrivacy(hidden);
});
document.addEventListener?.('freeze', () => {
  navigationProof = undefined; normalNavigation = false; lifecyclePrivacy(true);
});
document.addEventListener?.('resume', () => {
  navigationProof = undefined; normalNavigation = false; lifecyclePrivacy(document.visibilityState === 'hidden');
});
window.addEventListener('beforeunload', () => {
  normalNavigation = false;
  navigationProof = admitted && proofAvailable() ? { ...demo } : undefined;
});
window.addEventListener('pagehide', event => {
  // A normal document reload keeps only the existing nonce/expiry so startup
  // can recheck admission and read the saved run. Suspended/restored pages
  // still lose proof; no task or execution data enters browser storage.
  normalNavigation = event?.persisted === false;
  if (!normalNavigation) navigationProof = undefined;
  lifecyclePrivacy(true);
});
window.addEventListener('pageshow', event => {
  navigationProof = undefined; normalNavigation = false;
  // A fresh document's initial pageshow follows startup verification. Only a
  // restored/suspended page must clear proof; it must never revive old data.
  if (event?.persisted === false && !lifecycleSuspended && document.visibilityState !== 'hidden') return;
  lifecyclePrivacy(document.visibilityState === 'hidden');
});
clearPrivate('Start a local task session. A new tab or resumed page verifies fresh admission with the server; saved tasks remain stored.');
if (lifecycleSuspended) lifecyclePrivacy(true);
if (savedDemo && navigator.onLine && !workspaceLocked) {
  demo = savedDemo; savedDemo = undefined;
  $('demo-state').textContent = 'Stored session proof is unverified. Checking the current local server session…';
  action(async () => {
    const admissionDemo = demo; const admissionGeneration = generation;
    await api('/api/health');
    if (!currentDemo(admissionDemo, admissionGeneration)) return;
    admitted = true; try { $('demo-start').classList.add('ok'); } catch { }
    try { sessionStorage.setItem(nonceKey, JSON.stringify(demo)); } catch { /* RAM only. */ }
    $('demo-state').textContent = 'Local task access verified after refresh. No human identity or execution approval.';
    await refresh();
  });
} else { savedDemo = undefined; }

// Reuse the same admitted request path for Workroom; no second credential store.
window.meshWorkroom = Object.freeze({ request: api, onClear: listener => { clearWorkroom = listener; } });

// Only the serving adapter can declare this an authorized automatic-entry surface.
import('/session-entry.mjs').then(({createSessionEntry})=>{
  automaticEntry=createSessionEntry({
    readPolicy:async()=>{const response=await fetch('/gate/status',{credentials:'same-origin',cache:'no-store',signal:AbortSignal.timeout(3000)});if(response.status===404)return {automaticSession:false};if(!response.ok)throw Error('Workspace access unavailable. Reconnect when the private server is ready.');return response.json();},
    start:()=>{if(admitted&&demo?.expiresAt<=Date.now())clearPrivate('Refreshing workspace access. Saved tasks are safe.');return startSession();},ready:()=>admitted&&demo?.expiresAt>Date.now(),available:()=>!busy&&!lifecycleSuspended&&navigator.onLine,
    onMode:enabled=>{automaticAccess=enabled;controls();if(enabled&&admitted){$('demo-state').textContent='Workspace connected through authorized Tailscale access.';automaticEntry.verified(demo.expiresAt);}},
    onError:error=>{sessionRecoveryError=error.message;controls();},
  });
  if(workspaceLocked)automaticEntry.pause();else automaticEntry.recover();
}).catch(()=>{sessionRecoveryError='Automatic connection unavailable. Use Start local session to reconnect.';controls();});
