import nodeTest from 'node:test';
const test=process.platform==='win32'&&process.arch==='x64'?nodeTest:nodeTest.skip;
import assert from 'node:assert/strict';
import { mkdtempSync, writeFileSync, readFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { createServer, createConnection } from 'node:net';
import { execFileSync, spawn } from 'node:child_process';
import { once } from 'node:events';
import { DatabaseSync } from 'node:sqlite';
import { holdWindowsNativeMaintenance, nativeResourceFingerprint, assertNativeMaintenanceHold, validateNativeHoldEvidence } from '../lib/windows-native-maintenance.mjs';

const root=resolve('.');
const protectedPorts=new Set([3081,4123,4320,8452,8453,8642]);
async function listener() {
  const server=createServer();server.on('error',()=>{});
  await new Promise((resolve,reject)=>{server.once('error',reject);server.listen(0,'127.0.0.1',resolve);});
  assert.ok(!protectedPorts.has(server.address().port));return server;
}
async function fixture() {
  const dir=mkdtempSync(join(tmpdir(),'mesh-native-inprocess-')),lock=join(dir,'gateway.lock');
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
  const f=await fixture(),database=join(f.dir,'fixture.sqlite');
  const initial=new DatabaseSync(database);initial.exec('CREATE TABLE proof(value TEXT);');initial.close();
  const moduleUrl=new URL('../lib/windows-native-maintenance.mjs',import.meta.url).href;
  const code=`import {DatabaseSync} from 'node:sqlite';import {holdWindowsNativeMaintenance} from ${JSON.stringify(moduleUrl)};
    const lease=await holdWindowsNativeMaintenance(JSON.parse(process.argv[1]));
    const db=new DatabaseSync(process.argv[2]);db.exec("BEGIN IMMEDIATE;INSERT INTO proof VALUES('uncommitted');");
    console.log('held');process.stdin.once('data',()=>process.exit(73));`;
  const child=spawn(process.execPath,['--input-type=module','-e',code,JSON.stringify(f.resources),database],
    {cwd:root,stdio:['pipe','pipe','pipe'],windowsHide:true});
  try {
    assert.equal(await ready(child),'held');assert.deepEqual(peer(f),[true,true,true]);
    const exited=once(child,'exit');child.stdin.end('crash\n');assert.equal((await exited)[0],73);
    const restored=new DatabaseSync(database);try{assert.equal(restored.prepare('SELECT COUNT(*) AS n FROM proof').get().n,0);}finally{restored.close();}
    assert.deepEqual(peer(f),[false,false,false]);
  } finally {await clean(child);}
});
