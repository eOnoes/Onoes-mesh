// Invoked only by the disposable native owner qualifier; stdout carries RPC frames.
import assert from 'node:assert/strict';
import {readFileSync,writeFileSync} from 'node:fs';
import {join} from 'node:path';
import {createInterface} from 'node:readline';
import {openTaskStore} from '../../lib/task-store.mjs';
import {reconcileLocalSession} from '../../lib/workroom-local-sessions.mjs';
import {createTeamRunner} from '../../lib/workroom-automation.mjs';
import {writerQuiescenceBlockers} from '../../lib/workroom-claim-policy.mjs';

const root=process.argv[2],config=JSON.parse(readFileSync(join(root,'node-binding-config.json'),'utf8'));
const input=createInterface({input:process.stdin}),waiting=new Map(),counts={};let serial=0;
input.on('line',line=>{const frame=JSON.parse(line),pending=waiting.get(frame.id);if(!pending)return;waiting.delete(frame.id);
  if(frame.error)pending.reject(new Error(frame.error));else pending.resolve(frame.result);});
const rpc=(method,params)=>new Promise((resolve,reject)=>{const id=++serial;counts[method]=(counts[method]||0)+1;
  waiting.set(id,{resolve,reject});process.stdout.write(JSON.stringify({id,method,params})+'\n');});
const file=join(root,'mesh-local-binding.sqlite');let store=openTaskStore(file);
try{
  let task=store.create({title:'Dedicated native binding fixture',description:'Edit only local-session-proof.md.',owner:'echo'});
  task=store.workroom.save(task.id,{project:'synthetic',criteria:'Exact proof bytes',owner:'echo',team:'local_build',stage:'ready',revision:task.workroom?.revision??1});
  task=store.workroom.saveProgress(task.id,{goal:'Edit the single synthetic proof file',checklist:[{id:'proof',text:'Edit and verify the proof',status:'pending'}],
    result:'',evidence:'',reviewer:'',decision:'pending',revision:0,taskRevision:task.revision,briefRevision:task.workroom.revision});
  store.workroom.savePlan(task.id,{lead:'echo',spec:'Synthetic file edit',workspace:config.workspace,allowedFiles:'local-session-proof.md; local-build-proof.mjs; verify-local-build.mjs; local-build-check.json',
    checks:'Run the fixture verify-local-build.mjs with Node, checking local-build-proof.mjs syntax; read back exact bytes',boundaries:'Synthetic fixture only',workerId:'echo',reviewerId:'nims',state:'locked',
    revision:task.plan?.revision??0,taskRevision:task.revision,briefRevision:task.workroom.revision,progressRevision:task.progress.revision});
  task=store.workroom.get(task.id);
  const agents=[{id:'echo',backend:'hermes',status:'idle',conversation_id:'native-local'},
    {id:'nims',backend:'codex',status:'idle',conversation_id:'fixture-nims'}];
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
  assert.equal(repeated.admissionId,row.admissionId);assert.equal(counts['session.create'],1);assert.equal(counts['prompt.submit'],1);
  assert.equal(row.writerQuiescence,false);assert.ok(writerQuiescenceBlockers(store.workroom.list()).length>0);
  assert.equal(JSON.stringify(store.workroom.get(task.id)).includes('synthetic-local-provider'),false);
  const report={qualification:'PASS',taskId:task.id,sendId:body.id,createRequestId:row.createRequestId,submissionId:row.submissionId,
    sessionId:row.sessionId,admissionId:row.admissionId,nativeProfileId:row.nativeProfileId,nativeEpoch:row.nativeEpoch,
    nativeGeneration:row.nativeGeneration,nativeStatus:row.nativeStatus,rpcCounts:counts,restartedBeforeReadback:true,observationOnlyRecovery:true,teamRunnerObservation:true,automaticTeamDispatch:true,terminalResultImported:true,buildCheckVerified:true,processReadbackPersisted:true,resultHash:row.resultHash,resultMessageId:row.resultMessageId,
    workspaceStillHeld:true,writerQuiescence:false,liveActivation:false};
  writeFileSync(join(root,'mesh-local-binding-evidence.json'),JSON.stringify(report,null,2));
  await new Promise(resolve=>process.stdout.write(JSON.stringify({done:true,admissionId:row.admissionId})+'\n',resolve));
}finally{store.close();input.close();process.stdin.pause();}
