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

import {mockUI,flush,response,bodyFor} from './app-ui-fixture.mjs';
for(const status of [200,401,403,500])test('client checks peer proof before admission: '+status,async()=>{
 const proof={csrfToken:'p'.repeat(43),expiresAt:Date.now()+60000};
 const replacement={csrfToken:'q'.repeat(43),expiresAt:Date.now()+60000};
 const storedAtHealth=[];
 class CandidateChannel{postMessage(message){if(message.type==='request')queueMicrotask(()=>this.onmessage?.({data:{type:'candidate',requestId:message.requestId,proof}}));}close(){}}
 const ui=mockUI({BroadcastChannelImpl:CandidateChannel,responder:(route,options)=>{
  if(route==='/api/trial-session/bootstrap') return response(201,replacement);
  if(route==='/api/health'){
   storedAtHealth.push(ui.storage.has('mesh.synthetic-demo.proof.v1'));
   if(options.headers['X-Trial-CSRF']===proof.csrfToken&&status!==200)return response(status,{});
  }
  return response(200,bodyFor(route));
 }});
 await flush();await ui.ids.get('demo-start').events.click();await flush();
 const verification=ui.requests.filter(r=>r.route==='/api/health'||r.route.includes('/trial-session/'));
 assert.equal(verification[0].options.headers['X-Trial-CSRF'],proof.csrfToken);
 if(status===500){
  assert.equal(verification.length,1);
  assert.equal(ui.storage.has('mesh.synthetic-demo.proof.v1'),false);
  assert.equal(ui.ids.get('demo-end').disabled,true);
  assert.equal(ui.requests.some(r=>r.route==='/api/tasks'),false);
  return;
 }
 assert.deepEqual(verification.map(r=>r.route),status===200?['/api/health','/api/health']:['/api/health','/api/trial-session/bootstrap','/api/health','/api/health']);
 assert.deepEqual(storedAtHealth,status===200?[false,true]:[false,false,true]);
 const expected=status===200?proof:replacement;
 assert.equal(JSON.parse(ui.storage.get('mesh.synthetic-demo.proof.v1')).csrfToken,expected.csrfToken);
 assert.equal(ui.ids.get('demo-end').disabled,false);
 assert.ok(ui.requests.some(r=>r.route==='/api/tasks'&&r.options.headers['X-Trial-CSRF']===expected.csrfToken));
});
