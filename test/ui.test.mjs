import vm from 'node:vm';
import test from 'node:test';
import assert from 'node:assert/strict';

import {source,html,mockUI,response,flush,bodyFor} from './app-ui-fixture.mjs';

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
test('MOCK UI: manual fixture bootstrap is explicit; logout clears proof and retains only lock preference', async () => {
  const ui = mockUI({ responder: route => response(route.endsWith('bootstrap') ? 201 : route.endsWith('logout') ? 204 : 200, route.endsWith('bootstrap') ? { csrfToken: 'b'.repeat(43), expiresAt: Date.now() + 60000 } : bodyFor(route)) });
  assert.equal(ui.requests.length, 0); ui.ids.get('demo-start').events.click(); await flush();
  assert.equal(ui.requests[0].options.headers['X-Trial-CSRF'] === undefined, true);
  assert.equal(ui.ids.get('refresh').disabled, false); ui.ids.get('demo-end').events.click(); await flush();
  assert.deepEqual([...ui.storage.entries()],[['mesh.workspace.locked.v1','1']]); assert.equal(ui.forms.every(el => el.disabled), true);
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

test('MOCK UI: locked reload does not restore even a valid saved proof',async()=>{
 const ui=mockUI({locked:true,stored:{csrfToken:'e'.repeat(43),expiresAt:Date.now()+60000}});await flush();assert.equal(ui.requests.length,0);assert.equal(ui.forms.every(el=>el.disabled),true);assert.equal(ui.storage.has('mesh.synthetic-demo.proof.v1'),false);assert.deepEqual([...ui.storage.entries()],[['mesh.workspace.locked.v1','1']]);assert.equal(ui.ids.get('demo-start').textContent,'Reconnect workspace');
});

test('MOCK UI: locked board read during bootstrap cannot invalidate admission or send a private request',async()=>{
 let release;const pending=new Promise(resolve=>release=resolve);
 const ui=mockUI({responder:async route=>{if(route.endsWith('bootstrap')){await pending;return response(201,{csrfToken:'f'.repeat(43),expiresAt:Date.now()+60000});}return response(200,bodyFor(route));}});
 ui.ids.get('demo-start').events.click();
 await assert.rejects(vm.runInContext("api('/api/workroom')",ui.context),/admission required/);
 assert.equal(ui.requests.filter(r=>r.route==='/api/workroom').length,0);
 release();await flush();assert.equal(ui.ids.get('refresh').disabled,false);
});

test('MOCK UI: periodic fallback cannot overwrite admitted live observations; lock clears agent details',async()=>{
 const ui=mockUI({responder:route=>response(route.endsWith('bootstrap')?201:200,route.endsWith('bootstrap')?{csrfToken:'g'.repeat(43),expiresAt:Date.now()+60000}:bodyFor(route))});
 ui.ids.get('demo-start').events.click();await flush();
 ui.ids.get('relay-state').textContent='Live observation retained';
 vm.runInContext('applyLocalStubs()',ui.context);
 assert.equal(ui.ids.get('relay-state').textContent,'Live observation retained');
 vm.runInContext("renderAgentWorkspace(document.getElementById('agent-workspace'),{agents:[]},[],()=>{})",ui.context);
 assert.ok(ui.ids.get('agent-workspace').children.length>0);
 ui.events.offline();assert.equal(ui.ids.get('agent-workspace').children.length,0);
});

test('MOCK UI: Mind uses admitted GET and clears selected context and titles on pagehide',async()=>{
 const record={id:'memory-one',title:'Selected context',revision:1,workroom:{revision:1},progress:{revision:1,result:'Pending result',decision:'pending'}};
 const ui=mockUI({responder:route=>response(route.endsWith('bootstrap')?201:200,route.endsWith('bootstrap')?{csrfToken:'h'.repeat(43),expiresAt:Date.now()+60000}:route==='/api/workroom'?{tasks:[record]}:route==='/api/workroom/memory-one'?{task:record}:bodyFor(route))});
 ui.ids.get('demo-start').events.click();await flush();
 const [,select,read,,,content]=ui.ids.get('mind-workspace').children;
 assert.deepEqual(select.children.map(n=>n.value),['','memory-one']);
 assert.equal(ui.requests.filter(r=>r.route==='/api/workroom/memory-one').length,0);
 select.value='memory-one';select.events.change();
 assert.equal(read.disabled,false,JSON.stringify({options:select.children.map(n=>n.value),admitted:vm.runInContext('admitted',ui.context),busy:vm.runInContext('busy',ui.context),state:ui.ids.get('mind-workspace').children[4].textContent}));
 await read.events.click();
 assert.equal(content.hidden,false,ui.ids.get('mind-workspace').children[4].textContent+'; requests: '+ui.requests.map(r=>r.route).join(','));
 const request=ui.requests.find(r=>r.route==='/api/workroom/memory-one');
 assert.equal(request.options.method,undefined);assert.equal(request.options.headers['X-Trial-CSRF'],'h'.repeat(43));
 ui.events.pagehide();assert.equal(content.hidden,true);assert.equal(content.children.length,0);assert.equal(select.children.length,0);
});

test('MOCK UI: actual ordinary chat sends once through admission, never creates a task, and clears on lock',async()=>{
 const ui=mockUI({responder:(route,options)=>response(route.endsWith('bootstrap')?201:200,
   route.endsWith('bootstrap')?{csrfToken:'j'.repeat(43),expiresAt:Date.now()+60000}:
   route==='/relay/api/agents'?[{id:'echo',name:'Echo',conversation_id:'session-one'}]:
   route==='/relay/api/mesh-capabilities'?{taskSessionBinding:1}:
   route.endsWith('/messages')?{messages:[{id:'msg-one',k:'ag',t:'Existing source history'}]}:
   route==='/relay/api/agents/echo/message'?{ok:true}:bodyFor(route))});
 ui.ids.get('demo-start').events.click();await flush();
 const selector=ui.ids.get('relay-chat-agent');selector.value='echo';selector.events.change();await flush();
 assert.match(ui.ids.get('relay-chat-destination').textContent,/Echo.*session-one/);
 const composer=ui.ids.get('relay-text');composer.value='ordinary chat';composer.events.input();
 assert.equal(ui.ids.get('relay-send').disabled,false);assert.equal(ui.ids.get('relay-add-files').disabled,true);
 await ui.ids.get('relay-form').events.submit({preventDefault(){}});
 const posts=ui.requests.filter(r=>r.options.method==='POST'&&r.route.includes('/relay/'));
 assert.equal(posts.length,1);assert.equal(posts[0].route,'/relay/api/agents/echo/message');
 assert.equal(posts[0].options.headers['X-Trial-CSRF'],'j'.repeat(43));
 assert.equal(JSON.parse(posts[0].options.body).expectedConversationId,'session-one');
 assert.ok(!ui.requests.some(r=>r.route==='/api/relay/message'));assert.equal(composer.value,'');
 composer.value='private draft';composer.events.input();ui.events.pagehide();
 assert.equal(composer.value,'');assert.equal(ui.ids.get('relay-chat-agent').value,'');
 assert.ok(!JSON.stringify([...ui.storage.entries()]).includes('private draft'));
});

test('MOCK UI: workspace deep links select the named panel without admission or requests', () => {
  for (const name of ['overview','relay','inference','workroom','agent','mind','control']) {
    const ui=mockUI({hash:'#'+name});
    assert.equal(ui.ids.get('tab-'+name).attrs['aria-selected'],'true');
    assert.equal(ui.ids.get('panel-'+name).hidden,false);
    assert.equal(ui.requests.length,0);
    assert.equal(ui.forms.every(el=>el.disabled),true);
    ui.context.window.location.hash='#workroom';ui.events.hashchange();
    assert.equal(ui.ids.get('tab-workroom').attrs['aria-selected'],'true');
    ui.context.window.location.hash='#unknown';ui.events.hashchange();
    assert.equal(ui.ids.get('tab-workroom').attrs['aria-selected'],'true');
    assert.equal(ui.requests.length,0);
  }
});

test('MOCK UI: supervisor-reported models never enable controls and clear on expiry or privacy lock',()=>{
  const ui=mockUI();
  const modelObservation={schemaVersion:'mesh-supervisor-observation/v1',source:'local_supervisor',expiresAt:Date.now()+4900,
    models:[{label:'Nemotron test label',state:'reported_loaded',reason:null}]};
  const status={schemaVersion:'mesh-local-inference/v1',nodeId:'this-pc',profile:{id:'qwen38-flash-next-q6'},state:'UNAVAILABLE',
    controls:{load:false,stop:false,unload:false,chat:false,reason:'NATIVE_QUALIFICATION_REQUIRED'},runtime:{status:'UNKNOWN'},modelObservation};
  ui.context.renderLocalInference(status);
  const root=ui.ids.get('local-model-catalog');assert.match(root.children[0].textContent,/Nemotron test label.*Reported loaded/);
  for(const id of ['load','stop','unload','send'])assert.equal(ui.ids.get('local-inference-'+id).disabled,true);
  modelObservation.expiresAt=Date.now()-1;ui.context.renderLocalInference(status);
  assert.equal(root.children.length,0);assert.match(root.textContent,/expired/);
  modelObservation.expiresAt=Date.now()+4900;ui.context.renderLocalInference(status);ui.events.pagehide();
  assert.equal(root.children.length,0);assert.ok(!root.textContent.includes('Nemotron'));
  assert.ok(!JSON.stringify([...ui.storage.entries()]).includes('Nemotron'));
});

test('MOCK UI: visible model polling is GET-only, single-flight and cannot restore private data after lock',async()=>{
  let release,hold=false;
  const stored={csrfToken:'m'.repeat(43),expiresAt:Date.now()+60000};
  const status={schemaVersion:'mesh-local-inference/v1',nodeId:'this-pc',profile:{id:'qwen38-flash-next-q6'},state:'UNAVAILABLE',controls:{},
    modelObservation:{schemaVersion:'mesh-supervisor-observation/v1',source:'local_supervisor',expiresAt:Date.now()+4900,models:[{label:'private loaded model',state:'reported_loaded'}]}};
  const ui=mockUI({stored,hash:'#inference',responder:async route=>{
    if(route==='/api/inference/status'){if(hold)await new Promise(r=>{release=r;});return response(200,status);}
    return response(200,bodyFor(route));
  }});
  await flush();hold=true;const before=ui.requests.length;
  for(const f of ui.intervals)f();await flush();
  const reads=ui.requests.slice(before);assert.equal(reads.length,1);assert.equal(reads[0].route,'/api/inference/status');
  assert.equal(reads[0].options.method,'GET');
  for(const f of ui.intervals)f();await flush();assert.equal(ui.requests.length,before+1);
  ui.events.pagehide();release();await flush();
  assert.equal(ui.ids.get('local-model-catalog').children.length,0);
  assert.ok(!ui.ids.get('local-model-catalog').textContent.includes('private loaded model'));
  for(const f of ui.intervals)f();await flush();assert.equal(ui.requests.length,before+1);
});
