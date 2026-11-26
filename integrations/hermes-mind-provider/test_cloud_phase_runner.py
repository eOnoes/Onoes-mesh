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
