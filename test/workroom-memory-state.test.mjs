import test from 'node:test';
import assert from 'node:assert/strict';
import {randomUUID} from 'node:crypto';
import {rmSync} from 'node:fs';
import {resolve} from 'node:path';
import {startApp} from '../server.mjs';
import {createWorkroomProjectSyncCandidate} from '../integrations/workroom-project-sync-candidate.mjs';
import {memoryStatePresentation,paintMemoryState} from '../public/workroom-memory-state.mjs';

const schema='onoes-workroom-memory-state/v1';
async function fixture(t,{factory}={}){
  const old=process.env.MESH_STANDALONE;process.env.MESH_STANDALONE='1';
  const dataDir='test/app03-memory-state-'+randomUUID();let controller,db;
  const app=await startApp({dataDir,projectSyncTestOptions:{source:'disposable_fixture',factory:context=>{
    db=context.db;controller=factory?factory(context):createWorkroomProjectSyncCandidate(context,{storeId:'synthetic-store',initialize:true});return controller;
  }}});
  t.after(async()=>{await app.close();rmSync(resolve(dataDir),{recursive:true,force:true});if(old===undefined)delete process.env.MESH_STANDALONE;else process.env.MESH_STANDALONE=old;});
  let proof={};
  async function request(path,{method='GET',body,admitted=true}={}){
    const res=await fetch(app.url+path,{method,headers:{Origin:app.url,'Content-Type':'application/json',...(admitted?proof:{})},...(body?{body:JSON.stringify(body)}:{})});
    const text=await res.text(),value=text?JSON.parse(text):null;return {res,value};
  }
  const boot=await request('/api/trial-session/bootstrap',{method:'POST',body:{}});
  proof={Cookie:boot.res.headers.get('set-cookie').split(';')[0],'X-Trial-CSRF':boot.value.csrfToken};
  const created=await request('/api/tasks',{method:'POST',body:{title:'Synthetic card',owner:'nims'}});
  assert.equal(created.res.status,201);const cardId=created.value.task.id;
  return {app,request,cardId,get controller(){return controller;},get db(){return db;}};
}

test('admitted selected-card status covers sharing states without reads mutating the queue',async t=>{
  const f=await fixture(t),path='/api/workroom/'+f.cardId;
  assert.equal((await f.request(path,{admitted:false})).res.status,401);
  assert.deepEqual((await f.request(path)).value.memorySync,{schema,state:'not_shared'});
  f.controller.link({cardId:f.cardId,projectId:'project-A',approvalRef:'DO-NOT-LEAK-APPROVAL',fields:['title','stage']});
  const event=f.db.prepare('SELECT * FROM mind_project_outbox').get();
  const receipt={schema:'onoes-mind-project-receipt/v1',storeId:'synthetic-store',scope:'project/onoes-mind/shared',
    principal:'mesh-project-sync',projectId:'project-A',cardId:f.cardId,eventId:event.eventId,
    sequence:event.sequence,payloadHash:event.payloadHash,receiptId:'rcpt-synthetic',durable:true,recordState:'active'};
  f.db.prepare('UPDATE mind_project_outbox SET receipt=?').run(JSON.stringify(receipt));
  for(const state of ['pending','uncertain','held','saved']){
    f.db.prepare('UPDATE mind_project_outbox SET state=?').run(state);
    const before=f.db.prepare('SELECT * FROM mind_project_outbox').all();
    const result=await f.request(path);
    assert.match(result.res.headers.get('cache-control'),/no-store/);
    assert.deepEqual(result.value.memorySync,{schema,state});
    assert.ok(!JSON.stringify(result.value).includes('DO-NOT-LEAK-APPROVAL'));
    assert.ok(!JSON.stringify(result.value.memorySync).includes(event.eventId));
    assert.deepEqual(f.db.prepare('SELECT * FROM mind_project_outbox').all(),before);
    assert.equal(result.value.task.workroom.stage,'backlog');
  }
  f.controller.withdraw(f.cardId);
  assert.deepEqual((await f.request(path)).value.memorySync,{schema,state:'withdrawn'});
});

test('unrecorded source change and unreadable policy cannot falsely show saved',async t=>{
  const f=await fixture(t),path='/api/workroom/'+f.cardId;
  f.controller.link({cardId:f.cardId,projectId:'project-A',approvalRef:'synthetic-owner',fields:['title','stage']});
  f.db.exec("UPDATE mind_project_outbox SET state='saved'; UPDATE tasks SET revision=revision+1");
  assert.equal((await f.request(path)).value.memorySync.state,'held');
  f.db.exec("UPDATE mind_project_outbox SET state='pending'; UPDATE mind_project_capture_policy SET fields='invalid JSON'");
  assert.deepEqual((await f.request(path)).value.memorySync,{schema,state:'unavailable'});
});

test('a saved marker without a bound receipt cannot claim the update was recorded',async t=>{
  const f=await fixture(t),path='/api/workroom/'+f.cardId;
  f.controller.link({cardId:f.cardId,projectId:'project-A',approvalRef:'synthetic-owner',fields:['title','stage']});
  f.db.exec("UPDATE mind_project_outbox SET state='saved'");
  assert.equal((await f.request(path)).value.memorySync.state,'held');
});

test('status projection strips invalid controller data and exposes no new state-setting API',async t=>{
  const f=await fixture(t,{factory:()=>({capture(){},status(){return {state:'saved',token:'DO-NOT-LEAK'};}})});
  const result=await f.request('/api/workroom/'+f.cardId);
  assert.deepEqual(result.value.memorySync,{schema,state:'unavailable'});
  assert.ok(!JSON.stringify(result.value).includes('DO-NOT-LEAK'));
  assert.equal((await f.request('/api/workroom/'+f.cardId,{method:'PATCH',body:{memorySync:{state:'saved'}}})).res.status,400);
});

test('fixture seam refuses production mode and production data directories',async()=>{
  const old=process.env.MESH_STANDALONE;
  try{
    delete process.env.MESH_STANDALONE;
    await assert.rejects(startApp({dataDir:'test/app03-rejected-sync',projectSyncTestOptions:{source:'disposable_fixture',factory(){}}}),/isolated fixture/);
    process.env.MESH_STANDALONE='1';
    await assert.rejects(startApp({dataDir:'data/workroom-preview',projectSyncTestOptions:{source:'disposable_fixture',factory(){}}}),/isolated fixture/);
  }finally{if(old===undefined)delete process.env.MESH_STANDALONE;else process.env.MESH_STANDALONE=old;}
});

test('presentation identifies an unlinked card only when the server confirms it',()=>{
  assert.equal(memoryStatePresentation(undefined),null);
  assert.equal(memoryStatePresentation({schema,state:'off'}),null);
  assert.equal(memoryStatePresentation({schema,state:'not_shared'}).label,'Not linked');
  for(const state of ['pending','uncertain','held','saved','withdrawn','unavailable']){
    const result=memoryStatePresentation({schema,state});assert.equal(result.state,state);assert.ok(result.label.length<30);
  }
  assert.match(memoryStatePresentation({schema,state:'saved'}).description,/does not approve/);
  assert.equal(memoryStatePresentation({schema,state:'<img src=x onerror=alert(1)>'}).state,'unavailable');
});

test('status rendering uses plain text and clears a previously saved label',()=>{
  const element={hidden:false,textContent:'',title:'',attributes:{},setAttribute(key,value){this.attributes[key]=value;}};
  paintMemoryState(element,{schema,state:'saved'});assert.equal(element.hidden,false);assert.match(element.textContent,/Last update recorded/);
  for(const state of ['offline','held','uncertain','withdrawn','unavailable']){
    paintMemoryState(element,{schema,state});
    assert.ok(element.textContent.endsWith(memoryStatePresentation({schema,state}).description));
    assert.equal(element.attributes['aria-label'],element.textContent);
    assert.equal(element.title,'');
  }
  paintMemoryState(element,{schema,state:'pending'});assert.match(element.textContent,/Pending/);
  assert.equal(element.textContent,'Mind · Pending');
  paintMemoryState(element,{schema,state:'not_shared'});assert.equal(element.hidden,false);assert.equal(element.textContent,'Mind · Not linked');
  assert.match(element.attributes['aria-label'],/no link to a Mind project/);
  paintMemoryState(element,{schema,state:'off'});assert.equal(element.hidden,true);assert.equal(element.textContent,'');assert.equal(element.title,'');
});
