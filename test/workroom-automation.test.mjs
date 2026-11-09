import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtempSync,mkdirSync,writeFileSync} from 'node:fs';
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
import http from 'node:http';
import {startApp,ROOT} from '../server.mjs';
const file=()=>join(mkdtempSync(join(tmpdir(),'mesh-auto-')),'tasks.sqlite');
const agents=[{id:'echo',backend:'hermes',status:'idle',conversation_id:'e'},{id:'dsh',backend:'a2a',status:'idle',conversation_id:'d'}];
function ready(store,reviewerId='dsh'){let t=store.create({title:'Automatic fixture',description:'Only one named fixture artifact',owner:'echo'});t=store.workroom.save(t.id,{project:'Fixture',criteria:'Independent checks pass',owner:'echo',team:'local_build',stage:'ready',revision:1});t=store.workroom.saveProgress(t.id,{goal:'Bounded artifact',checklist:[{id:'one',text:'Implement and verify fixture',status:'pending'}],result:'',evidence:'',reviewer:'',decision:'pending',revision:0,taskRevision:t.revision,briefRevision:t.workroom.revision});return store.workroom.savePlan(t.id,{lead:'echo',spec:'One artifact',workspace:process.cwd(),allowedFiles:'data/fixture-only.mjs',checks:'node --check data/fixture-only.mjs',boundaries:'No other changes or network',workerId:'echo',reviewerId,state:'locked',revision:0,taskRevision:t.revision,briefRevision:t.workroom.revision,progressRevision:t.progress.revision}).task;}
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

test('team start refuses a paused or closed unresolved worker before creating another attempt',async()=>{
 const store=openTaskStore(file()),relay=fakeRelay(store),runner=createTeamRunner({workroom:store.workroom,relay,root:process.cwd(),intervalMs:600000});try{
  let a=ready(store),b=ready(store);store.workroom.automation.action(a.id,action(a),agents,process.cwd());await runner.tick();
  a=store.workroom.get(a.id);assert.equal(relay.sends.length,1);
  a=store.workroom.automation.action(a.id,action(a,'pause'),agents,process.cwd()).task;
  assert.throws(()=>store.workroom.automation.action(b.id,action(b),agents,process.cwd()),/Resolve the worker on/);
  assert.equal(store.workroom.get(b.id).automation,undefined);
  a=store.workroom.automation.action(a.id,action(a,'close'),[],process.cwd()).task;
  assert.throws(()=>store.workroom.automation.action(b.id,action(b),agents,process.cwd()),/Resolve the worker on/);
  assert.equal(relay.sends.length,1);
  await syncTaskReplies({workroom:store.workroom,taskId:a.id,relay,admitted:()=>true});a=store.workroom.get(a.id);
  const report=a.agentUpdates[0];assert.ok(report);
  store.workroom.applyAgentUpdate(a.id,{sendId:report.sendId,messageId:report.messageId,hash:report.hash,revision:a.progress.revision,taskRevision:a.revision,briefRevision:a.workroom.revision});
  b=store.workroom.automation.action(b.id,action(b),agents,process.cwd()).task;assert.equal(b.automation.state,'active');
  assert.equal(relay.sends.length,1,'admitting the next team does not itself dispatch it');
 }finally{await runner.close();store.close();}
});

test('managed admission retains the writer after an applied report and rejects unsupported Echo reconciliation',async()=>{
 const old=process.env.MESH_SIMPLE_FLOW;const name=file();let store=openTaskStore(name);const relay=fakeRelay(store),runner=createTeamRunner({workroom:store.workroom,relay,root:process.cwd(),intervalMs:600000});
 try{
  let a=ready(store),b=ready(store);store.workroom.automation.action(a.id,action(a),agents,process.cwd());await runner.tick();a=store.workroom.get(a.id);
  a=store.workroom.automation.action(a.id,action(a,'pause'),agents,process.cwd()).task;store.workroom.automation.action(a.id,action(a,'close'),[],process.cwd());
  await syncTaskReplies({workroom:store.workroom,taskId:a.id,relay,admitted:()=>true});a=store.workroom.get(a.id);const report=a.agentUpdates[0];store.workroom.applyAgentUpdate(a.id,{sendId:report.sendId,messageId:report.messageId,hash:report.hash,revision:a.progress.revision,taskRevision:a.revision,briefRevision:a.workroom.revision});
  process.env.MESH_SIMPLE_FLOW='1';
  assert.throws(()=>store.workroom.automation.action(b.id,action(b),agents,process.cwd()),/verified terminal receipt/);
  assert.throws(()=>store.workroom.reserve(b.id,{id:randomUUID(),agentId:'echo',conversationId:'e',text:'Competing writer'},'work'),/verified terminal receipt/);
  assert.throws(()=>store.workroom.recordSendOutcome(a.id,report.sendId,{peerTaskId:'echo-task',state:'TASK_STATE_COMPLETED',proofHash:'a'.repeat(64),verifiedAt:new Date().toISOString()}),/Only this task/);
  await runner.close();store.close();store=openTaskStore(name);b=store.workroom.get(b.id);
  assert.throws(()=>store.workroom.automation.action(b.id,action(b),agents,process.cwd()),/verified terminal receipt/);assert.equal(store.workroom.get(b.id).messages.length,0);assert.equal(relay.sends.length,1);
 }finally{await runner.close();store.close();if(old===undefined)delete process.env.MESH_SIMPLE_FLOW;else process.env.MESH_SIMPLE_FLOW=old;}
});

test('team resume refuses an unresolved worker from another task, including after restart',()=>{
 for(const state of ['prepared','unknown','accepted']){
  const name=file();let store=openTaskStore(name);try{
   let b=ready(store);store.workroom.automation.action(b.id,action(b),agents,process.cwd());b=store.workroom.get(b.id);
   b=store.workroom.automation.action(b.id,action(b,'pause'),agents,process.cwd()).task;
   const a=ready(store),id=randomUUID();store.workroom.reserve(a.id,{id,agentId:'echo',conversationId:'e',text:'Unresolved original worker'},'work');
   if(state!=='prepared')store.workroom.settle(id,state);
   store.close();store=openTaskStore(name);b=store.workroom.get(b.id);
   assert.throws(()=>store.workroom.automation.action(b.id,action(b,'resume'),agents,process.cwd()),/Resolve the worker on/);
   assert.equal(store.workroom.get(b.id).automation.state,'paused');
   assert.equal(store.workroom.get(a.id).messages[0].id,id);
  }finally{store.close();}
 }
});

test('real team endpoint refuses competing start/resume with admission intact and zero worker dispatch',async()=>{
 const keys=['MESH_RELAY_MODE','MESH_RELAY_URL','MESH_RELAY_TOKEN_FILE','MESH_STANDALONE','MESH_NIMS','MESH_NEMOTRON_CONTROL','MESH_MODEL_OBSERVATION','MESH_DSH_APPROVAL_ORIGIN','MESH_DSH_TOKEN_FILE','MESH_SIMPLE_FLOW'],previous=Object.fromEntries(keys.map(k=>[k,process.env[k]]));
 const token='fixture-'+randomUUID(),tokenPath=join(mkdtempSync(join(tmpdir(),'mesh-auto-http-')),'key');writeFileSync(tokenPath,token);
 let posts=0,app;
 const peers=http.createServer((req,res)=>{
  res.setHeader('Content-Type','application/json');
  if(req.method!=='GET')posts++;
  if(req.headers.authorization!=='Bearer '+token){res.writeHead(401);res.end('{}');return;}
  if(req.method==='GET'&&req.url==='/api/agents'){res.end(JSON.stringify(agents));return;}
  res.writeHead(503);res.end('{}');
 });
 const dataDir='data/team-admission-http-'+randomUUID();mkdirSync(join(ROOT,dataDir));
 let store=openTaskStore(join(ROOT,dataDir,'tasks.sqlite')),a,b,c;
 try{
  a=ready(store);b=ready(store);c=ready(store);
  b=store.workroom.automation.action(b.id,action(b),agents,ROOT).task;
  b=store.workroom.automation.action(b.id,action(b,'pause'),agents,ROOT).task;
  const id=randomUUID(),send=store.workroom.reserve(a.id,{id,agentId:'echo',conversationId:'e',text:'Original accepted fixture'},'work');store.workroom.settle(id,'accepted');
  const report={schema:'workroom-update/v1',taskId:a.id,sendId:id,goal:a.progress.goal,checklist:a.progress.checklist.map(s=>({...s,status:'done'})),result:'Reported complete, native end unverified',evidence:'Fixture report only'};
  store.workroom.captureReplies(a.id,id,[{id,k:'you',t:send.payload},{id:'fixture-report',k:'ag',t:'```workroom-update\n'+JSON.stringify(report)+'\n```'}]);a=store.workroom.get(a.id);const update=a.agentUpdates[0];store.workroom.applyAgentUpdate(a.id,{sendId:id,messageId:update.messageId,hash:update.hash,revision:a.progress.revision,taskRevision:a.revision,briefRevision:a.workroom.revision});
 }finally{store.close();}
 try{
  await new Promise(r=>peers.listen(0,'127.0.0.1',r));
  process.env.MESH_RELAY_MODE='http';process.env.MESH_RELAY_URL='http://127.0.0.1:'+peers.address().port;process.env.MESH_RELAY_TOKEN_FILE=tokenPath;process.env.MESH_STANDALONE='0';
  process.env.MESH_NIMS='0';process.env.MESH_NEMOTRON_CONTROL='0';process.env.MESH_MODEL_OBSERVATION='0';process.env.MESH_SIMPLE_FLOW='1';
  process.env.MESH_DSH_APPROVAL_ORIGIN=process.env.MESH_RELAY_URL;process.env.MESH_DSH_TOKEN_FILE=tokenPath;
  app=await startApp({dataDir,relayEnabled:true});
  const headers={Origin:app.url,'Content-Type':'application/json'},path=t=>'/api/workroom/'+t.id+'/automation';
  const post=(t,kind,override={})=>fetch(app.url+path(t),{method:'POST',headers:{...headers,...override},body:JSON.stringify(action(t,kind))});
  assert.equal((await post(c,'start')).status,401);
  const boot=await fetch(app.url+'/api/trial-session/bootstrap',{method:'POST',headers,body:'{}'});assert.equal(boot.status,201);
  const proof=await boot.json();headers.Cookie=boot.headers.get('set-cookie').split(';')[0];headers['X-Trial-CSRF']=proof.csrfToken;
  assert.equal((await post(c,'start',{'X-Trial-CSRF':'wrong'})).status,403);
  for(const [task,kind] of [[c,'start'],[b,'resume']]){
   const response=await post(task,kind);assert.equal(response.status,409);assert.match((await response.json()).error,/Resolve the worker on/);
  }
  const read=async t=>{const response=await fetch(app.url+'/api/workroom/'+t.id,{headers});assert.equal(response.status,200);return (await response.json()).task;};
  assert.equal((await read(b)).automation.state,'paused');assert.equal((await read(c)).automation,undefined);
  assert.equal((await read(a)).messages.length,1);assert.equal(posts,0);
 }finally{
  if(app)await app.close();await new Promise(r=>peers.close(r));
  for(const k of keys){if(previous[k]===undefined)delete process.env[k];else process.env[k]=previous[k];}
 }
});
test('assignment proposals require exact source/schema and apply only as an unlocked draft',()=>{
 const store=openTaskStore(file());try{let t=ready(store);const b={id:randomUUID(),agentId:'echo',conversationId:'e',text:'Plan only'},s=store.workroom.reserve(t.id,b,'plan');store.workroom.settle(b.id,'accepted');const p={schema:'workroom-assignment/v1',taskId:t.id,sendId:b.id,spec:'Proposed outcome',workspace:process.cwd(),allowedFiles:'one.mjs',checks:'node --check one.mjs',boundaries:'No other edits',workerId:'echo',reviewerId:'nims'};const text='```workroom-assignment\n'+JSON.stringify(p)+'\n```';assert.equal(parseAssignment(text,'other',b.id),null);assert.equal(parseAssignment(text+text,t.id,b.id),null);assert.equal(parseAssignment('```workroom-assignment\n'+JSON.stringify({...p,approved:true})+'\n```',t.id,b.id),null);store.workroom.captureReplies(t.id,b.id,[{id:b.id,k:'you',t:s.payload},{id:'lead',k:'ag',t:text}]);t=store.workroom.get(t.id);const offer=t.assignments[0];t=store.workroom.applyAssignment(t.id,{sendId:offer.sendId,messageId:offer.messageId,hash:offer.hash,revision:t.plan.revision,taskRevision:t.revision,briefRevision:t.workroom.revision,progressRevision:t.progress.revision}).task;assert.equal(t.plan.state,'draft');assert.equal(t.plan.reviewerId,'nims');assert.equal(t.progress.decision,'pending');}finally{store.close();}
});
test('Nims adapter binds exact task/send/native identities, deduplicates and captures only completed result',async()=>{
 const store=openTaskStore(file());let calls=0;const client={connect:async()=>({connected:true}),run:async({text,onBinding})=>{calls++;await onBinding({threadId:'native-thread',turnId:'native-turn'});const taskId=/Workroom task ([a-f0-9-]+):/.exec(text)[1],sendId=/Workroom message ([a-f0-9-]+)/.exec(text)[1];return{status:'completed',text:'```workroom-update\n'+JSON.stringify({schema:'workroom-update/v1',taskId,sendId,goal:'Nims plan',checklist:[{id:'one',text:'Clarify scope',status:'pending'}],result:'Proposed only',evidence:'Inline fixture'})+'\n```'};},close:async()=>{}};const relay=withNims({agents:async()=>[],snapshot:async()=>({status:'unavailable'}),close:async()=>{}},{root:process.cwd(),workroom:store.workroom,client});try{const t=store.create({title:'Nims lead',owner:'nims'}),body={id:randomUUID(),agentId:'nims',conversationId:'mesh-nims',phase:'plan'};await sendTaskHandoff({workroom:store.workroom,taskId:t.id,body,relay,admitted:()=>true});for(let i=0;i<12;i++)await new Promise(r=>setImmediate(r));await sendTaskHandoff({workroom:store.workroom,taskId:t.id,body,relay,admitted:()=>true});assert.equal(calls,1);await syncTaskReplies({workroom:store.workroom,taskId:t.id,relay,admitted:()=>true});assert.equal(store.workroom.get(t.id).agentUpdates.length,1);assert.equal(store.workroom.nims.get(body.id).threadId,'native-thread');assert.equal(store.workroom.nims.get(body.id).turnId,'native-turn');}finally{await relay.close();store.close();}
});
test('native Codex client forces read-only, hides its process and declines approval rather than granting access',async()=>{
 const sent=[];let options;const child=new EventEmitter();child.stdout=new EventEmitter();child.stdout.setEncoding=()=>{};child.stderr=new EventEmitter();child.killed=false;const emit=m=>child.stdout.emit('data',JSON.stringify(m)+'\n');child.stdin={writable:true,end(){child.emit('exit',0);},write(line){const m=JSON.parse(line);sent.push(m);if(!m.method)return;if(m.method==='initialize')emit({id:m.id,result:{}});if(m.method==='account/read')emit({id:m.id,result:{account:{type:'chatgpt'}}});if(m.method==='thread/start')emit({id:m.id,result:{thread:{id:'thread-fixture'},cwd:process.cwd(),modelProvider:'openai',approvalPolicy:'on-request',approvalsReviewer:'user',sandbox:{type:'readOnly',networkAccess:false}}});if(m.method==='turn/start'){emit({id:m.id,result:{turn:{id:'turn-fixture'}}});setImmediate(()=>{emit({id:99,method:'item/commandExecution/requestApproval',params:{threadId:'thread-fixture',turnId:'turn-fixture'}});emit({method:'item/completed',params:{threadId:'thread-fixture',item:{type:'agentMessage',text:'Blocked honestly'}}});emit({method:'turn/completed',params:{threadId:'thread-fixture',turn:{id:'turn-fixture',status:'completed'}}});});}}};child.kill=()=>{child.killed=true;child.emit('exit',0);};const client=createCodexClient({root:process.cwd(),spawnImpl:(exe,args,opts)=>{options=opts;return child;}});try{const result=await client.run({text:'Fixture'});assert.equal(result.permissionBlocked,true);assert.equal(options.windowsHide,true);assert.equal(sent.find(m=>m.method==='thread/start').params.sandbox,'read-only');assert.equal(sent.find(m=>m.method==='turn/start').params.sandboxPolicy.networkAccess,false);assert.deepEqual(sent.find(m=>m.id===99).result,{decision:'decline'});}finally{await client.close();}
});

test('closing a paused attempt preserves its identifiers and cannot replay uncertain work',async()=>{
 const store=openTaskStore(file());const relay=fakeRelay(store,{lost:true}),runner=createTeamRunner({workroom:store.workroom,relay,root:process.cwd(),intervalMs:600000});try{
  let t=ready(store);store.workroom.automation.action(t.id,action(t),agents,process.cwd());await runner.tick();t=store.workroom.get(t.id);assert.equal(t.automation.state,'paused');const original=t.automation.workerSendId;
  t=store.workroom.automation.action(t.id,action(t,'close'),[],process.cwd()).task;assert.equal(t.automation.state,'closed');assert.ok(t.history.some(h=>h.kind==='team_attempt_closed'&&h.detail.includes(original)));
  assert.throws(()=>store.workroom.automation.action(t.id,action(t),agents,process.cwd()),/Resolve the existing worker/);assert.equal(relay.sends.length,1);
 }finally{await runner.close();store.close();}
});

const nativeAgents=[agents[0],{id:'nims',backend:'codex',status:'idle',conversation_id:'n'}];
function nativeFixture(store,{lost=false,onCreate=()=>{}}={}){
 const methods=[];
 const profile={profileRef:'test-echo',identityRef:'test-native',model:'synthetic',baseUrl:'http://127.0.0.1:9/v1',workspace:process.cwd()};
 return {methods,profile,profileFor:()=>profile,credential:async()=>'fixture-only',authorized:()=>true,
  rpc:async(method,params)=>{
   methods.push([method,params]);
   if(method==='session.create'){await onCreate();return{session_id:'local-'+'a'.repeat(64)};}
   if(method==='prompt.submit'){if(lost)throw new Error('lost after commit');return{};}
   assert.equal(method,'prompt.lookup');return{found:true,session_id:params.session_id,submission_id:params.submission_id,
    receipt:{admission_id:'b'.repeat(32),ref:{profile_id:'synthetic-native',session_id:params.session_id},
     authority_epoch:1,execution_generation:1,status:'terminal'}};
  }};
}

test('automatic native worker uses the saved stage once; restart observes without Relay or reviewer fallback',async()=>{
 const name=file();let store=openTaskStore(name),runner;const native=nativeFixture(store,{lost:true});let legacy=0;
 const relay={agents:async()=>nativeAgents,taskMessage:async()=>{legacy++;},nativeRead:async()=>{legacy++;}};
 try{
  let t=ready(store,'nims');store.workroom.automation.action(t.id,action(t),nativeAgents,process.cwd());
  const stage=store.workroom.automation.read(t.id);
  runner=createTeamRunner({workroom:store.workroom,relay,root:process.cwd(),intervalMs:600000,nativeWorker:native});
  await runner.tick();t=store.workroom.get(t.id);
  assert.equal(t.messages.length,1);assert.equal(t.messages[0].id,stage.workerSendId);
  assert.equal(t.messages[0].nativeLocal.teamBound,1);assert.equal(t.messages[0].nativeLocal.state,'submit_unknown');
  assert.equal(t.automation.operations,1);
  await runner.close();store.close();store=openTaskStore(name);
  runner=createTeamRunner({workroom:store.workroom,relay,root:process.cwd(),intervalMs:600000,nativeWorker:native});
  await runner.tick();await runner.tick();t=store.workroom.get(t.id);
  assert.equal(t.automation.state,'paused');assert.equal(t.automation.phase,'worker');
  assert.equal(t.messages[0].nativeLocal.nativeStatus,'terminal');assert.equal(t.messages[0].nativeLocal.writerQuiescence,false);
  assert.equal(native.methods.filter(([method])=>method==='session.create').length,1);
  assert.equal(native.methods.filter(([method])=>method==='prompt.submit').length,1);
  assert.equal(legacy,0);assert.equal(t.progress.decision,'pending');assert.notEqual(t.status,'done');
 }finally{if(runner)await runner.close();store.close();}
});

test('native team pause during asynchronous session creation prevents submission',async()=>{
 const store=openTaskStore(file());let runner;try{
  let t=ready(store,'nims');store.workroom.automation.action(t.id,action(t),nativeAgents,process.cwd());
  const native=nativeFixture(store,{onCreate:()=>{const current=store.workroom.get(t.id);store.workroom.automation.action(t.id,action(current,'pause'),nativeAgents,process.cwd());}});
  runner=createTeamRunner({workroom:store.workroom,relay:{agents:async()=>nativeAgents},root:process.cwd(),intervalMs:600000,nativeWorker:native});
  await runner.tick();await runner.tick();t=store.workroom.get(t.id);
  assert.equal(t.automation.state,'paused');assert.equal(native.methods.filter(([method])=>method==='prompt.submit').length,0);
  assert.equal(t.messages[0].nativeLocal.state,'create_unknown');
 }finally{if(runner)await runner.close();store.close();}
});

test('native selection refuses other review routes and cannot replace an existing Relay send',async()=>{
 const store=openTaskStore(file());let runner;try{
  let t=ready(store);store.workroom.automation.action(t.id,action(t),agents,process.cwd());
  const native=nativeFixture(store);const relay=fakeRelay(store);
  runner=createTeamRunner({workroom:store.workroom,relay,root:process.cwd(),intervalMs:600000,nativeWorker:native});
  await runner.tick();assert.equal(store.workroom.get(t.id).automation.state,'paused');assert.equal(native.methods.length,0);
  assert.equal(store.workroom.get(t.id).messages.length,0);await runner.close();
  // Existing Relay receipt must stay on its original route when configuration changes.
  store.workroom.automation.action(t.id,action(store.workroom.get(t.id),'resume'),agents,process.cwd());
  runner=createTeamRunner({workroom:store.workroom,relay,root:process.cwd(),intervalMs:600000});await runner.tick();await runner.close();
  runner=createTeamRunner({workroom:store.workroom,relay,root:process.cwd(),intervalMs:600000,nativeWorker:native});
  await runner.tick();assert.equal(native.methods.length,0);assert.equal(relay.sends.length,1);
 }finally{if(runner)await runner.close();store.close();}
});

test('native reservation exempts only its exact active stage and submission rechecks a paused team',()=>{
 const store=openTaskStore(file());try{
  let t=ready(store,'nims');store.workroom.automation.action(t.id,action(t),nativeAgents,process.cwd());
  const stage=store.workroom.automation.read(t.id),local=store.workroom.localSessions,profile=nativeFixture(store).profile;
  const body={id:stage.workerSendId,agentId:'echo',conversationId:stage.workerConversation,text:'Fixed worker instruction'};
  const team={revision:stage.revision,planRevision:stage.planRevision};
  assert.throws(()=>local.reserve(t.id,body,profile),/existing workspace writer/);
  for(const [request,binding] of [[body,{...team,revision:team.revision+1}],
   [{...body,id:randomUUID()},team],[{...body,conversationId:'other'},team]]){
   assert.throws(()=>local.reserve(t.id,request,profile,binding),/exact saved native team stage/);
  }
  assert.equal(store.workroom.get(t.id).messages.length,0);
  let row=local.reserve(t.id,body,profile,team).nativeLocal;
  assert.equal(row.teamBound,1);
  assert.throws(()=>local.reserve(t.id,body,profile),/different message/);
  row=local.startCreate(t.id,body.id,row.revision);row=local.bindSession(t.id,body.id,row.revision,{session_id:'local-'+'a'.repeat(64)});
  t=store.workroom.get(t.id);store.workroom.automation.action(t.id,action(t,'pause'),nativeAgents,process.cwd());
  assert.throws(()=>local.startSubmit(t.id,body.id,row.revision),/paused or changed/);
  assert.equal(local.read(t.id,body.id).state,'session_bound');
 }finally{store.close();}
});

test('failed retired native worker pauses without dispatching Nims review',async()=>{
 const store=openTaskStore(file());let runner;try{
  const t=ready(store,'nims');store.workroom.automation.action(t.id,action(t),nativeAgents,process.cwd());
  const native=nativeFixture(store),original=native.rpc;let reviews=0;
  native.retireCompleted=true;
  native.rpc=async(method,params)=>{
   const reply=await original(method,params);if(method!=='prompt.lookup')return reply;
   return {...reply,outcome:'failed',profile_contract:{model:native.profile.model,provider:'custom',base_url:native.profile.baseUrl,
    workspace:process.cwd(),toolsets:['file'],safe_mode:true,ignore_user_config:true,follow_profile:false,source:'tool',max_turns:50,terminal_backend:'local',closed:true},
    process_scope:{admission_id:'b'.repeat(32),session_id:params.session_id,profile_id:'synthetic-native',execution_generation:1,
     authority_epoch:1,sealed:true,state:'ended',active_processes:0,root_ended:true,process_tree_ended:true,
     termination_requested:false,writer_quiescence:false,execution_closed:true,authority_writes_drained:true,worker_resources_idle:true},
    receipt:{...reply.receipt,result:{final_response:'Failed native fixture'}}};
  };
  runner=createTeamRunner({workroom:store.workroom,relay:{agents:async()=>nativeAgents,taskMessage:async()=>{reviews++;}},
   root:process.cwd(),intervalMs:600000,nativeWorker:native});
  await runner.tick();await runner.tick();
  const after=store.workroom.get(t.id);assert.equal(after.automation.state,'paused');assert.equal(after.automation.phase,'worker');
  assert.equal(after.messages[0].nativeLocal.writerQuiescence,true);assert.equal(reviews,0);
 }finally{if(runner)await runner.close();store.close();}
});

test('qualified native completion applies once and dispatches the original Nims review once',async()=>{
 const store=openTaskStore(file());let runner;try{
  const t=ready(store,'nims');store.workroom.automation.action(t.id,action(t),nativeAgents,process.cwd());
  const stage=store.workroom.automation.read(t.id),native=nativeFixture(store),original=native.rpc,reviews=[];
  native.retireCompleted=true;
  native.rpc=async(method,params)=>{
   const reply=await original(method,params);if(method!=='prompt.lookup')return reply;
   const update={schema:'workroom-update/v1',taskId:t.id,sendId:stage.workerSendId,goal:t.progress.goal,
    checklist:t.progress.checklist.map(step=>({...step,status:'done'})),result:'Fixture artifact built',evidence:'Synthetic unit report'};
   return {...reply,outcome:'completed',profile_contract:{model:native.profile.model,provider:'custom',base_url:native.profile.baseUrl,
    workspace:process.cwd(),toolsets:['file'],safe_mode:true,ignore_user_config:true,follow_profile:false,source:'tool',max_turns:50,terminal_backend:'local',closed:true},
    process_scope:{admission_id:'b'.repeat(32),session_id:params.session_id,profile_id:'synthetic-native',execution_generation:1,
     authority_epoch:1,sealed:true,state:'ended',active_processes:0,root_ended:true,process_tree_ended:true,
     termination_requested:false,writer_quiescence:false,execution_closed:true,authority_writes_drained:true,worker_resources_idle:true},
    receipt:{...reply.receipt,result:{final_response:'```workroom-update\n'+JSON.stringify(update)+'\n```'}}};
  };
  const relay={agents:async()=>nativeAgents,nativeRead:async()=>({taskSessionBinding:1,messages:[]}),taskMessage:async message=>reviews.push(message)};
  runner=createTeamRunner({workroom:store.workroom,relay,root:process.cwd(),intervalMs:600000,nativeWorker:native});
  for(let i=0;i<5;i++)await runner.tick();const after=store.workroom.get(t.id);
  assert.equal(after.automation.phase,'reviewer');assert.equal(after.agentUpdates[0].applied,true);
  assert.equal(after.messages.find(m=>m.id===stage.workerSendId).nativeLocal.writerQuiescence,true);
  assert.equal(reviews.length,1);assert.equal(reviews[0].id,stage.reviewerSendId);assert.equal(reviews[0].agentId,'nims');
  assert.match(reviews[0].text,/Read-only tools only/);assert.equal(after.progress.decision,'pending');assert.notEqual(after.status,'done');
 }finally{if(runner)await runner.close();store.close();}
});

function reviewProtocol(reply){
 const sent=[],child=new EventEmitter();child.stdout=new EventEmitter();child.stdout.setEncoding=()=>{};child.stderr=new EventEmitter();child.killed=false;
 const emit=m=>child.stdout.emit('data',JSON.stringify(m)+'\n');
 child.stdin={writable:true,end(){child.emit('exit',0);},write(line){const m=JSON.parse(line);sent.push(m);if(m.method==='initialize')emit({id:m.id,result:{}});if(m.method==='account/read')emit({id:m.id,result:{account:{type:'chatgpt'}}});if(['thread/start','thread/resume'].includes(m.method))emit({id:m.id,result:reply});if(m.method==='turn/start'){emit({id:m.id,result:{turn:{id:'review-turn'}}});setImmediate(()=>emit({method:'turn/completed',params:{threadId:'review-thread',turn:{id:'review-turn',status:'completed'}}}));}}};
 child.kill=()=>{child.killed=true;child.emit('exit',0);};
 return {sent,client:createCodexClient({root:process.cwd(),spawnImpl:()=>child})};
}
const verifiedReviewPolicy=()=>({thread:{id:'review-thread'},cwd:process.cwd(),modelProvider:'openai',approvalPolicy:'on-request',approvalsReviewer:'user',sandbox:{type:'readOnly',networkAccess:false}});
test('Nims refuses missing or widened runtime policy before sending a turn on start and resume',async()=>{
 for(const threadId of [undefined,'review-thread'])for(const patch of [{sandbox:{type:'workspaceWrite',networkAccess:false}},{sandbox:{type:'readOnly',networkAccess:true}},{sandbox:undefined},{approvalPolicy:'never'},{approvalsReviewer:'auto_review'},{cwd:process.cwd()+'/elsewhere'},{modelProvider:'custom'}]){
  const {client,sent}=reviewProtocol({...verifiedReviewPolicy(),...patch});let bound;
  try{await assert.rejects(client.run({threadId,text:'Do not run on a widened policy',onBinding:b=>{bound=b;}}),/read-only review policy/);assert.equal(bound.threadId,'review-thread');assert.equal(sent.some(m=>m.method==='turn/start'),false);}finally{await client.close();}
 }
});
test('Nims can verify a native review policy without creating an agent turn',async()=>{
 const {client,sent}=reviewProtocol(verifiedReviewPolicy());try{const prepared=await client.prepareReview({});assert.equal(prepared.threadId,'review-thread');assert.equal(prepared.policy.sandbox.type,'readOnly');assert.equal(sent.some(m=>m.method==='turn/start'),false);}finally{await client.close();}
});

test('Nims cannot replace a saved native thread identity while resuming',async()=>{
 const {client,sent}=reviewProtocol({...verifiedReviewPolicy(),thread:{id:'other-thread'}});let rebound=false;
 try{await assert.rejects(client.run({threadId:'review-thread',text:'Review',onBinding:()=>{rebound=true;}}),/different native thread identity/);assert.equal(rebound,false);assert.equal(sent.some(m=>m.method==='turn/start'),false);}finally{await client.close();}
});
