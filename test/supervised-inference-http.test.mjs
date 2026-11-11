import test from 'node:test';
import assert from 'node:assert/strict';
import {randomUUID} from 'node:crypto';
import {DatabaseSync} from 'node:sqlite';
import {resolve} from 'node:path';
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
    const stop=await request('/api/inference/propose-stop',{});await request('/api/inference/approve',{proposalId:stop.body.proposal.id,confirm:true});assert.equal(f.calls.length,2);
    f.receipts.clear();f.setNative({...f.getNative(),bootId:randomUUID(),active:null});
    let unknown=await request('/api/inference/status');assert.equal(unknown.body.controls.recover,true);assert.equal(unknown.body.controls.stop,false);
    assert.equal((await fetch(app.url+'/api/inference/propose-recover',{method:'POST',headers:{...headers,'X-Trial-CSRF':'wrong'},body:'{}'})).status,403);
    const recover=await request('/api/inference/propose-recover',{});assert.equal(recover.status,201);assert.equal(f.recoveries.length,0);
    const fenced=await request('/api/inference/approve',{proposalId:recover.body.proposal.id,confirm:true});assert.equal(fenced.status,200);assert.equal(fenced.body.receipt.state,'UNKNOWN');assert.equal(fenced.body.receipt.reason,'OUTCOME_FENCED');
    await app.close();app=await startApp({dataDir,relayEnabled:false,supervisedInferenceTestOptions:f.options});headers=await admit(app);
    unknown=await request('/api/inference/status');assert.equal(unknown.body.state,'RUNNING');assert.equal(unknown.body.controls.stop,true);assert.equal(unknown.body.operation.reason,'OUTCOME_FENCED');assert.equal(f.calls.length,2);assert.equal(f.recoveries.length,1);
  }finally{await app.close();f.db.close();}
});
test('standalone wins over supplied native fixture and never constructs its operation store or probes',async()=>{
  const before=process.env.MESH_STANDALONE;process.env.MESH_STANDALONE='1';const f=supervisedModelFixture();let reads=0;f.options.client.status=async()=>{reads++;throw Error('must not probe');};
  const app=await startApp({dataDir:'data/supervised-standalone-'+randomUUID(),relayEnabled:false,supervisedInferenceTestOptions:f.options});
  try{const headers=await admit(app),r=await fetch(app.url+'/api/inference/status',{headers}),body=await r.json();assert.equal(body.state,'UNAVAILABLE');assert.equal(body.controls.reason,'STANDALONE_NOT_CONFIGURED');assert.equal(reads,0);assert.equal(f.calls.length,0);}
  finally{await app.close();f.db.close();if(before===undefined)delete process.env.MESH_STANDALONE;else process.env.MESH_STANDALONE=before;}
});


test('completed load and unload receipts remain in the app database after restart without retaining chat',async()=>{
  const f=supervisedModelFixture(),dataDir='data/supervised-cycle-'+randomUUID();
  let app=await startApp({dataDir,relayEnabled:false,supervisedInferenceTestOptions:f.options});
  let headers=await admit(app);
  const request=async(path,body)=>{const r=await fetch(app.url+path,{headers,method:body?'POST':'GET',...(body?{body:JSON.stringify(body)}:{})});assert.ok(r.ok,`${path}: ${r.status}`);return r.json();};
  const ids=[];
  try{
    for(const action of ['load','unload']){
      const proposed=await request('/api/inference/propose-'+action,{});
      const accepted=await request('/api/inference/approve',{proposalId:proposed.proposal.id,confirm:true});
      ids.push(accepted.receipt.id);f.finish(accepted.receipt.id);
      const status=await request('/api/inference/status');assert.equal(status.state,action==='load'?'RUNNING':'STOPPED');
      if(action==='load')assert.equal((await request('/api/inference/chat',{prompt:'private-chat-sentinel'})).response,'Fixture answer');
    }
    assert.equal(f.calls.length,2);
    const rows=()=>{const db=new DatabaseSync(resolve(dataDir,'tasks.sqlite'),{readOnly:true});try{return db.prepare('SELECT id,state,binding,envelope,events FROM model_operations ORDER BY rowid').all();}finally{db.close();}};
    const before=rows();assert.deepEqual(before.map(row=>row.id),ids);assert.ok(before.every(row=>row.state==='COMPLETED'));
    assert.deepEqual(before.map(row=>JSON.parse(row.binding).command.action),['load','unload']);
    assert.equal(JSON.stringify(before).includes('private-chat-sentinel'),false);
    assert.equal(JSON.stringify(before).includes('Fixture answer'),false);
    await app.close();app=await startApp({dataDir,relayEnabled:false,supervisedInferenceTestOptions:f.options});headers=await admit(app);
    assert.equal((await request('/api/inference/status')).state,'STOPPED');
    for(const id of ids){const row=(await request('/api/inference/receipt/'+id)).receipt;assert.equal(row.id,id);assert.equal(row.state,'COMPLETED');}
    assert.deepEqual(rows(),before);assert.equal(f.calls.length,2,'restart and receipt reads cannot resend either command');
  }finally{await app.close();f.db.close();}
});
