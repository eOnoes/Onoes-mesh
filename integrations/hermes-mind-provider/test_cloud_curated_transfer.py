"""Synthetic saved-note transfer into supported canonical import, no real data."""
from dataclasses import replace
import os
from pathlib import Path
import sys

import pytest

MIND=Path(os.environ['MIND_SOURCE']);sys.path[:0]=[str(MIND),str(MIND/'tests')]
from test_agent_context import context_store
from onoes_mind.agent_home import AgentHome,AgentHomeBinding,enroll_agent_home
from onoes_mind.curated_home_import import import_curated_home
from cloud_curated_transfer import TransferHold,capture,encode,decode,stage,identity,sha


def private_dir(path):
    path.mkdir(mode=0o700)
    if os.name=='nt':
        # Use the same actual private-directory fixture as existing Mind tests.
        from test_enrollment_store import _CREATE
        import subprocess,shutil
        script=path.parent/(path.name+'-acl.ps1')
        # Set-Acl requests audit privileges in this host. Persist only the owner
        # and DACL sections actually changed, using .NET's normal owned-folder
        # API. The production read-only exact-ACL check stays unchanged.
        script.write_text(_CREATE.replace('Set-Acl -LiteralPath $Path -AclObject $acl',
            '[IO.FileSystemAclExtensions]::SetAccessControl([IO.DirectoryInfo]::new($Path),$acl)'))
        result=subprocess.run([shutil.which('pwsh') or 'powershell','-NoProfile','-NonInteractive',
            '-File',str(script),'-Path',str(path)],capture_output=True,
            creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        assert result.returncode==0
        script.unlink()  # Only this fixture-created script; keep source/staging empty.
    return path


@pytest.fixture
def sources(tmp_path):
    root=private_dir(tmp_path/'source');private_dir(root/'memories')
    for name,text in [('MEMORY.md','Synthetic print plan is revision seven.'),('USER.md','Prefer concise build updates.')]:
        path=root/'memories'/name;path.write_text(text);path.chmod(0o600)
    expected={p.name:identity(p.stat()) for p in (root/'memories').iterdir()}
    return root,expected


def snapshot(sources):
    root,expected=sources
    return capture(root,origin='srv1693050/cyony-hermes',expected_identities=expected)


def test_roundtrip_stage_import_readback_and_same_event_replay_preserve_originals(sources,context_store,tmp_path):
    writer,store,_,_=context_store;home=AgentHomeBinding(store,'cyony');tokens=[]
    enroll_agent_home(writer,home,operator_token='synthetic-operator',save_new_token=lambda t:tokens.append(t) or True)
    snap=snapshot(sources);raw=encode(snap);restored=decode(raw,expected_sha256=sha(raw))
    assert 'Synthetic print plan' not in str(snap) and snap.descriptor()['privateTextIncluded'] is False
    stage_root=private_dir(tmp_path/'canonical-private-stage')
    private_dir(stage_root/'memories')
    prepared=stage(restored,stage_root,home)
    result=import_curated_home(writer,home,operator_token='synthetic-operator',home_token=tokens[0],prepared=prepared)
    assert result['source_files_changed'] is False
    record,=AgentHome(writer,home).recall(tokens[0],{'kind':'profile','max_bytes':16384})['records']
    assert record['claim']==prepared.text and record['provenance']
    assert 'MEMORY.md; raw SHA256 '+snap.metadata['MEMORY.md']['sha256'] in record['claim']
    assert import_curated_home(writer,home,operator_token='synthetic-operator',home_token=tokens[0],prepared=prepared)['receipt']==result['receipt']
    for name,value in snap.files.items():assert (sources[0]/'memories'/name).read_bytes()==value
    with pytest.raises(TransferHold):stage(restored,stage_root,home)


@pytest.mark.parametrize('case',['changed-source','wrong-origin','bad-transport','tampered-payload'])
def test_changed_sources_or_transport_are_refused(sources,tmp_path,case):
    if case=='changed-source':
        (sources[0]/'memories/MEMORY.md').write_text('Changed after the approved snapshot')
        with pytest.raises(TransferHold):snapshot(sources)
    elif case=='wrong-origin':
        with pytest.raises(TransferHold):capture(sources[0],origin='another-agent',expected_identities=sources[1])
    else:
        snap=snapshot(sources);raw=encode(snap)
        if case=='bad-transport':
            with pytest.raises(TransferHold):decode(raw,expected_sha256='0'*64)
        else:
            import json,base64
            body=json.loads(raw);body['files']['USER.md']=base64.b64encode(b'Changed').decode()
            changed=json.dumps(body).encode()
            with pytest.raises(TransferHold):decode(changed,expected_sha256=sha(changed))


@pytest.mark.parametrize('text',['api_key=synthetic_credential_like_value','x'*7100])
def test_credential_like_or_over_budget_curated_text_is_not_transferred(sources,text):
    path=sources[0]/'memories/MEMORY.md';path.write_text(text)
    sources[1]['MEMORY.md']=identity(path.stat())
    with pytest.raises(TransferHold):snapshot(sources)
