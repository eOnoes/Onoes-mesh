import test from 'node:test';
import assert from 'node:assert/strict';
import { createLocalInference } from '../lib/local-inference.mjs';
import { createPendingNemotronInference } from '../lib/supervised-inference.mjs';
import { localFixture } from './local-inference-fixture.mjs';

import {mockUI,response,html,flush,bodyFor} from './app-ui-fixture.mjs';
function uiSetup({control:override}={}) {
  const fixture = localFixture(), control = override??createLocalInference({ adapter: fixture.adapter, now: fixture.now });
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
    return bodyFor(route);
  }
  class FixtureDate extends Date { static now() { return fixture.now(); } }
  const ui=mockUI({DateImpl:FixtureDate,responder:async(route,options)=>{
    let status=200,body;
    try{body=await respond(route,options);}catch(error){status=error.status??503;body={error:error.message};}
    return response(status,body);
  }});
  const {ids,storage,events,intervals,requests,context}=ui;
  const click = async id => { ids.get(id).events.click(); await flush(); };
  return { ids, fixture, control, storage, events, intervals, requests, context, click,
    holdChat: promise => { chatDelay = promise; } };
}

test('UI shows selected Nemotron as unqualified and never exposes execution controls', async () => {
  const ui=uiSetup({control:createPendingNemotronInference()}),el=id=>ui.ids.get('local-inference-'+id);
  await ui.click('demo-start');
  assert.match(el('profile').textContent,/Nemotron 3\.5 Bolt.*selected for qualification; no verified model connection/);
  assert.match(el('reason').textContent,/not qualified/);
  for(const id of ['load','stop','unload','recover','send'])assert.equal(el(id).disabled,true,id);
  assert.ok(ui.requests.filter(r=>r.route.startsWith('/api/inference/')).every(r=>(r.options.method||'GET')==='GET'));
  assert.equal(ui.fixture.calls.start.length,0);assert.equal(ui.fixture.calls.stop.length,0);
});

test('UI fixture: every local control has a handler and reason; Load/Stop/Unload confirm and read receipts', async () => {
  const ui = uiSetup(), el = id => ui.ids.get('local-inference-' + id);
  for (const id of ['refresh', 'load', 'stop', 'unload', 'approve', 'dismiss']) {
    assert.equal(typeof el(id).events.click, 'function'); assert.equal(el(id).disabled, true);
    assert.ok(el(id).title);
  }
  assert.equal(typeof el('chat-form').events.submit, 'function');
  await ui.click('demo-start');
  assert.equal(el('load').disabled, false,JSON.stringify({reason:el('reason').textContent,state:el('state').textContent,message:ui.ids.get('message').textContent})); assert.equal(el('send').disabled, true);
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
  const before = ui.requests.length,starts=ui.fixture.calls.start.length,stops=ui.fixture.calls.stop.length; ui.intervals.forEach(f => f()); await flush();
  assert.ok(ui.requests.slice(before).every(r=>(r.options.method||'GET')==='GET'&&['/api/inference/status','/relay/api/agents'].includes(r.route)),JSON.stringify(ui.requests.slice(before).map(r=>({route:r.route,method:r.options.method}))));
  assert.equal(ui.fixture.calls.start.length,starts);assert.equal(ui.fixture.calls.stop.length,stops);
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
