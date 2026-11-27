import test from 'node:test';
import assert from 'node:assert/strict';
import {taskContext,createMindWorkspace,createMindRecallView} from '../public/mind-workspace.mjs';
import {startApp} from '../server.mjs';
import {randomUUID} from 'node:crypto';
import {readFile} from 'node:fs/promises';

class Element {
  children=[]; events={}; style={}; value=''; hidden=false; disabled=false; textContent=''; tag='';
  attributes={}; setAttribute(name,value) {this.attributes[name]=value;} removeAttribute(name) {delete this.attributes[name];}
  addEventListener(name,fn) {this.events[name]=fn;}
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
  const mind=createMindWorkspace({root,doc:{createElement:tag=>Object.assign(new Element(),{tag})},request:async(...args)=>{calls.push(args);return request(...args);},openTask:id=>opened.push(id)});
  mind.setTasks([task,{id:'two',title:'Other task'}]);mind.setAvailable(true);
  const [memorySection,saved]=root.children;
  const [,,select,read,forget,state,content]=saved.children;
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

test('memory search is primary and optional task lookup stays closed without reads',async()=>{
  const f=fixture();
  const [memorySection,saved]=f.root.children;
  assert.equal(memorySection.tag,'section');
  assert.equal(memorySection.children[0].tag,'h2');
  assert.equal(memorySection.children[0].textContent,'Onoes-Mind memory');
  assert.notEqual(saved,memorySection);
  assert.equal(saved.tag,'details');
  assert.equal(saved.children[0].tag,'summary');
  assert.equal(saved.children[0].textContent,'Saved task context (optional)');
  assert.equal(saved.open,undefined); // starts closed: no open attribute or property set
  assert.equal(f.select.children.map(n=>n.textContent).join(','),'Choose a task…,<script>source title</script>,Other task');
  assert.equal(f.calls.length,0);
  saved.open=true; saved.events.toggle?.();
  f.choose();
  assert.equal(f.calls.length,0);
  saved.open=false; saved.events.toggle?.();
  assert.equal(f.calls.length,0);
});

test('Mind module is served byte-for-byte by the actual isolated HTTP app',async()=>{
  const app=await startApp({dataDir:'data/mind-http-'+randomUUID()});
  try {
    const response=await fetch(app.url+'/mind-workspace.mjs');assert.equal(response.status,200);
    assert.match(response.headers.get('content-type'),/javascript/);
    assert.equal(await response.text(),await readFile(new URL('../public/mind-workspace.mjs',import.meta.url),'utf8'));
  } finally {await app.close();}
});


test('canonical memory view requires explicit reads, preserves provenance and clears private or late results',async()=>{
 const record={record_id:'memory-1',project_id:'project-1',scope_id:'project/onoes-mind/shared',claim:'<script>plain source text</script>',source_class:'fixture',observed_at:null,payload_hash:'hash',provenance:[{type:'fixture',ref:'source.md',content_hash:'evidence-hash'}]};
 const snapshot={schema:'onoes-mind-recall/v1',source:'canonical_ledger',requestId:'request-1',observedAt:new Date().toISOString(),records:[record]};
 let deferred;const calls=[];const root=new Element();
 const view=createMindRecallView({root,doc:{createElement:()=>new Element()},request:async(route,options)=>{calls.push([route,options]);return route.endsWith('/status')?{configured:true,source:'canonical_ledger'}:deferred?deferred:snapshot;}});
 const [,check,,query,read,clear,state,results]=root.children[0].children;
 view.setAvailable(true);assert.equal(calls.length,0);assert.equal(read.disabled,true);
 await check.events.click();assert.match(state.textContent,/deliberately shared/);query.value='sentinel';query.events.input();await read.events.click();
 assert.match(text(results),/memory-1/);assert.match(text(results),/source.md/);assert.match(text(results),/<script>plain source text<\/script>/);
 assert.match(text(results),/Read-only shared project facts/);assert.doesNotMatch(text(results),/Synthetic fixture only/);
 assert.equal(calls.length,2);assert.equal(calls[1][0],'/api/mind/recall');assert.deepEqual(JSON.parse(calls[1][1].body),{query:'sentinel',limit:8});
 clear.events.click();assert.equal(text(results),'');assert.equal(query.value,'');
 let release;deferred=new Promise(resolve=>release=resolve);query.value='sentinel';const pending=read.events.click();view.setAvailable(false);release(snapshot);await pending;
 assert.equal(text(results),'');assert.equal(query.value,'');assert.equal(read.disabled,true);assert.match(state.textContent,/cleared/);
});

test('an unknown configured memory source cannot enable a read in the actual view',async()=>{
 const calls=[];const root=new Element();
 const view=createMindRecallView({root,doc:{createElement:()=>new Element()},request:async route=>{calls.push(route);return {configured:true,source:'unknown'};}});
 const [,check,,query,read,,state,results]=root.children[0].children;
 view.setAvailable(true);await check.events.click();query.value='sentinel';query.events.input();await read.events.click();
 assert.deepEqual(calls,['/api/mind/status']);assert.equal(read.disabled,true);assert.equal(text(results),'');
 // Query edits can replace the status text, but cannot make the unverified source readable.
 assert.equal(query.disabled,true);
});

test('Workroom recall shows readable shared fields and retains the full claim and provenance', async () => {
 const fact = {source:'workroom', cardId:'card-23', title:'<b>Printer clearance</b>', stage:'ready',
  owner:'nims', goal:'Check the hinges.', result:'First line.\n\nSecond line.', blocker:'', futureField:'kept'};
 const claim = JSON.stringify(fact);
 const record = {kind:'project_fact', source_class:'workroom', claim, record_id:'record-23', provenance:[{type:'workroom',ref:'card-23@2',content_hash:'ref-hash'}]};
 const records = [record, {...record,claim:'{invalid'}, {...record,source_class:'operator'}];
 const doc = {createElement:tag => Object.assign(new Element(), {tag})};
 const root = new Element();
 const view = createMindRecallView({root,doc,request:async route => route.endsWith('/status')
  ? {configured:true,source:'canonical_ledger'} : {schema:'onoes-mind-recall/v1',source:'canonical_ledger',records}});
 view.setAvailable(true);
 const [,check,,query,read,,,results] = root.children[0].children;
 await check.events.click(); query.value='clearance'; query.events.input(); await read.events.click();
 const [,card,invalid,otherSource] = results.children;
 const source = card.children.at(-1);
 assert.equal(card.children[0].tag,'h3');
 assert.equal(card.children[0].textContent,fact.title);
 assert.deepEqual(card.children.filter(n=>n.tag==='strong').map(n=>n.textContent),['Stage','Owner','Goal','Result']);
 assert.equal(card.children.find(n=>n.textContent===fact.result).style.whiteSpace,'pre-wrap');
 assert.equal(source.tag,'details'); assert.equal(source.children[0].tag,'summary');
 assert.ok(text(source).includes(claim)); assert.ok(text(source).includes('card-23@2'));
 assert.equal(invalid.children[0].textContent,'{invalid');
 assert.equal(otherSource.children[0].textContent,claim);
});

test('recall navigation requires a matching source and a card on the current board', async () => {
 const id = randomUUID(), other = randomUUID();
 const fact = {source:'workroom', cardId:id, title:'Earlier tray title'};
 const ref = {type:'workroom', ref:`card:${id}@1/2/3`};
 const row = {kind:'project_fact', source_class:'workroom', claim:JSON.stringify(fact), provenance:[ref,{...ref,ref:`card:${id}@2/3/4`}]};
 const records = [row, {...row,provenance:[]}, {...row,provenance:[{...ref,ref:`card:${other}@1/2/3`}]},
  {...row,provenance:[ref,{...ref,ref:`card:${other}@1/2/3`}]}, {...row,source_class:'operator'}, {...row,provenance:[{...ref,ref:ref.ref+'/extra'}]}];
 const f = fixture(async route => route.endsWith('/status') ? {configured:true,source:'canonical_ledger'}
  : {schema:'onoes-mind-recall/v1',source:'canonical_ledger',records});
  const [,check,,query,read,, ,results] = f.root.children[0].children;
 await check.events.click(); query.value='tray'; query.events.input(); await read.events.click();
 const links = results.children.flatMap(article => article.children).filter(n => n.textContent === 'Open current Workroom card');
 assert.equal(links.length,1);
 const [link] = links;
 assert.equal(link.hidden,true); assert.equal(link.attributes.href,undefined);
 f.mind.setTasks([{id,title:'New tray title'}]);
 assert.equal(link.hidden,false); assert.equal(link.attributes.href,'#task='+id);
 f.mind.setTasks([]); assert.equal(link.hidden,true); assert.equal(link.attributes.href,undefined);
 assert.equal(f.calls.length,2);
 f.mind.clear(); assert.equal(results.children.length,0);
});

function recallFixture(records) {
 const snapshot = {schema:'onoes-mind-recall/v1',source:'canonical_ledger',requestId:'request-handoff',observedAt:'2026-11-06T00:00:00Z',records};
 const doc = {createElement:tag => Object.assign(new Element(), {tag})};
 const root = new Element();
 const view = createMindRecallView({root,doc,request:async route => route.endsWith('/status')
  ? {configured:true,source:'canonical_ledger'} : snapshot});
 view.setAvailable(true);
 const [,check,,query,read,,,results] = root.children[0].children;
 return {view,check,query,read,results};
}
async function readOnce(f,queryText='handoff') {
 await f.check.events.click(); f.query.value=queryText; f.query.events.input(); await f.read.events.click();
 return f.results.children[1];
}

test('a valid agent handoff renders a readable card while keeping the full claim and provenance', async () => {
 const handoff = {schema:'onoes-handoff/v1', handoff_id:'handoff-77', project_id:'mesh-alpha', author:'nims',
  recipient:'rook', revision:4, objective:'Finish the hinge pass.\nThen photograph the tray.',
  next_action:'Calibrate hinge 3.\nThen log torque.', completed:['Bench cleared.','<img src=x onerror=alert(1)>'],
  remaining:['Torque log','<a href="https://example.invalid">click me</a>'], futureField:{kept:'intact'}};
 const claim = JSON.stringify(handoff);
 const record = {kind:'project_fact', source_class:'agent_handoff', claim, record_id:'handoff-record-77',
  project_id:'mesh-alpha', scope_id:'project/mesh-alpha/shared', observed_at:'2026-11-05T12:00:00Z',
  payload_hash:'handoff-hash', provenance:[{type:'agent',ref:'handoff:handoff-77',content_hash:'handoff-evidence-hash'}]};
 const f = recallFixture([record]);
 const card = await readOnce(f);
 assert.ok(text(f.results).includes('Read-only shared project facts; source claims are not independent verification.'));
 const heading = card.children.find(n => n.tag === 'h3');
 assert.equal(heading.textContent,'Project handoff');
 const shown = text(card);
 for (const phrase of ['Project mesh-alpha','recorded author nims','recorded recipient rook','Document revision 4',
  'handoff ID handoff-77','Finish the hinge pass.\nThen photograph the tray.','Calibrate hinge 3.\nThen log torque.',
  'Completed (reported)','Bench cleared.','Remaining work','Torque log','handoff-record-77','handoff-hash',
  'handoff:handoff-77','handoff-evidence-hash']) assert.ok(shown.includes(phrase),phrase);
 assert.ok(shown.includes('<img src=x onerror=alert(1)>'));
 assert.ok(shown.includes('<a href="https://example.invalid">click me</a>'));
 assert.ok(!shown.includes('owner-approved fact'));
 assert.ok(!shown.includes('independently verified fact'));
 assert.ok(!shown.includes('current state'));
 assert.ok(!shown.includes('deployed'));
 const action = card.children.find(n => n.textContent === handoff.next_action);
 assert.equal(action.style.whiteSpace,'pre-wrap');
 assert.equal(card.children.filter(n => n.tag === 'a').length,0);
 assert.equal(card.children.filter(n => 'href' in n.attributes).length,0);
 const source = card.children.at(-1);
 assert.equal(source.tag,'details'); assert.equal(source.children[0].tag,'summary');
 assert.ok(text(source).includes(claim));
 assert.ok(text(source).includes('project/mesh-alpha/shared'));
 assert.ok(text(source).includes('futureField'));
 assert.ok(text(source).includes('Source class agent_handoff'));
 assert.ok(text(source).includes('2026-11-05T12:00:00Z'));
});

test('malformed, mismatched or unrecognized handoff claims fall back to the original plain-text claim', async () => {
 const base = {schema:'onoes-handoff/v1', handoff_id:'handoff-9', project_id:'mesh-beta', author:'rook',
  revision:2, next_action:'Inspect the cradle.'};
 const claim = JSON.stringify(base);
 const record = {kind:'project_fact', source_class:'agent_handoff', claim, record_id:'handoff-fallback',
  project_id:'mesh-beta', scope_id:'project/mesh-beta/shared', observed_at:null, payload_hash:'fallback-hash',
  provenance:[{type:'agent',ref:'handoff:handoff-9',content_hash:'fallback-evidence'}]};
 const variants = [
  {...record, claim:'{not json'},
  {...record, claim:JSON.stringify({...base, schema:'onoes-handoff/v2'})},
  {...record, claim:JSON.stringify({...base, schema:undefined})},
  {...record, kind:'conversation_note'},
  {...record, source_class:'workroom'},
  {...record, claim:JSON.stringify({...base, project_id:'mesh-other'})},
  {...record, project_id:'mesh-other'},
  {...record, claim:JSON.stringify({...base, revision:0})},
  {...record, claim:JSON.stringify({...base, revision:1.5})},
  {...record, claim:JSON.stringify({...base, revision:21**71})},
  {...record, claim:JSON.stringify({...base, revision:'3'})},
  {...record, claim:JSON.stringify({...base, author:'Nims'})},
  {...record, claim:JSON.stringify({...base, author:'9nims'})},
  {...record, claim:JSON.stringify({...base, author:'nim s'})},
  {...record, claim:JSON.stringify({...base, author:'a'.repeat(49)})},
  {...record, claim:JSON.stringify({...base, handoff_id:''})},
  {...record, claim:JSON.stringify({...base, handoff_id:'h'.repeat(129)})},
  {...record, claim:JSON.stringify({...base, next_action:'   '})},
  {...record, claim:JSON.stringify({...base, objective:42})},
  {...record, claim:JSON.stringify({...base, recipient:'r'.repeat(97)})},
  {...record, claim:JSON.stringify({...base, completed:'not an array'})},
  {...record, claim:JSON.stringify({...base, completed:[1,2]})},
  {...record, claim:JSON.stringify({...base, remaining:['x'.repeat(4097)]})},
  {...record, claim:JSON.stringify({...base, remaining:Array.from({length:33},(_,i)=>`item ${i}`)})},
  {...record, claim:'null'},
  {...record, claim:JSON.stringify([base])},
  {...record, claim:JSON.stringify('a plain string')}
 ];
 const f = recallFixture([record, ...variants]);
 await f.check.events.click(); f.query.value='cradle'; f.query.events.input(); await f.read.events.click();
 assert.equal(f.results.children.length, variants.length + 2);
 assert.match(text(f.results.children[0]),/Read-only shared project facts; source claims are not independent verification\./);
 const cards = f.results.children.slice(1);
 const control = cards[0];
 const controlSource = control.children.at(-1);
 assert.equal(controlSource.tag,'details');
 assert.ok(control.children.some(n => n.tag === 'h3' && n.textContent === 'Project handoff'),'valid control card has the structured heading');
 assert.ok(text(control).includes('Next action'),'valid control card has the structured next action');
 assert.ok(text(controlSource).includes(claim),'valid control keeps the original claim under Source details');
 for (const [index,card] of cards.slice(1).entries()) {
  const variant = variants[index];
  const source = card.children.at(-1);
  assert.equal(source.tag,'details');
  const shown = text(card);
  assert.ok(!shown.includes('Project handoff'),'no structured heading for variant '+index);
  assert.ok(!shown.includes('Document revision'),'no structured revision for variant '+index);
  assert.ok(!shown.includes('Next action'),'no structured next action for variant '+index);
  assert.ok(!shown.includes('Completed (reported)'));
  assert.ok(!shown.includes('Remaining work'));
  assert.equal(card.children[0].textContent,variant.claim,'original claim unchanged for variant '+index);
  assert.ok(text(source).includes('handoff-fallback'));
  assert.ok(text(source).includes('fallback-hash'));
  assert.ok(text(source).includes('handoff:handoff-9'));
  assert.equal(card.children.filter(n => n.tag === 'a').length,0);
 }
});

test('a late handoff reply after access loss cannot restore structured handoff content', async () => {
 const handoff = {schema:'onoes-handoff/v1', handoff_id:'handoff-late', project_id:'mesh-late', author:'nims',
  revision:1, next_action:'Re-read the gauge.'};
 const record = {kind:'project_fact', source_class:'agent_handoff', claim:JSON.stringify(handoff),
  record_id:'handoff-late-record', project_id:'mesh-late', scope_id:'project/mesh-late/shared',
  observed_at:null, payload_hash:'late-hash', provenance:[]};
 let release;
 const deferred = new Promise(resolve => { release = resolve; });
 const doc = {createElement:tag => Object.assign(new Element(), {tag})};
 const root = new Element();
 const view = createMindRecallView({root,doc,request:async route => route.endsWith('/status')
  ? {configured:true,source:'canonical_ledger'} : deferred});
 view.setAvailable(true);
 const [,check,,query,read,,state,results] = root.children[0].children;
 await check.events.click();
 query.value='gauge';
 const pending = read.events.click();
 view.setAvailable(false);
 release({schema:'onoes-mind-recall/v1',source:'canonical_ledger',requestId:'request-late',observedAt:'2026-11-06T00:00:00Z',records:[record]});
 await pending;
 assert.equal(text(results),'');
 assert.equal(query.value,'');
 assert.equal(read.disabled,true);
 assert.match(state.textContent,/cleared/);
});
