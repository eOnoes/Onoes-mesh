import test from 'node:test';import assert from 'node:assert/strict';
import {createMindRecallClient,configureMindRecall,validateRecall,recallInput} from '../lib/mind-recall.mjs';
import {recallConnection} from '../public/mind-workspace.mjs';
const valid={schema:'onoes-mind-recall/v1',requestId:'fixture-request',source:'canonical_ledger',observedAt:new Date().toISOString(),records:[]};
const approvedFixture=()=>({baseUrl:'http://127.0.0.1:12345/',token:'synthetic-native-token',binding:{servicePrincipal:'mesh-recall',storeId:'00000000-0000-4000-8000-000000000001',environment:'synthetic',scopeId:'project/onoes-mind/shared',reviewRef:'fixture:review-only-not-live-approval'}});
test('recall client refuses remote/credential URLs and malformed input before sending',async()=>{
 for(const baseUrl of ['https://example.com','http://localhost:8080','http://127.0.0.1:80/path','http://user:pass@127.0.0.1:80/','http://127.0.0.1:80/?token=x'])assert.throws(()=>createMindRecallClient({baseUrl,token:'test'}));
 for(const body of [{query:'x',limit:8,scope:'other'},{query:' ',limit:8},{query:'x',limit:21}])assert.throws(()=>recallInput(body));
 assert.deepEqual(validateRecall(valid,8),valid);
 for(const body of [{...valid,source:'unknown'},{...valid,token:'leak'},{...valid,records:[{claim:'malformed'}]}])assert.throws(()=>validateRecall(body,8));
});
test('recall client sends only the fixed versioned read and refuses oversized/error responses',async()=>{
 let calls=[];const client=createMindRecallClient({baseUrl:'http://127.0.0.1:12345',token:'synthetic',fetchImpl:async(url,options)=>{calls.push({url:String(url),options});return new Response(JSON.stringify(valid),{headers:{'Content-Type':'application/json'}});}});
 assert.deepEqual(await client.recall({query:'sentinel',limit:8}),valid);assert.equal(calls.length,1);assert.equal(calls[0].url,'http://127.0.0.1:12345/v1/recall');assert.equal(calls[0].options.redirect,'error');assert.deepEqual(JSON.parse(calls[0].options.body),{schema:valid.schema,query:'sentinel',limit:8});
 for(const response of [()=>new Response('private upstream error',{status:401}),()=>new Response('x'.repeat(65537),{headers:{'Content-Type':'application/json'}})]){
  const bad=createMindRecallClient({baseUrl:'http://127.0.0.1:12345',token:'synthetic',fetchImpl:async()=>response()});await assert.rejects(bad.recall({query:'sentinel',limit:8}),/could not be verified/);
 }
});


test('ordinary Mesh has no configured Mind reader and rejects fixture injection outside standalone',async()=>{
 const {startApp}=await import('../server.mjs');const {randomUUID}=await import('node:crypto');const previous=process.env.MESH_STANDALONE;
 delete process.env.MESH_STANDALONE;
 await assert.rejects(startApp({mindRecallTestOptions:{source:'disposable_fixture',baseUrl:'http://127.0.0.1:12345',token:'synthetic'}}),/synthetic standalone/);
 process.env.MESH_STANDALONE='1';let app;
 try{
  app=await startApp({dataDir:'data/mind-disabled-'+randomUUID()});const boot=await fetch(app.url+'/api/trial-session/bootstrap',{method:'POST',headers:{Origin:app.url,'Content-Type':'application/json'},body:'{}'});const p=await boot.json();const headers={Origin:app.url,'Content-Type':'application/json',Cookie:boot.headers.get('set-cookie').split(';')[0],'X-Trial-CSRF':p.csrfToken};
  assert.deepEqual(await (await fetch(app.url+'/api/mind/status',{headers})).json(),{configured:false,source:'not_configured'});
  assert.equal((await fetch(app.url+'/api/mind/recall',{method:'POST',headers,body:JSON.stringify({query:'sentinel',limit:8})})).status,503);
 }finally{await app?.close();if(previous===undefined)delete process.env.MESH_STANDALONE;else process.env.MESH_STANDALONE=previous;}
});

test('native recall configuration stays separate from fixtures and rejects widened or malformed binding',()=>{
 assert.deepEqual(configureMindRecall({standalone:false}),{client:null,source:'not_configured'});
 assert.equal(configureMindRecall({standalone:false,approvedOptions:approvedFixture()}).source,'canonical_ledger');
 assert.throws(()=>configureMindRecall({standalone:true,approvedOptions:approvedFixture()}));
 assert.throws(()=>configureMindRecall({standalone:false,fixtureOptions:{baseUrl:'http://127.0.0.1:12345/',source:'disposable_fixture',token:'synthetic'}}));
 for(const changes of [{servicePrincipal:'echo'},{scopeId:'agent/echo/private'},{scopeId:'project/other/shared'},{storeId:'not-a-uuid'},{storeId:123},{environment:''},{reviewRef:''},{reviewRef:'bad\nreference'}]){
  const options=approvedFixture();Object.assign(options.binding,changes);assert.throws(()=>configureMindRecall({standalone:false,approvedOptions:options}));
 }
 for(const extra of [{fetchImpl:()=>{}},{source:'canonical_ledger'},{approved:true}])assert.throws(()=>configureMindRecall({standalone:false,approvedOptions:{...approvedFixture(),...extra}}));
});

test('a bound client refuses private-scope configuration before any request',()=>{
 assert.throws(()=>createMindRecallClient({baseUrl:'http://127.0.0.1:12345/',token:'synthetic',expectedScope:'agent/echo/private'}));
});

test('memory view distinguishes canonical and fixture sources and refuses an unknown configured source',()=>{
 const canonical=recallConnection({configured:true,source:'canonical_ledger'});
 assert.equal(canonical.configured,true);assert.match(canonical.message,/deliberately shared/);assert.doesNotMatch(canonical.message,/Synthetic/);
 const fixture=recallConnection({configured:true,source:'disposable_fixture'});
 assert.equal(fixture.configured,true);assert.match(fixture.message,/Synthetic test/);
 for(const source of [undefined,'unknown','not_configured'])assert.equal(recallConnection({configured:true,source}).configured,false);
 assert.equal(recallConnection({configured:false,source:'not_configured'}).configured,false);
});

test('native Mesh route labels reviewed configuration accurately and rejects leaked scopes or caller configuration',async()=>{
 const {startApp}=await import('../server.mjs');const {randomUUID}=await import('node:crypto');const http=await import('node:http');
 const names=['MESH_STANDALONE','MESH_RELAY_MODE','MESH_MODEL_OBSERVATION','MESH_NEMOTRON_CONTROL','MESH_SIMPLE_FLOW','MESH_NIMS'];
 const old=Object.fromEntries(names.map(name=>[name,process.env[name]]));
 delete process.env.MESH_STANDALONE;process.env.MESH_RELAY_MODE='child';
 for(const name of names.slice(2))process.env[name]='0';
 let app,scope='project/onoes-mind/shared',calls=0;
 const record=()=>({record_id:'fixture-record',scope_id:scope,kind:'project_fact',project_id:'fixture',payload_hash:'a'.repeat(64),claim:'fixture shared fact',source_class:'fixture',observed_at:null,provenance:[{type:'fixture',ref:'fixture:source',content_hash:'b'.repeat(64)}]});
 const reader=http.createServer((req,res)=>{calls++;assert.equal(req.url,'/v1/recall');assert.equal(req.headers.authorization,'Bearer synthetic-native-token');req.resume();res.writeHead(200,{'Content-Type':'application/json'});res.end(JSON.stringify({...valid,records:[record()]}));});
 try{
  await new Promise((resolve,reject)=>{reader.once('error',reject);reader.listen(0,'127.0.0.1',resolve);});
  const options=approvedFixture();options.baseUrl='http://127.0.0.1:'+reader.address().port+'/';
  app=await startApp({dataDir:'data/mind-native-fixture-'+randomUUID(),relayEnabled:false,mindRecallOptions:options});
  assert.equal((await fetch(app.url+'/api/mind/status')).status,401);
  const boot=await fetch(app.url+'/api/trial-session/bootstrap',{method:'POST',headers:{Origin:app.url,'Content-Type':'application/json'},body:'{}'});const p=await boot.json();
  const headers={Origin:app.url,'Content-Type':'application/json',Cookie:boot.headers.get('set-cookie').split(';')[0],'X-Trial-CSRF':p.csrfToken};
  const status=await (await fetch(app.url+'/api/mind/status',{headers})).json();
  assert.deepEqual(status,{configured:true,source:'canonical_ledger'});assert.doesNotMatch(JSON.stringify(status),/synthetic-native-token|storeId|reviewRef/);
  const call=body=>fetch(app.url+'/api/mind/recall',{method:'POST',headers,body:JSON.stringify(body)});
  const good=await call({query:'fixture',limit:8});assert.equal(good.status,200);assert.equal((await good.json()).records[0].claim,'fixture shared fact');
  const before=calls;assert.equal((await call({query:'fixture',limit:8,baseUrl:options.baseUrl,token:'caller-token'})).status,400);assert.equal(calls,before);
  scope='agent/echo/private';const denied=await call({query:'fixture',limit:8});assert.equal(denied.status,503);assert.doesNotMatch(await denied.text(),/fixture shared fact|agent\/echo|synthetic-native-token/);
 }finally{
  await app?.close();reader.closeAllConnections();await new Promise(resolve=>reader.close(resolve));
  for(const name of names){if(old[name]===undefined)delete process.env[name];else process.env[name]=old[name];}
 }
});
