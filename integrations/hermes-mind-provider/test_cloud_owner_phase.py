"""Actual Windows private custody around disposable cloud enrollment/import."""
import os
from pathlib import Path
import sys

import pytest

MIND=Path(os.environ['MIND_SOURCE']);sys.path[:0]=[str(MIND),str(MIND/'tests')]
from test_agent_context import context_store
from test_cloud_curated_transfer import private_dir,sources,snapshot
from onoes_mind.agent_home import AgentHome,AgentHomeBinding,WindowsAgentHomeCustody
from onoes_mind.agent_context import AgentContextBinding
from onoes_mind.context_host import WindowsReaderCustody
from onoes_mind.ledger import LedgerError
from cloud_curated_transfer import stage
from cloud_owner_phase import admit,revoke

pytestmark=pytest.mark.skipif(os.name!='nt',reason='Real Windows DPAPI/private ACL owner operation')


def owner(context_store,tmp_path):
    writer,store,_,_=context_store;home=AgentHomeBinding(store,'cyony')
    reader=AgentContextBinding(store,'context-cyony','onoes-mesh')
    private=WindowsAgentHomeCustody(private_dir(tmp_path/'private-custody'),home)
    shared=WindowsReaderCustody(private_dir(tmp_path/'shared-custody'),reader)
    evidence=private_dir(tmp_path/'owner-evidence')
    options=dict(operator_token='synthetic-operator',evidence=evidence,
        attempt_id='synthetic-windows-cloud-owner',review_sha256='b'*64)
    return writer,home,reader,private,shared,options


def test_actual_dpapi_owner_enrollment_curated_import_readback_and_receipted_revoke(context_store,sources,tmp_path):
    writer,home,reader,private,shared,options=owner(context_store,tmp_path)
    snap=snapshot(sources);root=private_dir(tmp_path/'curated-stage');private_dir(root/'memories')
    prepared=stage(snap,root,home)
    result=admit(writer,home,reader,private,shared,**options,prepared_curated=prepared,remote_origin=snap.descriptor())
    assert result['curatedImported'] is True and result['remoteDelivery'] is False
    row,=AgentHome(writer,home).recall(private.read(),{'kind':'profile','max_bytes':16384})['records']
    assert row['claim']==prepared.text
    # Receipt/evidence and encrypted custody must not contain either token or notes.
    for path in (options['evidence']).iterdir():
        raw=path.read_bytes()
        assert private.read().encode() not in raw and shared.read().encode() not in raw
        assert b'Synthetic print plan' not in raw
    assert private.read().encode() not in private.path.read_bytes()
    assert shared.read().encode() not in shared.path.read_bytes()
    outcome=revoke(writer,home,reader,private,shared,**options)
    assert outcome['revokedPrincipals']==['cyony','context-cyony']
    assert writer.authenticate('synthetic-private-writer')=='echo'
    assert writer.db.execute('SELECT 1 FROM memory_records WHERE record_id=?',(row['record_id'],)).fetchone()
    for name,raw in snap.files.items():assert (sources[0]/'memories'/name).read_bytes()==raw


def test_lost_reader_custody_ack_keeps_private_evidence_and_scoped_revoke(context_store,tmp_path,monkeypatch):
    writer,home,reader,private,shared,options=owner(context_store,tmp_path)
    monkeypatch.setattr(shared,'save_new',lambda _:False)
    with pytest.raises(LedgerError):admit(writer,home,reader,private,shared,**options)
    assert (options['evidence']/'ENROLLED-cyony.json').is_file()
    assert not (options['evidence']/'ENROLLED-context-cyony.json').exists()
    assert private.path.is_file() and not shared.path.exists()
    assert revoke(writer,home,reader,private,shared,**options)['revokedPrincipals']==['cyony']
    assert writer.authenticate('synthetic-private-writer')=='echo'
