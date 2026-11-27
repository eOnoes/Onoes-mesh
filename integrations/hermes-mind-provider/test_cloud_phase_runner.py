"""Actual owned child transport, privacy, replay and uncertain-exit behavior."""
import json,os,sys
from pathlib import Path
import pytest

sys.path[:0]=[os.environ['MIND_SOURCE'],str(Path(os.environ['MIND_TEST_SOURCE'])/'tests'),
    os.environ['MESH_PROVIDER_SOURCE']]
from cloud_phase_runner import execute_once,NativePhases,PhaseTransportHeld
from test_cloud_curated_transfer import private_dir


def journals(folder):return b''.join(p.read_bytes() for p in folder.iterdir())


def test_real_child_private_stdin_and_stdout_excluded_from_journal(tmp_path):
    evidence=private_dir(tmp_path/'evidence');private=b'Harmless private transport marker'
    code='import sys;sys.stdout.buffer.write(sys.stdin.buffer.read());sys.stderr.buffer.write(b"private child detail")'
    result=execute_once([sys.executable,'-I','-B','-c',code],evidence=evidence,
        label='curated-export',stdin=private,private_stdout=True)
    assert result==private
    assert private not in journals(evidence) and b'private child detail' not in journals(evidence)
    proof=json.loads((evidence/'curated-export-TRANSPORT-RESULT.json').read_bytes())
    assert proof['exitCode']==0 and proof['stdoutBytes']==len(private)


def test_attempt_replay_cannot_execute_child_twice(tmp_path):
    evidence=private_dir(tmp_path/'evidence');target=tmp_path/'one-owned-write'
    code='from pathlib import Path;import json,sys;Path(sys.argv[1]).open("x").write("owned");print(json.dumps({"verified":True}))'
    argv=[sys.executable,'-I','-B','-c',code,str(target)]
    assert execute_once(argv,evidence=evidence,label='one-write')['verified']
    before=target.stat().st_mtime_ns
    with pytest.raises(FileExistsError):execute_once(argv,evidence=evidence,label='one-write')
    assert target.stat().st_mtime_ns==before


def test_noninteractive_phase_cannot_consume_parent_terminal_input(tmp_path):
    evidence=private_dir(tmp_path/'evidence')
    code='import sys,json;print(json.dumps({"bytes":len(sys.stdin.buffer.read())}))'
    result=execute_once([sys.executable,'-I','-B','-c',code],evidence=evidence,label='no-terminal-input')
    assert result=={'bytes':0}


def test_nonzero_child_is_not_a_success_and_does_not_expose_stderr(tmp_path):
    evidence=private_dir(tmp_path/'evidence')
    code='import sys;sys.stderr.write("private failure detail");raise SystemExit(9)'
    with pytest.raises(PhaseTransportHeld):execute_once([sys.executable,'-I','-B','-c',code],
        evidence=evidence,label='failed-native-child')
    assert b'private failure detail' not in journals(evidence)
    assert json.loads((evidence/'failed-native-child-TRANSPORT-RESULT.json').read_bytes())['exitCode']==9


def test_local_timeout_never_claims_remote_writer_retirement(tmp_path):
    evidence=private_dir(tmp_path/'evidence')
    with pytest.raises(PhaseTransportHeld):execute_once([sys.executable,'-I','-B','-c','import time;time.sleep(10)'],
        evidence=evidence,label='uncertain-transport',timeout=.2)
    proof=json.loads((evidence/'uncertain-transport-TRANSPORT-UNKNOWN.json').read_bytes())
    assert proof['remoteActorRetirement']=='NOT_PROVEN' and proof['automaticRetry'] is False
    with pytest.raises(FileExistsError):execute_once([sys.executable,'-I','-B','-c','print("never")'],
        evidence=evidence,label='uncertain-transport')


def test_master_authority_is_not_inferred_from_existing_deep_approval(tmp_path):
    with pytest.raises(PhaseTransportHeld):NativePhases({},'a'*64,
        {'schema':'deep-prior-grant','owner':'Eddie'},tmp_path)


def test_broader_agent_or_project_contract_refused_before_child_execution(tmp_path):
    authorization={'schema':'onoes-cloud-install-authorization/v1','owner':'Eddie',
        'decision':'approve_cyony_private_home_and_mesh_reader','planSha256':'a'*64}
    plan={'schema':'onoes-cloud-install-window/v1','agentId':'deep','readerPrincipal':'context-cyony',
        'sharedProject':'all-projects','modelCalls':0,'maintenanceTask':'ONOes Mesh Workroom Recovery'}
    with pytest.raises(PhaseTransportHeld):NativePhases(plan,'a'*64,authorization,tmp_path)


# ---- Synthetic coverage of the exact pinned remote SSH recipe ----
# Every path, key, host and plan identity below is a synthetic placeholder. No credential, real
# user path or network route appears here, and execute_once is always monkeypatched away.
import cloud_phase_runner,hashlib,json as _json,shlex

SYNTHETIC_APPROVED_SSH=['ssh','-i','C:/synthetic/key','-T',
    '-o','BatchMode=yes','-o','StrictHostKeyChecking=yes','-o','ForwardAgent=no','-o','ForwardX11=no',
    '-o','ClearAllForwardings=yes','-o','PasswordAuthentication=no','-o','KbdInteractiveAuthentication=no',
    '-o','IdentityAgent=none','-o','IdentitiesOnly=yes','-o','PreferredAuthentications=publickey',
    '-o','UpdateHostKeys=no','-o','UserKnownHostsFile=C:/synthetic/known-hosts','root@100.106.29.72']
SYNTHETIC_PIN=hashlib.sha256(_json.dumps(SYNTHETIC_APPROVED_SSH,separators=(',',':')).encode()).hexdigest()


def ssh_pin(argv):return hashlib.sha256(_json.dumps(argv,separators=(',',':')).encode()).hexdigest()


def remote_plan(ssh_argv):
    """Authorized plan shape with synthetic entries only; the SSH argv is caller-supplied."""
    container='c'*64
    def side(entry):
        return {'entryPath':'/opt/data/synthetic/'+entry,
            'planPath':'/opt/data/synthetic/'+entry.removesuffix('_entry.py')+'-plan.json',
            'planSha256':'b'*64,'authorizationPath':'/opt/data/synthetic/authorization.json'}
    return {'schema':'onoes-cloud-install-window/v1','agentId':'cyony','readerPrincipal':'context-cyony',
        'sharedProject':'onoes-mesh','modelCalls':0,'maintenanceTask':'ONOes Mesh Workroom Recovery',
        'remote':{'sshArgv':ssh_argv,'sshArgvSha256':ssh_pin(ssh_argv),'containerId':container,
            'python':'/opt/hermes/.venv/bin/python3','gateway':side('cloud_gateway_entry.py'),
            'client':side('cloud_client_entry.py')}}


def authorized(remote_plan_body,monkeypatch,evidence):
    """Bind the plan to its own SHA while the independently approved pin stays the fixture value."""
    sha=hashlib.sha256(_json.dumps(remote_plan_body,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    monkeypatch.setattr(cloud_phase_runner,'APPROVED_SSH_SHA256',SYNTHETIC_PIN)
    return NativePhases(remote_plan_body,sha,{'schema':'onoes-cloud-install-authorization/v1','owner':'Eddie',
        'decision':'approve_cyony_private_home_and_mesh_reader','planSha256':sha},evidence)


def recording_execute(monkeypatch):
    calls=[]
    def fake(argv,*,evidence,label,stdin=None,private_stdout=False,timeout=180):
        calls.append({'argv':list(argv),'label':label,'stdin':stdin,'private_stdout':private_stdout,'timeout':timeout})
        return {'synthetic':True,'label':label}
    monkeypatch.setattr(cloud_phase_runner,'execute_once',fake)
    return calls


@pytest.mark.parametrize('kind,phase',(('gateway','verify-stopped'),('client','qualify-held')))
def test_remote_exact_approved_recipe_builds_pinned_command(tmp_path,monkeypatch,kind,phase):
    calls=recording_execute(monkeypatch)
    phases=authorized(remote_plan(list(SYNTHETIC_APPROVED_SSH)),monkeypatch,tmp_path/'evidence')
    result=phases.remote(kind,phase,label=kind+'-'+phase)
    assert result=={'synthetic':True,'label':kind+'-'+phase}
    assert len(calls)==1
    call=calls[0]
    assert call['argv'][:-1]==SYNTHETIC_APPROVED_SSH
    assert call['private_stdout'] is (kind=='client' and phase=='export-curated')
    inner=shlex.split(call['argv'][-1])
    container='c'*64
    entry='/opt/data/synthetic/cloud_%s_entry.py'%kind
    plan_path='/opt/data/synthetic/cloud_%s-plan.json'%kind
    assert inner==['docker','exec','--user','10000:10000','-i',container,'/opt/hermes/.venv/bin/python3',
        '-I','-B',entry,phase,plan_path,'b'*64,'/opt/data/synthetic/authorization.json']


@pytest.mark.parametrize('mangle',('target','strict-host-key','agent-forward','forward-agent-flag','key-path',
    'preferred-auth','update-host-keys','known-hosts','stdin-disabled'))
def test_remote_changed_recipe_cannot_self_authorize(tmp_path,monkeypatch,mangle):
    calls=recording_execute(monkeypatch)
    changed=list(SYNTHETIC_APPROVED_SSH)
    if mangle=='target':changed.insert(1,'-p');changed.insert(2,'22022')  # same host, alternate route/port
    elif mangle=='strict-host-key':changed[changed.index('StrictHostKeyChecking=yes')]='StrictHostKeyChecking=no'
    elif mangle=='agent-forward':changed[changed.index('ForwardAgent=no')]='ForwardAgent=yes'
    elif mangle=='forward-agent-flag':changed.insert(3,'-A')
    elif mangle=='key-path':changed[changed.index('C:/synthetic/key')]='C:/synthetic/other-key'
    elif mangle=='preferred-auth':changed[changed.index('PreferredAuthentications=publickey')]='PreferredAuthentications=password'
    elif mangle=='update-host-keys':changed[changed.index('UpdateHostKeys=no')]='UpdateHostKeys=yes'
    elif mangle=='stdin-disabled':changed.insert(1,'-n')
    elif mangle=='known-hosts':changed[changed.index('UserKnownHostsFile=C:/synthetic/known-hosts')]='UserKnownHostsFile=C:/synthetic/other-known-hosts'
    plan=remote_plan(changed)
    # The caller recomputes its own hash to match the substituted route; the approved fixture pin
    # is independent, so a self-authorized plan hash can never bless a different recipe.
    assert plan['remote']['sshArgvSha256']==ssh_pin(changed)!=SYNTHETIC_PIN
    phases=authorized(plan,monkeypatch,tmp_path/'evidence')
    with pytest.raises(PhaseTransportHeld):phases.remote('gateway','verify-stopped',label='gateway-verify-stopped')
    assert calls==[]


def test_remote_private_input_is_only_for_client_delivery(tmp_path,monkeypatch):
    calls=recording_execute(monkeypatch)
    phases=authorized(remote_plan(list(SYNTHETIC_APPROVED_SSH)),monkeypatch,tmp_path/'evidence')
    marker=b'Harmless private delivery marker'
    with pytest.raises(PhaseTransportHeld):phases.remote('gateway','verify-stopped',label='gateway-stdin',stdin=marker)
    with pytest.raises(PhaseTransportHeld):phases.remote('client','qualify-held',label='client-qualify-stdin',stdin=marker)
    with pytest.raises(PhaseTransportHeld):phases.remote('client','deliver',label='client-oversize-deliver',
        stdin=marker*(8192//len(marker)+1))
    assert calls==[]
    result=phases.remote('client','deliver',label='client-deliver',stdin=marker)
    assert result=={'synthetic':True,'label':'client-deliver'}
    assert len(calls)==1
    assert calls[0]['stdin']==marker
    assert calls[0]['private_stdout'] is False
    evidence=tmp_path/'evidence'
    assert not evidence.exists() or not any(evidence.iterdir())
    assert not [p for p in tmp_path.rglob('*') if p.is_file() and marker in p.read_bytes()]
