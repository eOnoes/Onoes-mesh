import test from 'node:test';
import assert from 'node:assert/strict';
import {DatabaseSync} from 'node:sqlite';
import {execFileSync} from 'node:child_process';
import {mkdtempSync,readFileSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {createHash,randomUUID} from 'node:crypto';
import {openTaskStore} from '../lib/task-store.mjs';
import {createModelOperationStore,NEMOTRON_MODEL,nativeCommandFingerprint} from '../lib/model-operation-store.mjs';
import {nemotronAdapterHash,saveNemotronQualification,readNemotronQualification} from '../lib/nemotron-qualification.mjs';

test('online backup and isolated application restore retain nonempty model operations and qualification byte for byte',()=>{
  const directory=mkdtempSync(join(tmpdir(),'mesh-model-backup-')),file=join(directory,'tasks.sqlite');
  openTaskStore(file).close();const db=new DatabaseSync(file),operations=createModelOperationStore(db);
  const binding={modelId:NEMOTRON_MODEL,bootId:randomUUID(),moduleSha256:'a'.repeat(64),supervisorSha256:'b'.repeat(64),command:{id:randomUUID(),action:'load',expected:'c'.repeat(64)}};
  operations.reserve(binding);operations.record(binding.command.id,{schemaVersion:'mesh-supervisor-control/v1',modelId:binding.modelId,bootId:binding.bootId,moduleSha256:binding.moduleSha256,supervisorSha256:binding.supervisorSha256,
    receipt:{id:binding.command.id,action:'load',fingerprint:nativeCommandFingerprint(binding.command),state:'ACCEPTED',ownerCallStarted:false,readBackVerified:false}});
  operations.unknown(binding.command.id);
  const qualification={schemaVersion:'mesh-nemotron-qualification/v1',modelId:NEMOTRON_MODEL,adapterSha256:nemotronAdapterHash(process.cwd()),executableSha256:'d'.repeat(64),supervisorSha256:'e'.repeat(64),moduleSha256:createHash('sha256').update(readFileSync('lib/supervisor_mesh_control.py')).digest('hex'),createdAt:new Date().toISOString(),checks:Object.fromEntries(['load','unload','chat','cancel','restart','lostResponse','gpuMapping','sourceBinding'].map(k=>[k,true]))};
  saveNemotronQualification(db,qualification,process.cwd());
  const tables=['model_operations','model_qualification'],rows=Object.fromEntries(tables.map(table=>[table,db.prepare('SELECT * FROM '+table+' ORDER BY rowid').all()]));
  // Keep the source connection open: the publisher must use SQLite online backup.
  const receipt=JSON.parse(execFileSync(process.execPath,['integrations/workroom-backup.mjs',file,join(directory,'snapshot')],{encoding:'utf8',windowsHide:true}));
  assert.equal(receipt.restore,'PASS');assert.equal(receipt.counts.model_operations,1);assert.equal(receipt.counts.model_qualification,1);
  const restored=new DatabaseSync(receipt.restored);
  try{for(const table of tables){assert.deepEqual(restored.prepare('SELECT * FROM '+table+' ORDER BY rowid').all(),rows[table]);assert.equal(receipt.durable[table],createHash('sha256').update(JSON.stringify(rows[table])).digest('hex'));}
    const recovered=createModelOperationStore(restored);assert.equal(recovered.unresolved().length,1);assert.equal(recovered.get(binding.command.id).state,'UNKNOWN');
    assert.equal(recovered.reserve(binding).created,false);assert.equal(readNemotronQualification(restored,process.cwd()).source,'qualified_native');
    for(const table of tables)assert.deepEqual(db.prepare('SELECT * FROM '+table+' ORDER BY rowid').all(),rows[table]);
  }finally{restored.close();db.close();}
});
