"""Real Task Scheduler flag transitions on owned, trigger-free tasks only."""
import hashlib,json,os,subprocess,sys,uuid
from pathlib import Path
import pytest

sys.path[:0]=[os.environ['MIND_SOURCE'],str(Path(os.environ['MIND_TEST_SOURCE'])/'tests'),
    os.environ['MESH_PROVIDER_SOURCE']]
from test_cloud_curated_transfer import private_dir
from cloud_windows_task import Binding,TaskWindow,TaskHeld,invoke,digest

pytestmark=pytest.mark.skipif(os.name!='nt',reason='Actual Windows Task Scheduler')
PS=Path('C:/Windows/System32/WindowsPowerShell/v1.0/powershell.exe')


def task_admin(name,action,enabled=True):
    # All mutations are confined to this fixture's randomly named task. No
    # triggers are registered and its harmless action is never started.
    assert name.startswith('Onoes-Mesh-Isolated-Test-') and len(name)==len('Onoes-Mesh-Isolated-Test-')+36
    script=r'''
$ErrorActionPreference='Stop'
$name=$env:ONOES_TEST_TASK_NAME
if ($name -cnotmatch '^Onoes-Mesh-Isolated-Test-[a-f0-9]{36}$') {throw 'Not an owned test task'}
$operation=$env:ONOES_TEST_TASK_ACTION
if ($operation -eq 'create') {
  if (Get-ScheduledTask -TaskName $name -TaskPath '\' -ErrorAction SilentlyContinue) {throw 'Preserve existing task'}
  $action=New-ScheduledTaskAction -Execute $env:ComSpec -Argument '/d /c exit 0'
  $user=[Security.Principal.WindowsIdentity]::GetCurrent().Name
  $principal=New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited
  $settings=New-ScheduledTaskSettingsSet
  $settings.Enabled=($env:ONOES_TEST_TASK_ENABLED -eq 'true')
  Register-ScheduledTask -TaskName $name -TaskPath '\' -Description ('Owned Mesh no-trigger test '+$name) -Action $action -Principal $principal -Settings $settings|Out-Null
} else {
  $t=Get-ScheduledTask -TaskName $name -TaskPath '\' -ErrorAction SilentlyContinue
  if ($null -ne $t) {
    if ($t.Description -cnotlike ('Owned Mesh no-trigger test '+$name+'*') -or @($t.Triggers|Where-Object {$null -ne $_}).Count -ne 0 -or $t.State -in @('Running','Queued')) {throw 'Preserve unknown task'}
    if ($operation -eq 'drift') {$t.Description='Owned Mesh no-trigger test '+$name+' changed';Set-ScheduledTask -InputObject $t|Out-Null}
    elseif ($operation -eq 'remove') {Unregister-ScheduledTask -TaskName $name -TaskPath '\' -Confirm:$false}
    else {throw 'Unknown fixture action'}
  }
}
@{ownedTask=$name;action=$operation;hasTriggers=$false;actionStarted=$false}|ConvertTo-Json -Compress
'''
    env={**os.environ,'ONOES_TEST_TASK_NAME':name,'ONOES_TEST_TASK_ACTION':action,
        'ONOES_TEST_TASK_ENABLED':str(enabled).lower()}
    result=subprocess.run([str(PS),'-NoProfile','-NonInteractive','-Command',script],env=env,
        stdin=subprocess.DEVNULL,capture_output=True,creationflags=subprocess.CREATE_NO_WINDOW,timeout=30)
    assert result.returncode==0,result.stderr.decode('utf-8',errors='replace')[-3000:]
    return json.loads(result.stdout.decode('utf-8-sig'))


@pytest.fixture
def owned(tmp_path,request):
    # 36 hexadecimal characters, so the native fixture cannot target Mesh's
    # real task or another project even if supplied an unexpected argument.
    name='Onoes-Mesh-Isolated-Test-'+uuid.uuid4().hex+'0000'
    enabled=getattr(request,'param',True)
    created=task_admin(name,'create',enabled)
    assert created['actionStarted'] is False and created['hasTriggers'] is False
    try:
        before=invoke(powershell=PS,powershell_sha256=digest(PS),task_name=name)
        assert before['activeInstances']==[] and before['enabled']==enabled
        evidence=private_dir(tmp_path/'task-evidence')
        binding=Binding(name,'\\',str(PS),digest(PS),before['definitionSha256'],
            before['otherDefinitionSha256'],before['enabled'])
        yield TaskWindow(binding,evidence),before
    finally:
        task_admin(name,'remove')


@pytest.mark.parametrize('owned',[True,False],indirect=True)
def test_real_pause_restore_preserves_all_other_settings_and_original_flag(owned):
    window,before=owned
    result=window.pause()
    assert result['verified'] and result['readyForCutover']
    paused=window.assert_paused()
    assert paused['otherDefinitionSha256']==before['otherDefinitionSha256']
    assert window.restore()['originalEnabledRestored']
    after=window.status()
    assert after['enabled']==before['enabled']
    assert after['otherDefinitionSha256']==before['otherDefinitionSha256']
    assert after['activeInstances']==[]
    assert (window.evidence/'TASK-ORIGINAL.xml').read_bytes()==before['xml'].encode()


def test_native_replay_cannot_make_a_second_transition(owned):
    window,_=owned
    window.pause();window.restore();before=window.status()
    with pytest.raises((TaskHeld,FileExistsError)):window.pause()
    with pytest.raises((TaskHeld,FileExistsError)):window.restore()
    assert window.status()['definitionSha256']==before['definitionSha256']


def test_changed_task_is_refused_before_pause_or_evidence_write(owned):
    window,_=owned
    task_admin(window.binding.task_name,'drift')
    before=window.status()
    with pytest.raises(TaskHeld):window.pause()
    assert list(window.evidence.iterdir())==[]
    assert window.status()['definitionSha256']==before['definitionSha256']


def test_foreign_drift_after_pause_blocks_restore_without_replacing_settings(owned):
    window,_=owned
    window.pause();task_admin(window.binding.task_name,'drift')
    before=window.status()
    with pytest.raises(TaskHeld):window.restore()
    assert not (window.evidence/'TASK-RESTORE-ATTEMPT.json').exists()
    assert window.status()['definitionSha256']==before['definitionSha256']


def test_wrong_powershell_pin_and_non_boolean_restore_refused_before_launch(owned):
    window,_=owned;before=window.status();b=window.binding
    with pytest.raises(TaskHeld):invoke(powershell=PS,powershell_sha256='0'*64,task_name=b.task_name)
    with pytest.raises(TaskHeld):invoke(powershell=PS,powershell_sha256=b.powershell_sha256,
        task_name=b.task_name,action='restore',expected_sha256=b.original_sha256,
        expected_other_sha256=b.other_sha256,restore_enabled='false')
    assert window.status()['definitionSha256']==before['definitionSha256']
