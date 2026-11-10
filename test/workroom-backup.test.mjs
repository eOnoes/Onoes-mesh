import test from 'node:test';
import assert from 'node:assert/strict';
import {compareRestoredRows} from '../lib/workroom-backup.mjs';

const before=()=>({tasks:[{id:'card',title:'Keep this',status:'open'}],
  workroom_automation:[{taskId:'card',state:'active',reason:'',revision:2,workerSendId:'original-send',reviewerSendId:'original-review'}],
  workroom_sends:[{id:'original-send',state:'prepared',payload:'frozen scope'}],
  workroom_local_sessions:[{taskId:'card',sessionId:'original-session',submissionId:'original-submission',writerQuiescence:0}],
  workroom_progress:[{taskId:'card',decision:'pending'}]});
const recovered=value=>{const r=structuredClone(value);Object.assign(r.workroom_automation[0],{state:'paused',reason:'Mesh restarted. Inspect and explicitly resume; no request was replayed.',revision:3});r.workroom_sends[0].state='unknown';return r;};

test('restore accepts exact safety recovery while preserving assignments, review and writer hold',()=>{
 const a=before(),b=recovered(a);assert.deepEqual(compareRestoredRows(a,b),{pausedTeams:1,uncertainSends:1});
 assert.deepEqual(a,before());
 assert.deepEqual(compareRestoredRows(b,b),{pausedTeams:0,uncertainSends:0});
});
test('restore refuses a missing pause, an unsafe resend, or invented writer retirement',()=>{
 const a=before();assert.throws(()=>compareRestoredRows(a,a));
 for(const mutate of [b=>b.workroom_automation[0].state='active',b=>b.workroom_sends[0].state='prepared',b=>b.workroom_local_sessions[0].writerQuiescence=1]){
  const b=recovered(a);mutate(b);assert.throws(()=>compareRestoredRows(a,b));
 }
});
test('restore refuses changed task content, send identity, scope, review, revision, or table rows',()=>{
 const a=before();
 for(const mutate of [b=>b.tasks[0].title='lost',b=>b.workroom_automation[0].workerSendId='replacement',b=>b.workroom_automation[0].revision++,b=>b.workroom_sends[0].payload='broader scope',b=>b.workroom_progress[0].decision='approved',b=>b.tasks.pop(),b=>delete b.workroom_local_sessions]){
  const b=recovered(a);mutate(b);assert.throws(()=>compareRestoredRows(a,b));
 }
});
