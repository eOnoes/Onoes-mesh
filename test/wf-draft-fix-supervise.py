"""Bounded custody observer for this proof's exact Node process tree only."""
import ctypes as c
from ctypes import wintypes as w
import json, os, pathlib, subprocess, sys, time

root = pathlib.Path(__file__).resolve().parents[1]
directory = (root / sys.argv[1]).resolve()
assert directory.parent == root / 'test' and directory.name.startswith('app03-draft-proof-')
directory.mkdir(exist_ok=False)
(directory/'binding.json').write_text(json.dumps({'baseline':'f8b284c160450397bc0b0e966bcfb1e529fe1596','worktree':str(root),'route':'gpt-6.1-sol/high workspace-write approval_policy=never','phase':'candidate'}),encoding='utf-8')
k = c.WinDLL('kernel32', use_last_error=True)
nt = c.WinDLL('ntdll')
class Entry(c.Structure):
    _fields_ = [('size',w.DWORD),('usage',w.DWORD),('pid',w.DWORD),('heap',c.c_size_t),('module',w.DWORD),('threads',w.DWORD),('parent',w.DWORD),('priority',w.LONG),('flags',w.DWORD),('exe',w.WCHAR*260)]
class Unicode(c.Structure):
    _fields_ = [('length',w.USHORT),('maximum',w.USHORT),('buffer',c.c_void_p)]
k.CreateToolhelp32Snapshot.restype = w.HANDLE
k.OpenProcess.restype = w.HANDLE
k.OpenProcess.argtypes = [w.DWORD,w.BOOL,w.DWORD]
for name in ['CloseHandle','WaitForSingleObject','GetExitCodeProcess','GetProcessTimes','QueryFullProcessImageNameW']:
    getattr(k,name).argtypes = {'CloseHandle':[w.HANDLE], 'WaitForSingleObject':[w.HANDLE,w.DWORD], 'GetExitCodeProcess':[w.HANDLE,c.POINTER(w.DWORD)],'GetProcessTimes':[w.HANDLE,c.POINTER(w.FILETIME),c.POINTER(w.FILETIME),c.POINTER(w.FILETIME),c.POINTER(w.FILETIME)],'QueryFullProcessImageNameW':[w.HANDLE,w.DWORD,w.LPWSTR,c.POINTER(w.DWORD)]}[name]
k.Process32FirstW.argtypes = k.Process32NextW.argtypes = [w.HANDLE,c.POINTER(Entry)]
nt.NtQueryInformationProcess.argtypes = [w.HANDLE,w.ULONG,c.c_void_p,w.ULONG,c.POINTER(w.ULONG)]
identities = {}; errors = []
observer_handle = k.OpenProcess(0x100000|0x1000,False,os.getpid())
observer_times = [w.FILETIME() for _ in range(4)]
assert observer_handle and k.GetProcessTimes(observer_handle,*[c.byref(x) for x in observer_times])
observer_created = (observer_times[0].dwHighDateTime << 32) | observer_times[0].dwLowDateTime
k.CloseHandle(observer_handle)
target = sys.argv[2] if len(sys.argv)>2 else 'test/wf-draft-fix-browser.mjs'
assert target in ['test/wf-draft-fix-browser.mjs','test/wf-draft-cancel-browser.mjs']
argv = [r'C:\Program Files\node.exe', str(root / target), sys.argv[1]]
out = open(directory / 'stdout.txt','wb'); err = open(directory / 'stderr.txt','wb')
env = dict(os.environ, MESH_STANDALONE='1', MESH_RELAY='0')
p = subprocess.Popen(argv,cwd=root,env=env,stdout=out,stderr=err,creationflags=subprocess.CREATE_NO_WINDOW)
def acquire(pid,parent):
    handle = k.OpenProcess(0x100000|0x1000,False,pid)
    if not handle:
        errors.append({'pid':pid,'parent':parent,'openError':c.get_last_error()}); return
    times = [w.FILETIME() for _ in range(4)]
    if not k.GetProcessTimes(handle,*[c.byref(x) for x in times]):
        errors.append({'pid':pid,'timesError':c.get_last_error()}); k.CloseHandle(handle); return
    created = (times[0].dwHighDateTime << 32) | times[0].dwLowDateTime
    if (pid,created) in identities: k.CloseHandle(handle); return
    parent_created = observer_created if parent == os.getpid() else next((i['creationTime100ns'] for i in identities.values() if i['pid']==parent and k.WaitForSingleObject(i['handle'],0)==258),None)
    if parent_created is None or created < parent_created:
        errors.append({'pid':pid,'parent':parent,'created':created,'parentCreated':parent_created,'error':'parent generation unavailable or child predates parent'})
        k.CloseHandle(handle); return
    buf = c.create_unicode_buffer(32768); size = w.DWORD(len(buf))
    exe = buf.value if k.QueryFullProcessImageNameW(handle,0,buf,c.byref(size)) else None
    needed = w.ULONG(); nt.NtQueryInformationProcess(handle,60,None,0,c.byref(needed))
    cmd = None; cmdstatus = None
    if needed.value:
        data = c.create_string_buffer(needed.value)
        cmdstatus = nt.NtQueryInformationProcess(handle,60,data,len(data),c.byref(needed))
        if cmdstatus == 0:
            u = Unicode.from_buffer(data); cmd = c.wstring_at(u.buffer,u.length//2)
    identities[(pid,created)] = {'pid':pid,'parentPid':parent,'parentCreationTime100ns':parent_created,'creationTime100ns':created,'exe':exe,'commandLine':cmd,'commandQueryStatus':cmdstatus,'handle':handle}
acquire(p.pid,os.getpid())
def scan():
    snap = k.CreateToolhelp32Snapshot(2,0)
    if snap == c.c_void_p(-1).value: errors.append({'snapshotError':c.get_last_error()}); return
    entries = []; e = Entry(); e.size=c.sizeof(e)
    ok = k.Process32FirstW(snap,c.byref(e))
    while ok:
        entries.append((e.pid,e.parent)); ok = k.Process32NextW(snap,c.byref(e))
    k.CloseHandle(snap)
    owned = {i['pid'] for i in identities.values() if k.WaitForSingleObject(i['handle'],0)==258}
    for _ in range(8):
        children = [(pid,parent) for pid,parent in entries if parent in owned and pid not in owned]
        if not children: break
        for pid,parent in children: acquire(pid,parent); owned.add(pid)
start=time.monotonic()
while time.monotonic()-start < 90:
    scan()
    if p.poll() is not None and all(k.WaitForSingleObject(i['handle'],0)==0 for i in identities.values()): break
    time.sleep(.02)
out.close(); err.close()
results=[]
for i in identities.values():
    handle=i.pop('handle'); i['exitSignaled']=k.WaitForSingleObject(handle,0)==0
    code=w.DWORD(); i['exitCode']=code.value if k.GetExitCodeProcess(handle,c.byref(code)) else None
    # GetExitCodeProcess writes code only after the call.
    if i['exitCode'] is not None: i['exitCode']=code.value
    results.append(i); k.CloseHandle(handle)
receipt={'argv':argv,'cwd':str(root),'envOverrides':{'MESH_STANDALONE':'1','MESH_RELAY':'0'},'rootPid':p.pid,'rootExit':p.poll(),'elapsedSeconds':time.monotonic()-start,'identities':results,'acquisitionErrors':errors,'allAcquiredExited':all(i['exitSignaled'] for i in results),'limit':'Fast unobserved descendants cannot be attested; no termination or unrelated process access performed.'}
(directory/'native-custody.json').write_text(json.dumps(receipt,indent=2),encoding='utf-8')
print(json.dumps({'directory':str(directory),'rootExit':p.poll(),'acquired':len(results),'allAcquiredExited':receipt['allAcquiredExited'],'acquisitionErrors':len(errors)}))
sys.exit(0 if p.poll()==0 and receipt['allAcquiredExited'] and not errors else 1)
