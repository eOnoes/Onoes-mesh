import test from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';
import {openTaskStore} from '../lib/task-store.mjs';
import {readFileSync,writeFileSync,existsSync} from 'node:fs';
import {join,dirname} from 'node:path';
import {createHash} from 'node:crypto';
import {prepareGuideTeamPilot,validateGuideTeamPilot,runGuideTeamPilot,readPilotReviewPayload,reviewedNativeBaseline} from '../integrations/guide-team-pilot.mjs';

const baselineFixture=()=>{
 const header={'gateway/session_controls.py':'old-controls','tui_gateway/contracts/canonical.py':'old-contract','unchanged.py':'unchanged'};
 const capability={baselineHashes:{'gateway/session_controls.py':'old-controls','tui_gateway/contracts/canonical.py':'old-contract'},candidateHashes:{'gateway/session_controls.py':'new-controls','tui_gateway/contracts/canonical.py':'new-contract'}};
 return {header,capability,deployment:{installed:true,processScopeSupported:true,installedSourceFiles:{...header,...capability.candidateHashes}}};
};
test('new pilot uses only the reviewed deployed patch and retains unchanged native hashes',()=>{
 const f=baselineFixture(),original=structuredClone(f.header);
 assert.deepEqual(reviewedNativeBaseline(f.header,f.capability,f.deployment),f.deployment.installedSourceFiles);
 assert.deepEqual(f.header,original);
});
test('uninstalled, unverified, stale or broadened native baselines cannot prepare a live trial',()=>{
 for(const change of [f=>f.deployment.installed=false,f=>f.deployment.processScopeSupported='true',f=>f.deployment.installedSourceFiles=f.header,f=>f.capability.baselineHashes['gateway/session_controls.py']='other',f=>f.capability.candidateHashes['unreviewed.py']='new']){
  const f=baselineFixture();change(f);assert.throws(()=>reviewedNativeBaseline(f.header,f.capability,f.deployment));
 }
});

test('preparation submits nothing; missing approval cannot create an attempt or connection',async()=>{
  const ready=prepareGuideTeamPilot({fixture:true}),p=validateGuideTeamPilot(ready.path);
  assert.equal(p.limits.builderAttempts,1);assert.equal(p.limits.reviewerAttempts,1);assert.equal(p.limits.automaticRetries,false);
  assert.equal(p.limits.builderMaxTurns,50);assert.equal(existsSync(join(dirname(ready.path),'attempt.json')),false);
  await assert.rejects(runGuideTeamPilot(ready.path),/Separate owner approval/);
  await assert.rejects(runGuideTeamPilot(ready.path,{ownerApproved:true}),/exact approved scope hash/);
  assert.equal(existsSync(join(dirname(ready.path),'attempt.json')),false);
});

test('prepared anchored patch preserves every original byte and exact newline placement',()=>{
 const ready=prepareGuideTeamPilot({fixture:true}),p=validateGuideTeamPilot(ready.path);
 const store=openTaskStore(join(dirname(ready.path),'tasks.sqlite'));let task;
 try{task=store.workroom.get(p.taskId);}finally{store.close();}
 const patch=JSON.parse(task.plan.spec.split('Exact patch JSON: ')[1].split('\n')[0]);
 const original=readFileSync(join(p.workspace,'MESH-QUICK-START.md'));
 assert.equal(patch.mode,'replace');assert.equal(patch.path,'MESH-QUICK-START.md');
 assert.equal(original.toString('utf8').split(patch.old_string).length,2);
 assert.equal(patch.new_string,patch.old_string+p.suffix);
 const actual=Buffer.from(original.toString('utf8').replace(patch.old_string,patch.new_string));
 assert.deepEqual(actual,Buffer.concat([original,Buffer.from(p.suffix)]));
 assert.equal(createHash('sha256').update(actual).digest('hex'),p.expectedSha256);
 assert.match(task.plan.checks,/report the existing step as blocked/);
 assert.equal(existsSync(join(dirname(ready.path),'attempt.json')),false);
});

test('changed guide and task/source intent cannot pass the prepared scope check',()=>{
  const ready=prepareGuideTeamPilot({fixture:true}),p=validateGuideTeamPilot(ready.path);
  writeFileSync(join(p.workspace,'MESH-QUICK-START.md'),'changed');
  assert.throws(()=>validateGuideTeamPilot(ready.path),/Prepared copy changed/);
  const another=prepareGuideTeamPilot({fixture:true}),intent=JSON.parse(readFileSync(another.path,'utf8'));
  intent.profile.model='different';writeFileSync(another.path,JSON.stringify(intent));
  assert.throws(()=>validateGuideTeamPilot(another.path),/Pilot scope changed/);
});

for(const incomplete of [false,true])test(incomplete?'actual server pauses a retired incomplete native report without importing or dispatching review':'actual server pilot builds once, retires, reviews once and reloads without recording owner approval',{timeout:60000},async()=>{
  const ready=prepareGuideTeamPilot({fixture:true}),p=validateGuideTeamPilot(ready.path),file=join(p.workspace,'MESH-QUICK-START.md');
  const token='disposable-pilot-token',tokenFile=join(dirname(ready.path),'synthetic-key');writeFileSync(tokenFile,token);
  const messages=[],calls=[];let submitted=false,request,workerPosts=0,reviewPosts=0,now=Date.now();
  const peer=http.createServer(async(req,res)=>{
    res.setHeader('Content-Type','application/json');
    if(req.headers.authorization!=='Bearer '+token){res.writeHead(401);res.end('{}');return;}
    if(req.url==='/api/agents'&&req.method==='GET'){res.end(JSON.stringify([
      {id:'echo',backend:'hermes',status:'idle',conversation_id:'fixture-echo'},
      {id:'nims',backend:'codex',status:'idle',conversation_id:'fixture-nims'}]));return;}
    if(req.url==='/api/nims/capabilities'||req.url==='/api/mesh-capabilities'){res.end('{"taskSessionBinding":1}');return;}
    if(req.url==='/api/agents/nims/sessions/fixture-nims/messages'){res.end(JSON.stringify({messages}));return;}
    if(req.method==='POST'&&req.url==='/api/agents/nims/message'){
      reviewPosts++;let text='';for await(const chunk of req)text+=chunk;const body=JSON.parse(text);
      const actual=createHash('sha256').update(readFileSync(file)).digest('hex');
      const review={schema:'workroom-review/v1',taskId:p.taskId,sendId:body.id,verdict:actual===p.expectedSha256?'approved':'changes_requested',
        summary:'Independent synthetic read verified exact guide bytes',evidence:'SHA-256 '+actual};
      messages.push({id:body.id,k:'you',t:body.text},{id:body.id+'-review',k:'ag',t:'```workroom-review\n'+JSON.stringify(review)+'\n```'});
      res.end('{"ok":true}');return;
    }
    if(req.method==='POST')workerPosts++;res.writeHead(503);res.end('{}');
  });
  await new Promise(resolve=>peer.listen(0,'127.0.0.1',resolve));
  const sid='local-'+'a'.repeat(64),aid='b'.repeat(32),profileId='synthetic-pilot';
  const contract={model:p.profile.model,provider:'openai-codex',base_url:null,workspace:p.workspace,toolsets:['file'],
    safe_mode:true,ignore_user_config:true,follow_profile:false,source:'tool',max_turns:50,terminal_backend:'local',closed:true,api_key_configured:false};
  const fixture={source:'disposable_fixture',relayUrl:'http://127.0.0.1:'+peer.address().port,tokenFile,sessionNow:()=>now,
    connected:async value=>{request=value.request;},rpc:async(method,params)=>{
      calls.push(method);
      if(method==='session.create')return {session_id:sid};
      if(method==='prompt.submit'){
        assert.equal(submitted,false);submitted=true;now+=300001;writeFileSync(file,Buffer.concat([readFileSync(file),Buffer.from(incomplete?p.suffix.slice(1):p.suffix)]));return {};
      }
      assert.equal(method,'prompt.lookup');
      if(!submitted)return {found:false,session_id:params.session_id,submission_id:params.submission_id,outcome:null,profile_contract:contract,process_scope_supported:true};
      const task=(await request('/api/workroom/'+p.taskId)).task;
      const update={schema:'workroom-update/v1',taskId:p.taskId,sendId:task.automation.workerSendId,goal:task.progress.goal,
        checklist:task.progress.checklist.map(s=>({...s,status:incomplete?'pending':'done'})),result:incomplete?'Read-back has a byte-length mismatch':'Exact append made to guide copy',evidence:'Synthetic native file operation'};
      return {found:true,session_id:params.session_id,submission_id:params.submission_id,outcome:'completed',profile_contract:contract,process_scope_supported:true,
        receipt:{admission_id:aid,ref:{profile_id:profileId,session_id:sid},authority_epoch:1,execution_generation:1,status:'terminal',
          result:{final_response:'```workroom-update\n'+JSON.stringify(update)+'\n```'}},
        process_scope:{admission_id:aid,session_id:sid,profile_id:profileId,execution_generation:1,authority_epoch:1,
          sealed:true,state:'ended',active_processes:0,root_ended:true,process_tree_ended:true,termination_requested:false,
          writer_quiescence:false,execution_closed:true,authority_writes_drained:true,worker_resources_idle:true}};
    }};
  try {
    if(incomplete){
      await assert.rejects(runGuideTeamPilot(ready.path,{fixture,deadlineMs:40000}),/Pilot not complete/);
      const result=JSON.parse(readFileSync(join(dirname(ready.path),'result.json'),'utf8')),task=result.task;
      assert.equal(result.qualification,'HELD');assert.equal(task.automation.state,'paused');
      assert.match(task.automation.reason,/finished with an incomplete report/);
      assert.equal(task.messages.length,1);assert.equal(task.messages[0].nativeLocal.writerQuiescence,true);
      assert.equal(task.messages[0].nativeLocal.nativeOutcome,'completed');
      assert.equal(task.agentUpdates.length,1);assert.equal(task.agentUpdates[0].applied,false);
      assert.equal(task.progress.checklist[0].status,'pending');assert.equal(task.progress.result,'');
      assert.equal(task.plan.state,'locked');assert.equal(task.agentReviews.length,0);
      assert.equal(task.progress.decision,'pending');assert.notEqual(task.status,'done');
      assert.equal(calls.filter(c=>c==='session.create').length,1);assert.equal(calls.filter(c=>c==='prompt.submit').length,1);
      assert.equal(workerPosts,0);assert.equal(reviewPosts,0);
      const before=calls.length;await assert.rejects(runGuideTeamPilot(ready.path,{fixture}),/already has an attempt/);assert.equal(calls.length,before);
      return;
    }
    const result=await runGuideTeamPilot(ready.path,{fixture,deadlineMs:40000});
    assert.equal(result.qualification,'PASS');assert.equal(result.source,'disposable_fixture');
    assert.equal(result.worker.writerQuiescence,true);assert.equal(result.reviewer.independentNativeReviewQualified,false);
    assert.equal(result.preservedAcrossRestart,true);assert.equal(result.ownerReviewRecorded,false);assert.equal(result.done,false);
    assert.equal(calls.filter(c=>c==='session.create').length,1);assert.equal(calls.filter(c=>c==='prompt.submit').length,1);
    assert.equal(workerPosts,0);assert.equal(reviewPosts,1);
    assert.equal(readPilotReviewPayload(p,messages[0].id),messages[0].t);
    assert.throws(()=>readPilotReviewPayload(p,'different-send'));
    const before=calls.length;await assert.rejects(runGuideTeamPilot(ready.path,{fixture}),/already has an attempt/);assert.equal(calls.length,before);
    assert.throws(()=>validateGuideTeamPilot(ready.path),/already has an attempt/);
    assert.equal(JSON.parse(readFileSync(join(dirname(ready.path),'result.json'),'utf8')).qualification,'PASS');
  } finally {peer.closeAllConnections();await new Promise(resolve=>peer.close(resolve));}
});

test('expired access records its actual HTTP status without dispatch or malformed-JSON errors',async()=>{
  const ready=prepareGuideTeamPilot({fixture:true});let now=Date.now(),calls=0;
  const fixture={source:'disposable_fixture',relayUrl:'http://127.0.0.1:9',tokenFile:join(dirname(ready.path),'unused'),
    sessionNow:()=>now,connected:()=>{now+=600001;},rpc:()=>{calls++;throw Error('No native call expected');}};
  await assert.rejects(runGuideTeamPilot(ready.path,{fixture}),/Pilot HTTP 401/);
  assert.equal(calls,0);
  const result=JSON.parse(readFileSync(join(dirname(ready.path),'result.json'),'utf8'));
  assert.equal(result.qualification,'HELD');assert.match(result.reason,/HTTP 401/);
});

test('unenrolled or untyped process capability stops the team before any model submission',{timeout:60000},async()=>{
  const peer=http.createServer((req,res)=>{res.setHeader('Content-Type','application/json');
    if(req.url==='/api/agents'){res.end(JSON.stringify([{id:'echo',backend:'hermes',status:'idle',conversation_id:'fixture-echo'},
      {id:'nims',backend:'codex',status:'idle',conversation_id:'fixture-nims'}]));return;}
    res.writeHead(503);res.end('{}');});
  await new Promise(resolve=>peer.listen(0,'127.0.0.1',resolve));
  try {
    for(const capability of [undefined,false,'true']){
      const ready=prepareGuideTeamPilot({fixture:true}),p=validateGuideTeamPilot(ready.path),calls=[];
      const key=join(dirname(ready.path),'synthetic-key');writeFileSync(key,'fixture-only');
      const fixture={source:'disposable_fixture',relayUrl:'http://127.0.0.1:'+peer.address().port,tokenFile:key,rpc:async(method,params)=>{
        calls.push(method);if(method==='session.create')return {session_id:'local-'+'c'.repeat(64)};
        assert.equal(method,'prompt.lookup');
        return {found:false,session_id:params.session_id,submission_id:params.submission_id,outcome:null,process_scope_supported:capability,
          profile_contract:{model:p.profile.model,provider:'openai-codex',base_url:null,workspace:p.workspace,toolsets:['file'],safe_mode:true,
            ignore_user_config:true,follow_profile:false,source:'tool',max_turns:50,terminal_backend:'local',closed:true,api_key_configured:false}};
      }};
      await assert.rejects(runGuideTeamPilot(ready.path,{fixture,deadlineMs:10000}));
      assert.equal(calls.filter(m=>m==='session.create').length,1);assert.equal(calls.includes('prompt.submit'),false);
    }
  } finally {peer.closeAllConnections();await new Promise(resolve=>peer.close(resolve));}
});
