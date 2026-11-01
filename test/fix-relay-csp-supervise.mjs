import { mkdir, writeFile } from 'node:fs/promises';
import path from 'node:path';

// Prepare a local, console-free observer/launcher. It only retains handles for
// this launch's descendants; it never terminates or reads unrelated processes.
const directory = path.resolve('test/app03-csp-evidence');
await mkdir(directory, { recursive: true });
await writeFile(path.join(directory, 'supervisor.py'), String.raw`
import ctypes as c
from ctypes import wintypes as w
import json, os, pathlib, subprocess, sys, time, traceback, urllib.request

k = c.WinDLL('kernel32', use_last_error=True)
n = c.WinDLL('ntdll')
u = c.WinDLL('user32', use_last_error=True)
k.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]; k.OpenProcess.restype = w.HANDLE
k.CloseHandle.argtypes = [w.HANDLE]
k.GetProcessTimes.argtypes = [w.HANDLE] + [c.POINTER(w.FILETIME)] * 4
k.QueryFullProcessImageNameW.argtypes = [w.HANDLE,w.DWORD,w.LPWSTR,c.POINTER(w.DWORD)]
k.WaitForSingleObject.argtypes = [w.HANDLE,w.DWORD]
k.GetExitCodeProcess.argtypes = [w.HANDLE,c.POINTER(w.DWORD)]
n.NtQueryInformationProcess.argtypes = [w.HANDLE,w.ULONG,c.c_void_p,w.ULONG,c.POINTER(w.ULONG)]
n.NtQueryInformationProcess.restype = c.c_long
class US(c.Structure):
    _fields_ = [('Length',w.USHORT),('MaximumLength',w.USHORT),('Buffer',c.c_void_p)]
class PE(c.Structure):
    _fields_ = [('dwSize',w.DWORD),('cntUsage',w.DWORD),('th32ProcessID',w.DWORD),('th32DefaultHeapID',c.c_size_t),('th32ModuleID',w.DWORD),('cntThreads',w.DWORD),('th32ParentProcessID',w.DWORD),('pcPriClassBase',w.LONG),('dwFlags',w.DWORD),('szExeFile',w.WCHAR*260)]
k.CreateToolhelp32Snapshot.argtypes = [w.DWORD,w.DWORD]; k.CreateToolhelp32Snapshot.restype = w.HANDLE
k.Process32FirstW.argtypes = [w.HANDLE,c.POINTER(PE)]
k.Process32NextW.argtypes = [w.HANDLE,c.POINTER(PE)]
CB = c.WINFUNCTYPE(w.BOOL,w.HWND,w.LPARAM)
u.EnumWindows.argtypes = [CB,w.LPARAM]
u.IsWindowVisible.argtypes = [w.HWND]; u.IsWindowVisible.restype = w.BOOL
u.GetWindowThreadProcessId.argtypes = [w.HWND,c.POINTER(w.DWORD)]
u.GetWindowTextW.argtypes = [w.HWND,w.LPWSTR,c.c_int]
u.GetClassNameW.argtypes = [w.HWND,w.LPWSTR,c.c_int]

root = pathlib.Path.cwd()
label = sys.argv[1]
assert label.replace('-','').isalnum()
out = root / 'test' / 'app03-csp-evidence' / label
out.mkdir(parents=True,exist_ok=True)
held = {}
races = []
windows = {}
def acquire(pid,parent,purpose):
    h = k.OpenProcess(0x100000 | 0x1000,False,pid)
    if not h: raise c.WinError(c.get_last_error())
    try:
        times = [w.FILETIME() for _ in range(4)]
        if not k.GetProcessTimes(h,*[c.byref(t) for t in times]): raise c.WinError(c.get_last_error())
        image = c.create_unicode_buffer(32768); size=w.DWORD(len(image))
        if not k.QueryFullProcessImageNameW(h,0,image,c.byref(size)): raise c.WinError(c.get_last_error())
        needed=w.ULONG()
        n.NtQueryInformationProcess(h,60,None,0,c.byref(needed))
        buf=c.create_string_buffer(needed.value+1024)
        result=n.NtQueryInformationProcess(h,60,buf,len(buf),c.byref(needed))
        if result < 0: raise RuntimeError('Command line query failed: '+str(result))
        us=US.from_buffer(buf)
        argv=c.wstring_at(us.Buffer,us.Length//2)
        entry=dict(pid=pid,parentPid=parent,creationTime100ns=str((times[0].dwHighDateTime<<32)|times[0].dwLowDateTime),executable=image.value,argv=argv,worktree=str(root),purpose=purpose,ancestry=[parent],exitSignaled=False)
        held[pid]=(h,entry)
        return entry
    except:
        k.CloseHandle(h)
        raise
def snapshot():
    h=k.CreateToolhelp32Snapshot(2,0)
    if h == c.c_void_p(-1).value: raise c.WinError(c.get_last_error())
    entries={}; pe=PE(); pe.dwSize=c.sizeof(pe)
    try:
        ok=k.Process32FirstW(h,c.byref(pe))
        while ok:
            entries[pe.th32ProcessID]=(pe.th32ParentProcessID,pe.szExeFile)
            ok=k.Process32NextW(h,c.byref(pe))
    finally: k.CloseHandle(h)
    return entries
def scan():
    entries=snapshot()
    progress=True
    while progress:
        progress=False
        for pid,(parent,exe) in entries.items():
            if parent in held and pid not in held and not held[parent][1]['exitSignaled']:
                try:
                    entry=acquire(pid,parent,label+' owned descendant '+exe)
                    entry['ancestry']=[parent]+held[parent][1]['ancestry']
                    progress=True
                except OSError as e:
                    races.append(dict(pid=pid,parentPid=parent,executable=exe,error=str(e),time=time.time()))
    for h,entry in held.values():
        if k.WaitForSingleObject(h,0)==0:
            code=w.DWORD()
            if not k.GetExitCodeProcess(h,c.byref(code)): raise c.WinError(c.get_last_error())
            entry.update(exitSignaled=True,exitCode=code.value)
    @CB
    def visit(hwnd,_):
        pid=w.DWORD();u.GetWindowThreadProcessId(hwnd,c.byref(pid))
        if pid.value in held:
            title=c.create_unicode_buffer(512);kind=c.create_unicode_buffer(128)
            u.GetWindowTextW(hwnd,title,len(title));u.GetClassNameW(hwnd,kind,len(kind))
            key=(pid.value,int(hwnd))
            previous=windows.get(key,{})
            windows[key]=dict(pid=pid.value,hwnd=str(hwnd),title=title.value,windowClass=kind.value,everVisible=previous.get('everVisible',False) or bool(u.IsWindowVisible(hwnd)))
        return True
    u.EnumWindows(visit,0)
def save(**extra):
    receipt=dict(label=label,worktree=str(root),launch=sys.argv[2:],identities=[v for _,v in held.values()],windows=list(windows.values()),acquisitionRaces=races,**extra)
    (out/'process-receipt.json').write_text(json.dumps(receipt,indent=2),encoding='utf-8')
    return receipt
def protected():
    try:
        with urllib.request.urlopen('http://127.0.0.1:4317/',timeout=3) as r: return r.status
    except Exception as e: return str(e)
child=None
try:
    acquire(os.getpid(),os.getppid(),label+' console-free supervisor')
    (out/'supervisor-identity.json').write_text(json.dumps(held[os.getpid()][1],indent=2),encoding='utf-8')
    healthBefore=protected()
    with (out/'stdout.txt').open('wb') as stdout,(out/'stderr.txt').open('wb') as stderr:
        child=subprocess.Popen(sys.argv[2:],cwd=root,stdin=subprocess.DEVNULL,stdout=stdout,stderr=stderr,creationflags=subprocess.CREATE_NO_WINDOW)
        acquire(child.pid,os.getpid(),label+' root test command')
        start=time.monotonic()
        while child.poll() is None:
            scan()
            if time.monotonic()-start > 180:
                save(failure='Root test deadline; retained processes left untouched',protectedBefore=healthBefore,protectedAfter=protected())
                raise RuntimeError('Root test deadline')
            time.sleep(.005)
        until=time.monotonic()+8
        while True:
            scan()
            live=[v for pid,(_,v) in held.items() if pid!=os.getpid() and not v['exitSignaled']]
            if not live or time.monotonic()>=until: break
            time.sleep(.01)
    receipt=save(commandExit=child.returncode,protectedBefore=healthBefore,protectedAfter=protected(),descendantsExited=not live,hiddenWindows=not any(v['everVisible'] for v in windows.values()))
    assert not live, 'Original owned native handles remain live'
    assert receipt['hiddenWindows'], 'Owned launch exposed a visible window'
    assert not races, 'Native acquisition race retained; no fabricated exit proof'
    sys.exit(child.returncode)
except BaseException as e:
    if not isinstance(e,SystemExit):
        (out/'supervisor-error.txt').write_text(traceback.format_exc(),encoding='utf-8')
        save(failure=str(e),commandExit=child.returncode if child else None,protectedAfter=protected())
        sys.exit(1)
    raise
finally:
    for h,_ in held.values(): k.CloseHandle(h)
`);
console.log(path.join(directory, 'supervisor.py'));
