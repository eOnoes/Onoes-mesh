export function createPlanEditor({task,agents,onSave,document}){
  const el=(tag,text)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;return n;};
  const plan=task.plan;
  const section=el('details');section.className='workroom-plan';section.open=Boolean(plan&&plan.state!=='locked');
  section.append(el('summary','Plan, scope and team · '+(plan?.state||'optional for this historical task')));
  section.append(el('p',`Scope: ${plan?.state||'not enrolled (historical task)'}. ${plan?.lockedAt?'Last lock: '+plan.lockedAt+'. ':''}Saving or locking starts no agent and does not approve the finished work.`));
  if(plan?.state==='stale')section.append(el('p','The saved brief, goal, checklist text or lead changed. Review the proposal and lock the new scope before another handoff.'));
  if(!plan)section.append(el('p','This historical task keeps its original workflow. Saving a proposal enrolls it in the scope-lock workflow.'));
  const form=el('form');section.append(form);const inputs={};
  for(const [key,label] of [['spec','Proposed spec / outcome'],['workspace','Allowed workspace'],['allowedFiles','Allowed files / areas'],['checks','Required local checks'],['boundaries','Boundaries and non-goals']]){
    const wrap=el('label',label),input=el('textarea');input.rows=key==='workspace'?2:3;input.maxLength=4000;input.value=plan?.[key]||'';wrap.append(input);form.append(wrap);inputs[key]=input;
  }
  for(const [key,label] of [['workerId','Proposed builder'],['reviewerId','Proposed independent reviewer']]){
    const wrap=el('label',label),select=el('select');select.setAttribute('aria-label',label);
    const options=[['','Choose a connected peer'],...agents.filter(a=>a.conversation_id&&(['hermes','a2a'].includes(a.backend)||(key==='reviewerId'&&a.backend==='codex'))).map(a=>[a.id,a.name||a.id])];
    if(plan?.[key]&&!options.some(([id])=>id===plan[key]))options.push([plan[key],plan[key]+' (not currently connected)']);
    for(const [value,name] of options){const option=el('option',name);option.value=value;select.append(option);}select.value=plan?.[key]||'';wrap.append(select);form.append(wrap);inputs[key]=select;
  }
  form.append(el('p','A connected peer is not proof of coding tools or repository access. Confirm those capabilities in the scoped request; the existing permission checks still apply. Builder and reviewer must differ.'));
  const values=()=>Object.fromEntries(Object.entries(inputs).map(([key,input])=>[key,input.value]));
  const original=JSON.stringify(values());
  const basis={revision:plan?.revision??0,taskRevision:task.revision,briefRevision:task.workroom.revision,progressRevision:task.progress.revision};
  const save=el('button','Save plan proposal');save.type='submit';
  const lock=el('button','Lock scope and team');lock.type='button';
  const notice=el('p');notice.setAttribute('role','status');
  const submit=state=>onSave({...values(),...basis,lead:task.workroom.owner,state});
  form.addEventListener('submit',e=>{e.preventDefault();submit('draft');});
  lock.addEventListener('click',()=>submit('locked'));
  for(const input of Object.values(inputs))input.addEventListener('input',()=>{notice.textContent=JSON.stringify(values())!==original?'Unsaved plan changes. Save or lock the proposal before sending a handoff.':'';});
  form.append(save,lock,notice);
  if(!['nims','echo'].includes(task.workroom.owner)||task.status==='done'||task.progress.decision==='approved'){
    save.disabled=true;lock.disabled=true;section.append(el('p','Select Nims/Echo on an open, unapproved card before revising its plan.'));
  }
  return {node:section,isDirty:()=>JSON.stringify(values())!==original};
}


export function scopedTeamStatus(plan,policy){
  if(policy?.schema!=='mesh-team-policy/v1'||typeof policy.workspace!=='string'||!policy.workspace||!Array.isArray(policy.builderIds)||!Array.isArray(policy.reviewerIds)||policy.actionLimit!==50)return {matches:false,message:'Automatic team policy unavailable. Refresh before starting or resuming.'};
  const same=typeof plan?.workspace==='string'&&plan.workspace.replace(/\\/g,'/').replace(/\/+$/,'').toLowerCase()===policy.workspace.replace(/\\/g,'/').replace(/\/+$/,'').toLowerCase();
  const roles=policy.builderIds.includes(plan?.workerId)&&policy.reviewerIds.includes(plan?.reviewerId)&&plan?.workerId!==plan?.reviewerId;
  return {matches:same&&roles,message:`Automatic team workspace: ${policy.workspace}. Builder: Echo. Independent reviewer: Deep or Nims. Limit: ${policy.actionLimit} transitions. ${!same?'This plan names a different workspace; it is not qualified for automatic work.':!roles?'The selected builder/reviewer pair is not qualified for this automatic lane.':'Saved scope matches this lane; current connections, task revisions and review checks still apply.'}`};
}
