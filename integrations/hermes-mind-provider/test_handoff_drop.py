"""Owner JSON client qualification with disposable custody, no live credentials."""
from dataclasses import asdict
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

MIND=Path(os.environ['MIND_SOURCE']).resolve();sys.path[:0]=[str(MIND),str(MIND/'tests')]
ENTRY=Path(os.environ['MESH_SOURCE'])/'integrations/mind-recovery-candidate/handoff_drop_candidate.py'
spec=importlib.util.spec_from_file_location('qualified_handoff_drop',ENTRY)
drop=importlib.util.module_from_spec(spec);sys.modules[spec.name]=drop;spec.loader.exec_module(drop)
from test_handoff_channel import online
from test_agent_handoff import handoff
from test_agent_context import context_store
from test_enrollment_store import _CREATE
from onoes_mind.context_enrollment import WindowsOperatorCustody
from onoes_mind.handoff_channel import HandoffTransportError


@pytest.fixture
def local(online,tmp_path):
    writer,server,client,token,payload,_,_=online
    root=tmp_path/'owner-client';custody=root/'custody';inputs=root/'inputs';journal=root/'journal'
    for path in (root,custody,inputs,journal):path.mkdir()
    script=tmp_path/'private-fixture.ps1';script.write_text(_CREATE)
    for path in (root,custody,inputs,journal):
        subprocess.run([shutil.which('pwsh'),'-NoProfile','-NonInteractive','-File',str(script),'-Path',str(path)],
            check=True,capture_output=True,timeout=20,creationflags=subprocess.CREATE_NO_WINDOW)
    bound=server.handoff_channel.binding
    WindowsOperatorCustody(custody,bound.store).save_new(token)
    profile=root/'profile.json'
    body={'schema':drop.SCHEMA,'mindSource':str(MIND),
        'sourceHashes':{str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in drop.source_paths(MIND)},
        'binding':asdict(bound),'endpoint':server.base_url,'custodyDirectory':str(custody),
        'inputDirectory':str(inputs),'journalDirectory':str(journal),'reviewRef':payload['review_ref']}
    profile.write_bytes(drop.canonical(body));pin=hashlib.sha256(profile.read_bytes()).hexdigest()
    source=inputs/'handoff-r2.json';source.write_bytes(drop.canonical(payload))
    loaded=drop.load_profile(profile,pin)
    return writer,server,loaded,source,body,journal


def test_isolated_preview_needs_neither_credentials_nor_a_running_service(local):
    _,server,p,_,_,journal=local
    credential=Path(p.body['custodyDirectory'])/'operator.dpapi';parked=credential.with_suffix('.parked')
    credential.rename(parked);server.close()
    before_caches=set((MIND/'onoes_mind').rglob('*.pyc'))
    result=subprocess.run([sys.executable,'-I',str(ENTRY),'--profile',str(p.path),'--sha256',p.sha256,'--preview'],
        capture_output=True,text=True,timeout=60,creationflags=subprocess.CREATE_NO_WINDOW)
    assert result.returncode==0,result.stdout
    assert json.loads(result.stdout)=={'profileVerified':True,'recordId':p.binding.record_id,
        'projectId':p.binding.project_id,'credentialRead':False,'memoryWritten':False}
    assert list(journal.iterdir())==[]
    assert set((MIND/'onoes_mind').rglob('*.pyc'))==before_caches


def test_isolated_publish_and_read_use_sealed_custody_without_secret_output(local):
    writer,_,p,source,_,_=local
    command=[sys.executable,'-I','-B',str(ENTRY),'--profile',str(p.path),'--sha256',p.sha256]
    sent=subprocess.run([*command,'--publish',str(source)],capture_output=True,text=True,timeout=60,creationflags=subprocess.CREATE_NO_WINDOW)
    assert sent.returncode==0,sent.stdout
    result=json.loads(sent.stdout);assert result['status']=='acknowledged' and result['receipt']['durable']
    assert 'omop1_' not in sent.stdout+sent.stderr
    readback=subprocess.run([*command,'--read'],capture_output=True,text=True,timeout=60,creationflags=subprocess.CREATE_NO_WINDOW)
    assert readback.returncode==0,readback.stdout
    current=json.loads(readback.stdout)
    assert current['document']['revision']==2 and current['document']['next_action']=='Build newharbor'
    assert current['record_id']==result['receipt']['record_id']
    duplicate=subprocess.run([*command,'--publish',str(source)],capture_output=True,text=True,timeout=60,creationflags=subprocess.CREATE_NO_WINDOW)
    assert duplicate.returncode==1 and json.loads(duplicate.stdout)['status']=='held'
    assert writer.db.execute("SELECT count(*) FROM submission_events WHERE event_id='handoff-update-2'").fetchone()[0]==1


def test_publish_once_records_metadata_only_and_cached_receipt_is_never_current_state(local,monkeypatch):
    writer,_,p,source,_,journal=local
    first=drop.publish(p,source)
    assert first['status']=='acknowledged' and first['receipt']['durable']
    assert first['currentStateVerified'] is False
    with pytest.raises((OSError,ValueError)):drop.publish(p,source)
    def forbidden(*args,**kwargs):raise AssertionError('cached acknowledgement must not send')
    monkeypatch.setattr(p.client,'call',forbidden)
    cached=drop.publish(p,source,reconcile=True)
    assert cached['status']=='already_acknowledged' and cached['receipt']==first['receipt']
    assert cached['currentStateVerified'] is False
    assert writer.db.execute("SELECT count(*) FROM submission_events WHERE event_id='handoff-update-2'").fetchone()[0]==1
    for path in journal.iterdir():
        raw=path.read_text()
        assert 'newharbor' not in raw and 'omop1_' not in raw and 'synthetic-operator' not in raw


def test_lost_reply_requires_explicit_same_payload_reconciliation(local,monkeypatch):
    writer,_,p,source,_,journal=local
    real=p.client.call;sent=[]
    def uncertain(action,value):
        sent.append(True);real(action,value)
        raise HandoffTransportError('transport_unavailable',outcome_uncertain=True)
    monkeypatch.setattr(p.client,'call',uncertain)
    first=drop.publish(p,source)
    assert first=={'status':'outcome_unconfirmed','eventId':'handoff-update-2','automaticRetry':False}
    assert sent==[True] and len(list(journal.iterdir()))==1
    assert real('read',{})['document']['revision']==2
    monkeypatch.setattr(p.client,'call',real)
    second=drop.publish(p,source,reconcile=True)
    assert second['status']=='acknowledged'
    assert writer.db.execute("SELECT count(*) FROM submission_events WHERE event_id='handoff-update-2'").fetchone()[0]==1


def test_changed_input_cannot_reconcile_an_uncertain_operation(local,monkeypatch):
    _,_,p,source,_,journal=local
    calls=[]
    def uncertain(*args,**kwargs):
        calls.append(True);raise HandoffTransportError('transport_unavailable',outcome_uncertain=True)
    monkeypatch.setattr(p.client,'call',uncertain)
    drop.publish(p,source)
    value=json.loads(source.read_bytes());value['document']['next_action']='Different future action';source.write_bytes(drop.canonical(value))
    with pytest.raises(ValueError):drop.publish(p,source,reconcile=True)
    assert calls==[True] and len(list(journal.iterdir()))==1


def test_wrong_record_receipt_in_local_journal_is_not_accepted(local):
    _,_,p,source,_,journal=local
    drop.publish(p,source)
    receipt,=journal.glob('*.receipt.json');value=json.loads(receipt.read_bytes());value['record_id']='rec_other'
    receipt.write_bytes(drop.canonical(value))
    with pytest.raises(ValueError):drop.publish(p,source,reconcile=True)


def test_unreviewed_source_and_input_outside_selected_folder_are_refused(local,tmp_path):
    _,_,p,source,body,journal=local
    outside=tmp_path/'outside.json';outside.write_bytes(source.read_bytes())
    with pytest.raises(ValueError):drop.publish(p,outside)
    changed={**body,'sourceHashes':{**body['sourceHashes'],str(ENTRY):'0'*64}}
    p.path.write_bytes(drop.canonical(changed));pin=hashlib.sha256(p.path.read_bytes()).hexdigest()
    with pytest.raises(ValueError):drop.load_profile(p.path,pin)
    aliased={**body,'inputDirectory':body['custodyDirectory'].upper()}
    p.path.write_bytes(drop.canonical(aliased));pin=hashlib.sha256(p.path.read_bytes()).hexdigest()
    with pytest.raises(ValueError):drop.load_profile(p.path,pin)
    assert list(journal.iterdir())==[]


def test_another_project_or_secret_is_rejected_before_any_intent_or_credential_read(local,monkeypatch):
    _,_,p,source,_,journal=local
    def forbidden(*args,**kwargs):raise AssertionError('invalid input must not send')
    monkeypatch.setattr(p.client,'call',forbidden)
    value=json.loads(source.read_bytes())
    for document in ({**value['document'],'project_id':'another-project'},
                     {**value['document'],'next_action':'sk-'+'x'*24}):
        source.write_bytes(drop.canonical({**value,'document':document}))
        with pytest.raises(ValueError):drop.publish(p,source)
    assert list(journal.iterdir())==[]
