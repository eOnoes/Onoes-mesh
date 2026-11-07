import {sendTaskHandoff,syncTaskReplies} from './workroom.mjs';
export function createTeamRunner({workroom,relay,root,intervalMs=4000,now=()=>Date.now()}){
 let stopped=false,running=null;
 const current=a=>!stopped&&workroom.automation.read(a.taskId)?.state==='active'&&workroom.automation.read(a.taskId)?.revision===a.revision;
 const pause=(a,reason)=>workroom.automation.transition(a.taskId,a.revision,{state:'paused',reason});
 async function step(a){
  if(!current(a))return;let t=workroom.get(a.taskId);
  if(t.plan?.state!=='locked'||t.plan.revision!==a.planRevision||t.status==='done'||t.progress.decision==='approved'){pause(a,'Scope/task changed. Team paused; no request was replayed.');return;}
  if(a.operations>=50){pause(a,'Team transition budget reached.');return;}
  const phase=a.phase==='worker'?'work':'review',sendId=phase==='work'?a.workerSendId:a.reviewerSendId,agentId=phase==='work'?t.plan.workerId:t.plan.reviewerId,conversationId=phase==='work'?a.workerConversation:a.reviewerConversation;
  let send=t.messages.find(m=>m.id===sendId);
  if(!send){
   if(now()-Date.parse(a.updatedAt)>15*60*1000){pause(a,'Assigned agent did not become available within the bounded wait.');return;}
   const agents=await relay.agents();if(!current(a))return;const agent=agents.find(x=>x.id===agentId);
   if(!agent||agent.conversation_id!==conversationId){pause(a,'Assigned agent conversation changed or disconnected.');return;}
   if(!['idle','done','stopped'].includes(agent.status))return;
   await sendTaskHandoff({workroom,taskId:t.id,body:{id:sendId,agentId,conversationId,phase},relay,admitted:()=>current(a)});
   if(current(a))workroom.automation.transition(t.id,a.revision,{operation:true});return;
  }
  if(send.nims&&['failed','blocked','interrupted'].includes(send.nims.state)){pause(a,'The exact Nims request '+send.nims.state+'. Inspect its native receipt; no automatic retry.');return;}
  if(send.state!=='accepted'){pause(a,'Delivery '+send.state+'. Inspect the exact saved attempt; no automatic retry.');return;}
  if(send.outcome&&send.outcome.state!=='TASK_STATE_COMPLETED'){pause(a,'Native attempt ended unsuccessfully. Inspect its result.');return;}
  await syncTaskReplies({workroom,taskId:t.id,relay,admitted:()=>current(a),sendId});if(!current(a))return;t=workroom.get(t.id);
  if(phase==='work'){
   const report=t.agentUpdates.filter(u=>u.sendId===sendId).at(-1);
   if(report){if(report.update.checklist.some(s=>s.status==='blocked')){pause(a,'Worker reported blocked work. Inspect its report before continuing.');return;}
    if(!report.update.checklist.length||report.update.checklist.some(s=>s.status!=='done')){if(now()-Date.parse(send.at)>15*60*1000)pause(a,'Worker progress never reached a confirmed completed report.');return;}
    if(!report.update.result.trim()||!report.update.evidence.trim()){pause(a,'Completed worker report lacks result/evidence.');return;}
    if(!report.applied)workroom.applyAgentUpdate(t.id,{sendId,messageId:report.messageId,hash:report.hash,revision:t.progress.revision,taskRevision:t.revision,briefRevision:t.workroom.revision});
    if(current(a))workroom.automation.transition(t.id,a.revision,{phase:'reviewer',operation:true});return;
   }
  }else if(t.agentReviews.some(r=>r.sendId===sendId)){workroom.automation.transition(t.id,a.revision,{state:'needs_review',reason:'Independent review received. Inspect and record its verdict; Done remains deliberate.',operation:true});return;}
  if(now()-Date.parse(send.at)>15*60*1000)pause(a,'Result not confirmed within the bounded wait. Inspect the original attempt; do not resend blindly.');
 }
 async function tick(){if(stopped||running)return running;running=(async()=>{for(const a of workroom.automation.active()){try{await step(a);}catch{if(current(a))pause(a,'A team step could not be confirmed. Inspect the saved receipt; no automatic retry.');}}})().finally(()=>running=null);return running;}
 const timer=setInterval(tick,intervalMs);timer.unref();
 return {tick,action(id,body,agents){const result=workroom.automation.action(id,body,agents,root);setImmediate(tick);return result;},async close(){stopped=true;clearInterval(timer);if(running)await running;}};
}
