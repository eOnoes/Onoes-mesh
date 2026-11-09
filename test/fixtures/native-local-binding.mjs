// Invoked only by the disposable native owner qualifier; stdout carries RPC frames.
import assert from 'node:assert/strict';
import {readFileSync,writeFileSync} from 'node:fs';
import {join} from 'node:path';
import {createHash} from 'node:crypto';
import {withNims} from '../../lib/nims-link.mjs';
import {createCodexClient} from '../../lib/codex-client.mjs';
import {createInterface} from 'node:readline';
import {openTaskStore} from '../../lib/task-store.mjs';
import {reconcileLocalSession,retireLocalSession} from '../../lib/workroom-local-sessions.mjs';
import {createTeamRunner} from '../../lib/workroom-automation.mjs';
import {writerQuiescenceBlockers} from '../../lib/workroom-claim-policy.mjs';

const root=process.argv[2],config=JSON.parse(readFileSync(join(root,'node-binding-config.json'),'utf8'));
const input=createInterface({input:process.stdin}),waiting=new Map(),counts={};let serial=0;
input.on('line',line=>{const frame=JSON.parse(line),pending=waiting.get(frame.id);if(!pending)return;waiting.delete(frame.id);
  if(frame.error)pending.reject(new Error(frame.error));else pending.resolve(frame.result);});
const rpc=(method,params)=>new Promise((resolve,reject)=>{const id=++serial;counts[method]=(counts[method]||0)+1;
  waiting.set(id,{resolve,reject});process.stdout.write(JSON.stringify({id,method,params})+'\n');});
const file=join(root,'mesh-local-binding.sqlite');let store=openTaskStore(file),liveReviewRelay;
try{
  let task=store.create({title:'Dedicated native binding fixture',description:'Create and verify only the synthetic artifacts declared in the locked plan; independent review must leave them unchanged.',owner:'echo'});
  task=store.workroom.save(task.id,{project:'synthetic',criteria:'Proof UTF-8 bytes must equal hex 4d657368206c6f63616c2073657373696f6e2070726f6f662e0a; valid module syntax exit 0, invalid syntax nonzero, exported localProof true',owner:'echo',team:'local_build',stage:'ready',revision:task.workroom?.revision??1});
  task=store.workroom.saveProgress(task.id,{goal:'Build and verify the declared synthetic proof artifacts against exact acceptance criteria',checklist:[{id:'proof',text:'Edit and verify the proof',status:'pending'}],
    result:'',evidence:'',reviewer:'',decision:'pending',revision:0,taskRevision:task.revision,briefRevision:task.workroom.revision});
  store.workroom.savePlan(task.id,{lead:'echo',spec:'Create local-session-proof.md with exact UTF-8 bytes hex 4d657368206c6f63616c2073657373696f6e2070726f6f662e0a (Mesh local session proof. followed by LF); local-build-proof.mjs exports localProof=true. Builder uses its three-test fixture verifier; independent reviewer verifies expected bytes, syntax outcomes and export using read-only equivalents.',workspace:config.workspace,allowedFiles:'local-session-proof.md; local-build-proof.mjs; verify-local-build.mjs; local-build-check.json; assignment-child-ready.json (fixture process marker only)',
    checks:'Builder: run verify-local-build.mjs with Node; it writes local-build-check.json and launches the qualified fixture child that writes assignment-child-ready.json. Reviewer: do not execute that mutating verifier; read the artifacts and independently run read-only Node equivalents: compare proof bytes against the exact expected hex, node --check the built module, verify deliberately invalid syntax returns nonzero without writing a file, and import local-build-proof.mjs to verify localProof is true. These independent checks satisfy review acceptance; no rewrite of build artifacts is required.',boundaries:'Synthetic fixture only',workerId:'echo',reviewerId:'nims',state:'locked',
    revision:task.plan?.revision??0,taskRevision:task.revision,briefRevision:task.workroom.revision,progressRevision:task.progress.revision});
  task=store.workroom.get(task.id);
  const agents=[{id:'echo',backend:'hermes',status:'idle',conversation_id:'native-local'},
    {id:'nims',backend:'codex',status:'idle',conversation_id:config.realNimsReview?'mesh-nims':'fixture-nims'}];
  store.workroom.automation.action(task.id,{action:'start',revision:0,planRevision:task.plan.revision,
    taskRevision:task.revision,briefRevision:task.workroom.revision,progressRevision:task.progress.revision},agents,config.workspace);
  const stage=store.workroom.automation.read(task.id),body={id:stage.workerSendId};
  const profile={profileRef:'fixture-echo-builder',identityRef:'fixture-native-principal',toolProfile:'build-check-v1',model:'mesh-local-fixture',baseUrl:config.endpoint,workspace:config.workspace};
  const initialRunner=createTeamRunner({workroom:store.workroom,root:config.workspace,
    relay:{agents:async()=>agents},intervalMs:600000,nativeWorker:{rpc,profileFor:()=>profile,
      credential:async()=>'synthetic-local-provider',authorized:()=>true}});
  // Parent commits the first native submission, then deliberately drops its reply.
  try{await initialRunner.tick();}finally{await initialRunner.close();}
  const before=store.workroom.localSessions.read(task.id,body.id);assert.equal(before.state,'submit_unknown');assert.equal(before.teamBound,1);
  store.close();store=openTaskStore(file);
  // Recover through the observation-only entry, without credentials or send payload.
  const recovery={workroom:store.workroom,taskId:task.id,sendId:body.id,rpc,
    authorized:saved=>saved.identityRef===profile.identityRef&&saved.profileRef===profile.profileRef};
  const observer=createTeamRunner({workroom:store.workroom,root:config.workspace,relay:{},intervalMs:600000,
    nativeObserver:{rpc,authorized:recovery.authorized}});
  let row;
  try{
   await observer.tick();row=store.workroom.localSessions.read(task.id,body.id);
  const deadline=Date.now()+60000;
  while(row.nativeStatus!=='terminal'||!row.resultHash){
    if(Date.now()>deadline)throw new Error('Native binding receipt did not settle');
    await new Promise(resolve=>setTimeout(resolve,30));await observer.tick();row=store.workroom.localSessions.read(task.id,body.id);
  }
  }finally{await observer.close();}
  const repeated=await reconcileLocalSession(recovery);
  assert.equal(repeated.processObservation.process_tree_ended,false);
  assert.ok(repeated.processObservation.active_processes>0);
  // Disposable line-bridge control only; this method is never sent to the native API.
  await rpc('mesh.fixture.release-child',{admission_id:row.admissionId});
  row=await reconcileLocalSession(recovery);
  assert.equal(row.processObservation.process_tree_ended,true);assert.equal(row.writerQuiescence,false);
  assert.equal(row.processObservation.authority_writes_drained,false);
  await rpc('mesh.fixture.release-write',{admission_id:row.admissionId});
  row=await reconcileLocalSession(recovery);
  for(const key of ['execution_closed','authority_writes_drained','worker_resources_idle'])assert.equal(row.processObservation[key],true);

  const persistedProcess=row.processObservation;store.close();store=openTaskStore(file);
  assert.deepEqual(store.workroom.localSessions.read(task.id,body.id).processObservation,persistedProcess);

  const build=JSON.parse(readFileSync(join(config.workspace,'local-build-check.json'),'utf8'));
  assert.equal(build.syntaxExitCode,0);assert.notEqual(build.invalidSyntaxExitCode,0);assert.ok(Number.isInteger(build.invalidSyntaxExitCode));assert.ok(Number.isSafeInteger(build.checkerPid));
  assert.equal(readFileSync(join(config.workspace,'local-build-proof.mjs'),'utf8'),'export const localProof = true;\n');
  assert.equal(repeated.resultHash,row.resultHash);
  const imported=store.workroom.get(task.id);assert.equal(imported.agentUpdates.length,1);
  const offer=imported.agentUpdates[0];assert.equal(offer.sendId,body.id);assert.equal(offer.messageId,row.resultMessageId);
  assert.equal(offer.applied,false);assert.equal(imported.replies.length,1);
  assert.throws(()=>store.workroom.applyAgentUpdate(task.id,{sendId:offer.sendId,messageId:offer.messageId,hash:offer.hash,
    revision:imported.progress.revision,taskRevision:imported.revision,briefRevision:imported.workroom.revision}),/retirement verification/);
  assert.equal(row.nativeOutcome,'completed');assert.equal(row.profileContract.closed,true);
  row=await retireLocalSession({...recovery,workroom:store.workroom,admitted:()=>true});
  assert.equal(row.writerQuiescence,true);assert.match(row.retirementHash,/^[a-f0-9]{64}$/);
  const current=store.workroom.get(task.id);
  store.workroom.applyAgentUpdate(task.id,{sendId:offer.sendId,messageId:offer.messageId,hash:offer.hash,
    revision:current.progress.revision,taskRevision:current.revision,briefRevision:current.workroom.revision});
  const resumed=store.workroom.get(task.id);
  store.workroom.automation.action(task.id,{action:'resume',revision:resumed.automation.revision,
    planRevision:resumed.plan.revision,taskRevision:resumed.revision,briefRevision:resumed.workroom.revision,
    progressRevision:resumed.progress.revision},agents,config.workspace);
  const reviewSends=[];
  let reviewRelay;
  let reviewEvidence;
  if(config.realNimsReview){
    const client=createCodexClient({root:config.workspace});
    liveReviewRelay=withNims({agents:async()=>[agents[0]],snapshot:async()=>({}),nativeRead:async()=>{throw Error('Unexpected non-Nims read');},close:async()=>{}},{root:config.workspace,workroom:store.workroom,client});
    writeFileSync(join(root,'nims-connection-evidence.json'),JSON.stringify(await liveReviewRelay.snapshot(),null,2));
    reviewRelay={...liveReviewRelay,taskMessage:async(message,admitted)=>{reviewSends.push(message);return liveReviewRelay.taskMessage(message,admitted);}};
    reviewEvidence={client};
  }else reviewRelay={agents:async()=>agents,nativeRead:async()=>({taskSessionBinding:1,messages:[]}),
    taskMessage:async message=>{assert.equal(message.agentId,'nims');assert.match(message.text,/Phase: review/);assert.match(message.text,/Read-only tools only/);reviewSends.push(message);}};
  const checkedFiles=['local-session-proof.md','local-build-proof.mjs','verify-local-build.mjs','local-build-check.json'];
  const fileHashes=()=>Object.fromEntries(checkedFiles.map(name=>[name,createHash('sha256').update(readFileSync(join(config.workspace,name))).digest('hex')]));
  const beforeReview=fileHashes();
  const handoff=createTeamRunner({workroom:store.workroom,root:config.workspace,relay:reviewRelay,intervalMs:600000});
  try{
    await handoff.tick();await handoff.tick();
    if(config.realNimsReview){
      const deadline=Date.now()+75000;
      while(store.workroom.get(task.id).automation.state==='active'){
        if(Date.now()>deadline)throw Error('Real Nims review did not reach a confirmed result');
        await new Promise(resolve=>setTimeout(resolve,250));await handoff.tick();
      }
      const reviewed=store.workroom.get(task.id),run=store.workroom.nims.get(stage.reviewerSendId);
      assert.equal(reviewed.automation.state,'needs_review');assert.equal(run.state,'completed');
      assert.equal(reviewed.agentReviews.length,1);assert.equal(reviewed.agentReviews[0].sendId,stage.reviewerSendId);
      const native=await reviewEvidence.client.readThread(run.threadId),turn=native.thread.turns.find(item=>item.id===run.turnId);
      assert.equal(turn.status,'completed');assert.deepEqual(fileHashes(),beforeReview);
      const commands=turn.items.filter(item=>item.type==='commandExecution').map(item=>({command:item.command,status:item.status,exitCode:item.exitCode,sourceReadInOutput:typeof item.aggregatedOutput==='string'&&item.aggregatedOutput.includes('export const localProof = true;')}));
      assert.ok(commands.some(item=>item.sourceReadInOutput&&item.exitCode===0));
      const itemTypes=turn.items.map(item=>item.type);assert.equal(itemTypes.some(type=>/mcp|fileChange/i.test(type)),false);
      reviewEvidence={qualification:'PASS',taskId:task.id,sendId:stage.reviewerSendId,threadId:run.threadId,turnId:run.turnId,
        status:turn.status,itemTypes,commands,review:reviewed.agentReviews[0],before:beforeReview,after:fileHashes(),realNimsTransport:true};
      writeFileSync(join(root,'nims-review-evidence.json'),JSON.stringify(reviewEvidence,null,2));
    }
  }finally{await handoff.close();if(liveReviewRelay){await liveReviewRelay.close();liveReviewRelay=null;}}
  assert.equal(reviewSends.length,1);assert.equal(reviewSends[0].id,stage.reviewerSendId);
  assert.equal(store.workroom.get(task.id).automation.phase,'reviewer');
  assert.equal(repeated.admissionId,row.admissionId);assert.equal(counts['session.create'],1);assert.equal(counts['prompt.submit'],1);
  assert.equal(row.writerQuiescence,true);assert.equal(writerQuiescenceBlockers(store.workroom.list()).length>0,!config.realNimsReview);
  assert.equal(JSON.stringify(store.workroom.get(task.id)).includes('synthetic-local-provider'),false);
  const report={qualification:'PASS',taskId:task.id,sendId:body.id,createRequestId:row.createRequestId,submissionId:row.submissionId,
    sessionId:row.sessionId,admissionId:row.admissionId,nativeProfileId:row.nativeProfileId,nativeEpoch:row.nativeEpoch,
    nativeGeneration:row.nativeGeneration,nativeStatus:row.nativeStatus,rpcCounts:counts,restartedBeforeReadback:true,observationOnlyRecovery:true,teamRunnerObservation:true,automaticTeamDispatch:true,terminalResultImported:true,buildCheckVerified:true,processReadbackPersisted:true,authorityDrainObserved:true,executionClosedObserved:true,resultHash:row.resultHash,resultMessageId:row.resultMessageId,
    workspaceStillHeld:!config.realNimsReview,writerQuiescence:true,retirementHash:row.retirementHash,reviewSentToNims:true,reviewTransportSynthetic:!config.realNimsReview,realNimsReviewCompleted:!!config.realNimsReview,liveActivation:false};
  writeFileSync(join(root,'mesh-local-binding-evidence.json'),JSON.stringify(report,null,2));
  await new Promise(resolve=>process.stdout.write(JSON.stringify({done:true,admissionId:row.admissionId})+'\n',resolve));
}finally{if(liveReviewRelay)await liveReviewRelay.close();store.close();input.close();process.stdin.pause();}
