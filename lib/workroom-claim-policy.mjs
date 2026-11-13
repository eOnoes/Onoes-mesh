import {isLegacyRecovered} from './workroom-legacy-recovery.mjs';
import {isUnresolvedWorkSend} from './workroom-writer-states.mjs';

export function backlogEligibility(task,at=Date.now()){
 const born=Date.parse(task.createdAt);
 if(!Number.isFinite(born)||born>at||at-born<12*60*60*1000)return {eligible:false,reason:'Not yet twelve hours old'};
 if(task.status==='done'||task.workroom.stage==='done'||task.progress.decision==='approved')return {eligible:false,reason:'Completed'};
 if(!['backlog','ready'].includes(task.workroom.stage)||task.workroom.owner)return {eligible:false,reason:'Already assigned or in progress'};
 // Failure reconciliation belongs to the original claim, never to fresh intake.
 if(task.flow?.claim||task.flow?.state&&task.flow.state!=='idea')return {eligible:false,reason:'Already claimed or waiting for clarification'};
 if(task.automation?.state==='active')return {eligible:false,reason:'Team active'};
 if(task.messages.some(isUnresolvedWorkSend))return {eligible:false,reason:'Writer quiescence is unproven'};
 return {eligible:true,reason:'Unassigned idea older than twelve hours'};
}

// A terminal task/run status does not prove that tools, subagents, or child
// processes have ended. Only a consumed trusted native retirement proof can
// remove its writer blocker, or a separately authorized exact legacy recovery
// may adjudicate its unknown outcome. Plain status/JSON fields never do so.
export function writerQuiescenceBlockers(tasks){
 const blockers=[];
 for(const task of tasks){
  if(task.automation?.state==='active')blockers.push({taskId:task.id,sendId:'',state:'active',reason:'active_team'});
  for(const message of task.messages||[]){
   if(isUnresolvedWorkSend(message)&&message.nativeLocal?.writerQuiescence!==true&&!isLegacyRecovered(message))blockers.push({taskId:task.id,sendId:message.id,state:message.state,reason:'writer_quiescence_unproven'});
  }
 }
 return blockers;
}
