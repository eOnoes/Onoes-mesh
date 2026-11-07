import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtempSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {randomUUID} from 'node:crypto';
import {verifyDshTaskOutcome} from '../lib/dsh-task-outcome.mjs';
import {createDshApprovalClient} from '../lib/dsh-approval.mjs';
import {openTaskStore} from '../lib/task-store.mjs';
const source={id:'send',taskId:'card',conversationId:'context',peerTaskId:'peer',payload:'Exact frozen Workroom handoff'};
const native={id:'peer',contextId:'context',history:[{role:'ROLE_USER',parts:[{text:source.payload}]}],status:{state:'TASK_STATE_CANCELED',timestamp:'2026-11-05T00:00:00Z'},artifacts:[]};
test('terminal proof requires exact unique user payload, peer and conversation; active states are not guessed',()=>{
  assert.equal(verifyDshTaskOutcome(native,source).state,'TASK_STATE_CANCELED');
  for(const changed of [{id:'other'},{contextId:'other'},{history:[]},{history:[native.history[0],native.history[0]]},{history:[{role:'ROLE_AGENT',parts:[{text:source.payload}]}]},{status:{state:'TASK_STATE_INPUT_REQUIRED'}}])assert.throws(()=>verifyDshTaskOutcome({...native,...changed},source),e=>e.status===409);
});
test('native lookup uses only GetTask with bounded response and validates the RPC receipt',async()=>{
  let calls=0;const client=createDshApprovalClient({token:'fixture',fetchImpl:async(url,options)=>{
    calls++;assert.equal(new URL(url).pathname,'/a2a');const body=JSON.parse(options.body);assert.equal(body.method,'GetTask');assert.deepEqual(body.params,{id:'peer'});
    return new Response(JSON.stringify({jsonrpc:'2.0',id:body.id,result:native}));
  }});
  assert.equal((await client.readTaskOutcome(source,'peer')).state,'TASK_STATE_CANCELED');assert.equal(calls,1);
  await assert.rejects(client.readTaskOutcome(source,'../other'),e=>e.status===400);assert.equal(calls,1);
  const mismatch=createDshApprovalClient({token:'fixture',fetchImpl:async()=>new Response(JSON.stringify({jsonrpc:'2.0',id:'wrong',result:native}))});
  await assert.rejects(mismatch.readTaskOutcome(source,'peer'),e=>e.status===409);
});
test('native outcome persists once without rewriting acceptance, progress or another task',()=>{
  const file=join(mkdtempSync(join(tmpdir(),'mesh-native-outcome-')),'tasks.sqlite');let store=openTaskStore(file);
  const task=store.create({title:'Scoped recovery'}),other=store.create({title:'Other work'});const id=randomUUID();
  const send=store.workroom.reserve(task.id,{id,agentId:'dsh',conversationId:'context',text:'Plan only'},'plan');store.workroom.settle(id,'accepted');
  const evidence=verifyDshTaskOutcome({...native,history:[{role:'ROLE_USER',parts:[{text:send.payload}]}]},{...source,payload:send.payload});
  const before=store.workroom.get(task.id);
  assert.throws(()=>store.workroom.recordSendOutcome(other.id,id,evidence),e=>e.status===409);
  const first=store.workroom.recordSendOutcome(task.id,id,evidence);assert.equal(first.duplicate,false);assert.equal(first.task.messages[0].state,'accepted');assert.deepEqual(first.task.progress,before.progress);
  assert.equal(store.workroom.canApproveHandoff(task.id,id),false);
  store.close();store=openTaskStore(file);const replay=store.workroom.recordSendOutcome(task.id,id,evidence);assert.equal(replay.duplicate,true);
  assert.equal(replay.task.history.filter(e=>e.kind==='native_outcome_verified').length,1);assert.equal(replay.task.messages[0].outcome.peerTaskId,'peer');
  assert.throws(()=>store.workroom.recordSendOutcome(task.id,id,{...evidence,state:'TASK_STATE_COMPLETED'}),e=>e.status===409);store.close();
});
