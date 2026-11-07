import test from 'node:test';
import assert from 'node:assert/strict';
import {DatabaseSync} from 'node:sqlite';
import {mkdtempSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {randomUUID} from 'node:crypto';
import {createModelOperationStore,NEMOTRON_MODEL,nativeCommandFingerprint} from '../lib/model-operation-store.mjs';
const binding=()=>({modelId:NEMOTRON_MODEL,bootId:randomUUID(),moduleSha256:'a'.repeat(64),supervisorSha256:'e'.repeat(64),command:{id:randomUUID(),action:'load',expected:'b'.repeat(64)}});
function envelope(b,state='ACCEPTED'){
  return {schemaVersion:'mesh-supervisor-control/v1',moduleSha256:b.moduleSha256,supervisorSha256:b.supervisorSha256,bootId:b.bootId,modelId:b.modelId,
    receipt:{id:b.command.id,action:b.command.action,fingerprint:nativeCommandFingerprint(b.command),state,
      readBackVerified:state==='COMPLETED',ownerCallStarted:['RUNNING','COMPLETED'].includes(state)}};
}
function fixture(){const filename=join(mkdtempSync(join(tmpdir(),'mesh-model-ops-')),'tasks.sqlite');const db=new DatabaseSync(filename);return {filename,db,store:createModelOperationStore(db)};}
test('a persisted reservation is never a second dispatch permission after replay or app restart',()=>{
  const f=fixture(),b=binding();assert.equal(f.store.reserve(b).created,true);assert.equal(f.store.reserve(b).created,false);
  f.db.close();const db=new DatabaseSync(f.filename),s=createModelOperationStore(db);
  assert.equal(s.reserve(b).created,false);assert.equal(s.get(b.command.id).state,'PREPARED');assert.equal(s.unresolved().length,1);
  assert.throws(()=>s.reserve(binding()),/prior model operation/);db.close();
});
test('lost response remains unresolved; only the same code/boot/command receipt can recover it',()=>{
  const f=fixture(),b=binding();f.store.reserve(b);f.store.unknown(b.command.id);
  for(const mutate of [e=>e.bootId=randomUUID(),e=>e.moduleSha256='c'.repeat(64),e=>e.receipt.id=randomUUID(),e=>e.receipt.fingerprint='d'.repeat(64),e=>e.modelId='other']){
    const e=envelope(b);mutate(e);assert.throws(()=>f.store.record(b.command.id,e),/does not match/);
  }
  assert.equal(f.store.unresolved().length,1);f.store.record(b.command.id,envelope(b,'RUNNING'));
  assert.equal(f.store.get(b.command.id).state,'RUNNING');assert.throws(()=>f.store.reserve(binding()));
  f.store.record(b.command.id,envelope(b,'COMPLETED'));assert.equal(f.store.unresolved().length,0);
  assert.equal(f.store.reserve(binding()).created,true);f.db.close();
});
test('bindings and final receipts are immutable; semantic duplicates do not add audit noise',()=>{
  const f=fixture(),b=binding();f.store.reserve(b);
  assert.throws(()=>f.store.reserve({...b,command:{...b.command,action:'unload'}}),/different binding/);
  const done=envelope(b,'COMPLETED');f.store.record(b.command.id,done);const before=f.store.get(b.command.id);
  f.store.record(b.command.id,{receipt:{...done.receipt},modelId:done.modelId,bootId:done.bootId,moduleSha256:done.moduleSha256,supervisorSha256:done.supervisorSha256,schemaVersion:done.schemaVersion});
  assert.deepEqual(f.store.get(b.command.id),before);
  assert.throws(()=>f.store.record(b.command.id,envelope(b,'REFUSED')),/cannot be rewritten/);
  assert.deepEqual(f.store.unknown(b.command.id),before);f.db.close();
});
test('an app UNKNOWN is not a native terminal outcome; stale accepted receipts cannot undo running',()=>{
  const f=fixture(),b=binding();f.store.reserve(b);f.store.record(b.command.id,envelope(b,'RUNNING'));
  f.store.unknown(b.command.id,'APP_RESTART');assert.equal(f.store.unresolved().length,1);
  assert.throws(()=>f.store.record(b.command.id,envelope(b)),/backwards/);
  f.store.record(b.command.id,envelope(b,'RUNNING'));assert.equal(f.store.unresolved().length,1);
  const unknown=envelope(b,'UNKNOWN');unknown.receipt.ownerCallStarted=true;unknown.receipt.reason='MODEL_READBACK_UNVERIFIED';
  f.store.record(b.command.id,unknown);assert.equal(f.store.unresolved().length,0);
  assert.equal(f.store.get(b.command.id).state,'UNKNOWN');assert.equal(f.store.get(b.command.id).envelope.receipt.readBackVerified,false);
  assert.throws(()=>f.store.record(b.command.id,envelope(b,'RUNNING')),/cannot be rewritten/);f.db.close();
});
test('strict schemas reject private/unexpected fields and contradictory success before recording',()=>{
  const f=fixture(),b=binding();
  assert.throws(()=>f.store.reserve({...b,prompt:'private'}),/Invalid fixed/);f.store.reserve(b);
  for(const e of [{...envelope(b),prompt:'private'},{...envelope(b),receipt:{...envelope(b).receipt,prompt:'private'}},
    {...envelope(b,'COMPLETED'),receipt:{...envelope(b,'COMPLETED').receipt,readBackVerified:false}},
    {...envelope(b),receipt:{...envelope(b).receipt,ownerCallStarted:true}}])assert.throws(()=>f.store.record(b.command.id,e));
  assert.equal(f.store.get(b.command.id).envelope,null);f.db.close();
});
test('two connections serialize the machine-wide reservation and retain recovery evidence',()=>{
  const f=fixture(),b=binding(),db=new DatabaseSync(f.filename),s=createModelOperationStore(db);
  f.store.reserve(b);assert.equal(s.reserve(b).created,false);assert.throws(()=>s.reserve(binding()));
  f.store.unknown(b.command.id);f.store.unknown(b.command.id);
  assert.equal(s.get(b.command.id).events.length,2);assert.equal(s.get(b.command.id).events[1].source,'app_observation');
  db.close();f.db.close();
});
