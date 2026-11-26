import test from 'node:test';import assert from 'node:assert/strict';import {createHash,randomUUID} from 'node:crypto';
import {createNimsChatState} from '../public/nims-chat-state.mjs';import {NIMS_RECEIPTS} from '../public/nims-send-state.mjs';
const id='11111111-1111-4111-8111-111111111111',projectId='33333333-3333-4333-8333-333333333333';
const hash=async value=>createHash('sha256').update(JSON.stringify(value)).digest('hex');
const storage=()=>{const values=new Map();return {getItem:k=>values.get(k)??null,setItem:(k,v)=>values.set(k,v)};};
function fixture({saved=storage(),send,readOnly=false}={}){
 const requests=[];let messages=[{id:'native-old',role:'assistant',text:'Existing answer'}];
 const request=async(route,options)=>{
  requests.push({route,body:options?.body&&JSON.parse(options.body)});
  if(route.endsWith('/status'))return {configured:true,readOnly};
  if(route.endsWith('/catalog'))return {project:{id:projectId,label:'Native project'},conversations:[{id,title:'Current chat',status:'idle'}],nextCursor:null};
  if(route.endsWith('/history'))return {conversation:{id,title:'Current chat',status:'idle'},groups:[{id:'turn',messages,olderItemCursor:null}],olderTurnCursor:null};
  if(send)return send(route,JSON.parse(options.body));
  const b=JSON.parse(options.body),kind=route.endsWith('/new')?'new':'send',targetId=kind==='new'?b.projectId:b.threadId;
  return {receipt:{requestId:b.requestId,kind,targetId,state:'accepted',nativeThreadId:kind==='send'?id:null,clientThreadId:kind==='new'?id:null,
   payloadHash:await hash(kind==='send'?[kind,targetId,b.text]:[kind,targetId,b.title.trim(),b.text])}};
 };
 const core=createNimsChatState({request,storage:saved,makeId:randomUUID,hash});
 return {core,requests,saved,setMessages:v=>messages=v,async ready(){core.setAvailable(true);await core.catalog();await core.select(id);}};
}
test('Send keeps an accepted user message visible beside a later assistant reply',async()=>{
 const f=fixture();await f.ready();f.core.setDraft('Hello Nims');await f.core.send();
 assert.equal(f.core.state().draft,'');assert.ok(f.core.state().messages.some(m=>m.text==='Hello Nims'&&m.role==='user'&&m.queued));
 f.setMessages([{id:'native-user',role:'user',text:'Hello Nims'},{id:'native-reply',role:'assistant',text:'Hello Eddie'}]);await f.core.refresh();
 assert.deepEqual(f.core.state().messages.map(m=>m.text),['Existing answer','Hello Nims','Hello Eddie']);assert.equal(f.core.state().messages.some(m=>m.queued),false);
});
test('a response loss retains the exact receipt across reload without an automatic send',async()=>{
 const saved=storage();const first=fixture({saved,send:async()=>{throw Error('Synthetic response lost');}});await first.ready();first.core.setDraft('Keep my draft');await first.core.send();
 assert.equal(first.core.state().draft,'Keep my draft');const meta=JSON.parse(saved.getItem(NIMS_RECEIPTS))[0];assert.equal(saved.getItem(NIMS_RECEIPTS).includes('Keep my draft'),false);
 let sent=0;const next=fixture({saved,send:async(route,b)=>{if(route.endsWith('/send'))sent++;return {receipt:{requestId:meta.requestId,kind:meta.kind,targetId:meta.targetId,payloadHash:meta.hash,state:'unconfirmed'}};}});
 await next.ready();assert.equal(sent,0);next.core.setDraft('Keep my draft');await next.core.send();assert.equal(sent,1);
 assert.equal(next.requests.find(v=>v.route.endsWith('/send')).body.requestId,meta.requestId);assert.equal(next.core.state().draft,'Keep my draft');
});
test('browser receipt failure blocks dispatch while leaving reading and draft intact',async()=>{
 const f=fixture({saved:{getItem:()=>null,setItem(){throw Error('Synthetic storage unavailable');}}});await f.ready();f.core.setDraft('Do not send');await f.core.send();
 assert.equal(f.requests.some(r=>r.route.endsWith('/send')),false);assert.equal(f.core.state().draft,'Do not send');assert.equal(f.core.state().canSend,false);
});
test('privacy clearance erases drafts/queued text but retains metadata for a late acknowledgement',async()=>{
 let resolve;const f=fixture({send:()=>new Promise(done=>resolve=done)});await f.ready();f.core.setDraft('Private in-memory draft');const operation=f.core.send();
 await new Promise(done=>setImmediate(done));const meta=JSON.parse(f.saved.getItem(NIMS_RECEIPTS))[0];f.core.setAvailable(false);
 resolve({receipt:{requestId:meta.requestId,kind:meta.kind,targetId:meta.targetId,payloadHash:meta.hash,state:'accepted',nativeThreadId:id}});await operation;
 assert.equal(f.core.state().draft,'');assert.deepEqual(f.core.state().messages,[]);assert.equal(f.saved.getItem(NIMS_RECEIPTS).includes('Private in-memory draft'),false);
});
test('New chat is deliberate and Cancel preserves the existing conversation draft',async()=>{
 const f=fixture();await f.ready();f.core.setDraft('Existing draft');f.core.startNew();f.core.setNewText('An idea');f.core.cancelNew();
 assert.equal(f.requests.some(r=>r.route.endsWith('/new')),false);assert.equal(f.core.state().draft,'Existing draft');
 f.core.startNew();f.core.setNewTitle('New idea');f.core.setNewText('Please plan this idea');await f.core.create();
 const sent=f.requests.find(r=>r.route.endsWith('/new')).body;assert.equal(sent.projectId,projectId);assert.equal(sent.text,'Please plan this idea');
 assert.equal(f.core.state().newChat,false);assert.equal(f.core.state().selected.id,id,'pending client ID is not opened as a ready thread');
});
test('read-only mode never posts a send or create even through state methods',async()=>{
 const f=fixture({readOnly:true});await f.ready();f.core.setDraft('Denied');f.core.startNew();f.core.setNewText('Denied');await f.core.send();await f.core.create();
 assert.equal(f.requests.some(r=>r.route.endsWith('/send')||r.route.endsWith('/new')),false);
});
