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
    if(route==='/relay/api/agents')return structuredClone(agents);
    if(route==='/relay/api/mesh-capabilities')return {taskSessionBinding:1};
    if(route.endsWith('/messages'))return structuredClone(history);
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
  assert.equal(f.calls.some(c=>c.route.endsWith('/messages')),false);
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
  for(const intercept of [(r)=>r.endsWith('mesh-capabilities')?{}:undefined,(r)=>r==='/relay/api/agents'&&swap?[]:undefined]){
    var swap=false;const f=fixture({intercept});await f.ready();swap=true;f.core.setDraft('blocked');await f.core.send();assert.equal(f.receipts.size,0);
  }
  const f=fixture();await f.ready();f.storage.set=()=>{throw Error('storage full');};f.core.setDraft('not sent');await f.core.send();assert.equal(f.receipts.size,0);
});
test('Privacy clearance drops late history/acknowledgments and all draft/history content without replay',async()=>{
  let release,hold=false;const f=fixture({intercept:r=>hold&&r.endsWith('/messages')?new Promise(resolve=>release=resolve):undefined});
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
    if(r==='/relay/api/agents')return new Promise(resolve=>releaseList=resolve);
    if(r.endsWith('/messages'))return new Promise(resolve=>releaseHistory=resolve);
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
  const f=fixture({intercept:r=>hold&&r.includes('/echo/')&&r.endsWith('/messages')?new Promise(resolve=>release=resolve):undefined});
  await f.ready();hold=true;const old=f.core.refresh();await new Promise(resolve=>setImmediate(resolve));
  await f.core.select('deep');assert.equal(f.core.state().destination.agentId,'deep');
  assert.equal(f.core.state().messages[0].t,'Original history');
  release({messages:[{id:9,t:'Late Echo history'}]});await old;
  assert.equal(f.core.state().destination.agentId,'deep');assert.equal(f.core.state().messages[0].t,'Original history');
});

test('A locked and reconnected Relay does not wait for or accept the previous admission read',async()=>{
  let hold=false,release;
  const f=fixture({intercept:r=>hold&&r.endsWith('/messages')?new Promise(resolve=>release=resolve):undefined});
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
