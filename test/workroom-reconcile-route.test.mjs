import test from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';
import {mkdirSync,writeFileSync} from 'node:fs';
import {resolve} from 'node:path';
import {randomUUID} from 'node:crypto';
import {startApp} from '../server.mjs';
import {openTaskStore} from '../lib/task-store.mjs';
test('reconciliation is CSRF guarded and reads only the matching native task without dispatch, cancellation or approval',async()=>{
  const directory='data/reconcile-route-'+randomUUID();mkdirSync(directory,{recursive:true});const keyPath=resolve(directory,'fixture-key');writeFileSync(keyPath,'fixture-key');
  const store=openTaskStore(resolve(directory,'tasks.sqlite'));const task=store.create({title:'Read cancelled attempt'}),other=store.create({title:'Unrelated'});const sendId=randomUUID();
  const send=store.workroom.reserve(task.id,{id:sendId,agentId:'dsh',conversationId:'context',text:'Plan only'},'plan');store.workroom.settle(sendId,'accepted');store.close();
  const methods=[];const native=http.createServer(async(req,res)=>{let raw='';for await(const part of req)raw+=part;const body=JSON.parse(raw);methods.push(body.method);assert.equal(req.url,'/a2a');assert.equal(req.headers.authorization,'Bearer fixture-key');assert.equal(body.method,'GetTask');res.setHeader('Content-Type','application/json');res.end(JSON.stringify({jsonrpc:'2.0',id:body.id,result:{id:body.params.id,contextId:'context',history:[{role:'ROLE_USER',parts:[{text:body.params.id==='peer'?send.payload:'Different handoff'}]}],status:{state:'TASK_STATE_CANCELED',timestamp:'2026-11-05T00:00:00Z'},artifacts:[]}}));});
  await new Promise(resolve=>native.listen(0,'127.0.0.1',resolve));const settings={MESH_RELAY_MODE:'http',MESH_DSH_APPROVAL_ORIGIN:'http://127.0.0.1:'+native.address().port,MESH_DSH_TOKEN_FILE:keyPath,MESH_RELAY_URL:'http://127.0.0.1:9'};const previous={};for(const [key,value] of Object.entries(settings)){previous[key]=process.env[key];process.env[key]=value;}
  let app;let proof={};async function api(route,method='GET',body,headers={}){const r=await fetch(app.url+route,{method,headers:{Origin:app.url,'Content-Type':'application/json',...proof,...headers},...(body?{body:JSON.stringify(body)}:{})});const raw=await r.text();return {status:r.status,body:raw?JSON.parse(raw):null,cookie:r.headers.get('set-cookie')};}
  try{
    app=await startApp({dataDir:directory,relayEnabled:true});const route='/api/workroom/'+task.id+'/reconcile';const body={sendId,peerTaskId:'peer'};
    assert.equal((await api(route,'POST',body)).status,401);const boot=await api('/api/trial-session/bootstrap','POST',{});proof={Cookie:boot.cookie.split(';')[0],'X-Trial-CSRF':boot.body.csrfToken};
    assert.equal((await api(route,'POST',body,{'X-Trial-CSRF':'invalid'})).status,403);
    assert.equal((await api('/api/workroom/'+other.id+'/reconcile','POST',body)).status,409);assert.equal(methods.length,0);
    assert.equal((await api(route,'POST',{...body,peerTaskId:'wrong'})).status,409);
    const first=await api(route,'POST',body);assert.equal(first.status,200,JSON.stringify(first));assert.equal(first.body.task.messages[0].state,'accepted');assert.equal(first.body.task.messages[0].outcome.state,'TASK_STATE_CANCELED');assert.equal(first.body.task.progress.decision,'pending');
    assert.equal((await api(route,'POST',body)).body.duplicate,true);assert.deepEqual(methods,['GetTask','GetTask','GetTask']);
  }finally{if(app)await app.close();native.closeAllConnections();await new Promise(resolve=>native.close(resolve));for(const key of Object.keys(settings)){if(previous[key]===undefined)delete process.env[key];else process.env[key]=previous[key];}}
});
