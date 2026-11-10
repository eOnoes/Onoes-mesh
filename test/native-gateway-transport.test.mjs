import test from 'node:test';
import assert from 'node:assert/strict';
import {EventEmitter} from 'node:events';
import {PassThrough,Writable} from 'node:stream';
import {resolve} from 'node:path';
import {createNativeGatewayTransport,nativeGatewayWorkerOptions} from '../lib/native-gateway-transport.mjs';
import {createNativeWorkerBinding} from '../lib/workroom-native-binding.mjs';

const paths={nativeRoot:resolve('data/native-fixture'),home:resolve('data/native-home'),pythonExecutable:resolve('data/fixture-python')};
function fixture(onWrite) {
  const child=new EventEmitter();child.stdout=new PassThrough();child.stderr=new PassThrough();
  child.stdin=new Writable({write(chunk,_encoding,callback){onWrite?.(JSON.parse(chunk),child);callback();}});
  let ended=false;
  const end=()=>{if(!ended){ended=true;child.emit('close',0);}};
  child.stdin.on('finish',()=>queueMicrotask(end));child.kill=()=>{end();return true;};
  return child;
}

test('transport/bootstrap is lazy, hidden and strips ambient provider secrets',async()=>{
  let starts=0,options,args;
  const transport=createNativeGatewayTransport({...paths,spawnImpl:(exe,argv,opts)=>{
    starts++;assert.equal(exe,paths.pythonExecutable);options=opts;args=argv;
    return fixture((frame,child)=>queueMicrotask(()=>child.stdout.write(JSON.stringify({id:frame.id,result:{found:false}})+'\n')));
  }});
  assert.equal(starts,0);assert.deepEqual(await transport.rpc('prompt.lookup',{session_id:'original'}),{found:false});
  assert.equal(starts,1);assert.equal(options.windowsHide,true);assert.equal(options.shell,false);
  assert.deepEqual(options.stdio,['pipe','pipe','pipe']);assert.equal(options.env.HERMES_HOME,paths.home);
  assert.ok(Object.keys(options.env).every(key=>['PATH','SYSTEMROOT','WINDIR','TEMP','TMP','USERPROFILE','LOCALAPPDATA','APPDATA',
    'HERMES_HOME','PYTHONUTF8','PYTHONNOUSERSITE'].includes(key.toUpperCase())));
  assert.ok(args.includes('--native-root'));await transport.close();
  let deniedStarts=0;
  const binding=createNativeWorkerBinding(nativeGatewayWorkerOptions({...paths,
    profile:{profileRef:'fixture',identityRef:'fixture',provider:'openai-codex',model:'synthetic',workspace:resolve('.')},
    authorized:()=>false,spawnImpl:()=>{deniedStarts++;throw Error('Must not start');}}));
  await assert.rejects(binding.rpc('session.create',{}),/not authorized/);await binding.close();assert.equal(deniedStarts,0);
});

test('one connection correlates out-of-order fragmented replies without changing request IDs',async()=>{
  const frames=[];let child;
  const transport=createNativeGatewayTransport({...paths,spawnImpl:()=>child=fixture(frame=>frames.push(frame))});
  const a=transport.rpc('session.create',{request_id:'fixed'}),b=transport.rpc('prompt.lookup',{submission_id:'saved'});
  assert.deepEqual(frames.map(f=>f.id),[1,2]);
  const bytes=Buffer.from(JSON.stringify({id:2,result:'original lookup'})+'\n'+JSON.stringify({id:1,result:'created'})+'\n');
  child.stdout.write(bytes.subarray(0,13));child.stdout.write(bytes.subarray(13));
  assert.deepEqual(await Promise.all([a,b]),['created','original lookup']);await transport.close();
});

test('connection loss rejects uncertain work and never reconnects or resends',async()=>{
  let starts=0,writes=0,child;
  const transport=createNativeGatewayTransport({...paths,spawnImpl:()=>{starts++;return child=fixture(()=>writes++);}});
  const pending=assert.rejects(transport.rpc('prompt.submit',{submission_id:'original'}),/nothing was replayed/);
  child.emit('close',1);await pending;
  await assert.rejects(transport.rpc('prompt.submit',{submission_id:'original'}),/nothing was replayed/);
  await transport.close();assert.equal(starts,1);assert.equal(writes,1);
});

test('timeout closes the connection and preserves the no-replay boundary',async()=>{
  let starts=0;
  const transport=createNativeGatewayTransport({...paths,timeoutMs:20,spawnImpl:()=>{starts++;return fixture();}});
  await assert.rejects(transport.rpc('session.create',{request_id:'original'}),/nothing was replayed/);
  await assert.rejects(transport.rpc('prompt.lookup',{}));await transport.close();assert.equal(starts,1);
});

test('shutdown waits for and if needed terminates only its owned helper',async()=>{
  let kills=0,child;
  const transport=createNativeGatewayTransport({...paths,spawnImpl:()=>{
    child=fixture();child.stdin.removeAllListeners('finish');
    const kill=child.kill;child.kill=()=>{kills++;return kill();};return child;
  }});
  const held=assert.rejects(transport.rpc('prompt.lookup',{}),/nothing was replayed/);
  const closing=transport.close();assert.equal(transport.close(),closing);await held;await closing;
  assert.equal(kills,1);
});

test('invalid methods and oversized requests never launch; malformed replies and native errors are sanitized',async()=>{
  let starts=0,child;
  const transport=createNativeGatewayTransport({...paths,spawnImpl:()=>{starts++;return child=fixture();}});
  await assert.rejects(transport.rpc('permissions.grant',{}),/Unsupported/);
  await assert.rejects(transport.rpc('prompt.submit',{text:'x'.repeat(1024*1024)}),/too large/);assert.equal(starts,0);
  const failed=assert.rejects(transport.rpc('prompt.lookup',{}),error=>!error.message.includes('private-ticket'));
  child.stdout.write('{"type":"fatal","error":"private-ticket"}\n');await failed;await transport.close();
  for(const response of ['not-json\n','{"id":99,"result":{}}\n','{"id":1,"result":{},"error":"private-ticket"}\n']){
    let peer;const t=createNativeGatewayTransport({...paths,spawnImpl:()=>peer=fixture()});
    const held=assert.rejects(t.rpc('prompt.lookup',{}),/nothing was replayed/);peer.stdout.write(response);await held;await t.close();
  }
});
