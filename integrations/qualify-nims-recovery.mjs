// Opt-in live Nims readback qualification; disposable board, one no-tools planning turn.
import assert from 'node:assert/strict';
import {mkdirSync,writeFileSync} from 'node:fs';
import {resolve,join} from 'node:path';
import {randomUUID} from 'node:crypto';
import {openTaskStore} from '../lib/task-store.mjs';
import {createCodexClient} from '../lib/codex-client.mjs';
import {withNims} from '../lib/nims-link.mjs';
import {sendTaskHandoff,syncTaskReplies} from '../lib/workroom.mjs';
const directory=resolve('data/nims-recovery-'+randomUUID());mkdirSync(directory);const file=join(directory,'tasks.sqlite');
let store=openTaskStore(file),relay,submitted=0,lookups=0,raw;
const base=()=>({agents:async()=>[],snapshot:async()=>({}),close:async()=>{},nativeRead:async()=>{throw Error('Unexpected route');}});
try{
 const native=createCodexClient({root:directory});
 relay=withNims(base(),{root:directory,workroom:store.workroom,client:{connect:()=>native.connect(),close:()=>native.close(),run:async args=>{submitted++;raw=await native.run(args);assert.equal(raw.status,'completed');throw Error('Qualification: completed native reply deliberately lost before local finish');}}});
 const task=store.create({title:'Recovery-only planning check',description:'No tools or edits. Based only on these inline facts, propose a pending checklist: Eddie wants a small helper but workspace and acceptance details are missing. Do not approve or claim completed work. Return the requested structured planning report.',owner:'nims'}),sendId=randomUUID();
 await sendTaskHandoff({workroom:store.workroom,taskId:task.id,body:{id:sendId,agentId:'nims',conversationId:'mesh-nims',phase:'plan'},relay,admitted:()=>true});
 const deadline=Date.now()+185000;
 while(['prepared','running'].includes(store.workroom.nims.get(sendId).state)){if(Date.now()>deadline)throw Error('Native planning check did not settle');await new Promise(r=>setTimeout(r,250));}
 const before=store.workroom.nims.get(sendId);assert.equal(before.state,'failed');assert.ok(before.threadId&&before.turnId);assert.equal(raw.turnId,before.turnId);
 await relay.close();relay=null;store.close();store=openTaskStore(file);
 const reader=createCodexClient({root:directory});
 relay=withNims(base(),{root:directory,workroom:store.workroom,client:{connect:()=>reader.connect(),close:()=>reader.close(),run:async()=>{submitted++;throw Error('Recovery must not dispatch');},readThread:async id=>{lookups++;return reader.readThread(id);}}});
 await syncTaskReplies({workroom:store.workroom,taskId:task.id,relay,admitted:()=>true,sendId});
 await syncTaskReplies({workroom:store.workroom,taskId:task.id,relay,admitted:()=>true,sendId});
 const after=store.workroom.nims.get(sendId),saved=store.workroom.get(task.id);
 assert.equal(after.state,'completed');assert.equal(after.threadId,before.threadId);assert.equal(after.turnId,before.turnId);assert.equal(after.text,raw.text);assert.equal(saved.agentUpdates.length,1);assert.equal(saved.progress.decision,'pending');assert.equal(submitted,1);assert.equal(lookups,1);
 const report={qualification:'PASS',at:new Date().toISOString(),directory,taskId:task.id,sendId,threadId:after.threadId,turnId:after.turnId,before:before.state,after:after.state,modelTurns:submitted,readbacks:lookups,structuredReports:saved.agentUpdates.length,decision:saved.progress.decision,lossInjectedAfterNativeCompletion:true,reopenedBeforeReadback:true,productionBoardTouched:false,limitation:'Completed native reply lost before local finish. Process death during a running native turn and absent turn-ID recovery are not qualified.'};
 writeFileSync(join(directory,'qualification.json'),JSON.stringify(report,null,2));console.log(JSON.stringify(report));
}catch(error){writeFileSync(join(directory,'failure.json'),JSON.stringify({message:error.message,submitted,lookups},null,2));throw error;}finally{if(relay)await relay.close();store.close();}
