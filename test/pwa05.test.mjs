import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import http from 'node:http';
import { readFile } from 'node:fs/promises';
import { createHash, randomUUID } from 'node:crypto';
import { startApp } from '../pwa-server.mjs';
import { PUBLIC_ASSETS, MAX_ENTRIES, getPublicEntry, makePopulationRequest } from '../public/shell-cache-policy.mjs';

const source = await readFile(new URL('../public/app.js', import.meta.url), 'utf8');
const html = await readFile(new URL('../public/index.html', import.meta.url), 'utf8');
const nonceKey = 'mesh.synthetic-demo.proof.v1';
const routes = ['/api/health', '/api/tasks', '/api/worker-activity', '/api/service-connections', '/api/inference-observation'];
const epoch = 1800000000000;
const token = character => character.repeat(43);
const proof = character => ({ csrfToken: token(character), expiresAt: epoch + 60000 });
const deferred = () => { let resolve, reject; const promise = new Promise((yes, no) => { resolve = yes; reject = no; }); return { promise, resolve, reject }; };
const flush = async () => { for (let i = 0; i < 8; i++) await new Promise(resolve => setImmediate(resolve)); };
const response = (status, body, text) => ({ status, ok: status >= 200 && status < 300, text: text ?? (async () => JSON.stringify(body)) });

function bodyFor(route, marker) {
  const observedAt = new Date(epoch).toISOString();
  if (route === '/api/tasks') return { tasks: [{ id: 1, revision: 1, title: marker + 'TASK', description: marker + 'DESCRIPTION', label: marker + 'LABEL', status: 'open' }] };
  if (route === '/api/health') return { state: marker + 'HEALTH', persistence: 'sqlite', url: marker + 'URL', activity: { source: 'disposable_fixture' } };
  if (route === '/api/worker-activity') return { state: 'ok', observedAt, workers: [{ runId: marker + 'WORKER' }] };
  if (route === '/api/service-connections') return { schemaVersion: 'mesh-service-connections/v1', services: ['relay', 'inference', 'agent', 'mind'].map(id => ({ id, label: marker + 'SERVICE', status: 'fresh', source: 'disposable_fixture', elapsedMs: 1, observedAt, errors: [] })) };
  if (route === '/api/inference-observation') return { schemaVersion: 'mesh-inference-observation/v1', status: 'fresh', observedAt, errors: [], nodes: [{ id: 'synthetic', label: marker + 'NODE', status: 'fresh', source: 'disposable_fixture', observedAt, capabilities: { observation: 'fixture' }, hardware: { expected: marker + 'HARDWARE', observed: marker + 'MEASUREMENT' }, models: [marker + 'MODEL'] }] };
  return {};
}

function harness({ stored, admissionDelay, initiallyHidden = false } = {}) {
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
  const forms = ['create-title', 'create-description', 'create-label', 'edit-title', 'edit-description', 'edit-label', 'toggle-status', 'reload-task', 'refresh'].map(id => ids.get(id));
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
    document: { visibilityState: initiallyHidden ? 'hidden' : 'visible', addEventListener: (event, handler) => { events[event] = handler; }, getElementById: id => ids.get(id), createElement: () => new Element(), querySelectorAll: selector => selector === '[role=tab]' ? tabs : selector.startsWith('form ') ? forms : groups.get(selector) ?? [] },
    navigator: { onLine: true }, window: { addEventListener: (event, handler) => { events[event] = handler; } },
    sessionStorage: { getItem: key => storage.get(key), setItem: (key, value) => storage.set(key, value), removeItem: key => storage.delete(key) },
    AbortController, TypeError, Date: FixtureDate,
    setTimeout: callback => { timers.set(++timerId, callback); return timerId; }, clearTimeout: id => timers.delete(id), setInterval: callback => { intervals.push(callback); },
    fetch: async (route, options) => {
      requests.push({ route, options });
      if (headerGate?.route === route) { const gate = headerGate; headerGate = undefined; gate.started = true; return gate.promise; }
      if (route.endsWith('/bootstrap')) return response(201, bootstrapProof);
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
  ui.ids.get('tasks').children[0].events.click();
  ui.ids.get('create-title').value = 'SYNTHETIC_DRAFT';
  assert.equal(ui.ids.get('edit-title').value, 'SYNTHETIC_BASE_TASK');
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


const sha = bytes => createHash('sha256').update(bytes).digest('hex');
const originalHash = '09d2a0c568ad6ecba970a7894a5855024b28a4a6bc0afbd2719ff547a448c7e5';
const immutableHashes = {
  "test/trial-session.test.mjs": "fbe41185c22a01036d4cf95d5f4a83e3eb5ae01bc35c4d873a2f121d5344b3a6",
  "server.mjs": "09d2a0c568ad6ecba970a7894a5855024b28a4a6bc0afbd2719ff547a448c7e5",
  "test/session-app.test.mjs": "2c05b725b2787dfe4cf9b60ea978d59f5559c6ba02b9fddc9e7d3ae1d66012b7",
  "test/ui.test.mjs": "c3816b644dd22b2b37417cbf302765ebaa744c0d0abc8f50d05c1e70f5b7f742",
  "test/privacy01.test.mjs": "8b9146aeea83aeda15ceed968ba15ea4e54d1f4ef00c6da3e06f1cbb7a6d5bf5",
  "package.json": "3ca8ce15b971263fd433d29d5cd2c616c9767f42b2adb91bc59e4758fe63a186"
};
const originalMap = "const staticFiles = new Map([['/', ['public/index.html', 'text/html']], ['/app.js', ['public/app.js', 'text/javascript']], ['/styles.css', ['public/styles.css', 'text/css']]]);";
const newMap = "const staticFiles = new Map([['/', ['public/index.html', 'text/html']], ['/app.js', ['public/app.js', 'text/javascript']], ['/styles.css', ['public/styles.css', 'text/css']], ['/sw.js', ['public/sw.js', 'text/javascript']], ['/shell-cache-policy.mjs', ['public/shell-cache-policy-browser-v2.mjs', 'text/javascript']], ['/manifest.webmanifest', ['public/manifest.webmanifest', 'application/manifest+json']], ['/icon.svg', ['public/icon.svg', 'image/svg+xml']], ['/pwa-register.mjs', ['public/pwa-register.mjs', 'text/javascript']]]);";
const cacheRoot = 'D:/tmp/fleet-consolidation-20260929/build/mesh-pwa-cache-module-v1/';
const expectedCSP = "default-src 'self'; connect-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'";
async function fixture(t) {
  const app = await startApp({ dataDir: `test/app03-pwa05-${process.pid}-${randomUUID()}` });
  t.after(() => app.close()); return app;
}
function request(app, route, { method = 'GET', headers = {}, body } = {}) {
  return new Promise((resolve, reject) => {
    const req = http.request(app.url + route, { method, headers }, res => {
      const chunks = []; res.on('data', c => chunks.push(c));
      res.on('end', () => resolve({ status: res.statusCode, headers: res.headers, bytes: Buffer.concat(chunks), json() { return JSON.parse(this.bytes.toString()); } }));
    });
    req.on('error', reject); req.end(body);
  });
}
async function admit(app) {
  const res = await request(app, '/api/trial-session/bootstrap', { method: 'POST', headers: { Origin: app.url, 'Content-Type': 'application/json' }, body: '{}' });
  assert.equal(res.status, 201); assert.equal(res.headers['cache-control'], 'no-store');
  return { Cookie: res.headers['set-cookie'][0].split(';')[0], 'X-Trial-CSRF': res.json().csrfToken };
}
function denial(res, status) {
  assert.equal(res.status, status); assert.equal(res.bytes.length, 0);
  assert.equal(res.headers['cache-control'], 'no-store');
}

test('PWA05: original backend unchanged; copied backend differs only in exact static map bytes', async () => {
  const original = await readFile(new URL('../server.mjs', import.meta.url));
  const copied = await readFile(new URL('../pwa-server.mjs', import.meta.url));
  assert.equal(sha(original), originalHash);
  const text = copied.toString('utf8');
  assert.equal(text.split(newMap).length, 2);
  assert.deepEqual(Buffer.from(text.replace(newMap, originalMap)), original);
  for (const [file, hash] of Object.entries(immutableHashes)) assert.equal(sha(await readFile(new URL('../' + file, import.meta.url))), hash, file);
});

test('PWA05: four byte-identical CACHE04 assets; unchanged seven paths exclude registration and every private route', async () => {
  const contract = JSON.parse(await readFile(cacheRoot + 'CACHE04-CONTRACT.json', 'utf8'));
  for (const file of ['sw.js','shell-cache-policy.mjs','manifest.webmanifest','icon.svg']) {
    assert.deepEqual(await readFile(new URL('../public/' + file, import.meta.url)), await readFile(cacheRoot + 'public/' + file), file);
  }
  assert.deepEqual(Object.keys(PUBLIC_ASSETS), contract.publicPaths); assert.equal(MAX_ENTRIES, 7);
  const origin = 'http://127.0.0.1:12345';
  for (const route of ['/pwa-register.mjs','/api/tasks','/api/trial-session/bootstrap','/api/trial-session/logout','/api/health']) {
    const request = new Request(origin + route);
    assert.equal(getPublicEntry(request, origin), null);
    assert.throws(() => makePopulationRequest(request, origin), /outside/);
  }
  const request = makePopulationRequest(new Request(origin + '/app.js'), origin);
  assert.equal(request.credentials, 'omit'); assert.equal(request.cache, 'no-store'); assert.equal(request.referrer, '');
  assert.deepEqual([...request.headers.keys()], ['accept']);
  assert.equal(getPublicEntry(new Request(origin + '/app.js', { headers: { 'X-Trial-CSRF': token('a') } }), origin), null);
  let listener;
  const sw = await readFile(new URL('../public/sw.js', import.meta.url), 'utf8');
  vm.runInNewContext(sw.replace(/^import[^\n]+\n/, ''), {
    getPublicEntry, handlePublicFetch: () => { throw new Error('Private fetch must never enter public handler'); },
    self: { location: { origin }, addEventListener: (name, handler) => { assert.equal(name, 'fetch'); listener = handler; } }
  });
  for (const route of ['/api/tasks','/api/trial-session/logout','/pwa-register.mjs']) listener({
    request: new Request(origin + route), respondWith: () => { throw new Error('Private/network-only request intercepted'); }
  });
});

test('PWA05: real copied server serves exact public bodies, MIME, unchanged CSP, no cookies and external registration linkage', async t => {
  const app = await fixture(t);
  const entries = [
    ['/', 'index.html', 'text/html'], ['/app.js','app.js','text/javascript'], ['/styles.css','styles.css','text/css'],
    ['/sw.js','sw.js','text/javascript'], ['/shell-cache-policy.mjs','shell-cache-policy-browser-v2.mjs','text/javascript'],
    ['/manifest.webmanifest','manifest.webmanifest','application/manifest+json'], ['/icon.svg','icon.svg','image/svg+xml'],
    ['/pwa-register.mjs','pwa-register.mjs','text/javascript']
  ];
  for (const [route, file, type] of entries) {
    const res = await request(app, route);
    assert.equal(res.status, 200); assert.equal(res.headers['content-type'], type + '; charset=utf-8');
    assert.equal(res.headers['cache-control'], 'public, max-age=0'); assert.equal(res.headers['content-security-policy'], expectedCSP);
    for (const header of ['set-cookie','set-cookie2','vary','location','pragma']) assert.equal(res.headers[header], undefined);
    assert.deepEqual(res.bytes, await readFile(new URL('../public/' + file, import.meta.url)));
    const head = await request(app, route, { method: 'HEAD' }); assert.equal(head.status, 200); assert.equal(head.bytes.length, 0);
  }
  const root = (await request(app, '/')).bytes.toString();
  assert.match(root, /<script type="module" src="\/pwa-register\.mjs"><\/script>/);
  assert.match(root, /<link rel="manifest" href="\/manifest\.webmanifest">/);
  assert.match(root, /<link rel="icon" href="\/icon\.svg"/);
  for (const script of root.matchAll(/<script\b([^>]*)>([\s\S]*?)<\/script>/g)) { assert.match(script[1], /\bsrc="/); assert.equal(script[2], ''); }
  assert.doesNotMatch(root, /csrfToken|expiresAt|mesh\.synthetic-demo\.proof|Set-Cookie/);
  const registration = (await request(app, '/pwa-register.mjs')).bytes.toString();
  assert.doesNotMatch(registration, /csrf|sessionStorage|localStorage|indexedDB|\/api\/|credentials|caches\./i);
  assert.doesNotMatch(source, /serviceWorker|caches\.|\bimport\b/);
  denial(await request(app, '/sw.js', { headers: { Host: 'localhost' } }), 403);
});

test('PWA05: real copied server keeps private proof denials/no-store and authenticated task/logout flow', async t => {
  const app = await fixture(t);
  for (const route of ['/api/tasks','/api/health']) denial(await request(app, route), 401);
  denial(await request(app, '/api/trial-session/logout'), 405);
  denial(await request(app, '/api/trial-session/logout', { method: 'POST', headers: { Origin: app.url, 'Content-Type': 'application/json' }, body: '{}' }), 401);
  const proof = await admit(app);
  for (const route of ['/api/tasks','/api/health']) {
    denial(await request(app, route, { headers: { Cookie: proof.Cookie } }), 403);
    denial(await request(app, route, { headers: { ...proof, 'X-Trial-CSRF': 'wrong' } }), 403);
    const res = await request(app, route, { headers: proof }); assert.equal(res.status, 200); assert.equal(res.headers['cache-control'], 'no-store');
  }
  const mutation = { method: 'POST', headers: { ...proof, Origin: app.url, 'Content-Type': 'application/json' }, body: JSON.stringify({ title: 'PWA05 owned synthetic task' }) };
  const made = await request(app, '/api/tasks', mutation); assert.equal(made.status, 201); assert.equal(made.headers['cache-control'], 'no-store');
  assert.equal((await request(app, '/api/tasks', { headers: proof })).json().tasks[0].title, 'PWA05 owned synthetic task');
  const logout = await request(app, '/api/trial-session/logout', { ...mutation, body: '{}' }); denial(logout, 204);
  denial(await request(app, '/api/tasks', { headers: proof }), 401);
});

test('PWA05: production registration module handles absence/rejection and only registers same-origin assigned loopback module scope', async () => {
  const registration = (await readFile(new URL('../public/pwa-register.mjs', import.meta.url), 'utf8')).replace(/export /g, '');
  for (const mode of ['success','absent','rejected','external','unassigned','https','localhost']) {
    const calls = []; const logs = [];
    const navigator = mode === 'absent' ? {} : { serviceWorker: { register: async (...args) => { calls.push(args); if (mode === 'rejected') throw new Error('Fixture rejection'); } } };
    const href = mode === 'external' ? 'http://example.test:12345/' : mode === 'unassigned' ? 'http://127.0.0.1/' : mode === 'https' ? 'https://127.0.0.1:12345/' : mode === 'localhost' ? 'http://localhost:12345/' : 'http://127.0.0.1:12345/';
    vm.runInNewContext(registration, { URL, location: { href }, navigator, console: { info: (...args) => logs.push(args.join(' ')) } });
    await flush(); assert.equal(logs.length, 1);
    if (['success','rejected'].includes(mode)) {
      assert.equal(calls.length, 1); assert.equal(calls[0][0], 'http://127.0.0.1:12345/sw.js');
      assert.equal(calls[0][1].type, 'module'); assert.equal(calls[0][1].scope, '/');
    } else assert.equal(calls.length, 0);
    assert.match(logs[0], mode === 'success' ? /registered: control and offline readiness still require verification/ : /unavailable:/);
  }
});

function suspend(ui, event) {
  if (event === 'visibilitychange') ui.context.document.visibilityState = 'hidden';
  ui.events[event]();
}
function resume(ui, event) {
  ui.context.document.visibilityState = 'visible'; ui.events[event]();
}
for (const [hide, show] of [['visibilitychange','visibilitychange'],['pagehide','pageshow'],['freeze','resume']]) {
  test(`PWA05: ${hide}/${show} synchronously clears rendered private state/saved proof and fences every delayed body`, async () => {
    const ui = await admittedUI(); const staleButton = ui.ids.get('tasks').children[0];
    ui.run(`savedDemo = {csrfToken:'${token('a')}',expiresAt:${epoch + 60000}};`);
    ui.setMarker('SYNTHETIC_LATE_'); const release = ui.delayBodies(); const pending = ui.run('refresh()');
    await flush(); assert.deepEqual([...ui.started].sort(), [...routes].sort());
    const requests = ui.requests.length; const generation = ui.run('generation');
    suspend(ui, hide); assertCleared(ui); assert.equal(ui.run('savedDemo'), undefined); assert.equal(ui.run('generation'), generation + 1);
    assert.equal(ui.ids.get('demo-start').disabled, true); assert.equal(ui.requests.length, requests);
    resume(ui, show); assertCleared(ui); assert.equal(ui.run('savedDemo'), undefined);
    assert.equal(ui.ids.get('demo-start').disabled, false); assert.equal(ui.requests.length, requests, 'resume has no automatic proof restoration or network effect');
    release(); await pending; await flush(); assertCleared(ui); assertNoLateWrites(ui);
    staleButton.events.click(); assertCleared(ui);
    await assert.rejects(ui.run("api('/api/tasks')"), /admission required/); assert.equal(ui.requests.length, requests);
    ui.ids.get('demo-start').events.click(); await flush(); assert.equal(ui.run('admitted'), true);
    assert.equal(ui.requests.filter(request => request.route.endsWith('/logout')).length, 0);
    assert.equal(ui.timers.size, 0);
  });
}

test('PWA05: initially hidden page discards stored proof before any admission request', async () => {
  const ui = harness({ stored: proof('a'), initiallyHidden: true });
  assertCleared(ui); assert.equal(ui.run('savedDemo'), undefined); assert.equal(ui.requests.length, 0);
  resume(ui, 'pageshow'); assertCleared(ui); assert.equal(ui.requests.length, 0);
});

test('PWA05: stored-proof admission body pending across freeze/resume cannot restore or admit', async () => {
  const gate = deferred(); const ui = harness({ stored: proof('a'), admissionDelay: gate });
  await flush(); assert.equal(ui.started.has('/api/health'), true); const requests = ui.requests.length;
  suspend(ui, 'freeze'); assertCleared(ui); resume(ui, 'resume'); assertCleared(ui);
  gate.resolve(); await flush(); assertCleared(ui); assert.equal(ui.run('savedDemo'), undefined);
  assert.equal(ui.requests.length, requests); assert.equal(ui.timers.size, 0);
});

test('PWA05: bootstrap pending across pagehide/pageshow cannot persist proof', async () => {
  const ui = harness(); const gate = ui.delayHeader('/api/trial-session/bootstrap');
  ui.ids.get('demo-start').events.click(); await flush(); assert.equal(gate.started, true);
  suspend(ui, 'pagehide'); resume(ui, 'pageshow');
  gate.resolve(response(201, proof('a'))); await flush(); assertCleared(ui);
  assert.equal(ui.run('savedDemo'), undefined); assert.equal(ui.requests.length, 1);
});

test('PWA05: offline UI clears private state and reconnection does not restore proof or queue mutations', async () => {
  const ui = await admittedUI(); const requests = ui.requests.length;
  ui.context.navigator.onLine = false; ui.events.offline(); assertCleared(ui);
  assert.equal(ui.ids.get('demo-start').disabled, true); assert.match(ui.ids.get('message').textContent, /unavailable offline/);
  await assert.rejects(ui.run("api('/api/tasks', {method:'POST',body:'{}'})"), /admission required/);
  ui.context.navigator.onLine = true; ui.events.online(); assertCleared(ui);
  assert.equal(ui.requests.length, requests); assert.equal(ui.ids.get('demo-start').disabled, false);
});

