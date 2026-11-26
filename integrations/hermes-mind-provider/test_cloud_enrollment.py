"""Synthetic-only SDK enrollment and exact-attempt revocation qualification."""
from copy import deepcopy
from contextlib import closing
from dataclasses import replace
import os
from pathlib import Path
import sys

import pytest

MIND=Path(os.environ['MIND_SOURCE'])
sys.path[:0]=[str(MIND),str(MIND/'tests')]
from test_agent_context import context_store
from onoes_mind.agent_home import AgentHome,AgentHomeBinding
from onoes_mind.agent_context import AgentContextBinding,ProjectContextReader
from onoes_mind.ledger import LedgerError
from cloud_enrollment import EnrollmentHold,enroll,revoke_new


def test_unprepared_recall_store_refuses_before_any_private_grant_or_custody(tmp_path):
    import secrets
    from onoes_mind import Ledger
    from onoes_mind.recall_binding import RecallBinding,prepare_store_identity
    path=tmp_path/'fresh-canonical.sqlite'
    with closing(Ledger(path,environment_id='synthetic-fresh',audit_key=secrets.token_bytes(32),
                        deletion_key=secrets.token_bytes(32))) as writer:
        writer.create_principal('operator');writer.issue_credential('operator','synthetic-operator')
        writer.create_principal('echo');writer.issue_credential('echo','synthetic-prior-echo')
        store_id=prepare_store_identity(writer,environment='synthetic-fresh',authority_ref='fixture:owner')
        info=path.stat()
        store=RecallBinding(str(path),store_id,'synthetic-fresh','fixture:owner','project/onoes-mind/shared',
            info.st_dev,info.st_ino,'fixture:custodian','fixture:revoke','fixture:review')
        pair=(writer,AgentHomeBinding(store,'cyony'),AgentContextBinding(store,'context-cyony','onoes-mesh'))
        assert not writer.db.execute("SELECT 1 FROM sqlite_master WHERE name='recall_service_credentials'").fetchone()
        saved=[]
        with pytest.raises(EnrollmentHold):
            enroll(writer,pair[1],pair[2],operator_token='synthetic-operator',attempt_id='synthetic-cloud-unprepared',
                review_sha256='a'*64,save_home_token=lambda t:saved.append(t) or True,
                save_reader_token=lambda t:saved.append(t) or True,persist_receipt=lambda r:saved.append(r) or True)
        assert saved==[]
        assert not writer.db.execute("SELECT 1 FROM principals WHERE principal_id IN ('cyony','context-cyony')").fetchone()
        assert not writer.db.execute("SELECT 1 FROM sqlite_master WHERE name='recall_service_credentials'").fetchone()
        assert writer.authenticate('synthetic-prior-echo')=='echo'


@pytest.fixture
def setup(context_store):
    writer,store,_,_=context_store
    return writer,AgentHomeBinding(store,'cyony'),AgentContextBinding(store,'context-cyony','onoes-mesh')


def admit(setup,*,save_reader=None,persist=None):
    writer,home,reader=setup;tokens={};receipts=[]
    def save(name,token):tokens[name]=token;return True
    def record(receipt):receipts.append(deepcopy(receipt));return True
    result=enroll(writer,home,reader,operator_token='synthetic-operator',attempt_id='synthetic-cloud-1',
        review_sha256='a'*64,save_home_token=lambda t:save('home',t),
        save_reader_token=save_reader or (lambda t:save('reader',t)),persist_receipt=persist or record)
    return tokens,receipts,result


def revoke(setup,receipts,**changes):
    writer,home,reader=setup
    args=dict(operator_token='synthetic-operator',attempt_id='synthetic-cloud-1',review_sha256='a'*64,receipts=receipts)
    args.update(changes)
    return revoke_new(writer,home,reader,**args)


def test_fresh_scoped_pair_private_save_shared_read_then_exact_revocation_preserves_old_agents(setup):
    writer,home,reader=setup;tokens,receipts,result=admit(setup)
    assert list(result)==receipts and not any(t in str(receipts) for t in tokens.values())
    private=AgentHome(writer,home)
    saved=private.remember(tokens['home'],event_id='private-cloud',text='Synthetic harbor note')
    shared=writer.remember('synthetic-operator',{'event_id':'cloud-shared','kind':'project_fact',
        'project_id':'onoes-mesh','claim':'Synthetic shared harbor','requested_visibility':'shared'})
    with closing(ProjectContextReader(home.store.database_path,binding=reader)) as read:
        row,=read.read_context(tokens['reader'],{'query':'harbor'})['records']
        assert row['record_id']==shared['record_id']
        outcome=revoke(setup,receipts)
        assert outcome['revokedPrincipals']==['cyony','context-cyony']
        with pytest.raises(LedgerError):read.check_access(tokens['reader'])
    with pytest.raises(LedgerError):private.recall(tokens['home'],{})
    assert writer.authenticate('synthetic-private-writer')=='echo'
    assert writer.authenticate('synthetic-operator')=='operator'
    assert writer.db.execute('SELECT 1 FROM memory_records WHERE record_id=?',(saved['record_id'],)).fetchone()
    with pytest.raises(EnrollmentHold):revoke(setup,receipts)


@pytest.mark.parametrize('existing',['cyony','context-cyony'])
def test_preexisting_identity_refuses_before_any_custody_or_new_principal(setup,existing):
    writer,_,_=setup
    if existing=='cyony':writer.create_principal(existing)
    else:writer.db.execute("INSERT INTO principals(principal_id,kind) VALUES (?, 'service')",(existing,))
    before=writer.db.total_changes
    with pytest.raises(EnrollmentHold):admit(setup)
    assert writer.db.total_changes==before


def test_reader_custody_failure_keeps_only_first_receipt_and_refuses_blind_reenrollment(setup):
    writer,home,_=setup;receipts=[]
    def persist(r):receipts.append(r);return True
    with pytest.raises(LedgerError):admit(setup,save_reader=lambda _:False,persist=persist)
    assert [r['principal'] for r in receipts]==['cyony']
    assert not writer.db.execute("SELECT 1 FROM principals WHERE principal_id='context-cyony'").fetchone()
    with pytest.raises(EnrollmentHold):admit(setup)
    assert revoke(setup,receipts)['revokedPrincipals']==['cyony']


def test_receipt_acknowledgement_failure_stops_before_second_identity(setup):
    writer,_,_=setup;receipts=[]
    def uncertain(r):receipts.append(r);return False
    with pytest.raises(EnrollmentHold):admit(setup,persist=uncertain)
    assert len(receipts)==1
    assert not writer.db.execute("SELECT 1 FROM principals WHERE principal_id='context-cyony'").fetchone()
    assert revoke(setup,receipts)['revokedPrincipals']==['cyony']


@pytest.mark.parametrize('changed',['credential','grant','receipt','attempt','project'])
def test_changed_state_or_receipt_refuses_entire_revocation_without_touching_either_identity(setup,changed):
    writer,home,reader=setup;tokens,receipts,_=admit(setup);args={}
    if changed=='credential':writer.issue_credential('cyony','synthetic-replacement')
    elif changed=='grant':writer.db.execute("UPDATE scope_grants SET can_write=1 WHERE principal_id='context-cyony'")
    elif changed=='receipt':receipts[1]['stateSha256']='0'*64
    elif changed=='attempt':args['attempt_id']='another-attempt'
    else:setup=(writer,home,replace(reader,project_id='another-project'))
    epochs=[tuple(r) for r in writer.db.execute("SELECT principal_id,credential_epoch FROM principals WHERE principal_id IN ('cyony','context-cyony') ORDER BY principal_id")]
    with pytest.raises(EnrollmentHold):revoke(setup,receipts,**args)
    assert [tuple(r) for r in writer.db.execute("SELECT principal_id,credential_epoch FROM principals WHERE principal_id IN ('cyony','context-cyony') ORDER BY principal_id")]==epochs
