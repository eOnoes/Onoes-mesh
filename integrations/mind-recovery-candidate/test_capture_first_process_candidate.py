"""Actual capture-first command, held memory, catch-up and cheap healthy tick."""
from contextlib import closing
import json
import os
from pathlib import Path
import pstats
import socket
import sqlite3
import subprocess
import sys
import time
import unittest
from unittest.mock import patch

import mesh_launch_candidate as launch
import recall_process_candidate as roles
import reader_service_process_candidate as reader_service
import test_project_mesh_input_candidate as fixtures
from test_native_ensure_candidate import OwnedTestGateway

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from mesh_launcher_window import MeshLauncherWindow
import mesh_recovery_candidate as recovery
import mesh_startup_candidate as startup


@unittest.skipUnless(os.name=='nt' and os.environ.get('MESH_CAPTURE_FIRST_WORKSPACE'),
                     'Explicit isolated copied capture-first workspace required')
class CaptureFirstProcessTests(unittest.TestCase):
    def test_real_startup_keeps_local_board_when_memory_held_then_catches_up(self):
        ws=Path(os.environ['MESH_CAPTURE_FIRST_WORKSPACE']).resolve()
        self.assertEqual(ws,launch.ROOT);self.assertEqual(ws,startup.ROOT);self.assertEqual(ws,recovery.ROOT)
        self.assertTrue(ws.parent.name.startswith('mesh-capture-first-'))
        receipt=ws.parent/'workroom-ab-preview-process.json';self.assertFalse(receipt.exists())
        (ws/'data').mkdir(exist_ok=True)
        def phase(value):print('Synthetic capture-first: '+value,flush=True)
        phase('baseline_start')
        case=fixtures.ProjectMeshLauncherTests();self.addCleanup(case.doCleanups);case.setUp()
        original_launch=launch.launch_mesh
        def fixed_gateway(profile,sha,approval):
            p=json.loads(Path(profile).read_text())
            with socket.socket() as sock:sock.bind(('127.0.0.1',0));p['settings']['MESH_PREVIEW_PORT']=str(sock.getsockname()[1])
            Path(profile).write_text(json.dumps(p));sha=launch.digest(profile)
            for path in (case.reader.approval,case.fixture.base.approval):
                value=json.loads(path.read_text());value['profiles'].append(sha);path.write_text(json.dumps(value))
            return original_launch(profile,sha,approval)
        with patch.object(launch,'launch_mesh',side_effect=fixed_gateway):
            case.test_exact_profiles_preflight_then_owned_gateway_delivers_only_approved_fields()
        phase('baseline_delivered')
        profile=case.root/'mesh-launch.json';sha=launch.digest(profile);p=json.loads(profile.read_text());root=case.root
        def events():
            with closing(sqlite3.connect((case.data/'tasks.sqlite').as_uri()+'?mode=ro',uri=True)) as db:
                return db.execute('SELECT eventId,payloadHash,state,receipt FROM mind_project_outbox ORDER BY sequence').fetchall()
        before=events();self.assertEqual(len(before),2)
        protected=[Path(case.reader.reader_data['credentialPath']),Path(case.fixture.base.value['credentialPath']),
            Path(case.reader.reader_data['terminalPath']),Path(case.fixture.base.value['terminalPath']),Path(case.fixture.base.value['keyEnrollmentPath'])]
        protected_hashes={str(path):launch.digest(path) for path in protected}
        runtime=case.reader.reader_data['runtime']
        cp=dict(schema=launch.CAPTURE_SCHEMA,workspace=str(ws),pythonExecutable=sys.executable,nodeExecutable=p['nodeExecutable'],
            pythonSha256=p['pythonSha256'],nodeSha256=p['nodeSha256'],runtime=runtime,ownerSid=case.reader.reader_data['ownerSid'],
            pwshSha256=launch.digest(runtime['pwsh']),sourceHashes={str(path):launch.digest(path) for path in launch.capture_source_paths(runtime)},
            settings=p['settings'],attemptPath=str(root/'capture-attempt.json'),stdoutPath=str(root/'capture-out.log'),stderrPath=str(root/'capture-err.log'),
            projectCapture=dict(schema='onoes-mesh-native-project-capture/v1',source=p['projectSync']['source'],
                storeId=case.reader.reader_data['binding']['store_id'],links=p['projectSync']['links']))
        capture_profile=root/'capture-profile.json';roles.private_new_json(capture_profile,cp);capture_sha=launch.digest(capture_profile)
        capture_approval=root/'capture-approval.json';roles.private_new_json(capture_approval,dict(schema='onoes-mesh-offline-capture-approval/v1',
            decision='approve_exact_workroom_offline_capture',ownerSid=cp['ownerSid'],workspace=str(ws),profileSha256=capture_sha))
        managed=root/'managed-reader.json';managed_attempt=root/'managed-reader-attempt.json'
        roles.private_new_json(managed,dict(schema=reader_service.SCHEMA,
            sourceHashes={str(path):launch.digest(path) for path in (Path(reader_service.__file__).resolve(),reader_service.HERE/'recall_process_candidate.py')},
            readerProfilePath=str(case.reader.reader),readerProfileSha256=case.reader.reader_sha,
            attemptPath=str(managed_attempt),stopPath=str(root/'managed-reader-stop')))
        managed_sha=launch.digest(managed);value=json.loads(case.reader.approval.read_text());value['profiles'].append(managed_sha);case.reader.approval.write_text(json.dumps(value))
        handoff=root/'handoff.json';roles.private_new_json(handoff,dict(schema='onoes-mesh-capture-handoff-approval/v1',
            decision='approve_exact_capture_to_connected_handoff',workspace=str(ws),ownerSid=cp['ownerSid'],pythonSha256=launch.digest(sys.executable),
            sourceHashes={str(ws/'integrations'/name):launch.digest(ws/'integrations'/name) for name in recovery.FILES},
            capture=dict(profilePath=str(capture_profile),profileSha256=capture_sha,approvalPath=str(capture_approval),approvalSha256=launch.digest(capture_approval)),
            connected=dict(profilePath=str(profile),profileSha256=sha,approvalPath=str(case.reader.approval),approvalSha256=launch.digest(case.reader.approval),
                projectApprovalPath=str(case.fixture.base.approval),projectApprovalSha256=launch.digest(case.fixture.base.approval))))
        memory=root/'memory-recovery.json';roles.private_new_json(memory,dict(schema='onoes-mesh-native-recovery-approval/v1',
            decision='approve_exact_same_grant_memory_recovery',ownerSid=cp['ownerSid'],workspace=str(ws),profilePath=str(profile),profileSha256=sha,
            pythonSha256=launch.digest(sys.executable),readerServiceProfile=str(managed),readerServiceSha256=managed_sha,
            sourceHashes={**{str(ws/'integrations'/name):launch.digest(ws/'integrations'/name) for name in recovery.FILES},
                str(Path(reader_service.__file__).resolve()):launch.digest(reader_service.__file__)}))
        approval=root/'startup.json';approved=dict(schema='onoes-mesh-capture-first-approval/v1',decision='approve_exact_capture_first_recovery',
            workspace=str(ws),ownerSid=cp['ownerSid'],pythonSha256=launch.digest(sys.executable),
            sourceHashes={str(ws/'integrations'/name):launch.digest(ws/'integrations'/name) for name in startup.SOURCES},
            handoffApprovalPath=str(handoff),handoffApprovalSha256=launch.digest(handoff),memoryApprovalPath=str(memory),memoryApprovalSha256=launch.digest(memory))
        roles.private_new_json(approval,approved);approval_sha=launch.digest(approval)
        with MeshLauncherWindow(ws,launch.digest(ws/'integrations/restart-workroom-preview.ps1')) as window:
            window.publish_native_owner(case.mesh,roles.creation_ticks(case.mesh._handle),profile,sha,previous_sha256=None)
            old_reader=roles.reader_state(case.reader.reader,case.reader.reader_sha,case.reader.approval)
            import project_service_process_candidate as service
            old_writer=service.service_state(case.fixture.profile,case.fixture.sha,case.fixture.base.approval)
            actors=[case.mesh,next(child for child in case.reader.children if child.pid==old_reader['pid']),
                next(child for child,ticks in case.fixture.children if child.pid==old_writer['pid'])]
            for child in actors:child.terminate();child.wait(timeout=30)
            case.mesh=None
        # Fault injection only: no actor was launched for this reserved record.
        # The startup command must preserve it and leave capture usable.
        roles.private_new_json(managed_attempt,dict(schema='onoes-mind-reader-service-attempt/v1',
            profileSha256=managed_sha,state='reserved'))
        reserved=managed_attempt.read_bytes();refs=[]
        def cleanup():
            for ref in reversed(refs):
                try:
                    if ref.poll() is None:ref.terminate();ref.wait(30)
                finally:ref.close()
        self.addCleanup(cleanup)
        def attach(path,expected):
            if not Path(path).is_file():return
            record=json.loads(Path(path).read_text())
            if record.get('profileSha256')==expected and record.get('state') in ('started','input_sent') and roles.same_process_alive(record['pid'],record['creationTicks']):
                if not any(ref.pid==record['pid'] for ref in refs):refs.append(OwnedTestGateway(record['pid'],record['creationTicks']))
        def command(label,profile_output=None):
            args=[sys.executable,'-I']
            if profile_output:args+=['-m','cProfile','-o',str(profile_output)]
            args += [str(ws/'integrations/mesh_startup_candidate.py'),'--approval',str(approval),'--sha256',approval_sha]
            start=time.monotonic();child=subprocess.Popen(args,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,creationflags=subprocess.CREATE_NO_WINDOW)
            try:
                while True:
                    try:out,err=child.communicate(timeout=30);break
                    except subprocess.TimeoutExpired:phase(label+'_same_command_'+str(int(time.monotonic()-start))+'s')
                (ws.parent/(label+'-RESULT.json')).write_text(json.dumps(dict(code=child.returncode,seconds=time.monotonic()-start,stdout=out,stderr=err),indent=2))
                self.assertEqual(child.returncode,0,out+err);return json.loads(out)
            finally:
                for path,expected in [(cp['attemptPath'],capture_sha),(p['attemptPath'],sha),
                    (managed_attempt,managed_sha),(case.fixture.value['attemptPath'],case.fixture.sha)]:attach(path,expected)
        first=command('HELD-MEMORY');self.assertEqual(first['state'],'capture_pending')
        self.assertEqual(managed_attempt.read_bytes(),reserved);self.assertEqual(events(),before)
        capture_record=json.loads(Path(cp['attemptPath']).read_text());self.assertEqual(json.loads(receipt.read_text())['Id'],capture_record['pid'])
        def backend(p,pid):
            for line in Path(p['stdoutPath']).read_text().splitlines():
                try:row=json.loads(line)
                except ValueError:continue
                if row.get('event')=='mesh_listening' and row.get('pid')==pid:return row['url']
            self.fail('Exact backend was not logged')
        request=fixtures.admitted_http(backend(cp,capture_record['pid']));token=request('/api/trial-session/bootstrap',{})['csrfToken'];card=p['projectSync']['links'][0]['cardId']
        self.assertEqual(request('/api/workroom/'+card,csrf=token,method='GET')['memorySync']['state'],'offline')
        task=request('/api/tasks/'+card,csrf=token,method='GET')['task'];request('/api/tasks/'+card,fixtures.edited_card(task,'Bootproof offline edit saved'),token,method='PATCH')
        request('/api/trial-session/logout',{},token);pending=events();self.assertEqual(pending[:2],before);self.assertEqual(pending[-1][2],'pending')
        phase('local_board_usable_while_unresolved_memory_attempt_preserved')
        # Remove only the known never-launched injected stub from the test's
        # counterfactual state, preserving its bytes. Runtime does not do this.
        fault_archive=root/'injected-reserved-record-preserved.json';managed_attempt.rename(fault_archive)
        self.assertEqual(fault_archive.read_bytes(),reserved)
        second=command('RESTORE-MEMORY');self.assertEqual(second.get('startupMode'),'connected')
        connected=json.loads(Path(p['attemptPath']).read_text());self.assertEqual(second['pid'],connected['pid'])
        request=fixtures.admitted_http(backend(p,connected['pid']));token=request('/api/trial-session/bootstrap',{})['csrfToken']
        try:
            after=case.wait_for(lambda:events() if len(events())==3 and all(row[2]=='saved' for row in events()) else None)
            self.assertEqual(after[:2],before);self.assertEqual(after[-1][:2],pending[-1][:2])
            recall=request('/api/mind/recall',dict(query='bootproof',limit=8),token)
            self.assertIn('Bootproof offline edit saved',json.dumps(recall));self.assertNotIn('EXCLUDED-PRIVATE-PROSE',json.dumps(recall))
        finally:request('/api/trial-session/logout',{},token)
        receipt_before=receipt.read_bytes();warm_profile=ws.parent/'WARM.pstats';warm=command('WARM',warm_profile)
        self.assertEqual(warm['state'],'observed_running');self.assertEqual(warm['pid'],connected['pid']);self.assertEqual(warm['processChanges'],0)
        self.assertEqual(receipt.read_bytes(),receipt_before);self.assertEqual(events(),after)
        stats=pstats.Stats(str(warm_profile));private_calls=sum(value[1] for (file,line,name),value in stats.stats.items() if name=='qualify_private_storage')
        self.assertEqual(private_calls,0);self.assertEqual({str(path):launch.digest(path) for path in protected},protected_hashes)
        phase('automatic_same_grant_catch_up_and_observation_only_warm_tick_passed')
        proof=dict(schema='onoes-mesh-synthetic-capture-first-proof/v1',syntheticOnly=True,liveChanged=False,
            localBoardSurvivedMemoryHold=True,unresolvedAttemptPreserved=True,sameGrantRecoveryAndCatchUp=True,
            originalEventIdsAndReceiptsPreserved=True,warmTickNoProcessChanges=True,warmTickPrivateChecks=0,
            protectedCredentialTerminalKeyHashesUnchanged=True,privateFieldExcluded=True,sourceHashes=approved['sourceHashes'],
            captureSourceHashes=cp['sourceHashes'],connectedSourceHashes=p['sourceHashes'])
        (ws.parent/'STARTUP-PROOF.json').write_text(json.dumps(proof,indent=2))


if __name__=='__main__':unittest.main()
