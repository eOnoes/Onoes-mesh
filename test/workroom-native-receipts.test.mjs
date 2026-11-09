import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtempSync,mkdirSync,writeFileSync,readFileSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join,resolve} from 'node:path';
import {createServer} from 'node:http';
import {randomUUID} from 'node:crypto';
import {openTaskStore} from '../lib/task-store.mjs';
import {syncTaskReplies} from '../lib/workroom.mjs';
import {startApp} from '../server.mjs';
import {normalizeWriterObservation} from '../lib/native-writer-observation.mjs';

const writer={schema:'mesh-relay-writer-observation/v1',runId:'run_fixture',state:'observed',
  ownerId:'11111111-1111-4111-8111-111111111111',generation:'22222222-2222-4222-8222-222222222222',
  localWorkEnded:true,unverifiedToolCalls:2,sourceObservedAt:1000,observationOnly:true,writerQuiescence:false};
function fileCompletion(){return {schema:'mesh-file-effect-summary/v1',policy:'bounded_native_write_file_v1',
  observedCalls:1,activeCalls:0,qualifiedCalls:1,effectsSettled:true};}
function fixture(){
  const path=join(mkdtempSync(join(tmpdir(),'mesh-native-receipt-')),'tasks.sqlite');
  const store=openTaskStore(path),task=store.create({title:'Observe original worker'}),sendId=randomUUID();
  store.workroom.reserve(task.id,{id:sendId,agentId:'echo',conversationId:'original',text:'A bounded request'});
  store.workroom.settle(sendId,'accepted');
  const receipt={agentId:'echo',sendId,conversationId:'original',runId:writer.runId,nativeSessionId:'rotated',
    status:'completed',observation:'observed',terminal:true,writerQuiescence:false,writerLifecycle:writer,privateOutput:'discard'};
  return {path,store,task,sendId,receipt};
}

test('existing sync durably binds native run/worker; reopening retains pins without changing task state',async()=>{
  const f=fixture();let store=f.store;const calls=[];
  try{
    const relay={nativeRead:async()=>({messages:[]}),nativeRunReceipt:async binding=>{calls.push(binding);return f.receipt;}};
    const initial=store.workroom.get(f.task.id);
    await syncTaskReplies({workroom:store.workroom,taskId:f.task.id,relay,admitted:()=>true});
    store.close();store=openTaskStore(f.path);
    const saved=store.workroom.get(f.task.id),observed=saved.messages[0].nativeReceipt;
    assert.equal(observed.runId,'run_fixture');assert.equal(observed.ownerId,writer.ownerId);
    assert.equal(observed.receipt.writerLifecycle.unverifiedToolCalls,2);assert.equal(observed.writerQuiescence,false);
    assert.equal('privateOutput' in observed.receipt,false);
    assert.equal(saved.status,initial.status);assert.equal(saved.progress.decision,initial.progress.decision);
    assert.equal(saved.messages[0].state,'accepted');
    await syncTaskReplies({workroom:store.workroom,taskId:f.task.id,relay,admitted:()=>true});
    assert.equal(calls[1].expectedRunId,'run_fixture');
    assert.equal(calls[1].expectedWriterOwnerId,writer.ownerId);
    assert.equal(calls[1].expectedWriterGeneration,writer.generation);
  }finally{store.close();}
});

test('failed/restarted identity checks retain original pins and mark last check unavailable without dispatch',async()=>{
  const f=fixture();try{
    const receipts=f.store.workroom.nativeReceipts;
    receipts.save(f.task.id,f.sendId,0,f.receipt);
    const relay={nativeRead:async()=>({messages:[]}),nativeRunReceipt:async binding=>{
      assert.equal(binding.expectedWriterOwnerId,writer.ownerId);throw new Error('private transport diagnostic');}};
    await syncTaskReplies({workroom:f.store.workroom,taskId:f.task.id,relay,admitted:()=>true});
    const saved=receipts.read(f.task.id,f.sendId);
    assert.equal(saved.observationState,'unavailable');assert.equal(saved.ownerId,writer.ownerId);
    assert.equal(saved.receipt.writerLifecycle.ownerId,writer.ownerId);assert.equal(saved.writerQuiescence,false);
    assert.equal(JSON.stringify(saved).includes('private transport diagnostic'),false);
    assert.equal(f.store.workroom.get(f.task.id).messages[0].state,'accepted');
  }finally{f.store.close();}
});

test('cross-task/changed-run/changed-worker and stale concurrent receipts cannot overwrite a saved binding',()=>{
  const f=fixture();try{
    const receipts=f.store.workroom.nativeReceipts,other=f.store.create({title:'Unrelated'});
    assert.throws(()=>receipts.binding(other.id,f.sendId),e=>e.status===409);
    receipts.save(f.task.id,f.sendId,0,f.receipt);
    assert.throws(()=>receipts.save(f.task.id,f.sendId,0,f.receipt),e=>e.status===409);
    assert.throws(()=>receipts.save(f.task.id,f.sendId,1,{...f.receipt,runId:'run_other'}),e=>e.status===409);
    assert.throws(()=>receipts.save(f.task.id,f.sendId,1,{...f.receipt,writerLifecycle:{...writer,ownerId:writer.generation}}),e=>e.status===409);
    assert.equal(receipts.read(f.task.id,f.sendId).revision,1);
    assert.equal(receipts.read(f.task.id,f.sendId).ownerId,writer.ownerId);
  }finally{f.store.close();}
});

test('file completion is validated independently and cannot grant whole-worker release',()=>{
  const value={...writer,unverifiedToolCalls:0,fileCompletion:{...fileCompletion(),privatePath:'discard'}};
  const normalized=normalizeWriterObservation(value,writer.runId);
  assert.deepEqual(normalized.fileCompletion,fileCompletion());assert.equal(normalized.writerQuiescence,false);
  for(const patch of [{qualifiedCalls:0},{qualifiedCalls:2},{activeCalls:1},{effectsSettled:false},{policy:'other'}]){
    assert.throws(()=>normalizeWriterObservation({...value,fileCompletion:{...value.fileCompletion,...patch}},writer.runId));
  }
  assert.throws(()=>normalizeWriterObservation(value,writer.runId,writer.generation,writer.generation));
});

test('expired sync cannot save an observation or failure after the native read',async()=>{
  const f=fixture();let admitted=true;try{
    const relay={nativeRead:async()=>({messages:[]}),nativeRunReceipt:async()=>{admitted=false;return f.receipt;}};
    await assert.rejects(syncTaskReplies({workroom:f.store.workroom,taskId:f.task.id,relay,admitted:()=>admitted}),e=>e.status===403);
    assert.equal(f.store.workroom.nativeReceipts.read(f.task.id,f.sendId),null);
  }finally{f.store.close();}
});

test('actual guarded sync route persists exact HTTP receipt across app restart without sending',async()=>{
  const observedWriter=process.env.MESH_TEST_NATIVE_RECEIPT_FIXTURE
    ? JSON.parse(readFileSync(process.env.MESH_TEST_NATIVE_RECEIPT_FIXTURE,'utf8')).writerLifecycle
    : {...writer,unverifiedToolCalls:0,fileCompletion:fileCompletion()};
  const directory='data/native-receipt-http-'+randomUUID();mkdirSync(directory,{recursive:true});
  const tokenPath=resolve(directory,'synthetic.key');writeFileSync(tokenPath,'synthetic');
  const store=openTaskStore(resolve(directory,'tasks.sqlite')),task=store.create({title:'HTTP receipt persistence'}),sendId=randomUUID();
  store.workroom.reserve(task.id,{id:sendId,agentId:'echo',conversationId:'original',text:'Fixture request'});
  store.workroom.settle(sendId,'accepted');store.close();
  const calls=[];
  const relay=createServer((req,res)=>{
    calls.push([req.method,req.url]);assert.equal(req.headers.authorization,'Bearer synthetic');
    res.setHeader('Content-Type','application/json');
    if(req.url==='/api/agents/echo/sessions/original/messages')return res.end(JSON.stringify({messages:[]}));
    assert.equal(req.url,'/api/agents/echo/outbox/'+sendId+'/native-run');
    res.end(JSON.stringify({ok:true,receipt:{agentId:'echo',sendId,conversationId:'original',runId:observedWriter.runId,
      nativeSessionId:'rotated',status:'completed',observation:'observed',terminal:true,writerQuiescence:false,writerLifecycle:observedWriter}}));
  });
  await new Promise(resolve=>relay.listen(0,'127.0.0.1',resolve));
  const settings={MESH_RELAY_MODE:'http',MESH_RELAY_URL:'http://127.0.0.1:'+relay.address().port,
    MESH_RELAY_TOKEN_FILE:tokenPath,MESH_SIMPLE_FLOW:'0'},previous={};
  for(const [key,value] of Object.entries(settings)){previous[key]=process.env[key];process.env[key]=value;}
  let app,proof={};
  async function api(path,method='GET',body,extra={}){
    const r=await fetch(app.url+path,{method,headers:{Origin:app.url,'Content-Type':'application/json',...proof,...extra},
      ...(body?{body:JSON.stringify(body)}:{})});const raw=await r.text();return {status:r.status,body:raw?JSON.parse(raw):null,cookie:r.headers.get('set-cookie')};
  }
  async function admit(){const b=await api('/api/trial-session/bootstrap','POST',{});assert.equal(b.status,201);
    proof={Cookie:b.cookie.split(';')[0],'X-Trial-CSRF':b.body.csrfToken};}
  try{
    app=await startApp({dataDir:directory,relayEnabled:true});const route='/api/workroom/'+task.id;
    assert.equal((await api(route+'/sync','POST',{})).status,401);assert.equal(calls.length,0);
    await admit();assert.equal((await api(route+'/sync','POST',{}, {'X-Trial-CSRF':'invalid'})).status,403);
    assert.equal(calls.length,0);
    const synced=await api(route+'/sync','POST',{});assert.equal(synced.status,200,JSON.stringify(synced));
    assert.equal(synced.body.task.messages[0].nativeReceipt.ownerId,observedWriter.ownerId);
    await app.close();app=null;proof={};app=await startApp({dataDir:directory,relayEnabled:true});await admit();
    const reopened=await api(route);
    assert.equal(reopened.body.task.messages[0].nativeReceipt.receipt.writerLifecycle.unverifiedToolCalls,0);
    assert.deepEqual(reopened.body.task.messages[0].nativeReceipt.receipt.writerLifecycle.fileCompletion,observedWriter.fileCompletion);
    assert.equal(reopened.body.task.messages[0].nativeReceipt.writerQuiescence,false);
    assert.equal(reopened.body.task.messages[0].state,'accepted');
    assert.deepEqual(calls,[['GET','/api/agents/echo/sessions/original/messages'],['GET','/api/agents/echo/outbox/'+sendId+'/native-run']]);
  }finally{
    if(app)await app.close();relay.closeAllConnections();await new Promise(resolve=>relay.close(resolve));
    for(const key of Object.keys(settings)){if(previous[key]===undefined)delete process.env[key];else process.env[key]=previous[key];}
  }
});
