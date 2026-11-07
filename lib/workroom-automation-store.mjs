import {randomUUID} from 'node:crypto';
import {resolve} from 'node:path';
import {TaskError} from './task-store.mjs';
export function automationPolicy(root){return {schema:'mesh-team-policy/v1',workspace:resolve(root),builderIds:['echo'],reviewerIds:['dsh','nims'],actionLimit:50};}
export function createAutomationStore(db,get){
 db.exec(`CREATE TABLE IF NOT EXISTS workroom_automation(taskId TEXT PRIMARY KEY REFERENCES tasks(id),planRevision INTEGER NOT NULL,state TEXT NOT NULL,phase TEXT NOT NULL,workerSendId TEXT NOT NULL,reviewerSendId TEXT NOT NULL,workerConversation TEXT NOT NULL,reviewerConversation TEXT NOT NULL,operations INTEGER NOT NULL,revision INTEGER NOT NULL,reason TEXT NOT NULL,updatedAt TEXT NOT NULL);`);
 db.prepare("UPDATE workroom_automation SET state='paused',reason='Mesh restarted. Inspect and explicitly resume; no request was replayed.',revision=revision+1 WHERE state='active'").run();
 const read=id=>db.prepare('SELECT * FROM workroom_automation WHERE taskId=?').get(id);
 const event=(id,kind,detail)=>db.prepare('INSERT INTO workroom_events(taskId,kind,detail,at) VALUES(?,?,?,?)').run(id,kind,detail,new Date().toISOString());
 return {read,active:()=>db.prepare("SELECT * FROM workroom_automation WHERE state='active' ORDER BY updatedAt").all(),
 action(id,body,agents,root){
  if(!body||Object.keys(body).sort().join(',')!=='action,briefRevision,planRevision,progressRevision,revision,taskRevision'||!['start','resume','pause','close'].includes(body.action)||['revision','briefRevision','planRevision','progressRevision','taskRevision'].some(k=>!Number.isSafeInteger(body[k])||body[k]<0))throw new TaskError(400,'Invalid team action.');
  db.exec('BEGIN IMMEDIATE;');try{
   const t=get(id),old=read(id);if((old?.revision??0)!==body.revision||t.revision!==body.taskRevision||t.workroom.revision!==body.briefRevision||t.progress.revision!==body.progressRevision||t.plan?.revision!==body.planRevision)throw new TaskError(409,'Task, scope or team changed. Reload first.');
   if(body.action==='close'){if(!old||!['paused','needs_review'].includes(old.state))throw new TaskError(409,'Pause the team before closing its attempt.');event(id,'team_attempt_closed','Owner closed this attempt without canceling accepted agents: '+JSON.stringify(old));db.prepare("UPDATE workroom_automation SET state='closed',reason='Closed by owner; saved handoff receipts retained.',revision=revision+1,updatedAt=? WHERE taskId=?").run(new Date().toISOString(),id);}
   else if(body.action==='pause'){if(!old||old.state!=='active')throw new TaskError(409,'No active team to pause.');db.prepare("UPDATE workroom_automation SET state='paused',reason='Paused by owner. Already accepted agent work is not canceled.',revision=revision+1,updatedAt=? WHERE taskId=?").run(new Date().toISOString(),id);event(id,'team_paused','Next team steps paused. Already accepted work is not canceled.');}
   else{
    if(t.plan?.state!=='locked'||t.status==='done'||t.progress.decision==='approved')throw new TaskError(409,'Lock the current open task scope before starting a team.');
    const policy=automationPolicy(root);
    if(resolve(t.plan.workspace).toLowerCase()!==policy.workspace.toLowerCase())throw new TaskError(409,'Automatic teams are currently qualified only for this Mesh checkout. Other workspaces need their own qualification.');
    if(db.prepare("SELECT taskId FROM workroom_automation WHERE state='active' AND taskId<>?").get(id))throw new TaskError(409,'Another team is active. One writer per workspace.');
    const worker=agents.find(a=>a.id===t.plan.workerId),reviewer=agents.find(a=>a.id===t.plan.reviewerId);
    if(!policy.builderIds.includes(worker?.id)||!policy.reviewerIds.includes(reviewer?.id))throw new TaskError(409,'This automatic lane is qualified for Echo building and Deep/Nims reviewing. Other lanes need separate qualification.');
    if(!worker?.conversation_id||!reviewer?.conversation_id||!['hermes','a2a'].includes(worker.backend)||!['hermes','a2a','codex'].includes(reviewer.backend))throw new TaskError(409,'The saved builder/reviewer adapters are not connected and supported.');
    if(body.action==='resume'){
     if(!old||old.state!=='paused'||old.planRevision!==t.plan.revision||old.operations>=50)throw new TaskError(409,'This team cannot resume under the current plan/budget. Inspect it first.');
     if(old.workerConversation!==worker.conversation_id||old.reviewerConversation!==reviewer.conversation_id)throw new TaskError(409,'A saved agent conversation changed. Do not silently rebind.');
     db.prepare("UPDATE workroom_automation SET state='active',reason='',revision=revision+1,updatedAt=? WHERE taskId=?").run(new Date().toISOString(),id);
    }else{
     if(old&&['active','paused'].includes(old.state))throw new TaskError(409,'Inspect/resume the existing team rather than creating another run.');
     if(t.messages.some(m=>m.phase==='work'&&['prepared','unknown','accepted'].includes(m.state)&&!m.outcome&&!t.agentUpdates.some(u=>u.sendId===m.id&&u.applied)))throw new TaskError(409,'Resolve the existing worker attempt before starting another team.');
     db.prepare(`INSERT INTO workroom_automation VALUES(?,?,'active','worker',?,?,?,?,0,?,'',?) ON CONFLICT(taskId) DO UPDATE SET planRevision=excluded.planRevision,state=excluded.state,phase=excluded.phase,workerSendId=excluded.workerSendId,reviewerSendId=excluded.reviewerSendId,workerConversation=excluded.workerConversation,reviewerConversation=excluded.reviewerConversation,operations=0,revision=excluded.revision,reason='',updatedAt=excluded.updatedAt`).run(id,t.plan.revision,randomUUID(),randomUUID(),worker.conversation_id,reviewer.conversation_id,(old?.revision??0)+1,new Date().toISOString());
    }
    event(id,'team_started','Scoped worker → independent review enabled for plan '+t.plan.revision+'. No automatic approval or Done.');
   }
   db.exec('COMMIT;');return {task:get(id)};
  }catch(e){db.exec('ROLLBACK;');throw e;}
 },
 transition(id,revision,{state='active',phase,reason='',operation=false}){const old=read(id);if(!old||old.state!=='active'||old.revision!==revision)return false;const operations=old.operations+(operation?1:0);if(operations>=50){state='paused';reason='Team transition budget reached. Inspect the checkpoint.';}
  db.prepare('UPDATE workroom_automation SET state=?,phase=?,reason=?,operations=?,revision=revision+1,updatedAt=? WHERE taskId=? AND revision=?').run(state,phase||old.phase,String(reason).slice(0,500),operations,new Date().toISOString(),id,revision);
  if(state!=='active')event(id,'team_paused',reason);return true;
 }
 };
}
