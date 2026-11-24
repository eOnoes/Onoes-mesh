import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtempSync,rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join,resolve} from 'node:path';
import {spawnSync} from 'node:child_process';
import {openTaskStore} from '../lib/task-store.mjs';
import {createWorkroomProjectSyncCandidate} from '../integrations/workroom-project-sync-candidate.mjs';

for(const edit of ['title','combined'])for(const phase of ['before_commit','after_commit'])test(`owned card-process crash ${phase} preserves atomic ${edit} edit and outbox state`,t=>{
  const dir=mkdtempSync(join(tmpdir(),'mesh-sync-process-')),file=join(dir,'tasks.sqlite');let controller;
  let store=openTaskStore(file,{projectSyncFactory:context=>controller=createWorkroomProjectSyncCandidate(context,{storeId:'synthetic-store',initialize:true})});
  const card=store.create({title:'Original card',description:'Synthetic',label:'',status:'open',owner:'nims'});
  controller.link({cardId:card.id,projectId:'project-A',approvalRef:'synthetic-owner-policy',fields:['title','stage','goal']});
  const original=store.workroom.get(card.id);
  store.close();
  t.after(()=>rmSync(dir,{recursive:true,force:true}));
  const child=spawnSync(process.execPath,[resolve('test/project-sync-card-crash.mjs'),file,card.id,phase,edit],{windowsHide:true,timeout:15000,encoding:'utf8'});
  assert.equal(child.error,undefined);assert.equal(child.status,phase==='before_commit'?71:72,child.stderr);
  store=openTaskStore(file,{projectSyncFactory:context=>controller=createWorkroomProjectSyncCandidate(context,{storeId:'synthetic-store'})});
  try {
    if(edit==='combined'){
      const saved=store.workroom.get(card.id);
      assert.equal(saved.progress.goal,phase==='before_commit'?original.progress.goal:'Use a 95 mm tray');
      assert.equal(saved.workroom.criteria,phase==='before_commit'?original.workroom.criteria:'Measure the tray');
    }else assert.equal(store.get(card.id).title,phase==='before_commit'?'Original card':'Committed process update');
    assert.equal(controller.outbox.status(card.id).length,phase==='before_commit'?1:2);
    assert.ok(controller.outbox.status(card.id).every(row=>row.state==='pending'));
  } finally {store.close();}
});
