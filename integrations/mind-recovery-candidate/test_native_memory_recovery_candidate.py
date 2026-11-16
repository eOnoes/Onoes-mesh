"""Actual combined memory recovery, restricted to an explicitly copied workspace."""
import json
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys
import time
import unittest
from unittest.mock import patch

import mesh_launch_candidate as launch
import reader_service_process_candidate as reader_service
import project_service_process_candidate as writer_service
import recall_process_candidate as roles
import test_project_mesh_input_candidate as fixtures
from test_native_ensure_candidate import OwnedTestGateway

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from mesh_launcher_window import MeshLauncherWindow
import mesh_recovery_candidate as recovery


@unittest.skipUnless(os.name=='nt' and os.environ.get('MESH_NATIVE_MEMORY_WORKSPACE'),
                     'Explicit isolated synthetic memory recovery only')
class MemoryRecoveryTests(unittest.TestCase):
    def test_terminated_memory_roles_refresh_gateway_and_new_card_update_reaches_canonical_mind(self):
        workspace=Path(os.environ['MESH_NATIVE_MEMORY_WORKSPACE']).resolve()
        self.assertEqual(workspace,launch.ROOT);self.assertEqual(workspace,recovery.ROOT)
        self.assertTrue(workspace.parent.name.startswith('mesh-native-memory-'))
        self.assertFalse((workspace.parent/'workroom-ab-preview-process.json').exists())
        (workspace/'data').mkdir(exist_ok=True)
        def phase(value):print('Synthetic full memory phase: '+value,flush=True)
        phase('baseline_start')
        case=fixtures.ProjectMeshLauncherTests();self.addCleanup(case.doCleanups);case.setUp()
        original_launch=launch.launch_mesh
        def fixed_gateway(profile,sha,approval):
            value=json.loads(Path(profile).read_text())
            with socket.socket() as sock:
                sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
            value['settings']['MESH_PREVIEW_PORT']=str(port)
            Path(profile).write_text(json.dumps(value));sha=launch.digest(profile)
            for path in (case.reader.approval,case.fixture.base.approval):
                accepted=json.loads(path.read_text());accepted['profiles'].append(sha);path.write_text(json.dumps(accepted))
            return original_launch(profile,sha,approval)
        with patch.object(launch,'launch_mesh',side_effect=fixed_gateway):
            case.test_exact_profiles_preflight_then_owned_gateway_delivers_only_approved_fields()
        phase('baseline_delivered')
        profile=case.root/'mesh-launch.json';sha=launch.digest(profile);p=json.loads(profile.read_text())
        original_gateway=case.mesh;gateway_ticks=roles.creation_ticks(original_gateway._handle)
        reader_state=roles.reader_state(case.reader.reader,case.reader.reader_sha,case.reader.approval)
        writer_state=writer_service.service_state(case.fixture.profile,case.fixture.sha,case.fixture.base.approval)
        old_reader=next(child for child in case.reader.children if child.pid==reader_state['pid'])
        old_writer=next(child for child,ticks in case.fixture.children if child.pid==writer_state['pid'])
        self.assertEqual(roles.creation_ticks(old_reader._handle),reader_state['creationTicks'])
        self.assertEqual(roles.creation_ticks(old_writer._handle),writer_state['creationTicks'])
        reader_profile=case.root/'managed-reader.json'
        managed=dict(schema=reader_service.SCHEMA,sourceHashes={str(path):reader_service.digest(path) for path in
            (Path(reader_service.__file__).resolve(),reader_service.HERE/'recall_process_candidate.py')},
            readerProfilePath=str(case.reader.reader),readerProfileSha256=case.reader.reader_sha,
            attemptPath=str(case.root/'managed-reader-attempt.json'),stopPath=str(case.root/'managed-reader-stop'))
        roles.private_new_json(reader_profile,managed);reader_sha=roles.digest(reader_profile)
        accepted=json.loads(case.reader.approval.read_text());accepted['profiles'].append(reader_sha)
        case.reader.approval.write_text(json.dumps(accepted))
        reader_value=json.loads(Path(p['readerProfile']).read_text())
        recovery_profile=case.root/'memory-recovery-approval.json'
        approval=dict(schema='onoes-mesh-native-recovery-approval/v1',
            decision='approve_exact_same_grant_memory_recovery',ownerSid=reader_value['ownerSid'],
            workspace=str(workspace),profilePath=str(profile),profileSha256=sha,
            pythonSha256=roles.digest(sys.executable),readerServiceProfile=str(reader_profile),readerServiceSha256=reader_sha,
            sourceHashes={str(workspace/'integrations'/name):roles.digest(workspace/'integrations'/name) for name in recovery.FILES})
        approval['sourceHashes'][str(Path(reader_service.__file__).resolve())]=roles.digest(reader_service.__file__)
        roles.private_new_json(recovery_profile,approval)
        with MeshLauncherWindow(workspace,roles.digest(workspace/'integrations/restart-workroom-preview.ps1')) as window:
            window.publish_native_owner(original_gateway,gateway_ticks,profile,sha,previous_sha256=None)
        legacy=workspace/'data/workroom-preview';legacy.mkdir()
        source=sqlite3.connect((case.data/'tasks.sqlite').as_uri()+'?mode=ro',uri=True);copy=sqlite3.connect(legacy/'tasks.sqlite')
        try:source.backup(copy)
        finally:copy.close();source.close()
        def events():
            db=sqlite3.connect((case.data/'tasks.sqlite').as_uri()+'?mode=ro',uri=True)
            try:return db.execute('SELECT eventId,payloadHash,state,receipt FROM mind_project_outbox ORDER BY sequence').fetchall()
            finally:db.close()
        before=case.wait_for(lambda:events() if len(events())==2 and all(row[2]=='saved' for row in events()) else None,original_gateway)
        protected=[Path(case.reader.reader_data['credentialPath']),Path(case.fixture.base.value['credentialPath']),
                   Path(case.reader.reader_data['terminalPath']),Path(case.fixture.base.value['terminalPath']),
                   Path(case.fixture.base.value['keyEnrollmentPath'])]
        protected_hashes={str(path):roles.digest(path) for path in protected}
        command=[reader_value['runtime']['pwsh'],'-NoLogo','-NoProfile','-NonInteractive','-File',
            str(workspace/'integrations/restart-workroom-preview.ps1'),'-Action','Ensure',
            '-NativeMindProfile',str(profile),'-NativeMindSha256',sha,'-NativeMindApproval',str(case.reader.approval),
            '-NativeRecoveryApproval',str(recovery_profile),'-NativeRecoverySha256',roles.digest(recovery_profile)]
        def ensure(label):
            # An observation timeout is not command retirement. Keep the original
            # handle and pipes until terminal, rather than killing its wrapper.
            child=subprocess.Popen(command,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
                                   text=True,creationflags=subprocess.CREATE_NO_WINDOW)
            started=time.monotonic()
            evidence=workspace.parent/('ENSURE-'+label+'.json')
            while True:
                try:stdout,stderr=child.communicate(timeout=30);break
                except subprocess.TimeoutExpired:
                    elapsed=round(time.monotonic()-started,3)
                    evidence.write_text(json.dumps(dict(pid=child.pid,state='observing_same_command',
                        elapsedSeconds=elapsed,syntheticOnly=True)),encoding='utf-8')
                    phase(label+'_observing_same_command_'+str(int(elapsed))+'s')
            elapsed=round(time.monotonic()-started,3)
            evidence.write_text(json.dumps(dict(pid=child.pid,state='terminal',returncode=child.returncode,
                elapsedSeconds=elapsed,stdout=stdout,stderr=stderr,syntheticOnly=True),indent=2),encoding='utf-8')
            self.assertEqual(child.returncode,0,stdout+stderr)
            return json.loads(stdout)
        first=ensure('healthy');self.assertEqual(first['state'],'running');self.assertEqual(first['pid'],original_gateway.pid)
        self.assertEqual(first['memoryServicesRestarted'],0);phase('healthy_full_tick_kept_all_owners')
        old_reader.terminate();old_reader.wait(timeout=30);old_writer.terminate();old_writer.wait(timeout=30)
        self.assertIsNone(original_gateway.poll());phase('only_test_memory_roles_crashed')
        # Cleanup also handles a newly identified actor if a later assertion fails.
        refs=[]
        def cleanup_new():
            try:
                for reference in refs:
                    try:
                        if reference.poll() is None:reference.terminate();reference.wait(30)
                    finally:reference.close()
            finally:
                if original_gateway.poll() is None:case.mesh=original_gateway
                else:original_gateway.wait(timeout=30);case.mesh=None
        self.addCleanup(cleanup_new)
        def attach_known_attempt(path,expected_sha,expected_schema,old_pid):
            if not Path(path).is_file():return None
            record=json.loads(Path(path).read_text())
            if (record.get('schema')==expected_schema and record.get('profileSha256')==expected_sha
                and record.get('state') in ('started','input_sent') and record.get('pid')!=old_pid
                and roles.same_process_alive(record['pid'],record['creationTicks'])):
                reference=OwnedTestGateway(record['pid'],record['creationTicks']);refs.append(reference);return reference
            return None
        try:recovered=ensure('recovery')
        finally:
            gateway=attach_known_attempt(p['attemptPath'],sha,'onoes-mesh-native-child/v2',original_gateway.pid)
            new_reader=attach_known_attempt(managed['attemptPath'],reader_sha,'onoes-mind-reader-service-attempt/v1',old_reader.pid)
            new_writer=attach_known_attempt(case.fixture.value['attemptPath'],case.fixture.sha,'onoes-mind-project-service-attempt/v1',old_writer.pid)
        self.assertIsNotNone(gateway);self.assertIsNotNone(new_reader);self.assertIsNotNone(new_writer)
        case.mesh=gateway
        self.assertEqual(recovered['memoryServicesRestarted'],2);self.assertTrue(recovered['gatewayRefreshedForPeers'])
        self.assertEqual((recovered['pid'],recovered['readerPid'],recovered['writerPid']),
                         (gateway.pid,new_reader.pid,new_writer.pid))
        self.assertEqual(events(),before);self.assertIsNotNone(original_gateway.poll())
        attempt=json.loads(Path(p['attemptPath']).read_text());self.assertEqual(attempt['peers']['reader']['pid'],new_reader.pid)
        self.assertEqual(attempt['peers']['writer']['pid'],new_writer.pid)
        self.assertNotIn('token',json.dumps(attempt).lower());phase('roles_restored_gateway_refreshed_receipts_unchanged')
        repeat=ensure('repeat');self.assertEqual(repeat['pid'],gateway.pid);self.assertEqual(repeat['memoryServicesRestarted'],0)
        self.assertFalse(repeat['gatewayRefreshedForPeers']);self.assertEqual(events(),before)
        def listening():
            for line in Path(p['stdoutPath']).read_text().splitlines():
                try:row=json.loads(line)
                except ValueError:continue
                if row.get('event')=='mesh_listening' and row.get('pid')==gateway.pid:return row
        address=case.wait_for(listening,gateway);request=fixtures.admitted_http(address['url'])
        token=request('/api/trial-session/bootstrap',{})['csrfToken']
        try:
            card_id=p['projectSync']['links'][0]['cardId'];card=request('/api/tasks/'+card_id,csrf=token,method='GET')['task']
            request('/api/tasks/'+card_id,fixtures.edited_card(card,'Combined recovery saved title'),token,method='PATCH')
            after=case.wait_for(lambda:events() if len(events())==3 and all(row[2]=='saved' for row in events()) else None,gateway)
            self.assertEqual(after[:2],before)
            recalled=request('/api/mind/recall',dict(query='combined',limit=10),token)
            self.assertIn('Combined recovery saved title',json.dumps(recalled))
            self.assertNotIn('EXCLUDED-PRIVATE-PROSE',json.dumps(recalled))
        finally:request('/api/trial-session/logout',{},token)
        self.assertEqual({str(path):roles.digest(path) for path in protected},protected_hashes)
        with sqlite3.connect(case.reader.database.as_uri()+'?mode=ro',uri=True) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM project_sync_events').fetchone()[0],3)
        phase('new_card_edit_and_canonical_recall_passed')
        proof=dict(schema='onoes-mesh-synthetic-full-memory-recovery/v1',syntheticOnly=True,liveChanged=False,
            readerAndWriterRestored=True,exactGatewayRefreshed=True,originalReceiptsUnchanged=True,
            newEditAndCanonicalRecallPassed=True,privateFieldExcluded=True,credentialsTerminalsAndKeyPackageUnchanged=True,
            healthyRepeatNoDuplicate=True,canonicalEventCount=3,sourceHashes=approval['sourceHashes'],
            nativeLaunchSha256=roles.digest(launch.__file__),readerEnrollmentValidatorUnchanged=True)
        (workspace.parent/'MEMORY-RECOVERY-PROOF.json').write_text(json.dumps(proof,indent=2),encoding='utf-8')


if __name__=='__main__':unittest.main()
