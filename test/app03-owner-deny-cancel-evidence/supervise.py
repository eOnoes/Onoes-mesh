"""Console-free, read-only descendant inventory and original-handle exit proof."""
import ctypes as c
from ctypes import wintypes as w
import json, pathlib, subprocess, sys, time, urllib.request, traceback, os

root = pathlib.Path(__file__).resolve().parents[2]
out = pathlib.Path(__file__).parent / sys.argv[1]
out.mkdir(parents=True, exist_ok=True)
k = c.WinDLL('kernel32', use_last_error=True)
n = c.WinDLL('ntdll')
u = c.WinDLL('user32')
class Entry(c.Structure):
    _fields_ = [('size',w.DWORD),('usage',w.DWORD),('pid',w.DWORD),('heap',c.c_size_t),('module',w.DWORD),('threads',w.DWORD),('parent',w.DWORD),('priority',w.LONG),('flags',w.DWORD),('exe',w.WCHAR*260)]
class US(c.Structure):
    _fields_ = [('length',w.USHORT),('maximum',w.USHORT),('buffer',c.c_void_p)]
k.CreateToolhelp32Snapshot.argtypes=[w.DWORD,w.DWORD]; k.CreateToolhelp32Snapshot.restype=w.HANDLE
k.Process32FirstW.argtypes=[w.HANDLE,c.POINTER(Entry)]; k.Process32NextW.argtypes=[w.HANDLE,c.POINTER(Entry)]
k.OpenProcess.argtypes=[w.DWORD,w.BOOL,w.DWORD]; k.OpenProcess.restype=w.HANDLE
k.GetProcessTimes.argtypes=[w.HANDLE]+[c.POINTER(w.FILETIME)]*4
k.QueryFullProcessImageNameW.argtypes=[w.HANDLE,w.DWORD,w.LPWSTR,c.POINTER(w.DWORD)]
k.WaitForSingleObject.argtypes=[w.HANDLE,w.DWORD]; k.GetExitCodeProcess.argtypes=[w.HANDLE,c.POINTER(w.DWORD)]
k.CloseHandle.argtypes=[w.HANDLE]
n.NtQueryInformationProcess.argtypes=[w.HANDLE,w.ULONG,c.c_void_p,w.ULONG,c.POINTER(w.ULONG)]
u.GetWindowThreadProcessId.argtypes=[w.HWND,c.POINTER(w.DWORD)]; u.IsWindowVisible.argtypes=[w.HWND]
callback=c.WINFUNCTYPE(w.BOOL,w.HWND,w.LPARAM)
u.EnumWindows.argtypes=[callback,w.LPARAM]
owned={}; misses=[]; windows=[]
def exception(kind,value,tb):
    (out/'supervisor-error.txt').write_text(''.join(traceback.format_exception(kind,value,tb)),encoding='utf8')
    (out/'interrupted-handles.json').write_text(json.dumps([r for _,r in owned.values()],indent=2),encoding='utf8')
sys.excepthook=exception
def snapshot():
    h=k.CreateToolhelp32Snapshot(2,0); e=Entry(); e.size=c.sizeof(e); rows={}
    try:
        ok=k.Process32FirstW(h,c.byref(e))
        while ok:
            rows[e.pid]=(e.parent,e.exe); ok=k.Process32NextW(h,c.byref(e))
    finally: k.CloseHandle(h)
    return rows
def acquire(pid,parent,exe):
    h=k.OpenProcess(0x100000|0x1000|0x400,False,pid)
    if not h:
        misses.append({'pid':pid,'parentPid':parent,'snapshotExe':exe,'error':c.get_last_error()}); return
    times=[w.FILETIME() for _ in range(4)]
    if not k.GetProcessTimes(h,*[c.byref(t) for t in times]): raise c.WinError(c.get_last_error())
    image=c.create_unicode_buffer(32768); size=w.DWORD(len(image))
    if not k.QueryFullProcessImageNameW(h,0,image,c.byref(size)): raise c.WinError(c.get_last_error())
    length=w.ULONG(); n.NtQueryInformationProcess(h,60,None,0,c.byref(length))
    buf=c.create_string_buffer(max(length.value,65536))
    status=n.NtQueryInformationProcess(h,60,buf,len(buf),c.byref(length))
    argv=c.wstring_at(US.from_buffer(buf).buffer,US.from_buffer(buf).length//2) if status==0 else None
    owned[pid]=(h,{'pid':pid,'parentPid':parent,'creationTime100ns':str((times[0].dwHighDateTime<<32)|times[0].dwLowDateTime),'executable':image.value,'argv':argv,'argvStatus':status,'purpose':'owned disposable verification descendant','visibleWindows':[]})
def scan():
    rows=snapshot(); wanted={process.pid}
    while True:
        extra={pid for pid,(parent,_) in rows.items() if parent in wanted or parent in owned}
        if extra<=wanted: break
        wanted|=extra
    for pid in wanted:
        if pid in rows and pid not in owned: acquire(pid,*rows[pid])
    @callback
    def each(hwnd,_):
        pid=w.DWORD(); u.GetWindowThreadProcessId(hwnd,c.byref(pid))
        if pid.value in owned and u.IsWindowVisible(hwnd):
            item={'pid':pid.value,'hwnd':int(hwnd)}
            if item not in windows: windows.append(item); owned[pid.value][1]['visibleWindows'].append(int(hwnd))
        return True
    u.EnumWindows(each,0)

command=sys.argv[2:]
rows=snapshot()
acquire(os.getpid(),*rows[os.getpid()])
(out/'supervisor-identity.json').write_text(json.dumps(owned[os.getpid()][1],indent=2),encoding='utf8')
own_handle,_=owned.pop(os.getpid()); k.CloseHandle(own_handle)
with (out/'stdout.txt').open('w',encoding='utf8') as stdout, (out/'stderr.txt').open('w',encoding='utf8') as stderr:
    process=subprocess.Popen(command,cwd=root,stdin=subprocess.DEVNULL,stdout=stdout,stderr=stderr,creationflags=subprocess.CREATE_NO_WINDOW)
    while process.poll() is None:
        scan(); time.sleep(.015)
    code=process.wait()
    deadline=time.monotonic()+8
    while time.monotonic()<deadline:
        scan()
        if all(k.WaitForSingleObject(h,0)==0 for h,_ in owned.values()): break
        time.sleep(.02)
records=[]
for h,r in owned.values():
    r['exitSignaled']=k.WaitForSingleObject(h,0)==0
    ec=w.DWORD(); k.GetExitCodeProcess(h,c.byref(ec)); r['exitCode']=ec.value
    records.append(r); k.CloseHandle(h)
try:
    protected=urllib.request.urlopen('http://127.0.0.1:4317/',timeout=3).status
except Exception as e: protected=str(e)
receipt={'command':command,'code':code,'identities':records,'acquisitionMisses':misses,'visibleWindows':windows,'protected4317':protected,'cleanupVerified':all(r['exitSignaled'] for r in records),'policy':'No process termination by this observer; exact owned ChildProcess/stdin/browser closure belongs to the harness.'}
(out/'cleanup.json').write_text(json.dumps(receipt,indent=2),encoding='utf8')
sys.exit(code if code else (1 if windows or misses or not receipt['cleanupVerified'] else 0))
