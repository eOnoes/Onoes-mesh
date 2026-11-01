import sys,json,time,threading,queue,ctypes as C
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
 try: i['commandLine']=cmdline(h)
 except Exception as e: i['commandLineError']=str(e)
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
   assert o.api.TerminateProcess(h,1)
  if action in ('snapshot','kill','finish'):
   scan(); print(json.dumps({'event':action,'target':command.get('pid'),'identities':records,'acquisitionRaces':races,'rejectedParentage':rejected}),flush=True)
  if action in ('finish','eof'): break
finally:
 o.close()
