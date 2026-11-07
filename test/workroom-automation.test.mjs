import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtempSync} from 'node:fs';
import {join} from 'node:path';
import {tmpdir} from 'node:os';
import {randomUUID} from 'node:crypto';
import {EventEmitter} from 'node:events';
import {openTaskStore} from '../lib/task-store.mjs';
import {sendTaskHandoff,syncTaskReplies} from '../lib/workroom.mjs';
import {createTeamRunner} from '../lib/workroom-automation.mjs';
import {withNims} from '../lib/nims-link.mjs';
import {createCodexClient} from '../lib/codex-client.mjs';
import {parseAssignment} from '../lib/workroom-assignment.mjs';
const file=()=>join(mkdtempSync(join(tmpdir(),'mesh-auto-')),'tasks.sqlite');
const agents=[{id:'echo',backend:'hermes',status:'idle',conversation_id:'e'},{id:'dsh',backend:'a2a',status:'idle',conversation_id:'d'}];
function ready(store){let t=store.create({title:'Automatic fixture',description:'Only one named fixture artifact',owner:'echo'});t=store.workroom.save(t.id,{project:'Fixture',criteria:'Independent checks pass',owner:'echo',team:'local_build',stage:'ready',revision:1});t=store.workroom.saveProgress(t.id,{goal:'Bounded artifact',checklist:[{id:'one',text:'Implement and verify fixture',status:'pending'}],result:'',evidence:'',reviewer:'',decision:'pending',revision:0,taskRevision:t.revision,briefRevision:t.workroom.revision});return store.workroom.savePlan(t.id,{lead:'echo',spec:'One artifact',workspace:process.cwd(),allowedFiles:'data/fixture-only.mjs',checks:'node --check data/fixture-only.mjs',boundaries:'No other changes or network',workerId:'echo',reviewerId:'dsh',state:'locked',revision:0,taskRevision:t.revision,briefRevision:t.workroom.revision,progressRevision:t.progress.revision}).task;}
const action=(t,kind='start')=>({action:kind,revision:t.automation?.revision??0,planRevision:t.plan.revision,taskRevision:t.revision,briefRevision:t.workroom.revision,progressRevision:t.progress.revision});
function fakeRelay(store,{lost=false,incomplete=false}={}){const sends=[];return {sends,agents:async()=>agents,nativeRead:async route=>{
 if(route==='/api/mesh-capabilities')return {taskSessionBinding:1};const messages=[];
 for(const s of sends){const taskId=/Workroom task ([a-f0-9-]+):/.exec(s.text)[1],t=store.workroom.get(taskId);let report;
  if(/Phase: work\n/.test(s.text))report={schema:'workroom-update/v1',taskId,sendId:s.id,goal:t.progress.goal,checklist:t.progress.checklist.map(x=>({...x,status:incomplete?'blocked':'done'})),result:'Fixture built',evidence:'Independent local fixture output'};
  else report={schema:'workroom-review/v1',taskId,sendId:s.id,verdict:'approved',summary:'Fixture independently checked',evidence:'Read and ran fixture checks'};
  messages.push({id:s.id,k:'you',t:s.text},{id:s.id+'-reply',k:'ag',t:'```'+(report.schema.startsWith('workroom-review')?'workroom-review':'workroom-update')+'\n'+JSON.stringify(report)+'\n```'});
 }return{messages};},taskMessage:async body=>{sends.push(body);if(lost)throw new Error('Lost response fixture');},close:async()=>{}};}

test('automatic cycle dispatches one builder and one independent reviewer, then stops before approval/Done',async()=>{
 const store=openTaskStore(file());const relay=fakeRelay(store),runner=createTeamRunner({workroom:store.workroom,relay,root:process.cwd(),intervalMs:600000});try{
  let t=ready(store);store.workroom.automation.action(t.id,action(t),agents,process.cwd());
  for(let i=0;i<4;i++)await runner.tick();t=store.workroom.get(t.id);
  assert.equal(relay.sends.length,2);assert.equal(t.automation.state,'needs_review');assert.equal(t.progress.decision,'pending');assert.equal(t.status,'open');assert.equal(t.agentReviews.length,1);assert.equal(t.agentReviews[0].applied,false);
  await runner.tick();assert.equal(relay.sends.length,2);
 }finally{await runner.close();store.close();}
});
test('uncertain delivery and incomplete result pause without replay/reviewer dispatch',async()=>{
 for(const config of [{lost:true},{incomplete:true}]){const store=openTaskStore(file());const relay=fakeRelay(store,config),runner=createTeamRunner({workroom:store.workroom,relay,root:process.cwd(),intervalMs:600000});try{const t=ready(store);store.workroom.automation.action(t.id,action(t),agents,process.cwd());for(let i=0;i<4;i++)await runner.tick();assert.equal(store.workroom.get(t.id).automation.state,'paused');assert.equal(relay.sends.length,1);assert.equal(store.workroom.get(t.id).progress.decision,'pending');}finally{await runner.close();store.close();}}
});
test('restart pauses consent; stale action, arbitrary workspace and second active team are rejected',()=>{
 const name=file();let store=openTaskStore(name);try{let t=ready(store);const original=action(t);store.workroom.automation.action(t.id,original,agents,process.cwd());assert.throws(()=>store.workroom.automation.action(t.id,original,agents,process.cwd()),/changed/);const other=ready(store);assert.throws(()=>store.workroom.automation.action(other.id,action(other),agents,process.cwd()),/Another team/);store.close();store=openTaskStore(name);t=store.workroom.get(t.id);assert.equal(t.automation.state,'paused');assert.equal(t.messages.length,0);assert.throws(()=>store.workroom.automation.action(other.id,action(store.workroom.get(other.id)),agents,'D:/different-root'),/qualified only/);}finally{store.close();}
});
test('new writer is rejected while another unresolved worker owns the same workspace',()=>{
 const store=openTaskStore(file());try{const a=ready(store),b=ready(store);store.workroom.reserve(a.id,{id:randomUUID(),agentId:'echo',conversationId:'e',text:'One writer'},'work');assert.throws(()=>store.workroom.reserve(b.id,{id:randomUUID(),agentId:'echo',conversationId:'e',text:'Second writer'},'work'),/second writer/);}finally{store.close();}
});
test('assignment proposals require exact source/schema and apply only as an unlocked draft',()=>{
 const store=openTaskStore(file());try{let t=ready(store);const b={id:randomUUID(),agentId:'echo',conversationId:'e',text:'Plan only'},s=store.workroom.reserve(t.id,b,'plan');store.workroom.settle(b.id,'accepted');const p={schema:'workroom-assignment/v1',taskId:t.id,sendId:b.id,spec:'Proposed outcome',workspace:process.cwd(),allowedFiles:'one.mjs',checks:'node --check one.mjs',boundaries:'No other edits',workerId:'echo',reviewerId:'nims'};const text='```workroom-assignment\n'+JSON.stringify(p)+'\n```';assert.equal(parseAssignment(text,'other',b.id),null);assert.equal(parseAssignment(text+text,t.id,b.id),null);assert.equal(parseAssignment('```workroom-assignment\n'+JSON.stringify({...p,approved:true})+'\n```',t.id,b.id),null);store.workroom.captureReplies(t.id,b.id,[{id:b.id,k:'you',t:s.payload},{id:'lead',k:'ag',t:text}]);t=store.workroom.get(t.id);const offer=t.assignments[0];t=store.workroom.applyAssignment(t.id,{sendId:offer.sendId,messageId:offer.messageId,hash:offer.hash,revision:t.plan.revision,taskRevision:t.revision,briefRevision:t.workroom.revision,progressRevision:t.progress.revision}).task;assert.equal(t.plan.state,'draft');assert.equal(t.plan.reviewerId,'nims');assert.equal(t.progress.decision,'pending');}finally{store.close();}
});
test('Nims adapter binds exact task/send/native identities, deduplicates and captures only completed result',async()=>{
 const store=openTaskStore(file());let calls=0;const client={connect:async()=>({connected:true}),run:async({text,onBinding})=>{calls++;await onBinding({threadId:'native-thread',turnId:'native-turn'});const taskId=/Workroom task ([a-f0-9-]+):/.exec(text)[1],sendId=/Workroom message ([a-f0-9-]+)/.exec(text)[1];return{status:'completed',text:'```workroom-update\n'+JSON.stringify({schema:'workroom-update/v1',taskId,sendId,goal:'Nims plan',checklist:[{id:'one',text:'Clarify scope',status:'pending'}],result:'Proposed only',evidence:'Inline fixture'})+'\n```'};},close:async()=>{}};const relay=withNims({agents:async()=>[],snapshot:async()=>({status:'unavailable'}),close:async()=>{}},{root:process.cwd(),workroom:store.workroom,client});try{const t=store.create({title:'Nims lead',owner:'nims'}),body={id:randomUUID(),agentId:'nims',conversationId:'mesh-nims',phase:'plan'};await sendTaskHandoff({workroom:store.workroom,taskId:t.id,body,relay,admitted:()=>true});for(let i=0;i<12;i++)await new Promise(r=>setImmediate(r));await sendTaskHandoff({workroom:store.workroom,taskId:t.id,body,relay,admitted:()=>true});assert.equal(calls,1);await syncTaskReplies({workroom:store.workroom,taskId:t.id,relay,admitted:()=>true});assert.equal(store.workroom.get(t.id).agentUpdates.length,1);assert.equal(store.workroom.nims.get(body.id).threadId,'native-thread');assert.equal(store.workroom.nims.get(body.id).turnId,'native-turn');}finally{await relay.close();store.close();}
});
test('native Codex client forces read-only, hides its process and declines approval rather than granting access',async()=>{
 const sent=[];let options;const child=new EventEmitter();child.stdout=new EventEmitter();child.stdout.setEncoding=()=>{};child.stderr=new EventEmitter();child.killed=false;const emit=m=>child.stdout.emit('data',JSON.stringify(m)+'\n');child.stdin={writable:true,end(){child.emit('exit',0);},write(line){const m=JSON.parse(line);sent.push(m);if(!m.method)return;if(m.method==='initialize')emit({id:m.id,result:{}});if(m.method==='account/read')emit({id:m.id,result:{account:{type:'chatgpt'}}});if(m.method==='thread/start')emit({id:m.id,result:{thread:{id:'thread-fixture'}}});if(m.method==='turn/start'){emit({id:m.id,result:{turn:{id:'turn-fixture'}}});setImmediate(()=>{emit({id:99,method:'item/commandExecution/requestApproval',params:{threadId:'thread-fixture',turnId:'turn-fixture'}});emit({method:'item/completed',params:{threadId:'thread-fixture',item:{type:'agentMessage',text:'Blocked honestly'}}});emit({method:'turn/completed',params:{threadId:'thread-fixture',turn:{id:'turn-fixture',status:'completed'}}});});}}};child.kill=()=>{child.killed=true;child.emit('exit',0);};const client=createCodexClient({root:process.cwd(),spawnImpl:(exe,args,opts)=>{options=opts;return child;}});try{const result=await client.run({text:'Fixture'});assert.equal(result.permissionBlocked,true);assert.equal(options.windowsHide,true);assert.equal(sent.find(m=>m.method==='thread/start').params.sandbox,'read-only');assert.equal(sent.find(m=>m.method==='turn/start').params.sandboxPolicy.networkAccess,false);assert.deepEqual(sent.find(m=>m.id===99).result,{decision:'decline'});}finally{await client.close();}
});

test('closing a paused attempt preserves its identifiers and cannot replay uncertain work',async()=>{
 const store=openTaskStore(file());const relay=fakeRelay(store,{lost:true}),runner=createTeamRunner({workroom:store.workroom,relay,root:process.cwd(),intervalMs:600000});try{
  let t=ready(store);store.workroom.automation.action(t.id,action(t),agents,process.cwd());await runner.tick();t=store.workroom.get(t.id);assert.equal(t.automation.state,'paused');const original=t.automation.workerSendId;
  t=store.workroom.automation.action(t.id,action(t,'close'),[],process.cwd()).task;assert.equal(t.automation.state,'closed');assert.ok(t.history.some(h=>h.kind==='team_attempt_closed'&&h.detail.includes(original)));
  assert.throws(()=>store.workroom.automation.action(t.id,action(t),agents,process.cwd()),/Resolve the existing worker/);assert.equal(relay.sends.length,1);
 }finally{await runner.close();store.close();}
});
