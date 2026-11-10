import {DatabaseSync,backup} from 'node:sqlite';
import {mkdirSync,copyFileSync,writeFileSync,readFileSync} from 'node:fs';
import {resolve,join,dirname} from 'node:path';
import {createHash,randomUUID} from 'node:crypto';
import {openTaskStore} from '../lib/task-store.mjs';
import {verifyBackupRestore} from '../lib/workroom-backup.mjs';

// SQLite online backup includes committed WAL data. Never copy a running DB file alone.
const source=resolve(process.argv[2]||'data/workroom-preview/tasks.sqlite');
const directory=process.argv[3]?resolve(process.argv[3]):resolve('data/workroom-backups',new Date().toISOString().replace(/[:.]/g,'-')+'-'+randomUUID());
mkdirSync(dirname(directory),{recursive:true});
mkdirSync(directory); // Immutable snapshot directory: never overwrite an existing backup.
const snapshot=join(directory,'tasks.sqlite');
const db=new DatabaseSync(source,{readOnly:true});
try{await backup(db,snapshot);}finally{db.close();}
function inspect(filename){
  const check=new DatabaseSync(filename,{readOnly:true});
  try{
    if(check.prepare('PRAGMA integrity_check').get().integrity_check!=='ok')throw Error('SQLite integrity check failed');
    if(check.prepare('PRAGMA foreign_key_check').all().length)throw Error('Foreign key check failed');
    const tables=check.prepare("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name").all();
    return Object.fromEntries(tables.map(({name})=>[name,check.prepare('SELECT count(*) AS n FROM "'+name.replaceAll('"','""')+'"').get().n]));
  }finally{check.close();}
}
const counts=inspect(snapshot);
function durableDigest(filename){
  const db=new DatabaseSync(filename,{readOnly:true});
  try{return Object.fromEntries(['tasks','workroom_tasks','workroom_progress','workroom_replies','workroom_update_applications','workroom_send_outcomes','workroom_plans','workroom_automation','nims_runs','nims_threads','model_operations','model_qualification'].map(table=>{const exists=db.prepare("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?").get(table);const rows=exists?db.prepare('SELECT * FROM '+table+' ORDER BY rowid').all():[];return [table,createHash('sha256').update(JSON.stringify(rows)).digest('hex')];}));}finally{db.close();}
}
const durable=durableDigest(snapshot);
const restored=join(directory,'restore-rehearsal.sqlite');
copyFileSync(snapshot,restored,1); // COPYFILE_EXCL: never replace a prior restore.
const store=openTaskStore(restored);
let taskCount;try{taskCount=store.workroom.list().length;}finally{store.close();}
const restoredCounts=inspect(restored);
const fidelity=verifyBackupRestore(snapshot,restored);
for(const [table,count] of Object.entries(counts))if(restoredCounts[table]!==count)throw Error('Restore changed row count: '+table);
const receipt={createdAt:new Date().toISOString(),source,snapshot,restored,sha256:createHash('sha256').update(readFileSync(snapshot)).digest('hex'),counts,durable,fidelity,taskCount,integrity:'ok',foreignKeys:'ok',restore:'PASS',note:'Restore opened through application migrations in isolated copy; all saved tables compared, allowing only exact startup safety pauses and prepared-send uncertainty. Live database was not replaced.'};
writeFileSync(join(directory,'receipt.json'),JSON.stringify(receipt,null,2));
console.log(JSON.stringify(receipt,null,2));
