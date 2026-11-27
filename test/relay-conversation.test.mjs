import test from 'node:test';
import assert from 'node:assert/strict';
import {createHash,randomUUID} from 'node:crypto';
import {startApp} from '../server.mjs';
import {readFile} from 'node:fs/promises';
import {createRelayConversation,RECEIPT_KEY} from '../public/relay-conversation.mjs';

const digest=async text=>createHash('sha256').update(text).digest('hex');
function fixture({storage=new Map(),intercept}={}) {
  const calls=[],receipts=new Map();let agents=[{id:'echo',name:'Echo',conversation_id:'one',status:'idle'},{id:'deep',name:'Deep',conversation_id:'two',status:'idle'}];
  let history={messages:[{id:1,k:'ag',t:'Original history'}]},offline=false;
  const request=async(route,options)=>{
    calls.push({route,options});if(offline)throw Error('offline');
    const result=intercept?.(route,options);if(result!==undefined)return result;
    if(route==='/api/relay/native/api/agents')return structuredClone(agents);
    if(route==='/relay/api/mesh-capabilities')return {taskSessionBinding:1};
    if(route.split('?')[0].endsWith('/messages'))return structuredClone(history);
    if(options?.method==='POST'){
      const body=JSON.parse(options.body),aid=route.split('/')[4];
      assert.deepEqual(Object.keys(body).sort(),['expectedConversationId','id','text']);
      if(receipts.has(body.id)){assert.deepEqual(receipts.get(body.id),{aid,...body});return {ok:true,duplicate:true};}
      assert.equal(agents.find(a=>a.id===aid)?.conversation_id,body.expectedConversationId);
      receipts.set(body.id,{aid,...body});return {ok:true};
    }
    throw Error('Unexpected request '+route);
  };
  const store={getItem:k=>storage.get(k)??null,setItem:(k,v)=>storage.set(k,v),removeItem:k=>storage.delete(k)};
  const core=createRelayConversation({request,storage:store,digest,uuid:randomUUID});
  return {core,calls,receipts,storage,setAgents:value=>{agents=value;},setHistory:value=>{history=value;},setOffline:value=>{offline=value;},
    ready:async()=>{await core.setAvailable(true);await core.select('echo');}};
}
test('Relay chooses no fallback agent and sends once only to the explicit displayed conversation',async()=>{
  const f=fixture();await f.core.setAvailable(true);assert.equal(f.core.state().destination,null);
  assert.equal(f.calls.some(c=>c.route.split('?')[0].endsWith('/messages')),false);
  await f.core.select('echo');f.core.setDraft('ordinary message');await Promise.all([f.core.send(),f.core.send()]);
  assert.equal(f.calls.filter(c=>c.options?.method==='POST').length,1);assert.equal(f.receipts.size,1);
  assert.equal(f.core.state().draft,'');assert.equal(f.storage.size,0);
  f.setAgents([{id:'deep',conversation_id:'two'}]);await f.core.refresh();
  assert.equal(f.core.state().destination.agentId,'echo');assert.equal(f.core.state().canSend,false);
  assert.ok(!f.calls.some(c=>c.route.includes('/deep/')&&c.options?.method==='POST'));
});
test('Relay clears empty or edited history even with an unchanged last ID and keeps drafts across an outage',async()=>{
  const f=fixture();await f.ready();f.core.setDraft('unsent');f.setOffline(true);await f.core.refresh();
  assert.equal(f.core.state().draft,'unsent');assert.equal(f.core.state().live,false);assert.match(f.core.state().note,/stale/);
  f.setOffline(false);f.setHistory({messages:[{id:1,k:'ag',t:'Edited history'}]});await f.core.refresh();assert.equal(f.core.state().messages[0].t,'Edited history');
  f.setHistory({messages:[]});await f.core.refresh();assert.deepEqual(f.core.state().messages,[]);assert.equal(f.core.state().draft,'unsent');
});
test('Conversation rotation pauses fresh sends and requires explicit rebinding; per-session drafts stay separate',async()=>{
  const f=fixture();await f.ready();f.core.setDraft('old draft');f.setAgents([{id:'echo',conversation_id:'new'}]);await f.core.refresh();
  assert.equal(f.core.state().destination.sessionId,'one');assert.equal(f.core.state().canSend,false);
  await f.core.send();assert.equal(f.receipts.size,0);await f.core.select('echo');assert.equal(f.core.state().destination.sessionId,'new');assert.equal(f.core.state().draft,'');
  f.core.setDraft('new draft');f.setAgents([{id:'echo',conversation_id:'one'}]);await f.core.refresh();await f.core.select('echo');assert.equal(f.core.state().draft,'old draft');
});
test('Uncertain sends persist only receipt metadata, retry the same identity after reload, and reject changed text/destination',async()=>{
  let lose=true;const f=fixture({intercept:(route,options)=>{if(options?.method==='POST'&&lose){lose=false;throw Error('response lost');}}});
  await f.ready();f.core.setDraft('private original');await f.core.send();const receipt=JSON.parse(f.storage.get(RECEIPT_KEY));
  assert.deepEqual(Object.keys(receipt).sort(),['agentId','hash','id','sessionId','version']);assert.ok(!f.storage.get(RECEIPT_KEY).includes('private original'));
  f.core.setDraft('changed');await f.core.send();assert.equal(f.calls.filter(c=>c.options?.method==='POST').length,1);
  await f.core.select('deep');f.core.setDraft('other');await f.core.send();assert.equal(f.calls.filter(c=>c.options?.method==='POST').length,1);
  const resumed=fixture({storage:f.storage});await resumed.core.setAvailable(true);assert.equal(resumed.core.state().destination.sessionId,'one');assert.equal(resumed.core.state().draft,'');
  resumed.core.setDraft('private original');await resumed.core.send();assert.equal([...resumed.receipts.keys()][0],receipt.id);assert.equal(resumed.storage.size,0);
});
test('An accepted send with a lost response resolves by duplicate receipt even after native conversation rotation',async()=>{
  let lost=true;let f;
  f=fixture({intercept:(route,options)=>{
    if(options?.method==='POST'&&lost){lost=false;const b=JSON.parse(options.body);f.receipts.set(b.id,{aid:'echo',...b});throw Error('lost after acceptance');}
  }});
  await f.ready();f.core.setDraft('original');await f.core.send();const id=JSON.parse(f.storage.get(RECEIPT_KEY)).id;
  f.setAgents([{id:'echo',conversation_id:'new'}]);await f.core.refresh();assert.equal(f.core.state().destination.sessionId,'one');
  await f.core.send();const posts=f.calls.filter(c=>c.options?.method==='POST');assert.equal(posts.length,2);
  assert.ok(posts.every(c=>JSON.parse(c.options.body).id===id&&JSON.parse(c.options.body).expectedConversationId==='one'));assert.equal(f.receipts.size,1);assert.equal(f.storage.size,0);
});
test('Unavailable capability/storage and changed preflight destination never dispatch',async()=>{
  for(const intercept of [(r)=>r.endsWith('mesh-capabilities')?{}:undefined,(r)=>r==='/api/relay/native/api/agents'&&swap?[]:undefined]){
    var swap=false;const f=fixture({intercept});await f.ready();swap=true;f.core.setDraft('blocked');await f.core.send();assert.equal(f.receipts.size,0);
  }
  const f=fixture();await f.ready();f.storage.set=()=>{throw Error('storage full');};f.core.setDraft('not sent');await f.core.send();assert.equal(f.receipts.size,0);
});
test('Privacy clearance drops late history/acknowledgments and all draft/history content without replay',async()=>{
  let release,hold=false;const f=fixture({intercept:r=>hold&&r.split('?')[0].endsWith('/messages')?new Promise(resolve=>release=resolve):undefined});
  await f.ready();f.core.setDraft('private');hold=true;const reading=f.core.refresh();await new Promise(resolve=>setImmediate(resolve));
  await f.core.setAvailable(false);release({messages:[{t:'late secret'}]});await reading;
  assert.equal(f.core.state().destination,null);assert.deepEqual(f.core.state().messages,[]);assert.equal(f.core.state().draft,'');assert.equal(f.core.state().agents.length,0);
  let acknowledge;const g=fixture({intercept:(r,o)=>o?.method==='POST'?new Promise(resolve=>acknowledge=resolve):undefined});await g.ready();g.core.setDraft('unknown');const sending=g.core.send();await new Promise(resolve=>setImmediate(resolve));await g.core.setAvailable(false);acknowledge({ok:true});await sending;
  assert.equal(g.core.state().destination,null);assert.equal(g.core.state().draft,'');assert.ok(g.storage.has(RECEIPT_KEY));
});

test('Slow Relay reads coalesce repeated polls and still paint the completed history',async()=>{
  let hold=false,releaseList,releaseHistory;
  const f=fixture({intercept:r=>{
    if(!hold)return;
    if(r==='/api/relay/native/api/agents')return new Promise(resolve=>releaseList=resolve);
    if(r.split('?')[0].endsWith('/messages'))return new Promise(resolve=>releaseHistory=resolve);
  }});
  await f.ready();f.core.setDraft('keep my draft');hold=true;const before=f.calls.length;
  const first=f.core.refresh();await new Promise(resolve=>setImmediate(resolve));
  const polls=Array.from({length:6},()=>f.core.refresh());
  assert.equal(f.calls.length-before,1,'timer/manual refreshes must share the pending agent read');
  releaseList([{id:'echo',name:'Echo',conversation_id:'one'}]);
  await new Promise(resolve=>setImmediate(resolve));
  const more=f.core.refresh();assert.equal(f.calls.length-before,2,'history read is shared too');
  releaseHistory({messages:[{id:2,k:'ag',t:'Slow response arrived'}]});
  await Promise.all([first,...polls,more]);
  assert.equal(f.core.state().messages[0].t,'Slow response arrived');
  assert.equal(f.core.state().draft,'keep my draft');assert.equal(f.receipts.size,0);
});

test('Selecting another conversation bypasses an old slow read without allowing its late result to repaint',async()=>{
  let hold=false,release;
  const f=fixture({intercept:r=>hold&&r.includes('/echo/')&&r.split('?')[0].endsWith('/messages')?new Promise(resolve=>release=resolve):undefined});
  await f.ready();hold=true;const old=f.core.refresh();await new Promise(resolve=>setImmediate(resolve));
  await f.core.select('deep');assert.equal(f.core.state().destination.agentId,'deep');
  assert.equal(f.core.state().messages[0].t,'Original history');
  release({messages:[{id:9,t:'Late Echo history'}]});await old;
  assert.equal(f.core.state().destination.agentId,'deep');assert.equal(f.core.state().messages[0].t,'Original history');
});

test('A locked and reconnected Relay does not wait for or accept the previous admission read',async()=>{
  let hold=false,release;
  const f=fixture({intercept:r=>hold&&r.split('?')[0].endsWith('/messages')?new Promise(resolve=>release=resolve):undefined});
  await f.ready();hold=true;const old=f.core.refresh();await new Promise(resolve=>setImmediate(resolve));
  await f.core.setAvailable(false);hold=false;await f.core.setAvailable(true);await f.core.select('echo');
  assert.equal(f.core.state().live,true);release({messages:[{t:'Old admission secret'}]});await old;
  assert.equal(f.core.state().messages[0].t,'Original history');assert.equal(f.core.state().draft,'');
});

test('A failed shared Relay refresh permits a later deliberate read',async()=>{
  const f=fixture();await f.ready();f.setOffline(true);
  await Promise.all([f.core.refresh(),f.core.refresh()]);assert.equal(f.core.state().live,false);
  f.setOffline(false);f.setHistory({messages:[{id:2,t:'Recovered'}]});await f.core.refresh();
  assert.equal(f.core.state().live,true);assert.equal(f.core.state().messages[0].t,'Recovered');
});
test('Legacy uncertain receipts migrate without dispatch; invalid/conflicting records stay preserved and blocked',async()=>{
  const id=randomUUID(),legacy={id,agentId:'echo',sessionId:'one',text:'old original'};
  const storage=new Map([['mesh.relay.pending.v1',JSON.stringify(legacy)]]);const f=fixture({storage});await f.core.setAvailable(true);
  assert.equal(f.core.state().draft,'old original');assert.equal(f.core.state().pending.id,id);assert.equal(storage.has('mesh.relay.pending.v1'),false);assert.ok(!storage.get(RECEIPT_KEY).includes('old original'));assert.equal(f.receipts.size,0);
  for(const raw of ['{}','not json']){const g=fixture({storage:new Map([['mesh.relay.pending.v1',raw]])});await g.core.setAvailable(true);assert.equal(g.core.state().canSend,false);assert.equal(g.storage.get('mesh.relay.pending.v1'),raw);}
});
test('Static HTTP serves the exact conversation module; the app no longer binds task creation to ordinary submit',async()=>{
  const app=await startApp({dataDir:'data/relay-chat-http-'+randomUUID()});
  try{const res=await fetch(app.url+'/relay-conversation.mjs');assert.equal(res.status,200);assert.equal(await res.text(),await readFile(new URL('../public/relay-conversation.mjs',import.meta.url),'utf8'));}finally{await app.close();}
  const appSource=await readFile(new URL('../public/app.js',import.meta.url),'utf8');assert.ok(!appSource.includes("$('relay-form').addEventListener('submit'"));
});


test('Phone conversation discovery uses the bounded Mesh agent API for its directory',async()=>{
  const f=fixture();await f.ready();
  assert.ok(f.calls.some(call=>call.route==='/api/relay/native/api/agents'));
  assert.equal(f.calls.some(call=>call.route==='/relay/api/agents'),false);
  assert.equal(f.core.state().destination.agentId,'echo');
  assert.equal(f.core.state().live,true);
});


test('Paged history keeps older messages through polling and preserves the pinned draft',async()=>{
 const rows=(first,last)=>Array.from({length:last-first+1},(_,i)=>({id:first+i,k:'ag',t:'Message '+(first+i)}));
 let latest={messages:rows(21,30),oldest_id:21,newest_id:30,has_more:true};
 const f=fixture({intercept:r=>{
  if(!r.includes('/messages?'))return;
  const u=new URL(r,'http://fixture');assert.equal(u.searchParams.get('limit'),'10');
  return u.searchParams.get('before')?{messages:rows(11,20),oldest_id:11,newest_id:20,has_more:true}:latest;
 }});
 await f.ready();assert.equal(f.core.state().hasOlder,true);f.core.setDraft('keep this');
 await Promise.all([f.core.loadOlder(),f.core.loadOlder()]);
 assert.equal(f.calls.filter(c=>c.route.includes('&before=')).length,1);
 assert.equal(f.core.state().messages.length,20);
 latest={messages:rows(28,37),oldest_id:28,newest_id:37,has_more:true};await f.core.refresh();
 assert.deepEqual(f.core.state().messages.map(m=>Number(m.id)),Array.from({length:27},(_,i)=>i+11));
 assert.equal(f.core.state().draft,'keep this');assert.equal(f.core.state().destination.sessionId,'one');
 assert.equal(f.receipts.size,0);assert.equal(f.storage.size,0);
});

test('Paged history fills a large reconnect gap forward without skipping replies',async()=>{
 const rows=(first,last)=>Array.from({length:last-first+1},(_,i)=>({id:first+i,t:'Message '+(first+i)}));let reconnect=false;
 const f=fixture({intercept:r=>{
  if(!r.includes('/messages?'))return;
  const after=new URL(r,'http://fixture').searchParams.get('after');
  if(after)return {messages:rows(31,40),oldest_id:31,newest_id:40,has_more:true};
  return reconnect?{messages:rows(51,60),oldest_id:51,newest_id:60,has_more:true}:{messages:rows(21,30),oldest_id:21,newest_id:30,has_more:true};
 }});
 await f.ready();reconnect=true;await f.core.refresh();
 assert.equal(f.calls.at(-1).route.endsWith('&after=30'),true);
 assert.deepEqual(f.core.state().messages.map(m=>Number(m.id)),Array.from({length:20},(_,i)=>i+21));
 assert.match(f.core.state().note,/Catching up/);assert.equal(f.receipts.size,0);
});

test('Late older history cannot repaint after privacy clearance; failure retains the existing transcript',async()=>{
 let release,hold=false;
 const f=fixture({intercept:r=>r.includes('/messages?')?(r.includes('&before=')?(hold?new Promise(resolve=>release=resolve):Promise.reject(Error('offline'))):{messages:[{id:21,t:'Current'}],oldest_id:21,newest_id:21,has_more:true}):undefined});
 await f.ready();await f.core.loadOlder();assert.equal(f.core.state().messages[0].t,'Current');assert.equal(f.core.state().hasOlder,true);
 hold=true;const loading=f.core.loadOlder();await new Promise(resolve=>setImmediate(resolve));await f.core.setAvailable(false);
 release({messages:[{id:20,t:'Late private'}],oldest_id:20,newest_id:20,has_more:false});await loading;
 assert.deepEqual(f.core.state().messages,[]);assert.equal(f.core.state().hasOlder,false);assert.equal(f.core.state().loadingOlder,false);
});
test('Maintenance keeps history and drafts usable and reopening never sends by itself', async () => {
  const f = fixture();
  f.setHistory({messages:[{id:1,k:'ag',t:'Earlier reply'}],meshDispatchState:'paused'});
  await f.ready();
  f.core.setDraft('Finish this later');
  assert.equal(f.core.state().messages[0].t, 'Earlier reply');
  assert.equal(f.core.state().canSend, false);
  assert.match(f.core.state().note, /paused for Mesh maintenance/);
  await f.core.send();
  assert.equal(f.storage.size, 0);
  f.setHistory({messages:[{id:1,k:'ag',t:'Earlier reply'}],meshDispatchState:'open'});
  await f.core.refresh();
  assert.equal(f.core.state().canSend, true);
  assert.equal(f.core.state().draft, 'Finish this later');
  assert.equal(f.calls.filter(call => call.options?.method === 'POST').length, 0);
  await f.core.send();
  assert.equal(f.receipts.size, 1);
});

test('Pause between history and Send leaves a new draft without a retry receipt', async () => {
  const f = fixture({intercept:route => route.endsWith('/mesh-capabilities')
    ? {taskSessionBinding:1,meshDispatchState:'paused'} : undefined});
  await f.ready();
  f.core.setDraft('Keep my words');
  await f.core.send();
  assert.equal(f.core.state().draft, 'Keep my words');
  assert.equal(f.core.state().canSend, false);
  assert.equal(f.core.state().pending, null);
  assert.equal(f.storage.size, 0);
  assert.equal(f.calls.filter(call => call.options?.method === 'POST').length, 0);
});

test('A maintenance pause preserves an earlier uncertain message and its original ID', async () => {
  let paused = false;
  const f = fixture({intercept:(route, options) => {
    if (options?.method === 'POST') throw Error('Acknowledgement lost');
    if (route.endsWith('/mesh-capabilities') && paused) return {taskSessionBinding:1, meshDispatchState:'paused'};
  }});
  await f.ready();
  f.core.setDraft('Already attempted');
  await f.core.send();
  const receipt = f.storage.get(RECEIPT_KEY);
  assert.ok(receipt);
  paused = true;
  await f.core.send();
  assert.equal(f.storage.get(RECEIPT_KEY), receipt);
  assert.equal(f.core.state().draft, 'Already attempted');
  assert.match(f.core.state().note, /earlier receipt is saved/);
  assert.equal(f.calls.filter(call => call.options?.method === 'POST').length, 1);
});

test('Oversized drafts stay complete and cannot dispatch', async () => {
  const f=fixture(); await f.ready();
  const originalHistory=f.core.state().messages;
  const oversized='a'.repeat(4000)+'VISIBLE SUFFIX';
  f.core.setDraft(oversized);
  assert.equal(f.core.state().draft,oversized);
  assert.equal(f.core.state().canSend,false);
  assert.match(f.core.state().note,/4014\/4000.*shorten/i);
  const calls=f.calls.length;
  await f.core.send();
  assert.equal(f.calls.length,calls,'oversized send must not request preflight or delivery');
  assert.equal(f.storage.size,0); assert.equal(f.receipts.size,0);
  assert.deepEqual(f.core.state().messages,originalHistory);
  await f.core.refresh();
  assert.equal(f.core.state().draft,oversized);
  assert.match(f.core.state().note,/4014\/4000/);
  const valid='b'.repeat(3990)+'END MARKER';
  assert.equal(valid.length,4000);
  f.core.setDraft(valid);
  assert.equal(f.core.state().canSend,true);
  assert.doesNotMatch(f.core.state().note,/4014\/4000|shorten/i);
  await f.core.send();
  assert.equal([...f.receipts.values()][0].text,valid);
  assert.equal(f.receipts.size,1); assert.equal(f.core.state().draft,'');
});

test('UTF16 limit includes surrogate pairs without splitting a draft', async () => {
  const f=fixture(); await f.ready();
  const oversized='a'.repeat(3999)+'😀';
  assert.equal(oversized.length,4001);
  f.core.setDraft(oversized);
  assert.equal(f.core.state().draft,oversized);
  assert.equal(f.core.state().canSend,false);
  const before=f.calls.length; await f.core.send(); assert.equal(f.calls.length,before);
  const valid='a'.repeat(3998)+'😀';
  assert.equal(valid.length,4000); f.core.setDraft(valid);
  assert.equal(f.core.state().canSend,true); await f.core.send();
  assert.equal([...f.receipts.values()][0].text,valid);
});

test('Oversized edits retain an uncertain receipt for its exact original retry', async () => {
  let lose=true;
  const f=fixture({intercept:(_route,options)=>{
    if(options?.method==='POST'&&lose){lose=false;throw Error('acknowledgement lost');}
  }});
  await f.ready(); f.core.setDraft('exact original'); await f.core.send();
  const saved=f.storage.get(RECEIPT_KEY), receipt=JSON.parse(saved);
  f.core.setDraft('x'.repeat(4001));
  const before=f.calls.length; await f.core.send();
  assert.equal(f.calls.length,before); assert.equal(f.storage.get(RECEIPT_KEY),saved);
  assert.equal(f.core.state().pending.id,receipt.id);
  f.core.setDraft('exact original'); await f.core.send();
  assert.equal([...f.receipts.keys()][0],receipt.id); assert.equal(f.storage.size,0);
});

test('Length warning follows the selected draft and preserves maintenance and privacy boundaries', async () => {
  const f=fixture();
  f.setHistory({messages:[],meshDispatchState:'paused'}); await f.ready();
  f.core.setDraft('e'.repeat(4001));
  assert.match(f.core.state().note,/maintenance/); assert.match(f.core.state().note,/4001\/4000/);
  await f.core.select('deep'); f.core.setDraft('short deep draft');
  assert.doesNotMatch(f.core.state().note,/4001\/4000|shorten/i);
  await f.core.select('echo'); assert.equal(f.core.state().draft,'e'.repeat(4001));
  assert.match(f.core.state().note,/4001\/4000/);
  await f.core.setAvailable(false); assert.equal(f.core.state().draft,'');
  assert.doesNotMatch(f.core.state().note,/4001\/4000|shorten/i);
});

test('stopped agent unanswered message shows observed guidance without sending', async () => {
  const f = fixture();
  f.setHistory({messages:[{id:1,k:'you',t:'My latest message'}]});
  f.setAgents([{id:'echo',name:'Echo',conversation_id:'one',status:'stopped'}]);
  await f.ready();
  assert.match(f.core.state().note, /Echo is stopped/);
  assert.match(f.core.state().note, /no agent reply yet/);
  assert.match(f.core.state().note, /Check the agent connection before sending again/);
  assert.equal(f.core.state().draft,'');
  f.core.setDraft('my draft');
  assert.equal(f.core.state().canSend, true, 'stopped status alone must not change Send eligibility');
  const postsBefore = f.calls.filter(c => c.options?.method === 'POST').length;
  await f.core.refresh();
  assert.equal(f.core.state().draft,'my draft');
  assert.deepEqual(f.core.state().messages.map(m=>m.t),['My latest message']);
  assert.equal(f.calls.filter(c => c.options?.method === 'POST').length, postsBefore, 'no extra POST and no automatic retry');
  assert.equal(f.receipts.size,0); assert.equal(f.storage.size,0);
});

test('stopped reply guidance clears after status change or agent reply', async () => {
  const f = fixture();
  f.setHistory({messages:[{id:1,k:'you',t:'My latest message'}]});
  f.setAgents([{id:'echo',name:'Echo',conversation_id:'one',status:'stopped'}]);
  await f.ready();
  assert.match(f.core.state().note, /no agent reply yet/);
  f.setAgents([{id:'echo',name:'Echo',conversation_id:'one',status:'idle'}]);
  await f.core.refresh();
  assert.doesNotMatch(f.core.state().note, /no agent reply yet/);
  assert.match(f.core.state().note, /Conversation checked/);
  f.setAgents([{id:'echo',name:'Echo',conversation_id:'one',status:'stopped'}]);
  f.setHistory({messages:[{id:1,k:'you',t:'My latest message'},{id:2,k:'ag',t:'Echo replied now'}]});
  await f.core.refresh();
  assert.doesNotMatch(f.core.state().note, /no agent reply yet/);
  assert.equal(f.core.state().messages.length,2);
});

test('stopped guidance does not replace uncertain receipt or maintenance guidance', async () => {
  let lose = true;
  const f = fixture({intercept:(route,options)=>{ if(options?.method==='POST'&&lose){lose=false;throw Error('acknowledgement lost');} }});
  await f.ready();
  f.core.setDraft('uncertain original');
  await f.core.send();
  const saved = f.storage.get(RECEIPT_KEY);
  assert.ok(saved);
  f.setAgents([{id:'echo',name:'Echo',conversation_id:'one',status:'stopped'}]);
  f.setHistory({messages:[{id:1,k:'you',t:'My latest message'}]});
  await f.core.refresh();
  assert.match(f.core.state().note, /Uncertain send/);
  assert.doesNotMatch(f.core.state().note, /no agent reply yet/);
  assert.equal(f.storage.get(RECEIPT_KEY), saved, 'uncertain receipt remains stored');
  assert.equal(f.core.state().draft,'uncertain original');
  assert.equal(f.calls.filter(c=>c.options?.method==='POST').length, 1, 'no automatic retry');
  const g = fixture();
  g.setHistory({messages:[{id:1,k:'you',t:'My latest message'}],meshDispatchState:'paused'});
  g.setAgents([{id:'echo',name:'Echo',conversation_id:'one',status:'stopped'}]);
  await g.ready();
  assert.match(g.core.state().note, /paused for Mesh maintenance/);
  assert.doesNotMatch(g.core.state().note, /no agent reply yet/);
  assert.equal(g.core.state().canSend, false);
  const h = fixture();
  h.setHistory({messages:[{id:1,k:'you',t:'My latest message'}],meshDispatchState:'unavailable'});
  h.setAgents([{id:'echo',name:'Echo',conversation_id:'one',status:'stopped'}]);
  await h.ready();
  assert.match(h.core.state().note, /could not check whether sending is available/);
  assert.doesNotMatch(h.core.state().note, /no agent reply yet/);
});

test('stopped guidance does not replace historical stale or catch-up guidance', async () => {
  const f = fixture();
  f.setHistory({messages:[{id:1,k:'you',t:'My latest message'}]});
  f.setAgents([{id:'echo',name:'Echo',conversation_id:'one',status:'stopped'}]);
  await f.ready();
  assert.match(f.core.state().note, /no agent reply yet/);
  f.setAgents([{id:'echo',name:'Echo',conversation_id:'rotated',status:'stopped'}]);
  await f.core.refresh();
  assert.match(f.core.state().note, /historical session/);
  assert.doesNotMatch(f.core.state().note, /no agent reply yet/);
  assert.equal(f.core.state().live,false);
  const rows = (first,last) => Array.from({length:last-first+1},(_,i)=>({id:first+i,k:'ag',t:'Message '+(first+i)}));
  let reconnect = false;
  const g = fixture({intercept:r=>{
    if(!r.includes('/messages?'))return;
    const after = new URL(r,'http://fixture').searchParams.get('after');
    if(after)return {messages:rows(31,40),oldest_id:31,newest_id:40,has_more:true};
    return reconnect?{messages:rows(51,60),oldest_id:51,newest_id:60,has_more:true}:{messages:rows(21,30),oldest_id:21,newest_id:30,has_more:true};
  }});
  g.setAgents([{id:'echo',name:'Echo',conversation_id:'one',status:'stopped'}]);
  await g.ready();
  g.core.setDraft('keep during catch-up');
  reconnect = true;
  await g.core.refresh();
  assert.match(g.core.state().note, /Catching up/);
  assert.doesNotMatch(g.core.state().note, /no agent reply yet/);
  assert.equal(g.core.state().draft,'keep during catch-up');
  assert.equal(g.calls.filter(c=>c.options?.method==='POST').length, 0);
});
