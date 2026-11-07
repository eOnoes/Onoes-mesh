import test from 'node:test';
import assert from 'node:assert/strict';
import {taskContext,createMindWorkspace} from '../public/mind-workspace.mjs';
import {startApp} from '../server.mjs';
import {randomUUID} from 'node:crypto';
import {readFile} from 'node:fs/promises';

class Element {
  children=[]; events={}; style={}; value=''; hidden=false; disabled=false; textContent='';
  setAttribute() {} addEventListener(name,fn) {this.events[name]=fn;}
  append(...nodes) {this.children.push(...nodes);}
  replaceChildren(...nodes) {this.children=nodes;}
  get firstChild() {return this.children[0];}
}
const task = {id:'one',title:'<script>source title</script>',description:'Saved description',revision:3,updatedAt:'2026-11-06T00:00:00Z',
  workroom:{revision:2,project:'Mesh',stage:'review'},progress:{revision:4,goal:'Saved goal',result:'Unreviewed result',
    checklist:[{text:'One check',status:'done'}],evidence:'file://untrusted-reference',decision:'pending',reviewer:''},
  messages:[{text:'PRIVATE TRANSCRIPT'}],assignments:[{secret:'PRIVATE ASSIGNMENT'}]};
const text = element => [element.textContent,...element.children.map(text)].join('\n');
function fixture(request=async()=>({task:structuredClone(task)})) {
  const root=new Element(),opened=[],calls=[];
  const mind=createMindWorkspace({root,doc:{createElement:()=>new Element()},request:async(...args)=>{calls.push(args);return request(...args);},openTask:id=>opened.push(id)});
  mind.setTasks([task,{id:'two',title:'Other task'}]);mind.setAvailable(true);
  const [,select,read,forget,state,content]=root.children;
  const choose=(id='one')=>{select.value=id;select.events.change();};
  return {root,mind,select,read,forget,state,content,choose,calls,opened};
}
test('Mind retrieves only an explicitly selected task with saved provenance and no transcript or mutation',async()=>{
  const f=fixture();assert.equal(f.calls.length,0);assert.equal(f.read.disabled,true);
  await f.read.events.click();assert.equal(f.calls.length,0);
  f.choose();await f.read.events.click();
  assert.deepEqual(f.calls,[['/api/workroom/one']]);
  const shown=text(f.content);
  for(const phrase of [task.title,'task one','task 3, brief 2, progress 4','Recorded decision: pending','Unreviewed result','file://untrusted-reference'])assert.ok(shown.includes(phrase),phrase);
  assert.ok(!shown.includes('PRIVATE TRANSCRIPT'));assert.ok(!shown.includes('PRIVATE ASSIGNMENT'));
  f.content.children.at(-1).events.click();assert.deepEqual(f.opened,['one']);
  const before=structuredClone(task);taskContext(task);assert.deepEqual(task,before);
  f.forget.events.click();assert.equal(f.content.hidden,true);assert.equal(text(f.content),'');assert.equal(f.select.value,'');
});
test('Mind clears selected content and drops late replies after access loss or explicit clear',async()=>{
  for(const clear of [f=>f.mind.clear(),f=>f.mind.setAvailable(false),f=>f.forget.events.click(),f=>f.mind.setTasks(undefined)]){
    let release;const pending=new Promise(resolve=>release=resolve);const f=fixture(()=>pending);
    f.choose();const read=f.read.events.click();clear(f);release({task});await read;
    assert.equal(f.content.hidden,true);assert.equal(text(f.content),'');
  }
});
test('Mind never displays a different task, stale selection, failed read or malformed provenance',async()=>{
  for(const response of [()=>({task:{...task,id:'two'}}),()=>{throw Error('Read failed');},()=>({task:{...task,progress:{}}})]){
    const f=fixture(response);f.choose();await f.read.events.click();assert.equal(f.content.hidden,true);assert.equal(text(f.content),'');
  }
  let release;const f=fixture(()=>new Promise(resolve=>release=resolve));f.choose();const reading=f.read.events.click();f.choose('two');release({task});await reading;assert.equal(text(f.content),'');
});
test('Mind clears an old snapshot on selection/list refresh and leaves independent records separate',async()=>{
  const f=fixture();f.choose();await f.read.events.click();assert.equal(f.content.hidden,false);
  f.choose('two');assert.equal(f.content.hidden,true);assert.equal(f.calls.length,1);
  f.mind.setTasks([task]);assert.equal(f.select.value,'');assert.equal(f.content.hidden,true);
  f.mind.clear();assert.equal(f.select.children.length,0);assert.equal(f.read.disabled,true);
});

test('Mind module is served byte-for-byte by the actual isolated HTTP app',async()=>{
  const app=await startApp({dataDir:'data/mind-http-'+randomUUID()});
  try {
    const response=await fetch(app.url+'/mind-workspace.mjs');assert.equal(response.status,200);
    assert.match(response.headers.get('content-type'),/javascript/);
    assert.equal(await response.text(),await readFile(new URL('../public/mind-workspace.mjs',import.meta.url),'utf8'));
  } finally {await app.close();}
});
