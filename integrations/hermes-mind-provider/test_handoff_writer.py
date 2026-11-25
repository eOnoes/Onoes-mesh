"""Inactive record refresh over the actual protected writer, disposable data only."""
from dataclasses import asdict,replace
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import unittest
from unittest.mock import patch

import pytest

MIND=Path(os.environ['MIND_SOURCE']).resolve();sys.path.insert(0,str(MIND))
from onoes_mind.handoff_channel import HandoffBinding,HandoffClient,HandoffTransportError,handoff_binding_sha256
from onoes_mind.agent_context import AgentContextBinding,ProjectContextReader
from onoes_mind.context_enrollment import enroll_context_reader
from onoes_mind.recall_binding import prepare_mesh_principal
sys.path[:0]=[str(Path(os.environ['MESH_SOURCE'])/'integrations/mind-recovery-candidate'),
             str(Path(os.environ['MESH_SOURCE'])/'integrations/hermes-mind-provider')]
import native_project_sync_candidate as native
import project_service_process_candidate as service
import test_writer_host as homes
import test_service_profile as profiles
from test_project_events_candidate import event


def selected():
    home=profiles.synthetic_binding()
    return HandoffBinding(home.store,'rec_fixture','nims/fixture-one/build','fixture-one','nims')


def version_six(binding=None):
    value=profiles.profile();value.update(schema=service.HANDOFF_SCHEMA,handoffBinding=asdict(binding or selected()))
    return value


def test_descriptor_matches_the_sdk_and_requires_explicit_version_six():
    p=version_six();b=selected();descriptor=service.handoff_approval(p)
    assert descriptor==dict(decision='approve_exact_owner_handoff_refresh',port=p['agentHomePort'],
        bindingSha256=handoff_binding_sha256(b),recordId=b.record_id,projectId=b.project_id,author='nims')
    assert service.profile_handoff(p,b.store,{'projects':[['fixture-one','Fixture']]})==b
    with pytest.raises(service.ServiceProcessError):service.handoff_approval(profiles.profile())
    assert service.profile_handoff(profiles.profile(),b.store,{'projects':[['fixture-one','Fixture']]}) is None


@pytest.mark.parametrize('change',[
    {'handoffBinding':None},{'handoffBinding':{}},{'agentHomeBindings':[]},{'agentHomePort':0},
    {'handoffBinding':{**asdict(selected()),'record_id':''}},
    {'handoffBinding':{**asdict(selected()),'scope_id':'private'}},
    {'handoffBinding':{**asdict(selected()),'author':'unknown'}},
])
def test_incomplete_or_implicit_target_never_qualifies(change):
    p={**version_six(),**change}
    with pytest.raises((service.ServiceProcessError,ValueError)):service.handoff_approval(p)


@pytest.mark.parametrize('field,value',[('database_path','D:/other.sqlite'),('store_id','00000000-0000-0000-0000-000000000002'),
    ('authority_ref','other-owner'),('file_inode',500),('scope_id','project/other/shared')])
def test_handoff_cannot_bind_to_another_store(field,value):
    bound=selected();p=version_six(replace(bound,store=replace(bound.store,**{field:value})))
    with pytest.raises(service.ServiceProcessError):service.profile_handoff(p,bound.store,{'projects':[['fixture-one','Fixture']]})


def test_handoff_project_must_already_be_in_existing_writer_projects():
    b=selected()
    with pytest.raises(service.ServiceProcessError):service.profile_handoff(version_six(),b.store,{'projects':[['other','Other']]})


class ProtectedWriterHandoffTests(unittest.TestCase):
    def setUp(self):
        self.base=homes.SharedWriterHomeTests();self.base.setUp();self.addCleanup(self.base.doCleanups)
        host=self.base.host();host.start();self.owner_token='omop1_'+'A'*43
        self.document={'schema':'onoes-handoff/v1','handoff_id':'nims/project-A/current-build',
            'project_id':'project-A','author':'nims','revision':1,'next_action':'Inspect oldlighthouse'}
        with host.writer_lock:
            host.ledger.issue_credential('operator',self.owner_token)
            receipt=host.ledger.remember(self.owner_token,{'event_id':'handoff-admitted','claim':json.dumps(self.document),
                'kind':'project_fact','project_id':'project-A','requested_visibility':'shared','source_class':'agent_handoff',
                'evidence_refs':[{'type':'agent_handoff','ref':'handoff:nims/project-A/current-build@1','content_hash':'a'*64}]})
            self.binding=HandoffBinding(self.base.home_binding.store,receipt['record_id'],self.document['handoff_id'],'project-A','nims')
            prepare_mesh_principal(host.ledger,scope_id=self.binding.store.scope_id)
            tokens=[]
            self.context_binding=AgentContextBinding(self.binding.store,'context-echo','project-A')
            enroll_context_reader(host.ledger,self.context_binding,operator_token=self.owner_token,
                save_new_token=lambda token:tokens.append(token) is None)
            self.context_token=tokens[0]
        host.close()

    def host(self,binding=True):
        base=self.base.base
        host=native.NativeProjectSyncHost(binding=base.events.binding,history_path=base.fixture.history,
            authority=base.fixture.authority,**base.fixture.keys,credential_path=base.path,
            project_ids=base.options['project_ids'],review_ref=base.options['review_ref'],
            agent_home_bindings=(self.base.home_binding,),handoff_binding=self.binding if binding is True else binding)
        self.addCleanup(host.close);return host

    def client(self,host):
        data=host.handoff_options()
        return HandoffClient(data['baseUrl'],binding_sha256=data['bindingSha256'],record_id=data['recordId'],credential_provider=lambda:self.owner_token,timeout=15)

    def test_shared_lock_current_recall_restart_purge_and_disable_preserve_existing_interfaces(self):
        host=self.host();host.start();client=self.client(host)
        self.assertIs(host.home_server._lock,host.writer_lock)
        self.assertIs(host.home_server.handoff_channel.ledger,host.ledger)
        private_saved=self.base.client(host).call('remember',{'event_id':'private-cabin','text':'Private cabin preference remains private'})
        current=client.call('read',{})
        payload={'expected_revision_id':current['revision_id'],'event_id':'handoff-second',
            'document':{**self.document,'revision':2,'next_action':'Build newharbor'},'review_ref':'owner:fixture-handoff'}
        reader=ProjectContextReader(self.binding.store.database_path,binding=self.context_binding);self.addCleanup(reader.close)
        entered,release,project_entered=threading.Event(),threading.Event(),threading.Event()
        revise=host.home_server.handoff_channel.revise;submit=host.events.submit;results={};errors=[]
        project_options=host.native_options()
        def hold_revision(*args,**kwargs):
            entered.set()
            if not release.wait(10):raise RuntimeError('fixture release missing')
            return revise(*args,**kwargs)
        def observe_submit(*args,**kwargs):project_entered.set();return submit(*args,**kwargs)
        def run(name,fn):
            try:results[name]=fn()
            except Exception as error:errors.append(error)
        with patch.object(host.home_server.handoff_channel,'revise',hold_revision),patch.object(host.events,'submit',observe_submit):
            first=threading.Thread(target=run,args=('handoff',lambda:client.call('revise',payload)))
            second=threading.Thread(target=run,args=('project',lambda:self.base.project_call(project_options,event())))
            first.start()
            try:self.assertTrue(entered.wait(10));second.start();self.assertFalse(project_entered.wait(.2))
            finally:release.set();first.join(25);second.join(25)
        self.assertFalse(first.is_alive() or second.is_alive());self.assertEqual(errors,[])
        self.assertTrue(results['handoff']['durable']);self.assertTrue(project_entered.is_set())
        self.assertEqual(reader.read_context(self.context_token,{'query':'oldlighthouse'})['records'],[])
        row,=reader.read_context(self.context_token,{'query':'newharbor'})['records']
        self.assertEqual(json.loads(row['claim']),payload['document'])
        self.assertEqual(client.call('read',{})['revision_id'],row['revision_id'])
        host.close();reopened=self.host();reopened.start();second=self.client(reopened)
        self.assertEqual(second.call('revise',payload),results['handoff'])
        self.assertEqual(second.call('read',{})['document'],payload['document'])
        self.assertEqual(self.base.project_call(reopened.native_options(),event())[1]['receiptId'],results['project'][1]['receiptId'])
        with reopened.writer_lock:
            purged=reopened.ledger.purge(self.owner_token,self.binding.record_id,'PURGE:'+self.binding.record_id,operation_id='handoff-purge')
        self.assertTrue(purged['checkpointAcknowledged'])
        with self.assertRaises(HandoffTransportError):second.call('read',{})
        self.assertEqual(second.call('revise',payload),results['handoff'])
        self.assertEqual(reader.read_context(self.context_token,{'query':'newharbor'})['records'],[])
        reopened.close();rollback=self.host(None);rollback.start()
        with self.assertRaises(native.ProjectCredentialError):rollback.handoff_options()
        self.assertIsNone(rollback.home_server.handoff_channel)
        self.assertEqual(self.base.project_call(rollback.native_options(),event())[1]['receiptId'],results['project'][1]['receiptId'])
        self.assertEqual(self.base.client(rollback).call('recall',{'query':'newharbor'})['records'],[])
        private_row,=self.base.client(rollback).call('recall',{'query':'cabin'})['records']
        self.assertEqual(private_row['record_id'],private_saved['record_id'])
        self.assertEqual(self.base.base.path.read_bytes(),self.base.original_credential)
        self.assertEqual(rollback.ledger.integrity_report()['status'],'PASS')

    def test_wrong_store_or_project_is_refused_without_another_listener_or_writer(self):
        for wrong in (replace(self.binding,store=replace(self.binding.store,file_inode=999)),
                      replace(self.binding,project_id='unapproved-project')):
            with self.assertRaises(native.ProjectCredentialError):self.host(wrong)
        host=self.host(None);self.assertEqual(host.start(),{'ready':True})
        self.assertIsNone(host.home_server.handoff_channel)

    @unittest.skipUnless(os.environ.get('MIND_LEGACY_SOURCE'),'select the deployed immutable client source explicitly')
    def test_existing_pinned_private_client_still_works_with_owner_refresh_enabled(self):
        host=self.host();host.start();options=host.agent_home_options()
        legacy=Path(os.environ['MIND_LEGACY_SOURCE']).resolve()
        self.assertTrue((legacy/'onoes_mind/agent_home_http.py').is_file())
        script="""import json,sys
sys.path.insert(0,sys.argv[1])
from onoes_mind.agent_home_http import AgentHomeClient
v=json.load(sys.stdin)
c=AgentHomeClient(v['baseUrl'],agent_id='nims',binding_sha256=v['binding'],credential_provider=lambda:v['token'],timeout=15)
r=c.call('remember',{'event_id':'legacy-private-client','text':'Private legacy lighthouse marker'})
row,=c.call('recall',{'query':'legacy lighthouse'})['records']
assert row['record_id']==r['record_id']
print(json.dumps({'deployedClientCompatible':True,'canonicalPrivateRecordMatched':True}))
"""
        result=subprocess.run([sys.executable,'-I','-B','-c',script,str(legacy)],
            input=json.dumps({'baseUrl':options['baseUrl'],'binding':options['agents']['nims'],'token':self.base.token}),
            capture_output=True,text=True,timeout=60,creationflags=subprocess.CREATE_NO_WINDOW)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(json.loads(result.stdout),{'deployedClientCompatible':True,'canonicalPrivateRecordMatched':True})
        self.assertEqual(self.client(host).call('read',{})['document'],self.document)

