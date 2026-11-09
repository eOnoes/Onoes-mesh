// Invoked only by the disposable native owner qualifier; stdout carries RPC frames.
import assert from 'node:assert/strict';
import {randomUUID} from 'node:crypto';
import {readFileSync,writeFileSync} from 'node:fs';
import {join} from 'node:path';
import {createInterface} from 'node:readline';
import {openTaskStore} from '../../lib/task-store.mjs';
import {dispatchLocalSession} from '../../lib/workroom-local-sessions.mjs';
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
  store.workroom.savePlan(task.id,{lead:'echo',spec:'Synthetic file edit',workspace:config.workspace,allowedFiles:'local-session-proof.md',
    checks:'Read back exact bytes',boundaries:'Synthetic fixture only',workerId:'echo',reviewerId:'nims',state:'locked',
    revision:task.plan?.revision??0,taskRevision:task.revision,briefRevision:task.workroom.revision,progressRevision:task.progress.revision});
  task=store.workroom.get(task.id);
  const body={id:randomUUID(),agentId:'echo',conversationId:'native-local',text:'Implement only the locked synthetic file edit.'};
  const profile={profileRef:'fixture-echo-builder',identityRef:'fixture-native-principal',model:'mesh-local-fixture',baseUrl:config.endpoint,workspace:config.workspace};
  const options={taskId:task.id,body,profile,rpc,credential:async()=>'synthetic-local-provider',admitted:()=>true};
  // Parent commits the first native submission, then deliberately drops its reply.
  await assert.rejects(dispatchLocalSession({...options,workroom:store.workroom}),/uncertain/);
  const before=store.workroom.localSessions.read(task.id,body.id);assert.equal(before.state,'submit_unknown');
  store.close();store=openTaskStore(file);
  let row=await dispatchLocalSession({...options,workroom:store.workroom});
  const deadline=Date.now()+60000;
  while(row.nativeStatus!=='terminal'){
    if(Date.now()>deadline)throw new Error('Native binding receipt did not settle');
    await new Promise(resolve=>setTimeout(resolve,30));row=await dispatchLocalSession({...options,workroom:store.workroom});
  }
  const repeated=await dispatchLocalSession({...options,workroom:store.workroom});
  assert.equal(repeated.admissionId,row.admissionId);assert.equal(counts['session.create'],1);assert.equal(counts['prompt.submit'],1);
  assert.equal(row.writerQuiescence,false);assert.ok(writerQuiescenceBlockers(store.workroom.list()).length>0);
  assert.equal(JSON.stringify(store.workroom.get(task.id)).includes('synthetic-local-provider'),false);
  const report={qualification:'PASS',taskId:task.id,sendId:body.id,createRequestId:row.createRequestId,submissionId:row.submissionId,
    sessionId:row.sessionId,admissionId:row.admissionId,nativeProfileId:row.nativeProfileId,nativeEpoch:row.nativeEpoch,
    nativeGeneration:row.nativeGeneration,nativeStatus:row.nativeStatus,rpcCounts:counts,restartedBeforeReadback:true,
    workspaceStillHeld:true,writerQuiescence:false,liveActivation:false};
  writeFileSync(join(root,'mesh-local-binding-evidence.json'),JSON.stringify(report,null,2));
  await new Promise(resolve=>process.stdout.write(JSON.stringify({done:true,admissionId:row.admissionId})+'\n',resolve));
}finally{store.close();input.close();process.stdin.pause();}
