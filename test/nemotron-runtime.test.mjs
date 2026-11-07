import test from 'node:test';
import assert from 'node:assert/strict';
import {createNemotronRuntime} from '../lib/nemotron-runtime.mjs';
import {NEMOTRON_MODEL} from '../lib/model-operation-store.mjs';
const before={bootId:'boot',expected:'expected',moduleSha256:'module',supervisorSha256:'supervisor',owner:{identity:{pid:42}}};
const gpu='GPU-12345678-1234-1234-1234-123456789abc';
function fixture({changed=false,oversize=false}={}){
  const requests=[];
  const client={status:async()=>({...before,expected:changed?'changed':before.expected})};
  const runtime=createNemotronRuntime({client,
    execFileImpl:(exe,args,options,done)=>{assert.equal(options.windowsHide,true);assert.equal(options.timeout,2500);done(null,`42, ${gpu}\n99, GPU-aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa`);},
    fetchImpl:async(url,options)=>{requests.push({url,options});assert.equal(options.redirect,'manual');assert.equal(options.credentials,'omit');return new Response(JSON.stringify(oversize?{text:'x'.repeat(17000)}:url.endsWith('/health')?{status:'ok'}:url.endsWith('/models')?{data:[{id:NEMOTRON_MODEL}]}:{choices:[{message:{content:'answer'}}]}),{headers:{'content-type':'application/json'}});}});
  return {runtime,requests,client};
}
test('resident proof binds child health and exact GPU PID to unchanged native owner',async()=>{
  const {runtime,requests}=fixture();assert.deepEqual(await runtime.verifyResident(before),{ownerChanged:false,healthy:true,gpuMapping:'VERIFIED',gpuUuids:[gpu]});
  assert.equal(requests.length,2);assert.ok(requests.every(r=>r.options.method==='GET'));
  assert.deepEqual(await fixture({changed:true}).runtime.verifyResident(before),{ownerChanged:true,healthy:false,gpuMapping:'UNKNOWN',gpuUuids:[]});
});
test('chat delegates to the guarded supervisor with cancellation/admission and never POSTs directly to the child',async()=>{
  const {runtime,requests,client}=fixture();const abort=new AbortController(),admitted=()=>true;
  client.chat=async(prompt,native,options)=>{assert.equal(prompt,'private');assert.equal(native,before);assert.equal(options.signal,abort.signal);assert.equal(options.admitted,admitted);return {response:'answer',expected:'new-token'};};
  assert.deepEqual(await runtime.chatImpl('private',{signal:abort.signal,native:before,admitted}),{response:'answer',expected:'new-token'});assert.equal(requests.length,0);
  await assert.rejects(fixture({oversize:true}).runtime.verifyResident(before),/bound/);
});
