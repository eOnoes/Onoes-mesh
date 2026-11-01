import assert from 'node:assert/strict';
import {writeFile} from 'node:fs/promises';
import {admit, mutate, get, rows, request, delay} from './supervisor.mjs';
const app={url:'http://127.0.0.1:49529'};
const proof=await admit(app);
const filename='test/app03-review-m3-browser/tasks.sqlite';
const initial=rows(filename);
for(const row of initial.task_executions){
 const before=await get(app,proof,row.taskId);
 for(const revision of [row.approvalRevision,before.revision]){
  const replay=await mutate(app,proof,`/api/tasks/${row.taskId}/approve`,{revision});
  assert.equal(replay.status,200); assert.deepEqual(replay.json().task,before);
 }
}
assert.deepEqual(rows(filename),initial);
const created=await mutate(app,proof,'/api/tasks',{title:'Independent API duplicate approval'});
assert.equal(created.status,201); const task=created.json().task;
const saved=await mutate(app,proof,`/api/tasks/${task.id}/proposal`,{revision:task.revision,proposal:{command:'node --version',cwd:'.'}});
assert.equal(saved.status,200); const pending=saved.json().task;
const route=`/api/tasks/${task.id}/approve`;
const replies=await Promise.all([mutate(app,proof,route,{revision:pending.revision}),mutate(app,proof,route,{revision:pending.revision})]);
assert.deepEqual(replies.map(r=>r.status).sort(),[200,202]);
assert.equal(replies[0].json().task.execution.id,replies[1].json().task.execution.id);
let terminal;
for(let i=0;i<100;i++){terminal=await get(app,proof,task.id);if(terminal.execution.result)break;await delay(25);}
assert.equal(terminal.execution.result.status,'PASS');assert.equal(terminal.execution.result.cleanupVerified,true);assert.equal(terminal.execution.result.stdout,process.version+'\r\n');
const replay=await mutate(app,proof,route,{revision:pending.revision});assert.equal(replay.status,200);assert.deepEqual(replay.json().task,terminal);
const final=rows(filename);assert.equal(final.task_executions.length,initial.task_executions.length+1);
assert.deepEqual(final.task_executions.filter(r=>r.taskId!==task.id),initial.task_executions);
const logout=await request(app,'/api/trial-session/logout',{method:'POST',headers:{...proof,Origin:app.url,'Content-Type':'application/json'},body:'{}'});assert.equal(logout.status,204);
const evidence={duplicateStatuses:replies.map(r=>r.status),oneNewExecution:true,terminal,priorCancelAndCrashReplayUnchanged:true,initial,final};
await writeFile('test/app03-review-m3-browser/independent-api.json',JSON.stringify(evidence,null,2));
console.log(JSON.stringify({event:'review_independent_api_pass',runId:terminal.execution.id,rootPid:terminal.execution.result.rootPid,duplicateStatuses:evidence.duplicateStatuses,oneNewExecution:true,priorCancelAndCrashReplayUnchanged:true}));
