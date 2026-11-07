import test from 'node:test';import assert from 'node:assert/strict';
import {createMindRecallClient,validateRecall,recallInput} from '../lib/mind-recall.mjs';
const valid={schema:'onoes-mind-recall/v1',requestId:'fixture-request',source:'canonical_ledger',observedAt:new Date().toISOString(),records:[]};
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
