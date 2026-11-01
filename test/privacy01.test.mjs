import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import { readFile } from 'node:fs/promises';

// Execute the complete production module, removing only its export keywords,
// as in the immutable ui.test.mjs. All fixtures below are synthetic.
const source = await readFile(new URL('../public/app.js', import.meta.url), 'utf8');
const html = await readFile(new URL('../public/index.html', import.meta.url), 'utf8');
const nonceKey = 'mesh.synthetic-demo.proof.v1';
const routes = ['/api/health', '/api/tasks', '/api/worker-activity', '/api/service-connections', '/api/inference-observation', '/api/commands', '/api/relay', '/api/node-probes'];
const epoch = 1800000000000;
const token = character => character.repeat(43);
const proof = character => ({ csrfToken: token(character), expiresAt: epoch + 60000 });
const deferred = () => { let resolve, reject; const promise = new Promise((yes, no) => { resolve = yes; reject = no; }); return { promise, resolve, reject }; };
const flush = async () => { for (let i = 0; i < 8; i++) await new Promise(resolve => setImmediate(resolve)); };
const response = (status, body, text) => ({ status, ok: status >= 200 && status < 300, text: text ?? (async () => JSON.stringify(body)) });

function bodyFor(route, marker) {
  const observedAt = new Date(epoch).toISOString();
  if (route === '/api/tasks') return { tasks: [{ id: 1, revision: 1, title: marker + 'TASK', description: marker + 'DESCRIPTION', label: marker + 'LABEL', status: 'open', proposal: { command: marker + 'COMMAND', cwd: '.' }, proposalStatus: 'pending' }] };
  if (route === '/api/commands') return { commands: [{ id: 'node-version', command: 'node --version', cwd: '.' }] };
  if (route === '/api/relay') return {status:'fresh',conversationId:marker+'CONVERSATION',links:[{messageId:marker+'MESSAGE',taskId:marker+'REFERENCE'}],error:null};
  if (route === '/api/health') return { state: marker + 'HEALTH', persistence: 'sqlite', url: marker + 'URL', activity: { source: 'disposable_fixture' } };
  if (route === '/api/worker-activity') return { state: 'ok', observedAt, workers: [{ runId: marker + 'WORKER' }] };
  if (route === '/api/service-connections') return { schemaVersion: 'mesh-service-connections/v1', services: ['relay', 'inference', 'agent', 'mind'].map(id => ({ id, label: marker + 'SERVICE', status: 'fresh', source: 'disposable_fixture', elapsedMs: 1, observedAt, errors: [] })) };
  if (route === '/api/inference-observation') return { schemaVersion: 'mesh-inference-observation/v1', status: 'fresh', observedAt, errors: [], nodes: [{ id: 'synthetic', label: marker + 'NODE', status: 'fresh', source: 'disposable_fixture', observedAt, capabilities: { observation: 'fixture' }, hardware: { expected: marker + 'HARDWARE', observed: marker + 'MEASUREMENT' }, models: [marker + 'MODEL'] }] };
  if (route === '/api/node-probes') return { schemaVersion: 'mesh-node-probes/v1', source: 'disposable_transport', observedAt,
    limits: { freshMs: 30000, staleGraceMs: 60000 }, nodes: ['pc', 'laptop'].map(id => ({ id, label: marker + 'TAILNET',
      dnsName: marker + 'DNS', tailscaleIp: marker + 'IP', status: 'ready', lastProbeAt: observedAt, lastSuccessAt: observedAt,
      observationAvailability: 'available', tailscaleOnline: true, errors: [] })) };
  return {};
}

function harness({ stored, admissionDelay, recovery = false } = {}) {
  const writes = []; const elements = [];
  class Element {
    constructor() { this.children = []; this.attrs = {}; this.events = {}; this.value = ''; this.disabled = false; this.hidden = false; this.resets = 0; this.text = ''; elements.push(this); }
    set textContent(value) { this.text = String(value); writes.push(this.text); }
    get textContent() { return this.text; }
    setAttribute(key, value) { this.attrs[key] = value; }
    getAttribute(key) { return this.attrs[key]; }
    addEventListener(key, handler) { this.events[key] = handler; }
    append(...children) { this.children.push(...children); }
    replaceChildren(...children) { this.children = children; }
    reset() { this.resets++; for (const field of this.fields ?? []) field.value = ''; }
    focus() {}
  }
  const ids = new Map([...html.matchAll(/\bid="([^"]+)"/g)].map(match => [match[1], new Element()]));
  const forms = ['create-title', 'create-description', 'create-label', 'edit-title', 'edit-description', 'edit-label', 'toggle-status', 'reload-task', 'refresh', 'node-probes-refresh', 'proposal-command', 'propose-command', 'approve-command', 'deny-command', 'relay-text', 'relay-message-id', 'relay-send', 'relay-new', 'relay-reconnect'].map(id => ids.get(id));
  forms.push(new Element(), new Element()); // The two anonymous submit buttons.
  for (const prefix of ['create', 'edit']) ids.get(prefix + '-form').fields = ['title', 'description', 'label'].map(field => ids.get(prefix + '-' + field));
  const tabs = [...html.matchAll(/<button role="tab" id="([^"]+)" aria-controls="([^"]+)"/g)].map(match => { const element = ids.get(match[1]); element.attrs['aria-controls'] = match[2]; return element; });
  const groups = new Map(['.activity-workers', '.service-connections', '.service-status', '.inference-state', '.inference-errors', '.activity-source', '.activity-state'].map(selector => [selector, [new Element()]]));
  groups.set('.activity-state, .activity-source', [...groups.get('.activity-state'), ...groups.get('.activity-source')]);
  groups.get('.service-status')[0].attrs['data-service'] = 'relay';
  const storage = new Map(stored ? [[nonceKey, JSON.stringify(stored)]] : []);
  const clock = { now: epoch }; class FixtureDate extends Date { static now() { return clock.now; } }
  const requests = []; const intervals = []; const timers = new Map(); const events = {};
  let timerId = 0; let marker = 'SYNTHETIC_BASE_'; let bootstrapProof = proof('a'); let headerGate;
  const bodyGates = new Map(); const started = new Set(); let initialHealth = Boolean(admissionDelay);
  const context = vm.createContext({
    document: { visibilityState: 'visible', addEventListener: (event, handler) => { events[event] = handler; }, getElementById: id => ids.get(id), createElement: () => new Element(), querySelectorAll: selector => selector === '[role=tab]' ? tabs : selector.startsWith('form ') ? forms : groups.get(selector) ?? [] },
    navigator: { onLine: true }, window: { addEventListener: (event, handler) => { events[event] = handler; } },
    sessionStorage: { getItem: key => storage.get(key), setItem: (key, value) => storage.set(key, value), removeItem: key => storage.delete(key) },
    AbortController, TypeError, Date: FixtureDate,
    setTimeout: callback => { timers.set(++timerId, callback); return timerId; }, clearTimeout: id => timers.delete(id), setInterval: callback => { intervals.push(callback); },
    fetch: async (route, options) => {
      requests.push({ route, options });
      if (headerGate?.route === route) { const gate = headerGate; headerGate = undefined; gate.started = true; return gate.promise; }
      if (route.endsWith('/bootstrap')) return recovery ? response(403, {}) : response(201, bootstrapProof);
      if (route.endsWith('/recovery-challenge')) return response(200, { challenge: token('z'), expiresAt: epoch + 30000 });
      if (route.endsWith('/recovery-complete')) return response(201, bootstrapProof);
      if (route.endsWith('/logout')) return response(204, undefined, () => { throw new Error('204 body must not be read'); });
      if (route === '/api/synthetic-revocation') return response(403, {});
      const body = bodyFor(route, marker);
      let gate = bodyGates.get(route);
      if (route === '/api/health' && initialHealth) { gate = admissionDelay; initialHealth = false; }
      if (gate) { bodyGates.delete(route); return response(200, body, () => { started.add(route); return gate.promise.then(() => JSON.stringify(body)); }); }
      return response(200, body);
    }
  });
  vm.runInContext(source.replace(/export /g, ''), context);
  return { ids, groups, forms, storage, clock, requests, intervals, timers, writes, events, context, started,
    run: code => vm.runInContext(code, context),
    setMarker: value => { marker = value; }, setBootstrap: value => { bootstrapProof = value; },
    delayBodies: () => { const gates = routes.map(route => { const gate = deferred(); bodyGates.set(route, gate); return gate; }); return () => gates.forEach(gate => gate.resolve()); },
    delayHeader: route => { const gate = { ...deferred(), route, started: false }; headerGate = gate; return gate; }
  };
}

async function admittedUI() {
  const ui = harness();
  assert.equal(ui.requests.length, 0, 'bootstrap is explicit');
  ui.ids.get('demo-start').events.click(); await flush();
  assert.equal(ui.run('admitted'), true); assert.equal(ui.ids.get('refresh').disabled, false);
  assert.equal(ui.ids.get('tasks').children.length, 1);
  assert.equal(ui.ids.get('relay-links').children.length, 1);
  assert.equal(ui.ids.get('tailnet-nodes').children.length, 2);
  ui.ids.get('relay-text').value = 'SYNTHETIC_RELAY_DRAFT'; ui.ids.get('relay-message-id').value = 'SYNTHETIC_RELAY_ID';
  ui.ids.get('tasks').children[0].events.click();
  ui.ids.get('create-title').value = 'SYNTHETIC_DRAFT';
  assert.equal(ui.ids.get('edit-title').value, 'SYNTHETIC_BASE_TASK');
  assert.match(ui.ids.get('proposal-value').textContent, /SYNTHETIC_BASE_COMMAND/);
  assert.match(ui.ids.get('proposal-state').textContent, /Pending.*not executed/);
  return ui;
}
function assertCleared(ui) {
  assert.equal(ui.run('admitted'), false); assert.equal(ui.run('demo'), undefined); assert.equal(ui.run('selected'), undefined);
  assert.equal(ui.storage.size, 0); assert.equal(ui.ids.get('tasks').children.length, 0);
  for (const id of ['total-count', 'open-count', 'done-count']) assert.equal(ui.ids.get(id).textContent, 'Unknown');
  for (const prefix of ['create', 'edit']) {
    assert.ok(ui.ids.get(prefix + '-form').resets >= 2);
    for (const field of ['title', 'description', 'label']) assert.equal(ui.ids.get(prefix + '-' + field).value, '');
  }
  assert.equal(ui.ids.get('edit-form').hidden, true); assert.equal(ui.ids.get('no-selection').hidden, false);
  assert.equal(ui.ids.get('task-identity').textContent, ''); assert.equal(ui.ids.get('task-status').textContent, '');
  assert.equal(ui.ids.get('proposal-form').hidden, true);
  assert.equal(ui.ids.get('proposal-value').textContent, ''); assert.equal(ui.ids.get('proposal-state').textContent, '');
  assert.equal(ui.ids.get('execution-result').textContent, '');
  assert.equal(ui.ids.get('relay-links').children.length, 0);
  assert.equal(ui.ids.get('relay-text').value, ''); assert.equal(ui.ids.get('relay-message-id').value, '');
  assert.equal(ui.run('relaySnapshot'), undefined);
  assert.equal(ui.run('nodeProbeSnapshot'), undefined);
  assert.match(ui.ids.get('tailnet-nodes').children[0].textContent, /unavailable/);
  assert.equal(ui.ids.get('proposal-command').children.length, 0);
  assert.equal(ui.forms.every(element => element.disabled), true);
  assert.equal(ui.ids.get('app-state').textContent, 'Private app status unavailable.');
  assert.equal(ui.groups.get('.activity-workers')[0].children.length, 0);
  assert.match(ui.groups.get('.activity-state')[0].textContent, /unavailable/);
  assert.match(ui.groups.get('.activity-source')[0].textContent, /unavailable/);
  assert.match(ui.groups.get('.service-connections')[0].children[0].textContent, /unavailable/);
  assert.match(ui.groups.get('.inference-state')[0].textContent, /unavailable/);
  assert.match(ui.ids.get('inference-nodes').children[0].textContent, /unknown/);
}
function assertNoLateWrites(ui) { assert.equal(ui.writes.some(value => value.includes('SYNTHETIC_LATE_')), false, 'late private tasks/observations never written, even transiently'); }
async function replaceSession(ui) {
  ui.run("clearPrivate('Synthetic fixture replacement');");
  ui.setMarker('SYNTHETIC_CURRENT_'); ui.setBootstrap(proof('b'));
  ui.ids.get('demo-start').events.click(); await flush();
  assert.equal(ui.run('admitted'), true); assert.equal(ui.run('demo.csrfToken'), token('b'));
}
function assertNewSession(ui) {
  assert.equal(ui.run('admitted'), true); assert.equal(ui.run('demo.csrfToken'), token('b'));
  assert.equal(JSON.parse(ui.storage.get(nonceKey)).csrfToken, token('b'));
  assert.equal(ui.ids.get('total-count').textContent, '1'); assert.equal(ui.ids.get('refresh').disabled, false);
  assert.equal(ui.ids.get('tasks').children[0].children[0].textContent, 'SYNTHETIC_CURRENT_TASK');
  assert.match(ui.ids.get('app-state').textContent, /SYNTHETIC_CURRENT_HEALTH/);
}

test('PRIVACY01: valid current proof renders tasks/observations; explicit bootstrap, same-tab reload, HEAD and 204 preserved', async () => {
  const ui = await admittedUI();
  assert.match(ui.ids.get('app-state').textContent, /SYNTHETIC_BASE_HEALTH/);
  assert.match(ui.groups.get('.activity-workers')[0].children[0].textContent, /SYNTHETIC_BASE_WORKER/);
  assert.match(ui.groups.get('.service-connections')[0].children[0].textContent, /SYNTHETIC_BASE_SERVICE/);
  assert.match(ui.ids.get('inference-nodes').children[0].children[0].textContent, /SYNTHETIC_BASE_NODE/);
  assert.equal(ui.requests[0].options.headers['X-Trial-CSRF'], undefined);
  const gate = ui.delayHeader('/api/tasks');
  const head = ui.run("api('/api/tasks', {method:'HEAD'})"); await flush();
  gate.resolve(response(200, {}, () => { throw new Error('HEAD body must not be read'); }));
  assert.equal(await head, undefined);
  assert.equal(await ui.run("api('/api/trial-session/logout', {method:'POST',body:'{}'})"), undefined);
  assert.ok(ui.requests.slice(1).every(request => request.options.credentials === 'same-origin' && request.options.cache === 'no-store' && request.options.headers['X-Trial-CSRF'] === token('a')));
  const reloaded = harness({ stored: proof('a') }); await flush();
  assert.equal(reloaded.run('admitted'), true); assert.equal(reloaded.requests.some(request => request.route.endsWith('/bootstrap')), false);
  assert.deepEqual(Object.keys(JSON.parse(reloaded.storage.get(nonceKey))).sort(), ['csrfToken', 'expiresAt']);
  assert.equal(ui.timers.size, 0); assert.equal(reloaded.timers.size, 0);
});

for (const transition of ['expiry', 'observed-403', 'logout', 'replacement']) {
  test(`PRIVACY01: delayed complete refresh bodies fenced after ${transition}`, async () => {
    const ui = await admittedUI(); const staleButton = ui.ids.get('tasks').children[0];
    ui.setMarker('SYNTHETIC_LATE_'); const release = ui.delayBodies();
    const before = ui.requests.length; const pending = ui.run('refresh()'); await flush();
    assert.deepEqual([...ui.started].sort(), [...routes].sort());
    assert.equal(ui.requests.length - before, routes.length, 'one request per refreshed resource including Relay and cached node probes');
    if (transition === 'expiry') ui.clock.now = epoch + 60000;
    if (transition === 'observed-403') await assert.rejects(ui.run("api('/api/synthetic-revocation')"), /authorization rejected/);
    if (transition === 'logout') { ui.ids.get('demo-end').events.click(); await flush(); }
    if (transition === 'replacement') await replaceSession(ui);
    release(); await pending; await flush(); assertNoLateWrites(ui);
    if (transition === 'replacement') {
      assertNewSession(ui); staleButton.events.click(); assertNewSession(ui);
      assert.equal(ui.ids.get('edit-form').hidden, true, 'old task closure cannot select into replacement proof');
    } else {
      assertCleared(ui); const requests = ui.requests.length;
      await assert.rejects(ui.run("api('/api/tasks')"), /admission required/);
      assert.equal(ui.requests.length, requests, 'stale proof cannot send a private request');
    }
    assert.equal(ui.timers.size, 0);
  });
}

for (const status of [401, 403]) {
  test(`PRIVACY01: old ${status} response cannot revoke newer valid proof`, async () => {
    const ui = await admittedUI(); const gate = ui.delayHeader('/api/tasks');
    const pending = ui.run("api('/api/tasks')"); const rejected = assert.rejects(pending, /changed or expired/);
    await flush(); assert.equal(gate.started, true); await replaceSession(ui);
    gate.resolve(response(status, {})); await rejected; assertNewSession(ui); assertNoLateWrites(ui);
  });
}
for (const kind of ['network', 'abort']) {
  test(`PRIVACY01: old ${kind} failure during body read cannot clear replacement`, async () => {
    const ui = await admittedUI(); const gate = ui.delayHeader('/api/tasks'); const bodyGate = deferred();
    const pending = ui.run("api('/api/tasks')"); const rejected = assert.rejects(pending, /unreachable or observation timed out/);
    gate.resolve(response(200, {}, () => { ui.started.add('/api/tasks'); return bodyGate.promise; }));
    await flush(); assert.equal(ui.started.has('/api/tasks'), true); await replaceSession(ui);
    const error = kind === 'network' ? new TypeError('Synthetic network failure') : Object.assign(new Error('Synthetic abort'), { name: 'AbortError' });
    bodyGate.reject(error); await rejected; assertNewSession(ui); assert.equal(ui.timers.size, 0);
  });
}
test('PRIVACY01: pending old logout finally cannot wipe newer session', async () => {
  const ui = await admittedUI(); const gate = ui.delayHeader('/api/trial-session/logout');
  ui.ids.get('demo-end').events.click(); await flush(); assert.equal(gate.started, true);
  // Install an already verified replacement as a controlled concurrency fixture;
  // the old action still owns busy, so a second UI click would be intentionally ignored.
  ui.run(`clearPrivate('Synthetic replacement while old logout pending'); demo = {csrfToken:'${token('b')}',expiresAt:${epoch + 60000}}; admitted = true; sessionStorage.setItem('${nonceKey}', JSON.stringify(demo));`);
  ui.setMarker('SYNTHETIC_CURRENT_'); await ui.run('refresh()');
  gate.resolve(response(204)); await flush(); assertNewSession(ui); assert.equal(ui.timers.size, 0);
});

for (const mode of ['explicit', 'reload']) {
  for (const transition of ['expiry', 'observed-403', 'logout', 'replacement']) {
    test(`PRIVACY01: ${mode} admission health body delayed across ${transition} cannot admit stale proof`, async () => {
      const gate = deferred(); const ui = harness({ stored: mode === 'reload' ? proof('a') : undefined, admissionDelay: gate });
      if (mode === 'explicit') ui.ids.get('demo-start').events.click();
      await flush(); assert.equal(ui.started.has('/api/health'), true); assert.equal(ui.run('admitted'), false);
      if (transition === 'expiry') ui.clock.now = epoch + 60000;
      if (transition === 'observed-403') await assert.rejects(ui.run("api('/api/synthetic-revocation')"), /authorization rejected/);
      if (transition === 'logout') ui.run("clearPrivate('Synthetic local logout during admission');");
      if (transition === 'replacement') {
        ui.run(`clearPrivate('Synthetic replaced admission'); demo = {csrfToken:'${token('b')}',expiresAt:${epoch + 60000}}; admitted = true; sessionStorage.setItem('${nonceKey}', JSON.stringify(demo));`);
        ui.setMarker('SYNTHETIC_CURRENT_'); await ui.run('refresh()');
      }
      gate.resolve(); await flush();
      if (transition === 'replacement') assertNewSession(ui); else assertCleared(ui);
      assert.equal(ui.timers.size, 0);
    });
  }
}

test('PRIVACY01: local expiry timer clears an already rendered private board and observations', async () => {
  const ui = await admittedUI(); const requests = ui.requests.length;
  ui.clock.now = epoch + 60000; ui.intervals[0](); assertCleared(ui);
  assert.equal(ui.requests.length, requests, 'local expiry requires no verification request');
});

test('PRIVACY01: approval controls follow current execution state and raw results clear on expiry', async () => {
  const ui = await admittedUI();
  assert.equal(ui.ids.get('approve-command').disabled, false); assert.equal(ui.ids.get('deny-command').disabled, false);
  ui.run("selectTask({...selected, proposalStatus:'running', execution:{id:'SYNTHETIC_RUN',state:'running',result:null}})");
  assert.equal(ui.ids.get('approve-command').disabled, true); assert.equal(ui.ids.get('deny-command').disabled, true);
  assert.equal(ui.ids.get('propose-command').disabled, true);
  assert.match(ui.ids.get('execution-result').textContent, /result not yet known/);
  ui.run("selectTask({...selected, proposalStatus:'completed', execution:{id:'SYNTHETIC_RUN',state:'completed',result:{rootExitCode:0,cleanupVerified:true,error:null,stdout:'SYNTHETIC_PRIVATE_STDOUT <script>',stderr:'SYNTHETIC_PRIVATE_STDERR'}}})");
  assert.equal(ui.ids.get('propose-command').disabled, false); assert.equal(ui.ids.get('approve-command').disabled, true);
  assert.match(ui.ids.get('execution-result').textContent, /SYNTHETIC_PRIVATE_STDOUT <script>/);
  assert.equal(ui.ids.get('execution-result').children.length, 0, 'raw output is text only');
  ui.clock.now = epoch + 60000; ui.intervals[0](); assertCleared(ui);
});

test('PRIVACY01: stale revision disables proposal decisions until the current task is loaded', async () => {
  const ui = await admittedUI(); const gate = ui.delayHeader('/api/tasks/1/approve');
  const pending = ui.run("api('/api/tasks/1/approve',{method:'POST',body:'{\"revision\":1}'})");
  gate.resolve(response(409, { error: 'Reload current task.' })); await assert.rejects(pending, /Reload/);
  assert.equal(ui.ids.get('approve-command').disabled, true); assert.equal(ui.ids.get('deny-command').disabled, true);
  assert.equal(ui.ids.get('propose-command').disabled, true);
  await ui.run('loadTasks()');
  assert.equal(ui.ids.get('approve-command').disabled, false); assert.equal(ui.ids.get('deny-command').disabled, false);
});


test('PRIVACY01: deliberate two-step recovery keeps challenge in RAM and verifies health before private admission', async () => {
  const ui = harness({ recovery: true });
  assert.equal(ui.requests.length, 0);
  ui.ids.get('workroom-session-start').events.click(); await flush();
  assert.equal(ui.run('admitted'), true);
  assert.deepEqual(ui.requests.slice(0, 4).map(r => r.route), [
    '/api/trial-session/bootstrap', '/api/trial-session/recovery-challenge', '/api/trial-session/recovery-complete', '/api/health'
  ]);
  assert.equal(ui.requests[1].options.headers['X-Trial-CSRF'], undefined);
  assert.equal(ui.requests[2].options.headers['X-Trial-CSRF'], token('z'));
  assert.ok(ui.requests.every(r => r.options.cache === 'no-store' && r.options.credentials === 'same-origin'));
  assert.equal([...ui.storage.values()].some(value => value.includes(token('z'))), false);
  assert.equal(ui.writes.some(value => value.includes(token('z'))), false);
});

for (const step of ['recovery-challenge', 'recovery-complete']) for (const stage of ['fetch', 'body']) {
  for (const transition of ['hidden-resume', 'freeze-resume', 'replacement']) {
    test(`PRIVACY01: pending ${step} ${stage} across ${transition} cannot admit or render`, async () => {
      const ui = harness({ recovery: true });
      const route = '/api/trial-session/' + step;
      const gate = ui.delayHeader(route); const bodyGate = deferred();
      const reply = step === 'recovery-challenge' ? { challenge: token('z'), expiresAt: epoch + 30000 } : proof('a');
      ui.ids.get('demo-start').events.click(); await flush(); assert.equal(gate.started, true);
      if (stage === 'body') { gate.resolve(response(200, reply, () => { ui.started.add(route); return bodyGate.promise.then(() => JSON.stringify(reply)); })); await flush(); assert.ok(ui.started.has(route)); }
      if (transition === 'hidden-resume') {
        ui.context.document.visibilityState = 'hidden'; ui.events.visibilitychange();
        ui.context.document.visibilityState = 'visible'; ui.events.visibilitychange();
      } else if (transition === 'freeze-resume') { ui.events.freeze(); ui.events.resume(); }
      else {
        ui.run(`clearPrivate('Replacement fixture'); demo = {csrfToken:'${token('b')}',expiresAt:${epoch + 60000}}; admitted = true; sessionStorage.setItem('${nonceKey}', JSON.stringify(demo));`);
        ui.setMarker('SYNTHETIC_CURRENT_'); await ui.run('refresh()');
      }
      const before = ui.requests.length;
      if (stage === 'fetch') gate.resolve(response(200, reply)); else bodyGate.resolve();
      await flush(); assert.equal(ui.requests.length, before, 'stale handshake must stop before next step/private verification');
      if (transition === 'replacement') assertNewSession(ui); else assertCleared(ui);
      assert.equal(ui.storage.size, transition === 'replacement' ? 1 : 0);
      assert.equal(ui.timers.size, 0);
    });
  }
}
