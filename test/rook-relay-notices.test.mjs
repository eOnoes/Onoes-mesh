import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import {mockUI, response, flush, bodyFor} from './app-ui-fixture.mjs';
const walk = node => [node, ...(node.children ?? []).flatMap(walk)];
const text = ui => walk(ui.ids.get('rook-reports')).map(n => n.textContent).join('\n');
const id = '11111111-1111-4111-8111-111111111111';
const notice = {connection: {status: 'running'},
  cards: [{taskId: id, flow: {state:'clarification', revision:3, question:'Which folder should this use?'}}],
  reports: [{createdAt: '2026-11-08T20:00:00Z',
  payload: {kind: 'needs_input', taskId: id, title: '<img src=x onerror=bad()>', questionRevision:3, summary: 'Open the card for clarification.'}}]};
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

test('Relay shows only the current saved question and keeps answered notices in history', async () => {
  const current = await admittedUi();
  assert.ok(text(current).includes('Which folder should this use?'));
  for (const flow of [
    {state:'clarification', revision:4, question:'Different question'},
    {state:'working', revision:4, question:''},
  ]) {
    const ui = await admittedUi({...notice, cards:[{taskId:id,flow}]});
    assert.ok(text(ui).includes('Earlier clarification'));
    assert.doesNotMatch(text(ui), /Your input needed|Which folder|Different question|Open the card for clarification/);
  }
  for (const cards of [[], [{taskId:'another-card',flow:notice.cards[0].flow}]]) {
    const ui = await admittedUi({...notice, cards});
    assert.ok(text(ui).includes('Clarification requested'));
    assert.doesNotMatch(text(ui), /Your input needed|Which folder/);
  }
  const legacy = await admittedUi({...notice, reports:[{payload:{
    kind:'needs_input', taskId:id, title:'Old notice', summary:'An unversioned question'
  }}]});
  assert.ok(text(legacy).includes('Clarification requested'));
  assert.doesNotMatch(text(legacy), /Your input needed|Which folder|An unversioned question/);
  const privateContent = await admittedUi({...notice,cards:[{taskId:id,flow:{
    state:'clarification',revision:3,question:'Use token=fixture-secret for the build?'
  }}]});
  assert.ok(text(privateContent).includes('Your input needed'));
  assert.doesNotMatch(text(privateContent), /fixture-secret/);
});

test('unconfigured watcher stays visibly unconnected; unknown report kinds are ignored', async () => {
  const ui = await admittedUi({connection: {status: 'not_configured'}, reports: [{payload: {kind: 'invented', summary: 'Never show me'}}]});
  assert.equal(ui.ids.get('rook-summary').textContent, 'Rook · not connected');
  assert.ok(text(ui).includes('No saved Rook notices'));
  assert.ok(!text(ui).includes('Never show me'));
});

test('each notice shows its saved delivery state even when the watcher is offline', async () => {
  const states = ['pending', 'sending', 'unknown', 'delivered', undefined, 'constructor'];
  const ui = await admittedUi({connection: {status: 'unavailable'},
    reports: states.map(state => ({...notice.reports[0], state}))});
  const rows = walk(ui.ids.get('rook-reports')).map(node => node.textContent)
    .filter(line => line.includes(' · Saved '));
  assert.deepEqual(rows.map(line => line.split(' · ')[0]), [
    'Queued for delivery', 'Awaiting confirmation', 'Delivery unconfirmed',
    'Delivery confirmed', 'Delivery status unavailable', 'Delivery status unavailable'
  ]);
});

test('Relay can confirm receipt when the watcher missed its reply', async () => {
  const ui = await admittedUi({connection: {status: 'paused'}, reports: [
    {...notice.reports[0], state: 'unknown', relayReceivedAt: '2026-11-08T20:01:02Z'},
    {...notice.reports[0], state: 'unknown', relayReceivedAt: null},
  ]});
  const rows = walk(ui.ids.get('rook-reports')).map(node => node.textContent);
  assert.equal(rows.filter(line => line.startsWith('Received by Mesh Relay · Saved ')).length, 1);
  assert.equal(rows.filter(line => line.startsWith('Delivery unconfirmed · Saved ')).length, 1);
});

test('assignment holds explain the original worker and open its card without releasing it', async () => {
  const hold={taskId:id,title:'Unconfirmed original worker',reason:'writer_quiescence_unproven'};
  const ui=await admittedUi({connection:{status:'not_configured'},assignmentHolds:[hold,{...hold,sendId:'another-attempt'}],reports:[]});
  assert.ok(text(ui).includes('previous worker has not been verified stopped'));
  assert.equal(walk(ui.ids.get('rook-reports')).filter(n=>n.textContent==='Assignment on hold').length,1);
  assert.equal(walk(ui.ids.get('rook-reports')).filter(n=>n.textContent==='Open card').length,1);
  assert.equal(ui.ids.get('rook-summary').textContent,'Rook · not connected');
  const before=ui.requests.length;ui.events.pagehide({persisted:true});
  assert.equal(text(ui),'');assert.equal(ui.requests.length,before);
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
