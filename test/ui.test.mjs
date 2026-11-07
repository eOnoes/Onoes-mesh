import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import { readFile } from 'node:fs/promises';

const source = await readFile(new URL('../public/app.js', import.meta.url), 'utf8');
const agentSource = await readFile(new URL('../public/agent-workspace.mjs', import.meta.url), 'utf8');
const mindSource = await readFile(new URL('../public/mind-workspace.mjs', import.meta.url), 'utf8');
const relayCoreSource = await readFile(new URL('../public/relay-conversation.mjs', import.meta.url), 'utf8');
const relayChatSource = await readFile(new URL('../public/chat.mjs', import.meta.url), 'utf8');
const html = await readFile(new URL('../public/index.html', import.meta.url), 'utf8');
class Element {
  constructor() { this.children = []; this.attrs = {}; this.events = {}; this.textContent = ''; this.value = ''; this.disabled = false; this.style = {}; this.dataset={};this.scrollHeight=0;this.clientHeight=0;this.scrollTop=0;this.classList={add(){},remove(){},contains(){return false;}}; }
  get firstChild() { return this.children[0]; }
  setAttribute(k, v) { this.attrs[k] = v; } getAttribute(k) { return this.attrs[k]; }
  addEventListener(k, f) { this.events[k] = f; } append(...els) { this.children.push(...els); }
  replaceChildren(...els) { this.children = els; } reset() {} focus() {}
  querySelectorAll() { return []; }
  getBoundingClientRect() {return {height:0,width:0,top:0,right:0,left:0,bottom:0};}
}
function mockUI({ stored, responder, locked=false } = {}) {
  const ids = new Map([...html.matchAll(/\bid="([^"]+)"/g)].map(m => [m[1], new Element()]));
  const forms = ['create-title','create-description','create-label','edit-title','edit-description','edit-label','toggle-status','reload-task','refresh'].map(id => ids.get(id));
  const tabs = [...html.matchAll(/<button role="tab" id="([^"]+)" aria-controls="([^"]+)"/g)].map(m => { const el = ids.get(m[1]); el.attrs['aria-controls'] = m[2]; return el; });
  const groups = new Map(['.activity-workers','.activity-state, .activity-source','.service-connections','.service-status','.inference-state','.inference-errors','.activity-source','.activity-state'].map(s => [s, [new Element()]]));
  const storage = new Map(stored ? [['mesh.synthetic-demo.proof.v1', JSON.stringify(stored)]] : []);
  if(locked)storage.set('mesh.workspace.locked.v1','1');
  const requests = []; const events = {}; const intervals = [];
  const context = vm.createContext({requestAnimationFrame:()=>{},MutationObserver:class{observe(){}},crypto:globalThis.crypto,TextEncoder,document: { getElementById: id => ['chat-grip','chat-seek','chat-jump'].includes(id)?null:ids.get(id), createElement: () => new Element(),createDocumentFragment:()=>new Element(), querySelectorAll: s => s === '[role=tab]' ? tabs : s.startsWith('form ') ? forms : groups.get(s) ?? [] }, navigator: { onLine: true }, window: { addEventListener: (e, f) => { events[e] = f; } }, sessionStorage: { getItem: k => storage.get(k)??null, setItem: (k, v) => storage.set(k, v), removeItem: k => storage.delete(k) }, AbortController, setTimeout, clearTimeout, setInterval: f => { intervals.push(f); }, Date, fetch: async (route, options) => { requests.push({ route, options }); return responder ? responder(route, options) : response(200, {}); } });
  const modules=[agentSource,mindSource,relayCoreSource,relayChatSource,source].map(s=>s.replace(/^import .*;\r?$/gm,'').replace(/^export /gm,''));
  vm.runInContext(modules.join('\n'), context);
  return { ids, forms, tabs, storage, requests, events, intervals, context };
}
const response = (status, body) => ({ status, ok: status >= 200 && status < 300, text: async () => JSON.stringify(body) });
const flush = async () => { for (let i = 0; i < 10; i++) await new Promise(r => setImmediate(r)); };
function bodyFor(route) {
  if (route === '/api/tasks') return { tasks: [] };
  if (route === '/api/health') return { state: 'ok', persistence: 'sqlite', activity: { source: 'none' } };
  if (route === '/api/worker-activity') return {state:'not_configured',workers:[]};
  if (route === '/api/commands') return {commands:[]};
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
