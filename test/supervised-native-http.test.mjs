import test from 'node:test';
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {once} from 'node:events';
import {createInterface} from 'node:readline';
import {existsSync} from 'node:fs';
import {randomUUID} from 'node:crypto';
import {startApp} from '../server.mjs';
import {createNemotronClient} from '../lib/nemotron-client.mjs';

test('actual Mesh admission → fixed client → actual candidate HTTP → gate → journal recovery survives restart without repeating native work',
  {skip:!existsSync('data/nemotron-supervisor-candidate-latest.json'),timeout:20000},async()=>{
  const child=spawn('python',['-u','-m','test.supervisor-http-fixture'],{windowsHide:true,stdio:['pipe','pipe','pipe']});
  let stderr='';child.stderr.on('data',chunk=>{stderr+=chunk;});
  const lines=createInterface({input:child.stdout})[Symbol.asyncIterator]();let app;
  const read=async()=>{const value=await lines.next();assert.equal(value.done,false,stderr);return JSON.parse(value.value);};
  const invoke=async action=>{child.stdin.write(JSON.stringify({action})+'\n');return read();};
  try{
    const native=await read();assert.match(native.origin,/^http:\/\/127\.0\.0\.1:\d+$/);
    // Test-only transport relocation. Production client remains fixed to8099.
    const client=createNemotronClient({...native,fetchImpl:(url,options)=>{assert.ok(url.startsWith('http://127.0.0.1:8099/mesh/v1/'));return fetch(url.replace('http://127.0.0.1:8099',native.origin),options);}});
    const options={client,qualification:{source:'disposable_fixture',executableSha256:'f'.repeat(64)},verifyResident:async()=>({healthy:true,gpuMapping:'VERIFIED',gpuUuids:['GPU-fixture']})};
    const dataDir='data/native-full-http-'+randomUUID();app=await startApp({dataDir,relayEnabled:false,supervisedInferenceTestOptions:options});
    let headers;
    async function admit(){const r=await fetch(app.url+'/api/trial-session/bootstrap',{method:'POST',headers:{Origin:app.url,'Content-Type':'application/json'},body:'{}'});assert.equal(r.status,201);const value=await r.json();headers={Origin:app.url,'Content-Type':'application/json',Cookie:r.headers.get('set-cookie').split(';')[0],'X-Trial-CSRF':value.csrfToken};}
    async function api(path,body){const r=await fetch(app.url+'/api/inference/'+path,{headers,method:body?'POST':'GET',...(body?{body:JSON.stringify(body)}:{})});const value=await r.json();assert.ok(r.ok,JSON.stringify(value));return value;}
    await admit();assert.equal((await api('status')).controls.unload,true);
    const p=await api('propose-unload',{});assert.deepEqual(await invoke('inspect'),{calls:0,queued:0});
    const ack=await api('approve',{proposalId:p.proposal.id,confirm:true});assert.equal(ack.receipt.state,'ACCEPTED');
    assert.deepEqual(await invoke('finish-and-evict'),{calls:1,queued:0});
    await app.close();app=await startApp({dataDir,relayEnabled:false,supervisedInferenceTestOptions:options});await admit();
    const unknown=await api('status');assert.equal(unknown.state,'UNKNOWN');assert.equal(unknown.controls.recover,true);assert.equal(unknown.controls.load,false);
    const recovery=await api('propose-recover',{});assert.deepEqual(await invoke('inspect'),{calls:1,queued:0});
    const fenced=await api('approve',{proposalId:recovery.proposal.id,confirm:true});assert.equal(fenced.receipt.reason,'OUTCOME_FENCED');assert.equal(fenced.receipt.state,'UNKNOWN');
    const stopped=await api('status');assert.equal(stopped.state,'STOPPED');assert.equal(stopped.controls.load,true);assert.equal(stopped.operation.readBackVerified,false);
    assert.deepEqual(await invoke('inspect'),{calls:1,queued:0});
    await app.close();app=await startApp({dataDir,relayEnabled:false,supervisedInferenceTestOptions:options});await admit();
    assert.equal((await api('status')).operation.reason,'OUTCOME_FENCED');assert.deepEqual(await invoke('inspect'),{calls:1,queued:0});
  }finally{
    if(app)await app.close();const exited=child.exitCode===null?once(child,'exit'):Promise.resolve();child.stdin.end();await exited;
    assert.equal(child.exitCode,0,stderr);
  }
});
