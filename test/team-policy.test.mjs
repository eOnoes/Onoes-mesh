import test from 'node:test';
import assert from 'node:assert/strict';
import {randomUUID} from 'node:crypto';
import {automationPolicy} from '../lib/workroom-automation-store.mjs';
import {scopedTeamStatus} from '../public/workroom-plan.mjs';
import {startApp,ROOT} from '../server.mjs';

test('team scope display follows the server policy without qualifying other folders or roles',()=>{
 const policy=automationPolicy('C:/Mesh');const plan={workspace:policy.workspace,workerId:'echo',reviewerId:'nims'};
 assert.equal(scopedTeamStatus(plan,policy).matches,true);
 assert.match(scopedTeamStatus(plan,policy).message,/connections, task revisions and review checks still apply/);
 for(const bad of [{...plan,workspace:plan.workspace+'-other'},{...plan,workerId:'nims'},{...plan,reviewerId:'echo'}])assert.equal(scopedTeamStatus(bad,policy).matches,false);
 for(const invalid of [null,{}, {...policy,schema:'unexpected'}, {...policy,actionLimit:500}])assert.equal(scopedTeamStatus(plan,invalid).matches,false);
 assert.equal(scopedTeamStatus({...plan,workspace:plan.workspace.toUpperCase()+'/'},policy).matches,true);
 assert.deepEqual(policy.builderIds,['echo']);assert.deepEqual(policy.reviewerIds,['dsh','nims']);assert.equal(policy.actionLimit,50);
});

test('actual admitted HTTP exposes the enforced team scope while anonymous reads remain denied',async()=>{
 const previous=process.env.MESH_STANDALONE;process.env.MESH_STANDALONE='1';
 const app=await startApp({dataDir:'data/team-policy-'+randomUUID(),relayEnabled:false});
 try{
  assert.equal((await fetch(app.url+'/api/workroom')).status,401);
  const response=await fetch(app.url+'/api/trial-session/bootstrap',{method:'POST',headers:{Origin:app.url,'Content-Type':'application/json'},body:'{}'});
  assert.equal(response.status,201);const cookie=response.headers.get('set-cookie').split(';')[0];const proof=await response.json();
  const read=await fetch(app.url+'/api/workroom',{headers:{Cookie:cookie,Origin:app.url,'X-Trial-CSRF':proof.csrfToken}});assert.equal(read.status,200);const body=await read.json();
  assert.deepEqual(body.teamPolicy,automationPolicy(ROOT));assert.deepEqual(body.tasks,[]);
 }finally{await app.close();if(previous===undefined)delete process.env.MESH_STANDALONE;else process.env.MESH_STANDALONE=previous;}
});
