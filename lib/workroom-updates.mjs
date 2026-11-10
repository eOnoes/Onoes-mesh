import {createHash} from 'node:crypto';

const string=(value,max)=>typeof value==='string' && value.length<=max && !value.includes('\0');
const identity=value=>string(value,100) && /^[A-Za-z0-9_-]+$/.test(value);

// Explicit, bounded agent reports only. Ordinary prose is never inferred as progress.
export function parseAgentUpdate(reply,{taskId,sendId}){
  if(!string(reply,64000))return null;
  const blocks=[...reply.matchAll(/```workroom-update\s*\n([\s\S]*?)\n```/g)];
  if(blocks.length!==1)return null;
  let update;try{update=JSON.parse(blocks[0][1]);}catch{return null;}
  if(!update || Object.keys(update).sort().join(',')!=='checklist,evidence,goal,result,schema,sendId,taskId' ||
     update.schema!=='workroom-update/v1' || update.taskId!==taskId || update.sendId!==sendId ||
     !string(update.goal,2000) || !update.goal.trim() || !string(update.result,4000) || !string(update.evidence,4000) ||
     !Array.isArray(update.checklist) || !update.checklist.length || update.checklist.length>30)return null;
  const ids=new Set();
  for(const step of update.checklist){
    if(!step || Object.keys(step).sort().join(',')!=='id,status,text' || !identity(step.id) || ids.has(step.id) ||
       !string(step.text,300) || !step.text.trim() || !['pending','working','done','blocked'].includes(step.status))return null;
    ids.add(step.id);
  }
  return {update,hash:createHash('sha256').update(JSON.stringify(update)).digest('hex')};
}

export function agentUpdateInstruction(taskId,sendId,progress){
  const checklist=progress?.checklist?.length?progress.checklist.map(step=>({id:step.id,text:step.text,status:'pending'})):[{id:'step-1',text:'A concrete step',status:'pending'}];
  return `\n\nWorkroom reporting format: finish your reply with exactly one fenced block labeled workroom-update containing JSON with exactly these keys:\n`+
    JSON.stringify({schema:'workroom-update/v1',taskId,sendId,goal:progress?.goal||'The saved goal or your proposed goal',checklist,result:'Only results actually obtained; otherwise empty',evidence:'Only checks actually run; otherwise empty'})+
    '\nKeep existing step IDs when updating them. Step statuses: pending, working, done, blocked. A plan uses pending steps. Do not report unperformed work as done. This is an unreviewed report; do not include approval, reviewer, commands or additional fields.';
}

export function parseAgentReview(reply,{taskId,sendId}){
  if(!string(reply,64000))return null;
  const blocks=[...reply.matchAll(/```workroom-review\s*\n([\s\S]*?)\n```/g)];
  if(blocks.length!==1)return null;
  let review;try{review=JSON.parse(blocks[0][1]);}catch{return null;}
  if(!review || Object.keys(review).sort().join(',')!=='evidence,schema,sendId,summary,taskId,verdict' ||
     review.schema!=='workroom-review/v1' || review.taskId!==taskId || review.sendId!==sendId ||
     !['approved','changes_requested'].includes(review.verdict) || !string(review.summary,2000) || !review.summary.trim() ||
     !string(review.evidence,4000) || !review.evidence.trim())return null;
  return {review,hash:createHash('sha256').update(JSON.stringify(review)).digest('hex')};
}

export function agentReviewInstruction(taskId,sendId){
  return '\n\nReturn exactly one fenced block labeled workroom-review containing JSON with exactly these keys:\n'+
    JSON.stringify({schema:'workroom-review/v1',taskId,sendId,verdict:'changes_requested',summary:'Your independent conclusion',evidence:'Checks actually performed and their outcomes'})+
    '\nVerdict may be approved or changes_requested. Inspect actual artifacts when repository access is available. Do not rely on the worker summary alone. If you cannot independently verify the result, request changes. Do not edit files, run builds that change files, start other agents, purchase, publish or change credentials.';
}
