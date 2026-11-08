import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import {mockUI, response, flush, bodyFor} from './app-ui-fixture.mjs';
const walk = node => [node, ...(node.children ?? []).flatMap(walk)];
const text = ui => walk(ui.ids.get('rook-reports')).map(n => n.textContent).join('\n');
const id = '11111111-1111-4111-8111-111111111111';
const notice = {connection: {status: 'running'}, reports: [{createdAt: '2026-11-08T20:00:00Z',
  payload: {kind: 'needs_input', taskId: id, title: '<img src=x onerror=bad()>', summary: 'Which folder should this use?'}}]};
async function admittedUi(rook = notice) {
  const ui = mockUI({responder: (route) => response(route === '/api/trial-session/bootstrap' ? 201 : 200,
    route === '/api/trial-session/bootstrap' ? {csrfToken: 'a'.repeat(43), expiresAt: Date.now() + 100000}
    : route === '/api/workroom/rook' ? rook : bodyFor(route))});
  await flush(); ui.ids.get('demo-start').events.click(); await flush(); return ui;
}

test('Relay Rook notices use admitted GET only and render untrusted titles as text', async () => {
  const ui = await admittedUi();
  assert.equal(ui.ids.get('rook-summary').textContent, 'Rook · running');
  assert.ok(text(ui).includes(notice.reports[0].payload.title));
  assert.ok(text(ui).includes('Your input needed'));
  assert.ok(walk(ui.ids.get('rook-reports')).some(n => n.textContent === 'Open card'));
  const calls = ui.requests.filter(r => r.route === '/api/workroom/rook');
  assert.equal(calls.length, 1); assert.equal(calls[0].options.method ?? 'GET', 'GET');
  assert.ok(!JSON.stringify([...ui.storage]).includes('Which folder'));
});

test('unconfigured watcher stays visibly unconnected; unknown report kinds are ignored', async () => {
  const ui = await admittedUi({connection: {status: 'not_configured'}, reports: [{payload: {kind: 'invented', summary: 'Never show me'}}]});
  assert.equal(ui.ids.get('rook-summary').textContent, 'Rook · not connected');
  assert.ok(text(ui).includes('No saved Rook notices'));
  assert.ok(!text(ui).includes('Never show me'));
});

test('page privacy clears notices and late responses cannot restore them', async () => {
  const ui = await admittedUi(); let release;
  ui.context.fetch = async route => route === '/api/workroom/rook' ? new Promise(resolve => {release = resolve;}) : response(200, {});
  ui.ids.get('rook-refresh').events.click(); await flush();
  ui.events.pagehide({persisted: true});
  release(response(200, notice)); await flush();
  assert.equal(text(ui), ''); assert.equal(ui.ids.get('rook-refresh').disabled, true);
  assert.equal(ui.ids.get('rook-summary').textContent, 'Rook · connect to check');
});

test('opening the card emits navigation only and a locked refresh reads nothing', async () => {
  const ui = await admittedUi(); const emitted = [];
  ui.context.CustomEvent = class {constructor(type, options) {this.type = type; this.detail = options.detail;}};
  ui.context.window.dispatchEvent = event => emitted.push(event);
  const open = walk(ui.ids.get('rook-reports')).find(n => n.textContent === 'Open card');
  const before = ui.requests.length; open.events.click();
  assert.equal(emitted[0].type, 'mesh-open-task'); assert.equal(emitted[0].detail.id, id);
  assert.equal(ui.requests.length, before);
  vm.runInContext("clearPrivate('locked'); controls()", ui.context);
  ui.ids.get('rook-refresh').events.click(); await flush(); assert.equal(ui.requests.length, before);
});
