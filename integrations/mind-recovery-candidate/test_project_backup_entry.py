"""Synthetic initialized-store owner-window qualification; no live setup profiles."""
from dataclasses import asdict
import contextlib
import copy
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import queue
import threading
import time
import unittest
import uuid
from unittest.mock import patch

import project_backup_entry as window


class ImportOnlyTests(unittest.TestCase):
    def test_help_needs_no_mind_import_or_password(self):
        child=subprocess.run([sys.executable,str(Path(window.__file__)),'--help'],capture_output=True,text=True,timeout=20,
            env={k:v for k,v in os.environ.items() if k.upper()!='PYTHONPATH'},creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        self.assertEqual(child.returncode,0,child.stderr)
        self.assertIn('never initializes',child.stdout)

    @unittest.skipUnless(os.name=='nt','Windows owner window')
    def test_launcher_refuses_drift_and_keeps_status_until_close(self):
        script=Path(window.__file__).with_name('Start-Existing-Mind-Backup.ps1')
        with tempfile.TemporaryDirectory(prefix='mind-backup-window-test-') as temporary:
            profile=Path(temporary)/'not-approved.json';profile.write_text('{}')
            child=subprocess.Popen([shutil.which('pwsh'),'-NoLogo','-NoProfile','-File',str(script),
                '-Profile',str(profile),'-Sha','0'*64,'-Approval',str(profile)],
                stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,creationflags=subprocess.CREATE_NO_WINDOW)
            lines=[];messages=queue.Queue()
            def read_lines():
                for line in child.stdout:lines.append(line);messages.put(line)
            reader=threading.Thread(target=read_lines,daemon=True);reader.start()
            try:
                deadline=time.monotonic()+25
                while True:
                    line=messages.get(timeout=max(.01,deadline-time.monotonic()))
                    if 'This window will stay open' in line:break
                self.assertIsNone(child.poll())
                child.stdin.write('WAIT\n');child.stdin.flush();time.sleep(.2)
                self.assertIsNone(child.poll(),'A non-CLOSE input must not dismiss the window')
                child.stdin.write('CLOSE\n');child.stdin.flush();child.stdin.close()
                self.assertEqual(child.wait(timeout=10),1);reader.join(timeout=5)
                self.assertIn('This window will stay open',''.join(lines))
                self.assertNotIn('Enter saved BACKUP',''.join(lines))
            finally:
                if child.poll() is None:child.terminate();child.wait(timeout=10)
                reader.join(timeout=5)
                for stream in (child.stdin,child.stdout,child.stderr):
                    if not stream.closed:stream.close()



@unittest.skipUnless(os.name=='nt','Windows ownership and DPAPI fixtures')
class BackupWindowTests(unittest.TestCase):
    def setUp(self):
        import test_recall_process_candidate as fixtures
        from test_persistent_authority import PRIVATE_ACL
        from onoes_mind.runtime_keys import unprotect_runtime_keys
        from onoes_mind.enrollment_store import prepare_and_save_enrollment
        self.fixture=fixtures.NativeRoleProcessTests();self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        f=self.fixture;p=f.operator_data;self.root=f.fixture.backup
        acl=self.root/'backup-fixture-acl.ps1';acl.write_text(PRIVATE_ACL)
        def private(name):
            folder=self.root/name;folder.mkdir()
            subprocess.run([p['runtime']['pwsh'],'-NoProfile','-NonInteractive','-File',str(acl),'-Path',str(folder)],
                capture_output=True,check=True,creationflags=subprocess.CREATE_NO_WINDOW)
            return folder
        source,stage,rehearsal=[private(n) for n in ('backup-source','archive-stage','archive-rehearsal')]
        # Replace only this fixture's placeholder recovery envelope with a real
        # wrapped package for the very same synthetic keys; never touch live keys.
        package=json.loads(f.key_package.read_text());keys=unprotect_runtime_keys(package['runtime_envelope'],
            store_id=package['storeId'],environment_id=f.environment)
        custody=private('fixture-correct-wrapped-package');self.password='fixture-backup-window-passphrase-2026'
        prepare_and_save_enrollment(directory=custody,**keys,store_id=package['storeId'],environment_id=f.environment,
            password=self.password,confirmation=self.password)
        f.key_package.write_bytes((custody/'key-enrollment.json').read_bytes())
        self.keys=keys;self.store=package['storeId']
        proof=Path(__file__).resolve().parents[2].parent/'mesh-workroom-ab/data/sevenzip-tool-proof-20261115.json'
        tool=json.loads(proof.read_text())['tool']
        destination=Path('E:/App-Backups/Onoes-Mind/Candidates/Existing-store-window-2026-11-16')
        destination.mkdir(parents=True,exist_ok=True)
        self.value=dict(schema=window.SCHEMA,ownerSid=p['ownerSid'],runtime=p['runtime'],
            sourceHashes={str(n):window.digest(n) for n in window.source_paths(p['runtime'])},
            binding={k:p['binding'][k] for k in ('database_path','file_device','file_inode','store_id','environment','authority_ref')},
            keyEnrollmentPath=p['keyEnrollmentPath'],authorityBindingPath=p['authorityBindingPath'],historyPath=p['historyPath'],
            sourceDirectory=str(source),stagingDirectory=str(stage),rehearsalDirectory=str(rehearsal),
            encryptedBackup=str(destination/(self._testMethodName+'-'+uuid.uuid4().hex+'.7z')),archiveTool=tool,
            attemptPath=str(self.root/'backup-attempt.json'),resultPath=str(self.root/'backup-result.json'),reviewRef='fixture:owner-backup',
            writerGate=dict(kind='not_started',attemptPath=str(self.root/'future-service-attempt.json'),
                readyPath=str(self.root/'future-service-ready.json'),profileSha256='a'*64))
        self.profile=self.root/'backup-profile.json';self.approval=self.root/'backup-approval.json';self.write()

    def write(self,value=None):
        self.profile.write_text(json.dumps(self.value if value is None else value),encoding='utf-8')
        self.sha=window.digest(self.profile)
        self.approval.write_text(json.dumps(dict(decision=window.DECISION,ownerSid=self.value['ownerSid'],
            profileSha256=self.sha,storeId=self.store,environment=self.fixture.environment,reviewRef=self.value['reviewRef'])),encoding='utf-8')

    def test_preview_and_rejections_never_open_store_or_ask_password(self):
        from unittest.mock import patch
        import onoes_mind.runtime_keys as keys
        with patch.object(keys,'unprotect_runtime_keys',side_effect=AssertionError('preview opened keys')):
            self.assertTrue(window.preview(self.profile,self.sha)['createsNothing'])
            held=json.loads(self.approval.read_text());held['decision']='not-approved';self.approval.write_text(json.dumps(held))
            with patch('project_backup_candidate.prompt_archive_password',side_effect=AssertionError('prompted without approval')):
                with self.assertRaises(ValueError):window.main(['--profile',str(self.profile),'--sha',self.sha,'--approval',str(self.approval),'--run'])
            for modify in ('source','inode','writer'):
                bad=copy.deepcopy(self.value)
                if modify=='source':bad['sourceHashes'][str(Path(window.__file__))]='0'*64
                elif modify=='inode':bad['binding']['file_inode']+=1
                else:Path(bad['writerGate']['attemptPath']).write_text('{}')
                self.write(bad)
                with self.assertRaises(ValueError):window.preview(self.profile,self.sha)
            self.assertFalse(Path(self.value['attemptPath']).exists());self.assertFalse(Path(self.value['encryptedBackup']).exists())

    def test_console_backup_preserves_populated_store_and_existing_keys_and_blocks_replay(self):
        from checkpointed_ledger_candidate import CheckpointedLedgerCandidate
        from persistent_authority import AuthorityBinding,PersistentAuthorityCandidate
        from project_events_candidate import EventBinding,ProjectEventsCandidate
        from test_project_events_candidate import event
        f=self.fixture
        authority=PersistentAuthorityCandidate(AuthorityBinding(**json.loads(Path(self.value['authorityBindingPath']).read_text())))
        ledger=CheckpointedLedgerCandidate(f.database,f.history,authority,store_id=self.store,environment=f.environment,**self.keys)
        try:
            writer=ProjectEventsCandidate(ledger,EventBinding(**self.value['binding']));writer.initialize()
            writer.register_project('project-A','Synthetic window project');token=writer.enroll(['project-A']);writer.submit(token,event())
        finally:ledger.close()
        key_before=f.key_package.read_bytes();output=io.StringIO()
        with patch('getpass.getpass',side_effect=[self.password,self.password]),contextlib.redirect_stdout(output):
            self.assertEqual(window.main(['--profile',str(self.profile),'--sha',self.sha,'--approval',str(self.approval),'--run']),0)
        result=json.loads(Path(self.value['resultPath']).read_text())
        self.assertEqual(result['projectReceiptCount'],1);self.assertEqual(result['status'],'backup_complete_inactive')
        self.assertFalse(result['newCredentialsCreated']);self.assertFalse(result['newKeysCreated']);self.assertFalse(result['serviceStarted'])
        self.assertEqual(f.key_package.read_bytes(),key_before)
        self.assertNotIn(self.password,output.getvalue());self.assertNotIn(token,output.getvalue())
        with patch('project_backup_candidate.prompt_archive_password',side_effect=AssertionError('replayed prompt')):
            with self.assertRaises(ValueError):window.main(['--profile',str(self.profile),'--sha',self.sha,'--approval',str(self.approval),'--run'])
        proof=Path(__file__).resolve().parents[2]/'data/project-backup-window-proof-20261116.json'
        proof.write_text(json.dumps(dict(**result,syntheticOnly=True,existingWrappedKeysUnchanged=True),indent=2)+'\n',encoding='utf-8')

    def test_stopped_writer_needs_matching_receipt_and_retired_exact_process(self):
        import recall_process_candidate as roles
        child=subprocess.Popen([sys.executable,'-c','pass'],creationflags=subprocess.CREATE_NO_WINDOW)
        ticks=roles.creation_ticks(child._handle);self.assertEqual(child.wait(timeout=10),0)
        self.value['writerGate']['kind']='stopped'
        attempt=dict(schema='onoes-mind-project-service-attempt/v1',state='started',profileSha256='a'*64,runId='fixture-run',pid=child.pid,creationTicks=ticks)
        ready=dict(attempt,schema='onoes-mind-project-service-owner/v1',state='stopped',storeId=self.store,environment=self.fixture.environment,scopeId='project/onoes-mind/shared')
        Path(self.value['writerGate']['attemptPath']).write_text(json.dumps(attempt));Path(self.value['writerGate']['readyPath']).write_text(json.dumps(ready));self.write()
        self.assertTrue(window.preview(self.profile,self.sha)['ready'])
        attempt.update(pid=os.getpid(),creationTicks=roles.current_ticks());ready.update(pid=attempt['pid'],creationTicks=attempt['creationTicks'])
        Path(self.value['writerGate']['attemptPath']).write_text(json.dumps(attempt));Path(self.value['writerGate']['readyPath']).write_text(json.dumps(ready))
        with self.assertRaises(ValueError):window.preview(self.profile,self.sha)
        ready['state']='failed';Path(self.value['writerGate']['readyPath']).write_text(json.dumps(ready))
        with self.assertRaises(ValueError):window.preview(self.profile,self.sha)

    def test_archive_failure_retains_attempt_and_snapshot_without_success_or_retry(self):
        with patch('project_backup_candidate.archive_prepared_project_backup',side_effect=RuntimeError('synthetic failure')) as called:
            with self.assertRaises(RuntimeError):window.run_backup(self.profile,self.sha,self.approval,self.password)
            self.assertTrue(Path(self.value['attemptPath']).is_file());self.assertFalse(Path(self.value['resultPath']).exists())
            attempt=json.loads(Path(self.value['attemptPath']).read_text())
            self.assertEqual((attempt['state'],attempt['phase']),('failed_outcome_unknown','archive'))
            self.assertTrue((Path(self.value['sourceDirectory'])/'project-snapshot.sqlite').is_file())
            with self.assertRaises(ValueError):window.run_backup(self.profile,self.sha,self.approval,self.password)
            self.assertEqual(called.call_count,1)


if __name__=='__main__':unittest.main()
