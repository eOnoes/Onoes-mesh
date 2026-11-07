import test from 'node:test';
import assert from 'node:assert/strict';
import {randomUUID} from 'node:crypto';
import {startApp} from '../server.mjs';
import {supervisedModelFixture} from './supervised-model-fixture.mjs';
async function admit(app){
  const r=await fetch(app.url+'/api/trial-session/bootstrap',{method:'POST',headers:{Origin:app.url,'Content-Type':'application/json'},body:'{}'});
  assert.equal(r.status,201);const b=await r.json();
  return {Origin:app.url,'Content-Type':'application/json',Cookie:r.headers.get('set-cookie').split(';')[0],'X-Trial-CSRF':b.csrfToken};
}
test('actual admitted model proposal/confirm/receipt flow survives Mesh restart without another native command',async()=>{
  const f=supervisedModelFixture(),dataDir='data/supervised-http-'+randomUUID();let app=await startApp({dataDir,relayEnabled:false,supervisedInferenceTestOptions:f.options});
  try{
    assert.equal((await fetch(app.url+'/api/inference/status')).status,401);let headers=await admit(app);
    const request=async(path,body)=>{const r=await fetch(app.url+path,{headers,method:body?'POST':'GET',...(body?{body:JSON.stringify(body)}:{})});return {status:r.status,body:await r.json()};};
    assert.equal((await request('/api/inference/status')).body.profile.id,'nemotron-bolt-local');
    assert.equal((await fetch(app.url+'/api/inference/propose-load',{method:'POST',headers:{...headers,'X-Trial-CSRF':'wrong'},body:'{}'})).status,403);
    const p=await request('/api/inference/propose-load',{});assert.equal(p.status,201);assert.equal(f.calls.length,0);
    const accepted=await request('/api/inference/approve',{proposalId:p.body.proposal.id,confirm:true});assert.equal(accepted.status,200);assert.equal(f.calls.length,1);
    const id=accepted.body.receipt.id;assert.equal((await request('/api/inference/receipt/'+id)).body.receipt.state,'ACCEPTED');
    await app.close();app=await startApp({dataDir,relayEnabled:false,supervisedInferenceTestOptions:f.options});headers=await admit(app);
    assert.equal((await request('/api/inference/status')).body.state,'STARTING');assert.equal(f.calls.length,1);
    f.finish(id);const done=await request('/api/inference/status');assert.equal(done.body.state,'RUNNING');assert.equal(done.body.operation.readBackVerified,true);
    const result=await request('/api/inference/chat',{prompt:'fixture prompt'});assert.equal(result.body.response,'Fixture answer');assert.equal(f.calls.length,1);
    assert.equal(JSON.stringify(done.body.operation).includes('fixture prompt'),false);
  }finally{await app.close();f.db.close();}
});
test('standalone wins over supplied native fixture and never constructs its operation store or probes',async()=>{
  const before=process.env.MESH_STANDALONE;process.env.MESH_STANDALONE='1';const f=supervisedModelFixture();let reads=0;f.options.client.status=async()=>{reads++;throw Error('must not probe');};
  const app=await startApp({dataDir:'data/supervised-standalone-'+randomUUID(),relayEnabled:false,supervisedInferenceTestOptions:f.options});
  try{const headers=await admit(app),r=await fetch(app.url+'/api/inference/status',{headers}),body=await r.json();assert.equal(body.state,'UNAVAILABLE');assert.equal(body.controls.reason,'STANDALONE_NOT_CONFIGURED');assert.equal(reads,0);assert.equal(f.calls.length,0);}
  finally{await app.close();f.db.close();if(before===undefined)delete process.env.MESH_STANDALONE;else process.env.MESH_STANDALONE=before;}
});
