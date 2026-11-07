import test from 'node:test';
import assert from 'node:assert/strict';
import {DatabaseSync} from 'node:sqlite';
import {readFileSync} from 'node:fs';
import {createHash} from 'node:crypto';
import {nemotronAdapterHash,validateNemotronQualification,readNemotronQualification,saveNemotronQualification} from '../lib/nemotron-qualification.mjs';
import {NEMOTRON_MODEL} from '../lib/model-operation-store.mjs';
test('qualification requires every lifecycle check, current source, and intact saved record',()=>{
  const root=process.cwd(),db=new DatabaseSync(':memory:');assert.equal(readNemotronQualification(db,root),null);
  const record={schemaVersion:'mesh-nemotron-qualification/v1',modelId:NEMOTRON_MODEL,adapterSha256:nemotronAdapterHash(root),executableSha256:'a'.repeat(64),supervisorSha256:'b'.repeat(64),moduleSha256:createHash('sha256').update(readFileSync('lib/supervisor_mesh_control.py')).digest('hex'),createdAt:new Date().toISOString(),checks:Object.fromEntries(['load','unload','chat','cancel','restart','lostResponse','gpuMapping','sourceBinding'].map(k=>[k,true]))};
  for(const key of Object.keys(record.checks))assert.throws(()=>validateNemotronQualification({...record,checks:{...record.checks,[key]:false}},root),/incomplete or stale/);
  assert.throws(()=>validateNemotronQualification({...record,adapterSha256:'0'.repeat(64)},root),/incomplete or stale/);
  saveNemotronQualification(db,record,root);assert.equal(readNemotronQualification(db,root).source,'qualified_native');
  db.prepare('UPDATE model_qualification SET payload=?').run('{}');assert.throws(()=>readNemotronQualification(db,root),/changed/);db.close();
});
