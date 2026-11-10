import {DatabaseSync} from 'node:sqlite';
import {createHash} from 'node:crypto';

const restartReason='Mesh restarted. Inspect and explicitly resume; no request was replayed.';
const hash=value=>createHash('sha256').update(JSON.stringify(value)).digest('hex');

export function compareRestoredRows(before,after) {
  if(JSON.stringify(Object.keys(before).sort())!==JSON.stringify(Object.keys(after).sort()))
    throw Error('Restore changed the saved table set.');
  const recovery={pausedTeams:0,uncertainSends:0};
  for(const [table,rows] of Object.entries(before)) {
    const restored=after[table];
    if(!Array.isArray(restored)||rows.length!==restored.length)throw Error('Restore changed row count: '+table);
    for(let i=0;i<rows.length;i++) {
      const original=rows[i],actual=restored[i];
      if(JSON.stringify(original)===JSON.stringify(actual))continue;
      let expected=null;
      if(table==='workroom_automation'&&original.state==='active'&&Number.isSafeInteger(original.revision)) {
        expected={...original,state:'paused',reason:restartReason,revision:original.revision+1};
        if(JSON.stringify(expected)===JSON.stringify(actual))recovery.pausedTeams++;
      } else if(table==='workroom_sends'&&original.state==='prepared') {
        expected={...original,state:'unknown'};
        if(JSON.stringify(expected)===JSON.stringify(actual))recovery.uncertainSends++;
      }
      if(!expected||JSON.stringify(expected)!==JSON.stringify(actual))throw Error('Restored task or review provenance differs: '+table);
    }
  }
  // Recovery must happen, not merely be permitted. Active/prepared rows may not
  // survive startup and become eligible for a blind continuation or resend.
  for(const row of after.workroom_automation??[])if(row.state==='active')throw Error('Restored team did not pause.');
  for(const row of after.workroom_sends??[])if(row.state==='prepared')throw Error('Restored send was not held as uncertain.');
  return recovery;
}

function readSnapshot(filename) {
  const db=new DatabaseSync(filename,{readOnly:true});
  try {
    const tables=db.prepare("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name").all();
    return Object.fromEntries(tables.map(({name})=>[name,db.prepare('SELECT * FROM "'+name.replaceAll('"','""')+'" ORDER BY rowid').all()]));
  } finally {db.close();}
}

export function verifyBackupRestore(snapshot,restored) {
  const before=readSnapshot(snapshot),after=readSnapshot(restored);
  const recovery=compareRestoredRows(before,after);
  return {recovery,snapshotTables:Object.fromEntries(Object.entries(before).map(([k,v])=>[k,hash(v)])),
    restoredTables:Object.fromEntries(Object.entries(after).map(([k,v])=>[k,hash(v)]))};
}
