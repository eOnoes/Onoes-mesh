import test from 'node:test';
import assert from 'node:assert/strict';
import {createDshApprovalClient} from '../lib/dsh-approval.mjs';
const scope={id:'send',taskId:'workroom',conversationId:'conversation'};
const pending={schema:'mesh-dsh-approval/v1',taskId:'peer',contextId:'conversation',sendId:'send',workroomTaskId:'workroom',requestId:'request',toolName:'read_file',arguments:'{"path":"fixture"}',reason:'Inspect fixture',canApprove:true};
const state={schema:'mesh-dsh-approval/v1',supported:true,pending,binding:{taskId:'peer',contextId:'conversation',sendId:'send',workroomTaskId:'workroom'},task:null};
const response=data=>new Response(JSON.stringify(data),{headers:{'Content-Type':'application/json'}});
test('approval transport is loopback-only, refuses redirects and never returns the key',async()=>{
  for(const origin of ['https://127.0.0.1','http://example.com','http://user:pass@127.0.0.1','http://127.0.0.1/other'])assert.throws(()=>createDshApprovalClient({origin}));
  const key='fixture-secret';const client=createDshApprovalClient({token:key,fetchImpl:async(url,options)=>{assert.ok(!url.includes(key));assert.equal(options.headers.Authorization,'Bearer '+key);assert.equal(options.redirect,'manual');return new Response('',{status:302,headers:{Location:'http://elsewhere/'}});}});
  await assert.rejects(client.inspect(scope),error=>!error.message.includes(key) && /redirect/.test(error.message));
});
test('wrong handoff, peer and conversation bindings fail closed',async()=>{
  for(const change of [{pending:{...pending,sendId:'other'}},{binding:{...state.binding,taskId:'other'}},{task:{id:'peer',contextId:'other'}}]){
    const client=createDshApprovalClient({token:'fixture',fetchImpl:async()=>response({...state,...change})});
    await assert.rejects(client.inspect(scope),e=>e.status===409);
  }
});
test('authorization is rechecked immediately before decision dispatch',async()=>{
  const methods=[];const client=createDshApprovalClient({token:'fixture',fetchImpl:async(url,options)=>{methods.push(options.method);return response(state);}});
  await assert.rejects(client.decide(scope,{requestId:'request',decision:'allow_once'},()=>{throw Object.assign(Error('Task changed'),{status:409});}),/Task changed/);
  assert.deepEqual(methods,['GET']);
});
test('old bridge reports unsupported; oversized and invalid protocols are refused',async()=>{
  const old=createDshApprovalClient({token:'fixture',fetchImpl:async()=>new Response('',{status:404})});assert.equal((await old.inspect(scope)).supported,false);
  for(const value of [{schema:'wrong'}, {...state,extra:'x'.repeat(131072)}]){
    const client=createDshApprovalClient({token:'fixture',fetchImpl:async()=>response(value)});await assert.rejects(client.inspect(scope),e=>e.status===503);
  }
});
test('decision receipt cannot attach another peer task result',async()=>{
  const client=createDshApprovalClient({token:'fixture',fetchImpl:async(url,options)=>response(options.method==='GET'?state:{schema:'mesh-dsh-approval/v1',taskId:'peer',requestId:'request',decision:'allow_once',result:{task:{id:'other',contextId:'conversation'}}})});
  await assert.rejects(client.decide(scope,{requestId:'request',decision:'allow_once'}),e=>e.status===409);
});
test('lost decision response is explicitly unconfirmed, not silently retried',async()=>{
  const methods=[];const client=createDshApprovalClient({token:'fixture',fetchImpl:async(url,options)=>{methods.push(options.method);if(options.method==='POST')throw Error('Response lost');return response(state);}});
  await assert.rejects(client.decide(scope,{requestId:'request',decision:'allow_once'}),e=>e.code==='DSH_DECISION_UNCONFIRMED');assert.deepEqual(methods,['GET','POST']);
});
