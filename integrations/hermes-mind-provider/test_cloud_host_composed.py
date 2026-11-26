"""Owned Windows v6 -> prepared v7 -> v6 rollback on a fresh synthetic ledger."""
from copy import deepcopy
from dataclasses import asdict
import http.client
import json
import os
from pathlib import Path
import socket
import sys
import unittest
from urllib.parse import urlsplit

MIND=Path(os.environ['MIND_SOURCE']).resolve()
SOURCE=Path(os.environ['MESH_SOURCE']).resolve()
CANDIDATE=Path(os.environ['MESH_CANDIDATE_SOURCE']).resolve()
sys.path[:0]=[str(MIND),str(CANDIDATE),str(SOURCE/'integrations/hermes-mind-provider')]
# Load the actual frozen adapter before the existing fixtures orient their imports.
import project_service_process_candidate as service
import project_operator_process_candidate as operator
import native_project_sync_candidate as native
assert Path(service.__file__).resolve().parent==CANDIDATE
assert Path(operator.__file__).resolve().parent==CANDIDATE
import test_service_profile as prior
from cloud_host_profiles import PROJECT,V6,encoded,digest,prepare_host
from onoes_mind.agent_context import AgentContextBinding
from onoes_mind.agent_home import AgentHomeBinding,enroll_agent_home
from onoes_mind.agent_home_http import AgentHomeClient,AgentHomeTransportError,home_binding_sha256
from onoes_mind.context_enrollment import enroll_context_reader
from onoes_mind.handoff_channel import HandoffBinding,HandoffClient,handoff_binding_sha256
from onoes_mind.project_context_http import context_binding_sha256
from onoes_mind.project_tool_grant import ReviewedProjectToolGrant
from onoes_mind.recall_binding import RecallBinding,prepare_mesh_principal


def read_shared(endpoint,binding,token):
    connection=http.client.HTTPConnection('127.0.0.1',urlsplit(endpoint).port,timeout=20)
    try:
        connection.request('POST','/v1/project/read',body=encoded({'query':'cloudbuilderhandoff'}),headers={
            'Authorization':'Bearer '+token,'X-Onoes-Context-Principal':binding.principal_id,
            'X-Onoes-Context-Binding':context_binding_sha256(binding),'Content-Type':'application/json'})
        response=connection.getresponse();return response.status,json.loads(response.read())
    finally:connection.close()


@unittest.skipUnless(sys.platform=='win32','Windows protected canonical-host lifecycle')
class CloudHostComposedTests(unittest.TestCase):
    def setUp(self):
        self.prior=prior.OwnedHomeServiceTests();self.prior.setUp();self.addCleanup(self.prior.doCleanups)
        self.base=self.prior.base
        owner=self.base.base;owner.value['projects']=[[PROJECT,'Synthetic Mesh']]
        owner.write();self.base.value['operatorProfileSha256']=owner.sha
        self.base.write(actions=['first_setup','run_service'])

    def test_prepared_v7_keeps_existing_homes_handoff_and_v6_rollback_blocks_new_routes(self):
        self.base.prepare();owner=self.base.base;root=self.base.profile.parent;raw=owner.value['binding']
        store=RecallBinding(raw['database_path'],raw['store_id'],raw['environment'],raw['authority_ref'],
            'project/onoes-mind/shared',raw['file_device'],raw['file_inode'],
            'fixture:custody','fixture:revoke','fixture:canonical-store')
        homes={actor:AgentHomeBinding(store,actor) for actor in ('deep','echo','cyony')}
        reader=AgentContextBinding(store,'context-cyony',PROJECT)
        doc={'schema':'onoes-handoff/v1','handoff_id':'nims/onoes-mesh/cloudbuilderhandoff',
            'project_id':PROJECT,'author':'nims','revision':1,'next_action':'Read the shared measured plan'}
        from persistent_authority import AuthorityBinding,PersistentAuthorityCandidate
        from onoes_mind.runtime_keys import unprotect_runtime_keys
        keys=unprotect_runtime_keys(json.loads(Path(owner.value['keyEnrollmentPath']).read_bytes())['runtime_envelope'],
            store_id=store.store_id,environment_id=store.environment)
        authority=PersistentAuthorityCandidate(AuthorityBinding(**json.loads(Path(owner.value['authorityBindingPath']).read_bytes())))
        host=native.NativeProjectSyncHost(binding=operator.checked_profile(owner.profile,owner.sha)[1],
            history_path=owner.value['historyPath'],authority=authority,**keys,credential_path=owner.value['credentialPath'],
            project_ids=(PROJECT,),review_ref=owner.value['reviewRef'])
        tokens={};operator_token='omop1_'+'A'*43
        host.start()
        try:
            with host.writer_lock:
                prepare_mesh_principal(host.ledger,scope_id=store.scope_id)
                host.ledger.create_principal('operator');host.ledger.issue_credential('operator',operator_token)
                for actor,binding in homes.items():
                    enroll_agent_home(host.ledger,binding,operator_token=operator_token,
                        save_new_token=lambda value,actor=actor:tokens.setdefault(actor,value) is not None)
                enroll_context_reader(host.ledger,reader,operator_token=operator_token,
                    save_new_token=lambda value:tokens.setdefault('reader',value) is not None)
                admitted=host.ledger.remember(operator_token,{'event_id':'seed-cloud-builder-handoff','claim':json.dumps(doc),
                    'kind':'project_fact','project_id':PROJECT,'requested_visibility':'shared','source_class':'agent_handoff',
                    'evidence_refs':[{'type':'agent_handoff','ref':'fixture:cloudbuilderhandoff@1','content_hash':'a'*64}]})
        finally:host.close()
        handoff=HandoffBinding(store,admitted['record_id'],doc['handoff_id'],PROJECT,'nims')
        view=root/'baseline-view.json';view.write_bytes(encoded(owner.value))
        with socket.socket() as reservation:reservation.bind(('127.0.0.1',0));port=reservation.getsockname()[1]
        p=self.base.value;p.update(schema=V6,serviceRuntimeProfilePath=str(view),
            serviceRuntimeProfileSha256=service.digest(view),enrolledMeshSourceDirectory=str(service.HERE),
            agentHomeBindings=[asdict(homes[a]) for a in ('deep','echo')],agentHomePort=port,handoffBinding=asdict(handoff))
        self.base.write(actions=['run_service','run_agent_homes','run_handoff_refresh'])
        decision=json.loads(owner.approval.read_bytes());decision.update(agentHomes=service.home_approval(p),handoffRefresh=service.handoff_approval(p))
        owner.approval.write_bytes(encoded(decision))
        baseline_path=self.base.profile;baseline_sha=self.base.sha;baseline_raw=baseline_path.read_bytes()
        baseline_decision=owner.approval.read_bytes();baseline_value=deepcopy(p)
        endpoint=f'http://127.0.0.1:{port}'
        clients={a:AgentHomeClient(endpoint,agent_id=a,binding_sha256=home_binding_sha256(binding),
            credential_provider=lambda a=a:tokens[a],timeout=20) for a,binding in homes.items()}
        handoff_client=HandoffClient(endpoint,binding_sha256=handoff_binding_sha256(handoff),record_id=handoff.record_id,
            credential_provider=lambda:operator_token,timeout=20)

        def start():
            child,stamp=service.launch_service(self.base.profile,self.base.sha,owner.approval)
            self.base.children.append((child,stamp));self.base.ready(child);return child
        def stop(child):
            service.request_stop(self.base.profile,self.base.sha,owner.approval)
            self.assertEqual(child.wait(timeout=90),0)

        child=start();saved={}
        for actor in ('deep','echo'):
            saved[actor]=clients[actor].call('remember',{'event_id':'prior-'+actor,'text':actor+' retained harbor preference'})
        self.assertEqual(handoff_client.call('read',{})['document'],doc)
        self.assertEqual(read_shared(endpoint,reader,tokens['reader'])[0],404)
        with self.assertRaises(AgentHomeTransportError):clients['cyony'].call('recall',{'query':'harbor'})
        stop(child)

        grant=ReviewedProjectToolGrant(root/'cyony-reviewed-tool.json',reader,'fixture:cyony-shared-only')
        grant.path.write_bytes(grant.document())
        plan=prepare_host(service_raw=baseline_raw,runtime_raw=view.read_bytes(),service_path=str(baseline_path),
            expected_service_sha256=baseline_sha,expected_runtime_sha256=service.digest(view),mind_source=str(MIND),
            runtime_source_hashes={str(path):operator.digest(path) for path in operator.source_paths(owner.value['runtime'])},
            service_source_hashes={str(Path(module.__file__).resolve()):service.digest(module.__file__) for module in (service,operator)},
            new_runtime_path=str(root/'cloud-view.json'),new_service_path=str(root/'cloud-service.json'),
            new_attempt_path=str(root/'cloud-attempt.json'),new_ready_path=str(root/'cloud-ready.json'),new_stop_path=str(root/'cloud-stop.json'),
            tool_grant_path=str(grant.path),tool_review_ref=grant.review_ref)
        Path(plan.runtime_path).write_bytes(encoded(plan.runtime));Path(plan.service_path).write_bytes(encoded(plan.service))
        self.base.profile=Path(plan.service_path);self.base.sha=digest(encoded(plan.service));self.base.value=deepcopy(plan.service)
        # The old approval cannot silently authorize the new actor or reader.
        with self.assertRaises(service.ServiceProcessError):service.checked_profile(self.base.profile,self.base.sha,owner.approval)
        self.assertFalse(Path(plan.service['attemptPath']).exists())
        decision=json.loads(baseline_decision);decision.update(profiles=[self.base.sha],
            actions=['run_service','run_agent_homes','run_handoff_refresh','run_project_reads'],
            agentHomes=service.home_approval(plan.service),handoffRefresh=service.handoff_approval(plan.service),
            projectReads=service.project_read_approval(plan.service))
        owner.approval.write_bytes(encoded(decision))
        child=start()
        for actor in ('deep','echo'):
            self.assertEqual(clients[actor].call('recall',{'query':'harbor'})['records'][0]['record_id'],saved[actor]['record_id'])
        own=clients['cyony'].call('remember',{'event_id':'new-cyony','text':'Cyony private cloud note'})
        status,result=read_shared(endpoint,reader,tokens['reader']);self.assertEqual(status,200)
        self.assertEqual(json.loads(result['result']['records'][0]['claim']),doc)
        wrong=AgentHomeClient(endpoint,agent_id='echo',binding_sha256=home_binding_sha256(homes['echo']),credential_provider=lambda:tokens['cyony'],timeout=20)
        with self.assertRaises(AgentHomeTransportError):wrong.call('recall',{'query':'harbor'})
        grant.path.unlink();self.assertIn(read_shared(endpoint,reader,tokens['reader'])[0],(403,503))
        self.assertEqual(clients['cyony'].call('recall',{'query':'cloud note'})['records'][0]['record_id'],own['record_id'])
        self.assertEqual(handoff_client.call('read',{})['document'],doc)
        grant.path.write_bytes(grant.document());stop(child)

        self.assertEqual(baseline_path.read_bytes(),baseline_raw)
        self.base.profile=baseline_path;self.base.sha=baseline_sha;self.base.value=baseline_value
        owner.approval.write_bytes(baseline_decision)
        child=start()
        for actor in ('deep','echo'):
            self.assertEqual(clients[actor].call('recall',{'query':'harbor'})['records'][0]['record_id'],saved[actor]['record_id'])
        self.assertEqual(handoff_client.call('read',{})['document'],doc)
        self.assertEqual(read_shared(endpoint,reader,tokens['reader'])[0],404)
        with self.assertRaises(AgentHomeTransportError):clients['cyony'].call('recall',{'query':'cloud note'})
        stop(child)
