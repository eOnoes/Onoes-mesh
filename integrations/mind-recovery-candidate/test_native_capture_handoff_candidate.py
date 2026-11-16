"""Opt-in real offline-to-connected handoff in a copied synthetic workspace."""
from contextlib import closing
import copy
import json
import os
from pathlib import Path
import socket
import sqlite3
import sys
import time
import unittest
from unittest.mock import patch

import mesh_launch_candidate as launch
import recall_process_candidate as roles
import reader_service_process_candidate as reader_service
import project_service_process_candidate as writer_service
import test_project_mesh_input_candidate as fixtures

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from mesh_launcher_window import MeshLauncherWindow
import mesh_recovery_candidate as recovery


@unittest.skipUnless(os.name=='nt' and os.environ.get('MESH_NATIVE_HANDOFF_WORKSPACE'),
                     'Explicit isolated copied handoff workspace required')
class CaptureHandoffTests(unittest.TestCase):
    def test_offline_edit_reconciles_same_events_after_interrupted_connected_publication(self):
        workspace=Path(os.environ['MESH_NATIVE_HANDOFF_WORKSPACE']).resolve()
        self.assertEqual(workspace,launch.ROOT);self.assertEqual(workspace,recovery.ROOT)
        self.assertTrue(workspace.parent.name.startswith('mesh-native-handoff-'))
        receipt=workspace.parent/'workroom-ab-preview-process.json';self.assertFalse(receipt.exists())
        (workspace/'data').mkdir(exist_ok=True)
        def phase(text):print('Synthetic capture handoff: '+text,flush=True)
        phase('baseline_start')
        case=fixtures.ProjectMeshLauncherTests();self.addCleanup(case.doCleanups);case.setUp()
        original_launch=launch.launch_mesh
        def fixed_gateway(profile,sha,approval):
            value=json.loads(Path(profile).read_text())
            with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
            value['settings']['MESH_PREVIEW_PORT']=str(port);Path(profile).write_text(json.dumps(value));sha=launch.digest(profile)
            for path in (case.reader.approval,case.fixture.base.approval):
                accepted=json.loads(path.read_text());accepted['profiles'].append(sha);path.write_text(json.dumps(accepted))
            return original_launch(profile,sha,approval)
        with patch.object(launch,'launch_mesh',side_effect=fixed_gateway):
            case.test_exact_profiles_preflight_then_owned_gateway_delivers_only_approved_fields()
        phase('baseline_delivered')
        original_profile=case.root/'mesh-launch.json';original_sha=launch.digest(original_profile)
        p=json.loads(original_profile.read_text());old_gateway=case.mesh
        old_reader_state=roles.reader_state(case.reader.reader,case.reader.reader_sha,case.reader.approval)
        old_writer_state=writer_service.service_state(case.fixture.profile,case.fixture.sha,case.fixture.base.approval)
        old_reader=next(child for child in case.reader.children if child.pid==old_reader_state['pid'])
        old_writer=next(child for child,ticks in case.fixture.children if child.pid==old_writer_state['pid'])
        new_children=[]
        def cleanup():
            for child in reversed(new_children):
                if child.poll() is None:child.terminate()
                child.wait(timeout=30)
        self.addCleanup(cleanup)
        def events():
            with closing(sqlite3.connect((case.data/'tasks.sqlite').as_uri()+'?mode=ro',uri=True)) as db:
                return db.execute('SELECT eventId,payloadHash,state,receipt FROM mind_project_outbox ORDER BY sequence').fetchall()
        before=events();self.assertEqual(len(before),2);self.assertTrue(all(row[2]=='saved' for row in before))
        protected=[Path(case.reader.reader_data['credentialPath']),Path(case.fixture.base.value['credentialPath']),
            Path(case.reader.reader_data['terminalPath']),Path(case.fixture.base.value['terminalPath']),Path(case.fixture.base.value['keyEnrollmentPath'])]
        protected_hashes={str(path):launch.digest(path) for path in protected}
        runtime=case.reader.reader_data['runtime'];root=case.root
        cp=dict(schema=launch.CAPTURE_SCHEMA,workspace=str(workspace),pythonExecutable=sys.executable,
            nodeExecutable=p['nodeExecutable'],pythonSha256=p['pythonSha256'],nodeSha256=p['nodeSha256'],
            runtime=runtime,ownerSid=case.reader.reader_data['ownerSid'],pwshSha256=launch.digest(runtime['pwsh']),
            sourceHashes={str(path):launch.digest(path) for path in launch.capture_source_paths(runtime)},settings=p['settings'],
            attemptPath=str(root/'capture-attempt.json'),stdoutPath=str(root/'capture-out.log'),stderrPath=str(root/'capture-err.log'),
            projectCapture=dict(schema='onoes-mesh-native-project-capture/v1',source=p['projectSync']['source'],
                storeId=case.reader.reader_data['binding']['store_id'],links=p['projectSync']['links']))
        capture_profile=root/'capture-profile.json';roles.private_new_json(capture_profile,cp);capture_sha=launch.digest(capture_profile)
        capture_approval=root/'capture-approval.json';roles.private_new_json(capture_approval,dict(
            schema='onoes-mesh-offline-capture-approval/v1',decision='approve_exact_workroom_offline_capture',
            ownerSid=cp['ownerSid'],workspace=str(workspace),profileSha256=capture_sha))
        np=copy.deepcopy(p)
        for field in ('attemptPath','stdoutPath','stderrPath'):np[field]=str(root/('connected-'+field))
        connected_profile=root/'connected-profile.json';roles.private_new_json(connected_profile,np);connected_sha=launch.digest(connected_profile)
        for path in (case.reader.approval,case.fixture.base.approval):
            accepted=json.loads(path.read_text());accepted['profiles'].append(connected_sha);path.write_text(json.dumps(accepted))
        managed=root/'managed-reader.json'
        roles.private_new_json(managed,dict(schema=reader_service.SCHEMA,
            sourceHashes={str(path):launch.digest(path) for path in (Path(reader_service.__file__).resolve(),reader_service.HERE/'recall_process_candidate.py')},
            readerProfilePath=str(case.reader.reader),readerProfileSha256=case.reader.reader_sha,
            attemptPath=str(root/'managed-reader-attempt.json'),stopPath=str(root/'managed-reader-stop')))
        managed_sha=launch.digest(managed);accepted=json.loads(case.reader.approval.read_text());accepted['profiles'].append(managed_sha);case.reader.approval.write_text(json.dumps(accepted))
        handoff=root/'handoff-approval.json'
        approved=dict(schema='onoes-mesh-capture-handoff-approval/v1',decision='approve_exact_capture_to_connected_handoff',
            workspace=str(workspace),ownerSid=cp['ownerSid'],pythonSha256=launch.digest(sys.executable),
            sourceHashes={str(workspace/'integrations'/name):launch.digest(workspace/'integrations'/name) for name in recovery.FILES},
            capture=dict(profilePath=str(capture_profile),profileSha256=capture_sha,approvalPath=str(capture_approval),approvalSha256=launch.digest(capture_approval)),
            connected=dict(profilePath=str(connected_profile),profileSha256=connected_sha,approvalPath=str(case.reader.approval),
                approvalSha256=launch.digest(case.reader.approval),projectApprovalPath=str(case.fixture.base.approval),
                projectApprovalSha256=launch.digest(case.fixture.base.approval)))
        roles.private_new_json(handoff,approved);handoff_sha=launch.digest(handoff)
        def address(profile,child):
            def listening():
                for line in Path(profile['stdoutPath']).read_text().splitlines():
                    try:row=json.loads(line)
                    except ValueError:continue
                    if row.get('event')=='mesh_listening' and row.get('pid')==child.pid:return row['url']
            return case.wait_for(listening,child)
        with MeshLauncherWindow(workspace,launch.digest(workspace/'integrations/restart-workroom-preview.ps1')) as window:
            window.publish_native_owner(old_gateway,roles.creation_ticks(old_gateway._handle),original_profile,original_sha,previous_sha256=None)
            for child in (old_gateway,old_reader,old_writer):child.terminate();child.wait(timeout=30)
            case.mesh=None;phase('only_original_synthetic_services_retired')
            # Offline launch must not call any reader enrollment/access methods.
            with patch.object(roles,'approved_profile',side_effect=AssertionError('capture used reader profile')), \
                 patch.object(roles,'native_options',side_effect=AssertionError('capture used reader access')):
                capture,ticks,record=launch.launch_mesh(capture_profile,capture_sha,capture_approval)
            new_children.append(capture);base=address(cp,capture)
            window.publish_native_owner(capture,ticks,capture_profile,capture_sha,previous_sha256=launch.digest(receipt),
                beforeimage_path=workspace/'data'/'original-before-capture.json')
            request=fixtures.admitted_http(base);token=request('/api/trial-session/bootstrap',{})['csrfToken'];card=p['projectSync']['links'][0]['cardId']
            self.assertEqual(request('/api/workroom/'+card,csrf=token,method='GET')['memorySync']['state'],'offline')
            task=request('/api/tasks/'+card,csrf=token,method='GET')['task']
            request('/api/tasks/'+card,fixtures.edited_card(task,'Handoff offline edit retained'),token,method='PATCH')
            pending=events();self.assertEqual(pending[:2],before);self.assertEqual(len(pending),3);self.assertEqual(pending[-1][2],'pending')
            request('/api/trial-session/logout',{},token);phase('offline_edit_persisted_with_original_receipts')
            reader,reader_ticks=reader_service.launch_service(managed,managed_sha,case.reader.approval);new_children.append(reader)
            writer,writer_ticks=writer_service.launch_service(case.fixture.profile,case.fixture.sha,case.fixture.base.approval);new_children.append(writer)
            def roles_ready():
                self.assertIsNone(reader.poll());self.assertIsNone(writer.poll())
                return (reader_service.service_state(managed,managed_sha,case.reader.approval)['ready']
                    and writer_service.service_state(case.fixture.profile,case.fixture.sha,case.fixture.base.approval)['ready'])
            case.wait_for(roles_ready,reader,timeout=180);phase('same_grant_memory_roles_restored')
            # Interrupt only final ownership publication, after native input was
            # durably delivered. Keep that original Popen through reconciliation.
            publish=window.publish_native_owner
            interrupted=[]
            def interrupt_connected(*args,**kwargs):
                if Path(args[2])==connected_profile:
                    interrupted.append(args[0].pid)
                    raise RuntimeError('synthetic publication interruption')
                return publish(*args,**kwargs)
            with patch.object(window,'publish_native_owner',side_effect=interrupt_connected):
                with self.assertRaises(recovery.CaptureHandoffUnknown) as held:
                    recovery.handoff_capture_to_connected(window,launch=launch,service=writer_service,roles=roles,
                        approval_path=handoff,approval_sha=handoff_sha)
            connected=held.exception.pair.mesh;self.assertIsNotNone(connected);new_children.append(connected)
            self.assertEqual(interrupted,[connected.pid])
            self.assertIsNone(connected.poll());self.assertIsNotNone(capture.poll());phase('original_connected_child_retained_after_publication_interruption')
            state,extra=recovery.handoff_capture_to_connected(window,launch=launch,service=writer_service,roles=roles,
                approval_path=handoff,approval_sha=handoff_sha)
            self.assertIsNone(extra);self.assertEqual(state['pid'],connected.pid)
            self.assertEqual(json.loads(receipt.read_text())['Id'],connected.pid)
            request=fixtures.admitted_http(address(np,connected));token=request('/api/trial-session/bootstrap',{})['csrfToken']
            try:
                after=case.wait_for(lambda:events() if len(events())==3 and all(row[2]=='saved' for row in events()) else None,connected)
                self.assertEqual(after[:2],before);self.assertEqual(after[-1][:2],pending[-1][:2])
                recalled=request('/api/mind/recall',dict(query='Handoff offline edit',limit=8),token)
                self.assertIn('Handoff offline edit retained',json.dumps(recalled));self.assertNotIn('EXCLUDED-PRIVATE-PROSE',json.dumps(recalled))
            finally:request('/api/trial-session/logout',{},token)
            self.assertEqual({str(path):launch.digest(path) for path in protected},protected_hashes)
            with closing(sqlite3.connect(case.reader.database.as_uri()+'?mode=ro',uri=True)) as db:
                self.assertEqual(db.execute('SELECT count(*) FROM project_sync_events').fetchone()[0],3)
            phase('same_event_canonical_catch_up_and_exact_owner_reconciled')
        proof=dict(schema='onoes-mesh-synthetic-capture-handoff-proof/v1',syntheticOnly=True,liveChanged=False,
            offlineCardSaved=True,sameEventAndOriginalReceiptsPreserved=True,canonicalCatchUpPassed=True,
            interruptedPublicationReconciledSameChild=True,noReplacementLaunch=True,privateFieldExcluded=True,
            publicationFaultReached=True,
            credentialTerminalAndKeyPackageHashesUnchanged=True,canonicalEventCount=3,
            handoffSourceHashes=approved['sourceHashes'],captureSourceHashes=cp['sourceHashes'],connectedSourceHashes=np['sourceHashes'])
        (workspace.parent/'HANDOFF-PROOF.json').write_text(json.dumps(proof,indent=2),encoding='utf-8')


if __name__=='__main__':unittest.main()
