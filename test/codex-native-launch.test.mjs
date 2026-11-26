import {createServer} from 'node:http';
import test from 'node:test';import assert from 'node:assert/strict';
import {Readable} from 'node:stream';import {readFile,mkdir,rm} from 'node:fs/promises';
import {createHash,randomUUID} from 'node:crypto';import {fileURLToPath} from 'node:url';import path from 'node:path';import {spawn,execFileSync} from 'node:child_process';
import {readNativeMeshInput,readNativeRecallInput,startNativeMesh,frameSchema} from '../integrations/native-mind-mesh-entry.mjs';
import {ROOT} from '../server.mjs';import {validateCodexDesktopOptions} from '../lib/codex-conversations.mjs';
const caller='11111111-1111-4111-8111-111111111111';
const hash=async p=>createHash('sha256').update(await readFile(p)).digest('hex');
async function options(){const serverPath=fileURLToPath(new URL('./fixtures/codex-chat-app-fixture.mjs',import.meta.url));return {source:'native_codex_desktop_messaging',projectDirectory:'C:/Owned/Project',transport:{nodePath:process.execPath,serverPath,nodeSha256:await hash(process.execPath),serverSha256:await hash(serverPath),pipePath:'\\\\.\\pipe\\synthetic-native-launch-only',callerThreadId:caller}};}
const memory=()=>({baseUrl:'http://127.0.0.1:12345/',token:'synthetic-inherited-frame-only',binding:{servicePrincipal:'mesh-recall',storeId:'00000000-0000-4000-8000-000000000001',environment:'synthetic',scopeId:'project/onoes-mind/shared',reviewRef:'fixture:not-live-approval'}});
const frame=codexDesktopOptions=>({schema:frameSchema,mindRecallOptions:memory(),codexDesktopOptions});
const input=value=>Readable.from([Buffer.from(JSON.stringify(value))]);
function environment(t){const keys=['MESH_STANDALONE','MESH_RELAY_MODE','MESH_MODEL_OBSERVATION','MESH_NEMOTRON_CONTROL','MESH_SIMPLE_FLOW'];const saved=Object.fromEntries(keys.map(k=>[k,process.env[k]]));Object.assign(process.env,{MESH_STANDALONE:'0',MESH_RELAY_MODE:'child',MESH_MODEL_OBSERVATION:'0',MESH_NEMOTRON_CONTROL:'0',MESH_SIMPLE_FLOW:'0'});t.after(()=>{for(const k of keys)saved[k]===undefined?delete process.env[k]:process.env[k]=saved[k];});}
async function ownedData(t){const dataDir='test/app03-codex-launch-'+randomUUID(),directory=path.join(ROOT,dataDir);await mkdir(directory);t.after(async()=>{assert.ok(path.resolve(directory).startsWith(path.resolve(ROOT,'test')+path.sep));await rm(directory,{recursive:true,force:true});});return dataDir;}
async function admitted(url,cookie=''){
 const headers={Origin:url,'Content-Type':'application/json',...(cookie?{Cookie:cookie}:{})};const boot=await fetch(url+'/api/trial-session/bootstrap',{method:'POST',headers,body:'{}'});assert.equal(boot.status,201);
 const b=await boot.json();headers.Cookie=[cookie,boot.headers.get('set-cookie').split(';')[0]].filter(Boolean).join('; ');headers['X-Trial-CSRF']=b.csrfToken;
 return async(route,body)=>{const r=await fetch(url+route,{method:body===undefined?'GET':'POST',headers,...body===undefined?{}:{body:JSON.stringify(body)}});return {status:r.status,body:await r.json()};};
}
test('native chat config travels only through the trusted Mesh frame and leaves memory options intact',async()=>{
 const config=await options(),body=frame(config);const accepted=await readNativeMeshInput(input(body));assert.deepEqual(accepted.codexDesktopOptions,config);assert.deepEqual(accepted.mindRecallOptions,body.mindRecallOptions);
 await assert.rejects(readNativeRecallInput(input(body)),/could not be verified/);
 await assert.rejects(startNativeMesh({appOptions:{codexDesktopOptions:config}}),/could not be verified/);
});
test('native enrollment rejects browser-style model, identity, source and transport overrides',async()=>{
 const config=await options();
 for(const changed of [{...config,model:'override'},{...config,projectDirectory:'../other'},{...config,source:'browser'},{...config,transport:{...config.transport,callerThreadId:'echo'}},{...config,transport:{...config.transport,discovery:'guess'}},{...config,transport:{...config.transport,serverSha256:'changed'}}]){
  assert.throws(()=>validateCodexDesktopOptions(changed));await assert.rejects(readNativeMeshInput(input(frame(changed))),/could not be verified/);
 }
});
test('unavailable Codex does not stop Mesh and a stale native source pin never launches a proxy',async t=>{
 environment(t);const dataDir=await ownedData(t),config=await options();config.transport.serverSha256='0'.repeat(64);
 const app=await startNativeMesh({input:input(frame(config)),appOptions:{dataDir,relayEnabled:false,nodeProbeTestOptions:{spawnImpl(){throw Error('Disabled hardware probe');}}}});
 try{const rpc=await admitted(app.url);assert.equal((await rpc('/api/relay/codex/status')).body.configured,true);assert.equal((await rpc('/api/relay/codex/catalog',{})).status,503);assert.equal((await rpc('/api/workroom')).status,200);assert.equal((await fetch(app.url+'/')).status,200);}
 finally{await app.close();}
});
test('existing serve gateway accepts the inherited native chat frame with its normal admission gate',async t=>{
 const dataDir=await ownedData(t),config=await options(),body=frame(config),gate='synthetic-native-codex-gateway';
 const env={...process.env,MESH_PREVIEW_PORT:'0',MESH_DATA_DIR:dataDir,MESH_RELAY:'0',MESH_RELAY_MODE:'child',MESH_MODEL_OBSERVATION:'0',MESH_NEMOTRON_CONTROL:'0',MESH_SIMPLE_FLOW:'0',MESH_NIMS:'0',MESH_GATE_TOKEN:gate};
 for(const key of ['MESH_STANDALONE','MESH_NATIVE_WORKER_RECORD','MESH_NATIVE_WORKER_RECORD_SHA256','MESH_TAILSCALE_LOGIN','MESH_TAILSCALE_HOST'])delete env[key];
 const child=spawn(process.execPath,['serve.mjs','--native-mind'],{cwd:ROOT,env,windowsHide:true,stdio:['pipe','pipe','pipe']});const ended=new Promise(resolve=>child.once('exit',resolve));let output='',errors='';child.stderr.on('data',b=>errors+=b);
 try{
  const ready=new Promise((resolve,reject)=>{const timer=setTimeout(()=>reject(Error('Owned gateway readiness timed out')),10000);child.once('error',e=>{clearTimeout(timer);reject(e);});child.once('exit',()=>{clearTimeout(timer);reject(Error('Owned gateway stopped before readiness'));});child.stdout.on('data',b=>{output+=b;for(const line of output.split('\n'))try{const v=JSON.parse(line);if(v.event==='mesh_listening'){clearTimeout(timer);resolve(v);}}catch{}});});
  child.stdin.end(JSON.stringify(body));const started=await ready;assert.equal(started.pid,child.pid);assert.equal((await fetch(started.previewUrl+'/api/relay/codex/status')).status,401);
  const cookie='mesh_session='+createHash('sha256').update('mesh-cookie:'+gate).digest('hex'),rpc=await admitted(started.previewUrl,cookie);
  const catalog=await rpc('/api/relay/codex/catalog',{});assert.equal(catalog.status,200);assert.equal(catalog.body.conversations[0].id,caller);
  assert.ok(!output.includes(body.mindRecallOptions.token)&&!errors.includes(body.mindRecallOptions.token));
 }finally{if(child.exitCode===null&&child.signalCode===null)child.kill();await ended;}
});

test('private launcher native-chat contract passes its local Python checks',()=>{
 execFileSync('python',['-X','utf8','-B','-m','unittest','test_native_codex_launch_candidate','-v'],{
  cwd:path.join(ROOT,'integrations/mind-recovery-candidate'),windowsHide:true,stdio:'pipe',timeout:20000});
});

test('an occupied gateway port closes the unopened native journal and preserves the existing listener',{skip:process.platform!=='win32'},async t=>{
 environment(t);const dataDir=await ownedData(t),config=await options(),listener=createServer();
 await new Promise(resolve=>listener.listen(0,'127.0.0.1',resolve));
 try{
  await assert.rejects(startNativeMesh({input:input(frame(config)),appOptions:{port:listener.address().port,dataDir,relayEnabled:false,nodeProbeTestOptions:{spawnImpl(){throw Error('Disabled hardware probe');}}}}),e=>e.code==='EADDRINUSE');
  assert.equal(listener.listening,true);
  // Windows refuses deletion while SQLite still owns this file handle.
  await rm(path.join(ROOT,dataDir,'codex-requests.sqlite'));
 }finally{await new Promise(resolve=>listener.close(resolve));}
});
