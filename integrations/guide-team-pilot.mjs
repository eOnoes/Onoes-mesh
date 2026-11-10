import {readFileSync,writeFileSync,mkdirSync,lstatSync,readdirSync,appendFileSync,existsSync} from 'node:fs';
import {join,resolve,dirname} from 'node:path';
import {fileURLToPath} from 'node:url';
import {createHash,randomUUID} from 'node:crypto';
import {DatabaseSync} from 'node:sqlite';
import assert from 'node:assert/strict';
import {startApp,ROOT} from '../server.mjs';
import {openTaskStore} from '../lib/task-store.mjs';
import {nativeGatewayWorkerOptions} from '../lib/native-gateway-transport.mjs';
import {createCodexClient} from '../lib/codex-client.mjs';

const sha=value=>createHash('sha256').update(value).digest('hex');
const fingerprint=t=>sha(JSON.stringify({id:t.id,title:t.title,description:t.description,status:t.status,
  workroom:t.workroom,progress:t.progress,plan:t.plan}));
const codeFiles=['server.mjs','lib/workroom-native-binding.mjs','lib/native-gateway-transport.mjs',
  'lib/workroom-local-sessions.mjs','lib/workroom-automation.mjs','lib/nims-link.mjs','lib/codex-client.mjs',
  'integrations/native_gateway_transport.py','integrations/guide-team-pilot.mjs'];
const home='C:/Users/eMitchell109/AppData/Local/hermes';
const runtime={home,nativeRoot:home+'/hermes-agent',pythonExecutable:home+'/tools/python-3.14.9+20261021-win32-x64/python.exe'};
const suffix="\n\n## Verified phone recovery\n\nBackground/resume, rotation with an unsaved draft, and network reconnection were confirmed on Eddie's phone. Reopening the completed guide still showed Done.\n";
const hashFile=path=>sha(readFileSync(path));
function owned(path) {
  const relative=resolve(path).slice(ROOT.length+1);
  assert.equal(resolve(ROOT,relative),resolve(path));assert.ok(resolve(path).startsWith(ROOT+'/')||resolve(path).startsWith(ROOT+'\\'));
  let next=ROOT;
  for(const part of relative.split(/[\\/]/)){next=join(next,part);assert.equal(lstatSync(next).isSymbolicLink(),false,'Pilot paths cannot contain links');}
}
function nativeHashes() {
  const expected=JSON.parse(readFileSync(join(ROOT,'integrations/native-header-fixture-qualification.json'),'utf8')).candidateFiles;
  for(const [path,digest] of Object.entries(expected))assert.equal(hashFile(join(runtime.nativeRoot,path)),digest,'Installed native bridge changed: '+path);
  return expected;
}
export function prepareGuideTeamPilot({fixture=false}={}) {
  const id=randomUUID(),dataDir='data/guide-team-state-'+id,workspace=join(ROOT,'data','guide-team-work-'+id);
  mkdirSync(workspace);mkdirSync(join(ROOT,dataDir));owned(workspace);owned(join(ROOT,dataDir));
  const original=readFileSync(join(ROOT,'MESH-QUICK-START.md'));
  assert.ok(original.length<65536);assert.equal(original.includes(Buffer.from(suffix)),false);
  writeFileSync(join(workspace,'MESH-QUICK-START.md'),original,{flag:'wx'});
  const beforeSha256=sha(original),expectedSha256=sha(Buffer.concat([original,Buffer.from(suffix)]));
  const store=openTaskStore(join(ROOT,dataDir,'tasks.sqlite'));let task;
  try {
    task=store.create({title:'Guide team pilot — phone recovery notes',description:'One isolated guide-copy build followed by one independent review. No live app changes.',owner:'echo'});
    task=store.workroom.save(task.id,{project:'Onoes-Mesh pilot',criteria:'Preserve every original byte; append only the exact supplied recovery note; independent review approves.',owner:'echo',team:'local_build',stage:'ready',revision:1});
    task=store.workroom.saveProgress(task.id,{goal:'Append the verified phone recovery note to the isolated guide copy and independently verify the exact result.',
      checklist:[{id:'guide',text:'Append exactly the supplied note and read the guide copy back',status:'pending'}],result:'',evidence:'',reviewer:'',decision:'pending',revision:0,taskRevision:task.revision,briefRevision:task.workroom.revision});
    task=store.workroom.savePlan(task.id,{lead:'echo',spec:'Append EXACTLY the decoded UTF-8 value of this JSON string to MESH-QUICK-START.md: '+JSON.stringify(suffix)+'. Append BOTH leading newline characters even if the existing file already ends in a newline. Preserve all original '+original.length+' bytes. Expected final length '+(original.length+Buffer.byteLength(suffix))+' bytes. Expected complete-file SHA-256: '+expectedSha256,
      workspace,allowedFiles:'MESH-QUICK-START.md',checks:'Builder: append the exact text using file tools, then read it back. Do not claim an unavailable SHA/terminal/directory check; those checks belong to the independent reviewer and host, not your worker checklist. Reviewer and host: independently verify all original bytes plus the exact append, final SHA-256 '+expectedSha256+', and no other files in the workspace. Reviewer may use read-only commands; do not write a checker or any file.',
      boundaries:'Guide-copy-only qualification. No other files, databases, memory, credentials, external messages, workers, service operations, commits, purchases or scope expansion. Ask if unclear. Builder file tools only; Nims independently reviews read-only. Do not mark Done or record owner approval.',
      workerId:'echo',reviewerId:'nims',state:'locked',revision:0,taskRevision:task.revision,briefRevision:task.workroom.revision,progressRevision:task.progress.revision}).task;
  } finally {store.close();}
  const intent={schema:'mesh-guide-team-pilot/v1',id,preparedAt:new Date().toISOString(),fixture,dataDir,workspace,taskId:task.id,
    beforeSha256,expectedSha256,originalBytes:original.length,suffix,preparedTaskSha256:fingerprint(task),
    sourceHashes:Object.fromEntries(codeFiles.map(file=>[file,hashFile(join(ROOT,file))])),nativeImplementationHashes:fixture?{}:nativeHashes(),
    profile:{profileRef:'guide-pilot-'+id,identityRef:'guide-pilot-'+id,provider:'openai-codex',model:'gpt-6-luna',workspace},
    limits:{builderAttempts:1,builderMaxTurns:50,builderTools:['file'],reviewerAttempts:1,reviewer:'nims',reviewerMode:'read-only',automaticRetries:false,automaticDone:false}};
  intent.scopeHash=sha(JSON.stringify(intent));
  const path=join(ROOT,dataDir,'pilot.json');writeFileSync(path,JSON.stringify(intent,null,2)+'\n',{flag:'wx'});
  writeFileSync(join(ROOT,dataDir,'REVIEW.txt'),`Onoes-Mesh guide team trial — PREPARED ONLY\n\nScope: ${intent.scopeHash}\nWorkspace: ${workspace}\nOnly editable file: MESH-QUICK-START.md\nOne Echo-role native Codex build (gpt-6-luna, file tools only, 50-turn ceiling), then one existing Nims read-only review (current configured Codex model, 180-second connector turn deadline). Existing ChatGPT Codex sign-in; no API-key billing.\nNo retries or automatic Done. Isolated board; no live board changes, service restart, Rook/Mind activation or production enrollment.\n\nExact append:${suffix}\nOriginal SHA-256: ${beforeSha256}\nExpected final SHA-256: ${expectedSha256}\n\nLive execution requires separate owner approval. Preparing this copied no credentials and submitted no model work.\n`,{flag:'wx'});
  return {path,review:join(ROOT,dataDir,'REVIEW.txt'),scopeHash:intent.scopeHash};
}

function checkPreparedTask(p) {
  const store=openTaskStore(join(ROOT,p.dataDir,'tasks.sqlite'));
  try {assert.equal(fingerprint(store.workroom.get(p.taskId)),p.preparedTaskSha256,'Prepared task changed');}finally{store.close();}
}
export function validateGuideTeamPilot(path,{readTask=true}={}) {
  if(existsSync(join(dirname(resolve(path)),'attempt.json')))
    throw Error('This pilot already has an attempt. Inspect its saved identities without reopening its writer store.');
  owned(path);const bytes=readFileSync(path);assert.ok(bytes.length<1048576);
  const p=JSON.parse(bytes),{scopeHash,...body}=p;
  assert.equal(p.schema,'mesh-guide-team-pilot/v1');assert.match(p.id,/^[a-f0-9-]{36}$/);
  assert.equal(p.dataDir,'data/guide-team-state-'+p.id);assert.equal(p.workspace,join(ROOT,'data','guide-team-work-'+p.id));
  assert.equal(resolve(path),join(ROOT,p.dataDir,'pilot.json'));owned(p.workspace);owned(join(ROOT,p.dataDir));
  assert.equal(sha(JSON.stringify(body)),scopeHash,'Pilot scope changed');
  assert.deepEqual(Object.keys(p.sourceHashes),codeFiles);
  for(const file of codeFiles)assert.equal(hashFile(join(ROOT,file)),p.sourceHashes[file],'Pilot source changed: '+file);
  assert.equal(p.suffix,suffix);assert.deepEqual(readdirSync(p.workspace),['MESH-QUICK-START.md']);
  assert.equal(hashFile(join(p.workspace,'MESH-QUICK-START.md')),p.beforeSha256,'Prepared copy changed');
  assert.equal(hashFile(join(ROOT,'MESH-QUICK-START.md')),p.beforeSha256,'Original guide changed');
  assert.equal(sha(Buffer.concat([readFileSync(join(p.workspace,'MESH-QUICK-START.md')),Buffer.from(suffix)])),p.expectedSha256);
  if(!p.fixture)assert.deepEqual(nativeHashes(),p.nativeImplementationHashes);
  if(readTask)checkPreparedTask(p);
  return p;
}

async function admitted(app) {
  const headers={Origin:app.url,'Content-Type':'application/json'};
  const bootstrap=await fetch(app.url+'/api/trial-session/bootstrap',{method:'POST',headers,body:'{}'});assert.equal(bootstrap.status,201);
  const session=await bootstrap.json();headers.Cookie=bootstrap.headers.get('set-cookie').split(';')[0];headers['X-Trial-CSRF']=session.csrfToken;
  return async(route,body)=>{
    const response=await fetch(app.url+route,{method:body===undefined?'GET':'POST',headers,...(body===undefined?{}:{body:JSON.stringify(body)}),signal:AbortSignal.timeout(30000)});
    const text=await response.text();let value;
    try{value=text?JSON.parse(text):{};}catch{throw Error('Pilot HTTP '+response.status+': invalid response; original attempt remains held');}
    assert.equal(response.status,200,'Pilot HTTP '+response.status+': '+(value.error??'Request refused'));return value;
  };
}
export function readPilotReviewPayload(p,sendId) {
  assert.equal(p.dataDir,'data/guide-team-state-'+p.id);
  const file=join(ROOT,p.dataDir,'tasks.sqlite');owned(file);
  const db=new DatabaseSync(file,{readOnly:true});
  try {
    const row=db.prepare('SELECT payload,phase,agentId FROM workroom_sends WHERE taskId=? AND id=?').get(p.taskId,sendId);
    assert.equal(row?.agentId,'nims');assert.equal(row.phase,'review');assert.equal(typeof row.payload,'string');
    return row.payload;
  } finally {db.close();}
}
async function reviewReadback(task,fixture,p) {
  if(fixture)return {source:'disposable_fixture',independentNativeReviewQualified:false};
  const send=task.messages.find(m=>m.id===task.automation.reviewerSendId),run=send?.nims;
  assert.equal(run?.state,'completed');assert.ok(run.threadId&&run.turnId);
  const expected=readPilotReviewPayload(p,send.id);
  const client=createCodexClient({root:p.workspace});
  try {
    const native=await client.readThread(run.threadId);assert.equal(native.thread.id,run.threadId);
    const matches=native.thread.turns.filter(t=>t.id===run.turnId);assert.equal(matches.length,1);
    const turn=matches[0];assert.equal(turn.status,'completed');
    assert.ok(turn.items.every(item=>['userMessage','agentMessage','reasoning','commandExecution'].includes(item.type)
      &&(item.type!=='commandExecution'||item.status==='completed'&&item.exitCode===0)));
    const users=turn.items.filter(item=>item.type==='userMessage');assert.equal(users.length,1);
    assert.deepEqual(users[0].content,[{type:'text',text:expected}]);
    return {source:'native_thread_readback',threadId:run.threadId,turnId:run.turnId,status:turn.status,itemTypes:turn.items.map(item=>item.type)};
  } finally {await client.close();}
}

export async function runGuideTeamPilot(path,{ownerApproved=false,approvedScopeHash,fixture,deadlineMs=480000}={}) {
  // Check the attempt marker BEFORE reopening a store (which can pause active
  // automation). A duplicate launch must not disturb the original worker.
  const attemptPath=join(dirname(resolve(path)),'attempt.json');
  if(existsSync(attemptPath))throw Error('This pilot already has an attempt. Inspect the saved identities; do not launch it again.');
  if(!fixture){
    assert.equal(ownerApproved,true,'Separate owner approval is required before any live connection');
    assert.match(approvedScopeHash??'',/^[a-f0-9]{64}$/,'The exact approved scope hash is required');
  }
  const p=validateGuideTeamPilot(path,{readTask:false});
  if(fixture){assert.equal(p.fixture,true);assert.equal(fixture.source,'disposable_fixture');}
  else {assert.equal(p.fixture,false);assert.equal(p.scopeHash,approvedScopeHash,'The prepared scope differs from the approved scope');}
  assert.ok(Number.isSafeInteger(deadlineMs)&&deadlineMs>=1000&&deadlineMs<=480000);
  writeFileSync(attemptPath,JSON.stringify({schema:'mesh-guide-team-attempt/v1',scopeHash:p.scopeHash,taskId:p.taskId,startedAt:new Date().toISOString(),source:fixture?'disposable_fixture':'owner_approved_live'},null,2)+'\n',{flag:'wx'});
  const keys=['MESH_STANDALONE','MESH_RELAY_MODE','MESH_RELAY_URL','MESH_RELAY_TOKEN_FILE','MESH_NIMS','MESH_SIMPLE_FLOW','MESH_NEMOTRON_CONTROL','MESH_MODEL_OBSERVATION','MESH_DSH_APPROVAL_ORIGIN','MESH_DSH_TOKEN_FILE'];
  const previous=Object.fromEntries(keys.map(key=>[key,process.env[key]]));let app,task,result;
  const stop=async()=>{const current=app;app=null;await current?.close();};
  const log=event=>appendFileSync(join(ROOT,p.dataDir,'observations.jsonl'),JSON.stringify({at:new Date().toISOString(),...event})+'\n');
  try {
    // The exclusive attempt marker is committed before any mutable store open.
    // A competing process can read metadata but cannot pause this team's store.
    checkPreparedTask(p);
    Object.assign(process.env,{MESH_STANDALONE:'0',MESH_RELAY_MODE:'http',MESH_RELAY_URL:fixture?.relayUrl??'http://127.0.0.1:8787',
      MESH_RELAY_TOKEN_FILE:fixture?.tokenFile??'D:/Dev/Onoes-Relay/.private/relay.key',MESH_NIMS:fixture?'0':'1',
      MESH_SIMPLE_FLOW:'0',MESH_NEMOTRON_CONTROL:'0',MESH_MODEL_OBSERVATION:'0'});
    if(fixture){process.env.MESH_DSH_APPROVAL_ORIGIN=fixture.relayUrl;process.env.MESH_DSH_TOKEN_FILE=fixture.tokenFile;}
    const nativeWorkerOptions=fixture?{profile:p.profile,rpc:fixture.rpc,authorized:()=>true}
      :nativeGatewayWorkerOptions({...runtime,profile:p.profile,authorized:()=>true});
    app=await startApp({dataDir:p.dataDir,relayEnabled:true,nativeWorkerOptions,sessionTtlMs:600000,
      ...(fixture?.sessionNow?{sessionNow:fixture.sessionNow}:{})});
    const request=await admitted(app),route='/api/workroom/'+p.taskId;
    await fixture?.connected?.({request});
    task=(await request(route)).task;
    assert.equal(fingerprint(task),p.preparedTaskSha256);
    await request(route+'/automation',{action:'start',revision:0,planRevision:task.plan.revision,
      taskRevision:task.revision,briefRevision:task.workroom.revision,progressRevision:task.progress.revision});
    const deadline=Date.now()+deadlineMs;let observed='';
    do {
      task=(await request(route)).task;
      const state=JSON.stringify({automation:task.automation,messages:task.messages.map(m=>({id:m.id,state:m.state,nativeLocal:m.nativeLocal,nims:m.nims}))});
      if(state!==observed){log({task});observed=state;}
      if(task.automation?.state!=='active')break;
      await new Promise(resolve=>setTimeout(resolve,150));
    } while(Date.now()<deadline);
    assert.equal(task.automation.state,'needs_review','Pilot not complete; original worker identities remain held');
    const worker=task.messages.find(m=>m.id===task.automation.workerSendId)?.nativeLocal;
    assert.equal(worker?.nativeOutcome,'completed');assert.equal(worker.writerQuiescence,true);assert.ok(worker.retirementHash);
    assert.equal(task.messages.length,2);assert.equal(task.agentReviews.length,1);assert.equal(task.agentReviews[0].review.verdict,'approved');
    const reviewer=await reviewReadback(task,fixture,p);
    assert.deepEqual(readdirSync(p.workspace),['MESH-QUICK-START.md']);
    assert.equal(hashFile(join(p.workspace,'MESH-QUICK-START.md')),p.expectedSha256);
    assert.equal(hashFile(join(ROOT,'MESH-QUICK-START.md')),p.beforeSha256);
    for(const file of codeFiles)assert.equal(hashFile(join(ROOT,file)),p.sourceHashes[file]);
    assert.equal(task.progress.decision,'pending');assert.notEqual(task.status,'done');
    await stop();
    process.env.MESH_STANDALONE='1';
    app=await startApp({dataDir:p.dataDir,relayEnabled:false});
    const reloaded=(await(await admitted(app))(route)).task;assert.deepEqual(reloaded,task,'Pilot results changed across restart');
    result={qualification:'PASS',source:fixture?'disposable_fixture':'live_native',scopeHash:p.scopeHash,taskId:p.taskId,
      worker,reviewer,preservedAcrossRestart:true,expectedSha256:p.expectedSha256,ownerReviewRecorded:false,done:false};
    return result;
  } catch(error) {
    result={qualification:'HELD',scopeHash:p.scopeHash,taskId:p.taskId,reason:String(error.message).slice(0,1000),task,
      warning:'Inspect the original saved attempt. Neither a timeout nor this runner exiting proves worker quiescence. No retry is authorized.'};
    throw error;
  } finally {
    try {await stop();} catch(error) {
      result={...result,qualification:'HELD',reason:'Pilot connection cleanup could not be confirmed; inspect the original identities.'};
      throw error;
    } finally {
      for(const key of keys){if(previous[key]===undefined)delete process.env[key];else process.env[key]=previous[key];}
      if(result)writeFileSync(join(ROOT,p.dataDir,'result.json'),JSON.stringify(result,null,2)+'\n',{flag:'wx'});
    }
  }
}

if(process.argv[1]&&resolve(process.argv[1])===fileURLToPath(import.meta.url)) {
  const [action,path,approval,approvedScopeHash]=process.argv.slice(2);
  if(action==='prepare'&&!path)console.log(JSON.stringify(prepareGuideTeamPilot(),null,2));
  else if(action==='run'&&path&&approval==='--owner-approved'&&approvedScopeHash)console.log(JSON.stringify(await runGuideTeamPilot(path,{ownerApproved:true,approvedScopeHash}),null,2));
  else throw Error('Use prepare, or run <prepared pilot.json> --owner-approved <approved scope hash> only after separate owner approval.');
}
