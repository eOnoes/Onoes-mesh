import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import { readFile } from 'node:fs/promises';
import { createLocalInference } from '../lib/local-inference.mjs';
import { localFixture } from './local-inference-fixture.mjs';

const source = await readFile(new URL('../public/app.js', import.meta.url), 'utf8');
const html = await readFile(new URL('../public/index.html', import.meta.url), 'utf8');
const flush = async () => { for (let i = 0; i < 12; i++) await new Promise(r => setImmediate(r)); };
class Element {
  constructor() { this.children = []; this.attrs = {}; this.events = {}; this.textContent = ''; this.value = ''; this.disabled = false; }
  setAttribute(k, v) { this.attrs[k] = v; } getAttribute(k) { return this.attrs[k]; }
  addEventListener(k, f) { this.events[k] = f; } append(...els) { this.children.push(...els); }
  replaceChildren(...els) { this.children = els; } reset() {} focus() {}
}
function uiSetup() {
  const fixture = localFixture(), control = createLocalInference({ adapter: fixture.adapter, now: fixture.now });
  const ids = new Map([...html.matchAll(/\bid="([^"]+)"/g)].map(m => [m[1], new Element()]));
  const tabs = [...html.matchAll(/<button role="tab" id="([^"]+)" aria-controls="([^"]+)"/g)].map(m => {
    const el = ids.get(m[1]); el.attrs['aria-controls'] = m[2]; return el;
  });
  const storage = new Map(), events = {}, intervals = [], requests = [];
  let chatDelay;
  async function respond(route, options) {
    const body = options.body ? JSON.parse(options.body) : null;
    if (route === '/api/trial-session/bootstrap') return { csrfToken: 'a'.repeat(43), expiresAt: fixture.now() + 60000 };
    if (route === '/api/tasks') return { tasks: [] };
    if (route === '/api/health') return { state: 'ok', activity: { source: 'none' } };
    if (route === '/api/inference/status') return control.status();
    if (route.startsWith('/api/inference/propose-')) return control.propose(route.split('propose-')[1], body, 'ui', () => true);
    if (route === '/api/inference/approve') return control.approve(body, 'ui', () => true);
    if (route.startsWith('/api/inference/receipt/')) return control.receipt(route.split('/').at(-1), 'ui');
    if (route === '/api/inference/chat') {
      const result = await control.chat(body, () => true);
      if (chatDelay) await chatDelay;
      return result;
    }
    return {};
  }
  class FixtureDate extends Date { static now() { return fixture.now(); } }
  const context = vm.createContext({
    document: { getElementById: id => ids.get(id), createElement: () => new Element(),
      querySelectorAll: s => s === '[role=tab]' ? tabs : [], addEventListener() {} },
    navigator: { onLine: true }, window: { addEventListener: (e, f) => { events[e] = f; } },
    sessionStorage: { getItem: k => storage.get(k), setItem: (k, v) => storage.set(k, v), removeItem: k => storage.delete(k) },
    AbortController, setTimeout, clearTimeout, setInterval: f => intervals.push(f), Date: FixtureDate,
    fetch: async (route, options) => {
      requests.push({ route, body: options.body });
      // JSON round-trip matches the HTTP realm boundary.
      let status = 200, body;
      try { body = await respond(route, { ...options, body: options.body }); }
      catch (e) { status = e.status ?? 503; body = { error: e.message }; }
      return { status, ok: status < 400, text: async () => JSON.stringify(body) };
    },
  });
  // The controller's strict schema checks use the server realm after JSON parse.
  vm.runInContext(source.replace(/export /g, ''), context);
  const click = async id => { ids.get(id).events.click(); await flush(); };
  return { ids, fixture, control, storage, events, intervals, requests, context, click,
    holdChat: promise => { chatDelay = promise; } };
}

test('UI fixture: every local control has a handler and reason; Load/Stop/Unload confirm and read receipts', async () => {
  const ui = uiSetup(), el = id => ui.ids.get('local-inference-' + id);
  for (const id of ['refresh', 'load', 'stop', 'unload', 'approve', 'dismiss']) {
    assert.equal(typeof el(id).events.click, 'function'); assert.equal(el(id).disabled, true);
    assert.ok(el(id).title);
  }
  assert.equal(typeof el('chat-form').events.submit, 'function');
  await ui.click('demo-start');
  assert.equal(el('load').disabled, false); assert.equal(el('send').disabled, true);
  await ui.click('local-inference-load');
  assert.equal(ui.fixture.calls.start.length, 0); assert.equal(el('approve').disabled, false);
  assert.match(el('proposal').textContent, /No action has executed/);
  await ui.click('local-inference-dismiss'); assert.equal(el('confirmation').hidden, true);
  await ui.click('local-inference-load'); await ui.click('local-inference-approve');
  assert.equal(ui.fixture.calls.start.length, 1); assert.equal(el('send').disabled, false);
  assert.match(el('receipt').textContent, /readBackVerified: true/);
  assert.ok(ui.requests.some(r => r.route.startsWith('/api/inference/receipt/')));
  el('prompt').value = 'PRIVATE_UI_PROMPT';
  el('chat-form').events.submit({ preventDefault() {} }); await flush();
  assert.equal(el('prompt').value, ''); assert.equal(el('response').textContent, 'Fixture reply');
  assert.equal([...ui.storage.values()].some(v => /PRIVATE_UI_PROMPT|Fixture reply/.test(v)), false);
  await ui.click('local-inference-stop'); assert.equal(ui.fixture.calls.stop.length, 0);
  await ui.click('local-inference-approve'); assert.equal(ui.fixture.calls.stop.length, 1);
  assert.equal(el('send').disabled, true); assert.equal(el('load').disabled, false);
  await ui.click('local-inference-load'); await ui.click('local-inference-approve');
  await ui.click('local-inference-unload'); await ui.click('local-inference-approve');
  assert.equal(ui.fixture.calls.stop.length, 2); assert.match(el('state').textContent, /STOPPED/);
  ui.fixture.advance(5001); ui.intervals.forEach(f => f());
  assert.equal(el('load').disabled, true); assert.match(el('reason').textContent, /expired/);
  await ui.click('local-inference-refresh'); assert.equal(el('load').disabled, false);
  const panel = html.slice(html.indexOf('<section role="tabpanel" id="panel-inference"'), html.indexOf('<section role="tabpanel" id="panel-workroom"'));
  assert.equal(/<h2>(Laptop|AI box)<\/h2>|SYNTHETIC/.test(panel), false);
});

test('UI fixture: ownership uncertainty and expired confirmation disable controls; no background control requests', async () => {
  const ui = uiSetup(), el = id => ui.ids.get('local-inference-' + id);
  await ui.click('demo-start'); await ui.click('local-inference-load');
  ui.fixture.advance(30001); ui.intervals.forEach(f => f()); assert.equal(el('approve').disabled, true);
  await ui.click('local-inference-refresh'); await ui.click('local-inference-load'); await ui.click('local-inference-approve');
  ui.fixture.override(v => ({ ...v, identity: { ...v.identity, pid: 99 } }));
  await ui.click('local-inference-refresh'); assert.match(el('state').textContent, /UNCERTAIN/);
  for (const id of ['load', 'stop', 'unload', 'send']) { assert.equal(el(id).disabled, true); assert.ok(el(id).title); }
  const before = ui.requests.length; ui.intervals.forEach(f => f()); assert.equal(ui.requests.length, before);
});

test('UI fixture: privacy clearance drops delayed chat response and confirmation; new admission has empty chat', async () => {
  const ui = uiSetup(), el = id => ui.ids.get('local-inference-' + id);
  await ui.click('demo-start'); await ui.click('local-inference-load'); await ui.click('local-inference-approve');
  let release; ui.holdChat(new Promise(r => { release = r; }));
  el('prompt').value = 'PRIVATE_DELAYED_PROMPT'; el('chat-form').events.submit({ preventDefault() {} }); await flush();
  ui.events.offline(); assert.equal(el('prompt').value, ''); assert.equal(el('response').textContent, '');
  release(); await flush(); assert.equal(el('response').textContent, ''); assert.equal(ui.storage.size, 0);
  ui.holdChat(null); await ui.click('demo-start'); assert.equal(el('response').textContent, '');
  await ui.click('local-inference-stop'); assert.equal(el('confirmation').hidden, false);
  ui.events.pagehide({ persisted: true }); assert.equal(el('confirmation').hidden, true);
  assert.equal(el('approve').disabled, true); assert.equal(el('response').textContent, '');
});
