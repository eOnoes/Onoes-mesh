// Operator-only, same-process Windows resources. No handles are opened on import.
// https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-lockfileex
// https://learn.microsoft.com/en-us/windows/win32/winsock/so-exclusiveaddruse
import { realpathSync, statSync } from 'node:fs';
import { isAbsolute, basename, join } from 'node:path';
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
  return { profileLocks, endpoints: endpoints(value.endpoints) };
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
  return { schema:'mesh-native-resource-hold/v1',scope:'declared_local_resources_only',
    resources:structuredClone(state.resources),fingerprint:state.fingerprint,ownerPid:state.pid,
    profilesReserved:true,tcpAdmissionsExcluded:true,processLifetimeBound:true,
    workerRetirementEstablished:false,coversDirectExecution:false };
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
}
export async function holdWindowsNativeMaintenance(value) {
  const scope=resources(value), bindings=await api();
  const state={api:bindings,resources:scope,fingerprint:hash(scope),pid:process.pid,thread:threadId,files:[],sockets:[],started:false,closed:false};
  const lease=Object.freeze({release() {
    if (state.closed) throw Error('Native hold was already released.');
    state.closed=true;holds.delete(lease);
    const errors=[];
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
    holds.set(lease,state);
    assertNativeMaintenanceHold(lease,{sources:{nativeResourceScope:state.fingerprint}});
    return lease;
  } catch(error) {
    try { lease.release(); } catch(cleanup) { throw new AggregateError([error,cleanup],'Native hold refused; cleanup reported an error.'); }
    throw error;
  }
}
