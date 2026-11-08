import {randomUUID} from 'node:crypto';
import {resolve,relative,isAbsolute} from 'node:path';
import {TaskError} from './task-store.mjs';
import {existsSync,realpathSync} from 'node:fs';
import {dirname} from 'node:path';
import {backlogEligibility,writerQuiescenceBlockers} from './workroom-claim-policy.mjs';

const SWEEP_INTERVAL_MS=5*60*60*1000;

export function createFlowStore(db,get,listTasks=()=>[]){
 db.exec(`CREATE TABLE IF NOT EXISTS workroom_flow(taskId TEXT PRIMARY KEY REFERENCES tasks(id),state TEXT NOT NULL,question TEXT NOT NULL,askedAt TEXT,ownerDecision TEXT NOT NULL,ownerNote TEXT NOT NULL,ownerAt TEXT,revision INTEGER NOT NULL,sendId TEXT NOT NULL,progressRevision INTEGER NOT NULL);`);
 db.exec(`CREATE TABLE IF NOT EXISTS workroom_claims(claimId TEXT PRIMARY KEY,taskId TEXT NOT NULL REFERENCES tasks(id),dispatchId TEXT NOT NULL UNIQUE,trigger TEXT NOT NULL,claimedAt TEXT NOT NULL,createdAt TEXT NOT NULL,intendedLead TEXT NOT NULL,taskRevision INTEGER NOT NULL,briefRevision INTEGER NOT NULL,progressRevision INTEGER NOT NULL,flowRevision INTEGER NOT NULL);`);
 db.exec(`CREATE TABLE IF NOT EXISTS workroom_sweep_state(id INTEGER PRIMARY KEY CHECK(id=1),lastScheduledAt TEXT,lastTaskId TEXT NOT NULL DEFAULT '',lastResult TEXT NOT NULL DEFAULT 'never');`);
 db.prepare("INSERT OR IGNORE INTO workroom_sweep_state(id,lastScheduledAt,lastTaskId,lastResult) VALUES(1,NULL,'','never')").run();
 const read=id=>{const row=db.prepare('SELECT * FROM workroom_flow WHERE taskId=?').get(id);if(!row)return row;const claim=db.prepare('SELECT * FROM workroom_claims WHERE taskId=? ORDER BY rowid DESC LIMIT 1').get(id);return {...row,...(claim?{claim}: {})};};
 const event=(id,kind,detail)=>db.prepare('INSERT INTO workroom_events(taskId,kind,detail,at) VALUES(?,?,?,?)').run(id,kind,detail,new Date().toISOString());
 function ensure(id){db.prepare("INSERT OR IGNORE INTO workroom_flow VALUES(?,'idea','',NULL,'pending','',NULL,0,'',0)").run(id);}
 function queue(id,trigger){const t=get(id);if(t.status==='done')throw new TaskError(409,'Completed cards cannot be queued. Request changes first.');ensure(id);const old=read(id);if(['queued','planning','working'].includes(old.state))return old;const dispatchId=randomUUID();db.prepare('INSERT INTO workroom_claims VALUES(?,?,?,?,?,?,?,?,?,?,?)').run(randomUUID(),id,dispatchId,trigger,new Date().toISOString(),t.createdAt,t.workroom.owner||'nims',t.revision,t.workroom.revision,t.progress.revision,old.revision);db.prepare("UPDATE workroom_flow SET state='queued',question='',askedAt=NULL,sendId=?,revision=revision+1 WHERE taskId=?").run(dispatchId,id);event(id,'triage_queued','Agent will inspect the request and either establish scope or ask a specific question.');return read(id);}
 function transaction(fn){if(db.isTransaction)return fn();db.exec('BEGIN IMMEDIATE;');try{const value=fn();db.exec('COMMIT;');return value;}catch(error){db.exec('ROLLBACK;');throw error;}}
 function scheduledSweep(at=Date.now()){
  if(!Number.isSafeInteger(at)||!Number.isFinite(new Date(at).getTime()))throw new TaskError(400,'Invalid scheduled sweep time.');
  const stamp=new Date(at).toISOString();
  return transaction(()=>{
   const previous=db.prepare('SELECT * FROM workroom_sweep_state WHERE id=1').get();
   if(previous.lastScheduledAt){const last=Date.parse(previous.lastScheduledAt);if(!Number.isFinite(last)||at-last<SWEEP_INTERVAL_MS)return {status:'not_due',lastScheduledAt:previous.lastScheduledAt,lastResult:previous.lastResult};}
   const finish=(result,lastTaskId='')=>{db.prepare('UPDATE workroom_sweep_state SET lastScheduledAt=?,lastTaskId=?,lastResult=? WHERE id=1').run(stamp,lastTaskId,result.status);return {...result,lastScheduledAt:stamp};};
   const tasks=listTasks();
   const blockers=writerQuiescenceBlockers(tasks);
   if(blockers.length){const reason=blockers.some(item=>item.reason==='writer_quiescence_unproven')?'writer_quiescence_unproven':'active_team';return finish({status:'blocked',reason,blockers});}
   const eligible=tasks.filter(task=>backlogEligibility(task,at).eligible).sort((a,b)=>Date.parse(a.createdAt)-Date.parse(b.createdAt)||a.id.localeCompare(b.id));
   if(!eligible.length)return finish({status:'empty'});
   const task=eligible[0];const flow=queue(task.id,'aged');event(task.id,'watcher_claimed','Five-hour sweep claimed this twelve-hour-old request before dispatch.');
   return finish({status:'claimed',taskId:task.id,flow},task.id);
  });
 }
 function sweepStatus(){const row=db.prepare('SELECT * FROM workroom_sweep_state WHERE id=1').get();return {schedulerInstalled:false,schedulerEnabled:false,lastScheduledAt:row.lastScheduledAt,lastTaskId:row.lastTaskId||null,lastResult:row.lastResult};}
 return {read,enqueue:id=>transaction(()=>queue(id,'manual')),
  claim(id,body){if(!body||Object.keys(body).sort().join(',')!=='briefRevision,progressRevision,revision,taskRevision'||Object.values(body).some(v=>!Number.isSafeInteger(v)||v<0))throw new TaskError(400,'Invalid board claim.');return transaction(()=>{const t=get(id);if(t.revision!==body.taskRevision||t.workroom.revision!==body.briefRevision||t.progress.revision!==body.progressRevision||(t.flow?.revision??0)!==body.revision)throw new TaskError(409,'Card changed before assignment.');const blockers=writerQuiescenceBlockers(listTasks());if(blockers.length)throw new TaskError(409,'Workspace writer quiescence is unproven; reconcile the original writer before assigning another card.');const eligibility=backlogEligibility(t);if(!eligibility.eligible)throw new TaskError(409,eligibility.reason);const claimed=queue(id,'aged');event(id,'watcher_claimed','Five-hour watcher claimed this twelve-hour-old request before dispatch.');return claimed;});},
  scheduledSweep,
  sweepStatus,
  pending:()=>db.prepare("SELECT * FROM workroom_flow WHERE state IN ('queued','planning') ORDER BY rowid").all(),
  planning(id){db.prepare("UPDATE workroom_flow SET state='planning',revision=revision+1 WHERE taskId=? AND state='queued'").run(id);},
  working(id){ensure(id);db.prepare("UPDATE workroom_flow SET state='working',question='',askedAt=NULL,revision=revision+1 WHERE taskId=?").run(id);},
  question(id,question,sendId=''){ensure(id);question=String(question).trim().slice(0,2000)||'Please add the intended outcome, workspace and how success should be checked.';db.prepare("UPDATE workroom_flow SET state='clarification',question=?,askedAt=?,sendId=?,revision=revision+1 WHERE taskId=?").run(question,new Date().toISOString(),sendId,id);event(id,'clarification_requested',question);},
  feedback(id,value,progressRevision){ensure(id);db.prepare("UPDATE workroom_flow SET ownerDecision=?,ownerNote=?,ownerAt=?,progressRevision=?,state=?,question='',askedAt=NULL,revision=revision+1 WHERE taskId=?").run(value.decision,value.note,new Date().toISOString(),progressRevision,value.decision==='accepted'?'accepted':'idea',id);event(id,value.decision==='accepted'?'owner_accepted':'owner_changes_requested',value.note||'Eddie accepted the completed result.');},
  failed(id,reason,sendId){ensure(id);db.prepare("UPDATE workroom_flow SET state='failed',question=?,sendId=?,revision=revision+1 WHERE taskId=?").run(String(reason).slice(0,2000),sendId,id);event(id,'worker_terminal_failure',String(reason).slice(0,2000));}
 };
}

export function createIntakeRunner({workroom,relay,root,sendTaskHandoff,syncTaskReplies,now,active=()=>true}){
 const contained=value=>{let candidate=resolve(value);const lexical=relative(resolve(root),candidate);if(!lexical||lexical.startsWith('..')||isAbsolute(lexical))return false;while(!existsSync(candidate)){const parent=dirname(candidate);if(parent===candidate)return false;candidate=parent;}const rel=relative(realpathSync(root),realpathSync(candidate));return !rel.startsWith('..')&&!isAbsolute(rel);};
 return async function tick(){
  if(!active())return;
  if(workroom.automation.active().length)return;
  const entry=workroom.flow.pending()[0];if(!entry)return;
  const current=()=>{const row=workroom.flow.read(entry.taskId);return active()&&row?.state===entry.state&&row.revision===entry.revision&&row.sendId===entry.sendId;};
  let t=workroom.get(entry.taskId);if(t.status==='done')return;
  try{
   const agents=await relay.agents();
   if(!current())return;t=workroom.get(t.id);
   if(entry.state==='queued'){
    if(t.plan?.state!=='locked'){
     const receipt=t.messages.find(m=>m.id===entry.sendId);
     if(receipt){if(receipt.state==='accepted')workroom.flow.planning(t.id);else workroom.flow.question(t.id,'The original planning delivery is '+receipt.state+'. Reconcile its saved receipt before retrying; no request was replayed.',entry.sendId);return;}
     const lead=agents.find(a=>a.id===(t.flow?.claim?.intendedLead||t.workroom.owner||'nims'));
     if(!lead?.conversation_id||!['idle','done'].includes(lead.status))return;
     if(!t.workroom.owner)t=workroom.save(t.id,{...Object.fromEntries(['project','criteria','team','stage','revision'].map(k=>[k,t.workroom[k]])),owner:lead.id});
     await sendTaskHandoff({workroom,taskId:t.id,body:{id:entry.sendId,agentId:lead.id,conversationId:lead.conversation_id,phase:'plan'},relay,admitted:current,allowUncertainReplay:false});
     if(current())workroom.flow.planning(t.id);return;
    }
   }else{
    const original=t.messages.find(m=>m.id===entry.sendId);if(!original||original.state!=='accepted'){workroom.flow.question(t.id,'The original planning delivery is uncertain. Inspect its saved receipt; it has not been reassigned.',entry.sendId);return;}
    await syncTaskReplies({workroom,taskId:t.id,relay,admitted:current,sendId:entry.sendId});if(!current())return;t=workroom.get(t.id);
    const run=workroom.nims.get(entry.sendId);if(run&&['failed','blocked','interrupted'].includes(run.state)){workroom.flow.question(t.id,'Planning could not finish. Inspect the original planning result before retrying.',entry.sendId);return;}
    const offer=t.assignments?.find(a=>a.sendId===entry.sendId);
    if(!offer){const reply=t.replies.filter(r=>r.sendId===entry.sendId).at(-1);if(reply)workroom.flow.question(t.id,t.agentUpdates.find(u=>u.sendId===entry.sendId)?.update.result||reply.text,entry.sendId);return;}
    const p=offer.proposal;
    const files=p.allowedFiles.split(/\r?\n/).map(x=>x.trim()).filter(Boolean);
    if(resolve(p.workspace).toLowerCase()!==resolve(root).toLowerCase()||!files.length||files.some(f=>!contained(resolve(p.workspace,f))||/(?:^|[\\/])(?:\.git|\.private|node_modules|data)(?:[\\/]|$)|\.github[\\/]workflows|(?:^|[\\/])\.env(?:\.|$)/i.test(f))||p.workerId!=='echo'||!['nims','dsh'].includes(p.reviewerId)){
     workroom.flow.question(t.id,'The proposed workspace/files or team need your confirmation. Automatic work is limited to the qualified Mesh checkout and its permitted source files.',entry.sendId);return;
    }
    t=workroom.applyAssignment(t.id,{sendId:offer.sendId,messageId:offer.messageId,hash:offer.hash,revision:t.plan?.revision??0,taskRevision:t.revision,briefRevision:t.workroom.revision,progressRevision:t.progress.revision}).task;
    if(!t.progress.goal.trim()||!t.progress.checklist.length){const report=t.agentUpdates.find(u=>u.sendId===entry.sendId)?.update;t=workroom.saveProgress(t.id,{goal:t.progress.goal||p.spec,checklist:report?.checklist?.length?report.checklist.map(s=>({...s,status:'pending'})):[{id:'build',text:'Implement the scoped request',status:'pending'},{id:'verify',text:'Run the stated checks and report evidence',status:'pending'}],result:'',evidence:'',reviewer:'',decision:'pending',revision:t.progress.revision,taskRevision:t.revision,briefRevision:t.workroom.revision});}
    if(!t.workroom.criteria.trim())t=workroom.save(t.id,{...Object.fromEntries(['project','owner','team','stage','revision'].map(k=>[k,t.workroom[k]])),criteria:p.checks});
    t=workroom.savePlan(t.id,{lead:t.workroom.owner||'nims',...Object.fromEntries(['spec','workspace','allowedFiles','checks','boundaries','workerId','reviewerId'].map(k=>[k,p[k]])),state:'locked',revision:t.plan.revision,taskRevision:t.revision,briefRevision:t.workroom.revision,progressRevision:t.progress.revision});
    t=t.task;
   }
   if(t.workroom.stage!=='working')t=workroom.save(t.id,{project:t.workroom.project,criteria:t.workroom.criteria,owner:t.workroom.owner||'nims',team:t.workroom.team,stage:'working',revision:t.workroom.revision});
   if(['paused','needs_review'].includes(t.automation?.state))t=workroom.automation.action(t.id,{action:'close',revision:t.automation.revision,planRevision:t.plan.revision,taskRevision:t.revision,briefRevision:t.workroom.revision,progressRevision:t.progress.revision},[],root).task;
   workroom.automation.action(t.id,{action:'start',revision:t.automation?.revision??0,planRevision:t.plan.revision,taskRevision:t.revision,briefRevision:t.workroom.revision,progressRevision:t.progress.revision},agents,root);
   workroom.flow.working(t.id);
  }catch(error){if(current())workroom.flow.question(t.id,error.message,entry.sendId);}
 };
}
