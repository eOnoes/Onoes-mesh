import test from 'node:test';
import assert from 'node:assert/strict';
import {randomUUID,createHash} from 'node:crypto';
import {mkdirSync,rmSync,statSync,realpathSync,readFileSync} from 'node:fs';
import {resolve,join} from 'node:path';
import {DatabaseSync} from 'node:sqlite';
import {openTaskStore} from '../lib/task-store.mjs';
import {readWorkroomCardState,workroomBriefFingerprint} from '../lib/workroom-card-state.mjs';
import {projectSnapshot} from '../integrations/workroom-project-sync-candidate.mjs';
import {initializeProjectOutbox,canonicalProjectEvent} from '../integrations/project-sync-outbox-candidate.mjs';
import {inspectProjectSource,prepareProjectSource,inspectProjectSourceAddition,prepareProjectSourceAddition}
  from '../integrations/project-sync-source-setup-candidate.mjs';

const hash=value=>createHash('sha256').update(canonicalProjectEvent(value)).digest('hex');
const copy=value=>JSON.parse(JSON.stringify(value));
function originalTables(filename){
  const db=new DatabaseSync(filename,{readOnly:true});
  try{
    return db.prepare("SELECT name FROM sqlite_schema WHERE type='table' AND name NOT LIKE 'mind_project_%' ORDER BY name").all()
      .map(({name})=>[name,copy(db.prepare('SELECT * FROM "'+name.replaceAll('"','""')+'"').all())]);
  }finally{db.close();}
}
function fixture(t,{cards=1,legacy=true}={}){
  const workspace=realpathSync(resolve('.')),dataDir='data/project-source-setup-'+randomUUID(),directory=join(workspace,dataDir);
  mkdirSync(directory);const filename=join(directory,'tasks.sqlite');
  t.after(()=>{assert.equal(resolve(directory).startsWith(join(workspace,'data')+'\\')||resolve(directory).startsWith(join(workspace,'data')+'/'),true);rmSync(directory,{recursive:true,force:true});});
  const store=openTaskStore(filename),ids=[];
  for(let i=0;i<cards;i++)ids.push(store.create({title:'Synthetic source '+i,description:'PRIVATE DESCRIPTION '+i}).id);
  store.create({title:'Unrelated card',description:'UNRELATED PRIVATE DATA'});store.close();
  const db=new DatabaseSync(filename);
  if(legacy)for(let i=0;i<8;i++)db.prepare('INSERT INTO workroom_sends(id,taskId,agentId,conversationId,text,fingerprint,state,at,payload) VALUES(?,?,?,?,?,?,?,?,?)')
    .run('legacy-'+i,ids[0],'echo','synthetic-conversation','PRIVATE CHAT','synthetic','prepared',new Date(0).toISOString(),'PRIVATE PAYLOAD');
  const links=ids.map(cardId=>{
    const task=db.prepare('SELECT * FROM tasks WHERE id=?').get(cardId);
    const fields=['title','goal','owner','stage','result','blocker'];
    const snapshot=projectSnapshot({...task,...readWorkroomCardState(db,task)},fields);
    return {cardId,projectId:'project-A',approvalRef:'fixture:owner-review',fields,revisions:snapshot.revisions,
      projectionSha256:hash({revisions:snapshot.revisions,snapshot:snapshot.snapshot})};
  });db.close();
  const stat=statSync(filename,{bigint:true});
  const plan={schema:'onoes-mesh-project-source-setup/v1',workspace,dataDir,
    source:{databasePath:realpathSync(filename),fileDevice:String(stat.dev),fileInode:String(stat.ino)},storeId:'synthetic-store',links};
  const approval=()=>({decision:'approve_exact_mesh_project_source_setup',planSha256:hash(plan)});
  return {filename,plan,approval,ids};
}

test('preview reads exact projection without schema, card, job or file changes',t=>{
  const f=fixture(t);const before=originalTables(f.filename),bytes=readFileSync(f.filename);
  const result=inspectProjectSource(f.plan);
  assert.equal(result.state,'unprepared');assert.equal(result.createsNothing,true);
  assert.deepEqual(originalTables(f.filename),before);assert.deepEqual(readFileSync(f.filename),bytes);
});

test('explicit setup atomically creates one baseline per card and preserves all existing rows',t=>{
  const f=fixture(t,{cards:2}),before=originalTables(f.filename);
  const first=prepareProjectSource(f.plan,f.approval());
  assert.equal(first.baselines.length,2);assert.equal(first.startsDelivery,false);
  assert.deepEqual(originalTables(f.filename),before);
  const recovered=inspectProjectSource(f.plan);assert.equal(recovered.state,'prepared');
  assert.deepEqual(recovered.baselines,first.baselines);
  assert.throws(()=>prepareProjectSource(f.plan,f.approval()));
  const db=new DatabaseSync(f.filename,{readOnly:true});
  try{
    assert.equal(db.prepare('SELECT count(*) AS n FROM mind_project_outbox').get().n,2);
    assert.equal(db.prepare("SELECT count(*) AS n FROM workroom_sends WHERE state='prepared'").get().n,8);
    const payloads=db.prepare('SELECT payload FROM mind_project_outbox').all();
    assert.doesNotMatch(JSON.stringify(payloads),/PRIVATE DESCRIPTION|PRIVATE CHAT|PRIVATE PAYLOAD|UNRELATED PRIVATE/);
  }finally{db.close();}
});

test('missing or mismatched approval refuses without modifying the database',t=>{
  const f=fixture(t),before=readFileSync(f.filename);
  for(const a of [undefined,{}, {decision:'approve_exact_mesh_project_source_setup',planSha256:'0'.repeat(64)},
    {decision:'approve_exact_shared_readonly_mind_enrollment_and_reader',planSha256:hash(f.plan)}])assert.throws(()=>prepareProjectSource(f.plan,a));
  assert.deepEqual(readFileSync(f.filename),before);
});

test('each stale revision and an unversioned changed projection refuse before schema creation',t=>{
  const f=fixture(t);
  for(const key of ['task','brief','progress']){
    const p=copy(f.plan);p.links[0].revisions[key]++;
    assert.throws(()=>prepareProjectSource(p,{decision:'approve_exact_mesh_project_source_setup',planSha256:hash(p)}));
  }
  const db=new DatabaseSync(f.filename);db.prepare('UPDATE tasks SET title=? WHERE id=?').run('Changed without revision',f.ids[0]);db.close();
  assert.throws(()=>prepareProjectSource(f.plan,f.approval()));
  const check=new DatabaseSync(f.filename,{readOnly:true});
  try{assert.equal(check.prepare("SELECT count(*) AS n FROM sqlite_schema WHERE name LIKE 'mind_project_%'").get().n,0);}finally{check.close();}
});

test('substituted file identity, widened fields and partial prior setup refuse',t=>{
  const f=fixture(t),before=readFileSync(f.filename);
  for(const change of [p=>p.source.fileInode='0',p=>p.links[0].fields.push('description'),p=>p.links.push(copy(p.links[0]))]){
    const p=copy(f.plan);change(p);assert.throws(()=>inspectProjectSource(p));
  }
  assert.deepEqual(readFileSync(f.filename),before);
  const db=new DatabaseSync(f.filename);db.exec('CREATE TABLE mind_project_capture_policy(cardId TEXT)');db.close();
  const partial=readFileSync(f.filename);assert.throws(()=>inspectProjectSource(f.plan));assert.throws(()=>prepareProjectSource(f.plan,f.approval()));
  assert.deepEqual(readFileSync(f.filename),partial);
});

test('failure at commit rolls back schema, policies and every baseline together',t=>{
  const f=fixture(t,{cards:2}),before=originalTables(f.filename),actual=DatabaseSync.prototype.exec;let fault=false;
  const mock=t.mock.method(DatabaseSync.prototype,'exec',function(sql){
    if(sql==='COMMIT'&&!fault){fault=true;throw Error('synthetic commit failure');}
    return actual.call(this,sql);
  });
  try{assert.throws(()=>prepareProjectSource(f.plan,f.approval()),e=>e.projectSourceOutcomeUnknown===true);}finally{mock.mock.restore();}
  assert.equal(fault,true);assert.deepEqual(originalTables(f.filename),before);
  assert.equal(inspectProjectSource(f.plan).state,'unprepared');
});

test('uncertain reply after actual commit is resolved by readback, never another baseline',t=>{
  const f=fixture(t),actual=DatabaseSync.prototype.exec;let fault=false;
  const mock=t.mock.method(DatabaseSync.prototype,'exec',function(sql){
    const result=actual.call(this,sql);
    if(sql==='COMMIT'&&!fault){fault=true;throw Error('synthetic lost commit acknowledgement');}
    return result;
  });
  try{assert.throws(()=>prepareProjectSource(f.plan,f.approval()),e=>e.projectSourceOutcomeUnknown===true);}finally{mock.mock.restore();}
  assert.equal(fault,true);const recovered=inspectProjectSource(f.plan);assert.equal(recovered.state,'prepared');
  assert.equal(recovered.baselines.length,1);assert.throws(()=>prepareProjectSource(f.plan,f.approval()));
  assert.deepEqual(inspectProjectSource(f.plan).baselines,recovered.baselines);
});

test('ordinary initialization cannot join a card transaction implicitly',t=>{
  const f=fixture(t),db=new DatabaseSync(f.filename);
  try{db.exec('BEGIN IMMEDIATE');assert.throws(()=>initializeProjectOutbox(db));db.exec('ROLLBACK');}
  finally{db.close();}
});

test('adding one reviewed card preserves existing sharing and reconciles a lost acknowledgement',t=>{
  const f=fixture(t,{cards:2}),[first,added]=f.plan.links;
  const original={...f.plan,links:[first]};
  const originalReceipt=prepareProjectSource(original,{decision:'approve_exact_mesh_project_source_setup',planSha256:hash(original)});
  added.projectId='3d-print-pilot';
  const preview=inspectProjectSourceAddition(f.plan,added.cardId);
  const decision={decision:'approve_exact_mesh_project_source_addition',addedCardId:added.cardId,planSha256:preview.planSha256};
  const before=originalTables(f.filename);
  assert.throws(()=>prepareProjectSourceAddition(f.plan,f.approval()));
  assert.throws(()=>prepareProjectSourceAddition(f.plan,{...decision,addedCardId:first.cardId}));
  const changed=copy(f.plan);
  changed.links[0].fields=['title','stage'];
  assert.throws(()=>prepareProjectSourceAddition(changed,{...decision,planSha256:hash(changed)}));
  const stale=copy(f.plan);
  stale.links[1].revisions.task++;
  assert.throws(()=>prepareProjectSourceAddition(stale,{...decision,planSha256:hash(stale)}));
  assert.deepEqual(inspectProjectSource(original).baselines,originalReceipt.baselines);
  const exec=DatabaseSync.prototype.exec;
  const lost=t.mock.method(DatabaseSync.prototype,'exec',function(sql){
    const result=exec.call(this,sql);
    if(sql==='COMMIT')throw Error('Lost acknowledgement');
    return result;
  });
  try{assert.throws(()=>prepareProjectSourceAddition(f.plan,decision),e=>e.projectSourceOutcomeUnknown===true);}
  finally{lost.mock.restore();}
  const recovered=inspectProjectSource(f.plan);
  assert.equal(recovered.baselines.length,2);
  assert.deepEqual(recovered.baselines[0],originalReceipt.baselines[0]);
  assert.equal(recovered.baselines[1].cardId,added.cardId);
  assert.throws(()=>prepareProjectSourceAddition(f.plan,decision));
  assert.deepEqual(inspectProjectSource(f.plan),recovered);
  assert.deepEqual(originalTables(f.filename),before);
});

test('readonly projection preserves the UI interpretation of stale approved Done cards',t=>{
  const f=fixture(t,{legacy:false}),db=new DatabaseSync(f.filename);
  try{
    const task=db.prepare('SELECT * FROM tasks WHERE id=?').get(f.ids[0]);
    db.prepare('INSERT INTO workroom_tasks VALUES(?,?,?,?,?,?,?)').run(task.id,'','','nims','local_build','done',1);
    const meta=db.prepare('SELECT * FROM workroom_tasks WHERE taskId=?').get(task.id);
    db.prepare('INSERT INTO workroom_progress VALUES(?,?,?,?,?,?,?,?,?,?)').run(task.id,'Shared goal','[]','','PRIVATE EVIDENCE','eddie','approved',1,workroomBriefFingerprint(task,meta),null);
    db.prepare("UPDATE tasks SET status='done' WHERE id=?").run(task.id);
    assert.equal(readWorkroomCardState(db,db.prepare('SELECT * FROM tasks WHERE id=?').get(task.id)).workroom.stage,'done');
    db.prepare('UPDATE tasks SET description=? WHERE id=?').run('Changed private brief',task.id);
    const current=readWorkroomCardState(db,db.prepare('SELECT * FROM tasks WHERE id=?').get(task.id));
    assert.equal(current.progress.decision,'stale');assert.equal(current.workroom.stage,'needs_you');
  }finally{db.close();}
});
