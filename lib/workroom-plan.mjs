import {createHash} from 'node:crypto';
import {TaskError} from './task-store.mjs';

export function initializePlans(db){
  db.exec(`CREATE TABLE IF NOT EXISTS workroom_plans (
    taskId TEXT PRIMARY KEY REFERENCES tasks(id), lead TEXT NOT NULL,
    spec TEXT NOT NULL DEFAULT '', workspace TEXT NOT NULL DEFAULT '',
    allowedFiles TEXT NOT NULL DEFAULT '', checks TEXT NOT NULL DEFAULT '',
    boundaries TEXT NOT NULL DEFAULT '', workerId TEXT NOT NULL DEFAULT '',
    reviewerId TEXT NOT NULL DEFAULT '', state TEXT NOT NULL DEFAULT 'draft',
    fingerprint TEXT NOT NULL DEFAULT '', revision INTEGER NOT NULL DEFAULT 0,
    lockedAt TEXT);`);
}
const id=value=>typeof value==='string'&&/^[A-Za-z0-9_-]{1,100}$/.test(value);
function fingerprint(task,plan){
  return createHash('sha256').update(JSON.stringify([
    task.title,task.description,task.workroom.project,task.workroom.criteria,
    task.workroom.owner,task.workroom.team,task.progress.goal,
    task.progress.checklist.map(({id,text})=>({id,text})),
    plan.lead,plan.spec,plan.workspace,plan.allowedFiles,plan.checks,
    plan.boundaries,plan.workerId,plan.reviewerId
  ])).digest('hex');
}
export function readPlan(db,task){
  const row=db.prepare('SELECT * FROM workroom_plans WHERE taskId=?').get(task.id);
  if(!row)return null;
  return {...row,state:row.state==='locked'&&row.fingerprint!==fingerprint(task,row)?'stale':row.state};
}
export function savePlan(db,get,taskId,body){
  const fields=['spec','workspace','allowedFiles','checks','boundaries','workerId','reviewerId'];
  const keys=[...fields,'lead','state','revision','taskRevision','briefRevision','progressRevision'];
  if(!body||Object.keys(body).sort().join(',')!==keys.sort().join(',')||
    !['nims','echo'].includes(body.lead)||!['draft','locked'].includes(body.state)||
    fields.some(key=>typeof body[key]!=='string'||body[key].length>4000||body[key].includes('\0'))||
    !Number.isSafeInteger(body.revision)||body.revision<0||
    [body.taskRevision,body.briefRevision,body.progressRevision].some(v=>!Number.isSafeInteger(v)||v<0))throw new TaskError(400,'Invalid plan proposal.');
  if(body.workerId&&!id(body.workerId)||body.reviewerId&&!id(body.reviewerId))throw new TaskError(400,'Choose valid worker identities.');
  db.exec('BEGIN IMMEDIATE;');
  try{
    const task=get(taskId),previous=readPlan(db,task);
    if((previous?.revision??0)!==body.revision||task.revision!==body.taskRevision||task.workroom.revision!==body.briefRevision||task.progress.revision!==body.progressRevision)throw new TaskError(409,'Task or plan changed. Reload before saving the plan.');
    if(task.status==='done'||task.progress.decision==='approved')throw new TaskError(409,'Reopen the task before changing its plan.');
    if(task.workroom.owner!==body.lead)throw new TaskError(409,'Save the selected project lead on the card first.');
    if(body.state==='locked'&&(!task.description.trim()||!task.workroom.criteria.trim()||!task.progress.goal.trim()||!task.progress.checklist.length||
      ['spec','workspace','allowedFiles','checks','boundaries'].some(key=>!body[key].trim())||!body.workerId||!body.reviewerId||body.workerId===body.reviewerId))throw new TaskError(400,'Locking needs a brief, goal, checklist, acceptance criteria, spec, workspace, files, checks, boundaries and different builder/reviewer.');
    const lockedAt=body.state==='locked'?new Date().toISOString():null;
    const hash=body.state==='locked'?fingerprint(task,body):'';
    db.prepare(`INSERT INTO workroom_plans VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(taskId) DO UPDATE SET
      lead=excluded.lead,spec=excluded.spec,workspace=excluded.workspace,allowedFiles=excluded.allowedFiles,checks=excluded.checks,
      boundaries=excluded.boundaries,workerId=excluded.workerId,reviewerId=excluded.reviewerId,state=excluded.state,
      fingerprint=excluded.fingerprint,revision=excluded.revision,lockedAt=excluded.lockedAt`)
      .run(taskId,body.lead,...fields.map(key=>body[key]),body.state,hash,body.revision+1,lockedAt);
    db.prepare('INSERT INTO workroom_events(taskId,kind,detail,at) VALUES(?,?,?,?)').run(taskId,body.state==='locked'?'scope_locked':'plan_proposed',
      body.state==='locked'?`Scope locked by owner action; lead ${body.lead}, builder ${body.workerId}, reviewer ${body.reviewerId}. No agent started.`:'Plan proposal saved; no work authorized or started.',new Date().toISOString());
    db.exec('COMMIT;');return {task:get(taskId)};
  }catch(error){db.exec('ROLLBACK;');throw error;}
}
export function assertPlanDispatch(task,agentId,phase,expectedRevision){
  if(!task.plan||!['work','review'].includes(phase))return;
  if(task.plan.state!=='locked')throw new TaskError(409,'Lock the current scope and team before sending work or review.');
  if(expectedRevision!==undefined&&task.plan.revision!==expectedRevision)throw new TaskError(409,'The frozen handoff belongs to an older plan. Inspect it before a new request.');
  if(agentId!==(phase==='review'?task.plan.reviewerId:task.plan.workerId))throw new TaskError(409,'Use the builder/reviewer selected in the locked plan, or revise the plan first.');
}
export function planBrief(plan){
  return plan?`\nPlan revision: ${plan.revision} (${plan.state})\nLead: ${plan.lead}\nSpec: ${plan.spec}\nAllowed workspace: ${plan.workspace}\nAllowed files: ${plan.allowedFiles}\nRequired local checks: ${plan.checks}\nBoundaries/non-goals: ${plan.boundaries}\nBuilder: ${plan.workerId}\nIndependent reviewer: ${plan.reviewerId}\n`:'';
}
