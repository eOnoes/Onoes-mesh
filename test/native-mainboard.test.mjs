import test from 'node:test';
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {mkdtempSync,mkdirSync,writeFileSync,unlinkSync} from 'node:fs';
import {join} from 'node:path';
import {tmpdir} from 'node:os';
import {mainboardNativeConnection} from '../lib/native-mainboard.mjs';
import {createNativeWorkerBinding} from '../lib/workroom-native-binding.mjs';

function fixture() {
  const directory=mkdtempSync(join(tmpdir(),'mesh-native-boot-')),root=join(directory,'project');
  const home=join(directory,'native'),nativeRoot=join(home,'hermes-agent'),pythonExecutable=join(home,'python.exe');
  mkdirSync(root);mkdirSync(nativeRoot,{recursive:true});writeFileSync(pythonExecutable,'Not executed');
  const record={schema:'mesh-native-worker-enrollment/v1',
    profile:{profileRef:'fixture-native',identityRef:'fixture-config-reference',provider:'openai-codex',model:'gpt-6-luna',workspace:root},
    runtime:{home,nativeRoot,pythonExecutable}};
  const file=join(directory,'owner-record.json'),bytes=JSON.stringify(record);writeFileSync(file,bytes);
  const env={MESH_RELAY:'1',MESH_RELAY_MODE:'http',MESH_NATIVE_WORKER_RECORD:file,
    MESH_NATIVE_WORKER_RECORD_SHA256:createHash('sha256').update(bytes).digest('hex')};
  return {directory,root,file,record,env,bytes};
}

test('normal launcher leaves native workers absent without explicit record and hash',()=>{
  let factories=0;
  const result=mainboardNativeConnection({root:process.cwd(),env:{},makeOptions:()=>{factories++;}});
  assert.equal(result.state,'disabled');assert.equal(result.options,undefined);assert.equal(factories,0);
});

test('build-check tools require an explicit hash-approved profile and cannot replace file-only authority',async()=>{
  const f=fixture();let calls=0;
  const makeOptions=options=>({profile:options.profile,authorized:options.authorized,rpc:async()=>{calls++;return {found:false};}});
  const original=mainboardNativeConnection({...f,makeOptions});
  assert.equal(original.state,'configured');assert.equal(Object.hasOwn(original.options.profile,'toolProfile'),false);
  const originalBinding=createNativeWorkerBinding(original.options);
  f.record.profile.toolProfile='build-check-v1';const bytes=JSON.stringify(f.record);writeFileSync(f.file,bytes);
  await assert.rejects(originalBinding.rpc('session.create',{}),/not authorized/);assert.equal(calls,0);await originalBinding.close();
  f.env.MESH_NATIVE_WORKER_RECORD_SHA256=createHash('sha256').update(bytes).digest('hex');
  const explicit=mainboardNativeConnection({...f,makeOptions});assert.equal(explicit.state,'configured');
  assert.equal(explicit.options.profile.toolProfile,'build-check-v1');
  const binding=createNativeWorkerBinding(explicit.options);assert.deepEqual(await binding.rpc('prompt.lookup',{}),{found:false});
  f.record.profile.toolProfile='all-tools';const widened=JSON.stringify(f.record);writeFileSync(f.file,widened);
  f.env.MESH_NATIVE_WORKER_RECORD_SHA256=createHash('sha256').update(widened).digest('hex');
  assert.equal(mainboardNativeConnection({...f,makeOptions}).state,'held');
  await assert.rejects(binding.rpc('session.create',{}),/not authorized/);assert.equal(calls,1);await binding.close();
});

test('invalid requested live enrollment holds the native lane before any transport or Relay fallback',async()=>{
  for(const change of [f=>delete f.env.MESH_NATIVE_WORKER_RECORD_SHA256,
    f=>f.env.MESH_NATIVE_WORKER_RECORD_SHA256='0'.repeat(64),
    f=>writeFileSync(f.file,'invalid JSON'),f=>f.env.MESH_SIMPLE_FLOW='1']){
    const f=fixture();change(f);let factories=0;
    const result=mainboardNativeConnection({...f,makeOptions:()=>{factories++;}});
    assert.equal(result.state,'held');assert.ok(result.options);assert.equal(factories,0);
    const binding=createNativeWorkerBinding(result.options);
    await assert.rejects(binding.rpc('session.create',{}),/not authorized/);await binding.close();
  }
});

test('closed enrollment rejects widened profiles, credentials and worker-editable authority records',()=>{
  for(const change of [r=>r.profile.provider='other',r=>r.profile.model='other',
    r=>r.profile.api_key='not-a-real-key',r=>r.runtime.credential='not-a-real-key',
    r=>r.extra=true,r=>r.profile.workspace='relative']){
    const f=fixture();change(f.record);const bytes=JSON.stringify(f.record);writeFileSync(f.file,bytes);
    f.env.MESH_NATIVE_WORKER_RECORD_SHA256=createHash('sha256').update(bytes).digest('hex');
    let factories=0;const result=mainboardNativeConnection({...f,makeOptions:()=>{factories++;}});
    assert.equal(result.state,'held');assert.equal(factories,0);
  }
  const f=fixture(),file=join(f.root,'editable-owner-record.json');writeFileSync(file,f.bytes);
  const result=mainboardNativeConnection({...f,env:{...f.env,MESH_NATIVE_WORKER_RECORD:file}});
  assert.equal(result.state,'held');assert.equal(result.reason,'record_must_be_outside_worker_workspace');
});

test('approved exact record constructs once and changed or deleted authority revokes before dispatch',async()=>{
  const f=fixture();let factories=0,calls=0;
  const result=mainboardNativeConnection({...f,makeOptions:options=>{
    factories++;return {profile:options.profile,authorized:options.authorized,rpc:async()=>{calls++;return {found:false};}};
  }});
  assert.equal(result.state,'configured');assert.equal(factories,1);
  const binding=createNativeWorkerBinding(result.options);
  assert.deepEqual(await binding.rpc('prompt.lookup',{}),{found:false});assert.equal(calls,1);
  writeFileSync(f.file,f.bytes+' ');
  await assert.rejects(binding.rpc('session.create',{}),/not authorized/);assert.equal(calls,1);
  writeFileSync(f.file,f.bytes);unlinkSync(f.file);
  await assert.rejects(binding.rpc('session.create',{}),/not authorized/);assert.equal(calls,1);await binding.close();
});

test('revocation during a request rejects its late result while preserving the original transport',async()=>{
  const f=fixture();let settle,calls=0;
  const result=mainboardNativeConnection({...f,makeOptions:options=>({profile:options.profile,authorized:options.authorized,
    rpc:()=>{calls++;return new Promise(resolve=>{settle=resolve;});}})});
  const binding=createNativeWorkerBinding(result.options),pending=binding.rpc('prompt.lookup',{});
  f.env.MESH_NATIVE_WORKER_RECORD_SHA256='0'.repeat(64);settle({found:true});
  await assert.rejects(pending,/not authorized/);assert.equal(calls,1);await binding.close();
});

test('standalone and non-live Relay modes never construct a live native transport',()=>{
  for(const fields of [{MESH_STANDALONE:'1'},{MESH_RELAY:'0'},{MESH_RELAY_MODE:'fake'}]){
    const f=fixture();let factories=0;const result=mainboardNativeConnection({...f,env:{...f.env,...fields},makeOptions:()=>{factories++;}});
    assert.equal(result.state,'held');assert.equal(result.options,undefined);assert.equal(factories,0);
  }
});
