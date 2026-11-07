// Agent state is live observation, never proof that a specific task ran.
export function handoffStatus(task,agents){
  const send=task.messages?.filter(m=>['plan','work','review'].includes(m.phase)).at(-1);
  if(!send)return null;
  if(send.nims&&['failed','blocked','interrupted'].includes(send.nims.state))return {label:'Nims '+send.nims.state,next:'This exact native request ended without a usable report. Inspect its replies/native identity; it was not replayed.'};
  if(['unknown','prepared'].includes(send.state))return {label:'Delivery uncertain',next:'Open Conversation and history and retry the original message identity. Do not send a new copy.'};
  if(send.state!=='accepted')return {label:'Delivery '+send.state,next:'Inspect the saved receipt before sending again.'};
  if(send.outcome && send.outcome.state!=='TASK_STATE_COMPLETED'){
    const state={TASK_STATE_CANCELED:'canceled',TASK_STATE_FAILED:'failed',TASK_STATE_REJECTED:'rejected'}[send.outcome.state]||'ended';
    return {label:`${send.phase==='review'?'Review':'Agent request'} ${state}`,next:'This exact attempt has a verified native outcome. Its accepted delivery receipt is preserved. Other Relay work is unchanged; check agent availability before a fresh handoff.'};
  }
  const review=task.agentReviews?.find(r=>r.sendId===send.id);
  const update=task.agentUpdates?.find(r=>r.sendId===send.id);
  if(review?.applied&&review.review?.verdict&&task.progress){
    if(task.progress.decision==='stale')return {label:'Review outdated',next:'The saved work changed. Request a fresh independent review before Done.'};
    if(task.progress.decision===review.review.verdict)return {label:review.review.verdict==='approved'?'Review approved':'Changes requested',next:review.review.verdict==='approved'?'The current review is approved. Moving to Done remains a deliberate action.':'Read the findings in Work timeline, correct the result, then request a fresh review.'};
  }
  if(review)return {label:review.applied?'Review recorded':'Review received',next:review.applied?'Inspect the verdict and current task before moving it.':'Inspect the evidence, then record this review.'};
  if(update)return {label:update.applied?'Worker report applied':'Agent report received',next:update.applied?'Inspect the saved result and request independent review.':'Inspect the report, then apply it to the checklist.'};
  if(send.outcome?.state==='TASK_STATE_COMPLETED')return {label:'Native request completed · no task report',next:'The native request ended, but no structured result is saved. Inspect replies before reviewing or finishing the task.'};
  const agent=agents?.find(a=>a.id===send.agentId && a.conversation_id===send.conversationId);
  if(!agent)return {label:'Agent unavailable',next:'Refresh the board or open Relay to check the connection. The accepted message is not resent.'};
  if(agent.approval)return {label:'Agent needs approval',next:'Open Relay to inspect the exact approval request. Approval has not been granted here.'};
  if(agent.status==='waiting')return {label:'Agent waiting',next:'Open Relay for the question or approval. If none is visible, the reason is unavailable; do not resend blindly.'};
  if(['stopped','stalled','failed'].includes(agent.status))return {label:'Agent '+agent.status,next:'Inspect Relay and refresh agent replies before deciding whether to retry.'};
  if(['idle','done'].includes(agent.status))return {label:'Agent '+agent.status+' · no task report',next:'Refresh agent replies. Agent status alone does not complete this task.'};
  return {label:'Agent '+(agent.status||'unknown'),next:'Follow agent replies for this task. Acceptance and live agent state do not prove completion.'};
}

// A read-only history assembled from saved facts, never inferred agent progress.
export function taskTimeline(task){
  const events=[];const sends=new Map((task.messages||[]).map(s=>[s.id,s]));
  const add=(id,at,label,detail,evidence='')=>{if(!events.some(e=>e.id===id))events.push({id,at,label,detail,evidence});};
  const replyAt=(send,report)=>{
    const finished=send.agentId==='nims'&&report.agentId==='nims'&&send.nims?.state==='completed'?send.nims.finishedAt:null;
    // Older adapter replies inherited the request time. Prefer the exact native
    // completion only when it supplies a valid later bound, never the wall clock.
    return typeof finished==='string'&&Number.isFinite(Date.parse(finished))&&
      (!Number.isFinite(Date.parse(report.at))||Date.parse(report.at)<Date.parse(finished)) ? finished : report.at;
  };
  for(const send of sends.values()){
    const label={plan:'Planning requested',work:'Worker assigned',review:'Independent review requested',message:'Message sent'}[send.phase]||'Message sent';
    add('send-'+send.id,send.at,label,`${send.agentId} · delivery ${send.state}. Delivery is not completion.`);
    if(send.nims)add('nims-'+send.id,send.nims.finishedAt||send.at,'Nims '+send.nims.state,'Task-bound read-only Codex request. Thread: '+(send.nims.threadId||'pending')+'; turn: '+(send.nims.turnId||'pending')+'. This is separate from task approval.');
    if(send.outcome)add('outcome-'+send.id,send.outcome.verifiedAt,'Native request '+(send.outcome.state==='TASK_STATE_COMPLETED'?'completed':send.outcome.state.replace('TASK_STATE_','').toLowerCase()),'Verified for this exact attempt; separate from the task review.');
  }
  for(const report of task.agentUpdates||[]){
    const send=sends.get(report.sendId);if(!send||send.state!=='accepted'||report.update?.taskId!==task.id||report.update?.sendId!==send.id)continue;
    const correction=send.phase==='work'&&(task.agentReviews||[]).some(r=>r.applied&&r.review?.taskId===task.id&&r.review?.sendId===r.sendId&&sends.get(r.sendId)?.phase==='review'&&r.review?.verdict==='changes_requested'&&Date.parse(r.at)<Date.parse(report.at));
    add('report-'+report.sendId+'-'+(report.hash||report.messageId),replyAt(send,report),send.phase==='plan'?'Plan received':correction?'Correction reported':'Worker report received',`${report.agentId} · ${report.applied?'applied to saved progress':'not applied'}. ${report.update.result||report.update.goal}`,report.update.evidence);
  }
  for(const report of task.agentReviews||[]){
    const send=sends.get(report.sendId);if(!send||send.phase!=='review'||send.state!=='accepted'||report.review?.taskId!==task.id||report.review?.sendId!==send.id)continue;
    add('review-'+report.sendId+'-'+(report.hash||report.messageId),replyAt(send,report),'Review received · '+(report.review.verdict==='approved'?'approved':'changes requested'),`${report.agentId} · ${report.applied?'recorded':'not recorded'}. ${report.review.summary}`,report.review.evidence);
  }
  for(const h of task.history||[]){
    const label={progress_saved:'Progress saved',team_attempt_closed:'Team attempt closed',team_started:'Scoped team started',team_paused:'Team paused / needs review',plan_proposed:'Plan proposed',scope_locked:'Scope and team locked',lead_selected:'Project lead selected',review_changes_requested:'Changes requested',review_approved:'Review approved',agent_update_applied:'Report applied',agent_review_applied:'Review recorded'}[h.kind]||(h.kind==='updated'?(/Stage: done[.;]/.test(h.detail)?'Moved to Done':'Card updated'):null);
    if(label)add('history-'+h.seq,h.at,label,h.detail);
  }
  return events.sort((a,b)=>(Date.parse(a.at)||0)-(Date.parse(b.at)||0)||a.id.localeCompare(b.id,undefined,{numeric:true}));
}
