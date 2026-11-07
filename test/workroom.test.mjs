import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtempSync} from 'node:fs';
import {tmpdir} from 'node:os';
import path from 'node:path';
import {randomUUID} from 'node:crypto';
import http from 'node:http';
import vm from 'node:vm';
import {readFileSync} from 'node:fs';
import {openTaskStore} from '../lib/task-store.mjs';
import {sendTaskMessage,syncTaskReplies} from '../lib/workroom.mjs';
import {parseAgentUpdate} from '../lib/workroom-updates.mjs';
import {createRelayHttpLink} from '../lib/relay-http.mjs';
import {startApp} from '../server.mjs';
const database=()=>path.join(mkdtempSync(path.join(tmpdir(),'mesh-workroom-')),'tasks.sqlite');
const metadata=(revision=0)=>({project:'Phone build',criteria:'A verified result',owner:'echo',team:'local_build',stage:'ready',revision});
const message=()=>({id:randomUUID(),agentId:'echo',conversationId:randomUUID(),text:'Implement the bounded task.'});

const agentReport=(taskId,sendId,extra={})=>({schema:'workroom-update/v1',taskId,sendId,goal:'Verify an agent update',
  checklist:[{id:'one',text:'Read the report',status:'done'},{id:'two',text:'Review the actual result',status:'pending'}],result:'Report returned',evidence:'Reply received',...extra});
const fencedReport=report=>'```workroom-update\n'+JSON.stringify(report)+'\n```';
function offerFixture(store,task){
  const body=message();const send=store.workroom.reserve(task.id,body);store.workroom.settle(body.id,'accepted');
  store.workroom.captureReplies(task.id,body.id,[{id:1,k:'you',t:send.payload},{id:2,k:'ag',t:fencedReport(agentReport(task.id,body.id))}]);
  const current=store.workroom.get(task.id),offer=current.agentUpdates[0];
  return {body,offer,selection:{sendId:offer.sendId,messageId:offer.messageId,hash:offer.hash,revision:current.progress.revision,taskRevision:current.revision,briefRevision:current.workroom.revision}};
}

test('structured reports reject wrong identity, prose, approval fields, duplicate blocks and invalid steps',()=>{
  const ids={taskId:randomUUID(),sendId:randomUUID()};const valid=agentReport(ids.taskId,ids.sendId);
  assert.equal(parseAgentUpdate(fencedReport(valid),ids).update.goal,valid.goal);
  for(const reply of ['All done, approved!',fencedReport({...valid,taskId:randomUUID()}),fencedReport({...valid,sendId:randomUUID()}),
    fencedReport({...valid,decision:'approved'}),fencedReport(valid)+'\n'+fencedReport(valid),fencedReport({...valid,checklist:[...valid.checklist,valid.checklist[0]]}),
    fencedReport({...valid,checklist:[{id:'one',text:'Do work',status:'approved'}]})])assert.equal(parseAgentUpdate(reply,ids),null);
});

test('agent reports apply once, stay pending review and keep provenance across restart',()=>{
  const filename=database();let store=openTaskStore(filename);const task=store.create({title:'Agent report acceptance'});store.workroom.save(task.id,metadata());
  const {selection}=offerFixture(store,task);const first=store.workroom.applyAgentUpdate(task.id,selection);
  assert.equal(first.task.progress.decision,'pending');assert.equal(first.task.progress.reviewer,'');assert.equal(first.task.progress.checklist[0].status,'done');
  assert.equal(first.task.agentUpdates[0].applied,true);assert.equal(first.task.history.filter(event=>event.kind==='agent_update_applied').length,1);
  assert.throws(()=>store.workroom.save(task.id,{...metadata(first.task.workroom.revision),stage:'done'}),error=>error.status===409);
  store.close();store=openTaskStore(filename);assert.equal(store.workroom.applyAgentUpdate(task.id,selection).duplicate,true);
  assert.equal(store.workroom.get(task.id).history.filter(event=>event.kind==='agent_update_applied').length,1);store.close();
});

test('late reports cannot overwrite a changed brief, manually edited progress or an approved review',()=>{
  for(const change of ['brief','progress','review']){
    const store=openTaskStore(database());const task=store.create({title:'No stale report'});store.workroom.save(task.id,metadata());
    const {selection}=offerFixture(store,task);let current=store.workroom.get(task.id);
    if(change==='brief')store.workroom.save(task.id,{...metadata(current.workroom.revision),criteria:'New scope'});
    else store.workroom.saveProgress(task.id,{goal:'Current human goal',checklist:[{id:'human',text:'Actual verified step',status:'done'}],result:'Human result',evidence:'Actual checks',reviewer:'Eddie',
      decision:change==='review'?'approved':'pending',revision:0,taskRevision:current.revision,briefRevision:current.workroom.revision});
    current=store.workroom.get(task.id);
    assert.throws(()=>store.workroom.applyAgentUpdate(task.id,{...selection,revision:current.progress.revision,taskRevision:current.revision,briefRevision:current.workroom.revision}),error=>error.status===409);
    assert.equal(store.workroom.get(task.id).progress.goal,current.progress.goal);store.close();
  }
});

test('reports cannot be selected from another task or applied with stale edit revisions',()=>{
  const store=openTaskStore(database());const task=store.create({title:'Bound task'});store.workroom.save(task.id,metadata());
  const {selection}=offerFixture(store,task);const other=store.create({title:'Other task'});
  assert.throws(()=>store.workroom.applyAgentUpdate(other.id,selection),error=>error.status===409);
  assert.throws(()=>store.workroom.applyAgentUpdate(task.id,{...selection,revision:100}),error=>error.status===409);
  assert.equal(store.workroom.get(task.id).progress.revision,0);store.close();
});

test('replies bind to exact accepted send, stop at next user turn and persist across restart',async()=>{
  const filename=database();let store=openTaskStore(filename);const task=store.create({title:'Reply isolation'});const body=message();
  store.workroom.reserve(task.id,body);store.workroom.settle(body.id,'accepted');
  const messages=[{id:'unrelated',k:'ag',t:'Earlier private conversation'},
    {id:body.id,k:'you',t:'Task brief'},{id:'answer',k:'ag',t:'Bounded answer'},
    {id:'other-user',k:'you',t:'Different task'},{id:'other-answer',k:'ag',t:'Unrelated answer'}];
  const relay={nativeRead:async route=>{assert.ok(route.includes(body.conversationId));return {messages};}};
  await syncTaskReplies({workroom:store.workroom,taskId:task.id,relay,admitted:()=>true});
  await syncTaskReplies({workroom:store.workroom,taskId:task.id,relay,admitted:()=>true});
  assert.deepEqual(store.workroom.get(task.id).replies.map(reply=>reply.text),['Bounded answer']);
  await assert.rejects(syncTaskReplies({workroom:store.workroom,taskId:task.id,relay,admitted:()=>false}),error=>error.status===403);
  store.close();store=openTaskStore(filename);assert.equal(store.workroom.get(task.id).replies.length,1);store.close();
});

test('missing exact outgoing ID never guesses a reply association',()=>{
  const store=openTaskStore(database());const task=store.create({title:'No guessing'});const body=message();
  store.workroom.reserve(task.id,body);store.workroom.settle(body.id,'accepted');
  store.workroom.captureReplies(task.id,body.id,[{id:'other',k:'ag',t:'Not this task'}]);
  assert.equal(store.workroom.get(task.id).replies.length,0);store.close();
});

test('numeric Relay transcript IDs bind through unique frozen payload, ambiguous matches fail closed',()=>{
  const store=openTaskStore(database());const task=store.create({title:'Numeric IDs'});const body=message();
  const send=store.workroom.reserve(task.id,body);store.workroom.settle(body.id,'accepted');
  const outgoing={id:155,k:'you',t:send.payload};
  store.workroom.captureReplies(task.id,body.id,[outgoing,{id:156,k:'ag',t:'Correct response'}]);
  assert.equal(store.workroom.get(task.id).replies[0].text,'Correct response');
  store.workroom.captureReplies(task.id,body.id,[outgoing,{...outgoing,id:157},{id:158,k:'ag',t:'Ambiguous'}]);
  assert.equal(store.workroom.get(task.id).replies.length,1);store.close();
});

test('legacy task and proposal persist; Workroom metadata, escaped text and history survive restart',()=>{
  const filename=database();let store=openTaskStore(filename);
  const task=store.create({title:'<img onerror=alert(1)>',description:'Original brief'});
  assert.equal(store.workroom.get(task.id).workroom.stage,'backlog');
  const saved=store.workroom.save(task.id,metadata());
  assert.equal(saved.workroom.revision,1);
  assert.throws(()=>store.workroom.save(task.id,metadata()),error=>error.status===409);
  store.close();store=openTaskStore(filename);
  assert.equal(store.get(task.id).description,'Original brief');
  assert.equal(store.workroom.get(task.id).workroom.project,'Phone build');
  assert.equal(store.workroom.get(task.id).history.length,1);
  assert.throws(()=>store.workroom.save(task.id,{...metadata(1),stage:'done'}),error=>error.status===409);
  const current=store.workroom.get(task.id);
  store.workroom.saveProgress(task.id,{goal:'A verified result',checklist:[{id:'check-1',text:'Verify the result',status:'done'}],
    result:'Verified',evidence:'Local checks passed',reviewer:'Eddie',decision:'approved',revision:0,
    taskRevision:current.revision,briefRevision:current.workroom.revision});
  const done=store.workroom.save(task.id,{...metadata(1),stage:'done'});
  assert.equal(done.status,'done');store.close();
});

test('goal and checklist persist; completed steps alone never approve the result',()=>{
  const filename=database();let store=openTaskStore(filename);const task=store.create({title:'Reviewed work'});
  store.workroom.save(task.id,metadata());
  let current=store.workroom.get(task.id);
  const progress={goal:'Ship a verified change',checklist:[{id:'one',text:'Build',status:'done'},{id:'two',text:'Check',status:'blocked'}],
    result:'',evidence:'',reviewer:'',decision:'pending',revision:0,taskRevision:current.revision,briefRevision:current.workroom.revision};
  store.workroom.saveProgress(task.id,progress);
  assert.throws(()=>store.workroom.saveProgress(task.id,{...progress,revision:1,decision:'approved'}),error=>error.status===400);
  assert.throws(()=>store.update(task.id,{title:task.title,status:'done',revision:task.revision}),error=>error.status===409);
  store.close();store=openTaskStore(filename);current=store.workroom.get(task.id);
  assert.equal(current.progress.goal,progress.goal);assert.equal(current.progress.checklist[1].status,'blocked');
  assert.equal(current.progress.decision,'pending');store.close();
});

test('review requires current revisions and evidence; changed brief invalidates approval',()=>{
  const store=openTaskStore(database());const task=store.create({title:'Versioned review'});store.workroom.save(task.id,metadata());
  const current=store.workroom.get(task.id);
  const body={goal:'Verified feature',checklist:[{id:'one',text:'Check result',status:'done'}],result:'Delivered',evidence:'test log',reviewer:'Eddie',
    decision:'approved',revision:0,taskRevision:current.revision,briefRevision:current.workroom.revision};
  assert.throws(()=>store.workroom.saveProgress(task.id,{...body,evidence:''}),error=>error.status===400);
  store.workroom.saveProgress(task.id,body);
  assert.throws(()=>store.workroom.saveProgress(task.id,body),error=>error.status===409);
  store.workroom.save(task.id,{...metadata(1),criteria:'New requirement'});
  assert.equal(store.workroom.get(task.id).progress.decision,'stale');
  assert.throws(()=>store.workroom.save(task.id,{...metadata(2),criteria:'New requirement',stage:'done'}),error=>error.status===409);
  store.close();
});

test('real HTTP review flow keeps goal, steps and reviewed result on one task',async()=>{
  const dataDir='test/app03-workroom-review-'+randomUUID();let app=await startApp({dataDir});
  const request=async(route,{method='GET',body,proof={}}={})=>{
    const response=await fetch(app.url+route,{method,headers:{...proof,Origin:app.url,'Content-Type':'application/json'},...(body?{body:JSON.stringify(body)}:{})});
    return {status:response.status,text:await response.text(),cookie:response.headers.get('set-cookie')};
  };
  const login=async()=>{const boot=await request('/api/trial-session/bootstrap',{method:'POST',body:{}});return {Cookie:boot.cookie.split(';')[0],'X-Trial-CSRF':JSON.parse(boot.text).csrfToken};};
  try{
    let proof=await login();const created=await request('/api/tasks',{method:'POST',proof,body:{title:'One complete task'}});const id=JSON.parse(created.text).task.id;
    assert.equal((await request('/api/workroom/'+id+'/progress',{method:'PATCH',body:{}})).status,401);
    await request('/api/workroom/'+id,{method:'PATCH',proof,body:metadata()});
    let task=JSON.parse((await request('/api/workroom/'+id,{proof})).text).task;
    const progress={goal:'Keep the full record together',checklist:[{id:'check',text:'Verify persistence',status:'done'}],result:'Task verified',evidence:'HTTP test and restart',reviewer:'Eddie',decision:'approved',revision:0,taskRevision:task.revision,briefRevision:task.workroom.revision};
    assert.equal((await request('/api/workroom/'+id+'/progress',{method:'PATCH',proof,body:progress})).status,200);
    assert.equal((await request('/api/workroom/'+id,{method:'PATCH',proof,body:{...metadata(1),stage:'done'}})).status,200);
    await app.close();app=await startApp({dataDir});proof=await login();
    task=JSON.parse((await request('/api/workroom/'+id,{proof})).text).task;
    assert.equal(task.workroom.stage,'done');assert.equal(task.progress.decision,'approved');assert.equal(task.progress.result,'Task verified');
    assert.ok(task.history.some(event=>event.kind==='review_approved'));
  }finally{await app.close();}
});

test('one task keeps multiple messages; accepted retry never dispatches twice; changed ID payload is rejected',async()=>{
  const store=openTaskStore(database());const task=store.create({title:'One job'});
  let sends=0;const relay={nativeRead:async()=>({taskSessionBinding:1}),taskMessage:async()=>{sends++;}};
  const body=message();const args={workroom:store.workroom,taskId:task.id,body,relay,admitted:()=>true};
  await sendTaskMessage(args);await sendTaskMessage(args);await sendTaskMessage({...args,body:message()});
  assert.equal(sends,2);assert.equal(store.list().length,1);assert.equal(store.workroom.get(task.id).messages.length,2);
  await assert.rejects(sendTaskMessage({...args,body:{...body,text:'Different'}}),error=>error.status===409);store.close();
});

test('lost response and restart preserve original send ID and frozen task brief for deliberate retry',async()=>{
  const filename=database();let store=openTaskStore(filename);const task=store.create({title:'Original title'});
  store.workroom.save(task.id,metadata());const body=message();const payloads=[];let fail=true;
  const relay={nativeRead:async()=>({taskSessionBinding:1}),taskMessage:async value=>{payloads.push(value);if(fail)throw new Error('response lost');}};
  await assert.rejects(sendTaskMessage({workroom:store.workroom,taskId:task.id,body,relay,admitted:()=>true}));
  assert.equal(store.workroom.get(task.id).messages[0].state,'unknown');store.close();store=openTaskStore(filename);
  store.workroom.save(task.id,{...metadata(1),criteria:'Changed criteria'});fail=false;
  await sendTaskMessage({workroom:store.workroom,taskId:task.id,body,relay,admitted:()=>true});
  assert.equal(payloads[0].id,payloads[1].id);assert.equal(payloads[0].text,payloads[1].text);
  assert.match(payloads[0].text,/A verified result/);assert.equal(store.list().length,1);store.close();
});

test('overlapping sends reject prepared attempt; crash marks it unknown without dispatching',async()=>{
  const filename=database();let store=openTaskStore(filename);const task=store.create({title:'Bounded task'});const body=message();
  store.workroom.reserve(task.id,body);
  const relay={nativeRead:async()=>({taskSessionBinding:1}),taskMessage:async()=>assert.fail('must not dispatch')};
  await assert.rejects(sendTaskMessage({workroom:store.workroom,taskId:task.id,body,relay,admitted:()=>true}),error=>error.status===409);
  store.close();store=openTaskStore(filename);assert.equal(store.workroom.get(task.id).messages[0].state,'unknown');store.close();
});

test('missing receiver capability and expired admission dispatch nothing',async()=>{
  const store=openTaskStore(database());const task=store.create({title:'No dispatch'});
  for(const [capability,admitted] of [[{},true],[{taskSessionBinding:1},false]]){
    const relay={nativeRead:async()=>capability,taskMessage:async()=>assert.fail('must not dispatch')};
    await assert.rejects(sendTaskMessage({workroom:store.workroom,taskId:task.id,body:message(),relay,admitted:()=>admitted}));
  }
  assert.equal(store.workroom.get(task.id).messages.length,0);store.close();
});

test('task bridge sends expected conversation and rejects changed session before sending',async()=>{
  const conversationId=randomUUID();let current=conversationId;const calls=[];
  const relay=await createRelayHttpLink({baseUrl:'http://127.0.0.1:1',token:'test-only',fetchImpl:async(url,options)=>{
    calls.push([url,options]);return new Response(JSON.stringify(url.endsWith('/api/agents')?[{id:'echo',backend:'hermes',conversation_id:current}]:{ok:true}),{headers:{'Content-Type':'application/json'}});
  }});
  const body={...message(),conversationId};await relay.taskMessage(body,()=>true);
  assert.equal(JSON.parse(calls[1][1].body).expectedConversationId,conversationId);
  current=randomUUID();await assert.rejects(relay.taskMessage(body,()=>true),error=>error.status===409);
  assert.equal(calls.filter(([url])=>url.endsWith('/message')).length,1);
});

test('real HTTP Workroom writes require admission and preserve task identity over app restart',async()=>{
  const dataDir='test/app03-workroom-'+randomUUID();let app=await startApp({dataDir});
  const query=async(route,{method='GET',body,proof={}}={})=>{
    const res=await fetch(app.url+route,{method,headers:{...proof,Origin:app.url,'Content-Type':'application/json'},...(body?{body:JSON.stringify(body)}:{})});
    return {status:res.status,body:await res.text(),cookie:res.headers.get('set-cookie')};
  };
  try{
    assert.equal((await query('/api/workroom')).status,401);
    const boot=await query('/api/trial-session/bootstrap',{method:'POST',body:{}});
    const proof={Cookie:boot.cookie.split(';')[0],'X-Trial-CSRF':JSON.parse(boot.body).csrfToken};
    const created=await query('/api/tasks',{method:'POST',body:{title:'Phone task'},proof});const task=JSON.parse(created.body).task;
    assert.equal((await query('/api/workroom/'+task.id,{method:'PATCH',body:metadata(),proof})).status,200);
    assert.equal((await query('/workroom.mjs')).status,200);
    await app.close();app=await startApp({dataDir});
    const boot2=await query('/api/trial-session/bootstrap',{method:'POST',body:{}});
    const proof2={Cookie:boot2.cookie.split(';')[0],'X-Trial-CSRF':JSON.parse(boot2.body).csrfToken};
    const list=JSON.parse((await query('/api/workroom',{proof:proof2})).body).tasks;
    assert.equal(list.length,1);assert.equal(list[0].id,task.id);assert.equal(list[0].workroom.project,'Phone build');
  }finally{await app.close();}
});

// Ordinary chat recovery and deliberate native-session rebinding are covered by
// relay-conversation.test.mjs, which exercises the current controller. The retired
// source-sliced chat refresh test asserted automatic rotation, now intentionally refused.
