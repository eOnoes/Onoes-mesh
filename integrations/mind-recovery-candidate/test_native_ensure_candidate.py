"""Opt-in real PowerShell Ensure against a separately copied synthetic workspace."""
import hashlib
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
if os.name=='nt':import _winapi

import mesh_launch_candidate as launch
import project_service_process_candidate as service
import recall_process_candidate as roles
import test_project_mesh_input_candidate as fixtures

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from mesh_launcher_window import MeshLauncherWindow
import mesh_recovery_candidate as recovery


class OwnedTestGateway:
    """Cleanup only the exact fresh synthetic child launched through Ensure."""
    def __init__(self,pid,ticks):
        self.pid=pid;self.ticks=ticks
        self._handle=_winapi.OpenProcess(0x100000|0x1000|1,False,pid)
        assert roles.creation_ticks(self._handle)==ticks
    def poll(self):
        return None if _winapi.WaitForSingleObject(self._handle,0)==258 else _winapi.GetExitCodeProcess(self._handle)
    def terminate(self):
        assert roles.creation_ticks(self._handle)==self.ticks
        _winapi.TerminateProcess(self._handle,1)
    def wait(self,timeout):
        assert _winapi.WaitForSingleObject(self._handle,int(timeout*1000))==0
        return _winapi.GetExitCodeProcess(self._handle)
    def close(self):_winapi.CloseHandle(self._handle)


@unittest.skipUnless(os.name=='nt' and os.environ.get('MESH_NATIVE_ENSURE_WORKSPACE'),
                     'Explicit isolated synthetic workspace only')
class NativeEnsureTests(unittest.TestCase):
    def test_named_ensure_reuses_binding_and_reconciles_unpublished_living_attempt(self):
        expected=Path(os.environ['MESH_NATIVE_ENSURE_WORKSPACE']).resolve()
        self.assertEqual(launch.ROOT,expected)
        self.assertTrue(expected.parent.name.startswith('mesh-native-ensure-'))
        self.assertEqual(recovery.ROOT,expected)
        self.assertFalse((expected.parent/'workroom-ab-preview-process.json').exists())
        (expected/'data').mkdir(exist_ok=True)
        def phase(name):print('Synthetic Ensure phase: '+name,flush=True)
        phase('baseline_start')
        case=fixtures.ProjectMeshLauncherTests();self.addCleanup(case.doCleanups);case.setUp()
        actual=launch.launch_mesh
        def fixed_port(profile,sha,approval):
            p=json.loads(Path(profile).read_text())
            with socket.socket() as sock:
                sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
            p['settings']['MESH_PREVIEW_PORT']=str(port)
            Path(profile).write_text(json.dumps(p),encoding='utf-8');sha=launch.digest(profile)
            for target in (case.reader.approval,case.fixture.base.approval):
                approved=json.loads(target.read_text());approved['profiles'].append(sha)
                target.write_text(json.dumps(approved),encoding='utf-8')
            return actual(profile,sha,approval)
        with patch.object(launch,'launch_mesh',side_effect=fixed_port):
            case.test_exact_profiles_preflight_then_owned_gateway_delivers_only_approved_fields()
        phase('baseline_delivered')
        profile=case.root/'mesh-launch.json';sha=launch.digest(profile);p=json.loads(profile.read_text())
        writer=case.fixture.children[-1][0];writer_ticks=roles.creation_ticks(writer._handle)
        credential=Path(case.fixture.base.value['credentialPath']);credential_sha=roles.digest(credential)
        reader=json.loads(Path(p['readerProfile']).read_text())
        approval_path=case.root/'native-recovery-approval.json'
        approval=dict(schema='onoes-mesh-native-recovery-approval/v1',
            decision='approve_exact_same_grant_gateway_recovery',ownerSid=reader['ownerSid'],
            workspace=str(expected),profilePath=str(profile),profileSha256=sha,
            pythonSha256=launch.digest(sys.executable),
            sourceHashes={str(expected/'integrations'/name):launch.digest(expected/'integrations'/name)
                          for name in recovery.FILES})
        roles.private_new_json(approval_path,approval)
        original=case.mesh;original_ticks=roles.creation_ticks(original._handle)
        with MeshLauncherWindow(expected,launch.digest(expected/'integrations/restart-workroom-preview.ps1')) as window:
            window.publish_native_owner(original,original_ticks,profile,sha,previous_sha256=None)
        receipt_path=expected.parent/'workroom-ab-preview-process.json';old_receipt=receipt_path.read_bytes()
        def cleanup_attempt():
            attempt_path=Path(p['attemptPath'])
            if not attempt_path.is_file():return
            record=json.loads(attempt_path.read_text())
            if (record.get('profileSha256')==sha and record.get('state')=='input_sent'
                    and record.get('pid')!=original.pid
                    and roles.same_process_alive(record['pid'],record['creationTicks'])):
                owned=OwnedTestGateway(record['pid'],record['creationTicks'])
                try:owned.terminate();owned.wait(30)
                finally:owned.close()
        self.addCleanup(cleanup_attempt)
        legacy=expected/'data/workroom-preview';legacy.mkdir()
        source=sqlite3.connect((case.data/'tasks.sqlite').as_uri()+'?mode=ro',uri=True)
        copied=sqlite3.connect(legacy/'tasks.sqlite')
        try:source.backup(copied)
        finally:copied.close();source.close()
        def events():
            db=sqlite3.connect((case.data/'tasks.sqlite').as_uri()+'?mode=ro',uri=True)
            try:return db.execute('SELECT eventId,payloadHash,state,receipt FROM mind_project_outbox ORDER BY sequence').fetchall()
            finally:db.close()
        before=case.wait_for(lambda:events() if len(events())==2 and all(row[2]=='saved' for row in events()) else None,original)
        command=[reader['runtime']['pwsh'],'-NoLogo','-NoProfile','-NonInteractive','-File',
            str(expected/'integrations/restart-workroom-preview.ps1'),'-Action','Ensure',
            '-NativeMindProfile',str(profile),'-NativeMindSha256',sha,'-NativeMindApproval',str(case.reader.approval),
            '-NativeRecoveryApproval',str(approval_path),'-NativeRecoverySha256',roles.digest(approval_path)]
        def ensure(ok=True):
            result=subprocess.run(command,capture_output=True,text=True,timeout=300,creationflags=subprocess.CREATE_NO_WINDOW)
            if ok:self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            else:self.assertNotEqual(result.returncode,0)
            rows=[json.loads(line) for line in result.stdout.splitlines() if line.startswith('{')]
            self.assertEqual(len(rows),1,result.stdout+result.stderr)
            return rows[0]
        running=ensure();self.assertEqual(running['state'],'running');self.assertEqual(running['pid'],original.pid)
        self.assertEqual(receipt_path.read_bytes(),old_receipt);phase('healthy_ensure_kept_owner')
        original.terminate();original.wait(timeout=30)
        recovered=ensure();self.assertEqual(recovered['state'],'recovered')
        self.assertNotEqual((recovered['pid'],recovered['creationTicks']),(original.pid,original_ticks))
        observed=OwnedTestGateway(recovered['pid'],recovered['creationTicks']);case.mesh=observed
        def cleanup_gateway():
            try:
                if observed.poll() is None:observed.terminate();observed.wait(30)
            finally:observed.close();case.mesh=None
        self.addCleanup(cleanup_gateway)
        self.assertEqual(events(),before);phase('crashed_gateway_recovered')
        # Model loss of publication after the new attempt had already started.
        # This is synthetic metadata only, within this unique copied workspace.
        receipt_path.write_bytes(old_receipt)
        reconciled=ensure();self.assertEqual(reconciled['state'],'reconciled')
        self.assertEqual(reconciled['pid'],observed.pid)
        running=ensure();self.assertEqual(running['state'],'running');self.assertEqual(running['pid'],observed.pid)
        self.assertEqual(events(),before);self.assertEqual(roles.digest(credential),credential_sha)
        self.assertIsNone(writer.poll());self.assertEqual(roles.creation_ticks(writer._handle),writer_ticks)
        phase('uncertain_publication_reconciled_same_attempt')
        with sqlite3.connect(case.data/'tasks.sqlite') as db:
            self.assertEqual(db.execute('SELECT count(*) FROM mind_project_outbox').fetchone()[0],2)
        service.request_stop(case.fixture.profile,case.fixture.sha,case.fixture.base.approval)
        self.assertEqual(writer.wait(timeout=60),0)
        held=ensure(False);self.assertEqual(held['state'],'held')
        self.assertIsNone(observed.poll());self.assertEqual(events(),before)
        phase('missing_writer_held_without_fallback')
        proof=dict(schema='onoes-mesh-synthetic-native-ensure/v1',syntheticOnly=True,liveChanged=False,
            healthyTickNoRestart=True,gatewayCrashRecovered=True,sameGrant=True,writerIdentityUnchanged=True,
            originalReceiptsPreserved=True,unpublishedLivingAttemptReconciled=True,
            repeatedTickNoDuplicate=True,missingWriterHeldWithoutLegacyFallback=True,
            automaticLiveRecoveryActivated=False,writerRestartQualified=False,
            sourceHashes=approval['sourceHashes'])
        (expected.parent/'ENSURE-PROOF.json').write_text(json.dumps(proof,indent=2),encoding='utf-8')


if __name__=='__main__':unittest.main()
