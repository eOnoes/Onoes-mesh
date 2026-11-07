import test from 'node:test';import assert from 'node:assert/strict';import vm from 'node:vm';
import {relayProgressSummary} from '../public/relay-task-progress.mjs';
import {mockUI,flush} from './app-ui-fixture.mjs';
const task=(done=false)=>({id:'task-fixture',title:'Selected fixture task',progress:{goal:'A saved goal <img src=x onerror=alert(1)>',decision:'pending',checklist:[{text:'Build the feature',status:done?'done':'working'},{text:'Independent review',status:'pending'}]}});
const walk=node=>[node,...(node.children||[]).flatMap(walk)];
function parts(ui){const root=ui.ids.get('relay-task-progress');return {root,open:ui.ids.get('relay-task-progress-open'),picker:walk(root).find(n=>n.attrs['aria-label']==='Saved task'),refresh:walk(root).find(n=>n.textContent==='Refresh tasks'),text:()=>walk(root).map(n=>n.textContent).join('\n')};}
async function harness(request,timeoutMs=40){const ui=mockUI();await flush();ui.context.progressRequest=request;ui.context.progressTimeout=timeoutMs;
 vm.runInContext("var savedProgress=createRelayTaskProgress({root:document.getElementById('relay-task-progress'),button:document.getElementById('relay-task-progress-open'),request:progressRequest,document,timeoutMs:progressTimeout})",ui.context);return ui;}
const enable=ui=>vm.runInContext('savedProgress.setAvailable(true)',ui.context);
const clear=ui=>vm.runInContext('savedProgress.clear()',ui.context);
const refresh=ui=>vm.runInContext('savedProgress.refresh()',ui.context);
test('saved completion remains pending review and malformed checklist data is refused',()=>{
 const source=task();source.progress.checklist.forEach(s=>s.status='done');
 assert.equal(relayProgressSummary(source).done,2);assert.equal(relayProgressSummary(source).review,'pending');
 assert.throws(()=>relayProgressSummary({...source,progress:{...source.progress,checklist:[{text:'invalid',status:'approved'}]}}));
});
test('selected saved task follows updates without a send, assignment or browser-stored body',async()=>{
 let current=task();const calls=[];const ui=await harness(async(route,options)=>{calls.push({route,options});return route==='/api/workroom'?{tasks:[current]}:{task:current};});enable(ui);const p=parts(ui);
 p.open.events.click();await flush();assert.equal(p.root.open,true);assert.equal(calls.length,1);
 p.picker.value=current.id;p.picker.events.change();await flush();assert.ok(p.text().includes(current.progress.goal));assert.equal(p.open.textContent,'Task · 0/2');
 current=task(true);await refresh(ui);assert.equal(p.open.textContent,'Task · 1/2');assert.ok(p.text().includes('Review: pending'));
 assert.ok(calls.every(call=>!call.options?.method||call.options.method==='GET'));
 assert.ok(calls.every(call=>call.route==='/api/workroom'||call.route==='/api/workroom/task-fixture'));
 assert.ok(!JSON.stringify([...ui.storage]).includes(current.progress.goal));clear(ui);
});
test('unavailable view and unselected polling never request private task data',async()=>{
 const calls=[];const ui=await harness(async route=>{calls.push(route);return {tasks:[]};});const p=parts(ui);
 p.open.events.click();await refresh(ui);assert.deepEqual(calls,[]);
 enable(ui);await refresh(ui);assert.deepEqual(calls,[]);assert.equal(p.open.disabled,false);clear(ui);
});
test('lock clears private titles and progress and ignores an in-flight reply',async()=>{
 let release;const source=task();const ui=await harness(async route=>route==='/api/workroom'?{tasks:[source]}:new Promise(resolve=>release=resolve));enable(ui);const p=parts(ui);
 p.open.events.click();await flush();p.picker.value=source.id;p.picker.events.change();await flush();clear(ui);release({task:source});await flush();
 assert.equal(p.root.open,false);assert.equal(p.open.disabled,true);assert.equal(p.open.textContent,'Task progress');assert.ok(!p.text().includes(source.title));assert.ok(!p.text().includes(source.progress.goal));
});
test('timed out read recovers single-flight and cannot overwrite a fresh result later',async()=>{
 const source=task();let release;let stalled=true,reads=0;
 const ui=await harness(async route=>{if(route==='/api/workroom')return {tasks:[source]};reads++;return stalled?new Promise(resolve=>release=resolve):{task:task(true)};},12);enable(ui);const p=parts(ui);
 p.open.events.click();await flush();p.picker.value=source.id;p.picker.events.change();await flush();await refresh(ui);assert.equal(reads,1);
 await new Promise(resolve=>setTimeout(resolve,25));assert.ok(p.text().includes('may be stale'));
 stalled=false;await refresh(ui);assert.equal(reads,2);assert.equal(p.open.textContent,'Task · 1/2');release({task:source});await flush();assert.equal(p.open.textContent,'Task · 1/2');clear(ui);
});
