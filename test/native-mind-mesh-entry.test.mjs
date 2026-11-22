import test from 'node:test';
import assert from 'node:assert/strict';
import {Readable,PassThrough} from 'node:stream';
import {spawn} from 'node:child_process';
import {randomUUID,createHash} from 'node:crypto';
import {createServer} from 'node:http';
import {mkdirSync, copyFileSync, renameSync} from 'node:fs';
import {resolve} from 'node:path';
import {openTaskStore} from '../lib/task-store.mjs';
import {databaseFileIdentity} from '../lib/database-identity.mjs';
import {nativeRookOptions} from '../lib/workroom-rook.mjs';
import {frameSchema,readNativeRecallInput,readNativeMeshInput,startNativeMesh} from '../integrations/native-mind-mesh-entry.mjs';

const options=()=>({baseUrl:'http://127.0.0.1:12345/',token:'synthetic-pipe-only-token',binding:{
  servicePrincipal:'mesh-recall',storeId:'00000000-0000-4000-8000-000000000001',environment:'synthetic',
  scopeId:'project/onoes-mind/shared',reviewRef:'fixture:not-live-approval',
}});
const frame=value=>JSON.stringify({schema:frameSchema,mindRecallOptions:value});
const stream=value=>Readable.from([Buffer.from(value)]);

function testEnrollment(directory) {
  mkdirSync(directory, {recursive:true});
  const boardPath=resolve(directory,'tasks.sqlite');
  const store=openTaskStore(boardPath);
  try {store.create({title:'Enrollment fixture',description:'Existing Workroom board'});}
  finally {store.close();}
  return {id:'rook',mode:'paused',destination:'mesh_relay_inbox',boardPath,
    boardIdentity:databaseFileIdentity(boardPath),approvalRef:'a'.repeat(64)};
}

test('native Rook enrollment refuses role substitution, activation and a different board',async()=>{
  const enrollment=testEnrollment('data/native-rook-'+randomUUID());
  const input=grant=>stream(JSON.stringify({...JSON.parse(frame(options())),rookEnrollment:grant}));
  for(const extra of [{id:'echo'},{mode:'running'},{destination:'telegram'},{enabled:true},{boardPath:'elsewhere'},{approvalRef:''}]){
    await assert.rejects(readNativeMeshInput(input({...enrollment,...extra})),/could not be verified/);
  }
  await assert.rejects(readNativeRecallInput(input(enrollment)),/could not be verified/);
  await assert.rejects(startNativeMesh({appOptions:{rookEnrollment:enrollment}}),/could not be verified/);
  const copy='data/native-rook-copy-'+randomUUID();
  mkdirSync(copy);
  copyFileSync(enrollment.boardPath,resolve(copy,'tasks.sqlite'));
  const app=await startNativeMesh({input:input({...enrollment,boardPath:resolve(copy,'tasks.sqlite')}),
    appOptions:{dataDir:copy,relayEnabled:false}});
  try {
    assert.equal(app.rookRuntime.status().status,'not_configured');
    assert.equal(app.rookRuntime.start().scheduler.enabled,false);
    assert.equal((await fetch(app.url+'/')).status,200);
  } finally {await app.close();}
});

test('replacing the board withdraws enrollment for the rest of that Mesh process',()=>{
  const record=testEnrollment('data/native-rook-replace-'+randomUUID());
  const grant=nativeRookOptions(record,record.boardPath);
  assert.equal(grant.verifyIdentity(grant.identity),true);
  const original=record.boardPath+'.original', other=record.boardPath+'.other';
  renameSync(record.boardPath,original);
  copyFileSync(original,record.boardPath);
  assert.equal(grant.verifyIdentity(grant.identity),false);
  renameSync(record.boardPath,other);
  renameSync(original,record.boardPath);
  assert.equal(grant.verifyIdentity(grant.identity),false);
  const fresh=nativeRookOptions(record,record.boardPath);
  assert.equal(fresh.verifyIdentity(fresh.identity),true);
});

test('inherited input accepts one bounded verified frame; no caller app configuration',async()=>{
  assert.deepEqual(await readNativeRecallInput(stream(frame(options()))),options());
  const bad=[ '', 'not json synthetic-pipe-only-token',frame(options())+frame(options()),
    JSON.stringify({schema:frameSchema,mindRecallOptions:options(),appOptions:{port:9999}}),
    frame({...options(),binding:{...options().binding,scopeId:'agent/echo/private'}}),
    frame({...options(),baseUrl:'https://example.com'}),'x'.repeat(16385),Buffer.from([255]) ];
  for(const value of bad)await assert.rejects(readNativeRecallInput(stream(value)),error=>
    error.message==='Native Mesh input could not be verified.');
  await assert.rejects(startNativeMesh({input:stream(frame(options())),appOptions:{mindRecallOptions:options()}}));
});

test('unfinished input times out without accepting partial frame or echoing secrets',async()=>{
  const pipe=new PassThrough();pipe.write(frame(options()));
  await assert.rejects(readNativeRecallInput(pipe,{timeoutMs:30}),/could not be verified/);
  pipe.destroy();
});

test('real Mesh remains usable after the independent reader stops and inherited pipe is closed',async()=>{
  const names=['MESH_STANDALONE','MESH_RELAY_MODE','MESH_MODEL_OBSERVATION','MESH_NEMOTRON_CONTROL','MESH_SIMPLE_FLOW','MESH_NIMS'];
  const old=Object.fromEntries(names.map(k=>[k,process.env[k]]));
  delete process.env.MESH_STANDALONE;process.env.MESH_RELAY_MODE='child';
  for(const k of names.slice(2))process.env[k]='0';
  let app;
  const reader=createServer((req,res)=>{
    assert.equal(req.headers.authorization,'Bearer synthetic-pipe-only-token');
    req.resume();res.writeHead(200,{'Content-Type':'application/json'});
    res.end(JSON.stringify({schema:'onoes-mind-recall/v1',requestId:'synthetic',source:'canonical_ledger',observedAt:new Date().toISOString(),records:[]}));
  });
  try{
    await new Promise(resolve=>reader.listen(0,'127.0.0.1',resolve));
    const native=options();native.baseUrl=`http://127.0.0.1:${reader.address().port}/`;
    app=await startNativeMesh({input:stream(frame(native)),appOptions:{port:0,dataDir:'data/native-pipe-'+randomUUID(),relayEnabled:false}});
    const boot=await fetch(app.url+'/api/trial-session/bootstrap',{method:'POST',headers:{Origin:app.url,'Content-Type':'application/json'},body:'{}'});
    const session=await boot.json();const headers={Origin:app.url,'Content-Type':'application/json',Cookie:boot.headers.get('set-cookie').split(';')[0],'X-Trial-CSRF':session.csrfToken};
    const recall=()=>fetch(app.url+'/api/mind/recall',{method:'POST',headers,body:JSON.stringify({query:'fixture',limit:8})});
    assert.equal((await recall()).status,200);
    reader.closeAllConnections();await new Promise(resolve=>reader.close(resolve));
    const refused=await recall();assert.equal(refused.status,503);assert.doesNotMatch(await refused.text(),/synthetic-pipe-only-token/);
    assert.equal((await fetch(app.url+'/')).status,200);
    const tasks=await fetch(app.url+'/api/tasks',{headers});assert.equal(tasks.status,200);assert.ok(Array.isArray((await tasks.json()).tasks));
  }finally{
    await app?.close();if(reader.listening){reader.closeAllConnections();await new Promise(resolve=>reader.close(resolve));}
    for(const k of names)if(old[k]===undefined)delete process.env[k];else process.env[k]=old[k];
  }
});

test('actual child entry refuses token arguments and malformed pipe data without echo',async()=>{
  for(const args of [['integrations/native-mind-mesh-entry.mjs'],['integrations/native-mind-mesh-entry.mjs','synthetic-pipe-only-token'],['serve.mjs','--native-mind']]){
    const child=spawn(process.execPath,args,{stdio:['pipe','pipe','pipe'],windowsHide:true});
    let output='';child.stdout.on('data',b=>output+=b);child.stderr.on('data',b=>output+=b);
    child.stdin.on('error',()=>{});child.stdin.end('synthetic-pipe-only-token');
    const code=await new Promise((resolve,reject)=>{child.once('error',reject);child.once('exit',resolve);});
    assert.equal(code,1);assert.match(output,/mesh_native_refused/);assert.doesNotMatch(output,/synthetic-pipe-only-token/);
  }
});

for(const gateway of [false,true])test(`actual launched ${gateway?'phone gateway':'Mesh'} receives credentials only over stdin and survives reader loss`, {timeout:20000},async()=>{
  const env={...process.env,MESH_PORT:'0',MESH_DATA_DIR:'data/native-child-'+randomUUID(),MESH_RELAY:'0',
    MESH_RELAY_MODE:'child',MESH_MODEL_OBSERVATION:'0',MESH_NEMOTRON_CONTROL:'0',MESH_SIMPLE_FLOW:'0',MESH_NIMS:'0',
    MESH_PREVIEW_PORT:'0',MESH_GATE_TOKEN:'synthetic-gateway-token'};
  delete env.MESH_STANDALONE;
  delete env.MESH_NATIVE_WORKER_RECORD;delete env.MESH_NATIVE_WORKER_RECORD_SHA256;
  delete env.MESH_TAILSCALE_LOGIN;delete env.MESH_TAILSCALE_HOST;
  const reader=createServer((req,res)=>{
    req.resume();res.writeHead(200,{'Content-Type':'application/json'});
    res.end(JSON.stringify({schema:'onoes-mind-recall/v1',requestId:'synthetic',source:'canonical_ledger',observedAt:new Date().toISOString(),records:[]}));
  });
  let child,output='',stderr='';
  try{
    await new Promise(resolve=>reader.listen(0,'127.0.0.1',resolve));
    const native=options();native.baseUrl=`http://127.0.0.1:${reader.address().port}/`;
    child=spawn(process.execPath,gateway?['serve.mjs','--native-mind']:['integrations/native-mind-mesh-entry.mjs'],{env,stdio:['pipe','pipe','pipe'],windowsHide:true});
    const ready=new Promise((resolve,reject)=>{
      const timer=setTimeout(()=>reject(Error('Test-owned child did not report ready.')),10000);
      child.once('error',error=>{clearTimeout(timer);reject(error);});
      child.once('exit',()=>{clearTimeout(timer);reject(Error('Test-owned child exited before ready.'));});
      child.stdout.on('data',bytes=>{
        output+=bytes;
        if(output.includes('\n')){
          clearTimeout(timer);
          try{resolve(JSON.parse(output.trim()));}catch{reject(Error('Unexpected fixed readiness output.'));}
        }
      });
    });
    child.stderr.on('data',bytes=>stderr+=bytes);
    const input=JSON.parse(frame(native));
    if(gateway)input.rookEnrollment=testEnrollment(env.MESH_DATA_DIR);
    child.stdin.end(JSON.stringify(input));
    const status=await ready;
    if(!gateway)assert.deepEqual(Object.keys(status).sort(),['event','mode','pid','url']);
    assert.equal(status.event,gateway?'mesh_listening':'mesh_native_listening');assert.equal(status.pid,child.pid);
    assert.doesNotMatch(output+stderr,/synthetic-pipe-only-token|fixture:not-live-approval|storeId/);
    const url=gateway?status.previewUrl:status.url;
    const gateCookie=gateway?'mesh_session='+createHash('sha256').update('mesh-cookie:synthetic-gateway-token').digest('hex'):'';
    const gateHeaders=gateway?{Cookie:gateCookie}:{};
    if(gateway)assert.equal((await fetch(url+'/api/mind/status')).status,401);
    if(gateway)assert.equal((await (await fetch(url+'/gate/status',{headers:gateHeaders})).json()).gated,true);
    const boot=await fetch(url+'/api/trial-session/bootstrap',{method:'POST',headers:{...gateHeaders,Origin:url,'Content-Type':'application/json'},body:'{}'});
    const bootBody=await boot.text();assert.ok(boot.ok,`Fixture bootstrap returned ${boot.status}; ${bootBody}`);
    const session=JSON.parse(bootBody);const headers={Origin:url,'Content-Type':'application/json',Cookie:[gateCookie,boot.headers.get('set-cookie').split(';')[0]].filter(Boolean).join('; '),'X-Trial-CSRF':session.csrfToken};
    const rook=await (await fetch(url+'/api/workroom/rook',{headers})).json();
    assert.equal(rook.connection.status,gateway?'paused':'not_configured');
    assert.equal(rook.connection.source,gateway?'native_mesh_profile':'none');
    assert.equal(rook.sweep.schedulerInstalled,false);
    assert.equal(rook.sweep.lastScheduledAt,null);
    assert.doesNotMatch(JSON.stringify(rook.connection),/boardPath|boardIdentity|approvalRef/);
    const recall=()=>fetch(url+'/api/mind/recall',{method:'POST',headers,body:JSON.stringify({query:'fixture',limit:8})});
    assert.equal((await recall()).status,200);
    reader.closeAllConnections();await new Promise(resolve=>reader.close(resolve));
    assert.equal((await recall()).status,503);
    assert.equal(child.exitCode,null);assert.equal((await fetch(url+'/api/tasks',{headers})).status,200);
    assert.doesNotMatch(output+stderr,/synthetic-pipe-only-token/);
  }finally{
    if(child && child.exitCode===null){const exited=new Promise(resolve=>child.once('exit',resolve));child.kill();await exited;}
    if(reader.listening){reader.closeAllConnections();await new Promise(resolve=>reader.close(resolve));}
  }
});
