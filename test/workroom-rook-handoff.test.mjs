import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtempSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {DatabaseSync} from 'node:sqlite';
import {openTaskStore} from '../lib/task-store.mjs';
import {createIntakeRunner} from '../lib/workroom-flow.mjs';
import {createTeamRunner} from '../lib/workroom-automation.mjs';
import {createRookRuntime} from '../lib/workroom-rook.mjs';
const agents=[{id:'echo',backend:'hermes',conversation_id:'fixture-echo',status:'idle'},
  {id:'nims',backend:'codex',conversation_id:'mesh-nims',status:'idle'}];
function setup(){
  const filename=join(mkdtempSync(join(tmpdir(),'mesh-rook-handoff-')),'tasks.sqlite');
  const store=openTaskStore(filename);
  const task=store.create({title:'Fixture request',description:'Only a synthetic scoped file'});
  return {filename,store,task};
}
test('claim revision is checked after the roster read; edited card causes a question and no dispatch',async()=>{
 const f=setup();let release,sends=0;
 try{
  f.store.workroom.flow.enqueue(f.task.id);
  const intake=createIntakeRunner({workroom:f.store.workroom,root:process.cwd(),relay:{agents:()=>new Promise(r=>release=r)},
   sendTaskHandoff:async()=>{sends++;},syncTaskReplies:async()=>{}});
  const tick=intake();let t=f.store.workroom.get(f.task.id);
  f.store.workroom.saveProgress(t.id,{goal:'Changed after claim',checklist:[],result:'',evidence:'',reviewer:'',decision:'pending',
   revision:t.progress.revision,taskRevision:t.revision,briefRevision:t.workroom.revision});
  release(agents);await tick;
  t=f.store.workroom.get(t.id);assert.equal(sends,0);assert.equal(t.flow.state,'clarification');
  assert.match(t.flow.question,/changed after assignment/);assert.equal(t.messages.length,0);
 }finally{f.store.close();}
});

test('another unproven writer holds intake even when its automation is no longer active',async()=>{
 const f=setup();let sends=0;
 try{
  f.store.workroom.flow.enqueue(f.task.id);
  const intake=createIntakeRunner({workroom:{...f.store.workroom,list:()=>[{id:'old',messages:[{id:'old-send',phase:'work',state:'accepted'}]}]},
   root:process.cwd(),relay:{agents:async()=>agents},sendTaskHandoff:async()=>{sends++;},syncTaskReplies:async()=>{}});
  await intake();assert.equal(sends,0);assert.equal(f.store.workroom.get(f.task.id).flow.state,'queued');
 }finally{f.store.close();}
});

for(const reviewerId of ['nims','dsh'])test('aged Rook claim uses the qualified Nims reviewer only: '+reviewerId,async()=>{
 const f=setup(),sends=[],replies=new Map(),notices=[];let rook,runner;
 try{
  const db=new DatabaseSync(f.filename);db.prepare('UPDATE tasks SET createdAt=? WHERE id=?').run('2020-01-01T00:00:00Z',f.task.id);db.close();
  const relay={agents:async()=>agents,taskMessage:async b=>{
   sends.push(b);const t=f.store.workroom.get(f.task.id);let report,label;
   if(b.text.includes('Phase: plan\n')){label='workroom-assignment';report={schema:label+'/v1',taskId:t.id,sendId:b.id,
    spec:'Implement the scoped fixture',workspace:process.cwd(),allowedFiles:'public/fixture.mjs',checks:'node --check public/fixture.mjs',
    boundaries:'Only the named fixture',workerId:'echo',reviewerId};}
   else if(b.text.includes('Phase: work\n')){label='workroom-update';report={schema:label+'/v1',taskId:t.id,sendId:b.id,goal:t.progress.goal,
    checklist:t.progress.checklist.map(s=>({...s,status:'done'})),result:'Built fixture',evidence:'Synthetic check passed'};}
   else{label='workroom-review';report={schema:label+'/v1',taskId:t.id,sendId:b.id,verdict:'approved',summary:'Independent fixture review',evidence:'Synthetic review check'};}
   replies.set(b.id,'```'+label+'\n'+JSON.stringify(report)+'\n```');
  },nativeRead:async p=>p.includes('capabilities')?{taskSessionBinding:1}:{messages:sends.flatMap(s=>[
   {id:s.id,k:'you',t:s.text},{id:s.id+'-reply',k:'ag',t:replies.get(s.id)}])}};
  rook=createRookRuntime({store:f.store.workroom.rook,flow:f.store.workroom.flow,board:()=>f.store.workroom.list(),enabled:true,
   identity:{id:'rook',approvalRef:'synthetic'},verifyIdentity:()=>true,schedule:()=>1,cancel:()=>{},
   transport:{send:async r=>{notices.push(r);return {id:r.id,accepted:true};},lookup:async id=>({id,accepted:true})}});
  rook.start();assert.equal((await rook.tick()).status,'claimed');
  const claim=f.store.workroom.get(f.task.id).flow.claim;
  runner=createTeamRunner({workroom:f.store.workroom,relay,root:process.cwd(),intervalMs:600000,simpleFlow:true});
  for(let i=0;i<12;i++)await runner.tick();
  await rook.tick();
  const t=f.store.workroom.get(f.task.id);
  if(reviewerId!=='nims'){
   assert.equal(t.flow.state,'clarification');assert.notEqual(t.workroom.stage,'done');assert.equal(sends.length,1);
   assert.equal(notices.filter(n=>n.kind==='needs_input').length,1);return;
  }
  assert.equal(t.workroom.stage,'done',t.flow.question);assert.equal(t.progress.decision,'approved');
  assert.equal(t.flow.claim.claimId,claim.claimId);assert.equal(sends[0].id,claim.dispatchId);
  assert.equal(sends.length,3);assert.deepEqual(sends.map(s=>s.agentId),['nims','echo','nims']);
  assert.notEqual(t.flow.ownerDecision,'accepted');
  assert.equal(notices.filter(n=>n.kind==='claim_saved').length,1);
  assert.equal(notices.filter(n=>n.kind==='ready_for_review').length,1);
  assert.equal(f.store.workroom.flow.scheduledSweep(Date.now()+5*60*60*1000).status,'blocked');
 }finally{await rook?.close();await runner?.close();f.store.close();}
});
