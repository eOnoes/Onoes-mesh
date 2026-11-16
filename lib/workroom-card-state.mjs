// Read-only card state, shared by the normal UI and explicit owner preparation.
import {createHash} from 'node:crypto';
import {readPlan} from './workroom-plan.mjs';

export function readWorkroomProgress(db,id){
  const row=db.prepare('SELECT * FROM workroom_progress WHERE taskId=?').get(id);
  return row?{...row,checklist:JSON.parse(row.checklist)}:{goal:'',checklist:[],result:'',evidence:'',reviewer:'',decision:'pending',revision:0,reviewFingerprint:'',reviewedAt:null};
}

export function workroomBriefFingerprint(task,meta){
  return createHash('sha256').update(JSON.stringify([task.title,task.description,meta.project,meta.criteria,meta.owner,meta.team])).digest('hex');
}

export function readWorkroomCardState(db,task){
  const meta=db.prepare('SELECT * FROM workroom_tasks WHERE taskId=?').get(task.id);
  const saved=meta?{...meta,stage:task.status==='done'?'done':meta.stage==='done'?'backlog':meta.stage}:{project:'',criteria:'',owner:'',team:'local_build',stage:task.status==='done'?'done':'backlog',revision:0};
  const progress=readWorkroomProgress(db,task.id);
  // Preserve the existing order: plan validity precedes derived review/stage.
  const plan=readPlan(db,{...task,workroom:saved,progress});
  if(progress.decision==='approved'&&progress.reviewFingerprint!==workroomBriefFingerprint(task,saved))progress.decision='stale';
  if(saved.stage==='done'&&progress.decision!=='approved')saved.stage='needs_you';
  return {workroom:saved,progress,plan};
}
