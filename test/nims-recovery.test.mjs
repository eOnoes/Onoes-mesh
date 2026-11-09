import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtempSync} from 'node:fs';
import {join} from 'node:path';
import {tmpdir} from 'node:os';
import {randomUUID} from 'node:crypto';
import {openTaskStore} from '../lib/task-store.mjs';
import {withNims} from '../lib/nims-link.mjs';
import {syncTaskReplies} from '../lib/workroom.mjs';
function fixture(blocked=false,missingTurn=false){
 const file=join(mkdtempSync(join(tmpdir(),'mesh-nims-recovery-')),'tasks.sqlite');let store=openTaskStore(file);
 const task=store.create({title:'Recover scoped plan',owner:'nims'}),id=randomUUID();
 const send=store.workroom.reserve(task.id,{id,agentId:'nims',conversationId:'mesh-nims',text:'Plan only'},'plan');store.workroom.settle(id,'accepted');
 store.workroom.nims.reserve({id,text:send.payload,conversationId:'mesh-nims'});store.workroom.nims.bind(id,{threadId:'saved-thread',turnId:missingTurn?undefined:'saved-turn'});
 if(blocked)store.workroom.nims.finish(id,'blocked','Permission declined');
 store.close();store=openTaskStore(file);
 const text='```workroom-update\n'+JSON.stringify({schema:'workroom-update/v1',taskId:task.id,sendId:id,goal:'Recovered plan',checklist:[{id:'one',text:'Clarify scope',status:'pending'}],result:'Plan only',evidence:'Native saved result'})+'\n```';
 const native={thread:{id:'saved-thread',turns:[{id:'saved-turn',status:'completed',items:[{type:'userMessage',content:[{type:'text',text:send.payload}]},{type:'agentMessage',text}]}]}};
 let reads=0,runs=0;const client={connect:async()=>({}),readThread:async()=>{reads++;return native;},run:async()=>{runs++;throw Error('Recovery must not dispatch');},close:async()=>{}};
 const relay=withNims({agents:async()=>[],close:async()=>{},nativeRead:async()=>{throw Error('Unexpected route');}},{root:process.cwd(),workroom:store.workroom,client});
 return {store,relay,task,id,native,client,counts:()=>({reads,runs}),close:async()=>{await relay.close();store.close();}};
}
test('restarted Nims result is read back once under original identities and reply sync deduplicates without dispatch',async()=>{
 const f=fixture();try{assert.equal(f.store.workroom.nims.get(f.id).state,'interrupted');await syncTaskReplies({workroom:f.store.workroom,taskId:f.task.id,relay:f.relay,admitted:()=>true,sendId:f.id});await syncTaskReplies({workroom:f.store.workroom,taskId:f.task.id,relay:f.relay,admitted:()=>true,sendId:f.id});assert.equal(f.store.workroom.nims.get(f.id).state,'completed');assert.equal(f.store.workroom.get(f.task.id).agentUpdates.length,1);assert.deepEqual(f.counts(),{reads:1,runs:0});}finally{await f.close();}
});
test('Nims recovery refuses mismatched, unfinished, permission-denied and nonlocal tool evidence',async()=>{
 const mutations=[n=>n.thread.id='wrong-thread',n=>n.thread.turns[0].id='wrong-turn',n=>n.thread.turns.push({...n.thread.turns[0]}),n=>n.thread.turns[0].status='inProgress',n=>n.thread.turns[0].items[0].content[0].text='wrong payload',n=>n.thread.turns[0].items.push({type:'commandExecution',status:'declined'}),n=>n.thread.turns[0].items.push({type:'commandExecution',status:'failed',exitCode:1}),n=>n.thread.turns[0].items.push({type:'mcpToolCall'})];
 for(const mutate of mutations){const f=fixture();try{mutate(f.native);await syncTaskReplies({workroom:f.store.workroom,taskId:f.task.id,relay:f.relay,admitted:()=>true,sendId:f.id});assert.equal(f.store.workroom.nims.get(f.id).state,'interrupted');assert.equal(f.store.workroom.get(f.task.id).agentUpdates.length,0);assert.equal(f.counts().runs,0);}finally{await f.close();}}
});
test('expired admission after native read cannot save a recovered result',async()=>{
 const f=fixture();let admitted=true;try{f.client.readThread=async()=>{admitted=false;return f.native;};await assert.rejects(syncTaskReplies({workroom:f.store.workroom,taskId:f.task.id,relay:f.relay,admitted:()=>admitted,sendId:f.id}),/expired/);assert.equal(f.store.workroom.nims.get(f.id).state,'interrupted');assert.equal(f.store.workroom.get(f.task.id).agentUpdates.length,0);}finally{await f.close();}
});
test('permission-blocked Nims attempts are never upgraded by readback',async()=>{
 const f=fixture(true);try{await syncTaskReplies({workroom:f.store.workroom,taskId:f.task.id,relay:f.relay,admitted:()=>true,sendId:f.id});assert.equal(f.store.workroom.nims.get(f.id).state,'blocked');assert.deepEqual(f.counts(),{reads:0,runs:0});}finally{await f.close();}
});

test('a previously displayed interruption cannot hide the later recovered report',async()=>{
 const f=fixture();try{f.native.thread.turns[0].status='inProgress';await syncTaskReplies({workroom:f.store.workroom,taskId:f.task.id,relay:f.relay,admitted:()=>true,sendId:f.id});f.native.thread.turns[0].status='completed';await syncTaskReplies({workroom:f.store.workroom,taskId:f.task.id,relay:f.relay,admitted:()=>true,sendId:f.id});assert.equal(f.store.workroom.nims.get(f.id).state,'completed');assert.equal(f.store.workroom.get(f.task.id).agentUpdates.length,1);}finally{await f.close();}
});

test('missing native turn identity is held without lookup or a replacement request',async()=>{
 const f=fixture(false,true);try{await syncTaskReplies({workroom:f.store.workroom,taskId:f.task.id,relay:f.relay,admitted:()=>true,sendId:f.id});assert.equal(f.store.workroom.nims.get(f.id).state,'interrupted');assert.deepEqual(f.counts(),{reads:0,runs:0});}finally{await f.close();}
});
test('unavailable native history keeps the unresolved receipt and never dispatches',async()=>{
 const f=fixture();try{f.client.readThread=async()=>{throw Error('offline');};await syncTaskReplies({workroom:f.store.workroom,taskId:f.task.id,relay:f.relay,admitted:()=>true,sendId:f.id});assert.equal(f.store.workroom.nims.get(f.id).state,'interrupted');assert.equal(f.counts().runs,0);}finally{await f.close();}
});
test('concurrent recovered readbacks save a single report without a state conflict',async()=>{
 const f=fixture();try{const sync=()=>syncTaskReplies({workroom:f.store.workroom,taskId:f.task.id,relay:f.relay,admitted:()=>true,sendId:f.id});await Promise.all([sync(),sync()]);assert.equal(f.store.workroom.nims.get(f.id).state,'completed');assert.equal(f.store.workroom.get(f.task.id).agentUpdates.length,1);assert.equal(f.counts().runs,0);}finally{await f.close();}
});
