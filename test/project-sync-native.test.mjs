import test from 'node:test';
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {createInterface} from 'node:readline';
import {Readable} from 'node:stream';
import {randomUUID,createHash} from 'node:crypto';
import {mkdirSync,rmSync,statSync,realpathSync} from 'node:fs';
import {resolve,join} from 'node:path';
import {DatabaseSync} from 'node:sqlite';
import {startApp} from '../server.mjs';
import {openTaskStore} from '../lib/task-store.mjs';
import {createWorkroomProjectSyncCandidate} from '../integrations/workroom-project-sync-candidate.mjs';
import {validateNativeProjectSync,prepareNativeProjectSync,nativeSyncSchema,captureSyncSchema,validateNativeProjectCapture} from '../integrations/project-sync-native-candidate.mjs';
import {startNativeMesh,readNativeRecallInput,readNativeMeshInput,meshFrameSchema,captureFrameSchema} from '../integrations/native-mind-mesh-entry.mjs';

import {memoryStatePresentation} from '../public/workroom-memory-state.mjs';

const readDescriptor=()=>({baseUrl:'http://127.0.0.1:12345/',token:'synthetic-unused-read-token',binding:{
  servicePrincipal:'mesh-recall',storeId:'00000000-0000-4000-8000-000000000001',environment:'synthetic',
  scopeId:'project/onoes-mind/shared',reviewRef:'fixture:read'}});
const stream=value=>Readable.from([Buffer.from(JSON.stringify(value))]);
const fixturePeer={pid:process.pid,creationTicks:'1',runId:'0'.repeat(32),profileSha256:'0'.repeat(64)};
const delay=ms=>new Promise(r=>setTimeout(r,ms));
async function until(fn){const deadline=Date.now()+15000;while(Date.now()<deadline){if(await fn())return;await delay(30);}assert.fail('Synthetic native condition did not settle.');}
function environment(t){
  const keys=['MESH_STANDALONE','MESH_RELAY_MODE','MESH_MODEL_OBSERVATION','MESH_NEMOTRON_CONTROL','MESH_SIMPLE_FLOW','MESH_NIMS'];
  const old=Object.fromEntries(keys.map(k=>[k,process.env[k]]));delete process.env.MESH_STANDALONE;
  process.env.MESH_RELAY_MODE='child';for(const key of keys.slice(2))process.env[key]='0';
  t.after(()=>{for(const key of keys)if(old[key]===undefined)delete process.env[key];else process.env[key]=old[key];});
}
function baseline(destination){
  const dataDir='test/app03-native-sync-'+randomUUID(),directory=resolve(dataDir);mkdirSync(directory);
  const filename=join(directory,'tasks.sqlite');let controller;
  const store=openTaskStore(filename,{projectSyncFactory:c=>controller=createWorkroomProjectSyncCandidate(c,{storeId:destination.storeId,initialize:true})});
  const card=store.create({title:'Synthetic native pipeline',description:'PRIVATE-UNSHARED-GOAL',owner:'nims'});
  const link={cardId:card.id,projectId:'project-A',approvalRef:'fixture:approved-card',fields:['title','stage']};
  controller.link(link);store.close();
  const stat=statSync(filename,{bigint:true});
  return {dataDir,filename,cardId:card.id,cleanup:()=>rmSync(directory,{recursive:true,force:true}),config:{schema:nativeSyncSchema,destination,links:[link],
    source:{databasePath:realpathSync(filename),fileDevice:stat.dev.toString(),fileInode:stat.ino.toString()}}};
}
async function mind(){
  const child=spawn('python',['-B',resolve('test/project-sync-native-fixture.py'),process.env.MIND_CANDIDATE_SOURCE||'D:/Dev/Onoes-Mind'],
    {windowsHide:true,stdio:['pipe','pipe','pipe']});
  const terminal=new Promise(r=>child.once('exit',code=>r(code)));let stderr='';child.stderr.on('data',b=>stderr+=b);
  const lines=createInterface({input:child.stdout}),iterator=lines[Symbol.asyncIterator]();
  const read=async()=>{const line=await iterator.next();assert.equal(line.done,false,stderr);return JSON.parse(line.value);};
  let options=await read();
  const rpc=async op=>{child.stdin.write(JSON.stringify({op})+'\n');return read();};
  return {get options(){return options;},rpc,async restart(){options=await rpc('restart');},
    async close(){if(child.exitCode===null){await rpc('close');child.stdin.end();}assert.equal(await terminal,0,stderr);lines.close();}};
}
async function admitted(app,gateCookie=''){
  const boot=await fetch(app.url+'/api/trial-session/bootstrap',{method:'POST',headers:{Origin:app.url,'Content-Type':'application/json',...(gateCookie?{Cookie:gateCookie}:{})},body:'{}'});
  assert.equal(boot.status,201);const session=await boot.json();
  const headers={Origin:app.url,'Content-Type':'application/json',Cookie:[gateCookie,boot.headers.get('set-cookie').split(';')[0]].filter(Boolean).join('; '),'X-Trial-CSRF':session.csrfToken};
  return async(path,{method='GET',body}={})=>{
    const response=await fetch(app.url+path,{method,headers,...(body?{body:JSON.stringify(body)}:{})});
    return {status:response.status,value:await response.json()};
  };
}
async function gateway(dataDir,frame){
  const env={...process.env,MESH_PORT:'0',MESH_PREVIEW_PORT:'0',MESH_DATA_DIR:dataDir,MESH_RELAY:'0',
    MESH_RELAY_MODE:'child',MESH_MODEL_OBSERVATION:'0',MESH_NEMOTRON_CONTROL:'0',MESH_SIMPLE_FLOW:'0',MESH_NIMS:'0',
    MESH_GATE_TOKEN:'synthetic-native-sync-gateway'};
  for(const key of ['MESH_STANDALONE','MESH_NATIVE_WORKER_RECORD','MESH_NATIVE_WORKER_RECORD_SHA256','MESH_TAILSCALE_LOGIN','MESH_TAILSCALE_HOST'])delete env[key];
  const child=spawn(process.execPath,['serve.mjs','--native-mind'],{env,stdio:['pipe','pipe','pipe'],windowsHide:true});
  const terminal=new Promise(r=>child.once('exit',code=>r(code)));let output='',stderr='';
  child.stderr.on('data',b=>stderr+=b);
  const close=async()=>{if(child.exitCode===null&&child.signalCode===null)child.kill();await terminal;};
  try{
    const ready=new Promise((resolve,reject)=>{
      const timer=setTimeout(()=>reject(Error('Owned gateway readiness timed out.')),15000);
      child.once('error',e=>{clearTimeout(timer);reject(e);});
      child.once('exit',()=>{clearTimeout(timer);reject(Error('Owned gateway exited before readiness.'));});
      child.stdout.on('data',b=>{
        output+=b;
        for(const line of output.split('\n')){
          try{const value=JSON.parse(line);if(value.event==='mesh_listening'){clearTimeout(timer);resolve(value);}}catch{}
        }
      });
    });
    child.stdin.end(JSON.stringify(frame));const status=await ready;assert.equal(status.pid,child.pid);
    assert.ok(!output.includes(frame.projectSyncOptions.destination.token)&&!stderr.includes(frame.projectSyncOptions.destination.token));
    assert.ok(!output.includes(frame.mindRecallOptions.token)&&!stderr.includes(frame.mindRecallOptions.token));
    const cookie='mesh_session='+createHash('sha256').update('mesh-cookie:synthetic-native-sync-gateway').digest('hex');
    assert.equal((await fetch(status.previewUrl+'/api/mind/status')).status,401);
    return {request:await admitted({url:status.previewUrl},cookie),close};
  }catch(error){await close();throw error;}
}
function rows(filename){const db=new DatabaseSync(filename,{readOnly:true});try{return db.prepare('SELECT eventId,state,receipt FROM mind_project_outbox ORDER BY sequence').all();}finally{db.close();}}

test('native app saves, reads canonical memory, awaits delivery at close and reconciles offline restart', {timeout:180000},async t=>{
  environment(t);let app,m,b,phoneGateway;
  t.after(async()=>{try{await phoneGateway?.close();await app?.close();}finally{try{await m?.close();}finally{b?.cleanup();}}});
  m=await mind();b=baseline(m.options.project);
  const start=async()=>{
    b.config.destination=m.options.project;
    app=await startNativeMesh({input:stream({schema:meshFrameSchema,mindRecallOptions:m.options.recall,projectSyncOptions:b.config}),
      appOptions:{dataDir:b.dataDir,relayEnabled:false}});
    return admitted(app);
  };
  let request=await start();const cardPath='/api/workroom/'+b.cardId;
  await until(async()=>(await request(cardPath)).value.memorySync.state==='saved');
  const recall=await request('/api/mind/recall',{method:'POST',body:{query:'Synthetic native pipeline',limit:8}});
  assert.equal(recall.status,200);assert.equal(recall.value.records.length,1);
  assert.doesNotMatch(JSON.stringify(recall.value),/PRIVATE-UNSHARED-GOAL/);
  assert.deepEqual(await m.rpc('stats'),{records:1,receipts:1});
  const edit=async title=>{
    const task=(await request('/api/tasks/'+b.cardId)).value.task;
    const response=await request('/api/tasks/'+b.cardId,{method:'PATCH',body:{
      title,description:task.description,label:task.label,status:task.status,owner:task.owner,revision:task.revision}});
    assert.equal(response.status,200);
  };
  await m.rpc('holdNextReply');await edit('Synthetic native pipeline updated');
  await until(async()=>(await m.rpc('committed')).committed);
  let closed=false;const closing=app.close().then(()=>{closed=true;app=null;});
  await delay(50);assert.equal(closed,false);
  await m.rpc('release');await closing;
  assert.deepEqual(rows(b.filename).map(row=>row.state),['saved','saved']);
  assert.deepEqual(await m.rpc('stats'),{records:1,receipts:2});
  request=await start();await m.rpc('stop');await edit('Synthetic native pipeline offline');
  const offline=(await request(cardPath)).value;
  assert.ok(['pending','uncertain'].includes(offline.memorySync.state));
  assert.equal(offline.task.workroom.stage,'backlog');
  await app.close();app=null;const pendingId=rows(b.filename).at(-1).eventId;
  await m.restart();request=await start();
  await until(async()=>(await request(cardPath)).value.memorySync.state==='saved');
  const recovered=rows(b.filename).at(-1);assert.equal(recovered.eventId,pendingId);
  assert.equal(JSON.parse(recovered.receipt).eventId,pendingId);
  assert.deepEqual(await m.rpc('stats'),{records:1,receipts:3});
  await app.close();app=null;
  phoneGateway=await gateway(b.dataDir,{schema:meshFrameSchema,mindRecallOptions:m.options.recall,projectSyncOptions:b.config});
  request=phoneGateway.request;
  await edit('Synthetic native pipeline gateway');
  await until(async()=>(await request(cardPath)).value.memorySync.state==='saved');
  const phoneRecall=await request('/api/mind/recall',{method:'POST',body:{query:'Synthetic native pipeline gateway',limit:8}});
  assert.equal(phoneRecall.status,200);assert.equal(phoneRecall.value.records.length,1);
  assert.doesNotMatch(JSON.stringify(phoneRecall.value),/PRIVATE-UNSHARED-GOAL/);
  assert.deepEqual(await m.rpc('stats'),{records:1,receipts:4});
  await phoneGateway.close();phoneGateway=null;request=await start();
  const unshared=await request('/api/tasks',{method:'POST',body:{title:'Unshared native card',owner:'echo'}});
  assert.equal(unshared.status,201);
  assert.equal((await request('/api/workroom/'+unshared.value.task.id)).value.memorySync.state,'not_shared');
  await m.rpc('revoke');await edit('Synthetic native pipeline revoked');
  await until(async()=>(await request(cardPath)).value.memorySync.state==='held');
  assert.deepEqual(await m.rpc('stats'),{records:1,receipts:4});
});

test('native input and startup refuse substituted source/policy and never initialize missing schema',async t=>{
  environment(t);
  const b=baseline({baseUrl:'http://127.0.0.1:12345/',token:'synthetic-project-token-for-validation',storeId:'synthetic-store',peer:fixturePeer});
  t.after(b.cleanup);
  const frame=()=>({schema:meshFrameSchema,mindRecallOptions:readDescriptor(),projectSyncOptions:b.config});
  assert.deepEqual((await readNativeMeshInput(stream(frame()))).projectSyncOptions,b.config);
  await assert.rejects(readNativeRecallInput(stream(frame())));
  await assert.rejects(startNativeMesh({input:stream(frame()),appOptions:{projectSyncOptions:b.config}}));
  for(const change of [{destination:{...b.config.destination,baseUrl:'https://example.invalid/'}},
    {destination:{...b.config.destination,peer:undefined}},
    {links:[{...b.config.links[0],fields:['title','private_chat','stage']}]}, {extra:true}]){
    assert.throws(()=>validateNativeProjectSync({...b.config,...change}));
  }
  const before=rows(b.filename);
  const db=new DatabaseSync(b.filename);db.exec("UPDATE mind_project_capture_policy SET fields='[\"title\",\"goal\",\"stage\"]'");db.close();
  await assert.rejects(startNativeMesh({input:stream(frame()),appOptions:{dataDir:b.dataDir,relayEnabled:false}}),/storage unavailable/);
  assert.deepEqual(rows(b.filename),before);
  const missing=new DatabaseSync(b.filename);missing.exec('DROP TABLE mind_project_capture_policy');missing.close();
  await assert.rejects(startNativeMesh({input:stream(frame()),appOptions:{dataDir:b.dataDir,relayEnabled:false}}),/storage unavailable/);
  const checked=new DatabaseSync(b.filename,{readOnly:true});
  assert.equal(checked.prepare("SELECT 1 FROM sqlite_schema WHERE name='mind_project_capture_policy'").get(),undefined);checked.close();
  assert.deepEqual(rows(b.filename),before);
  b.config.source.fileInode=(BigInt(b.config.source.fileInode)+1n).toString();
  await assert.rejects(startNativeMesh({input:stream(frame()),appOptions:{dataDir:b.dataDir,relayEnabled:false}}),/binding/);
});

test('policy drift holds delivery locally and rolls back shared edits while unshared work stays usable',async t=>{
  const b=baseline({baseUrl:'http://127.0.0.1:12345/',token:'synthetic-project-token-for-validation',storeId:'synthetic-store',peer:fixturePeer});
  const runtime=prepareNativeProjectSync(b.config,{filename:b.filename,standalone:false});
  const store=openTaskStore(b.filename,{projectSyncFactory:runtime.factory});
  const db=new DatabaseSync(b.filename);
  t.after(async()=>{await runtime.close();db.close();store.close();b.cleanup();});
  const original=store.get(b.cardId);
  db.exec("UPDATE mind_project_capture_policy SET fields='[\"title\",\"goal\",\"stage\"]'");
  assert.throws(()=>store.update(b.cardId,{title:'Refused shared edit',revision:original.revision}));
  assert.equal(store.get(b.cardId).title,original.title);
  assert.equal(store.projectSyncState(b.cardId).state,'unavailable');
  assert.ok(store.create({title:'Still unshared',owner:'echo'}).id);
  runtime.start();
  await until(async()=>db.prepare('SELECT state FROM mind_project_outbox').get().state==='held');
  assert.equal(db.prepare('SELECT reason FROM mind_project_outbox').get().reason,'local_binding_changed');
});


test('explicit credential-free capture starts offline, survives reopen and catches up identical events', {timeout:180000},async t=>{
  environment(t);let app,m,b;
  t.after(async()=>{try{await app?.close();}finally{try{await m?.close();}finally{b?.cleanup();}}});
  m=await mind();b=baseline(m.options.project);await m.rpc('stop');
  const capture={schema:captureSyncSchema,source:b.config.source,storeId:b.config.destination.storeId,links:b.config.links};
  const frame={schema:captureFrameSchema,projectCaptureOptions:capture};
  assert.deepEqual(await readNativeMeshInput(stream(frame)),{projectCaptureOptions:capture});
  await assert.rejects(readNativeRecallInput(stream(frame)));
  await assert.rejects(readNativeMeshInput(stream({...frame,mindRecallOptions:readDescriptor()})));
  for(const extra of [{token:'forbidden'},{destination:b.config.destination}])
    assert.throws(()=>validateNativeProjectCapture({...capture,...extra}));
  await assert.rejects(startNativeMesh({input:stream(frame),appOptions:{projectCaptureOptions:capture}}));
  const start=async()=>{app=await startNativeMesh({input:stream(frame),appOptions:{dataDir:b.dataDir,relayEnabled:false}});return admitted(app);};
  let request=await start();const cardPath='/api/workroom/'+b.cardId;
  assert.equal((await request(cardPath)).value.memorySync.state,'offline');
  const presentation=memoryStatePresentation((await request(cardPath)).value.memorySync);
  assert.equal(presentation.label,'Mind disconnected');assert.match(presentation.description,/saved on this PC/);
  for(const title of ['Offline captured first','Offline captured final']){
    const card=(await request('/api/tasks/'+b.cardId)).value.task;
    assert.equal((await request('/api/tasks/'+b.cardId,{method:'PATCH',body:{title,description:card.description,
      label:card.label,status:card.status,owner:card.owner,revision:card.revision}})).status,200);
  }
  const pending=rows(b.filename);assert.equal(pending.length,3);assert.ok(pending.every(row=>row.state==='pending'));
  const unshared=await request('/api/tasks',{method:'POST',body:{title:'Offline unrelated card',owner:'echo'}});
  assert.equal(unshared.status,201);
  assert.equal((await request('/api/workroom/'+unshared.value.task.id)).value.memorySync.state,'not_shared');
  assert.equal((await request('/api/mind/recall',{method:'POST',body:{query:'offline',limit:8}})).status,503);
  await app.close();app=null;request=await start();
  assert.equal((await request('/api/tasks/'+b.cardId)).value.task.title,'Offline captured final');
  assert.deepEqual(rows(b.filename),pending);
  // A service returning alone cannot turn capture-only mode into a sender.
  await m.restart();await delay(250);assert.deepEqual(await m.rpc('stats'),{records:0,receipts:0});
  await app.close();app=null;b.config.destination=m.options.project;
  app=await startNativeMesh({input:stream({schema:meshFrameSchema,mindRecallOptions:m.options.recall,projectSyncOptions:b.config}),
    appOptions:{dataDir:b.dataDir,relayEnabled:false}});request=await admitted(app);
  await until(async()=>(await request(cardPath)).value.memorySync.state==='saved');
  const saved=rows(b.filename);assert.deepEqual(saved.map(row=>row.eventId),pending.map(row=>row.eventId));
  assert.ok(saved.every(row=>row.state==='saved'&&JSON.parse(row.receipt).eventId===row.eventId));
  assert.deepEqual(await m.rpc('stats'),{records:1,receipts:3});
  const recall=await request('/api/mind/recall',{method:'POST',body:{query:'Offline captured final',limit:8}});
  assert.equal(recall.status,200);assert.equal(recall.value.records.length,1);
  assert.doesNotMatch(JSON.stringify(recall.value),/PRIVATE-UNSHARED-GOAL|Offline unrelated card/);
});


test('capture-only startup rejects mismatched authority and never repairs or widens sharing',async t=>{
  environment(t);
  const b=baseline({baseUrl:'http://127.0.0.1:12345/',token:'synthetic-unused-token',storeId:'synthetic-store',peer:fixturePeer});
  t.after(b.cleanup);
  const capture={schema:captureSyncSchema,source:b.config.source,storeId:'synthetic-store',links:b.config.links};
  const attempt=options=>startNativeMesh({input:stream({schema:captureFrameSchema,projectCaptureOptions:options}),
    appOptions:{dataDir:b.dataDir,relayEnabled:false}});
  const before=rows(b.filename);
  await assert.rejects(startApp({dataDir:b.dataDir,relayEnabled:false,projectCaptureOptions:capture,
    mindRecallOptions:readDescriptor()}),/cannot enroll memory access/);
  for(const change of [{storeId:'another-store'},
    {source:{...capture.source,fileInode:(BigInt(capture.source.fileInode)+1n).toString()}},
    {links:[{...capture.links[0],fields:['title','goal','stage']}]}]){
    await assert.rejects(attempt({...capture,...change}));assert.deepEqual(rows(b.filename),before);
  }
  const db=new DatabaseSync(b.filename);db.exec('DROP TABLE mind_project_capture_policy');db.close();
  await assert.rejects(attempt(capture),/storage unavailable/);
  const checked=new DatabaseSync(b.filename,{readOnly:true});
  assert.equal(checked.prepare("SELECT 1 FROM sqlite_schema WHERE name='mind_project_capture_policy'").get(),undefined);
  checked.close();assert.deepEqual(rows(b.filename),before);
});
