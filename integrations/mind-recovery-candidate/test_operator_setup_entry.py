"""Operator entry boundaries plus one real native TEMP setup/backup/rehearsal."""
import io
import json
from pathlib import Path
import subprocess
import sys
import unittest
import uuid
import warnings
from unittest.mock import patch

import test_operator_setup_candidate as fixtures
import operator_setup_entry as entry
import encrypted_backup_candidate as archives
import checkpointed_ledger_candidate as protected


class TerminalInput(io.StringIO):
    def isatty(self):return True


@unittest.skipUnless(sys.platform=='win32','Native Windows key protection')
class OperatorSetupEntryTests(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.OperatorSetupCandidateTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.archive_stage=self.fixture.root/'private-archive-stage'
        self.archive_rehearsal=self.fixture.root/'private-archive-rehearsal'
        for folder in (self.archive_stage,self.archive_rehearsal):
            folder.mkdir()
            subprocess.run([fixtures.shutil.which('pwsh'),'-NoProfile','-NonInteractive','-File',
                str(self.fixture.root/'fixture-private-acl.ps1'),'-Path',str(folder)],
                capture_output=True,check=True,creationflags=subprocess.CREATE_NO_WINDOW)
        evidence=Path(__file__).resolve().parents[2].parent/'mesh-workroom-ab/data'
        tool=json.loads((evidence/'sevenzip-tool-proof-20261115.json').read_text())['tool']
        self.archive_root=Path('E:/App-Backups/Onoes-Mesh/Candidates/Mind-encrypted-setup-trial-2026-11-15')
        self.archive_root.mkdir(parents=True,exist_ok=True)
        self.encrypted_backup=self.archive_root/(str(uuid.uuid4())+'.7z')
        self.all_roots=(self.fixture.data,self.fixture.authority,self.fixture.backup,self.archive_stage,self.archive_rehearsal)
        self.args=[]
        for key,value in self.fixture.args.items():
            self.args+=['--'+key.replace('_','-'),str(value)]
        self.args+=['--archive-staging-directory',str(self.archive_stage),'--archive-rehearsal-directory',str(self.archive_rehearsal),
                    '--encrypted-backup',str(self.encrypted_backup),'--archive-tool',str(tool)]
        self.initialize_args=self.args+['--initialize','--approval-ref','fixture:owner-approved-TEMP-only']
        self.actual_password_reader=entry.archive_password
        self.password_patch=patch.object(entry,'archive_password',return_value=self.fixture.password)
        self.password_mock=self.password_patch.start();self.addCleanup(self.password_patch.stop)

    def empty(self):
        for root in self.all_roots:
            self.assertEqual(list(root.iterdir()),[])

    def test_default_preview_creates_nothing_and_never_initializes(self):
        output=io.StringIO()
        with patch.object(entry,'initialize') as initialize:
            self.assertEqual(entry.main(self.args,input_stream=io.StringIO(),output=output),0)
            initialize.assert_not_called()
        plan=json.loads(output.getvalue());self.assertTrue(plan['createsNothing'])
        self.assertFalse(plan['activated']);self.assertTrue(plan['ownerApprovalRequired']);self.empty()

    def test_no_approval_reference_refuses_before_enrollment(self):
        with patch.object(entry,'initialize') as initialize:
            self.assertEqual(entry.main(self.args+['--initialize'],input_stream=TerminalInput(),output=io.StringIO()),1)
            initialize.assert_not_called()
        self.empty()

    def test_noninteractive_initialization_is_refused(self):
        with patch.object(entry,'initialize') as initialize:
            self.assertEqual(entry.main(self.initialize_args,input_stream=io.StringIO('CREATE EMPTY MIND STORE\n'),
                                       output=io.StringIO()),1)
            initialize.assert_not_called()
        self.empty()

    def test_cancel_confirmation_does_not_open_native_enrollment(self):
        with patch.object(entry,'initialize') as initialize:
            self.assertEqual(entry.main(self.initialize_args,input_stream=TerminalInput('\n'),output=io.StringIO()),2)
            initialize.assert_not_called()
        self.empty()

    def test_destination_change_during_confirmation_refuses_and_preserves_marker(self):
        marker=self.fixture.data/'later-file.txt'
        class ChangedInput(TerminalInput):
            def readline(self):
                marker.write_text('preserve this file')
                return 'CREATE EMPTY MIND STORE\n'
        with patch.object(entry,'initialize') as initialize:
            self.assertEqual(entry.main(self.initialize_args,input_stream=ChangedInput(),output=io.StringIO()),1)
            initialize.assert_not_called()
        self.assertEqual(marker.read_text(),'preserve this file')

    def test_exception_text_is_not_echoed_or_retried(self):
        output=io.StringIO()
        with patch.object(entry,'initialize',side_effect=ValueError('fixture-secret-must-not-echo')) as initialize:
            self.assertEqual(entry.main(self.initialize_args,input_stream=TerminalInput('CREATE EMPTY MIND STORE\n'),
                                       output=output),1)
            self.assertEqual(initialize.call_count,1)
        self.assertNotIn('fixture-secret',output.getvalue());self.empty()

    def test_native_complete_journey_through_entry_prints_only_inactive_summary(self):
        output=io.StringIO()
        restored=[];actual_restore=protected.restore_checkpointed_candidate
        actual_export=archives.export_encrypted_backup_candidate;actual_save=archives.save_new
        def capture(*args,**kwargs):
            result=actual_restore(*args,**kwargs);restored.append(result);return result
        def export_and_park(*args,**kwargs):
            result=actual_export(*args,**kwargs)
            originals=[self.fixture.data/'key-enrollment.json',self.fixture.data/'ledger.sqlite.deletions.jsonl']
            originals += [self.fixture.backup/name for name in ('first-empty-snapshot.sqlite','first-empty-snapshot.sqlite.meta',
                'encrypted-key-enrollment.json','snapshot-deletion-history.jsonl')]
            for path in originals:path.rename(path.with_name(path.name+'.fixture-unavailable'))
            return result
        def save_after_close(path,value):
            if Path(path).name=='setup-with-encrypted-backup-receipt.json':
                self.assertEqual(len(restored),1)
                with self.assertRaises(fixtures.sqlite3.ProgrammingError):restored[0].db.execute('SELECT 1')
            return actual_save(path,value)
        with patch('onoes_mind.operator_setup.show_recovery_setup',side_effect=self.fixture.native_entry), \
             patch.object(archives,'export_encrypted_backup_candidate',side_effect=export_and_park), \
             patch.object(protected,'restore_checkpointed_candidate',side_effect=capture), \
             patch.object(archives,'save_new',side_effect=save_after_close):
            self.assertEqual(entry.main(self.initialize_args,input_stream=TerminalInput('CREATE EMPTY MIND STORE\n'),
                                       output=output),0,output.getvalue())
        receipt=json.loads((self.fixture.data/'checkpointed-initialization-receipt.json').read_text())
        self.assertEqual(receipt['candidateRehearsal'],'PASS');self.assertFalse(receipt['activated'])
        self.assertTrue((self.fixture.backup/'restore-rehearsal.sqlite').is_file())
        final=json.loads((self.fixture.data/'setup-with-encrypted-backup-receipt.json').read_text())
        self.assertEqual(final['archiveRehearsal'],'PASS');self.assertFalse(final['activated'])
        self.assertTrue(self.encrypted_backup.is_file())
        self.assertTrue((self.archive_rehearsal/'verified-restored.sqlite').is_file())
        self.assertFalse((self.fixture.data/'key-enrollment.json').exists())
        self.assertIn('setup_complete_inactive',output.getvalue())
        for value in (self.fixture.password,'recovery_envelope','runtime_envelope','audit_key','deletion_key'):
            self.assertNotIn(value,output.getvalue())

    def test_archive_password_mismatch_creates_nothing(self):
        self.password_mock.side_effect=['fixture-first-long-password','fixture-other-long-password']
        with patch.object(entry,'initialize') as initialize:
            self.assertEqual(entry.main(self.initialize_args,input_stream=TerminalInput('CREATE EMPTY MIND STORE\n'),
                                       output=io.StringIO()),1)
            initialize.assert_not_called()
        self.empty();self.assertFalse(self.encrypted_backup.exists())

    def test_existing_encrypted_destination_refuses_before_enrollment(self):
        self.encrypted_backup.write_bytes(b'preserve synthetic marker')
        with patch.object(entry,'initialize') as initialize:
            self.assertEqual(entry.main(self.initialize_args,input_stream=TerminalInput('CREATE EMPTY MIND STORE\n'),
                                       output=io.StringIO()),1)
            initialize.assert_not_called()
        self.empty();self.assertEqual(self.encrypted_backup.read_bytes(),b'preserve synthetic marker')

    def test_archive_failure_preserves_initialized_store_without_final_completion(self):
        output=io.StringIO()
        with patch('onoes_mind.operator_setup.show_recovery_setup',side_effect=self.fixture.native_entry), \
             patch.object(entry,'finish_encrypted_backup',side_effect=OSError('fixture-secret-never-echo')):
            self.assertEqual(entry.main(self.initialize_args,input_stream=TerminalInput('CREATE EMPTY MIND STORE\n'),
                                       output=output),1)
        self.assertTrue((self.fixture.data/'ledger.sqlite').is_file())
        self.assertTrue((self.fixture.data/'checkpointed-initialization-receipt.json').is_file())
        self.assertFalse((self.fixture.data/'setup-with-encrypted-backup-receipt.json').exists())
        self.assertIn('Empty store exists',output.getvalue())
        self.assertNotIn('setup_complete_inactive',output.getvalue());self.assertNotIn('fixture-secret',output.getvalue())

    def test_password_reader_refuses_echo_fallback(self):
        echoed=[]
        def fallback(*args,**kwargs):
            warnings.warn('fixture echo fallback',entry.getpass.GetPassWarning)
            echoed.append(True)
            return 'fixture-would-have-echoed'
        with patch.object(entry.getpass,'getpass',side_effect=fallback):
            with self.assertRaises(entry.getpass.GetPassWarning):self.actual_password_reader()
        self.assertEqual(echoed,[])

    def test_native_cancellation_returns_no_completion_and_no_files(self):
        output=io.StringIO()
        with patch('onoes_mind.operator_setup.show_recovery_setup',return_value=None):
            self.assertEqual(entry.main(self.initialize_args,input_stream=TerminalInput('CREATE EMPTY MIND STORE\n'),
                                       output=output),2)
        self.assertNotIn('setup_complete_inactive',output.getvalue());self.empty()

    def test_help_subprocess_needs_no_mind_import_or_initialization(self):
        result=subprocess.run([sys.executable,str(Path(entry.__file__)),'--help'],capture_output=True,text=True,
                              creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn('Preview is read-only',result.stdout);self.empty()


if __name__=='__main__':unittest.main()
