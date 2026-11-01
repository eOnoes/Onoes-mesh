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
function mockUI({ stored, responder } = {}) {
  const ids = new Map([...html.matchAll(/\bid="([^"]+)"/g)].map(m => [m[1], new Element()]));
  const forms = ['create-title','create-description','create-label','edit-title','edit-description','edit-label','toggle-status','reload-task','refresh'].map(id => ids.get(id));
  const tabs = [...html.matchAll(/<button role="tab" id="([^"]+)" aria-controls="([^"]+)"/g)].map(m => { const el = ids.get(m[1]); el.attrs['aria-controls'] = m[2]; return el; });
  const groups = new Map(['.activity-workers','.activity-state, .activity-source','.service-connections','.service-status','.inference-state','.inference-errors','.activity-source','.activity-state'].map(s => [s, [new Element()]]));
  const storage = new Map(stored ? [['mesh.synthetic-demo.proof.v1', JSON.stringify(stored)]] : []);
  const requests = []; const events = {}; const intervals = [];
  const context = vm.createContext({ document: { getElementById: id => ids.get(id), createElement: () => new Element(), querySelectorAll: s => s === '[role=tab]' ? tabs : s.startsWith('form ') ? forms : groups.get(s) ?? [] }, navigator: { onLine: true }, window: { addEventListener: (e, f) => { events[e] = f; } }, sessionStorage: { getItem: k => storage.get(k), setItem: (k, v) => storage.set(k, v), removeItem: k => storage.delete(k) }, AbortController, setTimeout, clearTimeout, setInterval: f => { intervals.push(f); }, Date, fetch: async (route, options) => { requests.push({ route, options }); return responder ? responder(route, options) : response(200, {}); } });
  vm.runInContext(source.replace(/export /g, ''), context);
  return { ids, forms, tabs, storage, requests, events, intervals, context };
}
const response = (status, body) => ({ status, ok: status >= 200 && status < 300, text: async () => JSON.stringify(body) });
const flush = async () => { for (let i = 0; i < 10; i++) await new Promise(r => setImmediate(r)); };
function bodyFor(route) {
  if (route === '/api/tasks') return { tasks: [] };
  if (route === '/api/health') return { state: 'ok', persistence: 'sqlite', activity: { source: 'none' } };
  return {};
}
test('MOCK UI: seven panels, keyboard tabs, local task labels and initially disabled board', () => {
  const ui = mockUI(); assert.equal(ui.tabs.length, 7); assert.equal((html.match(/role="tabpanel"/g) ?? []).length, 7);
  assert.equal(html.includes('Local task board'), true); assert.equal(ui.requests.length, 0);
  assert.equal(ui.forms.every(el => el.disabled), true);
  ui.tabs[0].events.keydown({ key: 'End', preventDefault() {} }); assert.equal(ui.tabs[6].attrs['aria-selected'], 'true');
  assert.equal(ui.ids.get('demo-state').textContent.includes('new tab') || ui.ids.get('demo-state').textContent.includes('new tabs') || ui.ids.get('demo-state').textContent.includes('new tab'.replace('n','N')), true);
});
test('MOCK UI: stored nonce remains unverified until private GET; same-origin proof on GET/HEAD/mutation', async () => {
  let release; const pending = new Promise(resolve => { release = resolve; }); let first = true;
  const stored = { csrfToken: 'a'.repeat(43), expiresAt: Date.now() + 60000 };
  const ui = mockUI({ stored, responder: async route => { if (first) { first = false; await pending; } return response(200, bodyFor(route)); } });
  assert.equal(ui.forms.every(el => el.disabled), true); assert.equal(ui.ids.get('demo-state').textContent.includes('unverified'), true);
  ui.events.pageshow({ persisted: false });
  release(); await flush(); assert.equal(ui.ids.get('refresh').disabled, false);
  await vm.runInContext("api('/api/tasks', {method:'HEAD'})", ui.context);
  await vm.runInContext("api('/api/tasks', {method:'POST',body:'{}'})", ui.context);
  assert.equal(ui.requests.every(r => r.options.credentials === 'same-origin' && r.options.cache === 'no-store' && typeof r.options.headers['X-Trial-CSRF'] === 'string'), true);
  const values = [...ui.storage.values()].map(v => Object.keys(JSON.parse(v)).sort().join(',')); assert.equal(values.every(v => v === 'csrfToken,expiresAt'), true);
  assert.equal([...ui.ids.values()].some(el => el.textContent.includes(stored.csrfToken)), false);
  ui.events.pagehide(); ui.events.pageshow({ persisted: true });
  assert.equal(ui.storage.size, 0); assert.equal(ui.forms.every(el => el.disabled), true);
});
test('MOCK UI: bootstrap only on explicit click; logout and offline clear private UI/storage', async () => {
  const ui = mockUI({ responder: route => response(route.endsWith('bootstrap') ? 201 : route.endsWith('logout') ? 204 : 200, route.endsWith('bootstrap') ? { csrfToken: 'b'.repeat(43), expiresAt: Date.now() + 60000 } : bodyFor(route)) });
  assert.equal(ui.requests.length, 0); ui.ids.get('demo-start').events.click(); await flush();
  assert.equal(ui.requests[0].options.headers['X-Trial-CSRF'] === undefined, true);
  assert.equal(ui.ids.get('refresh').disabled, false); ui.ids.get('demo-end').events.click(); await flush();
  assert.equal(ui.storage.size, 0); assert.equal(ui.forms.every(el => el.disabled), true);
  ui.ids.get('demo-start').events.click(); await flush(); ui.events.offline();
  assert.equal(ui.storage.size, 0); assert.equal(ui.ids.get('tasks').children.length, 0); assert.equal(ui.ids.get('edit-form').hidden, true);
});
test('MOCK UI: 401, expired/invalid stored values and network failure never admit', async () => {
  for (const failure of ['401','network']) {
    const ui = mockUI({ stored: { csrfToken: 'c'.repeat(43), expiresAt: Date.now() + 60000 }, responder: () => { if (failure === 'network') throw new TypeError('Synthetic offline'); return response(401, {}); } });
    await flush(); assert.equal(ui.storage.size, 0); assert.equal(ui.forms.every(el => el.disabled), true);
  }
  for (const stored of [{ csrfToken: 'd'.repeat(43), expiresAt: Date.now() - 1 }, { csrfToken: 'd'.repeat(43), expiresAt: Date.now() + 1000, actor: 'human' }]) {
    const ui = mockUI({ stored }); assert.equal(ui.requests.length, 0); assert.equal(ui.storage.size, 0);
  }
  assert.equal(source.includes('localStorage'), false); assert.equal(/serviceWorker|caches\./.test(source), false);
});
