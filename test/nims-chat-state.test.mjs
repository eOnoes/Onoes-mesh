import test from 'node:test';
import assert from 'node:assert/strict';
import {createNimsChatState} from '../public/nims-chat-state.mjs';
const a='11111111-1111-4111-8111-111111111111',b='22222222-2222-4222-8222-222222222222';
const catalog={project:{id:'p',label:'Project'},conversations:[{id:a,title:'A'},{id:b,title:'B'}],nextCursor:null};
const message=(id,text)=>({id,role:'assistant',text});
const page=(id,groups,olderTurnCursor=null)=>({conversation:{id,title:id===a?'A':'B',status:'idle'},groups,olderTurnCursor});
const group=(id,messages,olderItemCursor=null)=>({id,messages,olderItemCursor});
function fixture(history){return createNimsChatState({request:async(path,options)=>path.endsWith('status')?{configured:true}:path.endsWith('catalog')?catalog:history(JSON.parse(options.body))});}
test('a late response cannot mix the previous conversation into the new selection',async()=>{
  let finish;const core=fixture(input=>input.threadId===a?new Promise(resolve=>finish=resolve):page(b,[group('tB',[message('b','B reply')])]));
  core.setAvailable(true);await core.catalog();const old=core.select(a);await core.select(b);finish(page(a,[group('tA',[message('a','A reply')])]));await old;
  assert.deepEqual(core.state().messages.map(m=>m.text),['B reply']);assert.equal(core.state().selected.id,b);
});
test('older items merge within their own turn rather than before unrelated older turns',async()=>{
  const core=fixture(input=>input.itemCursor?page(a,[group('new',[message('user','User'),message('new-reply','Updated reply')])]):page(a,[group('old',[message('old-reply','Old reply')]),group('new',[message('new-reply','Reply')],'native-item-page')],'older-turns'));
  core.setAvailable(true);await core.catalog();await core.select(a);await core.older();
  assert.deepEqual(core.state().messages.map(m=>m.id),['old-reply','user','new-reply']);
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
