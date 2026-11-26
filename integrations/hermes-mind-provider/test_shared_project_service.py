"""Explicit v7 admission and owned-process lifecycle on synthetic stores only."""
from copy import deepcopy
from dataclasses import asdict
import http.client
import json
import os
from pathlib import Path
import socket
import sys
import unittest

import pytest

MIND=Path(os.environ['MIND_SOURCE']).resolve();SOURCE=Path(os.environ['MESH_SOURCE']).resolve()
sys.path[:0]=[str(MIND),str(SOURCE/'integrations/hermes-mind-provider'),str(SOURCE/'integrations/mind-recovery-candidate')]
import test_service_profile as prior
import project_service_process_candidate as service
import project_operator_process_candidate as operator
import native_project_sync_candidate as native
from onoes_mind.agent_context import AgentContextBinding
from onoes_mind.agent_home import AgentHomeBinding,enroll_agent_home
from onoes_mind.agent_home_http import AgentHomeClient,home_binding_sha256
from onoes_mind.context_enrollment import enroll_context_reader
from onoes_mind.handoff_channel import HandoffBinding,HandoffClient,handoff_binding_sha256
from onoes_mind.project_context_http import context_binding_sha256
from onoes_mind.project_tool_grant import ReviewedProjectToolGrant
from onoes_mind.recall_binding import RecallBinding,prepare_mesh_principal


def metadata_profile():
    store=prior.synthetic_binding().store
    binding=AgentContextBinding(store,'context-cyony-mesh','read-only-project')
    return {'schema':service.PROJECT_READ_SCHEMA,'agentHomePort':23456,
        'agentHomeBindings':[asdict(prior.synthetic_binding())],
        'projectReaderBindings':[{'binding':asdict(binding),
            'toolGrantPath':str((MIND.parent/'private-operator-fixture/grant.json').resolve()),
            'toolReviewRef':'fixture:separate-read-approval'}]}


def test_exact_project_descriptor_matches_canonical_wire_binding_and_fixes_grant_location():
    p=metadata_profile();row=p['projectReaderBindings'][0];fields=deepcopy(row['binding']);fields['store']=RecallBinding(**fields['store'])
    descriptor=service.project_read_approval(p)
    assert descriptor['readers']['context-cyony-mesh']['bindingSha256']==context_binding_sha256(AgentContextBinding(**fields))
    assert descriptor['readers']['context-cyony-mesh']['toolGrantPath']==row['toolGrantPath']
    changed=deepcopy(p);changed['projectReaderBindings'][0]['toolReviewRef']='different-review'
    assert service.project_read_approval(changed)!=descriptor


@pytest.mark.parametrize('schema',[service.SCHEMA,service.RELOCATED_RUNTIME_SCHEMA,service.REVIEWED_RELEASE_SCHEMA,
    service.RELOCATED_MESH_SCHEMA,service.AGENT_HOME_SCHEMA,service.HANDOFF_SCHEMA])
def test_older_schemas_cannot_self_enable_project_reader_contract(schema):
    p=metadata_profile();p['schema']=schema
    with pytest.raises(service.ServiceProcessError):service.project_read_approval(p)
    assert service.profile_project_readers(p,None,None)==()


@pytest.mark.parametrize('bad',['duplicate','wrong-principal','extra-selector','relative-grant','empty-review'])
def test_bad_project_reader_metadata_is_rejected_before_runtime_or_store_open(bad):
    p=metadata_profile();row=p['projectReaderBindings'][0]
    if bad=='duplicate':p['projectReaderBindings']*=2
    elif bad=='wrong-principal':row['binding']['principal_id']='echo'
    elif bad=='extra-selector':row['scope']='all'
    elif bad=='relative-grant':row['toolGrantPath']='relative.json'
    else:row['toolReviewRef']=''
    with pytest.raises(service.ServiceProcessError):service.project_read_approval(p)


@unittest.skipUnless(sys.platform=='win32','Windows owned project service')
class OwnedProjectReadServiceTests(unittest.TestCase):
    def setUp(self):
        self.prior=prior.OwnedHomeServiceTests();self.prior.setUp();self.addCleanup(self.prior.doCleanups)
        self.base=self.prior.base

    def read(self,endpoint,binding,token):
        from urllib.parse import urlsplit
        url=urlsplit(endpoint);connection=http.client.HTTPConnection('127.0.0.1',url.port,timeout=20)
        try:
            connection.request('POST','/v1/project/read',body=json.dumps({'query':'sharedmarker'}),headers={
                'Authorization':'Bearer '+token,'X-Onoes-Context-Principal':binding.principal_id,
                'X-Onoes-Context-Binding':context_binding_sha256(binding),'Content-Type':'application/json'})
            response=connection.getresponse();return response.status,json.loads(response.read())
        finally:connection.close()

    def test_explicit_v7_launch_restart_current_grant_and_v6_rollback_preserve_private_and_handoff(self):
        self.base.prepare();owner=self.base.base;root=self.base.profile.parent;raw=owner.value['binding']
        store=RecallBinding(raw['database_path'],raw['store_id'],raw['environment'],raw['authority_ref'],
            'project/onoes-mind/shared',raw['file_device'],raw['file_inode'],'fixture:custody','fixture:revoke','fixture:review')
        home=AgentHomeBinding(store,'echo');project=owner.value['projects'][0][0]
        reader_binding=AgentContextBinding(store,'context-cyony-mesh',project)
        document={'schema':'onoes-handoff/v1','handoff_id':'nims/'+project+'/sharedmarker','project_id':project,
            'author':'nims','revision':1,'next_action':'Read sharedmarker current plan'}
        from persistent_authority import AuthorityBinding,PersistentAuthorityCandidate
        from onoes_mind.runtime_keys import unprotect_runtime_keys
        keys=unprotect_runtime_keys(json.loads(Path(owner.value['keyEnrollmentPath']).read_bytes())['runtime_envelope'],
            store_id=store.store_id,environment_id=store.environment)
        authority=PersistentAuthorityCandidate(AuthorityBinding(**json.loads(Path(owner.value['authorityBindingPath']).read_bytes())))
        host=native.NativeProjectSyncHost(binding=operator.checked_profile(owner.profile,owner.sha)[1],
            history_path=owner.value['historyPath'],authority=authority,**keys,credential_path=owner.value['credentialPath'],
            project_ids=tuple(v[0] for v in owner.value['projects']),review_ref=owner.value['reviewRef'])
        tokens={};operator_token='omop1_'+'A'*43
        host.start()
        try:
            with host.writer_lock:
                prepare_mesh_principal(host.ledger,scope_id=store.scope_id)
                host.ledger.create_principal('operator');host.ledger.issue_credential('operator',operator_token)
                enroll_agent_home(host.ledger,home,operator_token=operator_token,save_new_token=lambda value:tokens.setdefault('home',value) is not None)
                enroll_context_reader(host.ledger,reader_binding,operator_token=operator_token,save_new_token=lambda value:tokens.setdefault('context',value) is not None)
                admitted=host.ledger.remember(operator_token,{'event_id':'initial-reader-handoff','claim':json.dumps(document),
                    'kind':'project_fact','project_id':project,'requested_visibility':'shared','source_class':'agent_handoff',
                    'evidence_refs':[{'type':'agent_handoff','ref':'fixture:sharedmarker@1','content_hash':'a'*64}]})
        finally:host.close()
        handoff=HandoffBinding(store,admitted['record_id'],document['handoff_id'],project,'nims')
        # The existing fixture backup/control directory is already protected
        # and is separate from the canonical database and both source trees.
        self.assertFalse(root.resolve().is_relative_to(Path(store.database_path).parent))
        grant=ReviewedProjectToolGrant(root/'active-tool-grant.json',reader_binding,'fixture:shared-read')
        grant.path.write_bytes(grant.document())
        view=root/'project-read-runtime.json';view.write_text(json.dumps(owner.value),encoding='utf-8')
        with socket.socket() as reservation:reservation.bind(('127.0.0.1',0));port=reservation.getsockname()[1]
        p=self.base.value;p.update(schema=service.PROJECT_READ_SCHEMA,serviceRuntimeProfilePath=str(view),
            serviceRuntimeProfileSha256=service.digest(view),enrolledMeshSourceDirectory=str(service.HERE),
            agentHomeBindings=[asdict(home)],agentHomePort=port,handoffBinding=asdict(handoff),
            projectReaderBindings=[{'binding':asdict(reader_binding),'toolGrantPath':str(grant.path),'toolReviewRef':grant.review_ref}])
        actions=['run_service','run_agent_homes','run_handoff_refresh','run_project_reads'];self.base.write(actions=actions)
        decision=json.loads(owner.approval.read_bytes());decision.update(agentHomes=service.home_approval(p),
            handoffRefresh=service.handoff_approval(p),projectReads=service.project_read_approval(p))
        for failure in ('missing-action','wrong-target'):
            bad=deepcopy(decision)
            if failure=='missing-action':bad['actions'].remove('run_project_reads')
            else:bad['projectReads']['readers'][reader_binding.principal_id]['bindingSha256']='0'*64
            owner.approval.write_text(json.dumps(bad),encoding='utf-8')
            with self.assertRaises(service.ServiceProcessError):service.checked_profile(self.base.profile,self.base.sha,owner.approval)
            self.assertFalse(Path(p['attemptPath']).exists())
        owner.approval.write_text(json.dumps(decision),encoding='utf-8')
        endpoint=f'http://127.0.0.1:{port}'
        private=AgentHomeClient(endpoint,agent_id='echo',binding_sha256=home_binding_sha256(home),credential_provider=lambda:tokens['home'],timeout=20)
        handoff_client=HandoffClient(endpoint,binding_sha256=handoff_binding_sha256(handoff),record_id=handoff.record_id,
            credential_provider=lambda:operator_token,timeout=20)
        for iteration in range(2):
            child,stamp=service.launch_service(self.base.profile,self.base.sha,owner.approval);self.base.children.append((child,stamp))
            state=self.base.ready(child);self.assertEqual(state['projectReads'],service.project_read_options(p))
            ready_path=Path(p['readyPath']);ready_bytes=ready_path.read_bytes()
            forged=json.loads(ready_bytes)
            forged['projectReads']['readers'][reader_binding.principal_id]['projectId']='other-project'
            ready_path.write_text(json.dumps(forged),encoding='utf-8')
            try:
                with self.assertRaises(service.ServiceProcessError):service.service_state(self.base.profile,self.base.sha,owner.approval)
            finally:ready_path.write_bytes(ready_bytes)
            status,result=self.read(endpoint,reader_binding,tokens['context']);self.assertEqual(status,200)
            self.assertEqual(json.loads(result['result']['records'][0]['claim'])['author'],'nims')
            if iteration==0:saved=private.call('remember',{'event_id':'private-retained','text':'Private blueharbor preference'})
            else:self.assertEqual(private.call('recall',{'query':'blueharbor'})['records'][0]['record_id'],saved['record_id'])
            grant.path.unlink();self.assertIn(self.read(endpoint,reader_binding,tokens['context'])[0],(403,503))
            self.assertEqual(handoff_client.call('read',{})['document'],document)
            self.assertEqual(private.call('recall',{'query':'blueharbor'})['records'][0]['record_id'],saved['record_id'])
            grant.path.write_bytes(grant.document())
            service.request_stop(self.base.profile,self.base.sha,owner.approval);self.assertEqual(child.wait(timeout=120),0)
        p['schema']=service.HANDOFF_SCHEMA;p.pop('projectReaderBindings')
        for name in ('attemptPath','readyPath','stopPath'):p[name]=str(root/('reader-off-'+name+'.json'))
        self.base.profile=root/'reader-disabled.json';self.base.write(actions=actions[:-1])
        decision=json.loads(owner.approval.read_bytes());decision.pop('projectReads');owner.approval.write_text(json.dumps(decision),encoding='utf-8')
        child,stamp=service.launch_service(self.base.profile,self.base.sha,owner.approval);self.base.children.append((child,stamp))
        state=self.base.ready(child);self.assertNotIn('projectReads',state)
        ready_path=Path(p['readyPath']);ready_bytes=ready_path.read_bytes()
        forged=json.loads(ready_bytes);forged['projectReads']={'unexpected':'reader'}
        ready_path.write_text(json.dumps(forged),encoding='utf-8')
        try:
            with self.assertRaises(service.ServiceProcessError):service.service_state(self.base.profile,self.base.sha,owner.approval)
        finally:ready_path.write_bytes(ready_bytes)
        self.assertEqual(self.read(endpoint,reader_binding,tokens['context'])[0],404)
        self.assertEqual(private.call('recall',{'query':'blueharbor'})['records'][0]['record_id'],saved['record_id'])
        self.assertEqual(handoff_client.call('read',{})['document'],document)
        service.request_stop(self.base.profile,self.base.sha,owner.approval);self.assertEqual(child.wait(timeout=120),0)
