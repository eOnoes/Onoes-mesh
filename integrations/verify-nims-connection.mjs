import {mkdirSync,writeFileSync} from 'node:fs';
import {randomUUID} from 'node:crypto';
import {openTaskStore} from '../lib/task-store.mjs';
import {withNims} from '../lib/nims-link.mjs';
import {sendTaskHandoff,syncTaskReplies} from '../lib/workroom.mjs';
const id=randomUUID(),directory='data/nims-qualification-'+id;mkdirSync(directory);
const store=openTaskStore(directory+'/tasks.sqlite');
const relay=withNims({agents:async()=>[],snapshot:async()=>({status:'unavailable'}),close:async()=>{}},{root:process.cwd(),workroom:store.workroom});
try{
 const task=store.create({title:'Nims connection qualification',description:'Qualification only. Do not call tools, read files, edit files, contact services or dispatch other agents. Inline facts: owner wants one scoped helper; workspace/path and acceptance details need clarification. Return a workroom-update/v1 pending planning checklist for asking those questions. Do not propose a ready assignment or claim any build/review completed.',owner:'nims'});
 const body={id:randomUUID(),agentId:'nims',conversationId:'mesh-nims',phase:'plan'};
 await sendTaskHandoff({workroom:store.workroom,taskId:task.id,body,relay,admitted:()=>true});
 const deadline=Date.now()+170000;let native;
 while(Date.now()<deadline){native=store.workroom.nims.get(body.id);if(!['prepared','running'].includes(native.state))break;await new Promise(r=>setTimeout(r,500));}
 if(native.state!=='completed')throw Error('Native Nims qualification did not complete: '+native.state);
 await syncTaskReplies({workroom:store.workroom,taskId:task.id,relay,admitted:()=>true,sendId:body.id});
 const saved=store.workroom.get(task.id);if(saved.agentUpdates.length!==1)throw Error('No unique bound structured planning report returned');
 const receipt={at:new Date().toISOString(),result:'PASS',taskId:task.id,sendId:body.id,threadId:native.threadId,turnId:native.turnId,nativeStatus:native.state,structuredReportCount:saved.agentUpdates.length,taskDecision:saved.progress.decision,autoApplied:false,scope:'isolated fixture; no tools requested; existing ChatGPT sign-in'};
 writeFileSync('../mesh-nims-qualification.json',JSON.stringify(receipt,null,2));console.log(JSON.stringify(receipt,null,2));
}finally{await relay.close();store.close();}
