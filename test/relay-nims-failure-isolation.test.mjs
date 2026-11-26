// Failure isolation between the ordinary Relay conversation (Echo) and the optional
// native Nims desktop chat. A native Nims outage must leave Echo's destination,
// history and draft intact, and a Relay outage must leave an already-open Nims chat's
// client state intact. Both real clients share one mock request router and one
// in-memory storage object; nothing here touches agents, servers or the network.
import test from 'node:test';
import assert from 'node:assert/strict';
import {createRelayConversation,RECEIPT_KEY} from '../public/relay-conversation.mjs';
import {createNimsChatState} from '../public/nims-chat-state.mjs';
import {NIMS_RECEIPTS} from '../public/nims-send-state.mjs';

const ECHO='echo',ECHO_SESSION='one',DEEP_SESSION='two';
const NIMS_PROJECT='33333333-3333-4333-8333-333333333333';
const NIMS_CHAT='11111111-1111-4111-8111-111111111111';
const NATIVE_UNAVAILABLE=/Synthetic native Nims desktop connection is unavailable/;
const RELAY_OUTAGE='Synthetic Relay outage.';
const NATIVE_ROUTES=['/api/relay/codex/status','/api/relay/codex/catalog','/api/relay/codex/history'];
const isNative=route=>route.startsWith('/api/relay/codex/');
const isNativePost=route=>isNative(route)&&!NATIVE_ROUTES.some(native=>route===native);

function sharedFixture({relayRoutes=['/api/relay/native/api/agents']}={}){
  const requests=[],relayPosts=[],nativeDispatches=[];
  let nativeHistory=[{id:'native-old',role:'assistant',text:'Existing native answer'}];
  let relayHistory={messages:[{id:1,k:'ag',t:'Original Relay history'}]};
  const memory=new Map();
  const storage={getItem:k=>memory.get(k)??null,setItem:(k,v)=>memory.set(k,v),removeItem:k=>memory.delete(k)};
  let nativeDown=false,relayDown=false;
  const request=async(route,options)=>{
    requests.push({route,body:options?.body&&JSON.parse(options.body)});
    if(isNative(route)){
      if(nativeDown&&NATIVE_ROUTES.includes(route))throw Error(NATIVE_UNAVAILABLE);
      if(route.endsWith('/status'))return {configured:true,readOnly:false};
      if(route.endsWith('/catalog'))return {project:{id:NIMS_PROJECT,label:'Native project'},conversations:[{id:NIMS_CHAT,title:'Current chat',status:'idle'}],nextCursor:null};
      if(route.endsWith('/history'))return {conversation:{id:NIMS_CHAT,title:'Current chat',status:'idle'},groups:[{id:'turn',messages:nativeHistory,olderItemCursor:null}],olderTurnCursor:null};
      // Any other /api/relay/codex/ route — including an unexpected /send or /new — is recorded as an
      // accidental native dispatch and explicitly rejected, so a hidden send can never masquerade as an
      // unknown nonnative request. All traffic stays mocked; nothing reaches the network.
      nativeDispatches.push({route,body:options?.body?JSON.parse(options.body):null});
      throw Error('Unexpected native dispatch '+route);
    }
    if(relayDown&&relayRoutes.includes(route))throw Error(RELAY_OUTAGE);
    if(route==='/api/relay/native/api/agents')return [{id:ECHO,name:'Echo',conversation_id:ECHO_SESSION,status:'idle'}];
    if(route==='/relay/api/mesh-capabilities')return {taskSessionBinding:1};
    if(route.split('?')[0].endsWith('/messages'))return structuredClone(relayHistory);
    if(options?.method==='POST'&&route.startsWith('/relay/api/agents/')){
      const body=JSON.parse(options.body),agentId=route.split('/')[4];
      assert.deepEqual(Object.keys(body).sort(),['expectedConversationId','id','text']);
      assert.equal(route.includes(`/${agentId}/message`),true);
      assert.equal(body.expectedConversationId,agentId===ECHO?ECHO_SESSION:DEEP_SESSION);
      relayPosts.push({route,agentId,body});
      return {ok:true};
    }
    throw Error('Unexpected request '+route);
  };
  const echo=createRelayConversation({request,storage,digest:async value=>String(value),uuid:()=>'55555555-5555-4555-8555-555555555555'});
  const nims=createNimsChatState({request,storage,makeId:()=>'44444444-4444-4444-8444-444444444444',hash:async value=>String(value)});
  return {echo,nims,requests,relayPosts,nativeDispatches,memory,storage,
    setNativeHistory:value=>{nativeHistory=value;},
    setNativeDown:value=>{nativeDown=value;},
    setRelayDown:value=>{relayDown=value;},
    ready:async()=>{await echo.setAvailable(true);await echo.select(ECHO);nims.setAvailable(true);await nims.catalog();await nims.select(NIMS_CHAT);}};
}

test('Scenario A: a native Nims outage leaves the selected Echo chat intact and Echo send still dispatches once',async()=>{
  const f=sharedFixture();
  await f.ready();
  f.echo.setDraft('Finish this after the outage');
  assert.equal(f.echo.state().destination.agentId,ECHO);
  assert.equal(f.echo.state().destination.sessionId,ECHO_SESSION);
  assert.deepEqual(f.echo.state().messages.map(m=>m.t),['Original Relay history']);
  assert.equal(f.echo.state().draft,'Finish this after the outage');

  const before=f.requests.filter(r=>isNative(r.route)).length;
  f.setNativeDown(true);
  await f.nims.catalog();
  await f.nims.refresh();
  await f.echo.refresh();
  assert.equal(f.requests.filter(r=>isNative(r.route)).length,before+2,'the deliberate Nims catalog retry and history refresh reached the router and failed');
  assert.match(f.nims.state().note,NATIVE_UNAVAILABLE,'the note carries the fixture-controlled native unavailability');

  // Echo keeps its destination, history and unsent draft; nothing dispatched on its own.
  assert.equal(f.echo.state().destination.agentId,ECHO);
  assert.equal(f.echo.state().destination.sessionId,ECHO_SESSION);
  assert.deepEqual(f.echo.state().messages.map(m=>m.t),['Original Relay history']);
  assert.equal(f.echo.state().draft,'Finish this after the outage');
  assert.equal(f.echo.state().live,true,'Echo history survived the native outage');
  assert.equal(f.echo.state().canSend,true);
  assert.equal(f.relayPosts.length,0);
  assert.equal(f.nativeDispatches.length,0);
  assert.equal(f.memory.has(RECEIPT_KEY),false);
  assert.equal(f.memory.has(NIMS_RECEIPTS),false,'neither client persisted a pending receipt during the outage');

  // A deliberate Echo send still dispatches exactly once to the displayed Echo conversation,
  // while the native Nims outage is still in force (restored only after the send is verified).
  await f.echo.send();
  f.setNativeDown(false);
  assert.equal(f.relayPosts.length,1);
  assert.equal(f.relayPosts[0].route,`/relay/api/agents/${ECHO}/message`);
  assert.equal(f.relayPosts[0].agentId,ECHO);
  assert.deepEqual(f.relayPosts[0].body,{id:'55555555-5555-4555-8555-555555555555',text:'Finish this after the outage',expectedConversationId:ECHO_SESSION});
  assert.equal(f.echo.state().draft,'','an accepted send consumes the Echo draft');
  assert.equal(f.echo.state().live,true,'the Echo conversation is still live after the send');
  assert.equal(f.memory.has(RECEIPT_KEY),false,'an accepted send clears its retry receipt');
  assert.equal(f.nativeDispatches.length,0,'the native Nims failure never triggered a native send');
});

test('Scenario B: a Relay outage leaves an open Nims chat intact, its own refresh works, and nothing switches or submits',async()=>{
  const f=sharedFixture();
  await f.ready();
  f.nims.setDraft('Reply in the native chat later');
  assert.deepEqual(f.nims.state().project,{id:NIMS_PROJECT,label:'Native project'});
  assert.equal(f.nims.state().selected.id,NIMS_CHAT);
  assert.deepEqual(f.nims.state().messages.map(m=>m.text),['Existing native answer']);
  assert.equal(f.nims.state().draft,'Reply in the native chat later');

  const before=f.requests.filter(r=>!isNative(r.route)).length;
  f.setRelayDown(true);
  await f.echo.refresh();
  await f.nims.refresh();
  assert.equal(f.requests.filter(r=>!isNative(r.route)).length,before+1,'the deliberate Relay refresh reached the router and failed');
  assert.match(f.echo.state().note,/stale/);
  assert.equal(f.requests.some(r=>isNativePost(r.route)),false,'no native send/create request was submitted');

  // Nims keeps its project, selection, native history and unsent draft.
  assert.deepEqual(f.nims.state().project,{id:NIMS_PROJECT,label:'Native project'});
  assert.equal(f.nims.state().selected.id,NIMS_CHAT);
  assert.deepEqual(f.nims.state().messages.map(m=>m.text),['Existing native answer']);
  assert.equal(f.nims.state().draft,'Reply in the native chat later');
  assert.equal(f.nims.state().readOnly,false);

  // Nims' own read/refresh still works during the Relay outage and paints native content.
  f.setNativeHistory([{id:'native-old',role:'assistant',text:'Existing native answer'},{id:'native-new',role:'assistant',text:'New native reply'}]);
  await f.nims.refresh();
  assert.deepEqual(f.nims.state().messages.map(m=>m.text),['Existing native answer','New native reply']);
  assert.equal(f.nims.state().draft,'Reply in the native chat later');
  assert.equal(f.nims.state().canSend,true,'the open native chat stays sendable through a Relay outage');

  // Neither client silently switched destinations: Echo stays on its explicit
  // conversation and Nims stays on the native chat that was already open.
  // NO native send was submitted in this scenario — the recorded dispatch list must stay empty,
  // and the router rejects (never fulfils) any /api/relay/codex/ write that reaches it.
  assert.equal(f.echo.state().destination.agentId,ECHO);
  assert.equal(f.echo.state().destination.sessionId,ECHO_SESSION);
  assert.equal(f.echo.state().draft,'');
  assert.equal(f.nims.state().selected.id,NIMS_CHAT);
  assert.equal(f.nims.state().readOnly,false,'the Relay outage never demoted the open native chat to read-only');
  assert.equal(f.nativeDispatches.length,0,'zero native sends or creates were submitted during the Relay outage');
  assert.equal(f.relayPosts.length,0,'the Relay outage triggered no automatic Echo send');
  assert.equal(f.memory.has(NIMS_RECEIPTS),false,'no native receipt was persisted, so no automatic resend is primed');
  assert.equal(f.nims.state().draft,'Reply in the native chat later','the unsent native draft survived the Relay outage');
});

test('Scenario C: after a combined outage, explicit refresh recovery restores both clients without switching, sending or persisting receipts',async()=>{
  const f=sharedFixture();
  await f.ready();
  f.echo.setDraft('Echo draft survives the joint outage');
  f.nims.setDraft('Native draft survives the joint outage');

  // Both transports fail at once; every explicit refresh during the outage fails.
  f.setNativeDown(true);
  f.setRelayDown(true);
  await f.nims.catalog();
  await f.nims.refresh();
  await f.echo.refresh();

  // The failed reads destroyed nothing: each client keeps its own destination,
  // history and unsent draft, and neither dispatched nor persisted a receipt.
  assert.equal(f.echo.state().destination.agentId,ECHO);
  assert.equal(f.echo.state().destination.sessionId,ECHO_SESSION);
  assert.deepEqual(f.echo.state().messages.map(m=>m.t),['Original Relay history']);
  assert.equal(f.echo.state().draft,'Echo draft survives the joint outage');
  assert.deepEqual(f.nims.state().project,{id:NIMS_PROJECT,label:'Native project'});
  assert.equal(f.nims.state().selected.id,NIMS_CHAT);
  assert.deepEqual(f.nims.state().messages.map(m=>m.text),['Existing native answer']);
  assert.equal(f.nims.state().draft,'Native draft survives the joint outage');
  assert.equal(f.relayPosts.length,0,'the outage triggered no automatic Relay send');
  assert.equal(f.nativeDispatches.length,0,'the outage triggered no automatic native send or create');
  assert.equal(f.memory.has(RECEIPT_KEY),false,'no Relay retry receipt was persisted during the outage');
  assert.equal(f.memory.has(NIMS_RECEIPTS),false,'no native retry receipt was persisted during the outage');

  // Outage cleared; only explicit refreshes bring each client back.
  f.setNativeDown(false);
  f.setRelayDown(false);
  await f.echo.refresh();
  await f.nims.catalog();
  await f.nims.refresh();

  // Both clients re-resolve their own previously selected destinations and histories.
  assert.equal(f.echo.state().destination.agentId,ECHO);
  assert.equal(f.echo.state().destination.sessionId,ECHO_SESSION);
  assert.deepEqual(f.echo.state().messages.map(m=>m.t),['Original Relay history'],'Echo restored its original history');
  assert.deepEqual(f.nims.state().project,{id:NIMS_PROJECT,label:'Native project'});
  assert.equal(f.nims.state().selected.id,NIMS_CHAT,'Nims restored its previously selected chat');
  assert.deepEqual(f.nims.state().messages.map(m=>m.text),['Existing native answer'],'Nims restored its original native history');

  // The distinct unsent drafts are intact and both clients are sendable again.
  assert.equal(f.echo.state().draft,'Echo draft survives the joint outage');
  assert.equal(f.nims.state().draft,'Native draft survives the joint outage');
  assert.equal(f.echo.state().live,true);
  assert.equal(f.echo.state().canSend,true,'Echo is sendable again after explicit recovery');
  assert.equal(f.nims.state().canSend,true,'Nims is sendable again after explicit recovery');

  // Recovery never auto-submitted a send/create nor primed a retry receipt.
  assert.equal(f.relayPosts.length,0,'recovery submitted no Relay send on its own');
  assert.equal(f.nativeDispatches.length,0,'recovery submitted no native send or create on its own');
  assert.equal(f.memory.has(RECEIPT_KEY),false,'no Relay retry receipt lingers after recovery');
  assert.equal(f.memory.has(NIMS_RECEIPTS),false,'no native retry receipt lingers after recovery');
});
