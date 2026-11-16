"""Opt-in actual gateway recovery with a synthetic ledger and an unchanged grant."""
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
import unittest
import uuid

import test_project_mesh_input_candidate as fixtures
import mesh_launch_candidate as launch
import project_service_process_candidate as service
import recall_process_candidate as roles

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from mesh_launcher_window import MeshLauncherWindow
from mesh_native_recovery import archive_retired_mesh_attempt, NativeRecoveryHold


@unittest.skipUnless(os.name=='nt' and os.environ.get('MESH_NATIVE_RECOVERY_QUALIFY')=='1',
                     'Explicit synthetic recovery qualification only')
class GatewayRecoveryTests(unittest.TestCase):
    def test_retired_gateway_reuses_exact_profile_grant_and_receipts(self):
        case=fixtures.ProjectMeshLauncherTests();case.setUp();self.addCleanup(case.doCleanups)
        case.test_exact_profiles_preflight_then_owned_gateway_delivers_only_approved_fields()
        profile=case.root/'mesh-launch.json';sha=launch.digest(profile)
        p=json.loads(profile.read_text());source=case.data/'tasks.sqlite'
        credential=Path(case.fixture.base.value['credentialPath'])
        credential_sha=roles.digest(credential)
        writer=case.fixture.children[-1][0]
        writer_ticks=roles.creation_ticks(writer._handle)
        def source_events():
            db=sqlite3.connect(source.as_uri()+'?mode=ro',uri=True)
            try:return db.execute('SELECT eventId,payloadHash,state,receipt FROM mind_project_outbox ORDER BY sequence').fetchall()
            finally:db.close()
        original_events=source_events();self.assertEqual(len(original_events),2)
        self.assertTrue(all(row[2]=='saved' for row in original_events))
        original_mesh=case.mesh;original_ticks=roles.creation_ticks(original_mesh._handle)
        window=MeshLauncherWindow(launch.ROOT,launch.digest(launch.ROOT/'integrations/restart-workroom-preview.ps1'))
        with window:
            with self.assertRaises(NativeRecoveryHold):
                archive_retired_mesh_attempt(window,launch_module=launch,mesh_profile=profile,
                    mesh_sha256=sha,reader_approval=case.reader.approval)
            original_mesh.terminate();original_mesh.wait(timeout=30)
            before=[Path(p[key]).read_bytes() for key in ('attemptPath','stdoutPath','stderrPath')]
            retired=archive_retired_mesh_attempt(window,launch_module=launch,mesh_profile=profile,
                mesh_sha256=sha,reader_approval=case.reader.approval)
            self.assertEqual(retired['pid'],original_mesh.pid)
            self.assertEqual(retired['creationTicks'],original_ticks)
            self.assertEqual([Path(path).read_bytes() for path in retired['archives']],before)
            self.assertEqual(launch.digest(profile),sha)
            case.mesh,new_ticks,record=launch.launch_mesh(profile,sha,case.reader.approval)
            self.assertNotEqual((case.mesh.pid,new_ticks),(original_mesh.pid,original_ticks))
            self.assertEqual(record['state'],'input_sent')
            def listening():
                for line in Path(p['stdoutPath']).read_text().splitlines():
                    try:row=json.loads(line)
                    except ValueError:continue
                    if row.get('event')=='mesh_listening' and row.get('pid')==case.mesh.pid:return row
            address=case.wait_for(listening,case.mesh)
            request=fixtures.admitted_http(address['url'])
            token=request('/api/trial-session/bootstrap',{})['csrfToken']
            try:
                self.assertEqual(source_events(),original_events)
                self.assertIsNone(writer.poll());self.assertEqual(roles.creation_ticks(writer._handle),writer_ticks)
                self.assertEqual(roles.digest(credential),credential_sha)
                state=service.service_state(case.fixture.profile,case.fixture.sha,case.fixture.base.approval)
                self.assertTrue(state['ready']);self.assertEqual(state['pid'],writer.pid)
                card_id=p['projectSync']['links'][0]['cardId']
                card=request('/api/tasks/'+card_id,csrf=token,method='GET')['task']
                request('/api/tasks/'+card_id,fixtures.edited_card(card,'Launcher recovered with unchanged grant'),token,method='PATCH')
                rows=case.wait_for(lambda:source_events() if len(source_events())==3 and
                    all(r[2]=='saved' for r in source_events()) else None,case.mesh)
                self.assertEqual(rows[:2],original_events)
                recalled=request('/api/mind/recall',dict(query='recovered',limit=10),token)
                self.assertIn('Launcher recovered with unchanged grant',json.dumps(recalled))
                db=sqlite3.connect(case.reader.database.as_uri()+'?mode=ro',uri=True)
                try:self.assertEqual(db.execute('SELECT count(*) FROM project_sync_events').fetchone()[0],3)
                finally:db.close()
            finally:request('/api/trial-session/logout',{},token)
        proof=dict(schema='onoes-mesh-synthetic-gateway-recovery/v1',syntheticOnly=True,
            liveChanged=False,originalGatewayRefusedWhileAlive=True,originalHandleRetirementVerified=True,
            exactProfileReused=True,oldEvidencePreserved=True,writerOwnerUnchanged=True,
            grantCredentialUnchanged=True,originalReceiptsUnchanged=True,
            canonicalEventCount=3,postRecoveryEditAndRecallPassed=True,
            automaticLauncherWiring=False,writerCrashRecoveryQualified=False,
            recoveryToolSha256=hashlib.sha256((Path(__file__).resolve().parents[1]/'mesh_native_recovery.py').read_bytes()).hexdigest())
        proof_path=launch.ROOT/'data'/('project-gateway-recovery-proof-'+uuid.uuid4().hex+'.json')
        proof_path.write_text(json.dumps(proof,indent=2),encoding='utf-8')
        print('Synthetic recovery proof: '+str(proof_path),flush=True)


if __name__=='__main__':unittest.main()
