// Operator-only, same-process Windows resources. No handles are opened on import.
// https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-lockfileex
// https://learn.microsoft.com/en-us/windows/win32/winsock/so-exclusiveaddruse
import { realpathSync, statSync } from 'node:fs';
import { isAbsolute, basename, join, resolve } from 'node:path';
import { createHash } from 'node:crypto';
import { threadId } from 'node:worker_threads';

const holds = new WeakMap();
const canonical = value => Array.isArray(value) ? value.map(canonical) : value && typeof value === 'object'
  ? Object.fromEntries(Object.keys(value).sort().map(key => [key, canonical(value[key])])) : value;
const hash = value => createHash('sha256').update(JSON.stringify(canonical(value))).digest('hex');
const sha = value => typeof value === 'string' && /^[a-f0-9]{64}$/.test(value);
const invalid = value => BigInt(value) === 0xffffffffffffffffn;
const compare = (a,b) => a<b?-1:a>b?1:0;
let apiPromise;

function endpoints(values) {
  if (!Array.isArray(values) || !values.length || values.length > 16) throw Error('Exact loopback endpoints are required.');
  const result = values.map(item => {
    if (!Array.isArray(item) || item.length !== 2 || !['127.0.0.1','::1'].includes(item[0]) ||
        !Number.isInteger(item[1]) || item[1] < 1024 || item[1] > 65535) throw Error('Invalid loopback endpoint.');
    return [...item];
  }).sort((a,b) => compare(a[0],b[0]) || a[1]-b[1]);
  if (new Set(result.map(JSON.stringify)).size !== result.length) throw Error('Duplicate endpoints are not allowed.');
  return result;
}
function fileIdentity(file) {
  const value = statSync(file, { bigint: true });
  if (!value.isFile() || value.ino <= 0n || value.birthtimeNs <= 0n) throw Error('A persistent profile lock file is required.');
  return { dev: String(value.dev), ino: String(value.ino), born: String(value.birthtimeNs) };
}
function resources(value) {
  if (!value || !Array.isArray(value.profileLocks) || !value.profileLocks.length || value.profileLocks.length > 16)
    throw Error('Exact existing profile lock files are required.');
  const profileLocks = value.profileLocks.map(file => {
    if (typeof file !== 'string' || !isAbsolute(file) || !/^[a-z]:[\\/]/i.test(file) || basename(file).toLowerCase() !== 'gateway.lock') throw Error('Invalid local profile lock path.');
    const path = realpathSync.native(file).toLowerCase();
    if (!/^[a-z]:[\\/]/i.test(path)) throw Error('A local profile lock file is required.');
    return { path, identity: fileIdentity(path) };
  }).sort((a,b) => compare(a.path,b.path));
  if (new Set(profileLocks.map(item => item.path)).size !== profileLocks.length) throw Error('Duplicate profile locks are not allowed.');
  return { profileLocks, endpoints: endpoints(value.endpoints),
    ...(Object.hasOwn(value,'workerRuntimeNames')?{workerRuntimeNames:runtimeNames(value.workerRuntimeNames)}:{}) };
}
export const nativeResourceFingerprint = value => hash(resources(value));

async function api() {
  if (process.platform !== 'win32' || process.arch !== 'x64') throw Error('Qualified Windows x64 native bindings are required.');
  return apiPromise ??= (async () => {
    const { default: koffi } = await import('koffi');
    if (koffi.version !== '3.3.8') throw Error('The reviewed Koffi version is required.');
    const systemRoot=process.env.SystemRoot || process.env.SYSTEMROOT;
    if (!systemRoot || !isAbsolute(systemRoot)) throw Error('The Windows system directory is required.');
    const kernel = koffi.load(join(systemRoot,'System32','kernel32.dll'));
    const winsock = koffi.load(join(systemRoot,'System32','ws2_32.dll'));
    const k = (name, ret, args) => kernel.func('__stdcall', name, ret, args);
    const w = (name, ret, args) => winsock.func('__stdcall', name, ret, args);
    return {
      processSnapshot: k('CreateToolhelp32Snapshot','uintptr_t',['uint32_t','uint32_t']),
      processFirst: k('Process32FirstW','int',['uintptr_t','void *']),
      processNext: k('Process32NextW','int',['uintptr_t','void *']),
      processOpen: k('OpenProcess','uintptr_t',['uint32_t','int','uint32_t']),
      processTimes: k('GetProcessTimes','int',['uintptr_t','void *','void *','void *','void *']),
      processWait: k('WaitForSingleObject','uint32_t',['uintptr_t','uint32_t']),
      create: k('CreateFileW','uintptr_t',['str16','uint32_t','uint32_t','void *','uint32_t','uint32_t','uintptr_t']),
      info: k('GetFileInformationByHandle','int',['uintptr_t','void *']),
      flags: k('GetHandleInformation','int',['uintptr_t','void *']),
      lock: k('LockFileEx','int',['uintptr_t','uint32_t','uint32_t','uint32_t','uint32_t','void *']),
      unlock: k('UnlockFileEx','int',['uintptr_t','uint32_t','uint32_t','uint32_t','void *']),
      close: k('CloseHandle','int',['uintptr_t']), error: k('GetLastError','uint32_t',[]),
      startup: w('WSAStartup','int',['uint16_t','void *']), cleanup: w('WSACleanup','int',[]),
      socket: w('WSASocketW','uintptr_t',['int','int','int','void *','uint32_t','uint32_t']),
      set: w('setsockopt','int',['uintptr_t','int','int','void *','int']),
      get: w('getsockopt','int',['uintptr_t','int','int','void *','void *']),
      bind: w('bind','int',['uintptr_t','void *','int']),
      name: w('getsockname','int',['uintptr_t','void *','void *']),
      closeSocket: w('closesocket','int',['uintptr_t']), socketError: w('WSAGetLastError','int',[]),
    };
  })();
}
function fail(operation, code) { throw Error(`${operation} refused (${code}). Existing owners are unchanged.`); }
function checkFile(state, item) {
  const data = Buffer.alloc(52), flags = Buffer.alloc(4);
  if (!state.api.info(item.handle,data) || !state.api.flags(item.handle,flags)) fail('Profile handle check',state.api.error());
  const actual = { dev: String(data.readUInt32LE(28)),
    ino: String((BigInt(data.readUInt32LE(44))<<32n) | BigInt(data.readUInt32LE(48))),
    born: String((data.readBigUInt64LE(4)-116444736000000000n)*100n) };
  if ((flags.readUInt32LE(0)&1) || hash(actual)!==hash(item.identity) || hash(fileIdentity(item.path))!==hash(item.identity))
    throw Error('Profile lock file identity or inheritance changed.');
}
function option(state, handle, name) {
  const data=Buffer.alloc(4), size=Buffer.alloc(4);size.writeInt32LE(4);
  if (state.api.get(handle,65535,name,data,size)!==0 || size.readInt32LE(0)!==4) fail('Socket option check',state.api.socketError());
  return data.readInt32LE(0);
}
function checkSocket(state, item) {
  const data=Buffer.alloc(128),size=Buffer.alloc(4),flags=Buffer.alloc(4);size.writeInt32LE(data.length);
  if (state.api.name(item.handle,data,size)!==0 || !state.api.flags(item.handle,flags)) throw Error('Native transport handle was lost.');
  const family=item.endpoint[0]==='::1'?23:2;
  const address=family===2?Buffer.from([127,0,0,1]):Buffer.from([...Array(15).fill(0),1]);
  if (data.readUInt16LE(0)!==family || data.readUInt16BE(2)!==item.endpoint[1] ||
      !data.subarray(family===2?4:8,family===2?8:24).equals(address) || (flags.readUInt32LE(0)&1) ||
      option(state,item.handle,-5)!==1 || option(state,item.handle,2)!==0) throw Error('Exclusive non-listening endpoint changed.');
}
export function assertNativeMaintenanceHold(lease, plan) {
  const state=holds.get(lease);
  if (!state || state.closed || state.pid!==process.pid || state.thread!==threadId) throw Error('An authentic current native hold is required.');
  if (!sha(plan?.sources?.nativeResourceScope) || plan.sources.nativeResourceScope!==state.fingerprint)
    throw Error('Native hold does not match the exact reviewed resource scope.');
  for (const item of state.files) checkFile(state,item);
  for (const item of state.sockets) checkSocket(state,item);
  const workerRuntimeObservation=state.resources.workerRuntimeNames?assertRuntimeObservation(state):null;
  return { schema:'mesh-native-resource-hold/v1',scope:'declared_local_resources_only',
    resources:structuredClone(state.resources),fingerprint:state.fingerprint,ownerPid:state.pid,
    profilesReserved:true,tcpAdmissionsExcluded:true,processLifetimeBound:true,
    workerRetirementEstablished:false,coversDirectExecution:false,
    ...(workerRuntimeObservation?{workerRuntimeObservation}:{}) };
}
export function validateNativeHoldEvidence(value, plan) {
  const scope=value?.resources;
  if (!value || value.schema!=='mesh-native-resource-hold/v1' || value.scope!=='declared_local_resources_only' ||
      value.planHash!==plan.planHash || !sha(value.fingerprint) || value.fingerprint!==plan.sources?.nativeResourceScope ||
      !scope || !Array.isArray(scope.profileLocks) || !scope.profileLocks.length || scope.profileLocks.length>16 ||
      scope.profileLocks.some(item=>typeof item.path!=='string'||!isAbsolute(item.path)||basename(item.path).toLowerCase()!=='gateway.lock'||
        !item.identity||['dev','ino','born'].some(key=>typeof item.identity[key]!=='string'||!/^\d+$/.test(item.identity[key]))) ||
      hash(endpoints(scope.endpoints))!==hash(scope.endpoints) || hash(scope)!==value.fingerprint ||
      !Number.isSafeInteger(value.ownerPid)||value.ownerPid<=0 || value.profilesReserved!==true ||
      value.tcpAdmissionsExcluded!==true || value.processLifetimeBound!==true ||
      value.workerRetirementEstablished!==false || value.coversDirectExecution!==false) throw Error('Recorded native hold evidence is invalid.');
  if(scope.workerRuntimeNames)validateRuntimeWitness(value.workerRuntimeObservation,scope.workerRuntimeNames,value.ownerPid);
  else if(value.workerRuntimeObservation)throw Error('Unscoped worker runtime evidence is invalid.');
}
export async function holdWindowsNativeMaintenance(value) {
  const scope=resources(value), bindings=await api();
  const state={api:bindings,resources:scope,fingerprint:hash(scope),pid:process.pid,thread:threadId,files:[],sockets:[],runtimeProcesses:[],started:false,closed:false};
  const lease=Object.freeze({release() {
    if (state.closed) throw Error('Native hold was already released.');
    state.closed=true;holds.delete(lease);
    const errors=[];
    for(const item of state.runtimeProcesses.reverse())if(!bindings.close(item.handle))errors.push('process close');
    for (const item of state.sockets.reverse()) if (bindings.closeSocket(item.handle)!==0) errors.push('socket close');
    for (const item of state.files.reverse()) {
      if (item.locked && !bindings.unlock(item.handle,0,1,0,item.overlap)) errors.push('profile unlock');
      if (!bindings.close(item.handle)) errors.push('profile close');
    }
    if (state.started && bindings.cleanup()!==0) errors.push('Winsock cleanup');
    if (errors.length) throw Error('Native resource cleanup failed: '+errors.join(', '));
  }});
  try {
    for (const entry of scope.profileLocks) {
      const handle=bindings.create(entry.path,0xc0000000,3,null,3,128,0);
      if (invalid(handle)) fail('Profile open',bindings.error());
      const item={...entry,handle,overlap:Buffer.alloc(32),locked:false};state.files.push(item);
      item.overlap.writeUInt32LE(1024*1024,16);
      checkFile(state,item);
      if (!bindings.lock(handle,3,0,1,0,item.overlap)) fail('Profile lock',bindings.error());
      item.locked=true;
    }
    const startupData=Buffer.alloc(512), started=bindings.startup(0x202,startupData);
    if (started!==0) fail('Winsock initialization',started);
    state.started=true;
    if (startupData.readUInt16LE(0)!==0x202) throw Error('Winsock 2.2 is required.');
    for (const endpoint of scope.endpoints) {
      const family=endpoint[0]==='::1'?23:2, handle=bindings.socket(family,1,6,null,0,0x81);
      if (invalid(handle)) fail('Socket creation',bindings.socketError());
      state.sockets.push({handle,endpoint});
      const one=Buffer.alloc(4);one.writeInt32LE(1);
      if (bindings.set(handle,65535,-5,one,4)!==0) fail('Exclusive socket option',bindings.socketError());
      if (family===23 && bindings.set(handle,41,27,one,4)!==0) fail('IPv6-only option',bindings.socketError());
      const address=Buffer.alloc(family===2?16:28);address.writeUInt16LE(family,0);address.writeUInt16BE(endpoint[1],2);
      if (family===2) Buffer.from([127,0,0,1]).copy(address,4);else address[23]=1;
      if (bindings.bind(handle,address,address.length)!==0) fail('Loopback reservation',bindings.socketError());
    }
    if(scope.workerRuntimeNames)acquireRuntimeObservation(state);
    holds.set(lease,state);
    assertNativeMaintenanceHold(lease,{sources:{nativeResourceScope:state.fingerprint}});
    return lease;
  } catch(error) {
    try { lease.release(); } catch(cleanup) { throw new AggregateError([error,cleanup],'Native hold refused; cleanup reported an error.'); }
    throw error;
  }
}


// Kernel sharing restrictions protect these exact existing files against direct
// writes, truncation, replacement and deletion. They are not worker retirement
// evidence and do not exclude writes to unlisted files or newly created paths.
const fileReadHolds = new WeakMap();
function readBarrierResources(paths) {
  if (!Array.isArray(paths) || !paths.length || paths.length > 128) throw Error('Exact bounded local read-barrier paths are required.');
  const files = paths.map(path => {
    if (typeof path !== 'string' || !isAbsolute(path) || !/^[a-z]:[\\/]/i.test(path)) throw Error('A local existing read-barrier file is required.');
    const actual = realpathSync.native(path);
    if (actual.toLowerCase() !== resolve(path).toLowerCase()) throw Error('Read-barrier aliases are not allowed.');
    return {path:actual.toLowerCase(),identity:fileIdentity(actual)};
  }).sort((a,b)=>compare(a.path,b.path));
  if (new Set(files.map(f=>f.path)).size !== files.length) throw Error('Duplicate read-barrier paths are not allowed.');
  return files;
}
export function assertWindowsFileReadBarrier(lease, paths) {
  const state=fileReadHolds.get(lease);
  if (!state || state.closed || state.pid!==process.pid || state.thread!==threadId) throw Error('An authentic current file read barrier is required.');
  if (hash(readBarrierResources(paths))!==state.fingerprint) throw Error('Read barrier does not match the exact file scope.');
  for (const file of state.files) checkFile(state,file);
  return {schema:'mesh-windows-file-read-barrier/v1',ownerPid:state.pid,
    fileCount:state.files.length,fingerprint:state.fingerprint,
    writesAndReplacementExcluded:true,processLifetimeBound:true,
    scope:'listed_existing_files_only',workerRetirementEstablished:false};
}
export async function holdWindowsFileReadBarrier(paths) {
  const scope=readBarrierResources(paths),bindings=await api();
  const state={api:bindings,files:[],fingerprint:hash(scope),pid:process.pid,thread:threadId,closed:false};
  const lease=Object.freeze({release(){
    if(state.closed)throw Error('File read barrier was already released.');
    state.closed=true;fileReadHolds.delete(lease);const failures=[];
    for(const file of state.files.reverse())if(!bindings.close(file.handle))failures.push(bindings.error());
    if(failures.length)throw Error('Read-barrier cleanup failed: '+failures.join(', '));
  }});
  try {
    for(const file of scope){
      // GENERIC_READ, FILE_SHARE_READ only, OPEN_EXISTING. No permission changes,
      // no write access and no FILE_SHARE_WRITE/FILE_SHARE_DELETE.
      const handle=bindings.create(file.path,0x80000000,1,null,3,128,0);
      if(invalid(handle))fail('File read barrier',bindings.error());
      const item={...file,handle};state.files.push(item);checkFile(state,item);
    }
    fileReadHolds.set(lease,state);assertWindowsFileReadBarrier(lease,paths);return lease;
  } catch(error){
    try{lease.release();}catch(cleanup){throw new AggregateError([error,cleanup],'Read barrier refused; cleanup reported an error.');}
    throw error;
  }
}


// These are reviewed runtime entrypoints, NOT every program capable of writing.
// Snapshots observe absence at each check; they do not prevent future execution.
export const productionWorkerRuntimeNames=Object.freeze([
  'node.exe','python.exe','pythonw.exe','python3.exe','python3.14.exe',
  'codex.exe','codex-cli.exe','codex-worker.exe','claude.exe','kimi.exe',
  'bash.exe','sh.exe','pwsh.exe','powershell.exe','cmd.exe','wsl.exe',
  'ssh.exe','uv.exe','uvx.exe','bun.exe','deno.exe',
].sort());
function runtimeNames(names){
  if(!Array.isArray(names)||!names.length||names.length>64||names.some(n=>typeof n!=='string'||!/^[a-z0-9][a-z0-9._-]{0,100}\.exe$/i.test(n)))throw Error('Exact worker runtime image names are required.');
  const result=names.map(n=>n.toLowerCase()).sort();if(new Set(result).size!==result.length)throw Error('Duplicate worker runtime image names.');return result;
}
function processRows(bindings){
  const handle=bindings.processSnapshot(2,0);if(invalid(handle))fail('Process snapshot',bindings.error());
  try{
    // PROCESSENTRY32W: DWORD/ULONG_PTR alignment on the qualified Windows x64 ABI.
    const entry=Buffer.alloc(568);entry.writeUInt32LE(entry.length);const rows=new Map();
    if(!bindings.processFirst(handle,entry))fail('Process snapshot first entry',bindings.error());
    do{
      const pid=entry.readUInt32LE(8),parentPid=entry.readUInt32LE(32),name=entry.subarray(44,564).toString('utf16le').split('\0')[0].toLowerCase();
      if(rows.has(pid)||rows.size>=65536||!name)throw Error('Process snapshot is incomplete or malformed.');
      rows.set(pid,{pid,parentPid,name});
    }while(bindings.processNext(handle,entry));
    if(bindings.error()!==18)fail('Process snapshot enumeration',bindings.error());
    if(!rows.has(process.pid))throw Error('The observer is absent from its process snapshot.');return rows;
  }finally{if(!bindings.close(handle))fail('Process snapshot cleanup',bindings.error());}
}
function processBorn(state,item){
  const created=Buffer.alloc(8),exit=Buffer.alloc(8),kernel=Buffer.alloc(8),user=Buffer.alloc(8),flags=Buffer.alloc(4);
  if(state.api.processWait(item.handle,0)!==258||!state.api.processTimes(item.handle,created,exit,kernel,user)||
      !state.api.flags(item.handle,flags)||(flags.readUInt32LE(0)&1))throw Error('Worker-observer process custody was lost.');
  const born=created.readBigUInt64LE();if(born<=0n)throw Error('Worker-observer process identity is invalid.');return born.toString();
}
function acquireRuntimeObservation(state){
  const rows=processRows(state.api),seen=new Set();let pid=process.pid,childBorn=null;
  while(pid&&rows.has(pid)){
    if(seen.has(pid)||seen.size>=64)throw Error('Worker-observer ancestry is incomplete.');seen.add(pid);
    const row=rows.get(pid),handle=state.api.processOpen(0x101000,0,pid);
    if(!handle){
      // An inaccessible non-runtime ancestor is not an allowed worker identity.
      // Stop here; never allow any process above an unverified link.
      if(pid!==process.pid&&!state.resources.workerRuntimeNames.includes(row.name))break;
      fail('Observer process identity',state.api.error());
    }
    const item={...row,handle};state.runtimeProcesses.push(item);item.born=processBorn(state,item);
    // A reused parent PID cannot be treated as the creator or an allowed worker.
    if(childBorn!==null&&BigInt(item.born)>BigInt(childBorn)){
      if(!state.api.close(handle))fail('Unverified ancestor close',state.api.error());
      state.runtimeProcesses.pop();break;
    }
    childBorn=item.born;pid=row.parentPid;
  }
  assertRuntimeObservation(state);
}
function assertRuntimeObservation(state){
  const rows=processRows(state.api),allowed=new Set(state.runtimeProcesses.map(p=>p.pid));
  if(!allowed.has(process.pid))throw Error('The current observer has no retained process identity.');
  for(const item of state.runtimeProcesses){
    const row=rows.get(item.pid);
    if(!row||row.parentPid!==item.parentPid||row.name!==item.name||processBorn(state,item)!==item.born)throw Error('Worker-observer ancestry changed.');
  }
  const names=runtimeNames(state.resources.workerRuntimeNames);
  const outside=[...rows.values()].filter(row=>names.includes(row.name)&&!allowed.has(row.pid));
  if(outside.length)throw Error('Covered worker runtimes remain active: '+outside.map(p=>p.name+'#'+p.pid).join(', '));
  return {schema:'mesh-worker-runtime-observation/v1',scope:'reviewed_runtime_names_only',
    runtimeNames:names,outsideRuntimeCount:0,observerAncestry:state.runtimeProcesses.map(({pid,parentPid,name,born})=>({pid,parentPid,name,born})),
    continuousExecutionExcluded:false,workerRetirementEstablished:false};
}
function validateRuntimeWitness(value,names,ownerPid){
  if(!value||value.schema!=='mesh-worker-runtime-observation/v1'||value.scope!=='reviewed_runtime_names_only'||
      hash(value.runtimeNames)!==hash(runtimeNames(names))||value.outsideRuntimeCount!==0||
      value.continuousExecutionExcluded!==false||value.workerRetirementEstablished!==false||
      !Array.isArray(value.observerAncestry)||!value.observerAncestry.length||value.observerAncestry.length>64||
      value.observerAncestry[0]?.pid!==ownerPid||
      new Set(value.observerAncestry.map(p=>p.pid)).size!==value.observerAncestry.length||
      value.observerAncestry.some(p=>!Number.isSafeInteger(p.pid)||p.pid<=0||!Number.isSafeInteger(p.parentPid)||p.parentPid<0||
        typeof p.name!=='string'||!p.name||typeof p.born!=='string'||!/^\d+$/.test(p.born)||BigInt(p.born)<=0n))throw Error('Recorded worker runtime observation is invalid.');
  if(value.observerAncestry.some((p,i,rows)=>i>0&&(rows[i-1].parentPid!==p.pid||BigInt(rows[i-1].born)<BigInt(p.born))))throw Error('Recorded worker-observer ancestry is inconsistent.');
}
