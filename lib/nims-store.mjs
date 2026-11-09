import {createHash} from 'node:crypto';
import {TaskError} from './task-store.mjs';
export function createNimsStore(db){
 db.exec(`CREATE TABLE IF NOT EXISTS nims_threads(taskId TEXT PRIMARY KEY REFERENCES tasks(id),threadId TEXT NOT NULL);
 CREATE TABLE IF NOT EXISTS nims_runs(sendId TEXT PRIMARY KEY REFERENCES workroom_sends(id),taskId TEXT NOT NULL REFERENCES tasks(id),payload TEXT NOT NULL,hash TEXT NOT NULL,state TEXT NOT NULL,threadId TEXT,turnId TEXT,text TEXT NOT NULL DEFAULT '',at TEXT NOT NULL,finishedAt TEXT);`);
 db.prepare("UPDATE nims_runs SET state='interrupted',text='Nims connection restarted. Inspect the original request; it was not replayed.' WHERE state IN ('prepared','running')").run();
 const get=id=>db.prepare('SELECT * FROM nims_runs WHERE sendId=?').get(id);
 return {get,list:()=>db.prepare('SELECT * FROM nims_runs ORDER BY at,sendId').all(),thread:taskId=>db.prepare('SELECT threadId FROM nims_threads WHERE taskId=?').get(taskId)?.threadId,
 reserve(body){
  const source=db.prepare("SELECT * FROM workroom_sends WHERE id=? AND agentId='nims'").get(body.id);
  if(!source||source.payload!==body.text||source.conversationId!==body.conversationId||!['plan','review'].includes(source.phase))throw new TaskError(409,'Nims accepts only the exact saved planning/review request.');
  const hash=createHash('sha256').update(body.text).digest('hex');db.exec('BEGIN IMMEDIATE;');
  try{const previous=get(body.id);if(previous){if(previous.hash!==hash)throw new TaskError(409,'Nims request identity changed.');db.exec('COMMIT;');return {run:previous,fresh:false};}
   if(db.prepare("SELECT 1 FROM nims_runs WHERE state IN ('prepared','running')").get())throw new TaskError(409,'Nims is busy. No second request started.');
   db.prepare("INSERT INTO nims_runs(sendId,taskId,payload,hash,state,at) VALUES(?,?,?,?,'prepared',?)").run(body.id,source.taskId,body.text,hash,new Date().toISOString());db.exec('COMMIT;');return {run:get(body.id),fresh:true};
  }catch(e){db.exec('ROLLBACK;');throw e;}
 },
 bind(sendId,{threadId,turnId}){if(!/^[A-Za-z0-9_-]{1,100}$/.test(threadId)||turnId&&!/^[A-Za-z0-9_-]{1,100}$/.test(turnId))throw new TaskError(400,'Invalid native Nims identity.');const run=get(sendId);if(!run||!['prepared','running'].includes(run.state))throw new TaskError(409,'Nims request is no longer active.');db.prepare("UPDATE nims_runs SET state='running',threadId=?,turnId=coalesce(?,turnId) WHERE sendId=?").run(threadId,turnId||null,sendId);db.prepare('INSERT INTO nims_threads VALUES(?,?) ON CONFLICT(taskId) DO UPDATE SET threadId=excluded.threadId').run(run.taskId,threadId);},
 recover(expected,text){
  if(!expected?.threadId||!expected.turnId||!['failed','interrupted'].includes(expected.state)||typeof text!=='string'||!text.trim()||text.length>262144)throw new TaskError(409,'Nims recovery requires an exact unresolved native turn.');
  const changed=db.prepare(`UPDATE nims_runs SET state='completed',text=?,finishedAt=? WHERE sendId=? AND taskId=? AND hash=? AND threadId=? AND turnId=? AND state=?
   AND EXISTS(SELECT 1 FROM workroom_sends s WHERE s.id=nims_runs.sendId AND s.taskId=nims_runs.taskId AND s.agentId='nims' AND s.conversationId='mesh-nims' AND s.state='accepted' AND s.phase IN ('plan','review') AND s.payload=nims_runs.payload)`)
   .run(text,new Date().toISOString(),expected.sendId,expected.taskId,expected.hash,expected.threadId,expected.turnId,expected.state).changes;
  const current=get(expected.sendId);
  if(changed!==1&&!(current?.state==='completed'&&current.taskId===expected.taskId&&current.hash===expected.hash&&current.threadId===expected.threadId&&current.turnId===expected.turnId&&current.text===text))throw new TaskError(409,'Nims recovery identity or state changed; inspect before retrying.');
  return current;
 },
 finish(sendId,state,text){if(!['completed','failed','blocked','interrupted'].includes(state))throw new TaskError(400,'Invalid Nims state');db.prepare("UPDATE nims_runs SET state=?,text=?,finishedAt=? WHERE sendId=? AND state IN ('prepared','running')").run(state,String(text).slice(0,262144),new Date().toISOString(),sendId);}
 };
}
