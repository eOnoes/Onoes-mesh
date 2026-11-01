import ctypes as C
from ctypes import wintypes as W
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from lib import owned_job as oj
from test.test_owned_cancel import Observer
root=Path('test')
identities={}
def visit(v):
 if isinstance(v,dict):
  if 'pid' in v and ('creationTime100ns' in v or 'createdAt' in v):
   identities[(v['pid'],v.get('creationTime100ns',v.get('createdAt')))]=v
  for x in v.values():visit(x)
 elif isinstance(v,list):
  for x in v:visit(x)
for directory in [root/'app03-review-m3-suite',root/'app03-review-m3-browser']:
 for file in directory.rglob('*.json'):
  try:visit(json.loads(file.read_text(encoding='utf-8-sig')))
  except (ValueError,UnicodeError):pass
observer=Observer(); result=[]
try:
 for key,v in identities.items():
  h=observer.api.OpenProcess(0x00100000|0x1000,False,v['pid'])
  if not h:
   assert observer.api.last_error()==87, (v,observer.api.last_error())
   result.append(dict(v,cleanupAudit='PID absent'));continue
  observer.handles.append(h)
  times=[W.FILETIME() for _ in range(4)]
  assert observer.GetProcessTimes(h,*[C.byref(t) for t in times])
  created=str((times[0].dwHighDateTime<<32)|times[0].dwLowDateTime)
  state=observer.api.WaitForSingleObject(h,0)
  if 'creationTime100ns' in v and created!=v['creationTime100ns']:
   result.append(dict(v,cleanupAudit='PID reused; original identity absent',currentCreationTime100ns=created));continue
  assert state==0, (v,'recorded process still live',created)
  result.append(dict(v,cleanupAudit='retained current handle exit-signaled'))
finally:observer.close()
for pid,role in [(3048516,'browser supervisor'),(3981944,'independent API bridge'),(2094596,'independent API root')]:
 h=observer.api.OpenProcess(0x00100000|0x1000,False,pid)
 if h:
  try:assert observer.api.WaitForSingleObject(h,0)==0,(pid,role)
  finally:assert observer.api.CloseHandle(h)
 result.append(dict(pid=pid,role=role,cleanupAudit='PID absent or handle exit-signaled'))
Path('test/app03-review-m3-cleanup.json').write_text(json.dumps(dict(verified=True,identities=result),indent=2),encoding='utf-8')
print(json.dumps(dict(event='review_cleanup_pass',recordedIdentities=len(identities),supervisorAndApiPidsAbsent=True)))
