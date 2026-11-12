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
import {spawnSync} from 'node:child_process';

const sha=value=>createHash('sha256').update(value).digest('hex');
const fingerprint=t=>sha(JSON.stringify({id:t.id,title:t.title,description:t.description,status:t.status,
  workroom:t.workroom,progress:t.progress,plan:t.plan}));
const codeFiles=['server.mjs','lib/workroom.mjs','lib/workroom-updates.mjs','lib/workroom-native-binding.mjs','lib/native-gateway-transport.mjs',
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
export function reviewedNativeBaseline(header,capability,deployment) {
  const changed=['gateway/session_controls.py','tui_gateway/contracts/canonical.py'];
  assert.deepEqual(Object.keys(capability.candidateHashes).sort(),changed.slice().sort(),'Unreviewed native patch files');
  for(const path of changed)assert.equal(capability.baselineHashes[path],header[path],'Native patch baseline differs');
  const expected={...header,...capability.candidateHashes};
  assert.equal(deployment?.installed,true,'Native capability update is not installed');
  assert.equal(deployment?.processScopeSupported,true,'Native process capability is not verified');
  assert.deepEqual(deployment.installedSourceFiles,expected,'Installed native source record differs');
  return expected;
}
function nativeHashes() {
  const header=JSON.parse(readFileSync(join(ROOT,'integrations/native-header-fixture-qualification.json'),'utf8')).candidateFiles;
  const capability=JSON.parse(readFileSync(join(ROOT,'integrations/native-process-capability-qualification.json'),'utf8'));
  const maintenance=JSON.parse(readFileSync(join(ROOT,'integrations/native-worker-maintenance-qualification.json'),'utf8'));
  const expected=reviewedNativeBaseline(header,capability,maintenance.deployment);
  for(const [path,digest] of Object.entries(expected))assert.equal(hashFile(join(runtime.nativeRoot,path)),digest,'Installed native bridge changed: '+path);
  return expected;
}
export function pilotReviewCommand(workspace,expectedSha256,expectedBytes) {
  assert.equal(typeof workspace,'string');assert.ok(workspace.length);
  assert.match(expectedSha256,/^[a-f0-9]{64}$/);
  assert.ok(Number.isSafeInteger(expectedBytes)&&expectedBytes>0&&expectedBytes<=65536);
  const path64=Buffer.from(workspace,'utf8').toString('base64');
  const script=`$ErrorActionPreference='Stop';[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false);`+
    `$r=[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('${path64}'));`+
    `$f=@(Get-ChildItem -LiteralPath $r -Force);`+
    `if($f.Count -ne 1 -or $f[0].PSIsContainer -or $f[0].Name -cne 'MESH-QUICK-START.md' -or ($f[0].Attributes -band [IO.FileAttributes]::ReparsePoint)){throw 'Unexpected workspace entries'};$p=$f[0].FullName;`+
    `$b=[IO.File]::ReadAllBytes($p);$s=[Security.Cryptography.SHA256]::Create();try{$h=[BitConverter]::ToString($s.ComputeHash($b)).Replace('-','').ToLowerInvariant()}finally{$s.Dispose()};`+
    `if($b.Length -ne ${expectedBytes} -or $h -cne '${expectedSha256}'){throw 'Guide bytes or hash mismatch'};`+
    `[pscustomobject]@{Bytes=$b.Length;SHA256=$h;OnlyAllowedFile=$true}|ConvertTo-Json;`+
    `[Console]::WriteLine([Text.Encoding]::UTF8.GetString($b));`;
  assert.match(script,/^[\x00-\x7f]+$/);
  return {script,command:'powershell.exe -NoProfile -NonInteractive -EncodedCommand '+Buffer.from(script,'utf16le').toString('base64')};
}
export const BUILD_CHECK_SOURCE="export function boardColumn(stage) {\n  switch (stage) {\n    case 'backlog': case 'ready': return 'To do';\n    case 'working': case 'needs_you': return 'In progress';\n    case 'done': return 'Done';\n    default: throw new TypeError('Unknown stage');\n  }\n}\n";
const BUILD_CHECK_STUB="export function boardColumn() { throw new Error('Not implemented'); }\n";
const BUILD_CHECK_TEST="import test from 'node:test';\nimport assert from 'node:assert/strict';\nimport {boardColumn} from './board-column.mjs';\ntest('saved stages map to the three visible lanes',()=>{\n  for (const [stage,lane] of [['backlog','To do'],['ready','To do'],['working','In progress'],['needs_you','In progress'],['done','Done']]) assert.equal(boardColumn(stage),lane);\n});\ntest('unknown values do not invent a lane',()=>{\n  for (const value of ['unknown','toString','',null,undefined,1,{}]) assert.throws(()=>boardColumn(value),TypeError);\n});\n";
const buildFiles=['board-column.mjs','board-column.test.mjs'];
function buildReviewCommand(workspace) {
  const root=Buffer.from(workspace).toString('base64');
  const script="$ErrorActionPreference='Stop';[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false);"+
    `$r=[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('${root}'));$f=@(Get-ChildItem -LiteralPath $r -Force);`+
    "if($f.Count -ne 2 -or @($f|Where-Object {$_.PSIsContainer -or ($_.Attributes -band [IO.FileAttributes]::ReparsePoint)}).Count){throw 'Unexpected workspace entries'};"+
    "function Get-PilotHash($p){$s=[Security.Cryptography.SHA256]::Create();try{[BitConverter]::ToString($s.ComputeHash([IO.File]::ReadAllBytes($p))).Replace('-','').ToLowerInvariant()}finally{$s.Dispose()}};"+
    buildFiles.map((name,i)=>`$p=Join-Path $r '${name}';if((Get-PilotHash $p) -cne '${sha(i?BUILD_CHECK_TEST:BUILD_CHECK_SOURCE)}'){throw 'Code or tests changed'};[Console]::WriteLine([IO.File]::ReadAllText($p));`).join('')+
    "Set-Location -LiteralPath $r;$pilotOutput=& node --test board-column.test.mjs;if($LASTEXITCODE -ne 0){throw 'Build checks failed'};$pilotOutput|ForEach-Object {[Console]::WriteLine($_)};";
  return {script,command:'powershell.exe -NoProfile -NonInteractive -EncodedCommand '+Buffer.from(script,'utf16le').toString('base64')};
}
export function verifyBuildCheckArtifacts(p) {
  assert.equal(p.kind,'build-check-v1');assert.deepEqual(readdirSync(p.workspace).sort(),buildFiles);
  for(const name of buildFiles){owned(join(p.workspace,name));assert.equal(hashFile(join(p.workspace,name)),sha(name===buildFiles[0]?BUILD_CHECK_SOURCE:BUILD_CHECK_TEST),'Code or tests changed');}
  // Only execute the exact pre-reviewed module and tests after checking both hashes.
  const env={...process.env};delete env.NODE_TEST_CONTEXT;
  const checked=spawnSync(process.execPath,['--test',buildFiles[1]],{cwd:p.workspace,env,encoding:'utf8',windowsHide:true,timeout:10000});
  assert.equal(checked.status,0,'Fixed code checks failed: '+String(checked.stderr).slice(0,500));
  assert.match(checked.stdout,/pass 2\b/,'Expected both fixed tests to actually run');
  return {command:'node --test board-column.test.mjs',exitCode:0,stdoutHash:sha(checked.stdout),sourceAndTestsMatched:true};
}
export function prepareGuideTeamPilot({fixture=false,buildCheck=false}={}) {
  assert.equal(typeof buildCheck,'boolean');
  const installedHashes=fixture?{}:nativeHashes();
  const id=randomUUID(),dataDir='data/guide-team-state-'+id,workspace=join(ROOT,'data','guide-team-work-'+id);
  mkdirSync(workspace);mkdirSync(join(ROOT,dataDir));owned(workspace);owned(join(ROOT,dataDir));
  const original=buildCheck?Buffer.from(BUILD_CHECK_STUB):readFileSync(join(ROOT,'MESH-QUICK-START.md'));
  assert.ok(original.length<65536);assert.equal(original.includes(Buffer.from(suffix)),false);
  const artifactName=buildCheck?buildFiles[0]:'MESH-QUICK-START.md';
  writeFileSync(join(workspace,artifactName),original,{flag:'wx'});
  if(buildCheck)writeFileSync(join(workspace,buildFiles[1]),BUILD_CHECK_TEST,{flag:'wx'});
  const beforeSha256=sha(original),expectedSha256=sha(buildCheck?BUILD_CHECK_SOURCE:Buffer.concat([original,Buffer.from(suffix)]));
  const originalText=original.toString('utf8'),tail=originalText.slice(-400);
  assert.equal(Buffer.from(originalText).equals(original),true,'Guide must round-trip as UTF-8');
  assert.equal(originalText.split(tail).length,2,'Guide tail must be a unique replacement anchor');
  const patch={mode:'replace',path:artifactName,old_string:tail,new_string:buildCheck?BUILD_CHECK_SOURCE:tail+suffix};
  const reviewCheck=buildCheck?buildReviewCommand(workspace):pilotReviewCommand(workspace,expectedSha256,original.length+Buffer.byteLength(suffix));
  const buildSpec='Read both supplied files. Replace only the stub in board-column.mjs with the exact implementation below; do not edit board-column.test.mjs. This implements the five saved Workroom stages as three visible lanes and rejects unknown stages.\nExact patch JSON: '+JSON.stringify(patch);
  const buildChecks='Builder: run node --test board-column.test.mjs; preserve tests and report actual output/exit. Report blocked on failure. Reviewer: read both files and run this exact hash-check/test command:\n'+reviewCheck.command;
  const buildBoundary='Isolated code-and-test qualification only. Edit only board-column.mjs; tests are immutable. Terminal commands limited to local read/syntax/test commands in this workspace. No network, installs, package manager, services, credentials, memory, other workers, commits, purchases or scope expansion. Nims reviews read-only. No automatic Done or owner approval.';
  const store=openTaskStore(join(ROOT,dataDir,'tasks.sqlite'));let task;
  try {
    task=store.create({title:buildCheck?'Code-and-test team pilot — board lane mapping':'Guide team pilot — phone recovery notes',description:'One isolated bounded build followed by one independent review. No live app changes.',owner:'echo'});
    task=store.workroom.save(task.id,{project:'Onoes-Mesh pilot',criteria:buildCheck?'Exact supplied module implemented, unchanged local tests pass, independent review approves.':'Preserve every original byte; append only the exact supplied recovery note; independent review approves.',owner:'echo',team:'local_build',stage:'ready',revision:1});
    task=store.workroom.saveProgress(task.id,{goal:buildCheck?'Implement the exact supplied board-lane module and run its unchanged local tests.':'Append the verified phone recovery note to the isolated guide copy and independently verify the exact result.',
      checklist:[{id:'guide',text:buildCheck?'Implement the supplied module and run node --test board-column.test.mjs':'Append exactly the supplied note and read the guide copy back',status:'pending'}],result:'',evidence:'',reviewer:'',decision:'pending',revision:0,taskRevision:task.revision,briefRevision:task.workroom.revision});
    task=store.workroom.savePlan(task.id,{lead:'echo',spec:buildCheck?buildSpec:'Read MESH-QUICK-START.md first. Use the file patch tool in replace mode with the decoded JSON arguments below, replacing the unique existing tail with itself plus the exact note. Do not use V4A or reconstruct the whole file.\nExact patch JSON: '+JSON.stringify(patch)+'\nPreserve all original '+original.length+' bytes, both added leading newlines and the final newline. Expected final length '+(original.length+Buffer.byteLength(suffix))+' bytes. Expected complete-file SHA-256: '+expectedSha256,
      workspace,allowedFiles:buildCheck?'board-column.mjs':'MESH-QUICK-START.md',checks:buildCheck?buildChecks:'Builder: apply the supplied anchored replacement, then read it back. A mismatch is unfinished work: correct the same allowed file within this attempt and read it back again; if unable, report the existing step as blocked with the actual mismatch. Mark the guide step done only after the required file edit/read-back succeeds. Do not claim an unavailable SHA/terminal/directory check; those checks belong to the independent reviewer and host, not your worker checklist. Reviewer and host: independently verify all original bytes plus the exact append, final SHA-256 '+expectedSha256+', and no other files in the workspace. Reviewer may use read-only commands; do not write a checker or any file. Reviewer: execute this exact read-only command verbatim to verify the inventory, byte count and full hash and read the complete guide; do not reconstruct quoted guide text:\n'+reviewCheck.command,
      boundaries:buildCheck?buildBoundary:'Guide-copy-only qualification. No other files, databases, memory, credentials, external messages, workers, service operations, commits, purchases or scope expansion. Ask if unclear. Builder file tools only; Nims independently reviews read-only. Do not mark Done or record owner approval.',
      workerId:'echo',reviewerId:'nims',state:'locked',revision:0,taskRevision:task.revision,briefRevision:task.workroom.revision,progressRevision:task.progress.revision}).task;
  } finally {store.close();}
  const intent={schema:'mesh-guide-team-pilot/v1',id,preparedAt:new Date().toISOString(),fixture,dataDir,workspace,taskId:task.id,
    beforeSha256,expectedSha256,originalBytes:original.length,suffix:buildCheck?'':suffix,preparedTaskSha256:fingerprint(task),
    ...(buildCheck?{kind:'build-check-v1',testSha256:sha(BUILD_CHECK_TEST),originalGuideSha256:hashFile(join(ROOT,'MESH-QUICK-START.md'))}:{}),
    sourceHashes:Object.fromEntries(codeFiles.map(file=>[file,hashFile(join(ROOT,file))])),nativeImplementationHashes:installedHashes,
    profile:{profileRef:'guide-pilot-'+id,identityRef:'guide-pilot-'+id,provider:'openai-codex',model:'gpt-6-luna',workspace,...(buildCheck?{toolProfile:'build-check-v1'}:{})},
    limits:{builderAttempts:1,builderMaxTurns:50,builderTools:buildCheck?['file','terminal']:['file'],reviewerAttempts:1,reviewer:'nims',reviewerMode:'read-only',automaticRetries:false,automaticDone:false}};
  intent.scopeHash=sha(JSON.stringify(intent));
  const path=join(ROOT,dataDir,'pilot.json');writeFileSync(path,JSON.stringify(intent,null,2)+'\n',{flag:'wx'});
  writeFileSync(join(ROOT,dataDir,'REVIEW.txt'),buildCheck?`Onoes-Mesh CODE AND TEST trial - PREPARED ONLY\n\nScope: ${intent.scopeHash}\nWorkspace: ${workspace}\nOnly editable file: board-column.mjs. Immutable tests: board-column.test.mjs.\nOne Echo-role gpt-6-luna builder, explicit build-check-v1 file+terminal tools, max50 turns; one existing Nims read-only review. No retries, Done, production enrollment, service restart or model load.\n${buildBoundary}\nModule SHA256: ${expectedSha256}\nTest SHA256: ${sha(BUILD_CHECK_TEST)}\nSeparate exact owner approval required before any live provider task.\n`:`Onoes-Mesh guide team trial — PREPARED ONLY\n\nScope: ${intent.scopeHash}\nWorkspace: ${workspace}\nOnly editable file: MESH-QUICK-START.md\nOne Echo-role native Codex build (gpt-6-luna, file tools only, 50-turn ceiling), then one existing Nims read-only review (current configured Codex model, 180-second connector turn deadline). Existing ChatGPT Codex sign-in; no API-key billing.\nNo retries or automatic Done. Isolated board; no live board changes, service restart, Rook/Mind activation or production enrollment.\n\nExact append:${suffix}\nOriginal SHA-256: ${beforeSha256}\nExpected final SHA-256: ${expectedSha256}\n\nLive execution requires separate owner approval. Preparing this copied no credentials and submitted no model work.\n`,{flag:'wx'});
  appendFileSync(join(ROOT,dataDir,'REVIEW.txt'),'\nRead-only reviewer check (decoded for inspection):\n'+reviewCheck.script+'\n\nExact command:\n'+reviewCheck.command+'\n');
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
  assert.ok(p.kind===undefined||p.kind==='build-check-v1','Unsupported pilot kind');
  assert.equal(p.profile.toolProfile,p.kind?'build-check-v1':undefined,'Tool profile differs from artifact scope');
  assert.deepEqual(p.limits.builderTools,p.kind?['file','terminal']:['file']);
  if(p.kind){
    assert.equal(p.suffix,'');assert.equal(p.beforeSha256,sha(BUILD_CHECK_STUB));assert.equal(p.expectedSha256,sha(BUILD_CHECK_SOURCE));
    assert.deepEqual(readdirSync(p.workspace).sort(),buildFiles);assert.equal(p.testSha256,sha(BUILD_CHECK_TEST));
    for(const file of buildFiles)owned(join(p.workspace,file));
    assert.equal(hashFile(join(p.workspace,buildFiles[0])),p.beforeSha256,'Prepared code changed');
    assert.equal(hashFile(join(p.workspace,buildFiles[1])),p.testSha256,'Immutable tests changed');
    assert.equal(hashFile(join(ROOT,'MESH-QUICK-START.md')),p.originalGuideSha256,'Original guide changed');
  }else{
    assert.equal(p.suffix,suffix);assert.deepEqual(readdirSync(p.workspace),['MESH-QUICK-START.md']);
    assert.equal(hashFile(join(p.workspace,'MESH-QUICK-START.md')),p.beforeSha256,'Prepared copy changed');
    assert.equal(hashFile(join(ROOT,'MESH-QUICK-START.md')),p.beforeSha256,'Original guide changed');
    assert.equal(sha(Buffer.concat([readFileSync(join(p.workspace,'MESH-QUICK-START.md')),Buffer.from(suffix)])),p.expectedSha256);
  }
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
export function assertPilotReviewInput(content,expected) {
  assert.ok(Array.isArray(content));
  const normalized=content.map(part=>{
    if(part&&typeof part==='object'&&Object.hasOwn(part,'text_elements')){
      const {text_elements,...text}=part;
      assert.deepEqual(text_elements,[],'Native input contains unexpected text elements');
      return text;
    }
    return part;
  });
  assert.deepEqual(normalized,[{type:'text',text:expected}]);
}
export function assertPilotReviewTrace(turn) {
  assert.equal(turn.status,'completed');
  assert.ok(Array.isArray(turn.items),'Native review items are unavailable');
  for(const item of turn.items){
    assert.ok(['userMessage','agentMessage','reasoning','commandExecution'].includes(item.type),
      'Native review contains an unsupported item type: '+String(item.type));
    if(item.type==='commandExecution')assert.ok(item.status==='completed'&&item.exitCode===0,
      'Native review contains a failed or incomplete command; inspect the original trace before qualification');
  }
}
export async function reviewReadback(task,fixture,p) {
  if(fixture)return {source:'disposable_fixture',independentNativeReviewQualified:false};
  const send=task.messages.find(m=>m.id===task.automation.reviewerSendId),run=send?.nims;
  assert.equal(run?.state,'completed');assert.ok(run.threadId&&run.turnId);
  const expected=readPilotReviewPayload(p,send.id);
  const client=createCodexClient({root:p.workspace});
  try {
    const native=await client.readThread(run.threadId);assert.equal(native.thread.id,run.threadId);
    const matches=native.thread.turns.filter(t=>t.id===run.turnId);assert.equal(matches.length,1);
    const turn=matches[0];assertPilotReviewTrace(turn);
    const users=turn.items.filter(item=>item.type==='userMessage');assert.equal(users.length,1);
    assertPilotReviewInput(users[0].content,expected);
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
    let buildVerification;
    if(p.kind)buildVerification=verifyBuildCheckArtifacts(p);
    else{
      assert.deepEqual(readdirSync(p.workspace),['MESH-QUICK-START.md']);
      assert.equal(hashFile(join(p.workspace,'MESH-QUICK-START.md')),p.expectedSha256);
    }
    assert.equal(hashFile(join(ROOT,'MESH-QUICK-START.md')),p.kind?p.originalGuideSha256:p.beforeSha256);
    for(const file of codeFiles)assert.equal(hashFile(join(ROOT,file)),p.sourceHashes[file]);
    assert.equal(task.progress.decision,'pending');assert.notEqual(task.status,'done');
    await stop();
    process.env.MESH_STANDALONE='1';
    app=await startApp({dataDir:p.dataDir,relayEnabled:false});
    const reloaded=(await(await admitted(app))(route)).task;assert.deepEqual(reloaded,task,'Pilot results changed across restart');
    result={qualification:'PASS',source:fixture?'disposable_fixture':'live_native',scopeHash:p.scopeHash,taskId:p.taskId,
      worker,reviewer,...(p.kind?{kind:p.kind,buildVerification}:{}),preservedAcrossRestart:true,expectedSha256:p.expectedSha256,ownerReviewRecorded:false,done:false};
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
  if(action==='prepare-build-check'&&!path)console.log(JSON.stringify(prepareGuideTeamPilot({buildCheck:true}),null,2));
  else if(action==='prepare'&&!path)console.log(JSON.stringify(prepareGuideTeamPilot(),null,2));
  else if(action==='run'&&path&&approval==='--owner-approved'&&approvedScopeHash)console.log(JSON.stringify(await runGuideTeamPilot(path,{ownerApproved:true,approvedScopeHash}),null,2));
  else throw Error('Use prepare, or run <prepared pilot.json> --owner-approved <approved scope hash> only after separate owner approval.');
}
