import nodeTest from 'node:test';
const test=process.platform==='win32'&&process.arch==='x64'?nodeTest:nodeTest.skip;
import assert from 'node:assert/strict';
import { mkdtempSync, writeFileSync, readFileSync, realpathSync, copyFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve, basename } from 'node:path';
import { createServer, createConnection } from 'node:net';
import { execFileSync, spawn } from 'node:child_process';
import { once } from 'node:events';
import { pathToFileURL } from 'node:url';
import { DatabaseSync } from 'node:sqlite';
import { holdWindowsNativeMaintenance, nativeResourceFingerprint, assertNativeMaintenanceHold, validateNativeHoldEvidence, holdWindowsFileReadBarrier, assertWindowsFileReadBarrier } from '../lib/windows-native-maintenance.mjs';

const root=resolve('.');
const protectedPorts=new Set([3081,4123,4320,8452,8453,8642]);
async function listener() {
  const server=createServer();server.on('error',()=>{});
  await new Promise((resolve,reject)=>{server.once('error',reject);server.listen(0,'127.0.0.1',resolve);});
  assert.ok(!protectedPorts.has(server.address().port));return server;
}
async function fixture() {
  const dir=realpathSync.native(mkdtempSync(join(tmpdir(),'mesh-native-inprocess-'))),lock=join(dir,'gateway.lock');
  writeFileSync(lock,'Synthetic profile record; preserve bytes.');
  const seed=await listener(),port=seed.address().port;await new Promise(resolve=>seed.close(resolve));
  const resources={profileLocks:[lock],endpoints:[['127.0.0.1',port],['::1',port]]};
  return {dir,lock,resources,plan:{planHash:'a'.repeat(64),sources:{nativeResourceScope:nativeResourceFingerprint(resources)}}};
}
function peer(f) {
  const code=`import json,socket,msvcrt,sys
path,port=sys.argv[1],int(sys.argv[2]);results=[]
with open(path,'r+b') as file:
 file.seek(1024*1024)
 try:msvcrt.locking(file.fileno(),msvcrt.LK_NBLCK,1);results.append(False);msvcrt.locking(file.fileno(),msvcrt.LK_UNLCK,1)
 except OSError:results.append(True)
for address,family in [('127.0.0.1',socket.AF_INET),('::1',socket.AF_INET6)]:
 with socket.socket(family,socket.SOCK_STREAM) as handle:
  handle.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
  try:handle.bind((address,port));results.append(False)
  except OSError as error:
   if error.winerror not in (10013,10048):raise
   results.append(True)
print(json.dumps(results))`;
  return JSON.parse(execFileSync('python',['-c',code,f.lock,String(f.resources.endpoints[0][1])],
    {encoding:'utf8',windowsHide:true,timeout:10000}));
}
async function ready(child) {
  let timer;
  try {return await Promise.race([once(child.stdout,'data').then(([data])=>data.toString().trim()),
    once(child,'exit').then(([code])=>{throw Error('Owned fixture exited before readiness: '+code);}),
    new Promise((_,reject)=>{timer=setTimeout(()=>reject(Error('Owned fixture readiness timed out')),10000);})]);}
  finally {clearTimeout(timer);}
}
async function clean(child) {
  if(child.exitCode===null&&child.signalCode===null){child.kill();await once(child,'exit');}
}

test('same-process native hold excludes real Python byte locks and socket reuse without changing the profile',async()=>{
  const f=await fixture(),before=readFileSync(f.lock),lease=await holdWindowsNativeMaintenance(f.resources);
  try {
    assert.deepEqual(peer(f),[true,true,true]);
    const proof=assertNativeMaintenanceHold(lease,f.plan);
    assert.equal(proof.ownerPid,process.pid);assert.equal(proof.processLifetimeBound,true);
    assert.equal(proof.workerRetirementEstablished,false);assert.deepEqual(readFileSync(f.lock),before);
  } finally {lease.release();}
  assert.deepEqual(peer(f),[false,false,false]);
});

test('an original Python profile owner is refused, never stopped or adopted',async()=>{
  const f=await fixture();
  const code=`import msvcrt,sys
with open(sys.argv[1],'r+b') as file:
 file.seek(1024*1024);msvcrt.locking(file.fileno(),msvcrt.LK_NBLCK,1)
 print('held',flush=True);sys.stdin.readline()
 file.seek(1024*1024);msvcrt.locking(file.fileno(),msvcrt.LK_UNLCK,1)`;
  const child=spawn('python',['-c',code,f.lock],{stdio:['pipe','pipe','pipe'],windowsHide:true});
  try {
    assert.equal(await ready(child),'held');
    await assert.rejects(holdWindowsNativeMaintenance(f.resources),/Profile lock refused/);
    assert.equal(child.exitCode,null);
    const exited=once(child,'exit');child.stdin.end('release\n');assert.equal((await exited)[0],0);
    const lease=await holdWindowsNativeMaintenance(f.resources);lease.release();
  } finally {await clean(child);}
});

test('a later endpoint conflict rolls back new locks and sockets while the original listener serves traffic',async()=>{
  const f=await fixture(),servers=await Promise.all([listener(),listener()]);
  servers.sort((a,b)=>a.address().port-b.address().port);
  const free=servers[0].address().port,busy=servers[1].address().port;
  await new Promise(resolve=>servers[0].close(resolve));
  try {
    await assert.rejects(holdWindowsNativeMaintenance({profileLocks:[f.lock],endpoints:[['127.0.0.1',free],['127.0.0.1',busy]]}),/Loopback reservation refused/);
    const accepted=once(servers[1],'connection'),client=createConnection({host:'127.0.0.1',port:busy});
    await once(client,'connect');const [connection]=await accepted;client.destroy();connection.destroy();
    const lease=await holdWindowsNativeMaintenance({profileLocks:[f.lock],endpoints:[['127.0.0.1',free]]});lease.release();
  } finally {await new Promise(resolve=>servers[1].close(resolve));}
});

test('copied, wrong-scope and released capabilities fail; historical evidence needs no live hold',async()=>{
  const f=await fixture(),lease=await holdWindowsNativeMaintenance(f.resources);
  const proof={...assertNativeMaintenanceHold(lease,f.plan),planHash:f.plan.planHash};
  try {
    for(const invalid of [{...lease},structuredClone(proof),{}])assert.throws(()=>assertNativeMaintenanceHold(invalid,f.plan),/authentic/);
    assert.throws(()=>assertNativeMaintenanceHold(lease,{sources:{nativeResourceScope:'b'.repeat(64)}}),/resource scope/);
  } finally {lease.release();}
  assert.throws(()=>assertNativeMaintenanceHold(lease,f.plan),/authentic/);
  validateNativeHoldEvidence(proof,f.plan);
  assert.throws(()=>validateNativeHoldEvidence({...proof,fingerprint:'b'.repeat(64)},f.plan),/invalid/);
});

test('public, wildcard, duplicate and network-file scopes are refused before acquisition',async()=>{
  const f=await fixture();
  for(const resources of [
    {...f.resources,profileLocks:[]},{...f.resources,profileLocks:['\\\\untrusted.invalid\\share\\gateway.lock']},
    {...f.resources,endpoints:[['0.0.0.0',55321]]},{...f.resources,endpoints:[['localhost',55321]]},
    {...f.resources,endpoints:[['127.0.0.1',0]]},{...f.resources,endpoints:[['127.0.0.1',55321],['127.0.0.1',55321]]},
  ])await assert.rejects(holdWindowsNativeMaintenance(resources));
  assert.deepEqual(peer(f),[false,false,false]);
});

test('abrupt owner exit rolls back SQLite and releases both kernel protections together',async()=>{
  const f=await fixture(),database=join(f.dir,'fixture.sqlite'),source=join(f.dir,'reviewed-source.mjs');writeFileSync(source,'Frozen');
  const initial=new DatabaseSync(database);initial.exec('CREATE TABLE proof(value TEXT);');initial.close();
  const moduleUrl=new URL('../lib/windows-native-maintenance.mjs',import.meta.url).href;
  const code=`import {DatabaseSync} from 'node:sqlite';import {holdWindowsNativeMaintenance,holdWindowsFileReadBarrier} from ${JSON.stringify(moduleUrl)};
    const lease=await holdWindowsNativeMaintenance(JSON.parse(process.argv[1]));
    const fileLease=await holdWindowsFileReadBarrier([process.argv[3]]);
    const db=new DatabaseSync(process.argv[2]);db.exec("BEGIN IMMEDIATE;INSERT INTO proof VALUES('uncommitted');");
    console.log('held');process.stdin.once('data',()=>process.exit(73));`;
  const child=spawn(process.execPath,['--input-type=module','-e',code,JSON.stringify(f.resources),database,source],
    {cwd:root,stdio:['pipe','pipe','pipe'],windowsHide:true});
  try {
    assert.equal(await ready(child),'held');assert.deepEqual(peer(f),[true,true,true]);assert.throws(()=>writeFileSync(source,'Premature write'));
    const exited=once(child,'exit');child.stdin.end('crash\n');assert.equal((await exited)[0],73);
    const restored=new DatabaseSync(database);try{assert.equal(restored.prepare('SELECT COUNT(*) AS n FROM proof').get().n,0);}finally{restored.close();}
    assert.deepEqual(peer(f),[false,false,false]);writeFileSync(source,'Released after owner exit');
  } finally {await clean(child);}
});


test('file barriers exclude real direct writes and replacement while preserving readable source bytes',async()=>{
  const f=await fixture(),source=join(f.dir,'reviewed-source.txt');writeFileSync(source,'Frozen source');
  const lease=await holdWindowsFileReadBarrier([source]);
  const peerCode=`import os,sys,json
p=sys.argv[1];results=[]
for operation in [lambda:open(p,'wb').close(),lambda:open(p,'ab').close(),lambda:os.unlink(p),lambda:os.replace(p,p+'.moved')]:
 try:operation();results.append(False)
 except PermissionError:results.append(True)
print(json.dumps(results))`;
  try{
    assert.deepEqual(JSON.parse(execFileSync('python',['-c',peerCode,source],{encoding:'utf8',windowsHide:true,timeout:10000})),[true,true,true,true]);
    assert.equal(readFileSync(source,'utf8'),'Frozen source');
    const proof=assertWindowsFileReadBarrier(lease,[source]);assert.equal(proof.fileCount,1);assert.equal(proof.workerRetirementEstablished,false);
    for(const fake of [{...lease},structuredClone(proof),{}])assert.throws(()=>assertWindowsFileReadBarrier(fake,[source]),/authentic/);
    assert.throws(()=>assertWindowsFileReadBarrier(lease,[f.lock]),/exact file scope/);
  }finally{lease.release();}
  assert.throws(()=>assertWindowsFileReadBarrier(lease,[source]),/authentic/);
  writeFileSync(source,'Allowed after release');assert.equal(readFileSync(source,'utf8'),'Allowed after release');
});

test('a non-listening original writer blocks file custody and partial file reservations roll back',async()=>{
  const f=await fixture(),first=join(f.dir,'a.txt'),last=join(f.dir,'z.txt');writeFileSync(first,'A');writeFileSync(last,'Z');
  const code=`import sys
with open(sys.argv[1],'r+b') as f:
 print('held',flush=True);sys.stdin.readline()`;
  const child=spawn('python',['-c',code,last],{stdio:['pipe','pipe','pipe'],windowsHide:true});
  try{
    assert.equal(await ready(child),'held');await assert.rejects(holdWindowsFileReadBarrier([first,last]),/File read barrier refused/);
    assert.equal(child.exitCode,null);writeFileSync(first,'Still writable after partial refusal');
    const exited=once(child,'exit');child.stdin.end('release\n');assert.equal((await exited)[0],0);
    const lease=await holdWindowsFileReadBarrier([first,last]);lease.release();
  }finally{await clean(child);}
});

test('file barriers keep a WAL database and reviewed source stable through another database commit',async()=>{
  const f=await fixture(),external=join(f.dir,'external.sqlite'),workroom=join(f.dir,'workroom.sqlite'),source=join(f.dir,'module.mjs');
  let db=new DatabaseSync(external);db.exec(`PRAGMA journal_mode=WAL;CREATE TABLE original(v TEXT);INSERT INTO original VALUES('preserve');`);db.close();
  writeFileSync(source,'Original module');const initial=readFileSync(source);
  const lease=await holdWindowsFileReadBarrier([external,source]);db=new DatabaseSync(workroom);
  try{
    db.exec('CREATE TABLE recovered(v TEXT);BEGIN IMMEDIATE;');
    const reader=new DatabaseSync(external,{readOnly:true});try{assert.equal(reader.prepare('SELECT v FROM original').get().v,'preserve');}finally{reader.close();}
    const contender=new DatabaseSync(external);try{assert.throws(()=>contender.exec("UPDATE original SET v='forbidden'"));}finally{contender.close();}assert.throws(()=>writeFileSync(source,'Changed'));
    assertWindowsFileReadBarrier(lease,[external,source]);db.exec("INSERT INTO recovered VALUES('unknown');COMMIT;");
    assert.equal(db.prepare('SELECT COUNT(*) AS n FROM recovered').get().n,1);assert.deepEqual(readFileSync(source),initial);
    assertWindowsFileReadBarrier(lease,[external,source]);
  }finally{db.close();lease.release();}
});

test('file barrier scope rejects missing, network, duplicate and empty paths without creating files',async()=>{
  const f=await fixture();
  for(const paths of [[],[f.lock,f.lock],[join(f.dir,'missing')],['\\\\untrusted.invalid\\file']])await assert.rejects(holdWindowsFileReadBarrier(paths));
  writeFileSync(f.lock,'Unchanged permissions, still writable');
});


async function runtimeFixture(){
  const f=await fixture(),name=basename(f.dir).toLowerCase()+'.exe',image=join(f.dir,name);
  copyFileSync('C:/Python314/python.exe',image);
  f.resources.workerRuntimeNames=[name];f.plan.sources.nativeResourceScope=nativeResourceFingerprint(f.resources);
  return {...f,image,name};
}
function runtimePeer(f){return spawn(f.image,['-B','-S','-c',"import sys;print('held',flush=True);sys.stdin.readline()"],{cwd:f.dir,env:{...process.env,PYTHONHOME:'C:/Python314',PATH:'C:/Python314;'+process.env.PATH},stdio:['pipe','pipe','pipe'],windowsHide:true});}

test('a non-listening runtime with no file handle blocks native maintenance without being stopped',async()=>{
  const f=await runtimeFixture(),child=runtimePeer(f);
  try{
    assert.equal(await ready(child),'held');
    await assert.rejects(holdWindowsNativeMaintenance(f.resources),/Covered worker runtimes remain active/);
    assert.equal(child.exitCode,null);assert.deepEqual(peer(f),[false,false,false]);
    const exited=once(child,'exit');child.stdin.end('done\r\n');assert.equal((await exited)[0],0);
    const lease=await holdWindowsNativeMaintenance(f.resources);try{
      const value=assertNativeMaintenanceHold(lease,f.plan);assert.equal(value.workerRuntimeObservation.outsideRuntimeCount,0);
      assert.equal(value.workerRuntimeObservation.continuousExecutionExcluded,false);
      assert.equal(value.workerRuntimeObservation.observerAncestry[0].pid,process.pid);
      assert.throws(()=>validateNativeHoldEvidence({...value,planHash:f.plan.planHash,ownerPid:process.pid+1},f.plan),/runtime observation/);
      validateNativeHoldEvidence({...value,planHash:f.plan.planHash},f.plan);
      assert.throws(()=>validateNativeHoldEvidence({...value,planHash:f.plan.planHash,workerRuntimeObservation:{...value.workerRuntimeObservation,continuousExecutionExcluded:true}},f.plan),/runtime observation/);
    }finally{lease.release();}
  }finally{await clean(child);}
});

test('a runtime started after acquisition invalidates every subsequent native hold assertion',async()=>{
  const f=await runtimeFixture(),lease=await holdWindowsNativeMaintenance(f.resources);let child;
  try{
    const before=assertNativeMaintenanceHold(lease,f.plan);child=runtimePeer(f);assert.equal(await ready(child),'held');
    assert.throws(()=>assertNativeMaintenanceHold(lease,f.plan),/Covered worker runtimes remain active/);
    assert.throws(()=>assertNativeMaintenanceHold(structuredClone(before),f.plan),/authentic/);
    const exited=once(child,'exit');child.stdin.end('done\r\n');assert.equal((await exited)[0],0);
    assert.equal(assertNativeMaintenanceHold(lease,f.plan).workerRuntimeObservation.outsideRuntimeCount,0);
  }finally{lease.release();if(child)await clean(child);}
});

test('malformed and duplicate runtime scopes are refused before profile or socket acquisition',async()=>{
  const f=await fixture();
  for(const names of [[],['python.exe','PYTHON.EXE'],['../python.exe'],['python'],['*'],null])await assert.rejects(holdWindowsNativeMaintenance({...f.resources,workerRuntimeNames:names}),/runtime image names|runtime image/);
  assert.deepEqual(peer(f),[false,false,false]);
});


test('a rejected newer ancestor stays tracked when CloseHandle fails instead of returning a successful observation',async()=>{
  const f=await fixture(),copy=join(f.dir,'native-cleanup-algorithm.mjs');
  // Fault injection exists only in this disposable module copy. Production never
  // accepts native bindings or an ignore flag from arguments, scope or environment.
  writeFileSync(copy,readFileSync(new URL('../lib/windows-native-maintenance.mjs',import.meta.url),'utf8')+'\nexport { acquireRuntimeObservation };\n');
  const {acquireRuntimeObservation}=await import(pathToFileURL(copy).href);
  const parentPid=process.pid+100000,rows=[{pid:process.pid,parentPid,name:'observer.exe'},{pid:parentPid,parentPid:0,name:'unverified-parent.exe'}];
  let next=0,lastError=18,parentCloseAttempts=0;const closed=[];
  const fill=(buffer,row)=>{buffer.fill(0);buffer.writeUInt32LE(568);buffer.writeUInt32LE(row.pid,8);buffer.writeUInt32LE(row.parentPid,32);Buffer.from(row.name+'\0','utf16le').copy(buffer,44);};
  const bindings={
    processSnapshot(){next=0;return 100;},
    processFirst(_handle,buffer){fill(buffer,rows[next++]);return 1;},
    processNext(_handle,buffer){if(next<rows.length){fill(buffer,rows[next++]);return 1;}lastError=18;return 0;},
    processOpen(_access,_inherit,pid){return pid===process.pid?11:12;},
    processWait(){return 258;},
    processTimes(handle,created){created.writeBigUInt64LE(handle===11?1000n:2000n);return 1;},
    flags(_handle,buffer){buffer.writeUInt32LE(0);return 1;},
    close(handle){if(handle===12&&++parentCloseAttempts===1){lastError=6;return 0;}closed.push(handle);return 1;},
    error(){return lastError;},
  };
  const state={api:bindings,resources:{workerRuntimeNames:['covered-fixture.exe']},runtimeProcesses:[]};
  assert.throws(()=>acquireRuntimeObservation(state),/Unverified ancestor close refused/);
  assert.deepEqual(state.runtimeProcesses.map(item=>item.handle),[11,12]);
  // The outer native lease can still see and clean both retained handles.
  for(const item of state.runtimeProcesses.reverse())assert.equal(bindings.close(item.handle),1);
  assert.equal(parentCloseAttempts,2);assert.ok(closed.includes(11));assert.ok(closed.includes(12));
});
