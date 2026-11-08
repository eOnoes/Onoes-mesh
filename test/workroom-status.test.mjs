import test from 'node:test';
import assert from 'node:assert/strict';
import {handoffStatus,taskTimeline,cardNextAction,nativeWorkerStatus} from '../public/workroom-status.mjs';
import {withNims} from '../lib/nims-link.mjs';

function nativeMessage(){
  return {id:'send',agentId:'echo',conversationId:'chat',nativeReceipt:{runId:'run_one',ownerId:'owner',generation:'generation',observationState:'observed',
    receipt:{agentId:'echo',sendId:'send',conversationId:'chat',runId:'run_one',observation:'observed',status:'completed',
      writerLifecycle:{state:'observed',runId:'run_one',ownerId:'owner',generation:'generation',observationOnly:true,writerQuiescence:false,localWorkEnded:false}}}};
}
test('completed reply does not hide unfinished local work, and local end never implies Done',()=>{
  const message=nativeMessage(),before=JSON.stringify(message);
  assert.equal(nativeWorkerStatus(message).label,'Local worker not finished');
  assert.equal(JSON.stringify(message),before);
  message.nativeReceipt.receipt.writerLifecycle.localWorkEnded=true;
  assert.match(nativeWorkerStatus(message).label,/confirmation pending/);
  assert.match(nativeWorkerStatus(message).next,/does not mark the card Done/);
});
test('unavailable, legacy and crossed worker observations remain unconfirmed',()=>{
  for(const change of [m=>m.nativeReceipt.observationState='unavailable',m=>delete m.nativeReceipt.receipt.writerLifecycle,
    m=>m.nativeReceipt.receipt.sendId='other',m=>m.nativeReceipt.receipt.conversationId='other',
    m=>m.nativeReceipt.receipt.writerLifecycle.ownerId='other',m=>m.nativeReceipt.receipt.writerLifecycle.generation='other']){
    const message=nativeMessage();change(message);assert.equal(nativeWorkerStatus(message).label,'Worker status unconfirmed');
  }
  assert.equal(nativeWorkerStatus({agentId:'nims'}),null);
  assert.equal(nativeWorkerStatus({agentId:'echo'}),null);
});

test('card next action offers Done only after recorded approval, regardless of lane',()=>{
  const t={workroom:{stage:'backlog'},progress:{decision:'pending',checklist:[{status:'done'}]},agentReviews:[{review:{verdict:'approved'},applied:false}]};
  assert.equal(cardNextAction(t),'record');
  t.agentReviews[0].applied=true;assert.equal(cardNextAction(t),'edit');
  t.progress.decision='approved';assert.equal(cardNextAction(t),'finish');
  t.workroom.stage='done';assert.equal(cardNextAction(t),'close');
});

test('requested changes, stale review and active team never offer premature Done',()=>{
  for(const decision of ['pending','stale','changes_requested']){
    const t={workroom:{stage:'working'},progress:{decision},automation:{state:'active'}};
    assert.equal(cardNextAction(t),'progress');
    t.agentReviews=[{applied:false,review:{verdict:'changes_requested'}}];assert.equal(cardNextAction(t),'record');
    t.agentReviews[0].applied=true;t.automation.state='needs_review';assert.equal(cardNextAction(t),'edit');
  }
});

test('Nims reply exposes its completion time under the field consumed by Workroom capture',async()=>{
  const at='2026-11-07T23:45:42.597Z',finishedAt='2026-11-07T23:47:04.000Z';
  const records=[{sendId:'review',payload:'Frozen request',state:'completed',text:'Exact final report',at,finishedAt}];
  const adapter=withNims({}, {root:'.',workroom:{nims:{list:()=>records}},client:{}});
  const {messages}=await adapter.nativeRead('/api/agents/nims/sessions/mesh-nims/messages');
  assert.equal(messages[0].created_at,at);assert.equal(messages[1].created_at,finishedAt);
  assert.equal(messages[1].ts,finishedAt);assert.equal(messages[1].id,'review-result');assert.equal(messages[1].t,'Exact final report');
  records[0].state='running';assert.equal((await adapter.nativeRead('/api/agents/nims/sessions/mesh-nims/messages')).messages.length,1);
});

test('legacy Nims results use exact completion after request, without rewriting saved facts',()=>{
  const at='2026-11-07T23:45:42.597Z',finishedAt='2026-11-07T23:47:04.000Z';
  const t={id:'card',messages:[{id:'review',agentId:'nims',phase:'review',state:'accepted',at,nims:{state:'completed',finishedAt}}],
    agentReviews:[{sendId:'review',agentId:'nims',at,review:{taskId:'card',sendId:'review',verdict:'approved',summary:'Checked',evidence:'Read actual source'}}]};
  const before=JSON.stringify(t),events=taskTimeline(t),received=events.find(e=>e.label==='Review received · approved');
  assert.equal(received.at,finishedAt);assert.ok(events.findIndex(e=>e.id==='send-review')<events.indexOf(received));assert.equal(JSON.stringify(t),before);
  t.agentReviews[0].at='2026-11-07T23:48:00Z';assert.equal(taskTimeline(t).find(e=>e.label==='Review received · approved').at,t.agentReviews[0].at);
  t.agentReviews[0].at=at;t.messages[0].nims.finishedAt='invalid';assert.equal(taskTimeline(t).find(e=>e.label==='Review received · approved').at,at);
  t.messages[0].nims.finishedAt=finishedAt;t.agentReviews[0].agentId='other';assert.equal(taskTimeline(t).find(e=>e.label==='Review received · approved').at,at);
});
test('verified canceled attempt is distinct from global agent waiting; delivery remains accepted',()=>{
  const task={messages:[{id:'cancelled',phase:'review',agentId:'dsh',conversationId:'same',state:'accepted',outcome:{state:'TASK_STATE_CANCELED'}}]};
  const signal=handoffStatus(task,[{id:'dsh',conversation_id:'same',status:'waiting'}]);assert.equal(signal.label,'Review canceled');assert.match(signal.next,/Other Relay work is unchanged/);assert.equal(task.messages[0].state,'accepted');
});
const task={messages:[{id:'send',phase:'review',agentId:'dsh',conversationId:'session',state:'accepted'}]};
const agent={id:'dsh',conversation_id:'session',status:'waiting'};
test('waiting does not invent an approval or question',()=>{const s=handoffStatus(task,[agent]);assert.equal(s.label,'Agent waiting');assert.match(s.next,/reason is unavailable/);});
test('actual approval is distinguished from waiting',()=>assert.equal(handoffStatus(task,[{...agent,approval:{id:'request'}}]).label,'Agent needs approval'));
test('unknown delivery instructs same-identity recovery',()=>assert.match(handoffStatus({...task,messages:[{...task.messages[0],state:'unknown'}]},[]).next,/original message identity/));
test('missing or different session never reports current task running',()=>assert.equal(handoffStatus(task,[{...agent,conversation_id:'other',status:'working'}]).label,'Agent unavailable'));
test('agent done never implies task done',()=>assert.equal(handoffStatus(task,[{...agent,status:'done'}]).label,'Agent done · no task report'));
test('task-bound report wins over unrelated live agent status',()=>assert.equal(handoffStatus({...task,agentReviews:[{sendId:'send',applied:false}]},[agent]).label,'Review received'));
test('unrelated reports do not resolve a send',()=>assert.equal(handoffStatus({...task,agentReviews:[{sendId:'other',applied:true}]},[agent]).label,'Agent waiting'));
