import test from 'node:test';
import assert from 'node:assert/strict';
import {createHash,randomUUID} from 'node:crypto';
import {createRelayConversation,RECEIPT_KEY} from '../public/relay-conversation.mjs';

const digest=async text=>createHash('sha256').update(text).digest('hex');
const settle=async(rounds=3)=>{for(let i=0;i<rounds;i++)await new Promise(resolve=>setImmediate(resolve));};

// Self-contained fixture for listSessions/selectSession behavior. No live services.
// Agents: echo -> current conversation 'one'; cyony -> current conversation 'cyony-current'.
// Session catalogue for echo lists 'one' (current) plus 'old' (historical).
// current ALWAYS means agents[].conversation_id, never the selected historical ID.
// Histories are distinct per (agentId,sessionId) so any cross-repaint is detectable.
function fixture({storage=new Map(),intercept,sessionReply}={}) {
  const calls=[],receipts=new Map();
  let agents=[
    {id:'echo',name:'Echo',conversation_id:'one',status:'idle'},
    {id:'cyony',name:'Cyony',conversation_id:'cyony-current',status:'idle'}
  ];
  let sessions=sessionReply===undefined
    ? [{id:'one',title:'Current echo chat',updated_at:'2026-11-01T10:00:00Z'},
       {id:'old',title:'Old echo chat',updated_at:'2026-10-02T09:00:00Z'}]
    : sessionReply;
  let offline=false;
  const histories=new Map([
    ['echo/one',{messages:[{id:1,k:'ag',t:'Echo current one'}]}],
    ['echo/old',{messages:[{id:2,k:'ag',t:'Echo old transcript'}]}],
    ['cyony/cyony-current',{messages:[{id:3,k:'ag',t:'Cyony current'}]}]
  ]);
  const request=async(route,options)=>{
    calls.push({route,options});
    if(offline)throw Error('offline');
    const intercepted=intercept?.(route,options);
    if(intercepted!==undefined)return intercepted;
    if(route==='/api/relay/native/api/agents')return structuredClone(agents);
    if(route==='/relay/api/mesh-capabilities')return {taskSessionBinding:1};
    if(route==='/relay/api/agents/echo/sessions')return {ok:true,sessions:structuredClone(sessions)};
    if(route==='/relay/api/agents/cyony/sessions')return {ok:true,sessions:[{id:'cyony-current',title:'Cyony current chat',updated_at:'2026-11-05T08:00:00Z'}]};
    const historyMatch=/^\/relay\/api\/agents\/([^/]+)\/sessions\/([^/]+)\/messages/.test(route);
    if(historyMatch){
      const aid=decodeURIComponent(route.split('/')[4]);
      const sid=decodeURIComponent(route.split('/')[6]);
      const page=histories.get(`${aid}/${sid}`);
      if(page===undefined)throw Error('Unknown history route '+route);
      return structuredClone(page);
    }
    if(options?.method==='POST'){
      const body=JSON.parse(options.body),aid=decodeURIComponent(route.split('/')[4]);
      assert.deepEqual(Object.keys(body).sort(),['expectedConversationId','id','text']);
      if(receipts.has(body.id)){
        assert.deepEqual(receipts.get(body.id),{aid,...body});
        return {ok:true,duplicate:true};
      }
      assert.equal(agents.find(a=>a.id===aid)?.conversation_id,body.expectedConversationId,'POST must target the displayed current conversation');
      receipts.set(body.id,{aid,...body});
      return {ok:true};
    }
    throw Error('Unexpected request '+route);
  };
  const store={getItem:k=>storage.get(k)??null,setItem:(k,v)=>storage.set(k,v),removeItem:k=>storage.delete(k)};
  const core=createRelayConversation({request,storage:store,digest,uuid:randomUUID});
  return {core,calls,receipts,storage,
    setAgents:value=>{agents=value;},
    setSessionRows:value=>{sessions=value;},
    setOffline:value=>{offline=value;},
    postCalls:()=>calls.filter(c=>c.options?.method==='POST').length,
    sessionListCalls:agent=>calls.filter(c=>c.route===`/relay/api/agents/${agent??'echo'}/sessions`).length,
    ready:async()=>{await core.setAvailable(true);await core.select('echo');}
  };
}

test('1. explicit list never auto-selects nor changes history, draft or POST; rows expose only id/title/updatedAt/current',async()=>{
  const f=fixture();await f.ready();
  f.core.setDraft('keep this draft');
  const before=f.sessionListCalls();
  assert.equal(before,0,'ready/refresh never fetch the session list implicitly');
  assert.deepEqual(f.core.state().sessions,[]);
  assert.equal(f.core.state().sessionsLoading,false);
  assert.equal(f.core.state().sessionsNote,'');
  const postsBefore=f.postCalls();
  await f.core.listSessions();
  assert.equal(f.sessionListCalls(),before+1);
  assert.equal(f.postCalls(),postsBefore,'listing sessions must not POST');
  assert.deepEqual(f.core.state().messages.map(m=>m.t),['Echo current one'],'listing must not change history');
  assert.equal(f.core.state().draft,'keep this draft','listing must not change the draft');
  assert.equal(f.core.state().destination.sessionId,'one','listing must not auto-select a session');
  const rows=f.core.state().sessions;
  assert.deepEqual(rows.map(r=>r.id),['one','old']);
  assert.deepEqual(rows.map(r=>Object.keys(r).sort()),rows.map(()=>['current','id','title','updatedAt']));
  assert.equal(rows.find(r=>r.id==='one').current,true,'current follows agents[].conversation_id');
  assert.equal(rows.find(r=>r.id==='old').current,false,'a historical session is never current');
  assert.equal(rows.find(r=>r.id==='one').title,'Current echo chat');
  assert.equal(rows.find(r=>r.id==='one').updatedAt,'2026-11-01T10:00:00Z');
  assert.equal(JSON.stringify(rows).includes('updated_at'),false,'no raw backend field leaks through');
  // Duplicates, invalid IDs and oversized titles are dropped or bounded.
  const longTitle='t'.repeat(400);
  f.setSessionRows([
    {id:'one',title:'Current echo chat',updated_at:'2026-11-01T10:00:00Z'},
    {id:'one',title:'Duplicate should vanish',updated_at:'x'},
    {id:'',title:'Blank id',updated_at:'x'},
    {title:'Missing id',updated_at:'x'},
    {id:null,title:'Null id',updated_at:'x'},
    {id:'x'.repeat(300),title:'Id too long',updated_at:'x'},
    {id:'long',title:longTitle,updated_at:'2026-09-09'}
  ]);
  await f.core.listSessions();
  const kept=f.core.state().sessions;
  assert.deepEqual(kept.map(r=>r.id),['one','long']);
  assert.ok(kept[1].title.length<=160,'long titles are bounded');
  assert.ok(longTitle.startsWith(kept[1].title),'the bounded title stays a prefix of the original');
  assert.equal(kept[0].title,'Current echo chat','the surviving duplicate keeps its first row');
  assert.equal(kept[0].current,true);
  assert.equal(kept[1].current,false);
  assert.equal(f.core.state().destination.sessionId,'one');
  assert.equal(f.core.state().draft,'keep this draft');
  assert.equal(f.postCalls(),postsBefore);
  assert.equal(f.receipts.size,0);
  assert.equal(f.storage.size,0);
});

test('2. selected old transcript stays selected through refresh, blocks fresh sends; select(echo) restores its draft; drafts are per session',async()=>{
  const f=fixture();await f.ready();
  await f.core.listSessions();
  f.core.setDraft('echo current draft');
  await f.core.selectSession('old');
  assert.equal(f.core.state().destination.sessionId,'old');
  assert.deepEqual(f.core.state().messages.map(m=>m.t),['Echo old transcript']);
  assert.equal(f.core.state().live,false);
  assert.equal(f.core.state().canSend,false,'a historical session must not accept a fresh send');
  assert.equal(f.core.state().draft,'','the old session has its own separate draft');
  const selectedRow=f.core.state().sessions.find(r=>r.id==='old');
  assert.equal(selectedRow.current,false,'selected is not current: current means agents[].conversation_id');
  assert.equal(f.core.state().sessions.find(r=>r.id==='one').current,true);
  f.core.setDraft('old session draft');
  await f.core.refresh();
  assert.equal(f.core.state().destination.sessionId,'old','refresh stays on the explicitly selected old session');
  assert.deepEqual(f.core.state().messages.map(m=>m.t),['Echo old transcript']);
  assert.equal(f.core.state().draft,'old session draft');
  assert.equal(f.core.state().sessions.find(r=>r.id==='old').current,false,'refresh must not relabel the selected old session as current');
  assert.equal(f.core.state().sessions.find(r=>r.id==='one').current,true);
  assert.equal(f.sessionListCalls(),1,'refresh must not re-list sessions');
  await f.core.send();
  assert.equal(f.postCalls(),0,'no dispatch while a historical session is displayed');
  assert.equal(f.receipts.size,0);
  assert.equal(f.storage.size,0);
  // Returning to the current conversation via explicit agent selection restores its draft.
  await f.core.select('echo');
  assert.equal(f.core.state().destination.sessionId,'one');
  assert.equal(f.core.state().draft,'echo current draft','the current session draft survives old-session browsing');
  assert.equal(f.core.state().live,true);
  assert.deepEqual(f.core.state().messages.map(m=>m.t),['Echo current one']);
  assert.equal(f.postCalls(),0);
  assert.equal(f.receipts.size,0);
  assert.equal(f.storage.size,0);
});

test('3. unknown or foreign-agent session IDs cannot redirect; agent switch clears the list; invalid selection keeps the same selection',async()=>{
  const f=fixture();await f.ready();await f.core.listSessions();
  const before=f.calls.length;
  await f.core.selectSession('ghost');
  assert.equal(f.core.state().destination.agentId,'echo');
  assert.equal(f.core.state().destination.sessionId,'one');
  assert.equal(f.core.state().live,true);
  await f.core.selectSession('cyony-current');
  assert.equal(f.core.state().destination.agentId,'echo','a foreign agent session cannot redirect the destination');
  assert.equal(f.core.state().destination.sessionId,'one');
  assert.deepEqual(f.core.state().messages.map(m=>m.t),['Echo current one']);
  assert.equal(f.core.state().sessions.length,2,'the invalid selection left the catalogue untouched');
  assert.equal(f.sessionListCalls(),1);
  assert.equal(f.calls.slice(before).some(c=>c.options?.method==='POST'),false);
  await f.core.send();
  assert.equal(f.postCalls(),0);
  assert.equal(f.receipts.size,0);
  // Conversation rotation: neither listed row is current anymore; the stale row stays selectable.
  f.setAgents([{id:'echo',name:'Echo',conversation_id:'rotated',status:'idle'},{id:'cyony',name:'Cyony',conversation_id:'cyony-current',status:'idle'}]);
  await f.core.refresh();
  assert.deepEqual(f.core.state().sessions.map(row=>row.id),['one','old']);
  assert.ok(f.core.state().sessions.every(row=>row.current===false),'rotation makes both rows non-current');
  await f.core.selectSession('old');
  assert.equal(f.core.state().destination.sessionId,'old');
  assert.deepEqual(f.core.state().messages.map(m=>m.t),['Echo old transcript']);
  assert.equal(f.core.state().canSend,false);
  // Switching agents clears the old list; the invalid cross-agent selection never changed anything.
  await f.core.select('cyony');
  assert.deepEqual(f.core.state().sessions,[],'changing agents clears the previous agent list');
  assert.equal(f.core.state().destination.sessionId,'cyony-current');
  assert.equal(f.calls.some(c=>c.route==='/relay/api/agents/cyony/sessions'),false,'no Cyony list was ever fetched');
  assert.equal(f.receipts.size,0);
  assert.equal(f.storage.size,0);
});

test('4. concurrent listSessions coalesce into one GET',async()=>{
  let release;
  let hold=true;
  const g=fixture({intercept:route=>{
    if(route==='/relay/api/agents/echo/sessions'&&hold){hold=false;return new Promise(resolve=>{release=resolve;});}
  }});
  await g.ready();
  const first=g.core.listSessions();
  await settle(1);
  const second=g.core.listSessions();
  await settle(1);
  assert.equal(g.sessionListCalls(),1,'concurrent lists share one GET');
  assert.equal(g.core.state().sessionsLoading,true);
  release({ok:true,sessions:[{id:'one',title:'Current echo chat',updated_at:'2026-11-01T10:00:00Z'},{id:'old',title:'Old echo chat',updated_at:'2026-10-02T09:00:00Z'}]});
  await Promise.all([first,second]);
  assert.equal(g.sessionListCalls(),1);
  assert.deepEqual(g.core.state().sessions.map(row=>row.id),['one','old']);
  assert.equal(g.core.state().sessionsLoading,false);
  assert.equal(g.postCalls(),0);
  assert.equal(g.receipts.size,0);
});

test('5. a late Echo list cannot repopulate old metadata or clear the newer Cyony loading state',async()=>{
  let releaseEcho,releaseCyony;
  let echoLists=0,cyonyLists=0;
  const g=fixture({intercept:route=>{
    if(route==='/relay/api/agents/echo/sessions'){echoLists++;if(echoLists===1)return new Promise(resolve=>{releaseEcho=resolve;});}
    if(route==='/relay/api/agents/cyony/sessions'){cyonyLists++;if(cyonyLists===1)return new Promise(resolve=>{releaseCyony=resolve;});}
  }});
  await g.ready();
  const staleList=g.core.listSessions();
  await settle(1);
  assert.equal(g.core.state().sessionsLoading,true);
  await g.core.select('cyony');
  assert.deepEqual(g.core.state().sessions,[],'switching agents clears the previous agent session list');
  assert.equal(g.core.state().sessionsNote,'');
  const cyonyList=g.core.listSessions();
  await settle(1);
  assert.equal(g.core.state().sessionsLoading,true,'the newer Cyony load is in flight');
  releaseEcho({ok:true,sessions:[{id:'one',title:'Stale echo chat',updated_at:'2026-11-01T10:00:00Z'},{id:'old',title:'Old echo chat'}]});
  await staleList;
  await settle(1);
  assert.deepEqual(g.core.state().sessions,[],'the late Echo list must not repopulate old agent metadata');
  assert.equal(g.core.state().sessionsLoading,true,'the late Echo list must not clear the newer Cyony loading state');
  assert.equal(g.core.state().destination.agentId,'cyony');
  releaseCyony({ok:true,sessions:[{id:'cyony-current',title:'Cyony current chat',updated_at:'2026-11-05T08:00:00Z'}]});
  await cyonyList;
  assert.deepEqual(g.core.state().sessions.map(row=>row.id),['cyony-current']);
  assert.equal(g.core.state().sessions[0].current,true);
  assert.equal(g.core.state().sessionsLoading,false);
  assert.equal(g.core.state().sessionsNote,'');
  assert.equal(g.core.state().destination.agentId,'cyony');
  assert.equal(g.postCalls(),0);
  assert.equal(g.receipts.size,0);
  assert.equal(g.storage.size,0);
});

test('6. privacy lock and reconnect discard list, titles, loading state and in-flight reads without auto-post or auto-select',async()=>{
  let releaseSessions,releaseHistory;
  let hold=false;
  const g=fixture({intercept:route=>{
    if(!hold)return undefined;
    if(route==='/relay/api/agents/echo/sessions')return new Promise(resolve=>{releaseSessions=resolve;});
    if(/^\/relay\/api\/agents\/echo\/sessions\/one\/messages/.test(route))return new Promise(resolve=>{releaseHistory=resolve;});
  }});
  await g.ready();
  hold=true;
  g.core.setDraft('private draft');
  const listPromise=g.core.listSessions();
  const readPromise=g.core.refresh();
  await settle(1);
  assert.equal(g.core.state().sessionsLoading,true);
  await g.core.setAvailable(false);
  assert.deepEqual(g.core.state().sessions,[],'lock discards session rows and titles');
  assert.equal(g.core.state().sessionsLoading,false,'lock discards the loading state');
  assert.equal(g.core.state().sessionsNote,'');
  assert.deepEqual(g.core.state().messages,[]);
  assert.equal(g.core.state().draft,'');
  releaseSessions({ok:true,sessions:[{id:'one',title:'Late private title',updated_at:'x'}]});
  releaseHistory({messages:[{id:99,k:'ag',t:'Late private transcript'}]});
  await Promise.all([listPromise,readPromise]);
  await settle(1);
  assert.equal(g.core.state().destination,null,'after the lock there is no destination and nothing is auto-selected');
  assert.deepEqual(g.core.state().sessions,[],'a late list cannot repopulate after the lock');
  assert.equal(g.core.state().sessionsLoading,false);
  assert.deepEqual(g.core.state().messages,[]);
  assert.equal(g.core.state().draft,'');
  assert.equal(g.postCalls(),0,'no automatic post across lock and reconnect');
  assert.equal(g.receipts.size,0);
  assert.equal(g.storage.size,0);
  await g.core.setAvailable(true);
  assert.deepEqual(g.core.state().sessions,[],'reconnect starts with a clean session catalogue');
  assert.equal(g.core.state().sessionsLoading,false);
  assert.equal(g.core.state().destination,null,'reconnect has no destination');
  assert.equal(g.postCalls(),0);
});

test('7. malformed and offline list responses preserve transcript and draft and yield a generic sessionsNote',async()=>{
  for(const bad of [{ok:true,sessions:'not an array'},{sessions:[{id:'one'}]},{ok:false,sessions:[]}]){
    const f=fixture({sessionReply:bad});
    await f.ready();
    f.core.setDraft('keep this draft');
    await f.core.listSessions();
    assert.deepEqual(f.core.state().sessions,[]);
    assert.equal(f.core.state().sessionsLoading,false);
    assert.ok(f.core.state().sessionsNote,'a generic sessionsNote is surfaced');
    assert.ok(!f.core.state().sessionsNote.includes('private'),'no raw private error detail leaks');
    assert.deepEqual(f.core.state().messages.map(m=>m.t),['Echo current one'],'the current transcript survives a malformed list');
    assert.equal(f.core.state().draft,'keep this draft');
    assert.equal(f.core.state().destination.sessionId,'one');
    assert.equal(f.core.state().live,true);
    // A failed list must not leave a stale catalogue behind.
    const before=f.calls.length;
    await f.core.selectSession('old');
    assert.equal(f.core.state().destination.sessionId,'one','no navigation from a catalogue that failed to load');
    assert.equal(f.calls.length,before,'an invalid selection must not request anything');
    assert.equal(f.postCalls(),0,'listing and selection alone never send');
    assert.equal(f.receipts.size,0);
    assert.equal(f.storage.size,0);
  }
  const f=fixture();
  await f.ready();
  f.core.setDraft('offline draft');
  f.setOffline(true);
  await f.core.listSessions();
  assert.deepEqual(f.core.state().sessions,[]);
  assert.equal(f.core.state().sessionsLoading,false);
  assert.ok(f.core.state().sessionsNote);
  assert.ok(!/offline|Error|Unexpected request/.test(f.core.state().sessionsNote),'the note never echoes the raw transport error');
  assert.deepEqual(f.core.state().messages.map(m=>m.t),['Echo current one']);
  assert.equal(f.core.state().draft,'offline draft');
  f.setOffline(false);
  await f.core.listSessions();
  assert.deepEqual(f.core.state().sessions.map(row=>row.id),['one','old']);
  assert.equal(f.core.state().sessionsNote,'');
  assert.equal(f.core.state().draft,'offline draft');
  assert.equal(f.postCalls(),0);
  assert.equal(f.receipts.size,0);
  assert.equal(f.storage.size,0);
});

test('8. uncertain original receipt stays byte-identical while browsing; exact-original retry reuses the same ID and then clears',async()=>{
  let lose=true;
  const f=fixture({intercept:(route,options)=>{if(options?.method==='POST'&&lose){lose=false;return Promise.reject(Error('response lost'));}}});
  await f.ready();
  f.core.setDraft('exact original words');
  await f.core.send();
  const saved=f.storage.get(RECEIPT_KEY);
  assert.ok(saved,'the uncertain receipt was persisted');
  const receipt=JSON.parse(saved);
  assert.equal('text' in receipt,false,'retry storage retains metadata only, never message text');
  assert.equal(receipt.sessionId,'one');
  assert.equal(f.receipts.size,0,'the failed POST was never accepted, so no receipt exists server-side yet');
  assert.equal(f.postCalls(),1);
  await f.core.listSessions();
  await f.core.selectSession('old');
  assert.equal(f.storage.get(RECEIPT_KEY),saved,'browsing an old session leaves the receipt byte-identical');
  assert.equal(f.core.state().pending.id,receipt.id);
  f.core.setDraft('browsing thoughts');
  await f.core.send();
  assert.equal(f.postCalls(),1,'no fresh send or receipt while the old session is displayed');
  assert.equal(f.storage.get(RECEIPT_KEY),saved);
  assert.equal(f.receipts.size,0);
  await f.core.select('echo');
  assert.equal(f.storage.get(RECEIPT_KEY),saved,'returning to the current session leaves the receipt byte-identical');
  assert.equal(f.core.state().draft,'exact original words','the restored draft is the exact original, not the browsing draft');
  assert.equal(f.core.state().pending.id,receipt.id);
  await f.core.send();
  assert.equal(f.postCalls(),2,'the exact original retries once with the same receipt identity');
  const posts=f.calls.filter(c=>c.options?.method==='POST').map(c=>JSON.parse(c.options.body));
  assert.equal(posts.length,2);
  assert.ok(posts.every(p=>p.id===receipt.id&&p.text==='exact original words'&&p.expectedConversationId==='one'),'every retry reuses the exact original identity');
  assert.equal(f.storage.size,0,'the accepted retry clears exactly the original receipt');
  assert.equal(f.receipts.size,1);
});

test('9. session lists and ordinary history reads finish independently in either order',async()=>{
  for(const listFirst of [true,false]){
    let hold=false,releaseList,releaseHistory;
    const g=fixture({intercept:route=>{
      if(!hold)return;
      if(route==='/relay/api/agents/echo/sessions')return new Promise(resolve=>{releaseList=resolve;});
      if(route.includes('/messages?'))return new Promise(resolve=>{releaseHistory=resolve;});
    }});
    await g.ready();hold=true;
    let listing,reading;
    if(listFirst){listing=g.core.listSessions();await settle(1);reading=g.core.refresh();}
    else{reading=g.core.refresh();await settle(1);listing=g.core.listSessions();}
    await settle();
    assert.equal(typeof releaseList,'function','a history read does not block listing');
    assert.equal(typeof releaseHistory,'function','a list does not suppress history');
    assert.equal(g.core.state().sessionsLoading,true);
    if(listFirst){
      releaseHistory({messages:[{id:9,k:'ag',t:'Refreshed current history'}]});await reading;
      assert.equal(g.core.state().sessionsLoading,true,'history completion leaves pending list loading');
      releaseList({ok:true,sessions:[{id:'one',title:'Current'},{id:'old',title:'Historical'}]});await listing;
    }else{
      releaseList({ok:true,sessions:[{id:'one',title:'Current'},{id:'old',title:'Historical'}]});await listing;
      assert.equal(g.core.state().sessionsLoading,false,'list can finish before history');
      releaseHistory({messages:[{id:9,k:'ag',t:'Refreshed current history'}]});await reading;
    }
    assert.equal(g.core.state().sessionsLoading,false);
    assert.deepEqual(g.core.state().sessions.map(row=>row.id),['one','old']);
    assert.deepEqual(g.core.state().messages.map(m=>m.t),['Refreshed current history']);
    assert.equal(g.sessionListCalls(),1);
    assert.equal(g.postCalls(),0);assert.equal(g.storage.size,0);
  }
});

test('10. mutating returned state.sessions cannot forge a selectable ID',async()=>{
  const f=fixture();await f.ready();
  await f.core.listSessions();
  const rows=f.core.state().sessions;
  assert.ok(rows.length>0);
  rows[0].id='forged';
  rows[1].id='cyony-current';
  assert.equal(rows[0].id,'forged','the client mutated its own copy');
  assert.equal(f.core.state().sessions.some(r=>r.id==='forged'),false,'internal catalogue is unchanged');
  const before=f.calls.length;
  await f.core.selectSession('forged');
  await f.core.selectSession('cyony-current');
  assert.equal(f.core.state().destination.sessionId,'one','a forged ID cannot redirect the destination');
  assert.equal(f.core.state().destination.agentId,'echo');
  assert.deepEqual(f.core.state().messages.map(m=>m.t),['Echo current one']);
  assert.equal(f.core.state().live,true);
  assert.equal(f.calls.length,before,'a forged selection requests nothing');
  await f.core.send();
  assert.equal(f.postCalls(),0);
  assert.equal(f.receipts.size,0);
  assert.equal(f.storage.size,0);
});