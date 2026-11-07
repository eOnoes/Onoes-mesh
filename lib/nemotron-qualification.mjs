import {createHash} from 'node:crypto';
import {readFileSync} from 'node:fs';
import {join} from 'node:path';
import {NEMOTRON_MODEL} from './model-operation-store.mjs';
const checks=['load','unload','chat','cancel','restart','lostResponse','gpuMapping','sourceBinding'];
const sha=value=>typeof value==='string'&&/^[a-f0-9]{64}$/.test(value);
export function nemotronAdapterHash(root){const digest=createHash('sha256');for(const name of ['model-operation-store.mjs','nemotron-client.mjs','nemotron-runtime.mjs','supervised-inference.mjs']){digest.update(name+'\0');digest.update(readFileSync(join(root,'lib',name)));}return digest.digest('hex');}
export function validateNemotronQualification(value,root){
  if(!value||Object.keys(value).sort().join(',')!=='adapterSha256,checks,createdAt,executableSha256,modelId,moduleSha256,schemaVersion,supervisorSha256'||value.schemaVersion!=='mesh-nemotron-qualification/v1'||value.modelId!==NEMOTRON_MODEL||
    ![value.adapterSha256,value.executableSha256,value.moduleSha256,value.supervisorSha256].every(sha)||value.adapterSha256!==nemotronAdapterHash(root)||
    value.moduleSha256!==createHash('sha256').update(readFileSync(join(root,'lib/supervisor_mesh_control.py'))).digest('hex')||
    typeof value.createdAt!=='string'||!Number.isFinite(Date.parse(value.createdAt))||!value.checks||Object.keys(value.checks).sort().join(',')!==checks.sort().join(',')||checks.some(key=>value.checks[key]!==true))throw Error('Nemotron lifecycle qualification is incomplete or stale');
  return Object.freeze({...value,source:'qualified_native'});
}
export function readNemotronQualification(db,root){
  if(!db.prepare("SELECT 1 FROM sqlite_master WHERE type='table' AND name='model_qualification'").get())return null;
  const row=db.prepare('SELECT payload,sha256 FROM model_qualification WHERE id=1').get();if(!row)return null;
  if(createHash('sha256').update(row.payload).digest('hex')!==row.sha256)throw Error('Model qualification record changed');
  return validateNemotronQualification(JSON.parse(row.payload),root);
}
export function saveNemotronQualification(db,value,root){
  validateNemotronQualification(value,root);const payload=JSON.stringify(value),hash=createHash('sha256').update(payload).digest('hex');
  db.exec('CREATE TABLE IF NOT EXISTS model_qualification(id INTEGER PRIMARY KEY CHECK(id=1),payload TEXT NOT NULL,sha256 TEXT NOT NULL)');
  db.prepare('INSERT INTO model_qualification(id,payload,sha256) VALUES(1,?,?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload,sha256=excluded.sha256').run(payload,hash);
}
