// Native custody and actual npm start; generated files stay in disposable evidence.
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { once } from 'node:events';
import { createInterface } from 'node:readline';
import { mkdir, writeFile, readFile } from 'node:fs/promises';
import { createHash, randomUUID } from 'node:crypto';
import path from 'node:path';
import { pathToFileURL, fileURLToPath } from 'node:url';
const ROOT = path.dirname(path.dirname(fileURLToPath(import.meta.url)));

const observerSource = String.raw`import sys,json,time,threading,queue,ctypes as C
from ctypes import wintypes as W
from test.test_owned_cancel import Observer
o=Observer(); records=[]; live={}; races=[]; rejected=[]; commands=queue.Queue()
class UnicodeString(C.Structure):
 _fields_=[('Length',W.USHORT),('MaximumLength',W.USHORT),('Buffer',C.c_void_p)]
nt=C.WinDLL('ntdll'); nt.NtQueryInformationProcess.argtypes=[W.HANDLE,W.ULONG,C.c_void_p,W.ULONG,C.POINTER(W.ULONG)]; nt.NtQueryInformationProcess.restype=C.c_long
def cmdline(h):
 size=W.ULONG(); nt.NtQueryInformationProcess(h,60,None,0,C.byref(size))
 buf=C.create_string_buffer(max(size.value,65536)); status=nt.NtQueryInformationProcess(h,60,buf,len(buf),C.byref(size))
 if status<0: raise OSError('NtQueryInformationProcess status '+str(status))
 u=UnicodeString.from_buffer(buf); return C.wstring_at(u.Buffer,u.Length//2)
def argv(text):
 shell=C.WinDLL('shell32'); shell.CommandLineToArgvW.argtypes=[W.LPCWSTR,C.POINTER(C.c_int)]; shell.CommandLineToArgvW.restype=C.POINTER(W.LPWSTR)
 kernel=C.WinDLL('kernel32'); kernel.LocalFree.argtypes=[C.c_void_p]; kernel.LocalFree.restype=C.c_void_p
 count=C.c_int(); values=shell.CommandLineToArgvW(text,C.byref(count)); assert values
 try: return [values[n] for n in range(count.value)]
 finally: assert not kernel.LocalFree(values)
def cwd(pid,identity):
 # Read the native x64 process parameters through a separate read-only handle.
 # The retained original identity remains the sole stop authority.
 kernel=C.WinDLL('kernel32'); kernel.ReadProcessMemory.argtypes=[W.HANDLE,C.c_void_p,C.c_void_p,C.c_size_t,C.POINTER(C.c_size_t)]; kernel.ReadProcessMemory.restype=W.BOOL
 h=o.api.OpenProcess(0x1000|0x10,False,pid); assert h
 try:
  times=[W.FILETIME() for _ in range(4)]; assert o.GetProcessTimes(h,*[C.byref(t) for t in times])
  assert str((times[0].dwHighDateTime<<32)|times[0].dwLowDateTime)==identity['creationTime100ns']
  basic=(C.c_void_p*6)(); size=W.ULONG(); assert nt.NtQueryInformationProcess(h,0,basic,C.sizeof(basic),C.byref(size))>=0
  def memory(address,size):
   buf=C.create_string_buffer(size); read=C.c_size_t(); assert kernel.ReadProcessMemory(h,address,buf,size,C.byref(read)) and read.value==size; return buf.raw
  params=int.from_bytes(memory(basic[1]+0x20,8),'little'); value=memory(params+0x38,16)
  length=int.from_bytes(value[:2],'little'); pointer=int.from_bytes(value[8:16],'little'); return memory(pointer,length).decode('utf-16-le')
 finally: assert o.api.CloseHandle(h)
def listeners():
 ip=C.WinDLL('iphlpapi'); ip.GetExtendedTcpTable.argtypes=[C.c_void_p,C.POINTER(W.ULONG),W.BOOL,W.ULONG,W.ULONG,W.ULONG]; ip.GetExtendedTcpTable.restype=W.DWORD
 result=[]
 for family,row_size,pid_offset,port_offset in [(2,24,20,8),(23,56,52,20)]:
  size=W.ULONG(); status=ip.GetExtendedTcpTable(None,C.byref(size),False,family,5,0); assert status in (0,122)
  buf=C.create_string_buffer(size.value); assert ip.GetExtendedTcpTable(buf,C.byref(size),False,family,5,0)==0
  count=int.from_bytes(buf.raw[:4],'little')
  for index in range(count):
   row=buf.raw[4+index*row_size:4+(index+1)*row_size]
   state=int.from_bytes(row[0:4] if family==2 else row[48:52],'little')
   if state!=2: continue
   address=row[4:8] if family==2 else row[:16]
   host='.'.join(str(n) for n in address) if family==2 else ('::1' if address==bytes(15)+b'\x01' else 'non-loopback-ipv6')
   pid=int.from_bytes(row[pid_offset:pid_offset+4],'little'); held=live.get(pid)
   creation=held[1]['creationTime100ns'] if held and o.api.WaitForSingleObject(held[0],0)==258 else None
   result.append(dict(pid=pid,creationTime100ns=creation,host=host,port=int.from_bytes(row[port_offset:port_offset+2],'big')))
 return result
def retain(pid,parent,purpose):
 h,i=o.retain(pid,purpose,True); i['parentPid']=parent
 if parent is not None:
  # Toolhelp PPIDs can name an exited/reused generation. Only an original
  # retained live parent, older than this native child, can confer ownership.
  ph,pi=live[parent]; times=[W.FILETIME() for _ in range(4)]
  assert o.GetProcessTimes(ph,*[C.byref(t) for t in times])
  parent_creation=str((times[0].dwHighDateTime<<32)|times[0].dwLowDateTime)
  assert parent_creation==pi['creationTime100ns'], 'Retained parent creation changed'
  reason=None
  parent_state=o.api.WaitForSingleObject(ph,0)
  assert parent_state in (0,258), 'Retained parent liveness unavailable'
  if int(i['creationTime100ns'])<int(parent_creation): reason='native child predates retained parent generation'
  elif parent_state==0: reason='retained parent generation no longer live'
  if reason:
   rejection=dict(i,parentCreationTime100ns=parent_creation,reason=reason)
   if rejection not in rejected: rejected.append(rejection)
   assert o.api.CloseHandle(h); o.handles.remove(h)
   return None
  i['parentCreationTime100ns']=parent_creation
 try: i['commandLine']=cmdline(h); i['argv']=argv(i['commandLine'])
 except Exception as e: i['commandLineError']=str(e)
 try: i['currentDirectory']=cwd(pid,i)
 except Exception as e: i['currentDirectoryError']=str(e)
 text=i.get('commandLine','').lower()
 i['purpose']=next((label for token,label in [
  ('owned-command.py','Original native command ownership bridge'),('--owned-child','Fixed slow-command descendant'),
  ('slow-command.mjs','Fixed slow-command root'),('--version','Actual node version root'),
  ('chrome','Owned headless verification browser'),('conhost','Console host of an owned temporary child'),
  ('npm-cli','Actual npm entry point / local qualification'),('m1-serve.mjs','Disposable actual Agent / Workroom server'),
  ('powershell','Owned legacy test identity helper'),('observer','Read-only native process observer'),
  ('unittest','Existing native ownership qualification'),('--test','Named Node contract qualification')
 ] if token in text),purpose)
 if parent is not None:
  parent_state=o.api.WaitForSingleObject(ph,0)
  assert parent_state in (0,258), 'Retained parent liveness unavailable'
  if parent_state==0:
   rejection=dict(i,reason='retained parent exited during child identity acquisition')
   if rejection not in rejected: rejected.append(rejection)
   assert o.api.CloseHandle(h); o.handles.remove(h)
   return None
 i['worktree']=__import__('os').getcwd()
 i['custodyClass']='infrastructure' if purpose in ('M6 verification harness','M6 native custody observer') or i['executable'].lower().endswith('\\conhost.exe') else 'workload'
 i['exitSignaled']=False; records.append(i); live[pid]=(h,i); return i
root=int(sys.argv[1]); retain(root,None,'M6 verification harness'); retain(__import__('os').getpid(),root,'M6 native custody observer')
def input_loop():
 for line in sys.stdin: commands.put(json.loads(line))
 commands.put({'action':'eof'})
threading.Thread(target=input_loop,daemon=True).start()
print(json.dumps({'event':'ready','identities':records}),flush=True)
def scan(entries=None):
 for pid,(h,i) in list(live.items()):
  if o.api.WaitForSingleObject(h,0)==0:
   code=W.DWORD(); assert o.api.GetExitCodeProcess(h,C.byref(code)); i.update(exitSignaled=True,exitCode=code.value); del live[pid]
 entries=o.processes() if entries is None else entries; changed=True
 while changed:
  changed=False
  for e in entries:
   if e['pid'] not in live and e['parentPid'] in live:
    try: changed=retain(e['pid'],e['parentPid'],'Owned M6 descendant') is not None or changed
    except (OSError,AssertionError) as error:
     races.append({'pid':e['pid'],'parentPid':e['parentPid'],'exe':e['exe'],'error':str(error),'reason':'identity acquisition raced child exit or was unavailable'})
try:
 while True:
  scan()
  try: command=commands.get_nowait()
  except queue.Empty: time.sleep(.002); continue
  action=command['action']
  if action=='kill':
   h,i=live[command['pid']]; assert i['creationTime100ns']==command['creationTime100ns']; assert o.api.WaitForSingleObject(h,0)==258
   check_h,check=o.retain(command['pid'],'Immediate exact-identity recheck',True)
   assert check['creationTime100ns']==i['creationTime100ns'] and check['executable']==i['executable'] and cmdline(check_h)==i['commandLine']
   if 'executable' in command:
    assert command['executable']==i['executable'] and command['commandLine']==i['commandLine'] and command['argv']==i['argv']
   assert o.api.TerminateProcess(h,1)
  if action in ('snapshot','kill','listeners','finish'):
   scan(); print(json.dumps({'event':action,'target':command.get('pid'),'identities':records,'listeners':listeners() if action=='listeners' else [],'acquisitionRaces':races,'rejectedParentage':rejected}),flush=True)
  if action in ('finish','eof'): break
finally:
 o.close()
`;

// Stream-only seam: no process creation or native custody policy lives here.
export function createCustodyPipe(child, { timeoutMs = 15000 } = {}) {
  const diagnostics = [], lifecycle = {}; let failure, rejectFailure, serial = Promise.resolve(), finishing = false;
  const failed = new Promise((_, reject) => { rejectFailure = reject; });
  failed.catch(() => {}); // Errors may arrive while no request is pending.
  const record = (source, error) => {
    if (diagnostics.length < 32) diagnostics.push({ source, code: error.code,
      message: String(error.message).slice(0, 4096) });
    if (!failure) { failure = Error(`CUSTODY_PIPE_UNVERIFIED:${source}:${error.code ?? error.message}`, { cause: error }); rejectFailure(failure); }
  };
  child.stdin.on('error', error => record('stdin', error));
  child.stdin.on('close', () => { if (!finishing) record('stdin-close', Error('premature close')); });
  child.stdout.on('error', error => record('stdout', error));
  child.stderr?.on('error', error => record('stderr', error));
  child.on('error', error => record('helper', error));
  const closed = new Promise(resolve => child.once('close', (code, signal) => {
    lifecycle.exitCode = code; lifecycle.signal = signal;
    resolve([code, signal]);
    if (!finishing) record('helper-close', Error(`premature exit ${code}/${signal}`));
  }));
  const lines = createInterface({ input: child.stdout })[Symbol.asyncIterator]();
  async function bounded(promise) {
    let timer;
    try { return await Promise.race([promise, failed, new Promise((_, reject) => {
      timer = setTimeout(() => {
        record('deadline', Error('Native custody deadline; partial receipt retained')); reject(failure);
      }, timeoutMs);
    })]); } finally { clearTimeout(timer); }
  }
  async function next() {
    if (failure) throw failure;
    const line = await bounded(lines.next());
    if (line.done) { record('stdout-eof', Error('missing native receipt')); throw failure; }
    try { return JSON.parse(line.value); }
    catch (error) { record('receipt-json', error); throw failure; }
  }
  function call(action, extra = {}) {
    const request = serial.then(async () => {
      if (failure) throw failure;
      if (child.stdin.destroyed || child.stdin.writableEnded) {
        record('stdin-state', Error('pipe unavailable')); throw failure;
      }
      if (action === 'finish') finishing = true;
      await bounded(new Promise((resolve, reject) => {
        child.stdin.write(JSON.stringify({ action, ...extra }) + '\n', error => {
          if (error) { record('stdin-write', error); reject(failure); } else resolve();
        });
      }));
      const value = await next();
      try { assert.equal(value.event, action); }
      catch (error) { record('receipt-action', error); throw failure; }
      return value;
    });
    serial = request.catch(() => {});
    return request;
  }
  return { diagnostics, lifecycle, next, call, closed, bounded, end() { finishing = true; child.stdin.end(); } };
}

export async function custody(directory, options = {}) {
  await mkdir(directory, { recursive: true });
  const script = path.join(directory, 'native-observer.py'); await writeFile(script, observerSource);
  const child = spawn('C:\\Python314\\pythonw.exe', ['-B', script, String(process.pid)], {
    cwd: ROOT, windowsHide: true, stdio: ['pipe','pipe','pipe'],
    env: options.env === undefined ? { ...process.env, PYTHONPATH: ROOT } : { ...options.env }
  });
  const pipe = createCustodyPipe(child, options);
  let errors = ''; child.stderr.on('data', b => { errors = (errors + b).slice(-65536); });
  const { closed, bounded, next } = pipe;
  let ready;
  try { ready = await next(); assert.equal(ready.event, 'ready'); }
  catch (error) {
    pipe.end(); // EOF asks the owned helper to close its original handles.
    const partial = { observer: { pid: child.pid, executable: child.spawnfile, argv: child.spawnargs },
      error: error.message, pipeErrors: pipe.diagnostics, pipeLifecycle: pipe.lifecycle, stderr: errors };
    try { const [code] = await bounded(closed); partial.observer.exitCode = code; }
    catch (closeError) { partial.closeError = closeError.message; }
    await writeFile(path.join(directory, 'native-processes.json'), JSON.stringify(partial, null, 2));
    throw error;
  }
  const receipt = { observer: { pid: child.pid, executable: child.spawnfile, argv: child.spawnargs },
    ready, stages: [], pipeErrors: pipe.diagnostics, pipeLifecycle: pipe.lifecycle };
  const saveReceipt = async () => { receipt.stderr = errors;
    await writeFile(path.join(directory, 'native-processes.json'), JSON.stringify(receipt, null, 2)); };
  async function call(action, extra = {}) {
    try { const value = await pipe.call(action, extra); receipt.stages.push(value);
      await saveReceipt(); return value.identities;
    } catch (error) { receipt.error = error.message; await saveReceipt(); throw error; }
  }
  return { child, call, receipt, async finish() { await call('finish'); pipe.end(); const [code] = await bounded(closed);
    receipt.observer.exitCode = code; await saveReceipt(); assert.equal(code, 0, errors);
    const final = receipt.stages.at(-1);
    assert.deepEqual(final.acquisitionRaces, [], 'Native custody acquisition unavailable; inspect retained evidence');
    assert.ok(final.rejectedParentage.every(i => i.reason === 'native child predates retained parent generation'),
      'Parent liveness changed during acquisition; genuine descendant custody unresolved');
    assert.ok(final.identities.every(i => !i.commandLineError), 'Native command line unavailable; inspect retained evidence'); } };
}

export async function fixture(label) {
  const dataDir = `test/app03-m6-standalone-${label}-${randomUUID()}`;
  const directory = path.join(ROOT, dataDir); await mkdir(directory, { recursive: true });
  const monitor = await custody(directory); const apps = [];
  const launches = path.join(directory, 'js-launches.jsonl'); const preload = path.join(directory, 'launch-observer.mjs');
  await writeFile(preload, `import cp from 'node:child_process'; import {appendFileSync} from 'node:fs';
    const original = cp.ChildProcess.prototype.spawn;
    cp.ChildProcess.prototype.spawn = function(options) { const result = original.call(this, options);
      appendFileSync(${JSON.stringify(launches)}, JSON.stringify({event:'spawn',parentPid:process.pid,pid:this.pid,executable:this.spawnfile,argv:this.spawnargs,at:new Date().toISOString()})+'\\n');
      this.once('close',(exitCode,signal)=>appendFileSync(${JSON.stringify(launches)},JSON.stringify({event:'close',parentPid:process.pid,pid:this.pid,exitCode,signal,at:new Date().toISOString()})+'\\n')); return result; };`);
  const save = (name, value) => writeFile(path.join(directory, name), JSON.stringify(value, null, 2));
  async function boot(port = 0) {
    const npmCli = process.env.npm_execpath ?? path.join(path.dirname(process.execPath), 'node_modules/npm/bin/npm-cli.js');
    const child = spawn(process.execPath, [npmCli, 'start'], { cwd: ROOT, windowsHide: true, stdio: ['ignore','pipe','pipe'],
      env: { ...process.env, MESH_STANDALONE: '1', MESH_RELAY: '1', MESH_DATA_DIR: dataDir, MESH_PREVIEW_PORT: String(port),
        NODE_OPTIONS: `--import=${pathToFileURL(preload).href}` } });
    const app = { child, closed: once(child, 'close'), stdout: '', stderr: '' }; apps.push(app);
    child.stderr.on('data', b => { app.stderr += b; });
    const info = await new Promise((resolve, reject) => {
      const timer = setTimeout(() => reject(Error('Actual npm start timed out: ' + app.stderr)), 15000);
      child.once('error', e => { clearTimeout(timer); reject(e); });
      child.once('exit', code => { clearTimeout(timer); if (!app.pid) reject(Error(`npm start exited ${code}: ${app.stderr}`)); });
      child.stdout.on('data', b => { app.stdout += b;
        const line = app.stdout.split(/\r?\n/).find(l => l.startsWith('{') && l.includes('mesh_listening'));
        if (line) { const value = JSON.parse(line); app.pid = value.pid; clearTimeout(timer); resolve(value); }
      });
    });
    Object.assign(app, info); assert.equal(info.mode, 'standalone'); assert.equal(info.dataDir, dataDir);
    app.identity = (await monitor.call('snapshot')).find(i => i.pid === app.pid);
    assert.ok(app.identity); assert.match(app.identity.commandLine, /node test\/m1-serve.mjs|node.*test[\\/]m1-serve.mjs/);
    await save(`npm-${child.pid}-startup.json`, { info, identity: app.identity, executable: child.spawnfile, argv: child.spawnargs,
      env: { MESH_STANDALONE: '1', MESH_RELAY: '1', MESH_DATA_DIR: dataDir, MESH_PREVIEW_PORT: String(port) } });
    return app;
  }
  async function stop(app) {
    if (app.child.exitCode === null && app.child.signalCode === null) {
      const live = (await monitor.call('snapshot')).find(i => i.pid === app.pid && !i.exitSignaled);
      if (live) { assert.equal(live.creationTime100ns, app.identity.creationTime100ns); await monitor.call('kill', live); }
      await app.closed;
    }
    await writeFile(path.join(directory, `npm-${app.child.pid}.log`), app.stdout + '\n' + app.stderr);
  }
  return { dataDir, directory, monitor, apps, boot, stop, save, async launches() {
    try { return (await readFile(launches, 'utf8')).trim().split('\n').filter(Boolean).map(JSON.parse); }
    catch (e) { if (e.code === 'ENOENT') return []; throw e; }
  }, async provenance() {
    return Object.fromEntries(await Promise.all(['server.mjs','test/m1-serve.mjs','package.json','public/app.js','public/index.html',
      'lib/task-store.mjs','lib/command-execution.mjs','lib/owned-command.py','lib/owned_job.py','config/commands.json','service_roots/relay/SOURCE.md']
      .map(async file => [file, createHash('sha256').update(await readFile(path.join(ROOT, file))).digest('hex')])));
  } };
}
