import test from 'node:test';
import assert from 'node:assert/strict';
import {createNemotronRuntime} from '../lib/nemotron-runtime.mjs';
import {NEMOTRON_MODEL} from '../lib/model-operation-store.mjs';
const before={bootId:'boot',expected:'expected',moduleSha256:'module',supervisorSha256:'supervisor',owner:{identity:{pid:42}}};
const gpu='GPU-12345678-1234-1234-1234-123456789abc';
function fixture({changed=false,oversize=false}={}){
  const requests=[];
  const runtime=createNemotronRuntime({client:{status:async()=>({...before,expected:changed?'changed':before.expected})},
    execFileImpl:(exe,args,options,done)=>{assert.equal(options.windowsHide,true);assert.equal(options.timeout,2500);done(null,`42, ${gpu}\n99, GPU-aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa`);},
    fetchImpl:async(url,options)=>{requests.push({url,options});assert.equal(options.redirect,'manual');assert.equal(options.credentials,'omit');return new Response(JSON.stringify(oversize?{text:'x'.repeat(17000)}:url.endsWith('/health')?{status:'ok'}:url.endsWith('/models')?{data:[{id:NEMOTRON_MODEL}]}:{choices:[{message:{content:'answer'}}]}),{headers:{'content-type':'application/json'}});}});
  return {runtime,requests};
}
test('resident proof binds child health and exact GPU PID to unchanged native owner',async()=>{
  const {runtime,requests}=fixture();assert.deepEqual(await runtime.verifyResident(before),{ownerChanged:false,healthy:true,gpuMapping:'VERIFIED',gpuUuids:[gpu]});
  assert.equal(requests.length,2);assert.ok(requests.every(r=>r.options.method==='GET'));
  assert.deepEqual(await fixture({changed:true}).runtime.verifyResident(before),{ownerChanged:true,healthy:false,gpuMapping:'UNKNOWN',gpuUuids:[]});
});
test('chat uses fixed endpoint/model, passes cancellation, and refuses oversized output',async()=>{
  const {runtime,requests}=fixture();const abort=new AbortController();assert.equal(await runtime.chatImpl('private',{signal:abort.signal}),'answer');
  const request=requests[0];assert.equal(request.url,'http://127.0.0.1:8199/v1/chat/completions');assert.equal(JSON.parse(request.options.body).model,NEMOTRON_MODEL);
  abort.abort();assert.equal(request.options.signal.aborted,true);
  await assert.rejects(fixture({oversize:true}).runtime.chatImpl('private',{}),/bound/);
});
