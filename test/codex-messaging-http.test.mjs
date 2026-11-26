import test from 'node:test';import assert from 'node:assert/strict';import {readFile,mkdir,rm} from 'node:fs/promises';import {createHash,randomUUID} from 'node:crypto';import path from 'node:path';import {fileURLToPath} from 'node:url';
import {startApp,ROOT} from '../server.mjs';
const caller='11111111-1111-4111-8111-111111111111',projectId='33333333-3333-4333-8333-333333333333';
const hash=async p=>createHash('sha256').update(await readFile(p)).digest('hex');
async function fixture(t){
 const dataDir='test/app03-codex-messaging-'+randomUUID(),directory=path.join(ROOT,dataDir);await mkdir(directory,{recursive:true});
 const audit=path.join(directory,'synthetic-dispatch.jsonl');
 const changed=['MESH_STANDALONE','MESH_RELAY_MODE','MESH_MODEL_OBSERVATION','MESH_NEMOTRON_CONTROL','MESH_SIMPLE_FLOW','MESH_CODEX_FIXTURE_AUDIT'];
 const prior=new Map(changed.map(k=>[k,process.env[k]]));
 process.env.MESH_STANDALONE='0';process.env.MESH_RELAY_MODE='child';for(const k of ['MESH_MODEL_OBSERVATION','MESH_NEMOTRON_CONTROL','MESH_SIMPLE_FLOW'])process.env[k]='0';process.env.MESH_CODEX_FIXTURE_AUDIT=audit;
 const serverPath=fileURLToPath(new URL('./fixtures/codex-chat-app-fixture.mjs',import.meta.url));
 const options={source:'native_codex_desktop_messaging',projectDirectory:'C:/Owned/Project',transport:{nodePath:process.execPath,serverPath,nodeSha256:await hash(process.execPath),serverSha256:await hash(serverPath),pipePath:'\\\\.\\pipe\\mesh-native-synthetic-only',callerThreadId:caller}};
 let app;
 async function open(){app=await startApp({dataDir,relayEnabled:false,nodeProbeTestOptions:{spawnImpl(){throw Error('Disabled fixture probe');}},codexDesktopOptions:options});
  const headers={Origin:app.url,'Content-Type':'application/json','Sec-Fetch-Site':'same-origin'};
  const boot=await fetch(app.url+'/api/trial-session/bootstrap',{method:'POST',headers,body:'{}'});assert.equal(boot.status,201);const b=await boot.json();
  const proof={...headers,Cookie:boot.headers.get('set-cookie').split(';')[0],'X-Trial-CSRF':b.csrfToken};
  return async(route,body)=>{const response=await fetch(app.url+route,{method:'POST',headers:proof,body:JSON.stringify(body)});return {status:response.status,body:await response.json()};};
 }
 t.after(async()=>{await app?.close();for(const [k,v] of prior)v===undefined?delete process.env[k]:process.env[k]=v;assert.ok(path.resolve(directory).startsWith(path.resolve(ROOT,'test')+path.sep));await rm(directory,{recursive:true,force:true});});
 return {open,async restart(){await app.close();return open();},get app(){return app;},async audit(){try{return (await readFile(audit,'utf8')).trim().split('\n').filter(Boolean).map(s=>JSON.parse(s));}catch{return [];}}};
}
test('authenticated native send/new routes use the real client and receipt store against a synthetic app only',async t=>{
 const f=await fixture(t);let post=await f.open();
 assert.equal((await fetch(f.app.url+'/api/relay/codex/status')).status,401);
 const input={requestId:randomUUID(),threadId:caller,text:'Synthetic initial message'};
 const sent=await post('/api/relay/codex/send',input);assert.equal(sent.status,200);assert.equal(sent.body.receipt.state,'accepted');
 await post('/api/relay/codex/send',input);assert.equal((await f.audit()).length,1);
 const history=await post('/api/relay/codex/history',{threadId:caller});assert.deepEqual(history.body.messages.map(m=>m.role),['user','assistant']);assert.equal(history.body.messages[0].viaRelay,true);assert.equal(history.body.messages[0].text,input.text);
 const created=await post('/api/relay/codex/new',{requestId:randomUUID(),projectId,title:'A new fixture chat',text:'Synthetic new chat'});
 assert.equal(created.body.receipt.state,'accepted');assert.ok(created.body.receipt.nativeThreadId);assert.equal((await f.audit()).length,2);
 const polluted=await post('/api/relay/codex/send',{...input,requestId:randomUUID(),model:'untrusted'});assert.equal(polluted.status,400);assert.equal((await f.audit()).length,2);
 post=await f.restart();const recovered=await post('/api/relay/codex/send',input);assert.equal(recovered.body.receipt.state,'accepted');assert.equal((await f.audit()).length,2);
});
test('a lost native acknowledgement remains unconfirmed across HTTP/server restart and is never resent',async t=>{
 const f=await fixture(t);let post=await f.open();const input={requestId:randomUUID(),threadId:caller,text:'SYNTHETIC_LOST_ACK'};
 const lost=await post('/api/relay/codex/send',input);assert.equal(lost.status,200);assert.equal(lost.body.receipt.state,'unconfirmed');assert.equal((await f.audit()).length,1);
 post=await f.restart();assert.equal((await post('/api/relay/codex/send',input)).body.receipt.state,'unconfirmed');
 assert.equal((await post('/api/relay/codex/send',{...input,requestId:randomUUID()})).status,409);assert.equal((await f.audit()).length,1);
});
