import test from 'node:test';import assert from 'node:assert/strict';
import {createAdmissionPeers} from '../public/session-entry.mjs';
function hub(){const channels=[];return class Channel{constructor(){channels.push(this);}postMessage(data){for(const channel of channels)if(channel!==this)queueMicrotask(()=>channel.onmessage?.({data}));}close(){this.onmessage=null;}};}
test('explicit peer request transfers only current proof; no transcript, identity or grant fields',async()=>{
 const Channel=hub();const proof={csrfToken:'a'.repeat(43),expiresAt:Date.now()+60000};
 const active=createAdmissionPeers({Channel,readProof:()=>proof});const fresh=createAdmissionPeers({Channel,readProof:()=>null});
 try{assert.deepEqual(await fresh.request(),proof);}finally{active.close();fresh.close();}
});
test('locked/expired/oversized proof never answers and close settles pending requests',async()=>{
 const Channel=hub();let proof=null;const active=createAdmissionPeers({Channel,readProof:()=>proof});const fresh=createAdmissionPeers({Channel,timeoutMs:10});
 try{
  assert.equal(await fresh.request(),null);
  proof={csrfToken:'a'.repeat(43),expiresAt:Date.now()-1};assert.equal(await fresh.request(),null);
  proof={csrfToken:'a'.repeat(43),expiresAt:Date.now()+60000,tasks:['private']};assert.equal(await fresh.request(),null);
  const waiting=fresh.request();fresh.close();assert.equal(await waiting,null);assert.equal(await fresh.request(),null);
 }finally{active.close();fresh.close();}
});
test('unsolicited, malformed and mismatched candidate responses cannot resolve a request',async()=>{
 const Channel=hub();const rogue=new Channel();rogue.onmessage=({data})=>{for(const message of [{type:'candidate',requestId:crypto.randomUUID(),proof:{csrfToken:'a'.repeat(43),expiresAt:Date.now()+60000}},{type:'candidate',requestId:data.requestId,proof:{csrfToken:'bad',expiresAt:Date.now()+60000}},{type:'candidate',requestId:data.requestId,proof:{csrfToken:'a'.repeat(43),expiresAt:Date.now()+60000},grant:'all'}])rogue.postMessage(message);};
 const fresh=createAdmissionPeers({Channel,timeoutMs:10});try{assert.equal(await fresh.request(),null);}finally{rogue.close();fresh.close();}
});

import {mockUI,flush} from './app-ui-fixture.mjs';
for(const accepted of [true,false])test('client verifies peer candidate with server before admission: '+accepted,async()=>{
 const proof={csrfToken:'p'.repeat(43),expiresAt:Date.now()+60000};
 class CandidateChannel{postMessage(message){if(message.type==='request')queueMicrotask(()=>this.onmessage?.({data:{type:'candidate',requestId:message.requestId,proof}}));}close(){}}
 const ui=mockUI({BroadcastChannelImpl:CandidateChannel,responder:async route=>({status:route==='/api/health'&&!accepted?403:200,ok:route!=='/api/health'||accepted,text:async()=>JSON.stringify(route==='/api/health'?{state:'ok',persistence:'sqlite',activity:{source:'none'}}:route==='/api/tasks'?{tasks:[]}:route==='/api/commands'?{commands:[]}:route==='/api/worker-activity'?{state:'not_configured',workers:[]}:{})})});
 await flush();await ui.ids.get('demo-start').events.click();await flush();
 assert.equal(ui.requests.some(r=>r.route.includes('/bootstrap')||r.route.includes('/recovery-')),false);
 const verify=ui.requests.find(r=>r.route==='/api/health');assert.equal(verify.options.headers['X-Trial-CSRF'],proof.csrfToken);
 if(accepted)assert.equal(JSON.parse(ui.storage.get('mesh.synthetic-demo.proof.v1')).csrfToken,proof.csrfToken);
 else{assert.equal(ui.storage.has('mesh.synthetic-demo.proof.v1'),false);assert.equal(ui.ids.get('demo-end').disabled,true);}
});
