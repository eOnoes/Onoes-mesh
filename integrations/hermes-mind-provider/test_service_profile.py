"""Exact inactive startup profile and real owned-process cutover/rollback proof."""
from copy import deepcopy
from dataclasses import asdict,replace
import json
import os
from pathlib import Path
import socket
import sys
import unittest

import pytest

MIND=Path(os.environ['MIND_SOURCE']).resolve()
sys.path.insert(0,str(MIND))
import onoes_mind
from onoes_mind.agent_home import AgentHomeBinding,enroll_agent_home
from onoes_mind.agent_home_http import AgentHomeClient,AgentHomeTransportError,home_binding_sha256
from onoes_mind.recall_binding import RecallBinding
assert Path(onoes_mind.__file__).resolve().parents[1] == MIND
sys.path.insert(0,str(Path(__file__).resolve().parent.parent/'mind-recovery-candidate'))
import project_service_process_candidate as service
import project_operator_process_candidate as operator
import native_project_sync_candidate as native
import test_project_service_process_candidate as fixtures


def synthetic_binding():
    return AgentHomeBinding(RecallBinding(str((MIND/'synthetic.sqlite').resolve()),
        '00000000-0000-0000-0000-000000000001','synthetic-home-profile','fixture:owner',
        'project/onoes-mind/shared',1,2,'fixture:custodian','fixture:revoke','fixture:review'),'echo')


def profile(binding=None):
    return {'schema':service.AGENT_HOME_SCHEMA,'agentHomePort':23456,
            'agentHomeBindings':[asdict(binding or synthetic_binding())]}


def test_exact_approval_matches_the_transport_binding():
    binding=synthetic_binding()
    assert service.home_approval(profile(binding)) == {
        'decision':'approve_exact_private_agent_homes','port':23456,
        'bindings':{'echo':home_binding_sha256(binding)}}


@pytest.mark.parametrize('field,value',[('agentHomePort',0),('agentHomePort',True),('agentHomePort',65536),
    ('agentHomePort','23456'),('agentHomeBindings',[]),('agentHomeBindings',None),
    ('agentHomeBindings',[{'agent_id':'echo','store':{},'scope':'broad'}]),
    ('agentHomeBindings',[{'agent_id':'unknown','store':{}}])])
def test_invalid_home_contract_is_refused(field,value):
    p=profile();p[field]=value
    with pytest.raises(service.ServiceProcessError):service.home_approval(p)


def test_duplicate_or_unsorted_home_ids_are_refused():
    p=profile();row=p['agentHomeBindings'][0]
    for rows in ([row,row],[row,asdict(replace(synthetic_binding(),agent_id='deep'))]):
        p['agentHomeBindings']=rows
        with pytest.raises(service.ServiceProcessError):service.home_approval(p)


def test_home_upgrade_allows_only_the_two_attached_writer_files(tmp_path,monkeypatch):
    old=tmp_path/'old/mind-recovery-candidate';new=tmp_path/'new/mind-recovery-candidate'
    old.mkdir(parents=True);new.mkdir(parents=True)
    monkeypatch.setattr(service,'HERE',new)
    hashes={'project_operator_process_candidate.py':'a'*64,'native_project_sync_candidate.py':'b'*64,
            'project_events_http_candidate.py':'c'*64,'checkpoint_candidate.py':'d'*64}
    original={old/name:value for name,value in hashes.items()}
    replacement={new/name:value for name,value in hashes.items()}
    replacement[new/'native_project_sync_candidate.py']='e'*64
    replacement[new/'project_events_http_candidate.py']='f'*64
    with pytest.raises(service.ServiceProcessError):service.relocate_mesh_source_pins(original,replacement,str(old))
    assert service.relocate_mesh_source_pins(original,replacement,str(old),home_upgrade=True) == {}
    for file in ('project_operator_process_candidate.py','checkpoint_candidate.py'):
        changed={**replacement,new/file:'0'*64}
        with pytest.raises(service.ServiceProcessError):service.relocate_mesh_source_pins(original,changed,str(old),home_upgrade=True)


@pytest.mark.parametrize('field,value',[('database_path','D:/other.sqlite'),('store_id','00000000-0000-0000-0000-000000000002'),
    ('environment','other'),('authority_ref','other'),('file_device',3),('file_inode',4),('scope_id','project/other/shared')])
def test_home_store_cannot_differ_from_existing_project_writer(field,value):
    binding=synthetic_binding()
    changed=replace(binding,store=replace(binding.store,**{field:value}))
    with pytest.raises(service.ServiceProcessError):service.profile_agent_homes(profile(changed),binding.store)


class OwnedHomeServiceTests(unittest.TestCase):
    def setUp(self):
        self.base=fixtures.ProjectServiceProcessTests();self.base.setUp()
        self.addCleanup(self.base.doCleanups)
        # The test owner selects current reviewed source before its synthetic
        # project enrollment. No live runtime or older source checkout is edited.
        owner=self.base.base
        owner.value['runtime']['mindSource']=str(MIND)
        owner.value['sourceHashes']={str(path):operator.digest(path) for path in operator.source_paths(owner.value['runtime'])}
        owner.write()
        self.base.value['operatorProfileSha256']=owner.sha
        self.base.write(actions=['first_setup','run_service'])

    def test_owned_home_start_same_endpoint_restart_and_project_only_rollback(self):
        self.base.prepare()
        owner=self.base.base;binding=owner.value['binding'];root=self.base.profile.parent
        b=RecallBinding(binding['database_path'],binding['store_id'],binding['environment'],binding['authority_ref'],
            'project/onoes-mind/shared',binding['file_device'],binding['file_inode'],
            'fixture:echo-custody','fixture:revoke','fixture:private-home-review')
        home=AgentHomeBinding(b,'echo')
        # Owner enrollment on an exact disposable protected writer, prior to
        # the service launch. The runtime does not provision its own access.
        from persistent_authority import AuthorityBinding,PersistentAuthorityCandidate
        from onoes_mind.runtime_keys import unprotect_runtime_keys
        key_package=json.loads(Path(owner.value['keyEnrollmentPath']).read_bytes())
        keys=unprotect_runtime_keys(key_package['runtime_envelope'],store_id=b.store_id,environment_id=b.environment)
        authority=PersistentAuthorityCandidate(AuthorityBinding(**json.loads(Path(owner.value['authorityBindingPath']).read_bytes())))
        host=native.NativeProjectSyncHost(binding=operator.checked_profile(owner.profile,owner.sha)[1],history_path=owner.value['historyPath'],
            authority=authority,**keys,credential_path=owner.value['credentialPath'],
            project_ids=tuple(row[0] for row in owner.value['projects']),review_ref=owner.value['reviewRef'])
        host.start();tokens=[]
        try:
            with host.writer_lock:
                with host.ledger._transaction(immediate=True):
                    host.ledger.create_principal('operator')
                    host.ledger.issue_credential('operator','synthetic-owner-home-enrollment')
                enroll_agent_home(host.ledger,home,operator_token='synthetic-owner-home-enrollment',
                    save_new_token=lambda token:tokens.append(token) is None)
        finally:host.close()
        token=tokens[0]
        view_path=root/'private-home-runtime.json'
        view_path.write_text(json.dumps(owner.value,separators=(',',':')),encoding='utf-8')
        with socket.socket() as reservation:
            reservation.bind(('127.0.0.1',0));port=reservation.getsockname()[1]
        p=self.base.value
        p.update(schema=service.AGENT_HOME_SCHEMA,serviceRuntimeProfilePath=str(view_path),
            serviceRuntimeProfileSha256=service.digest(view_path),enrolledMeshSourceDirectory=str(service.HERE),
            agentHomeBindings=[asdict(home)],agentHomePort=port)
        self.base.write(actions=['run_service','run_agent_homes'])
        decision=json.loads(owner.approval.read_bytes());decision['agentHomes']=service.home_approval(p)
        owner.approval.write_text(json.dumps(decision),encoding='utf-8')
        no_home=deepcopy(decision);no_home['actions']=['run_service']
        owner.approval.write_text(json.dumps(no_home),encoding='utf-8')
        with self.assertRaises(service.ServiceProcessError):service.checked_profile(self.base.profile,self.base.sha,owner.approval)
        self.assertFalse(Path(p['attemptPath']).exists())
        owner.approval.write_text(json.dumps(decision),encoding='utf-8')
        endpoint=f'http://127.0.0.1:{port}'
        client=AgentHomeClient(endpoint,agent_id='echo',binding_sha256=home_binding_sha256(home),credential_provider=lambda:token,timeout=10)
        receipts=[]
        for iteration in range(2):
            child,stamp=service.launch_service(self.base.profile,self.base.sha,owner.approval)
            self.base.children.append((child,stamp))
            state=self.base.ready(child)
            self.assertEqual(state['agentHomes'],{'baseUrl':endpoint,'agents':{'echo':home_binding_sha256(home)}})
            if iteration==0:
                saved=client.call('remember',{'event_id':'echo-profile-live-copy','kind':'profile','text':'Echo selected concise preference'})
                receipts.append(self.base.send(service.native_options(self.base.profile,self.base.sha,owner.approval)))
            row,=client.call('recall',{'query':'concise'})['records']
            self.assertEqual(row['record_id'],saved['record_id'])
            service.request_stop(self.base.profile,self.base.sha,owner.approval)
            self.assertEqual(child.wait(timeout=120),0)
        # Roll back the runtime surface with original project grants/custody;
        # private records remain durable and private access is simply off.
        p['schema']=service.RELOCATED_RUNTIME_SCHEMA
        for key in ('agentHomeBindings','agentHomePort','enrolledMeshSourceDirectory'):p.pop(key)
        for key in ('attemptPath','readyPath','stopPath'):p[key]=str(root/('rollback-'+key+'.json'))
        self.base.profile=root/'project-only-rollback.json'
        self.base.write(actions=['run_service'])
        decision=json.loads(owner.approval.read_bytes());decision.pop('agentHomes',None)
        owner.approval.write_text(json.dumps(decision),encoding='utf-8')
        child,stamp=service.launch_service(self.base.profile,self.base.sha,owner.approval)
        self.base.children.append((child,stamp));state=self.base.ready(child)
        self.assertNotIn('agentHomes',state)
        with self.assertRaises(AgentHomeTransportError):client.call('recall',{'query':'concise'})
        replay=self.base.send(service.native_options(self.base.profile,self.base.sha,owner.approval))
        self.assertEqual(replay['receiptId'],receipts[0]['receiptId'])
        service.request_stop(self.base.profile,self.base.sha,owner.approval)
        self.assertEqual(child.wait(timeout=120),0)
