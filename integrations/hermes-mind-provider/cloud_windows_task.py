"""Finite exact task-flag control for an owner-approved installation window.

No registration, task start/stop, new schedule or process management. The owner
entry must bind this helper to Mesh's existing task and verify authorization.
Tests use a distinct disposable task with no triggers and never run its action.
"""
from dataclasses import dataclass,asdict
import base64,hashlib,json,os,re,subprocess
from pathlib import Path


class TaskHeld(RuntimeError):pass


def require(ok):
    if not ok:raise TaskHeld('Exact startup-task state differs; preserve original evidence')


def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


SCRIPT=r'''
$ErrorActionPreference='Stop'
[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false)
$r=$env:ONOES_MESH_WINDOW_TASK_REQUEST|ConvertFrom-Json
if ($r.taskPath -cne '\' -or $r.taskName -cnotmatch '^[A-Za-z0-9 _.\-]{1,200}$') {throw 'Invalid exact task binding'}
$service=New-Object -ComObject Schedule.Service
$service.Connect()
function Hash([string]$text) {
  $h=[Security.Cryptography.SHA256]::Create()
  try {return ([BitConverter]::ToString($h.ComputeHash([Text.Encoding]::UTF8.GetBytes($text)))).Replace('-','').ToLowerInvariant()} finally {$h.Dispose()}
}
function Snapshot {
  $tasks=@(Get-ScheduledTask -TaskName $r.taskName -TaskPath $r.taskPath)
  if ($tasks.Count -ne 1) {throw 'Exact task not found'}
  $t=$tasks[0]
  $registered=$service.GetFolder($r.taskPath).GetTask($r.taskName)
  $xml=Export-ScheduledTask -TaskName $r.taskName -TaskPath $r.taskPath
  [xml]$doc=$xml
  $ns=[Xml.XmlNamespaceManager]::new($doc.NameTable)
  $ns.AddNamespace('t',$doc.DocumentElement.NamespaceURI)
  $flag=$doc.SelectSingleNode('/t:Task/t:Settings/t:Enabled',$ns)
  if ($null -ne $flag) {[void]$flag.ParentNode.RemoveChild($flag)}
  $instances=@()
  foreach ($instance in $registered.GetInstances(0)) {$instances+=([string]$instance.InstanceGuid)}
  return @{taskName=$r.taskName;taskPath=$r.taskPath;enabled=[bool]$registered.Enabled;
    state=[string]$t.State;activeInstances=$instances;xml=$xml;definitionSha256=(Hash $xml);
    otherDefinitionSha256=(Hash $doc.OuterXml)}
}
$before=Snapshot
if ($r.action -eq 'status') {$before|ConvertTo-Json -Depth 6 -Compress;exit 0}
if ($r.action -notin @('pause','restore') -or $before.definitionSha256 -cne $r.expectedSha256 -or
    $before.otherDefinitionSha256 -cne $r.expectedOtherSha256) {throw 'Task changed before mutation'}
$desired=$false
if ($r.action -eq 'restore') {$desired=[bool]$r.restoreEnabled}
if ($before.enabled -ne $desired) {
  if ($desired) {Enable-ScheduledTask -TaskName $r.taskName -TaskPath $r.taskPath|Out-Null}
  else {Disable-ScheduledTask -TaskName $r.taskName -TaskPath $r.taskPath|Out-Null}
}
$after=Snapshot
if ($after.enabled -ne $desired -or $after.otherDefinitionSha256 -cne $before.otherDefinitionSha256) {throw 'Task transition unconfirmed'}
$after|ConvertTo-Json -Depth 6 -Compress
'''


def invoke(*,powershell,powershell_sha256,task_name,task_path='\\',action='status',
           expected_sha256=None,expected_other_sha256=None,restore_enabled=None):
    require(os.name=='nt' and re.fullmatch(r'[A-Za-z0-9 _.\-]{1,200}',task_name)
        and task_path=='\\' and action in ('status','pause','restore'))
    ps=Path(powershell)
    require(ps.is_absolute() and ps.resolve(strict=True)==ps and digest(ps)==powershell_sha256)
    if action!='status':
        require(all(type(v) is str and re.fullmatch('[a-f0-9]{64}',v) for v in (expected_sha256,expected_other_sha256)))
    if action=='restore':require(type(restore_enabled) is bool)
    request={'taskName':task_name,'taskPath':task_path,'action':action,'expectedSha256':expected_sha256,
        'expectedOtherSha256':expected_other_sha256,'restoreEnabled':restore_enabled}
    environment={**os.environ,'ONOES_MESH_WINDOW_TASK_REQUEST':json.dumps(request,separators=(',',':'))}
    result=subprocess.run([str(ps),'-NoLogo','-NoProfile','-NonInteractive','-EncodedCommand',
        base64.b64encode(SCRIPT.encode('utf-16-le')).decode('ascii')],env=environment,
        stdin=subprocess.DEVNULL,capture_output=True,timeout=30,creationflags=subprocess.CREATE_NO_WINDOW)
    require(result.returncode==0)
    value=json.loads(result.stdout.decode('utf-8-sig'))
    require(value['taskName']==task_name and value['taskPath']==task_path
        and type(value['enabled']) is bool and type(value['activeInstances']) is list
        and hashlib.sha256(value['xml'].encode()).hexdigest()==value['definitionSha256'])
    return value


@dataclass(frozen=True)
class Binding:
    task_name:str
    task_path:str
    powershell:str
    powershell_sha256:str
    original_sha256:str
    other_sha256:str
    original_enabled:bool


def save(root,name,value,*,raw=False):
    from onoes_mind.enrollment_store import qualify_private_storage
    root=qualify_private_storage(Path(root));path=root/name
    data=value if raw else json.dumps(value,sort_keys=True).encode()
    with path.open('xb') as stream:stream.write(data);stream.flush();os.fsync(stream.fileno())
    qualify_private_storage(path,kind='file')


class TaskWindow:
    def __init__(self,binding,evidence):
        require(type(binding) is Binding and type(binding.original_enabled) is bool)
        self.binding=binding;self.evidence=Path(evidence)

    def _invoke(self,**operation):
        b=self.binding
        return invoke(powershell=b.powershell,powershell_sha256=b.powershell_sha256,
            task_name=b.task_name,task_path=b.task_path,**operation)

    def status(self):return self._invoke()

    def pause(self):
        b=self.binding;before=self.status()
        require(before['definitionSha256']==b.original_sha256 and before['otherDefinitionSha256']==b.other_sha256
            and before['enabled']==b.original_enabled)
        save(self.evidence,'TASK-ORIGINAL.xml',before['xml'].encode(),raw=True)
        save(self.evidence,'TASK-PAUSE-ATTEMPT.json',{'binding':asdict(b),'automaticRetry':False})
        after=self._invoke(action='pause',expected_sha256=b.original_sha256,expected_other_sha256=b.other_sha256)
        require(after['enabled'] is False and after['otherDefinitionSha256']==b.other_sha256)
        save(self.evidence,'TASK-PAUSED.json',after)
        return {'verified':True,'enabled':False,'definitionSha256':after['definitionSha256'],
            'readyForCutover':after['activeInstances']==[] and after['state'] not in ('Running','Queued')}

    def assert_paused(self):
        from onoes_mind.enrollment_store import qualify_private_storage
        path=qualify_private_storage(self.evidence/'TASK-PAUSED.json',kind='file')
        expected=json.loads(path.read_bytes());current=self.status()
        require(current['enabled'] is False and current['definitionSha256']==expected['definitionSha256']
            and current['otherDefinitionSha256']==self.binding.other_sha256
            and not current['activeInstances'] and current['state'] not in ('Running','Queued'))
        return current

    def restore(self):
        from onoes_mind.enrollment_store import qualify_private_storage
        b=self.binding;before=self.assert_paused()
        original=qualify_private_storage(self.evidence/'TASK-ORIGINAL.xml',kind='file').read_bytes()
        require(hashlib.sha256(original).hexdigest()==b.original_sha256)
        save(self.evidence,'TASK-RESTORE-ATTEMPT.json',{'originalEnabled':b.original_enabled,'automaticRetry':False})
        after=self._invoke(action='restore',expected_sha256=before['definitionSha256'],
            expected_other_sha256=b.other_sha256,restore_enabled=b.original_enabled)
        require(after['enabled']==b.original_enabled and after['otherDefinitionSha256']==b.other_sha256)
        save(self.evidence,'TASK-RESTORED.json',after)
        return {'verified':True,'originalEnabledRestored':True,'otherSettingsUnchanged':True,
            'taskStartedOrStopped':False,'enabled':after['enabled']}
