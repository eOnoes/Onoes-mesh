"""Exact inactive v6 owned-process qualification; no live store or profile."""
from copy import deepcopy
from dataclasses import asdict
import json
import os
from pathlib import Path
import socket
import sys
import unittest

MIND=Path(os.environ['MIND_SOURCE']).resolve();sys.path.insert(0,str(MIND))
SOURCE=Path(os.environ['MESH_SOURCE']).resolve()
sys.path[:0]=[str(SOURCE/'integrations/hermes-mind-provider'),str(SOURCE/'integrations/mind-recovery-candidate')]
import test_service_profile as prior
import project_service_process_candidate as service
import project_operator_process_candidate as operator
import native_project_sync_candidate as native
from onoes_mind.agent_home import AgentHomeBinding,enroll_agent_home
from onoes_mind.agent_home_http import AgentHomeClient,home_binding_sha256
from onoes_mind.handoff_channel import HandoffBinding,HandoffClient,HandoffTransportError,handoff_binding_sha256
from onoes_mind.recall_binding import RecallBinding


class OwnedHandoffServiceTests(unittest.TestCase):
    def setUp(self):
        self.prior=prior.OwnedHomeServiceTests();self.prior.setUp();self.addCleanup(self.prior.doCleanups)
        self.base=self.prior.base

    def test_exact_grant_same_endpoint_recovery_and_private_home_only_rollback(self):
        self.base.prepare();owner=self.base.base;root=self.base.profile.parent;b=owner.value['binding']
        store=RecallBinding(b['database_path'],b['store_id'],b['environment'],b['authority_ref'],
            'project/onoes-mind/shared',b['file_device'],b['file_inode'],'fixture:custody','fixture:revoke','fixture:review')
        home=AgentHomeBinding(store,'echo');project=owner.value['projects'][0][0]
        document={'schema':'onoes-handoff/v1','handoff_id':'nims/'+project+'/current-build','project_id':project,
            'author':'nims','revision':1,'next_action':'Inspect oldlighthouse'}
        from persistent_authority import AuthorityBinding,PersistentAuthorityCandidate
        from onoes_mind.runtime_keys import unprotect_runtime_keys
        keys=unprotect_runtime_keys(json.loads(Path(owner.value['keyEnrollmentPath']).read_bytes())['runtime_envelope'],
            store_id=store.store_id,environment_id=store.environment)
        authority=PersistentAuthorityCandidate(AuthorityBinding(**json.loads(Path(owner.value['authorityBindingPath']).read_bytes())))
        host=native.NativeProjectSyncHost(binding=operator.checked_profile(owner.profile,owner.sha)[1],
            history_path=owner.value['historyPath'],authority=authority,**keys,
            credential_path=owner.value['credentialPath'],project_ids=tuple(row[0] for row in owner.value['projects']),
            review_ref=owner.value['reviewRef'])
        host.start();operator_token='omop1_'+'A'*43;tokens=[]
        try:
            with host.writer_lock:
                host.ledger.create_principal('operator');host.ledger.issue_credential('operator',operator_token)
                enroll_agent_home(host.ledger,home,operator_token=operator_token,save_new_token=lambda token:tokens.append(token) is None)
                admitted=host.ledger.remember(operator_token,{'event_id':'handoff-initial','claim':json.dumps(document),
                    'kind':'project_fact','project_id':project,'requested_visibility':'shared','source_class':'agent_handoff',
                    'evidence_refs':[{'type':'agent_handoff','ref':'handoff:'+document['handoff_id']+'@1','content_hash':'a'*64}]})
        finally:host.close()
        handoff=HandoffBinding(store,admitted['record_id'],document['handoff_id'],project,'nims')
        view=root/'handoff-runtime.json';view.write_text(json.dumps(owner.value),encoding='utf-8')
        with socket.socket() as reserve:reserve.bind(('127.0.0.1',0));port=reserve.getsockname()[1]
        p=self.base.value
        p.update(schema=service.HANDOFF_SCHEMA,serviceRuntimeProfilePath=str(view),serviceRuntimeProfileSha256=service.digest(view),
            enrolledMeshSourceDirectory=str(service.HERE),agentHomeBindings=[asdict(home)],agentHomePort=port,handoffBinding=asdict(handoff))
        self.base.write(actions=['run_service','run_agent_homes','run_handoff_refresh'])
        decision=json.loads(owner.approval.read_bytes());decision.update(agentHomes=service.home_approval(p),handoffRefresh=service.handoff_approval(p))
        for bad in ('missing-action','wrong-target'):
            invalid=deepcopy(decision)
            if bad=='missing-action':invalid['actions'].remove('run_handoff_refresh')
            else:invalid['handoffRefresh']['bindingSha256']='0'*64
            owner.approval.write_text(json.dumps(invalid),encoding='utf-8')
            with self.assertRaises(service.ServiceProcessError):service.checked_profile(self.base.profile,self.base.sha,owner.approval)
            self.assertFalse(Path(p['attemptPath']).exists())
        owner.approval.write_text(json.dumps(decision),encoding='utf-8')
        endpoint=f'http://127.0.0.1:{port}'
        client=HandoffClient(endpoint,binding_sha256=handoff_binding_sha256(handoff),record_id=handoff.record_id,
            credential_provider=lambda:operator_token,timeout=15)
        private=AgentHomeClient(endpoint,agent_id='echo',binding_sha256=home_binding_sha256(home),credential_provider=lambda:tokens[0],timeout=15)
        for iteration in range(2):
            child,stamp=service.launch_service(self.base.profile,self.base.sha,owner.approval)
            self.base.children.append((child,stamp));state=self.base.ready(child)
            self.assertEqual(state['handoffRefresh'],dict(baseUrl=endpoint,bindingSha256=handoff_binding_sha256(handoff),
                recordId=handoff.record_id,projectId=project,author='nims'))
            current=client.call('read',{})
            if iteration==0:
                payload={'expected_revision_id':current['revision_id'],'event_id':'owner-refresh-second',
                    'document':{**document,'revision':2,'next_action':'Build newharbor'},'review_ref':'owner:fixture-refresh'}
                receipt=client.call('revise',payload)
                saved=private.call('remember',{'event_id':'private-retained','text':'Private quietcabin preference'})
                project_receipt=self.base.send(service.native_options(self.base.profile,self.base.sha,owner.approval))
            else:
                self.assertEqual(current['document'],payload['document']);self.assertEqual(client.call('revise',payload),receipt)
                self.assertEqual(private.call('recall',{'query':'quietcabin'})['records'][0]['record_id'],saved['record_id'])
            service.request_stop(self.base.profile,self.base.sha,owner.approval);self.assertEqual(child.wait(timeout=120),0)
        p['schema']=service.AGENT_HOME_SCHEMA;p.pop('handoffBinding')
        for name in ('attemptPath','readyPath','stopPath'):p[name]=str(root/('refresh-disabled-'+name+'.json'))
        self.base.profile=root/'private-home-only.json';self.base.write(actions=['run_service','run_agent_homes'])
        decision=json.loads(owner.approval.read_bytes());decision.pop('handoffRefresh',None);decision['agentHomes']=service.home_approval(p)
        owner.approval.write_text(json.dumps(decision),encoding='utf-8')
        child,stamp=service.launch_service(self.base.profile,self.base.sha,owner.approval);self.base.children.append((child,stamp))
        state=self.base.ready(child);self.assertNotIn('handoffRefresh',state)
        with self.assertRaises(HandoffTransportError):client.call('read',{})
        self.assertEqual(private.call('recall',{'query':'quietcabin'})['records'][0]['record_id'],saved['record_id'])
        self.assertEqual(self.base.send(service.native_options(self.base.profile,self.base.sha,owner.approval))['receiptId'],project_receipt['receiptId'])
        service.request_stop(self.base.profile,self.base.sha,owner.approval);self.assertEqual(child.wait(timeout=120),0)
