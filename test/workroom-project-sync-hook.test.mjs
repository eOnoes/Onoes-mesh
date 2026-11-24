import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtempSync,rmSync} from 'node:fs';
import {join} from 'node:path';
import {tmpdir} from 'node:os';
import {DatabaseSync} from 'node:sqlite';
import {openTaskStore} from '../lib/task-store.mjs';
import {createWorkroomProjectSyncCandidate} from '../integrations/workroom-project-sync-candidate.mjs';

export const approval={projectId:'project-A',approvalRef:'synthetic-owner-policy',fields:['title','stage','goal','owner','result','blocker']};

function fixture(t,{approveCreation=null,failCapture=false}={}) {
  const dir=mkdtempSync(join(tmpdir(),'mesh-sync-hook-'));const file=join(dir,'tasks.sqlite');
  let controller,db;
  const store=openTaskStore(file,{projectSyncFactory:context=>{
    db=context.db;
    controller=createWorkroomProjectSyncCandidate(context,{storeId:'synthetic-store',initialize:true,approveCreation});
    return {capture:(...args)=>{const result=controller.capture(...args);if(failCapture)throw Error('synthetic capture failure');return result;}};
  }});
  t.after(()=>{store.close();rmSync(dir,{recursive:true,force:true});});
  return {store,controller,db,file};
}
function card(store,owner='nims') {return store.create({title:'Synthetic card',description:'PRIVATE text excluded',label:'',status:'open',owner});}
function brief(store,id,fields={}) {const t=store.workroom.get(id);return store.workroom.save(id,{project:'synthetic',criteria:'',owner:'nims',team:'local_build',stage:'ready',revision:t.workroom.revision,...fields});}
function progress(store,id,fields={}){const t=store.workroom.get(id),p=t.progress;return store.workroom.saveProgress(id,{goal:'Shared goal',checklist:[],result:'',evidence:'PRIVATE free-form evidence',reviewer:'',decision:'pending',revision:p.revision,taskRevision:t.revision,briefRevision:t.workroom.revision,...fields});}

test('default app opens and saves with no sync schema or shared data',t=>{
  const dir=mkdtempSync(join(tmpdir(),'mesh-sync-off-'));const file=join(dir,'tasks.sqlite');const store=openTaskStore(file);
  t.after(()=>{store.close();rmSync(dir,{recursive:true,force:true});});
  card(store);const db=new DatabaseSync(file);try{assert.equal(db.prepare("SELECT count(*) n FROM sqlite_schema WHERE name LIKE 'mind_project_%'").get().n,0);}finally{db.close();}
});

test('real create/edit/stage/progress methods capture only explicitly linked cards',t=>{
  const f=fixture(t);const c=card(f.store);
  assert.equal(f.controller.outbox.status(c.id).length,0);
  f.controller.link({...approval,cardId:c.id});
  f.store.update(c.id,{title:'Updated title',description:c.description,label:'',status:'open',revision:c.revision});
  brief(f.store,c.id,{stage:'working',owner:'echo'});
  progress(f.store,c.id,{result:'Synthetic result'});
  const rows=f.db.prepare('SELECT payload FROM mind_project_outbox ORDER BY sequence').all().map(r=>JSON.parse(r.payload));
  assert.deepEqual(rows.map(r=>r.kind),['created','progress','stage_changed','progress']);
  assert.equal(rows[2].snapshot.owner,'echo');assert.equal(rows[3].snapshot.goal,'Shared goal');
  assert.equal(rows[3].snapshot.result,'Synthetic result');
  assert.ok(rows.every(r=>!JSON.stringify(r).includes('PRIVATE')));
});

test('selected new-card policy captures within real create and rollback removes both',t=>{
  const f=fixture(t,{approveCreation:()=>approval});const c=card(f.store);
  assert.equal(f.controller.outbox.status(c.id).length,1);
  const g=fixture(t,{approveCreation:()=>approval,failCapture:true});
  assert.throws(()=>card(g.store),/capture failure/);
  assert.equal(g.store.list().length,0);
  assert.equal(g.db.prepare('SELECT count(*) n FROM mind_project_outbox').get().n,0);
  assert.equal(g.db.prepare('SELECT count(*) n FROM mind_project_links').get().n,0);
});

test('capture failure rolls back actual task update and Workroom stage save',t=>{
  const f=fixture(t);const c=card(f.store);f.controller.link({...approval,cardId:c.id});
  f.db.exec("CREATE TRIGGER fail_sync BEFORE INSERT ON mind_project_outbox BEGIN SELECT RAISE(ABORT,'synthetic outbox unavailable'); END");
  assert.throws(()=>f.store.update(c.id,{title:'Not saved',description:c.description,label:'',status:'open',revision:c.revision}));
  assert.equal(f.store.get(c.id).title,c.title);
  assert.throws(()=>brief(f.store,c.id,{stage:'working'}));
  assert.equal(f.store.workroom.get(c.id).workroom.stage,'backlog');
  assert.equal(f.controller.outbox.status(c.id).length,1);
});

test('stale revision and withdrawn sharing cannot create new events',t=>{
  const f=fixture(t);const c=card(f.store);f.controller.link({...approval,cardId:c.id});
  f.store.update(c.id,{title:'First edit',description:c.description,label:'',status:'open',revision:c.revision});
  assert.throws(()=>f.store.update(c.id,{title:'Stale edit',description:c.description,label:'',status:'open',revision:c.revision}));
  f.controller.withdraw(c.id);brief(f.store,c.id,{stage:'working'});
  assert.equal(f.controller.outbox.status(c.id).length,2);
  assert.ok(f.controller.outbox.status(c.id).every(r=>r.reason==='sharing_withdrawn'));
});

test('field approval excludes goal/result and Relay text stays unshared by default',t=>{
  const f=fixture(t);const c=card(f.store);
  f.controller.link({...approval,fields:['title','stage'],cardId:c.id});progress(f.store,c.id,{result:'PRIVATE result'});
  const rows=f.db.prepare('SELECT payload FROM mind_project_outbox').all();
  assert.ok(rows.every(r=>!r.payload.includes('PRIVATE')&&!r.payload.includes('Shared goal')));
  const relay=f.store.linkRelay({scope:'relay:mesh',conversationId:'00000000-0000-0000-0000-000000000001',messageId:'message-1',text:'PRIVATE Relay chat'});
  assert.equal(f.controller.outbox.status(relay.taskId).length,0);
});

test('one card edit saves the whole answer and one shared snapshot, or rolls it all back',t=>{
  const f=fixture(t);
  const c=card(f.store);
  f.controller.link({...approval,cardId:c.id});
  const original=f.store.workroom.get(c.id);
  const brief={project:'Print',criteria:'Check the 95 mm tray',owner:'echo',stage:'working',team:'local_build',revision:original.workroom.revision};
  const progress={goal:'Use 95 mm',checklist:[],result:'',evidence:'',reviewer:'',decision:'pending',revision:original.progress.revision,taskRevision:original.revision,briefRevision:original.workroom.revision};
  const count=()=>f.controller.outbox.status(c.id).length;
  const before=count();
  assert.throws(()=>f.store.workroom.save(c.id,brief,{...progress,checklist:[{}]}),/checklist step/);
  assert.deepEqual(f.store.workroom.get(c.id),original);
  assert.equal(count(),before);
  const saved=f.store.workroom.save(c.id,brief,progress);
  assert.equal(saved.workroom.criteria,brief.criteria);
  assert.equal(saved.progress.goal,progress.goal);
  assert.equal(count(),before+1);
  const snapshot=JSON.parse(f.db.prepare('SELECT payload FROM mind_project_outbox ORDER BY sequence DESC LIMIT 1').get().payload);
  assert.equal(snapshot.kind,'stage_changed');
  assert.equal(snapshot.snapshot.goal,progress.goal);
  assert.equal(snapshot.snapshot.stage,'working');
  assert.throws(()=>f.store.workroom.save(c.id,brief,progress),e=>e.status===409);
  assert.equal(count(),before+1);
});

test('Done keeps plan/review gates and captures combined status change once',t=>{
  const f=fixture(t);const c=card(f.store);f.controller.link({...approval,cardId:c.id});
  brief(f.store,c.id,{stage:'working',criteria:'Guide exists'});
  const steps=[{id:'guide',text:'Write guide',status:'done'}];
  progress(f.store,c.id,{checklist:steps,result:'Guide written'});
  const before=f.controller.outbox.status(c.id).length;
  assert.throws(()=>brief(f.store,c.id,{stage:'done',criteria:'Guide exists'}));
  assert.equal(f.controller.outbox.status(c.id).length,before);
  const tsk=f.store.workroom.get(c.id);
  f.store.workroom.savePlan(c.id,{lead:'nims',state:'locked',spec:'Write guide',workspace:'C:/synthetic',
    allowedFiles:'GUIDE.md',checks:'Read guide',boundaries:'Docs only',workerId:'echo',reviewerId:'nims',
    revision:tsk.plan.revision,taskRevision:tsk.revision,briefRevision:tsk.workroom.revision,progressRevision:tsk.progress.revision});
  progress(f.store,c.id,{checklist:steps,result:'Guide written',reviewer:'nims',decision:'approved'});
  const approvedCount=f.controller.outbox.status(c.id).length;
  brief(f.store,c.id,{stage:'done',criteria:'Guide exists'});
  assert.equal(f.store.get(c.id).status,'done');
  assert.equal(f.controller.outbox.status(c.id).length,approvedCount+1);
  let last=JSON.parse(f.db.prepare('SELECT payload FROM mind_project_outbox ORDER BY sequence DESC LIMIT 1').get().payload);
  assert.equal(last.kind,'completed');assert.equal(last.snapshot.stage,'done');
  progress(f.store,c.id,{checklist:steps,result:'Guide written',decision:'changes_requested'});
  assert.equal(f.store.get(c.id).status,'open');
  assert.equal(f.controller.outbox.status(c.id).length,approvedCount+2);
  last=JSON.parse(f.db.prepare('SELECT payload FROM mind_project_outbox ORDER BY sequence DESC LIMIT 1').get().payload);
  assert.equal(last.kind,'blocked');assert.equal(last.snapshot.stage,'needs_you');
});
