import {DatabaseSync,backup} from 'node:sqlite';
import {mkdir,copyFile,readFile,writeFile} from 'node:fs/promises';
import {join,resolve} from 'node:path';
import {createHash} from 'node:crypto';
import {openCodexRequestStore} from './codex-request-store.mjs';

// Preserve the committed WAL and every unresolved request. Never replay a receipt.
export async function backupCodexRequests(source,directory){
  source=resolve(source);directory=resolve(directory);await mkdir(directory);
  const snapshot=join(directory,'codex-requests.sqlite'),restored=join(directory,'restore-rehearsal.sqlite');
  const live=new DatabaseSync(source,{readOnly:true});
  try{await backup(live,snapshot);}finally{live.close();}
  const rows=file=>{const db=new DatabaseSync(file,{readOnly:true});try{
    if(db.prepare('PRAGMA integrity_check').get().integrity_check!=='ok')throw Error('Native receipt backup integrity failed.');
    return db.prepare('SELECT * FROM codex_requests ORDER BY request_id').all();
  }finally{db.close();}};
  const expected=rows(snapshot);
  await copyFile(snapshot,restored,1);
  const store=openCodexRequestStore(restored);store.close();
  if(JSON.stringify(rows(restored))!==JSON.stringify(expected))throw Error('Native receipt restore changed saved delivery state.');
  const receipt={schema:'onoes-mesh-codex-receipt-backup/v1',snapshot,restored,count:expected.length,
    sha256:createHash('sha256').update(await readFile(snapshot)).digest('hex'),restore:'PASS',
    note:'Metadata only. Keep the current live receipt journal when restoring older app/task data. Never overwrite newer receipts or treat missing history as permission to resend.'};
  await writeFile(join(directory,'receipt.json'),JSON.stringify(receipt,null,2),{flag:'wx'});
  return receipt;
}
