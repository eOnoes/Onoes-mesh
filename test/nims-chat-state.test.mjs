import test from 'node:test';
import assert from 'node:assert/strict';
import {createNimsChatState} from '../public/nims-chat-state.mjs';
const a='11111111-1111-4111-8111-111111111111',b='22222222-2222-4222-8222-222222222222';
const catalog={project:{id:'p',label:'Project'},conversations:[{id:a,title:'A'},{id:b,title:'B'}],nextCursor:null};
const message=(id,text,role='assistant')=>({id,role,text});
const userMessage=(id,text)=>({id,role:'user',text});
const page=(id,groups,olderTurnCursor=null)=>({conversation:{id,title:id===a?'A':'B',status:'idle'},groups,olderTurnCursor});
const group=(id,messages,olderItemCursor=null)=>({id,messages,olderItemCursor});
function fixture(history){return createNimsChatState({request:async(path,options)=>path.endsWith('status')?{configured:true}:path.endsWith('catalog')?catalog:history(JSON.parse(options.body))});}
test('a late response cannot mix the previous conversation into the new selection',async()=>{
  let finish;const core=fixture(input=>input.threadId===a?new Promise(resolve=>finish=resolve):page(b,[group('tB',[message('b','B reply')])]));
  core.setAvailable(true);await core.catalog();const old=core.select(a);await core.select(b);finish(page(a,[group('tA',[message('a','A reply')])]));await old;
  assert.deepEqual(core.state().messages.map(m=>m.text),['B reply']);assert.equal(core.state().selected.id,b);
});
test('older items merge within their own turn rather than before unrelated older turns',async()=>{
  const core=fixture(input=>input.itemCursor?page(a,[group('new',[message('user','User'),message('new-reply','Updated reply')])]):page(a,[group('old',[userMessage('turn-user','Turn prompt'),message('old-reply','Old reply')]),group('new',[message('new-reply','Reply')],'native-item-page')],'older-turns'));
  core.setAvailable(true);await core.catalog();await core.select(a);await core.older();
  assert.deepEqual(core.state().messages.map(m=>m.id),['turn-user','old-reply','user','new-reply']);
  assert.equal(core.state().messages.at(-1).text,'Reply');assert.equal(core.state().hasOlder,true);
});
test('ending access clears native titles, messages and all pending response effects',async()=>{
  let finish;const core=fixture(()=>new Promise(resolve=>finish=resolve));core.setAvailable(true);await core.catalog();const read=core.select(a);
  core.setAvailable(false);finish(page(a,[group('t',[message('secret','private body')])]));await read;
  assert.equal(core.state().selected,null);assert.deepEqual(core.state().messages,[]);assert.deepEqual(core.state().conversations,[]);assert.equal(core.state().project,null);
});
test('refresh updates a native message by ID without duplicating it or discarding older turns',async()=>{
  let phase=0;const core=fixture(()=>phase++?page(a,[group('new',[message('r','Finished')])]):page(a,[group('old',[message('o','Older')]),group('new',[message('r','Streaming')])]));
  core.setAvailable(true);await core.catalog();await core.select(a);await core.refresh();assert.deepEqual(core.state().messages.map(m=>m.text),['Older','Finished']);
});
test('refresh of a notLoaded native conversation shows the label without touching raw state or sending',async()=>{
  const calls=[];
  const core=createNimsChatState({request:async(path,options)=>{
    calls.push(path);
    if(path.endsWith('status'))return{configured:true,readOnly:false};
    if(path.endsWith('catalog'))return {...catalog,project:{id:'33333333-3333-4333-8333-333333333333',label:'Project'}};
    if(path.endsWith('history'))return{conversation:{id:a,title:'A',status:'notLoaded'},groups:[group('t',[message('m1','Saved reply')])],olderTurnCursor:null};
    throw Error('Unexpected mock request '+path);
  },storage:{getItem:()=>null,setItem(){},removeItem(){}}});
  core.setAvailable(true);await core.catalog();
  await core.select(a);
  core.setDraft('unsent draft');
  const before=core.state().canSend;
  assert.equal(core.state().canSend,true);
  await core.refresh();
  const after=core.state();
  assert.ok(after.note.includes('Saved chat'));
  assert.ok(!after.note.includes('notLoaded'));
  assert.equal(after.selected.status,'notLoaded');
  assert.equal(after.selected.id,a);
  assert.deepEqual(after.messages.map(m=>m.text),['Saved reply']);
  assert.equal(after.draft,'unsent draft');
  assert.equal(after.canSend,before);
  assert.deepEqual(calls.filter(p=>!p.endsWith('status')&&!p.endsWith('catalog')&&!p.endsWith('history')),[]);
});

function prefetchFixture(history){
  const calls=[],store=new Map();
  const core=createNimsChatState({request:async(path,options={})=>{
    calls.push({path,method:options.method??'GET',input:options.body?JSON.parse(options.body):null});
    if(path.endsWith('status'))return{configured:true,readOnly:false};
    if(path.endsWith('catalog'))return{...catalog,project:{id:'44444444-4444-4444-8444-444444444444',label:'Project'}};
    if(path.endsWith('history'))return history(JSON.parse(options.body));
    throw Error('Unexpected mutation or fixture request '+path);
  },storage:{getItem:key=>store.get(key)??null,setItem:(key,value)=>store.set(key,value),removeItem:key=>store.delete(key)}});
  return{core,calls,reads:()=>calls.filter(c=>c.path.endsWith('history')).map(c=>c.input)};
}

test('assistant-only initial selection finds the prompt and retains the draft without refresh prefetch',async()=>{
  let finish,entered;const pending=new Promise(resolve=>finish=resolve),started=new Promise(resolve=>entered=resolve);
  const f=prefetchFixture(input=>{
    if(input.itemCursor==='c1'){entered();return pending;}
    assert.equal(input.itemCursor,undefined);
    return page(a,[group('t',[message('reply','Saved reply')],'c1')]);
  });
  f.core.setAvailable(true);await f.core.catalog();const selecting=f.core.select(a);await started;
  f.core.setDraft('unsent draft');
  finish(page(a,[group('t',[userMessage('prompt','Latest owner prompt'),message('reply','Saved reply')],'c2')]));
  await selecting;
  assert.deepEqual(f.reads().map(r=>r.itemCursor),[undefined,'c1']);
  const state=f.core.state();assert.deepEqual(state.messages.map(m=>m.id),['prompt','reply']);
  assert.equal(state.messages[0].role,'user');assert.equal(state.draft,'unsent draft');
  assert.equal(state.canSend,true);assert.equal(state.busy,false);assert.equal(state.selected.id,a);assert.equal(state.hasOlder,true);
  assert.ok(state.note.includes('Idle'));await f.core.refresh();
  assert.deepEqual(f.reads().map(r=>r.itemCursor),[undefined,'c1',undefined]);
  assert.equal(f.core.state().draft,'unsent draft');assert.deepEqual([...f.reads()].map(r=>r.threadId),[a,a,a]);
  assert.deepEqual(f.calls.filter(c=>!/\/(status|catalog|history)$/.test(c.path)),[]);
});

test('two automatic item pages leave the next page for a successful manual older read',async()=>{
  const f=prefetchFixture(input=>{
    const pages={c1:page(a,[group('t',[message('m2','Reply two')],'c2')]),c2:page(a,[group('t',[message('m3','Reply three')],'c3')]),c3:page(a,[group('t',[message('m4','Reply four')],'c4')])};
    if(!input.itemCursor)return page(a,[group('t',[message('m1','Reply one')],'c1')]);
    assert.ok(Object.hasOwn(pages,input.itemCursor),'No automatic request past the cap');return pages[input.itemCursor];
  });
  f.core.setAvailable(true);await f.core.catalog();await f.core.select(a);
  assert.deepEqual(f.reads().map(r=>r.itemCursor),[undefined,'c1','c2']);assert.equal(f.core.state().hasOlder,true);
  assert.deepEqual(f.core.state().messages.map(m=>m.id),['m3','m2','m1']);
  await f.core.older();assert.deepEqual(f.reads().map(r=>r.itemCursor),[undefined,'c1','c2','c3']);
  assert.deepEqual(f.core.state().messages.map(m=>m.id),['m4','m3','m2','m1']);
  assert.equal(f.core.state().hasOlder,true);assert.ok(!f.core.state().note.includes('unavailable'));
});

test('initial user content, turn-only history, failed reads and stalled item cursors stop prefetch',async()=>{
  const user=prefetchFixture(()=>page(a,[group('t',[userMessage('u','Owner prompt'),message('r','Reply')],'unused')]));
  user.core.setAvailable(true);await user.core.catalog();await user.core.select(a);assert.equal(user.reads().length,1);
  const turns=prefetchFixture(()=>page(a,[group('t',[message('r','Reply')])],'older-turn'));
  turns.core.setAvailable(true);await turns.core.catalog();await turns.core.select(a);assert.equal(turns.reads().length,1);assert.equal(turns.core.state().hasOlder,true);
  const failed=prefetchFixture(input=>{if(input.itemCursor)throw Error('synthetic page failure');return page(a,[group('t',[message('r','Reply')],'broken')]);});
  failed.core.setAvailable(true);await failed.core.catalog();await failed.core.select(a);
  assert.deepEqual(failed.reads().map(r=>r.itemCursor),[undefined,'broken']);assert.ok(failed.core.state().note.includes('unavailable'));assert.equal(failed.core.state().hasOlder,true);
  const stalled=prefetchFixture(input=>input.itemCursor?page(a,[group('new',[message('r0','Earlier reply')],'same')]):page(a,[group('old',[message('o','Other turn')]),group('new',[message('r','Reply')],'same')]));
  stalled.core.setAvailable(true);await stalled.core.catalog();await stalled.core.select(a);
  assert.deepEqual(stalled.reads().map(r=>r.itemCursor),[undefined,'same']);assert.deepEqual(stalled.core.state().messages.map(m=>m.id),['o','r0','r']);
  assert.equal(stalled.core.state().hasOlder,true);
});

test('initial prefetch chooses the newest item group and preserves unrelated older turns',async()=>{
  const f=prefetchFixture(input=>{
    if(!input.itemCursor)return page(a,[group('old',[message('old-reply','Earlier turn')],'old-cursor'),group('new',[message('new-reply','Current reply')],'new-cursor')]);
    assert.equal(input.itemCursor,'new-cursor');return page(a,[group('new',[userMessage('new-prompt','Current prompt'),message('new-reply','Current reply')],'remaining')]);
  });
  f.core.setAvailable(true);await f.core.catalog();await f.core.select(a);
  assert.deepEqual(f.reads().map(r=>r.itemCursor),[undefined,'new-cursor']);assert.deepEqual(f.core.state().messages.map(m=>m.id),['old-reply','new-prompt','new-reply']);
  assert.equal(f.core.state().hasOlder,true);
});

test('ending access during an earlier-item prefetch clears and rejects its late response',async()=>{
  let finish,entered;const pending=new Promise(resolve=>finish=resolve),started=new Promise(resolve=>entered=resolve);
  const f=prefetchFixture(input=>{if(input.itemCursor){assert.equal(input.itemCursor,'c1');entered();return pending;}return page(a,[group('t',[message('r','Private reply')],'c1')]);});
  f.core.setAvailable(true);await f.core.catalog();const selecting=f.core.select(a);await started;
  f.core.setDraft('private draft');f.core.setAvailable(false);finish(page(a,[group('t',[userMessage('late','Late private prompt')],'c2')]));await selecting;
  const state=f.core.state();assert.equal(state.available,false);assert.equal(state.selected,null);assert.deepEqual(state.messages,[]);assert.deepEqual(state.conversations,[]);assert.equal(state.draft,'');
  assert.deepEqual(f.reads().map(r=>r.itemCursor),[undefined,'c1']);
});

test('switching conversations during an earlier-item prefetch rejects the old response',async()=>{
  let finish,entered;const pending=new Promise(resolve=>finish=resolve),started=new Promise(resolve=>entered=resolve);
  const f=prefetchFixture(input=>{
    if(input.threadId===b)return page(b,[group('b',[userMessage('b-prompt','B prompt'),message('b-reply','B reply')])]);
    if(input.itemCursor){assert.equal(input.itemCursor,'c1');entered();return pending;}
    return page(a,[group('a',[message('a-reply','A reply')],'c1')]);
  });
  f.core.setAvailable(true);await f.core.catalog();const selecting=f.core.select(a);await started;
  f.core.setDraft('A draft');await f.core.select(b);f.core.setDraft('B draft');finish(page(a,[group('a',[userMessage('late','Late A prompt')],'c2')]));await selecting;
  const state=f.core.state();assert.equal(state.selected.id,b);assert.equal(state.draft,'B draft');assert.deepEqual(state.messages.map(m=>m.id),['b-prompt','b-reply']);
  assert.deepEqual(f.reads().map(r=>[r.threadId,r.itemCursor]),[[a,undefined],[a,'c1'],[b,undefined]]);
});
