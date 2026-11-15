"""Whole operator journey in protected TEMP directories; fixture password only."""
from pathlib import Path
import json
import hashlib
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import tkinter as tk
import unittest
from unittest.mock import patch

sys.path.insert(0, 'D:/Dev/Onoes-Mind')
from onoes_mind.recovery_setup import RecoverySetup
from test_persistent_authority import PRIVATE_ACL
from operator_setup_candidate import initialize_checkpointed_candidate, CheckpointedSetupError
import operator_setup_candidate as host


@unittest.skipUnless(sys.platform == 'win32', 'Native Windows key protection')
class OperatorSetupCandidateTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name).resolve()
        self.data,self.authority,self.backup=[self.root/name for name in ('synthetic-data','synthetic-current','synthetic-backup')]
        script=self.root/'fixture-private-acl.ps1';script.write_text(PRIVATE_ACL)
        for folder in (self.data,self.authority,self.backup):
            folder.mkdir();self.assertTrue(folder.resolve().is_relative_to(self.root))
            subprocess.run([shutil.which('pwsh'),'-NoProfile','-NonInteractive','-File',str(script),'-Path',str(folder)],
                check=True,capture_output=True,creationflags=subprocess.CREATE_NO_WINDOW)
        self.args=dict(directory=self.data,authority_directory=self.authority,backup_directory=self.backup,
            environment_id='synthetic-whole-operator-journey',owner_ref='fixture:Eddie',
            authority_ref='fixture:canonical-source',review_ref='fixture:development-only')
        self.password='fixture-only-password-never-a-live-secret'

    def tearDown(self):
        self.temp.cleanup()

    def native_entry(self, **keys):
        self.assertFalse((self.data/'ledger.sqlite').exists(), 'keys must be protected before DB creation')
        root=tk.Tk();root.withdraw();results=[]
        screen=RecoverySetup(root,keys={k:keys[k] for k in ('audit_key','deletion_key','store_id','environment_id')},
            on_done=results.append,directory=keys['directory'])
        try:
            screen.password.set(self.password);screen.confirmation.set(self.password)
            screen.saved.set(True);screen.prepare_button.invoke()
            end=time.monotonic()+30
            while not results and time.monotonic()<end:root.update();time.sleep(.01)
            self.assertTrue(results,'withdrawn native enrollment did not finish')
            return results[0]
        finally:screen.cancel();root.destroy()

    def run_native(self):
        with patch('onoes_mind.operator_setup.show_recovery_setup',side_effect=self.native_entry):
            return initialize_checkpointed_candidate(**self.args)

    def test_complete_native_enrollment_journal_backup_restore_and_receipt(self):
        result=self.run_native()
        self.assertTrue(result['initialized']);self.assertFalse(result['activated'])
        self.assertFalse(result['recoveryQualified']);self.assertFalse(result['runtimeEnrollment'])
        self.assertEqual(result['candidateRehearsal'],'PASS')
        self.assertEqual((result['principals'],result['records']),(0,0))
        self.assertEqual(json.loads((self.data/'checkpointed-initialization-receipt.json').read_text()),result)
        self.assertEqual(result['authorityBinding']['store_id'],result['storeId'])
        self.assertEqual(result['publication']['store_id'],result['storeId'])
        self.assertTrue(Path(result['rehearsal']).is_file())
        self.assertEqual(set(result['backupArtifacts']),{'first-empty-snapshot.sqlite',
            'first-empty-snapshot.sqlite.meta','encrypted-key-enrollment.json','snapshot-deletion-history.jsonl'})
        for name,digest in result['backupArtifacts'].items():
            self.assertEqual(hashlib.sha256((self.backup/name).read_bytes()).hexdigest(),digest)
        self.assertEqual((self.backup/'encrypted-key-enrollment.json').read_bytes(),
            (self.data/'key-enrollment.json').read_bytes())
        serialized=json.dumps(result)
        self.assertNotIn(self.password,serialized)
        self.assertNotIn('runtime_envelope',serialized);self.assertNotIn('audit_key',serialized)

    def test_cancel_creates_no_database_journal_backup_or_success_receipt(self):
        with patch('onoes_mind.operator_setup.show_recovery_setup',return_value=None):
            result=initialize_checkpointed_candidate(**self.args)
        self.assertTrue(result['cancelled']);self.assertFalse(result['initialized'])
        for folder in (self.data,self.authority,self.backup):self.assertEqual(list(folder.iterdir()),[])

    def test_occupied_destinations_refuse_before_any_key_enrollment(self):
        for folder in (self.data,self.authority,self.backup):
            marker=folder/'existing-fixture.txt';marker.write_text('preserve existing data')
            with patch.object(host,'initialize_private_store') as initialize:
                with self.assertRaises(CheckpointedSetupError) as error:
                    initialize_checkpointed_candidate(**self.args)
                initialize.assert_not_called();self.assertEqual(error.exception.stage,'preflight')
            self.assertEqual(marker.read_text(),'preserve existing data');marker.unlink()

    def test_overlapping_destinations_refuse_before_enrollment(self):
        args={**self.args,'backup_directory':self.data}
        with patch.object(host,'initialize_private_store') as initialize:
            with self.assertRaises(CheckpointedSetupError):initialize_checkpointed_candidate(**args)
            initialize.assert_not_called()

    def test_journal_failure_preserves_protected_keys_and_empty_store_without_success(self):
        with patch.object(host.PersistentAuthorityCandidate,'create',side_effect=OSError('fixture unavailable')):
            with self.assertRaises(CheckpointedSetupError) as error:self.run_native()
        self.assertEqual(error.exception.stage,'current-journal')
        self.assertTrue((self.data/'key-enrollment.json').exists());self.assertTrue((self.data/'ledger.sqlite').exists())
        self.assertFalse((self.data/'checkpointed-initialization-receipt.json').exists())
        self.assertEqual(list(self.backup.iterdir()),[])

    def test_rehearsal_failure_never_claims_recovery_success_or_removes_originals(self):
        with patch.object(host,'restore_checkpoint_candidate',side_effect=OSError('fixture failed rehearsal')):
            with self.assertRaises(CheckpointedSetupError) as error:self.run_native()
        self.assertEqual(error.exception.stage,'restore-rehearsal')
        self.assertTrue((self.backup/'first-empty-snapshot.sqlite').exists())
        self.assertTrue((self.authority/'current-checkpoint.sqlite').exists())
        self.assertTrue((self.data/'checkpoint-authority-binding.json').exists())
        self.assertFalse((self.data/'checkpointed-initialization-receipt.json').exists())

    def test_late_receipt_failure_preserves_completed_rehearsal_for_inspection(self):
        save=host.save_new
        def fail_final(path,value):
            if path.name=='checkpointed-initialization-receipt.json':raise OSError('fixture receipt failure')
            return save(path,value)
        with patch.object(host,'save_new',side_effect=fail_final):
            with self.assertRaises(CheckpointedSetupError) as error:self.run_native()
        self.assertEqual(error.exception.stage,'final-receipt')
        self.assertTrue((self.backup/'restore-rehearsal.sqlite').exists())
        self.assertFalse((self.data/'checkpointed-initialization-receipt.json').exists())

    def test_success_receipt_is_written_only_after_source_connection_closes(self):
        create,save=host.Ledger,host.save_new
        seen=[]
        def capture(*args,**kwargs):
            ledger=create(*args,**kwargs);seen.append(ledger);return ledger
        def check_closed(path,value):
            if path.name=='checkpointed-initialization-receipt.json':
                self.assertEqual(len(seen),1)
                with self.assertRaises(sqlite3.ProgrammingError):seen[0].db.execute('SELECT 1')
            return save(path,value)
        with patch.object(host,'Ledger',side_effect=capture),patch.object(host,'save_new',side_effect=check_closed):
            result=self.run_native()
        self.assertEqual(result['candidateRehearsal'],'PASS')

    def test_rehearsal_uses_exported_files_while_source_keys_and_history_are_unavailable(self):
        restore=host.restore_checkpoint_candidate
        def backup_only(snapshot,target,history,*args,**kwargs):
            self.assertEqual(Path(snapshot).parent,self.backup)
            self.assertEqual(Path(history),self.backup/'snapshot-deletion-history.jsonl')
            originals=[self.data/'key-enrollment.json',self.data/'ledger.sqlite.deletions.jsonl']
            parked=[]
            try:
                for item in originals:
                    preserved=item.with_name(item.name+'.fixture-unavailable');item.rename(preserved)
                    parked.append((item,preserved))
                return restore(snapshot,target,history,*args,**kwargs)
            finally:
                for item,preserved in reversed(parked):preserved.rename(item)
        with patch.object(host,'restore_checkpoint_candidate',side_effect=backup_only):
            result=self.run_native()
        self.assertEqual(result['candidateRehearsal'],'PASS')


if __name__=='__main__':unittest.main()
