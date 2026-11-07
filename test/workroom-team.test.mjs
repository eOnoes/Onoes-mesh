import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtempSync} from 'node:fs';
import {tmpdir} from 'node:os';
import path from 'node:path';
import {randomUUID} from 'node:crypto';
import {openTaskStore} from '../lib/task-store.mjs';
import {sendTaskHandoff} from '../lib/workroom.mjs';
import {parseAgentReview} from '../lib/workroom-updates.mjs';

const filename=()=>path.join(mkdtempSync(path.join(tmpdir(),'mesh-team-')),'tasks.sqlite');
const selection=(task,report)=>({sendId:report.sendId,messageId:report.messageId,hash:report.hash,revision:task.progress.revision,taskRevision:task.revision,briefRevision:task.workroom.revision});
function ready(store){
  let task=store.create({title:'Bounded worker task',description:'Create one scoped artifact and run the named checks.'});
  task=store.workroom.save(task.id,{project:'Acceptance',criteria:'Artifact checked independently',owner:'echo',team:'local_build',stage:'ready',revision:0});
  return store.workroom.saveProgress(task.id,{goal:'Create a verified artifact',checklist:[{id:'one',text:'Implement and test',status:'pending'}],result:'',evidence:'',reviewer:'',decision:'pending',revision:0,taskRevision:task.revision,briefRevision:task.workroom.revision});
}
function workerResult(store,id){
  const body={id:randomUUID(),agentId:'echo',conversationId:'echo-session',text:'Worker task'};
  const send=store.workroom.reserve(id,body,'work');store.workroom.settle(body.id,'accepted');
  const update={schema:'workroom-update/v1',taskId:id,sendId:body.id,goal:'Create a verified artifact',checklist:[{id:'one',text:'Implement and test',status:'done'}],result:'Artifact created',evidence:'node --test: PASS'};
  store.workroom.captureReplies(id,body.id,[{id:'user',k:'you',t:send.payload},{id:'worker',k:'ag',t:'```workroom-update\n'+JSON.stringify(update)+'\n```'}]);
  const task=store.workroom.get(id);return store.workroom.applyAgentUpdate(id,selection(task,task.agentUpdates.at(-1))).task;
}
function reviewReply(store,id,{agentId='dsh',verdict='approved'}={}){
  const body={id:randomUUID(),agentId,conversationId:'review-session',text:'Review task'};
  const send=store.workroom.reserve(id,body,'review');store.workroom.settle(body.id,'accepted');
  const review={schema:'workroom-review/v1',taskId:id,sendId:body.id,verdict,summary:'Inspected the artifact against criteria',evidence:'Read source and independently ran the named check: PASS'};
  store.workroom.captureReplies(id,body.id,[{id:'review-user',k:'you',t:send.payload},{id:'reviewer',k:'ag',t:'```workroom-review\n'+JSON.stringify(review)+'\n```'}]);
  const task=store.workroom.get(id);return {review,task,selection:selection(task,task.agentReviews.at(-1))};
}

test('worker result plus separate review survives restart and enables deliberate Done',()=>{
  const file=filename();let store=openTaskStore(file);let task=ready(store);task=workerResult(store,task.id);
  assert.equal(task.progress.decision,'pending');assert.equal(task.worker.agentId,'echo');
  const review=reviewReply(store,task.id);assert.equal(review.task.progress.decision,'pending');
  task=store.workroom.applyAgentReview(task.id,review.selection).task;assert.equal(task.progress.decision,'approved');assert.equal(task.progress.reviewer,'dsh');
  assert.equal(task.history.filter(entry=>entry.kind==='agent_review_recorded').length,1);
  store.close();store=openTaskStore(file);assert.equal(store.workroom.applyAgentReview(task.id,review.selection).duplicate,true);
  const {project,criteria,owner,team,revision}=task.workroom;
  assert.equal(store.workroom.save(task.id,{project,criteria,owner,team,revision,stage:'done'}).status,'done');store.close();
});

test('self-review, cross-task review and changed result are rejected',()=>{
  for(const mode of ['self','other','changed']){
    const store=openTaskStore(filename());let task=workerResult(store,ready(store).id);
    if(mode==='self'){assert.throws(()=>reviewReply(store,task.id,{agentId:'echo'}),error=>error.status===409);store.close();continue;}
    const review=reviewReply(store,task.id,{agentId:mode==='self'?'echo':'dsh'});
    let id=task.id;
    if(mode==='other')id=ready(store).id;
    if(mode==='changed'){task=store.workroom.get(id);store.workroom.saveProgress(id,{...Object.fromEntries(['goal','checklist','result','evidence','reviewer'].map(key=>[key,task.progress[key]])),result:'Changed result',decision:'pending',revision:task.progress.revision,taskRevision:task.revision,briefRevision:task.workroom.revision});}
    assert.throws(()=>store.workroom.applyAgentReview(id,review.selection),error=>error.status===409);store.close();
  }
});

test('scope edits invalidate worker provenance and changes-requested review stays open',()=>{
  const store=openTaskStore(filename());let task=workerResult(store,ready(store).id);
  const review=reviewReply(store,task.id,{verdict:'changes_requested'});
  task=store.workroom.applyAgentReview(task.id,review.selection).task;assert.equal(task.progress.decision,'changes_requested');assert.equal(task.workroom.stage,'needs_you');
  const {project,criteria,owner,team,revision}=task.workroom;
  task=store.workroom.save(task.id,{project,criteria:'New scope',owner,team,revision,stage:'ready'});assert.equal(task.worker,null);store.close();
});

test('handoffs reject missing scope, same reviewer, busy agents and overlapping worker starts',async()=>{
  const store=openTaskStore(filename());let task=ready(store);let sends=0;
  const relay={agents:async()=>[{id:'echo',conversation_id:'echo-session',backend:'hermes',status:'done'},{id:'dsh',conversation_id:'review-session',backend:'a2a',status:'running'}],nativeRead:async()=>({taskSessionBinding:1}),taskMessage:async()=>{sends++;}};
  const args={workroom:store.workroom,taskId:task.id,relay,admitted:()=>true};
  const body={id:randomUUID(),agentId:'echo',conversationId:'echo-session',phase:'work'};
  await sendTaskHandoff({...args,body});await sendTaskHandoff({...args,body});assert.equal(sends,1);
  await assert.rejects(sendTaskHandoff({...args,body:{...body,id:randomUUID()}}),error=>error.status===409);
  task=workerResult(store,ready(store).id);
  await assert.rejects(sendTaskHandoff({...args,taskId:task.id,body:{...body,id:randomUUID(),phase:'review'}}),error=>error.status===409);
  await assert.rejects(sendTaskHandoff({...args,taskId:task.id,body:{id:randomUUID(),agentId:'dsh',conversationId:'review-session',phase:'review'}}),error=>error.status===409);
  const empty=store.create({title:'No scope'});await assert.rejects(sendTaskHandoff({...args,taskId:empty.id,body:{...body,id:randomUUID()}}),error=>error.status===409);store.close();
});

test('changes requested can be followed by a fresh worker and independent approval',()=>{
  const store=openTaskStore(filename());let task=workerResult(store,ready(store).id);
  const first=reviewReply(store,task.id,{verdict:'changes_requested'});task=store.workroom.applyAgentReview(task.id,first.selection).task;
  assert.equal(task.workroom.stage,'needs_you');
  task=workerResult(store,task.id);assert.equal(task.progress.decision,'pending');
  const second=reviewReply(store,task.id);task=store.workroom.applyAgentReview(task.id,second.selection).task;
  const {project,criteria,owner,team,revision}=task.workroom;
  assert.equal(store.workroom.save(task.id,{project,criteria,owner,team,revision,stage:'done'}).status,'done');store.close();
});

test('restart retains uncertain handoff identity and stale tab edits are rejected',()=>{
  const file=filename();let store=openTaskStore(file);let task=ready(store);
  const body={id:randomUUID(),agentId:'echo',conversationId:'echo-session',text:'Scoped worker'};
  store.workroom.reserve(task.id,body,'work');store.close();store=openTaskStore(file);
  const recovered=store.workroom.get(task.id).messages.at(-1);assert.equal(recovered.id,body.id);assert.equal(recovered.state,'unknown');
  const {project,criteria,owner,team,revision}=task.workroom;
  store.workroom.save(task.id,{project,criteria,owner,team,revision,stage:'working'});
  assert.throws(()=>store.workroom.save(task.id,{project,criteria,owner,team,revision,stage:'ready'}),e=>e.status===409);store.close();
});

test('review protocol rejects wrong source, unsupported verdict and extra approval fields',()=>{
  const ids={taskId:randomUUID(),sendId:randomUUID()};const review={schema:'workroom-review/v1',...ids,verdict:'approved',summary:'Inspected',evidence:'Checks PASS'};
  const encode=value=>'```workroom-review\n'+JSON.stringify(value)+'\n```';assert.ok(parseAgentReview(encode(review),ids));
  for(const bad of [{...review,sendId:randomUUID()},{...review,verdict:'done'},{...review,reviewer:'Forged'},{...review,evidence:''}])assert.equal(parseAgentReview(encode(bad),ids),null);
});
test('a verified unsuccessful review cannot be applied as approval',()=>{
  const store=openTaskStore(filename());const task=workerResult(store,ready(store).id);const review=reviewReply(store,task.id);
  store.workroom.recordSendOutcome(task.id,review.selection.sendId,{peerTaskId:'peer-review',state:'TASK_STATE_CANCELED',proofHash:'a'.repeat(64),verifiedAt:new Date().toISOString()});
  assert.throws(()=>store.workroom.applyAgentReview(task.id,review.selection),e=>e.status===409);assert.equal(store.workroom.get(task.id).progress.decision,'pending');store.close();
});

test('lost-response retry keeps frozen payload while agent is busy; accepted retry dispatches nothing',async()=>{
  const store=openTaskStore(filename());const task=ready(store);let busy=false;let attempts=0;const payloads=[];
  const relay={agents:async()=>[{id:'echo',conversation_id:'echo-session',backend:'hermes',status:busy?'working':'done'}],nativeRead:async()=>({taskSessionBinding:1}),taskMessage:async body=>{attempts++;payloads.push(body.text);if(attempts===1){busy=true;throw Object.assign(Error('Response lost'),{status:503});}}};
  const args={workroom:store.workroom,taskId:task.id,relay,admitted:()=>true};const body={id:randomUUID(),agentId:'echo',conversationId:'echo-session',phase:'work'};
  await assert.rejects(sendTaskHandoff({...args,body}),/Response lost/);
  assert.equal(store.workroom.get(task.id).messages[0].state,'unknown');
  const {project,criteria,owner,team,revision}=task.workroom;store.workroom.save(task.id,{project,criteria:criteria+' updated',owner,team,revision,stage:'working'});
  await sendTaskHandoff({...args,body});assert.equal(attempts,2);assert.equal(payloads[0],payloads[1]);
  assert.equal((await sendTaskHandoff({...args,body})).duplicate,true);assert.equal(attempts,2);
  for(const changed of [{phase:'plan'},{agentId:'dsh'},{conversationId:'other-session'}])await assert.rejects(sendTaskHandoff({...args,body:{...body,...changed}}),e=>e.status===409);
  await assert.rejects(sendTaskHandoff({...args,body,admitted:()=>false}),e=>e.status===403);store.close();
});

test('an uncertain send cannot dispatch after approval',async()=>{
  const store=openTaskStore(filename());let task=workerResult(store,ready(store).id);const review=reviewReply(store,task.id);
  task=store.workroom.applyAgentReview(task.id,review.selection).task;
  const send=task.messages.find(m=>m.phase==='review');store.workroom.settle(send.id,'unknown');let dispatched=0;
  await assert.rejects(sendTaskHandoff({workroom:store.workroom,taskId:task.id,body:{id:send.id,agentId:send.agentId,conversationId:send.conversationId,phase:'review'},relay:{taskMessage:async()=>dispatched++},admitted:()=>true}),e=>e.status===409);
  assert.equal(dispatched,0);store.close();
});

test('simultaneous worker starts reserve only one send before dispatch',async()=>{
  const store=openTaskStore(filename());const task=ready(store);let dispatches=0;
  const relay={agents:async()=>[{id:'echo',conversation_id:'echo-session',backend:'hermes',status:'done'}],nativeRead:async()=>({taskSessionBinding:1}),taskMessage:async()=>{dispatches++;}};
  const run=()=>sendTaskHandoff({workroom:store.workroom,taskId:task.id,relay,admitted:()=>true,body:{id:randomUUID(),agentId:'echo',conversationId:'echo-session',phase:'work'}});
  const results=await Promise.allSettled([run(),run()]);assert.equal(results.filter(result=>result.status==='fulfilled').length,1);
  assert.equal(dispatches,1);assert.equal(store.workroom.get(task.id).messages.length,1);store.close();
});

test('same source/hash over a second transport is already applied and cannot replay progress or approval',()=>{
 const store=openTaskStore(filename());let task=workerResult(store,ready(store).id);const worker=task.agentUpdates[0];
 store.workroom.captureReplies(task.id,worker.sendId,[{id:worker.sendId,k:'you',t:''},{id:'second-worker-transport',k:'ag',t:'```workroom-update\n'+JSON.stringify(worker.update)+'\n```'}]);
 task=store.workroom.get(task.id);const duplicate=task.agentUpdates.find(r=>r.messageId==='second-worker-transport');assert.ok(duplicate);assert.equal(duplicate.applied,true);const revision=task.progress.revision;assert.equal(store.workroom.applyAgentUpdate(task.id,selection(task,duplicate)).duplicate,true);assert.equal(store.workroom.get(task.id).progress.revision,revision);
 const changed={...worker.update,evidence:'A different later result'};store.workroom.captureReplies(task.id,worker.sendId,[{id:worker.sendId,k:'you',t:''},{id:'different-worker-report',k:'ag',t:'```workroom-update\n'+JSON.stringify(changed)+'\n```'}]);task=store.workroom.get(task.id);assert.equal(task.agentUpdates.find(r=>r.messageId==='different-worker-report').applied,false);
 const review=reviewReply(store,task.id);task=store.workroom.applyAgentReview(task.id,review.selection).task;
 store.workroom.captureReplies(task.id,review.selection.sendId,[{id:review.selection.sendId,k:'you',t:''},{id:'second-review-transport',k:'ag',t:'```workroom-review\n'+JSON.stringify(review.review)+'\n```'}]);task=store.workroom.get(task.id);const duplicateReview=task.agentReviews.find(r=>r.messageId==='second-review-transport');assert.equal(duplicateReview.applied,true);
 const {goal,checklist,result,evidence}=task.progress;task=store.workroom.saveProgress(task.id,{goal,checklist,result:result+' corrected again',evidence,reviewer:'',decision:'pending',revision:task.progress.revision,taskRevision:task.revision,briefRevision:task.workroom.revision});
 assert.equal(store.workroom.applyAgentReview(task.id,selection(task,duplicateReview)).duplicate,true);assert.equal(store.workroom.get(task.id).progress.decision,'pending');store.close();
});
