import assert from 'node:assert/strict';
import {execFileSync} from 'node:child_process';
import {randomUUID} from 'node:crypto';
import {readFileSync} from 'node:fs';
import {fileURLToPath} from 'node:url';
import {openTaskStore} from '../lib/task-store.mjs';
import {sendTaskHandoff} from '../lib/workroom.mjs';

const brief = JSON.parse(readFileSync(0, 'utf8'));
const match = /^card:([a-f0-9-]+)@/.exec(brief.source);
assert.ok(match);
const taskId = match[1];
const body = {id:randomUUID(), phase:'work', agentId:'echo', conversationId:'print-fixture'};
const helper = fileURLToPath(new URL('./isolated_print_worker.py', import.meta.url));
const filename = 'print-board/tasks.sqlite';

// The test transport acts as the lead handing a limited brief to its worker.
// Its only input here is the message Workroom actually delivered.
function workerAssignment(request) {
  const lines = request.text.split('\n');
  const value = prefix => {
    const matches = lines.filter(line => line.startsWith(prefix));
    assert.equal(matches.length, 1, 'Missing or ambiguous assignment field: '+prefix);
    return matches[0].slice(prefix.length);
  };
  assert.equal(value('Workroom message '), request.id);
  const task = /^([a-f0-9-]+): /.exec(value('Workroom task '));
  assert.ok(task);
  const selected = JSON.parse(value('Spec: '));
  assert.deepEqual(Object.keys(selected).sort(), ['project','revision','source','spec']);
  assert.equal(selected.spec, value('Goal: '));
  assert.ok(selected.source.startsWith('card:'+task[1]+'@'));
  return {brief:selected, taskId:task[1], sendId:request.id};
}

let store = openTaskStore(filename);
try {
  const current = store.workroom.get(taskId);
  assert.equal(current.progress.goal, brief.spec);
  assert.equal(current.title, 'Desk tray');
  assert.equal(brief.project, 'project-A');
  store.workroom.savePlan(taskId, {lead:'echo', workerId:'echo', reviewerId:'nims', state:'locked',
    spec:JSON.stringify(brief), workspace:process.cwd(), allowedFiles:'Assigned specification in memory',
    checks:'Calculate the tray width range', boundaries:'Offline calculation with the selected fields only',
    revision:current.plan?.revision ?? 0, taskRevision:current.revision, briefRevision:current.workroom.revision,
    progressRevision:current.progress.revision});
  const other = store.create({title:'Unrelated fixture card'});
  let dispatches = 0;
  let requestText, update;
  const relay = {
    agents:async () => [{id:'echo', conversation_id:body.conversationId, backend:'hermes', status:'done'}],
    nativeRead:async () => ({taskSessionBinding:1}),
    taskMessage:async request => {
      dispatches++;
      assert.equal(request.id, body.id);
      requestText = request.text;
      const delivered = workerAssignment(request);
      assert.deepEqual(delivered.brief, brief);
      assert.ok(!JSON.stringify(delivered).includes('PRIVATE'));
      assert.throws(() => workerAssignment({...request, text:request.text.replace('\nSpec: ', '\nMissing spec: ')}));
      const output = execFileSync(process.argv[2], ['-I','-B','-X','utf8',helper], {encoding:'utf8',
        windowsHide:true, timeout:process.env.MESH_TEST_PRINT_GGUF ? 165000 : 90000, input:JSON.stringify(delivered)});
      update = JSON.parse(output);
    }
  };
  const handoff = {workroom:store.workroom, taskId, relay, admitted:() => true, body};
  await sendTaskHandoff(handoff);
  await sendTaskHandoff(handoff);
  assert.equal(dispatches, 1);
  assert.equal(update.taskId, taskId);
  assert.equal(update.sendId, body.id);
  store.workroom.captureReplies(taskId, body.id, [
    {id:'assignment', k:'you', t:requestText},
    {id:'response', k:'ag', t:'```workroom-update\n'+JSON.stringify(update)+'\n```'}
  ]);
  const task = store.workroom.get(taskId);
  const [report] = task.agentUpdates;
  assert.equal(report.sendId, body.id);
  store.workroom.applyAgentUpdate(taskId, {sendId:report.sendId, messageId:report.messageId,
    hash:report.hash, revision:task.progress.revision, taskRevision:task.revision,
    briefRevision:task.workroom.revision});
  store.close();
  store = openTaskStore(filename);
  const saved = store.workroom.get(taskId).progress;
  assert.equal(store.workroom.get(other.id).progress.result, '');
  process.stdout.write(JSON.stringify({dispatches, result:saved.result, evidence:saved.evidence,
    decision:saved.decision, checklist:saved.checklist}));
} finally {
  store.close();
}
