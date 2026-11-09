import {sendTaskHandoff,syncTaskReplies} from './workroom.mjs';
import {createIntakeRunner} from './workroom-flow.mjs';
import {reconcileLocalSession} from './workroom-local-sessions.mjs';
export function createTeamRunner({workroom,relay,root,intervalMs=4000,now=()=>Date.now(),simpleFlow=false,nativeObserver=null}){
 let stopped=false,running=null;
 const current=a=>!stopped&&workroom.automation.read(a.taskId)?.state==='active'&&workroom.automation.read(a.taskId)?.revision===a.revision;
 const pause=(a,reason)=>workroom.automation.transition(a.taskId,a.revision,{state:'paused',reason});
 const intake=simpleFlow?createIntakeRunner({workroom,relay,root,sendTaskHandoff,syncTaskReplies,now,active:()=>!stopped}):null;
 async function step(a){
  if(!current(a))return;let t=workroom.get(a.taskId);
  if(t.plan?.state!=='locked'||t.plan.revision!==a.planRevision||t.status==='done'||t.progress.decision==='approved'){pause(a,'Scope/task changed. Team paused; no request was replayed.');return;}
  if(a.operations>=50){pause(a,'Team transition budget reached.');return;}
  const phase=a.phase==='worker'?'work':'review',sendId=phase==='work'?a.workerSendId:a.reviewerSendId,agentId=phase==='work'?t.plan.workerId:t.plan.reviewerId,conversationId=phase==='work'?a.workerConversation:a.reviewerConversation;
  let send=t.messages.find(m=>m.id===sendId);
  if(send?.nativeLocal){
   pause(a,'Dedicated native worker remains held pending result and retirement verification. Inspect its saved receipt; no Relay fallback.');return;
  }
  if(!send){
   if(now()-Date.parse(a.updatedAt)>15*60*1000){pause(a,'Assigned agent did not become available within the bounded wait.');return;}
   const agents=await relay.agents();if(!current(a))return;const agent=agents.find(x=>x.id===agentId);
   if(!agent||agent.conversation_id!==conversationId){pause(a,'Assigned agent conversation changed or disconnected.');return;}
   if(!['idle','done','stopped'].includes(agent.status))return;
   await sendTaskHandoff({workroom,taskId:t.id,body:{id:sendId,agentId,conversationId,phase},relay,admitted:()=>current(a),allowUncertainReplay:false});
   if(current(a))workroom.automation.transition(t.id,a.revision,{operation:true});return;
  }
  if(send.nims&&['failed','blocked','interrupted'].includes(send.nims.state)){pause(a,'The exact Nims request '+send.nims.state+'. Inspect its native receipt; no automatic retry.');return;}
  if(send.state!=='accepted'){pause(a,'Delivery '+send.state+'. Inspect the exact saved attempt; no automatic retry.');return;}
  if(send.outcome&&send.outcome.state!=='TASK_STATE_COMPLETED'){if(simpleFlow)workroom.flow.failed(t.id,'Native worker ended: '+send.outcome.state,sendId);pause(a,'Native attempt ended unsuccessfully. Inspect its result.');return;}
  await syncTaskReplies({workroom,taskId:t.id,relay,admitted:()=>current(a),sendId});if(!current(a))return;t=workroom.get(t.id);
  if(phase==='work'){
   const report=t.agentUpdates.filter(u=>u.sendId===sendId).at(-1);
   if(report){if(report.update.checklist.some(s=>s.status==='blocked')){if(simpleFlow){if(!report.applied)workroom.applyAgentUpdate(t.id,{sendId,messageId:report.messageId,hash:report.hash,revision:t.progress.revision,taskRevision:t.revision,briefRevision:t.workroom.revision});workroom.flow.question(t.id,report.update.result||report.update.checklist.filter(s=>s.status==='blocked').map(s=>s.text).join('\n'),sendId);}pause(a,'Worker needs clarification. The question is saved on this card.');return;}
    if(!report.update.checklist.length||report.update.checklist.some(s=>s.status!=='done')){if(now()-Date.parse(send.at)>15*60*1000)pause(a,'Worker progress never reached a confirmed completed report.');return;}
    if(!report.update.result.trim()||!report.update.evidence.trim()){pause(a,'Completed worker report lacks result/evidence.');return;}
    if(!report.applied)workroom.applyAgentUpdate(t.id,{sendId,messageId:report.messageId,hash:report.hash,revision:t.progress.revision,taskRevision:t.revision,briefRevision:t.workroom.revision});
    if(current(a))workroom.automation.transition(t.id,a.revision,{phase:'reviewer',operation:true});return;
   }
  }else if(t.agentReviews.some(r=>r.sendId===sendId)){
   if(!simpleFlow){workroom.automation.transition(t.id,a.revision,{state:'needs_review',reason:'Independent review received. Inspect and record its verdict; Done remains deliberate.',operation:true});return;}
   const review=t.agentReviews.find(r=>r.sendId===sendId);
   if(!review.applied)t=workroom.applyAgentReview(t.id,{sendId,messageId:review.messageId,hash:review.hash,revision:t.progress.revision,taskRevision:t.revision,briefRevision:t.workroom.revision}).task;
   if(review.review.verdict==='approved'){
    workroom.save(t.id,{...Object.fromEntries(['project','criteria','owner','team','revision'].map(k=>[k,t.workroom[k]])),stage:'done'});
    workroom.automation.transition(t.id,a.revision,{state:'completed',reason:'Independent checks approved. Completed work is in Done for Eddie to review.',operation:true});
   }else if(review.review.verdict==='changes_requested'&&a.operations<11){workroom.automation.retry(t.id,a.revision);}
   else{workroom.flow.question(t.id,review.review.summary,sendId);pause(a,'Review needs clarification after the bounded correction cycle.');}
   return;
  }
  if(now()-Date.parse(send.at)>15*60*1000)pause(a,'Result not confirmed within the bounded wait. Inspect the original attempt; do not resend blindly.');
 }
 async function tick(){if(stopped||running)return running;running=(async()=>{
  if(nativeObserver){
   for(const saved of workroom.localSessions.pendingReads()){
    if(stopped)break;
    try{await reconcileLocalSession({workroom,...saved,rpc:nativeObserver.rpc,
     authorized:profile=>!stopped&&nativeObserver.authorized(profile)===true});}
    catch{/* Saved binding/hold remains authoritative; observations never replay work. */}
   }
  }
  for(const a of workroom.automation.active()){try{await step(a);}catch{if(current(a))pause(a,'A team step could not be confirmed. Inspect the saved receipt; no automatic retry.');}}if(intake&&!stopped)await intake();})().finally(()=>running=null);return running;}
 const timer=setInterval(tick,intervalMs);timer.unref();
 return {tick,action(id,body,agents){const result=workroom.automation.action(id,body,agents,root);setImmediate(tick);return result;},async close(){stopped=true;clearInterval(timer);if(running)await running;}};
}
