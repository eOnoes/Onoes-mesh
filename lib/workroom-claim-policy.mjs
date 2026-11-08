export function backlogEligibility(task,at=Date.now()){
 const born=Date.parse(task.createdAt);
 if(!Number.isFinite(born)||born>at||at-born<12*60*60*1000)return {eligible:false,reason:'Not yet twelve hours old'};
 if(task.status==='done'||task.workroom.stage==='done'||task.progress.decision==='approved')return {eligible:false,reason:'Completed'};
 if(!['backlog','ready'].includes(task.workroom.stage)||task.workroom.owner)return {eligible:false,reason:'Already assigned or in progress'};
 // Failure reconciliation belongs to the original claim, never to fresh intake.
 if(task.flow?.claim||task.flow?.state&&task.flow.state!=='idea')return {eligible:false,reason:'Already claimed or waiting for clarification'};
 if(task.automation?.state==='active')return {eligible:false,reason:'Team active'};
 if(task.messages.some(m=>m.phase==='work'&&['prepared','unknown','accepted'].includes(m.state)&&!m.outcome&&!task.agentUpdates.some(u=>u.sendId===m.id&&u.applied)))return {eligible:false,reason:'Unresolved original worker'};
 return {eligible:true,reason:'Unassigned idea older than twelve hours'};
}
