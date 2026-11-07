import test from 'node:test';
import assert from 'node:assert/strict';
import {handoffStatus} from '../public/workroom-status.mjs';
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
