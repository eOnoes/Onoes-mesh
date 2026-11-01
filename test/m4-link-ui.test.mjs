import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import { readFile } from 'node:fs/promises';

const source = await readFile(new URL('../public/app.js',import.meta.url),'utf8');
const html = await readFile(new URL('../public/index.html',import.meta.url),'utf8');
const task = {id:'11111111-1111-4111-8111-111111111111',title:'Relay UI task',description:'hello',label:'Relay',status:'open',revision:1};
const conversationId='22222222-2222-4222-8222-222222222222';
const flush=async()=>{for(let i=0;i<12;i++)await new Promise(resolve=>setImmediate(resolve));};
const response=(status,body)=>({status,ok:status>=200&&status<300,text:async()=>JSON.stringify(body)});
function harness() {
  class Element {
    constructor(){this.children=[];this.attrs={};this.events={};this.value='';this.disabled=false;this.textContent='';}
    setAttribute(k,v){this.attrs[k]=v} getAttribute(k){return this.attrs[k]}
    addEventListener(k,f){this.events[k]=f} append(...v){this.children.push(...v)} replaceChildren(...v){this.children=v} reset(){} focus(){}
  }
  const ids=new Map([...html.matchAll(/\bid="([^"]+)"/g)].map(m=>[m[1],new Element()]));
  const tabs=[...html.matchAll(/<button role="tab" id="([^"]+)" aria-controls="([^"]+)"/g)].map(m=>{const e=ids.get(m[1]);e.attrs['aria-controls']=m[2];return e});
  const forms=[...ids].filter(([id])=>/^(relay-|create-|edit-)|refresh/.test(id)).map(([,e])=>e);
  const storage=new Map(),events={},requests=[],writes=[];let linked=false,failOnce=false,delay;
  const context=vm.createContext({document:{visibilityState:'visible',getElementById:id=>ids.get(id),createElement:()=>new Element(),querySelectorAll:s=>s==='[role=tab]'?tabs:s.startsWith('form ')?forms:[],addEventListener:(k,f)=>{events[k]=f}},navigator:{onLine:true},window:{location:{origin:'http://127.0.0.1:12345'},addEventListener:(k,f)=>{events[k]=f}},sessionStorage:{getItem:k=>storage.get(k),setItem:(k,v)=>storage.set(k,v),removeItem:k=>storage.delete(k)},crypto:{randomUUID:()=> '33333333-3333-4333-8333-333333333333'},AbortController,setTimeout,clearTimeout,setInterval:()=>{},Date,
    fetch:async(route,options)=>{
      requests.push({route,options});
      if(route.endsWith('bootstrap'))return response(201,{csrfToken:'b'.repeat(43),expiresAt:Date.now()+60000});
      if(route==='/api/health')return response(200,{state:'ok',persistence:'sqlite',activity:{source:'none'}});
      if(route==='/api/tasks')return response(200,{tasks:linked?[task]:[]});
      if(route===`/api/tasks/${task.id}`)return response(200,{task});
      if(route==='/api/relay/shell')return response(200,{html:'<html><head></head>MOCK native Relay shell</html>'});
      if(route==='/api/relay/message'){
        writes.push(JSON.parse(options.body));
        if(delay)await delay;
        if(failOnce){failOnce=false;return response(503,{error:'Actual Relay unavailable; retry same identity.'})}
        const duplicate=linked;linked=true;return response(200,{ok:true,taskId:task.id,messageId:writes.at(-1).id,conversationId,duplicate});
      }
      if(route==='/api/relay'||route==='/api/relay/reconnect')return response(200,{status:'fresh',conversationId,links:linked?[{messageId:'retry_1',taskId:task.id}]:[],error:null});
      return response(200,{});
    }});
  vm.runInContext(source.replace(/export /g,''),context);
  return {ids,events,requests,writes,storage,context,fail:()=>{failOnce=true},hold:p=>{delay=p}};
}
test('M4 MOCK UI: explicit message retry keeps identity, reconnect recovers selectable reference, native frame uses admitted session',async()=>{
  const ui=harness();assert.equal(ui.requests.length,0);
  assert.equal(ui.ids.get('relay-send').disabled,true);ui.ids.get('demo-start').events.click();await flush();
  ui.ids.get('relay-message-id').value='retry_1';ui.ids.get('relay-text').value='hello';ui.fail();
  ui.ids.get('relay-form').events.submit({preventDefault(){}});await flush();
  assert.equal(ui.ids.get('relay-message-id').value,'retry_1');assert.match(ui.ids.get('message').textContent,/unavailable/);
  ui.ids.get('relay-form').events.submit({preventDefault(){}});await flush();
  assert.deepEqual(ui.writes[0],ui.writes[1]);assert.deepEqual(Object.keys(ui.writes[1]).sort(),['conversationId','id','meshIntent','text']);
  ui.ids.get('relay-reconnect').events.click();await flush();assert.equal(ui.ids.get('relay-links').children.length,1);
  ui.ids.get('relay-links').children[0].events.click();await flush();assert.equal(ui.ids.get('tab-workroom').attrs['aria-selected'],'true');assert.match(ui.ids.get('task-identity').textContent,/11111111/);
  ui.ids.get('relay-open').events.click();await flush();assert.match(ui.ids.get('relay-terminal').srcdoc,/MOCK native Relay shell/);assert.equal(ui.ids.get('relay-terminal').hidden,false);
  ui.ids.get('relay-terminal').contentWindow={};const beforeNative=ui.requests.length;
  ui.events.message({source:{},origin:'http://127.0.0.1:12345',data:{type:'mesh_relay_select',instance:'33333333-3333-4333-8333-333333333333',taskId:task.id}});
  ui.events.message({source:ui.ids.get('relay-terminal').contentWindow,origin:'http://evil.test',data:{type:'mesh_relay_select',instance:'33333333-3333-4333-8333-333333333333',taskId:task.id}});
  ui.events.message({source:ui.ids.get('relay-terminal').contentWindow,origin:'http://127.0.0.1:12345',data:{type:'mesh_relay_select',instance:'expired-document',taskId:task.id}});
  await flush();assert.equal(ui.requests.length,beforeNative,'foreign source/origin/old native document cannot select');
  ui.events.message({source:ui.ids.get('relay-terminal').contentWindow,origin:'http://127.0.0.1:12345',data:{type:'mesh_relay_select',instance:'33333333-3333-4333-8333-333333333333',taskId:task.id}});
  await flush();assert.equal(ui.requests.length,beforeNative+2);assert.deepEqual(ui.requests.slice(beforeNative).map(r=>r.route),[`/api/tasks/${task.id}`,'/api/tasks']);assert.equal(ui.ids.get('tasks').children.length,1);assert.equal(ui.ids.get('tasks').children[0].attrs['aria-pressed'],'true');assert.equal(ui.ids.get('relay-terminal').hidden,true);assert.equal(ui.ids.get('relay-terminal').srcdoc,'');
  assert.deepEqual(Object.keys(JSON.parse([...ui.storage.values()][0])).sort(),['csrfToken','expiresAt']);
  const stale=ui.ids.get('relay-links').children[0];ui.events.offline();assert.equal(ui.ids.get('relay-links').children.length,0);assert.equal(ui.ids.get('relay-text').value,'');assert.equal(ui.ids.get('relay-message-id').value,'');assert.equal(ui.ids.get('relay-terminal').src,'about:blank');assert.equal(ui.ids.get('relay-terminal').srcdoc,'');
  ui.ids.get('demo-start').events.click();await flush();const before=ui.requests.length;stale.events.click();await flush();assert.equal(ui.requests.length,before,'old reference closure cannot act in a replacement session');
});
test('M4 MOCK UI: message response after private clearance cannot select or display its task',async()=>{
  const ui=harness();ui.ids.get('demo-start').events.click();await flush();
  let release;ui.hold(new Promise(resolve=>{release=resolve}));ui.ids.get('relay-message-id').value='held';ui.ids.get('relay-text').value='hello';
  ui.ids.get('relay-form').events.submit({preventDefault(){}});await flush();ui.events.offline();release();await flush();
  assert.equal(ui.ids.get('relay-links').children.length,0);assert.equal(ui.ids.get('tasks').children.length,0);assert.equal(ui.ids.get('task-identity').textContent,'');assert.doesNotMatch(ui.ids.get('message').textContent,/11111111/);
});
