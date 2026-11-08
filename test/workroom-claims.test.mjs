import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtempSync} from 'node:fs';
import {join} from 'node:path';
import {tmpdir} from 'node:os';
import {DatabaseSync} from 'node:sqlite';
import {openTaskStore} from '../lib/task-store.mjs';
import {backlogEligibility} from '../lib/workroom-claim-policy.mjs';
import {createIntakeRunner} from '../lib/workroom-flow.mjs';

const at=Date.parse('2026-11-08T18:00:00Z');
const idea=()=>({id:'idea',createdAt:new Date(at-12*3600000).toISOString(),status:'open',workroom:{stage:'backlog',owner:''},progress:{decision:'pending'},messages:[],agentUpdates:[]});
test('scheduled claim requires original age, ownership and no saved claim or uncertainty',()=>{
 assert.equal(backlogEligibility(idea(),at).eligible,true);
 for(const createdAt of [new Date(at-12*3600000+1).toISOString(),new Date(at+1).toISOString(),'invalid'])assert.equal(backlogEligibility({...idea(),createdAt},at).eligible,false);
 for(const state of ['queued','planning','working','clarification','failed','accepted'])assert.equal(backlogEligibility({...idea(),flow:{state}},at).eligible,false,state);
 assert.equal(backlogEligibility({...idea(),flow:{state:'idea',claim:{claimId:'persisted'}}},at).eligible,false);
 assert.equal(backlogEligibility({...idea(),workroom:{stage:'backlog',owner:'echo'}},at).eligible,false);
 assert.equal(backlogEligibility({...idea(),messages:[{id:'uncertain',phase:'work',state:'unknown'}]},at).eligible,false);
 assert.equal(backlogEligibility({...idea(),workroom:{stage:'done',owner:''}},at).eligible,false);
});
test('cancelled and failed native receipts never turn an existing assignment into a fresh idea',()=>{
 for(const state of ['TASK_STATE_CANCELED','TASK_STATE_FAILED','TASK_STATE_REJECTED'])assert.equal(backlogEligibility({...idea(),flow:{state:'failed',sendId:'original'},messages:[{id:'original',phase:'work',state:'accepted',outcome:{state}}]},at).eligible,false);
});
test('atomic claim persists original basis and planned dispatch; second writer and restart cannot replace it',()=>{
 const path=join(mkdtempSync(join(tmpdir(),'mesh-claim-')),'tasks.sqlite');let a=openTaskStore(path),b;
 try{
  let t=a.create({title:'Claim fixture',description:'No live dispatch'});const db=new DatabaseSync(path);db.prepare('UPDATE tasks SET createdAt=? WHERE id=?').run('2020-01-01T00:00:00.000Z',t.id);db.close();
  t=a.workroom.get(t.id);const body={revision:0,taskRevision:t.revision,briefRevision:t.workroom.revision,progressRevision:t.progress.revision};b=openTaskStore(path);
  const claim=a.workroom.flow.claim(t.id,body);
  assert.equal(claim.claim.dispatchId,claim.sendId);assert.equal(claim.claim.trigger,'aged');assert.equal(claim.claim.createdAt,t.createdAt);assert.equal(claim.claim.taskRevision,t.revision);assert.equal(claim.claim.intendedLead,'nims');
  assert.throws(()=>b.workroom.flow.claim(t.id,body),/changed/);
  assert.equal(b.workroom.flow.read(t.id).claim.claimId,claim.claim.claimId);
  a.close();a=openTaskStore(path);assert.deepEqual(a.workroom.flow.read(t.id),claim);
  assert.equal(a.workroom.flow.enqueue(t.id).sendId,claim.sendId);
  assert.equal(a.workroom.get(t.id).messages.length,0);
  assert.equal(a.workroom.get(t.id).createdAt,t.createdAt);
 }finally{b?.close();a.close();}
});
test('bad claim body and stale task revision cannot create a claim',()=>{
 const s=openTaskStore(join(mkdtempSync(join(tmpdir(),'mesh-claim-stale-')),'tasks.sqlite'));
 try{const t=s.workroom.get(s.create({title:'Stale fixture',description:''}).id);assert.throws(()=>s.workroom.flow.claim(t.id,{revision:0,taskRevision:99,briefRevision:t.workroom.revision,progressRevision:0}),/changed/);assert.throws(()=>s.workroom.flow.claim(t.id,{revision:0,owner:'echo'}),/Invalid/);assert.equal(s.workroom.flow.read(t.id),undefined);}finally{s.close();}
});
test('manual lane move preserves Echo and saves its claim atomically; claim failure rolls the move back',()=>{
 const old=process.env.MESH_SIMPLE_FLOW;process.env.MESH_SIMPLE_FLOW='1';const path=join(mkdtempSync(join(tmpdir(),'mesh-manual-claim-')),'tasks.sqlite');const s=openTaskStore(path);
 try{
  const t=s.workroom.get(s.create({title:'Manual fixture',description:''}).id);const body={project:'Mesh',criteria:'One clear outcome',owner:'echo',team:'local_build',stage:'working',revision:t.workroom.revision};
  const db=new DatabaseSync(path);db.exec("CREATE TRIGGER reject_claim BEFORE INSERT ON workroom_claims BEGIN SELECT RAISE(ABORT,'fixture claim unavailable'); END;");
  assert.throws(()=>s.workroom.save(t.id,body),/fixture claim unavailable/);assert.deepEqual(s.workroom.get(t.id),t);
  db.exec('DROP TRIGGER reject_claim');db.close();
  const moved=s.workroom.save(t.id,body);assert.equal(moved.workroom.owner,'echo');assert.equal(moved.flow.claim.intendedLead,'echo');assert.equal(moved.flow.claim.trigger,'manual');assert.equal(moved.flow.claim.dispatchId,moved.flow.sendId);assert.equal(moved.createdAt,t.createdAt);
 }finally{s.close();if(old===undefined)delete process.env.MESH_SIMPLE_FLOW;else process.env.MESH_SIMPLE_FLOW=old;}
});
test('an unavailable claimed lead waits without substituting another agent',async()=>{
 const s=openTaskStore(join(mkdtempSync(join(tmpdir(),'mesh-claimed-lead-')),'tasks.sqlite'));
 try{const t=s.create({title:'Wait for assigned lead',description:''});const claim=s.workroom.flow.enqueue(t.id);let sends=0;
  const tick=createIntakeRunner({workroom:s.workroom,root:process.cwd(),relay:{agents:async()=>[{id:'echo',status:'idle',conversation_id:'echo'}]},sendTaskHandoff:async()=>{sends++;},syncTaskReplies:async()=>{}});
  await tick();assert.equal(sends,0);assert.equal(s.workroom.flow.read(t.id).state,'queued');assert.equal(s.workroom.flow.read(t.id).claim.dispatchId,claim.sendId);
 }finally{s.close();}
});
test('uncertain planning delivery keeps its original claim and asks for reconciliation without replay',async()=>{
 const s=openTaskStore(join(mkdtempSync(join(tmpdir(),'mesh-claim-uncertain-')),'tasks.sqlite'));
 try{const t=s.create({title:'Uncertain delivery fixture',description:''});const claim=s.workroom.flow.enqueue(t.id);s.workroom.flow.planning(t.id);let sends=0;
  const tick=createIntakeRunner({workroom:s.workroom,root:process.cwd(),relay:{agents:async()=>[]},sendTaskHandoff:async()=>{sends++;},syncTaskReplies:async()=>{throw Error('Must not sync a nonexistent receipt');}});
  await tick();await tick();const flow=s.workroom.flow.read(t.id);assert.equal(sends,0);assert.equal(flow.state,'clarification');assert.match(flow.question,/uncertain/);assert.equal(flow.claim.claimId,claim.claim.claimId);assert.equal(flow.claim.dispatchId,claim.sendId);assert.equal(flow.sendId,claim.sendId);
 }finally{s.close();}
});
