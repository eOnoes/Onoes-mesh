import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtempSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {randomUUID} from 'node:crypto';
import {openTaskStore} from '../lib/task-store.mjs';
import {sendTaskHandoff,syncTaskReplies} from '../lib/workroom.mjs';
import {dispatchLocalSession} from '../lib/workroom-local-sessions.mjs';
import {TaskError} from '../lib/task-store.mjs';
const filename=()=>join(mkdtempSync(join(tmpdir(),'mesh-plan-')),'tasks.sqlite');
function ready(store){let t=store.create({title:'Scoped build',description:'One bounded artifact',owner:'echo'});t=store.workroom.save(t.id,{...meta(t),criteria:'Artifact meets acceptance',revision:t.workroom?.revision??1});return store.workroom.saveProgress(t.id,{goal:'Bounded build',checklist:[{id:'one',text:'Implement and verify',status:'pending'}],result:'',evidence:'',reviewer:'',decision:'pending',revision:0,taskRevision:t.revision,briefRevision:t.workroom.revision});}
function meta(t){return{project:t.workroom?.project||'',criteria:t.workroom?.criteria||'',owner:t.workroom?.owner||'echo',team:'local_build',stage:'ready'};}
function proposal(t,state='locked'){return{lead:'echo',spec:'Create one artifact',workspace:'D:/example-only',allowedFiles:'one.mjs; one.test.mjs',checks:'node --test one.test.mjs',boundaries:'No network, purchases or unrelated edits',workerId:'echo',reviewerId:'dsh',state,revision:t.plan?.revision??0,taskRevision:t.revision,briefRevision:t.workroom.revision,progressRevision:t.progress.revision};}
const relay=()=>({agents:async()=>[{id:'echo',conversation_id:'session',backend:'hermes',status:'idle'},{id:'dsh',conversation_id:'review-session',backend:'a2a',status:'idle'}],nativeRead:async()=>({taskSessionBinding:1}),taskMessage:async()=>{}});
const body=()=>({id:randomUUID(),agentId:'echo',conversationId:'session',phase:'work'});

test('new leads begin gated; locks persist, reject incomplete/self-review/stale edits, and ordinary progress keeps scope',()=>{
 const file=filename();let store=openTaskStore(file);try{
  let t=ready(store);assert.equal(t.plan.state,'draft');
  assert.throws(()=>store.workroom.savePlan(t.id,{...proposal(t),spec:''}),/Locking needs/);
  assert.throws(()=>store.workroom.savePlan(t.id,{...proposal(t),reviewerId:'echo'}),/different builder/);
  const p=proposal(t);t=store.workroom.savePlan(t.id,p).task;assert.equal(t.plan.state,'locked');
  assert.throws(()=>store.workroom.savePlan(t.id,p),/changed/);
  t=store.workroom.saveProgress(t.id,{goal:t.progress.goal,checklist:t.progress.checklist.map(s=>({...s,status:'done'})),result:'Implemented',evidence:'Local tests passed',reviewer:'',decision:'pending',revision:t.progress.revision,taskRevision:t.revision,briefRevision:t.workroom.revision});assert.equal(t.plan.state,'locked');
  store.close();store=openTaskStore(file);t=store.workroom.get(t.id);assert.equal(t.plan.state,'locked');assert.equal(t.plan.workerId,'echo');
  store.update(t.id,{title:t.title,description:'Changed scope',label:t.label,status:'open',revision:t.revision});assert.equal(store.workroom.get(t.id).plan.state,'stale');
 }finally{store.close();}
});

test('unlocked/wrong builder handoffs fail before dispatch; frozen scope is included and accepted replay sends nothing',async()=>{
 const store=openTaskStore(filename());let sends=0,payload;const r=relay();r.taskMessage=async message=>{sends++;payload=message.text;};try{
  let t=ready(store);const b=body();await assert.rejects(sendTaskHandoff({workroom:store.workroom,taskId:t.id,body:b,relay:r,admitted:()=>true}),/Lock the current/);assert.equal(sends,0);
  t=store.workroom.savePlan(t.id,proposal(t)).task;
  await assert.rejects(sendTaskHandoff({workroom:store.workroom,taskId:t.id,body:{...b,agentId:'dsh'},relay:r,admitted:()=>true}),/selected in the locked/);
  await sendTaskHandoff({workroom:store.workroom,taskId:t.id,body:b,relay:r,admitted:()=>true});assert.equal(sends,1);assert.match(payload,/Allowed workspace: D:\/example-only/);assert.match(payload,/Spec: Create one artifact/);
  const binding=store.workroom.get(t.id).messages[0];assert.equal(store.workroom.canApproveHandoff(t.id,b.id),true);
  t=store.workroom.get(t.id);store.workroom.savePlan(t.id,proposal(t,'draft'));assert.equal(store.workroom.canApproveHandoff(t.id,b.id),false);
  await sendTaskHandoff({workroom:store.workroom,taskId:t.id,body:b,relay:r,admitted:()=>true});assert.equal(sends,1);assert.deepEqual(store.workroom.get(t.id).messages[0],binding);
 }finally{store.close();}
});

test('async plan change and uncertain old-plan retry cannot dispatch a worker',async()=>{
 const store=openTaskStore(filename());let sends=0;try{
  let t=ready(store);t=store.workroom.savePlan(t.id,proposal(t)).task;const r=relay();r.agents=async()=>{store.workroom.savePlan(t.id,proposal(store.workroom.get(t.id),'draft'));return[{id:'echo',conversation_id:'session',backend:'hermes',status:'idle'}];};r.taskMessage=async()=>{sends++;};
  await assert.rejects(sendTaskHandoff({workroom:store.workroom,taskId:t.id,body:body(),relay:r,admitted:()=>true}),/Lock the current/);assert.equal(sends,0);
  t=store.workroom.get(t.id);t=store.workroom.savePlan(t.id,proposal(t)).task;const b=body();const offline=relay();offline.taskMessage=async()=>{throw new TaskError(503,'lost response');};
  await assert.rejects(sendTaskHandoff({workroom:store.workroom,taskId:t.id,body:b,relay:offline,admitted:()=>true}),/lost response/);
  t=store.workroom.get(t.id);store.workroom.savePlan(t.id,proposal(t));
  await assert.rejects(sendTaskHandoff({workroom:store.workroom,taskId:t.id,body:b,relay:relay(),admitted:()=>true}),/older plan/);
 }finally{store.close();}
});

// HTTP qualification uses only fake local peers; no live Relay, harness or model.
import http from 'node:http';
import {startApp} from '../server.mjs';
test('real plan endpoint keeps admission/CSRF, validates connected assignments and persists across restart',async()=>{
 const previous={};for(const key of ['MESH_RELAY_MODE','MESH_RELAY_URL','MESH_RELAY_TOKEN_FILE'])previous[key]=process.env[key];
 const {writeFileSync}=await import('node:fs');const {resolve}=await import('node:path');
 const token='fixture-'+randomUUID(),tokenPath=join(mkdtempSync(join(tmpdir(),'mesh-plan-http-')),'key');writeFileSync(tokenPath,token);
 const peers=http.createServer((req,res)=>{res.setHeader('Content-Type','application/json');if(req.headers.authorization!=='Bearer '+token){res.writeHead(401);res.end('{}');return;}if(req.url==='/api/agents'){res.end(JSON.stringify([{id:'echo',backend:'hermes',conversation_id:'e',status:'idle'},{id:'dsh',backend:'a2a',conversation_id:'d',status:'idle'}]));return;}res.writeHead(503);res.end('{}');});
 await new Promise(r=>peers.listen(0,'127.0.0.1',r));
 process.env.MESH_RELAY_MODE='http';process.env.MESH_RELAY_URL='http://127.0.0.1:'+peers.address().port;process.env.MESH_RELAY_TOKEN_FILE=tokenPath;
 const dataDir='data/plan-http-'+randomUUID();let app;let headers;
 async function admit(){const r=await fetch(app.url+'/api/trial-session/bootstrap',{method:'POST',headers:{Origin:app.url,'Content-Type':'application/json'},body:'{}'});const b=await r.json();headers={Origin:app.url,'Content-Type':'application/json',Cookie:r.headers.get('set-cookie').split(';')[0],'X-Trial-CSRF':b.csrfToken};}
 async function request(path,method='GET',body,override={}){const r=await fetch(app.url+path,{method,headers:{...headers,...override},...(body?{body:JSON.stringify(body)}:{})});const raw=await r.text();return {status:r.status,body:raw?JSON.parse(raw):null};}
 try{
  app=await startApp({dataDir,relayEnabled:true});await admit();
  let t=(await request('/api/tasks','POST',{title:'HTTP locked task',description:'Bounded fixture',owner:'echo'})).body.task;
  t=(await request('/api/workroom/'+t.id)).body.task;
  t=(await request('/api/workroom/'+t.id,'PATCH',{...meta(t),criteria:'Independent tests pass',revision:t.workroom.revision})).body.task;
  t=(await request('/api/workroom/'+t.id+'/progress','PATCH',{goal:'Fixture',checklist:[{id:'one',text:'One fixture check',status:'pending'}],result:'',evidence:'',reviewer:'',decision:'pending',revision:0,taskRevision:t.revision,briefRevision:t.workroom.revision})).body.task;
  const p=proposal(t),path='/api/workroom/'+t.id+'/plan';
  assert.equal((await fetch(app.url+path,{method:'PATCH',headers:{Origin:app.url,'Content-Type':'application/json'},body:JSON.stringify(p)})).status,401);
  assert.equal((await request(path,'PATCH',p,{Cookie:'','X-Trial-CSRF':''})).status,400);
  assert.equal((await request(path,'PATCH',p,{'X-Trial-CSRF':'wrong'})).status,403);
  assert.equal((await request(path,'PATCH',{...p,workerId:'not-connected'})).status,409);
  assert.equal((await request(path,'PATCH',{...p,reviewerId:'echo'})).status,400);
  const locked=await request(path,'PATCH',p);assert.equal(locked.status,200);assert.equal(locked.body.task.plan.state,'locked');
  assert.equal((await request(path,'PATCH',p)).status,409);
  await app.close();app=await startApp({dataDir,relayEnabled:true});await admit();const after=(await request('/api/workroom/'+t.id)).body.task;assert.equal(after.plan.state,'locked');assert.equal(after.messages.length,0);
 }finally{if(app)await app.close();await new Promise(r=>peers.close(r));for(const [key,value]of Object.entries(previous)){if(value===undefined)delete process.env[key];else process.env[key]=value;}}
});

test('reports and current worker provenance stay bound to their exact plan; stale scope cannot be manually approved',()=>{
 const store=openTaskStore(filename());try{
  let t=ready(store);t=store.workroom.savePlan(t.id,proposal(t)).task;
  const capture=()=>{const b={id:randomUUID(),agentId:'echo',conversationId:'session',text:'Scoped work'};const send=store.workroom.reserve(t.id,b,'work');store.workroom.settle(b.id,'accepted');const update={schema:'workroom-update/v1',taskId:t.id,sendId:b.id,goal:t.progress.goal,checklist:t.progress.checklist.map(s=>({...s,status:'done'})),result:'Fixture complete',evidence:'Local checks passed'};store.workroom.captureReplies(t.id,b.id,[{id:'user',k:'you',t:send.payload},{id:'result',k:'ag',t:'```workroom-update\n'+JSON.stringify(update)+'\n```'}]);t=store.workroom.get(t.id);const r=t.agentUpdates.at(-1);return{sendId:r.sendId,messageId:r.messageId,hash:r.hash,revision:t.progress.revision,taskRevision:t.revision,briefRevision:t.workroom.revision};};
  const selection=capture();t=store.workroom.savePlan(t.id,{...proposal(t),spec:'A different scope'}).task;
  assert.throws(()=>store.workroom.applyAgentUpdate(t.id,selection),/older or unlocked plan/);assert.equal(t.worker,null);
  // A separate task proves an applied worker is no longer current after re-lock.
  t=ready(store);t=store.workroom.savePlan(t.id,{...proposal(t),workspace:'D:/second-example'}).task;const current=capture();t=store.workroom.applyAgentUpdate(t.id,current).task;assert.ok(t.worker);
  t=store.workroom.savePlan(t.id,proposal(t)).task;assert.equal(t.worker,null);assert.equal(t.progress.decision,'pending');
  store.update(t.id,{title:t.title,description:'Scope changed after lock',label:t.label,status:'open',revision:t.revision});t=store.workroom.get(t.id);assert.equal(t.plan.state,'stale');
  assert.throws(()=>store.workroom.saveProgress(t.id,{goal:t.progress.goal,checklist:t.progress.checklist,result:t.progress.result,evidence:t.progress.evidence,reviewer:'owner',decision:'approved',revision:t.progress.revision,taskRevision:t.revision,briefRevision:t.workroom.revision}),/Lock the current scope/);
 }finally{store.close();}
});

test('lead planning reports can populate a draft checklist before scope is locked',()=>{
 const store=openTaskStore(filename());try{
  let t=ready(store);const b={id:randomUUID(),agentId:'echo',conversationId:'session',text:'Plan only'};const send=store.workroom.reserve(t.id,b,'plan');store.workroom.settle(b.id,'accepted');
  const update={schema:'workroom-update/v1',taskId:t.id,sendId:b.id,goal:'Clarified proposed goal',checklist:[{id:'plan-one',text:'Inspect named project scope',status:'pending'}],result:'Proposed only; owner lock still required',evidence:'No tools used in fixture'};
  store.workroom.captureReplies(t.id,b.id,[{id:'user',k:'you',t:send.payload},{id:'plan-result',k:'ag',t:'```workroom-update\n'+JSON.stringify(update)+'\n```'}]);t=store.workroom.get(t.id);const r=t.agentUpdates[0];
  t=store.workroom.applyAgentUpdate(t.id,{sendId:r.sendId,messageId:r.messageId,hash:r.hash,revision:t.progress.revision,taskRevision:t.revision,briefRevision:t.workroom.revision}).task;
  assert.equal(t.progress.goal,update.goal);assert.equal(t.plan.state,'draft');assert.equal(t.progress.decision,'pending');assert.equal(t.worker,null);
 }finally{store.close();}
});

test('online backup and migration restore preserve a nonempty locked plan',async()=>{
 const {execFileSync}=await import('node:child_process');
 const directory=mkdtempSync(join(tmpdir(),'mesh-plan-backup-')),file=join(directory,'source.sqlite');
 let store=openTaskStore(file);let t=ready(store);t=store.workroom.savePlan(t.id,proposal(t)).task;const expected=t.plan;store.close();
 const receipt=JSON.parse(execFileSync(process.execPath,['integrations/workroom-backup.mjs',file,join(directory,'snapshot')],{encoding:'utf8'}));
 assert.equal(receipt.restore,'PASS');assert.equal(receipt.counts.workroom_plans,1);assert.match(receipt.durable.workroom_plans,/^[a-f0-9]{64}$/);
 store=openTaskStore(receipt.restored);try{assert.deepEqual(store.workroom.get(t.id).plan,expected);}finally{store.close();}
});

function localReady(store,workspace='D:/example-only'){
 let t=ready(store);store.workroom.savePlan(t.id,{...proposal(t),workspace,reviewerId:'nims'});t=store.workroom.get(t.id);
 return {t,send:{id:randomUUID(),agentId:'echo',conversationId:'native-local',text:'Implement this locked build.'},
  profile:{profileRef:'echo-builder-v1',identityRef:'approved-fixture',model:'synthetic',baseUrl:'http://127.0.0.1:9/v1',workspace}};
}
const nativeSid='local-'+'a'.repeat(64),nativeAid='b'.repeat(32);
function localReceipt(row,status='started',generation=1){return {found:true,session_id:row.sessionId,submission_id:row.submissionId,receipt:{admission_id:nativeAid,status,execution_generation:generation,authority_epoch:1,ref:{profile_id:'fixture-native-home',session_id:row.sessionId}}};}

test('native intent shares saved build identity, survives restart, and cannot switch profile or Relay transport',async()=>{
 const file=filename();let store=openTaskStore(file);try{
  const {t,send,profile}=localReady(store);
  assert.throws(()=>store.workroom.localSessions.reserve(t.id,send,{...profile,api_key:'do-not-store'}),/profile/);
  assert.throws(()=>store.workroom.localSessions.reserve(t.id,send,{...profile,workspace:'D:/wrong-workspace'}),/matching workspace/);
  assert.equal(store.workroom.get(t.id).messages.length,0);
  const prepared=store.workroom.localSessions.reserve(t.id,send,profile),first=prepared.nativeLocal;
  assert.match(first.createRequestId,/^mesh-local-create-[a-f0-9]{64}$/);assert.match(first.submissionId,/^mesh-local-submit-[a-f0-9]{64}$/);
  store.close();store=openTaskStore(file);
  assert.deepEqual(store.workroom.localSessions.reserve(t.id,send,profile).nativeLocal,first);
  assert.throws(()=>store.workroom.reserve(t.id,send,'work'),/different message/);
  assert.throws(()=>store.workroom.localSessions.reserve(t.id,send,{...profile,identityRef:'different-owner'}),/different message/);
  assert.throws(()=>store.workroom.settle(send.id,'rejected'),/dedicated native receipt/);
  let calls=0;await assert.rejects(sendTaskHandoff({workroom:store.workroom,taskId:t.id,body:{...body(),id:send.id,agentId:send.agentId,conversationId:send.conversationId},relay:{nativeRead:async()=>{calls++;}},admitted:()=>true}),/dedicated native transport/);
  assert.equal(calls,0);
 }finally{store.close();}
});

test('uncertain native submission recovers only by readback across restart and pins immutable admission identity',async()=>{
 const file=filename();let store=openTaskStore(file);try{
  const {t,send,profile}=localReady(store);let creates=0,submits=0,reads=0;
  const rpc=async(method,params)=>{
   if(method==='session.create'){creates++;return {session_id:nativeSid};}
   if(method==='prompt.submit'){submits++;throw new Error('reply lost after receiver commit');}
   assert.equal(method,'prompt.lookup');reads++;const row=store.workroom.localSessions.read(t.id,send.id);
   return localReceipt(row);
  };
  const options={taskId:t.id,body:send,profile,rpc,credential:async()=>'DO_NOT_PERSIST_KEY',admitted:()=>true};
  await assert.rejects(dispatchLocalSession({...options,workroom:store.workroom}),/uncertain/);
  const pending=store.workroom.localSessions.read(t.id,send.id);assert.equal(pending.state,'submit_unknown');
  store.close();store=openTaskStore(file);
  const changed=store.workroom.get(t.id);store.workroom.saveProgress(t.id,{goal:'Later clarification must not hide the original receipt',checklist:changed.progress.checklist,result:changed.progress.result,evidence:changed.progress.evidence,reviewer:changed.progress.reviewer,decision:changed.progress.decision,revision:changed.progress.revision,taskRevision:changed.revision,briefRevision:changed.workroom.revision});
  assert.throws(()=>store.workroom.localSessions.startSubmit(t.id,send.id,pending.revision),/first native submission/);
  const observed=await dispatchLocalSession({...options,workroom:store.workroom});
  assert.equal(creates,1);assert.equal(submits,1);assert.equal(reads,1);assert.equal(observed.admissionId,nativeAid);
  assert.equal(observed.writerQuiescence,false);assert.equal(store.workroom.get(t.id).messages[0].state,'accepted');
  assert.equal(JSON.stringify(store.workroom.get(t.id)).includes('DO_NOT_PERSIST_KEY'),false);
  assert.throws(()=>store.workroom.localSessions.observe(t.id,send.id,pending.revision,localReceipt(observed)),/binding changed/);
  assert.throws(()=>store.workroom.localSessions.observe(t.id,send.id,observed.revision,{...localReceipt(observed),receipt:{...localReceipt(observed).receipt,admission_id:'c'.repeat(32)}}),/identity changed/);
  const missing=store.workroom.localSessions.observe(t.id,send.id,observed.revision,{found:false,session_id:observed.sessionId,submission_id:observed.submissionId});
  assert.equal(missing.admissionId,nativeAid);assert.equal(missing.state,'unavailable');
  const terminal=store.workroom.localSessions.observe(t.id,send.id,missing.revision,localReceipt(missing,'terminal'));
  assert.equal(terminal.writerQuiescence,false);assert.equal(store.workroom.get(t.id).messages[0].state,'accepted');
  const {execFileSync}=await import('node:child_process');
  const backup=JSON.parse(execFileSync(process.execPath,['integrations/workroom-backup.mjs',file,join(mkdtempSync(join(tmpdir(),'mesh-native-binding-backup-')),'snapshot')],{encoding:'utf8'}));
  assert.equal(backup.restore,'PASS');const restored=openTaskStore(backup.restored);try{assert.deepEqual(restored.workroom.localSessions.read(t.id,send.id),terminal);}finally{restored.close();}
  const peer=localReady(store);assert.throws(()=>store.workroom.reserve(peer.t.id,peer.send,'work'),/native writer/);
  let legacyReads=0;await syncTaskReplies({workroom:store.workroom,taskId:t.id,relay:{nativeRead:async()=>{legacyReads++;}},admitted:()=>true});assert.equal(legacyReads,0);
  assert.throws(()=>store.workroom.nativeReceipts.binding(t.id,send.id),/dedicated native session/);
 }finally{store.close();}
});

test('native unsent work refuses a changed scope while already attempted work remains reconcilable',()=>{
 const store=openTaskStore(filename());try{
  let {t,send,profile}=localReady(store);const local=store.workroom.localSessions;
  let row=local.reserve(t.id,send,profile).nativeLocal;
  row=local.startCreate(t.id,send.id,row.revision);row=local.bindSession(t.id,send.id,row.revision,{session_id:nativeSid});
  t=store.workroom.get(t.id);store.workroom.saveProgress(t.id,{goal:'Changed after session creation',checklist:t.progress.checklist,result:t.progress.result,evidence:t.progress.evidence,reviewer:t.progress.reviewer,decision:t.progress.decision,revision:t.progress.revision,taskRevision:t.revision,briefRevision:t.workroom.revision});
  assert.throws(()=>local.startSubmit(t.id,send.id,row.revision),/changed before native submission/);
  assert.equal(local.read(t.id,send.id).state,'session_bound');
 }finally{store.close();}
});
