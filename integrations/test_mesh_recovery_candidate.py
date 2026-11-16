"""Recovery enrollment refusals; full actual launcher integration is separate."""
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from types import SimpleNamespace, ModuleType
import unittest
from unittest.mock import patch

import mesh_recovery_candidate as recovery


class RecoveryApprovalTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name).resolve();self.path=self.root/'approval.json'
        self.profile=self.root/'profile.json'
        self.value=dict(schema='onoes-mesh-native-recovery-approval/v1',
            decision='approve_exact_same_grant_gateway_recovery',ownerSid='synthetic-owner',
            workspace=str(recovery.ROOT),profilePath=str(self.profile),profileSha256='a'*64,
            pythonSha256=recovery.digest(sys.executable),
            sourceHashes={str(recovery.ROOT/'integrations'/name):recovery.digest(recovery.ROOT/'integrations'/name)
                          for name in recovery.FILES})

    def write(self,value):
        self.path.write_text(json.dumps(value),encoding='utf-8');return recovery.digest(self.path)

    @unittest.skipUnless(os.name=='nt','Windows exact source approval')
    def test_exact_approval_checks_all_sources_without_loading_a_service(self):
        sha=self.write(self.value)
        self.assertEqual(recovery.checked_recovery_approval(self.path,sha,self.profile,'a'*64),self.value)

    @unittest.skipUnless(os.name=='nt','Windows exact source approval')
    def test_memory_recovery_requires_an_explicit_separate_decision_and_reader_pin(self):
        value=copy.deepcopy(self.value)
        value.update(decision='approve_exact_same_grant_memory_recovery',readerServiceProfile=str(self.root/'reader-service.json'),readerServiceSha256='d'*64)
        value['sourceHashes'][str(recovery.ROOT/'integrations/mind-recovery-candidate/reader_service_process_candidate.py')]=recovery.digest(recovery.ROOT/'integrations/mind-recovery-candidate/reader_service_process_candidate.py')
        self.assertEqual(recovery.checked_recovery_approval(self.path,self.write(value),self.profile,'a'*64),value)
        value['decision']='approve_exact_same_grant_gateway_recovery'
        with self.assertRaises(recovery.RecoveryHold):recovery.checked_recovery_approval(self.path,self.write(value),self.profile,'a'*64)

    @unittest.skipUnless(os.name=='nt','Windows exact source approval')
    def test_wrong_decision_profile_runtime_or_source_never_qualifies(self):
        variants=[]
        for key,value in (('decision','first_setup'),('profileSha256','b'*64),
                          ('workspace',str(self.root)),('pythonSha256','0'*64),('extra',True)):
            bad=copy.deepcopy(self.value);bad[key]=value;variants.append(bad)
        bad=copy.deepcopy(self.value);bad['sourceHashes'].pop(next(iter(bad['sourceHashes'])));variants.append(bad)
        bad=copy.deepcopy(self.value);bad['sourceHashes'][next(iter(bad['sourceHashes']))]='0'*64;variants.append(bad)
        for bad in variants:
            with self.subTest(changed=set(bad)^set(self.value)):
                with self.assertRaises(recovery.RecoveryHold):
                    recovery.checked_recovery_approval(self.path,self.write(bad),self.profile,'a'*64)

    def test_duplicate_metadata_and_changed_approval_are_held(self):
        self.path.write_text('{"schema":1,"schema":2}')
        with self.assertRaises(recovery.RecoveryHold):recovery.bounded_json(self.path)
        with self.assertRaises(recovery.RecoveryHold):
            recovery.checked_recovery_approval(self.path,'0'*64,self.profile,'a'*64)

    def test_isolated_cli_refuses_before_any_service_import(self):
        self.path.write_text('{"private-marker":"must-not-appear"}')
        command=[sys.executable,'-I',str(Path(recovery.__file__)),
            '--profile',str(self.profile),'--sha256','a'*64,'--approval',str(self.root/'missing-reader'),
            '--recovery-approval',str(self.path),'--recovery-sha256','0'*64,'--ensure']
        result=subprocess.run(command,capture_output=True,text=True,timeout=10,
            creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        self.assertEqual(result.returncode,1)
        self.assertEqual(json.loads(result.stdout)['state'],'held')
        self.assertNotIn('must-not-appear',result.stdout+result.stderr)

    def test_powershell_delegation_precedes_mutex_and_refuses_bad_approval(self):
        source=(recovery.ROOT/'integrations/restart-workroom-preview.ps1').read_text()
        self.assertLess(source.index('--recovery-approval'),source.index('$mutex = New-Object'))
        # An isolated launcher copy has no runtime or source data to affect.
        scripts=self.root/'integrations';scripts.mkdir()
        target=scripts/'restart-workroom-preview.ps1';target.write_text(source)
        db=self.root/'data/workroom-preview';db.mkdir(parents=True);(db/'tasks.sqlite').write_bytes(b'')
        approval=self.root/'bad-approval.json';approval.write_text('{}')
        before={str(p.relative_to(self.root)):p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        result=subprocess.run([shutil.which('pwsh'),'-NoLogo','-NoProfile','-NonInteractive','-File',str(target),
            '-Action','Ensure','-NativeMindProfile',str(self.profile),'-NativeMindSha256','a'*64,
            '-NativeMindApproval',str(self.root/'missing-reader'),'-NativeRecoveryApproval',str(approval),
            '-NativeRecoverySha256','0'*64],capture_output=True,text=True,timeout=15,
            creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        self.assertNotEqual(result.returncode,0)
        self.assertIn('Recovery approval changed; no legacy fallback',result.stderr)
        self.assertEqual({str(p.relative_to(self.root)):p.read_bytes() for p in self.root.rglob('*') if p.is_file()},before)


class RecoveryBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name).resolve();self.workspace=self.root/'workspace';self.workspace.mkdir()
        self.window=SimpleNamespace(workspace=self.workspace,assert_held=lambda:None)
        self.p=dict(schema='onoes-mesh-native-launch/v2',nodeExecutable=sys.executable,
            attemptPath=str(self.workspace/'attempt'),stdoutPath=str(self.workspace/'out'),stderrPath=str(self.workspace/'err'),
            settings=dict(MESH_PREVIEW_PORT='4320'),projectSync=dict(serviceProfile='test-service',
                serviceProfileSha256='test-sha',approvalPath='test-approval'))
        self.attempt=dict(schema='onoes-mesh-native-child/v1',profileSha256='approved',pid=101,
            creationTicks=2020,state='input_sent',credentialsInRecord=False,executable=sys.executable,
            entryPoint=str(self.workspace/'serve.mjs'))
        self.owner=dict(Schema='onoes-owned-process/v1',WorkingDirectory=str(self.workspace),
            Id=101,StartTime=recovery.native_start(2020),EntryPoint=str(self.workspace/'serve.mjs'),
            Path=sys.executable,Port=4320,CommandLine=subprocess.list2cmdline([sys.executable,str(self.workspace/'serve.mjs'),'--native-mind']))
        self.roles=SimpleNamespace(same_process_alive=lambda *args:True)
        self.launch=SimpleNamespace(checked_launch=lambda *args:(self.p,self.roles),native_frame=lambda *args:{})
        self.state=dict(ready=True,pid=303,creationTicks=4040)
        self.service=SimpleNamespace(service_state=lambda *args:self.state)
        fake=ModuleType('onoes_mind.enrollment_store');fake.qualify_private_storage=lambda *args,**kwargs:None
        self.enrollment=patch.dict(sys.modules,{'onoes_mind.enrollment_store':fake});self.enrollment.start();self.addCleanup(self.enrollment.stop)
        self.observation=patch.object(recovery,'ProcessObservation',side_effect=AssertionError('No process may be adopted or launched'))
        self.observation.start();self.addCleanup(self.observation.stop)

    def check_held(self,error=recovery.RecoveryHold):
        attempt=Path(self.p['attemptPath']);receipt=self.root/'workroom-ab-preview-process.json'
        attempt.write_text(json.dumps(self.attempt));receipt.write_text(json.dumps(self.owner))
        before=(attempt.read_bytes(),receipt.read_bytes())
        with self.assertRaises(error):
            recovery.ensure_gateway(self.window,launch=self.launch,service=self.service,roles=self.roles,
                profile=self.workspace/'profile',sha='approved',approval='reader')
        self.assertEqual((attempt.read_bytes(),receipt.read_bytes()),before)

    def test_missing_writer_cannot_start_a_disconnected_gateway(self):
        self.state['ready']=False;self.check_held()

    def test_unresolved_input_cannot_be_reinterpreted_as_a_retry(self):
        self.attempt['state']='input_pending';self.check_held()

    def test_foreign_owner_blocks_recovery_before_any_process_change(self):
        self.owner['WorkingDirectory']=str(self.root);self.check_held()

    def test_unpublished_dead_attempt_has_no_automatic_replacement(self):
        self.owner['Id']=99;self.roles.same_process_alive=lambda *args:False;self.check_held()

    def test_denied_observation_is_not_original_process_retirement(self):
        def denied(*args):raise PermissionError('Synthetic inaccessible process')
        self.roles.same_process_alive=denied;self.check_held(PermissionError)


class ServiceViewTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name).resolve();self.attempt=self.root/'attempt';self.ready=self.root/'ready'
        self.record=dict(schema='onoes-mind-project-service-attempt/v1',profileSha256='approved',state='started',
                         pid=101,creationTicks=2020,runId='a'*32)
        self.attempt.write_text(json.dumps(self.record))
        self.value=dict(pid=101,creationTicks=2020,state='running',processLive=True,ready=True)
        self.roles=SimpleNamespace(same_process_alive=lambda *args:True)
        self.fetches=0
    def fetch(self):self.fetches+=1;return self.value
    def view(self):
        return recovery.known_service_view(attempt_path=self.attempt,ready_path=self.ready,
            profile_sha='approved',kind='project',fetch=self.fetch,roles=self.roles)
    def test_known_live_start_waits_without_reinterpreting_absence_as_restart(self):
        value=self.view();self.assertEqual(value['state'],'starting');self.assertTrue(value['processLive'])
        self.assertFalse(value['ready']);self.assertEqual(self.fetches,0)
    def test_dead_unpublished_start_is_held(self):
        self.roles.same_process_alive=lambda *args:False
        with self.assertRaises(recovery.RecoveryHold):self.view()
        self.assertEqual(self.fetches,0)
    def test_ready_owner_must_match_exact_attempt_before_runtime_readback(self):
        self.ready.write_text(json.dumps(dict(pid=999,creationTicks=2020)))
        with self.assertRaises(recovery.RecoveryHold):self.view()
        self.assertEqual(self.fetches,0)
    def test_previously_ready_retired_owner_is_known_but_failed_owner_is_held(self):
        self.ready.write_text(json.dumps(dict(pid=101,creationTicks=2020)))
        self.roles.same_process_alive=lambda *args:False
        self.value.update(processLive=False,ready=False)
        self.assertEqual(self.view()['state'],'running')
        self.value['state']='failed'
        with self.assertRaises(recovery.RecoveryHold):self.view()
    def test_partial_identity_cannot_start_another_actor(self):
        self.record['state']='identity_pending';self.attempt.write_text(json.dumps(self.record))
        with self.assertRaises(recovery.RecoveryHold):self.view()
        self.assertEqual(self.fetches,0)


if __name__=='__main__':unittest.main()
