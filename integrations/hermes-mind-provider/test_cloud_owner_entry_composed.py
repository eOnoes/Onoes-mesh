"""Real encrypted backup/lease/DPAPI/enroll/import/revoke on an owned ledger.

No production store, credential, service, model or cloud connection is used.
The test refuses a live workspace and every data path stays in its own TEMP.
"""
from contextlib import closing
from dataclasses import asdict
import hashlib,importlib,json,os,secrets,socket,subprocess,sys,unittest
from pathlib import Path

WS=Path(os.environ['MESH_OWNER_FIXTURE_WORKSPACE']).resolve()
assert WS.name=='mesh-workroom-ab' and WS.parent.name.startswith('cloud-owner-entry-fixture-')
assert WS!=Path('D:/App-Data/Onoes-Mesh/mesh-workroom-ab')
MIND=Path(os.environ['MIND_SOURCE']).resolve()
sys.path[:0]=[str(MIND),str(Path(os.environ['MIND_TEST_SOURCE'])/'tests'),
    str(WS/'integrations/hermes-mind-provider'),str(WS/'integrations/mind-recovery-candidate')]
import test_service_profile as prior
import project_service_process_candidate as service
import project_operator_process_candidate as operator
import native_project_sync_candidate as native
import recall_process_candidate as roles
import project_backup_entry as backup
from cloud_curated_transfer import capture,encode,identity
from cloud_owner_entry import ACCESS
from cloud_phase_runner import NativePhases
from cloud_install_entry import CombinedWindow
from test_cloud_curated_transfer import private_dir
from onoes_mind.agent_home import AgentHome,AgentHomeBinding,WindowsAgentHomeCustody,enroll_agent_home
from onoes_mind.agent_context import AgentContextBinding,ProjectContextReader
from onoes_mind.context_enrollment import WindowsOperatorCustody
from onoes_mind.context_host import WindowsReaderCustody
from onoes_mind.handoff_channel import HandoffBinding
from onoes_mind.project_tool_grant import ReviewedProjectToolGrant
from onoes_mind.recall_binding import RecallBinding,prepare_mesh_principal
from onoes_mind.runtime_keys import unprotect_runtime_keys
from persistent_authority import AuthorityBinding,PersistentAuthorityCandidate
from checkpointed_ledger_candidate import CheckpointedLedgerCandidate


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def read(path):return json.loads(Path(path).read_bytes())
def put(path,value):
    with Path(path).open('xb') as stream:
        stream.write(json.dumps(value,sort_keys=True).encode());stream.flush();os.fsync(stream.fileno())


@unittest.skipUnless(os.name=='nt','Actual Windows canonical owner bridge')
class CloudOwnerEntryTests(unittest.TestCase):
    def test_actual_owner_entry_backup_curated_import_and_exact_revoke(self):
        before=prior.OwnedHomeServiceTests();before.setUp();self.addCleanup(before.doCleanups)
        base=before.base;owner=base.base;root=base.profile.parent
        self.assertTrue(root.is_relative_to(Path(os.environ['TEMP']).resolve()))
        owner.value['projects']=[['onoes-mesh','Synthetic Mesh']];owner.write()
        base.value['operatorProfileSha256']=owner.sha;base.write(actions=['first_setup','run_service'])
        print('Owner fixture: prepare project grant',flush=True)
        base.prepare()
        raw=owner.value['binding']
        store=RecallBinding(raw['database_path'],raw['store_id'],raw['environment'],raw['authority_ref'],
            'project/onoes-mind/shared',raw['file_device'],raw['file_inode'],'fixture:custody','fixture:revoke','fixture:owner-entry')
        homes={a:AgentHomeBinding(store,a) for a in ('cyony','deep','echo')}
        reader=AgentContextBinding(store,'context-cyony','onoes-mesh')
        op_token='omop1_'+secrets.token_urlsafe(32)
        op_directory=private_dir(root/'full-operator');op=WindowsOperatorCustody(op_directory,store)
        self.assertTrue(op.save_new(op_token));op_profile=op_directory/'owner-profile.json'
        put(op_profile,{'schema':'fixture-operator-profile/v1','binding':asdict(store)})
        prior_custody={a:WindowsAgentHomeCustody(private_dir(root/(a+'-custody')),homes[a]) for a in ('deep','echo')}
        package=read(owner.value['keyEnrollmentPath'])
        keys=unprotect_runtime_keys(package['runtime_envelope'],store_id=store.store_id,environment_id=store.environment)
        authority=PersistentAuthorityCandidate(AuthorityBinding(**read(owner.value['authorityBindingPath'])))
        host=native.NativeProjectSyncHost(binding=operator.checked_profile(owner.profile,owner.sha)[1],
            history_path=owner.value['historyPath'],authority=authority,**keys,credential_path=owner.value['credentialPath'],
            project_ids=('onoes-mesh',),review_ref=owner.value['reviewRef'])
        host.start()
        try:
            with host.writer_lock:
                # Match the existing phone/PC Mesh store: its read-only recall
                # principal/schema precede a new agent's home enrollment.
                prepare_mesh_principal(host.ledger,scope_id=store.scope_id)
                host.ledger.create_principal('operator');host.ledger.issue_credential('operator',op_token)
                for a,custody in prior_custody.items():
                    enroll_agent_home(host.ledger,homes[a],operator_token=op_token,save_new_token=custody.save_new)
                document={'author':'nims','revision':1,'next_action':'Review the synthetic print plan'}
                admitted=host.ledger.remember(op_token,{'event_id':'owner-entry-handoff','kind':'project_fact',
                    'project_id':'onoes-mesh','requested_visibility':'shared','claim':json.dumps(document),
                    'source_class':'agent_handoff','evidence_refs':[{'type':'fixture','ref':'nims:owner@1','content_hash':'a'*64}]})
        finally:host.close()
        # Replace only this fixture's placeholder recovery envelope. Runtime
        # keys stay identical; no real enrollment or user's password is read.
        from onoes_mind.enrollment_store import prepare_and_save_enrollment
        wrap=private_dir(root/'fixture-wrap')
        password='fixture-only-owner-entry-recovery-2026'
        prepare_and_save_enrollment(directory=wrap,**keys,store_id=store.store_id,environment_id=store.environment,
            password=password,confirmation=password)
        Path(owner.value['keyEnrollmentPath']).write_bytes((wrap/'key-enrollment.json').read_bytes())
        view=root/'server-runtime.json';put(view,owner.value)
        with socket.socket() as probe:probe.bind(('127.0.0.1',0));port=probe.getsockname()[1]
        handoff=HandoffBinding(store,admitted['record_id'],'nims/onoes-mesh/owner-entry','onoes-mesh','nims')
        grant=ReviewedProjectToolGrant(root/'cyony-tool.json',reader,'fixture:owner-entry')
        grant.path.write_bytes(grant.document())
        p=base.value
        p.update(schema=service.PROJECT_READ_SCHEMA,serviceRuntimeProfilePath=str(view),serviceRuntimeProfileSha256=sha(view),
            enrolledMeshSourceDirectory=str(service.HERE),agentHomeBindings=[asdict(homes[a]) for a in ('cyony','deep','echo')],
            agentHomePort=port,handoffBinding=asdict(handoff),projectReaderBindings=[{'binding':asdict(reader),
                'toolGrantPath':str(grant.path),'toolReviewRef':grant.review_ref}])
        base.write(actions=['run_service','run_agent_homes','run_handoff_refresh','run_project_reads'])
        decision=read(owner.approval)
        decision.update(agentHomes=service.home_approval(p),handoffRefresh=service.handoff_approval(p),projectReads=service.project_read_approval(p))
        owner.approval.write_text(json.dumps(decision))
        # Real passwordless encrypted snapshot and archive recovery readback.
        print('Owner fixture: native encrypted backup and verification',flush=True)
        source,stage,rehearsal=[private_dir(root/n) for n in ('before-source','before-stage','before-rehearsal')]
        archive_root=private_dir(root/'encrypted-archives')
        tool=read(WS/'data/sevenzip-tool-proof-20261115.json')['tool']
        backup_profile=root/'before-backup.json';backup_approval=root/'before-backup-approval.json'
        b=dict(schema=backup.SCHEMA,ownerSid=owner.value['ownerSid'],runtime=owner.value['runtime'],
            sourceHashes={str(n):backup.digest(n) for n in backup.source_paths(owner.value['runtime'])},
            binding=raw,keyEnrollmentPath=owner.value['keyEnrollmentPath'],authorityBindingPath=owner.value['authorityBindingPath'],
            historyPath=owner.value['historyPath'],sourceDirectory=str(source),stagingDirectory=str(stage),rehearsalDirectory=str(rehearsal),
            encryptedBackup=str(archive_root/'Owner-entry-synthetic-before.7z'),archiveTool=tool,
            attemptPath=str(root/'before-backup-attempt.json'),resultPath=str(root/'before-backup-result.json'),
            reviewRef='fixture:owner-entry-backup',archiveCredentialMode='windows-local',
            writerGate={'kind':'not_started','attemptPath':str(root/'future-service-attempt.json'),
                'readyPath':str(root/'future-service-ready.json'),'profileSha256':'a'*64})
        put(backup_profile,b);backup_sha=sha(backup_profile)
        put(backup_approval,dict(decision=backup.DECISION,ownerSid=b['ownerSid'],profileSha256=backup_sha,
            storeId=store.store_id,environment=store.environment,reviewRef=b['reviewRef']))
        # Exercise the concrete parent transport, including the real backup
        # CLI. The fixture's own master contract grants no live access.
        parent_evidence=private_dir(root/'parent-phase-evidence')
        master={'schema':'onoes-cloud-install-window/v1','agentId':'cyony',
            'readerPrincipal':'context-cyony','sharedProject':'onoes-mesh','modelCalls':0,
            'maintenanceTask':'ONOes Mesh Workroom Recovery','python':str(Path(sys.executable).resolve()),
            'pythonSha256':sha(Path(sys.executable).resolve()),'backups':{'before':{
                'entryPath':str(Path(backup.__file__)),'entrySha256':sha(backup.__file__),
                'profilePath':str(backup_profile),'profileSha256':backup_sha,
                'approvalPath':str(backup_approval),'approvalSha256':sha(backup_approval),
                'resultPath':b['resultPath']}}}
        def parent():
            pin=hashlib.sha256(json.dumps(master,sort_keys=True).encode()).hexdigest()
            return NativePhases(master,pin,{'schema':'onoes-cloud-install-authorization/v1','owner':'Eddie',
                'decision':'approve_cyony_private_home_and_mesh_reader','planSha256':pin},parent_evidence)
        backup_result=parent().backup('before',label='owned-real-backup')
        self.assertEqual(backup_result['archiveRehearsal'],'PASS')
        self.assertEqual(backup.verify_completed_archive(backup_profile,backup_sha)['status'],'archive_verified')
        # Synthetic curated transfer only; this does not contact Cyony or read
        # anyone's saved MEMORY.md/USER.md.
        saved=private_dir(root/'synthetic-saved-notes');private_dir(saved/'memories')
        for n,text in [('MEMORY.md','Synthetic measured print plan version seven.'),('USER.md','Use concise updates.')]:
            (saved/'memories'/n).write_text(text)
        identities={p.name:list(identity(p.stat())) for p in (saved/'memories').iterdir()}
        snapshot=capture(saved,origin='srv1693050/cyony-hermes',expected_identities=identities)
        transport=root/'curated-private-transport.json';transport.write_bytes(encode(snapshot))
        capture_receipt=root/'curated-capture.json'
        put(capture_receipt,{'schema':'onoes-cloud-curated-capture/v1','verified':True,
            'approvedSourceIdentities':identities,'transportSha256':sha(transport)})
        curated_stage=private_dir(root/'curated-stage');private_dir(curated_stage/'memories')
        evidence=private_dir(root/'owner-evidence')
        private=private_dir(root/'cyony-private');shared=private_dir(root/'cyony-shared')
        entry=WS/'integrations/hermes-mind-provider/cloud_owner_entry.py'
        pins={str(p):sha(p) for p in (MIND/'onoes_mind').rglob('*.py')}
        pins.update({str(p):sha(p) for p in (MIND/'onoes_mind/migrations').glob('*.sql')})
        pins.update({str(p):sha(p) for p in (WS/'integrations/mind-recovery-candidate').glob('*.py') if not p.name.startswith('test')})
        plan={'schema':'onoes-cloud-owner-operation/v1','access':ACCESS,'python':sys.executable,'sdk':str(MIND),'workspace':str(WS),
            'executors':{n:sha(entry.with_name(n)) for n in ('cloud_owner_entry.py','cloud_owner_phase.py','cloud_enrollment.py','cloud_curated_transfer.py')},
            'sourcePins':pins,'writer':{'path':str(base.profile),'sha256':sha(base.profile)},
            'writerApproval':{'path':str(owner.approval),'sha256':sha(owner.approval)},
            'operator':{'path':str(op_profile),'sha256':sha(op_profile)},
            'beforeBackupResult':b['resultPath'],'beforeArchive':b['encryptedBackup'],
            'beforeBackup':{'entryPath':str(Path(backup.__file__)),'entrySha256':sha(backup.__file__),
                'profilePath':str(backup_profile),'profileSha256':backup_sha},
            'evidence':str(evidence),'privateCustody':str(private),'sharedCustody':str(shared),
            'preservedCustody':[str(op.path),owner.value['credentialPath'],*[str(c.path) for c in prior_custody.values()]],
            'curatedCaptureReceipt':str(capture_receipt),'curatedSourceIdentities':identities,
            'curatedTransport':str(transport),'curatedStage':str(curated_stage),'attemptId':'synthetic-cloud-owner-entry'}
        plan_path=root/'owner-plan.json';put(plan_path,plan);pin=sha(plan_path)
        auth_path=root/'owner-authorization.json'
        put(auth_path,{'schema':'onoes-cloud-owner-operation-authorization/v1','owner':'Eddie',
            'decision':'approve_cyony_private_home_and_mesh_reader','planSha256':pin})
        master['owner']={'entryPath':str(entry),'entrySha256':sha(entry),'planPath':str(plan_path),
            'planSha256':pin,'authorizationPath':str(auth_path)}
        def operation(action):
            log=WS.parent/('owner-'+action+'.log')
            result=parent().local('owner',action,label='owned-owner-'+action)
            put(log,result)
            return result
        print('Owner fixture: actual cold entry admission',flush=True)
        self.assertTrue(operation('admit')['verified'])
        # Real DPAPI custody -> the enclosing adapter's private delivery bytes.
        # Only the remote endpoint is replaced by an owned capture sink; no
        # SSH or real agent access occurs. Binding review refs deliberately
        # differ from the original operator's store metadata in this fixture.
        window=CombinedWindow.__new__(CombinedWindow)
        window.owner_body=plan;window.root={'owner':evidence,'private':private_dir(root/'parent-private')}
        window.pin='a'*64;captured=[]
        def private_sink(phase,label,stdin=None):
            self.assertEqual(phase,'deliver');captured.append(json.loads(stdin));return {'verified':True}
        window.client=private_sink
        self.assertTrue(window.deliver_client()['verified'])
        self.assertEqual(len(captured),1)
        self.assertEqual(captured[0]['homeToken'],WindowsAgentHomeCustody(private,homes['cyony']).read())
        self.assertEqual(captured[0]['readerToken'],WindowsReaderCustody(shared,reader).read())
        import base64
        self.assertEqual(len(base64.b64decode(captured[0]['intentKeyBase64'],validate=True)),32)
        self.assertTrue((window.root['private']/'NEW-CLIENT-INTENT.dpapi').exists())
        captured.clear()
        with closing(ProjectContextReader(store.database_path,binding=reader)) as current:
            self.assertEqual(current.authenticate(WindowsReaderCustody(shared,reader).read()),'context-cyony')
        # Use the same authoritative writer APIs for readback after the child
        # released its service lease. Do not launch a gateway or a model.
        def inspect_current(expect_revoked=False):
            from native_project_sync_candidate import ProjectServiceLease
            from onoes_mind.ledger import LedgerError
            with closing(ProjectServiceLease(operator.checked_profile(owner.profile,owner.sha)[1])):
                ledger=CheckpointedLedgerCandidate(store.database_path,owner.value['historyPath'],authority,
                    store_id=store.store_id,environment=store.environment,**keys)
                try:
                    for a,c in prior_custody.items():self.assertEqual(ledger.authenticate(c.read()),a)
                    self.assertEqual(ledger.authenticate(op.read()),'operator')
                    credential=WindowsAgentHomeCustody(private,homes['cyony']).read()
                    if expect_revoked:
                        with self.assertRaises(LedgerError):ledger.authenticate(credential)
                        imported=read(evidence/'CURATED-IMPORT.json')['canonicalImport']['receipt']['record_id']
                        self.assertTrue(ledger.db.execute('SELECT 1 FROM memory_records WHERE record_id=?',(imported,)).fetchone())
                    else:
                        rows=AgentHome(ledger,homes['cyony']).recall(credential,{'kind':'profile','max_bytes':16384})['records']
                        self.assertEqual(len(rows),1);self.assertIn('Synthetic measured print plan',rows[0]['claim'])
                finally:ledger.close()
        inspect_current()
        print('Owner fixture: exact cold receipt-bound revocation',flush=True)
        self.assertTrue(operation('revoke')['verified']);inspect_current(expect_revoked=True)
        self.assertTrue((evidence/'CURATED-IMPORT.json').exists())
        self.assertTrue(all((saved/'memories'/n).read_bytes()==raw for n,raw in snapshot.files.items()))
        result={'passed':True,'realEncryptedBackup':True,'realArchiveVerification':True,'nativeWriterLease':True,
            'actualColdOwnerEntry':True,'curatedImportReadback':True,'exactRevocation':True,
            'existingEchoDeepCustodyUnchanged':True,'canonicalImportRetained':True,'liveChanges':False,'modelCalls':0,
            'actualParentBackupTransport':True,'actualParentColdOwnerTransport':True,
            'actualParentProtectedDeliveryPayload':True,'remoteDelivery':'NOT_RUN_LOCAL_PRIVATE_SINK_ONLY'}
        put(WS.parent/'OWNER-COMPOSED.json',result)
        print(json.dumps(result),flush=True)
