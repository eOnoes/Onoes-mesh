import test from 'node:test';
import assert from 'node:assert/strict';
import {randomUUID} from 'node:crypto';
import {createNemotronClient} from '../lib/nemotron-client.mjs';
import {NEMOTRON_MODEL} from '../lib/model-operation-store.mjs';
function fixture(change){
  const binding={modelId:NEMOTRON_MODEL,moduleSha256:'a'.repeat(64),supervisorSha256:'b'.repeat(64),bootId:randomUUID(),command:{id:randomUUID(),action:'load',expected:'c'.repeat(64)}};
  const calls=[],metadata={schemaVersion:'mesh-supervisor-control/v1',moduleSha256:binding.moduleSha256,supervisorSha256:binding.supervisorSha256,bootId:binding.bootId,modelId:NEMOTRON_MODEL};
  const client=createNemotronClient({...binding,fetchImpl:async(url,options)=>{
    calls.push({url,options});assert.equal(options.redirect,'manual');assert.equal(options.credentials,'omit');
    const override=change?.(url,options,metadata);if(override)return override;
    return Response.json(url.endsWith('/status')?{...metadata,expected:binding.command.expected,owner:{state:'empty',identity:null,clear:true},active:null,load:true,unload:false}:{...metadata,receipt:{id:binding.command.id}});
  }});
  return {client,binding,calls,metadata};
}
test('fixed client uses status preflight and exactly one source-bound POST; receipt reads cannot dispatch',async()=>{
  const f=fixture();await f.client.command(f.binding);await f.client.receipt(f.binding);
  assert.deepEqual(f.calls.map(x=>new URL(x.url).pathname),['/mesh/v1/status','/mesh/v1/commands','/mesh/v1/receipts/'+f.binding.command.id]);
  assert.ok(f.calls.every(x=>new URL(x.url).origin==='http://127.0.0.1:8099'));
  assert.deepEqual(JSON.parse(f.calls[1].options.body),f.binding.command);assert.equal(f.calls.filter(x=>x.options.method==='POST').length,1);
});
test('owner/code/boot changes prevent command delivery; a lost POST response never retries',async()=>{
  for(const key of ['moduleSha256','supervisorSha256','bootId','expected']){
    const f=fixture((url,options,m)=>url.endsWith('/status')?Response.json({...m,expected:f.binding.command.expected,owner:{state:'empty'},active:null,load:true,unload:false,[key]:key==='bootId'?randomUUID():'d'.repeat(64)}):null);
    await assert.rejects(f.client.command(f.binding),error=>error.notSent===true);assert.equal(f.calls.filter(x=>x.options.method==='POST').length,0);
  }
  const f=fixture((url,options)=>{if(options.method==='POST')throw Error('response lost');});
  await assert.rejects(f.client.command(f.binding),error=>error.code==='BRIDGE_UNAVAILABLE'&&!error.notSent);
  assert.equal(f.calls.filter(x=>x.options.method==='POST').length,1);
});
test('redirects/oversized/non-JSON/private errors fail closed and cannot choose another endpoint',async()=>{
  for(const reply of [()=>new Response('private',{status:302,headers:{location:'https://other.invalid'}}),
    ()=>new Response('x'.repeat(17000),{headers:{'content-type':'application/json'}}),()=>new Response('private')]){
    const f=fixture(()=>reply());await assert.rejects(f.client.status(),error=>!error.message.includes('private'));
    assert.equal(f.calls.length,1);
  }
  assert.throws(()=>createNemotronClient({}),/hashes/);
});
test('native refusal is attested to the original boot/code; stale boot receipt stays unresolved',async()=>{
  const f=fixture((url,options,m)=>options.method==='POST'?Response.json({...m,error:'OWNER_CHANGED'},{status:409}):null);
  await assert.rejects(f.client.command(f.binding),error=>error.nativeIdentityVerified===true&&error.envelope.bootId===f.binding.bootId);
  const g=fixture((url,options,m)=>Response.json({...m,bootId:randomUUID(),error:'RECEIPT_UNKNOWN'},{status:404}));
  await assert.rejects(g.client.receipt(g.binding),error=>error.code==='NATIVE_BOOT_CHANGED'&&!error.nativeIdentityVerified);
});
