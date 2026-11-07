import test from 'node:test';import assert from 'node:assert/strict';import {randomUUID} from 'node:crypto';
import {startApp} from '../server.mjs';import {canonicalMindFixture} from './mind-canonical-fixture.mjs';
for(const bound of [false,true])test('actual Mesh HTTP -> Python canonical ledger -> scoped provenance '+(bound?'with reviewed shared-only fixture binding':'with agent fixture')+', admission and no secret response',async()=>{
 const fixture=await canonicalMindFixture(process.env.MESH_MIND_SOURCE,{bound});const previous=process.env.MESH_STANDALONE;process.env.MESH_STANDALONE='1';let app;
 try{
  app=await startApp({dataDir:'data/mind-canonical-'+randomUUID(),mindRecallTestOptions:{source:'disposable_fixture',baseUrl:fixture.baseUrl,token:fixture.token}});
  assert.equal((await fetch(app.url+'/api/mind/status')).status,401);
  const bootstrap=await fetch(app.url+'/api/trial-session/bootstrap',{method:'POST',headers:{Origin:app.url,'Content-Type':'application/json'},body:'{}'});const proof=await bootstrap.json();const headers={Origin:app.url,'Content-Type':'application/json',Cookie:bootstrap.headers.get('set-cookie').split(';')[0],'X-Trial-CSRF':proof.csrfToken};
  const response=await fetch(app.url+'/api/mind/recall',{method:'POST',headers,body:JSON.stringify({query:'meshfixture',limit:8})});assert.equal(response.status,200);const body=await response.json();
  assert.equal(body.source,'canonical_ledger');assert.equal(body.records.length,bound?1:2);if(bound)assert.ok(body.records.every(r=>r.scope_id==='project/onoes-mind/shared'));assert.ok(body.records.every(r=>r.project_id==='mesh-recall-fixture'&&r.provenance[0].ref==='synthetic-memory.md'));assert.doesNotMatch(JSON.stringify(body),/HIDDEN|synthetic-mesh-token/);
  assert.equal((await fetch(app.url+'/api/mind/recall',{method:'POST',headers,body:JSON.stringify({query:'meshfixture',limit:8,agentId:'tripp'})})).status,400);
  await fixture.close();fixture.close=async()=>{};
  assert.equal((await fetch(app.url+'/api/mind/recall',{method:'POST',headers,body:JSON.stringify({query:'meshfixture',limit:8})})).status,503);
 }finally{await app?.close();await fixture.close();if(previous===undefined)delete process.env.MESH_STANDALONE;else process.env.MESH_STANDALONE=previous;}
});
