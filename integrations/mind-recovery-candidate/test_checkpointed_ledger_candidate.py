"""Actual canonical Ledger through opt-in adapter; disposable data only."""
from pathlib import Path
import secrets
import sqlite3
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0, 'D:/Dev/Onoes-Mind')
from onoes_mind import Ledger
from onoes_mind.recall_binding import prepare_store_identity
from checkpoint_candidate import (CheckpointRecoveryError, purge_checkpoint_candidate,
                                  publish_snapshot_candidate, restore_checkpoint_candidate)
import checkpointed_ledger_candidate as host_module
from checkpointed_ledger_candidate import CheckpointedLedgerCandidate, restore_checkpointed_candidate
from persistent_authority import PersistentAuthorityCandidate
from test_persistent_authority import PRIVATE_ACL


@unittest.skipUnless(sys.platform == 'win32', 'Windows private storage')
class CheckpointedLedgerTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        temporary_root=Path(self.temp.name).resolve()
        self.root=temporary_root/'synthetic-private-store';self.root.mkdir()
        script=temporary_root/'fixture-private-acl.ps1';script.write_text(PRIVATE_ACL)
        acl_result=subprocess.run([shutil.which('pwsh'),'-NoProfile','-NonInteractive','-File',str(script),
            '-Path',str(self.root)],capture_output=True,text=True,creationflags=subprocess.CREATE_NO_WINDOW)
        self.assertEqual(acl_result.returncode,0,acl_result.stderr)
        journal=self.root/'journal';journal.mkdir()
        acl_result=subprocess.run([shutil.which('pwsh'),'-NoProfile','-NonInteractive','-File',str(script),
            '-Path',str(journal)],capture_output=True,text=True,creationflags=subprocess.CREATE_NO_WINDOW)
        self.assertEqual(acl_result.returncode,0,acl_result.stderr)
        self.database=self.root/'source.sqlite';self.history=self.root/'history.jsonl'
        self.keys=dict(audit_key=secrets.token_bytes(32),deletion_key=secrets.token_bytes(32))
        self.environment='synthetic-checkpointed-host'
        source=Ledger(self.database,deletion_ledger_path=self.history,environment_id=self.environment,**self.keys)
        try:
            self.store_id=prepare_store_identity(source,environment=self.environment,authority_ref='fixture:source')
            source.create_principal('operator');self.token=source.issue_credential('operator','fixture-token')
            self.record=source.remember(self.token,dict(event_id='fixture-record',claim='fixture banana',
                kind='project_fact',project_id='onoes-mind',requested_visibility='shared'))['record_id']
            self.authority=PersistentAuthorityCandidate.create(journal,source,store_id=self.store_id,
                environment=self.environment,review_ref='fixture:source')
        finally:source.close()
        self.ledger=self.open_host();self.addCleanup(self.ledger.close)

    def open_host(self):
        return CheckpointedLedgerCandidate(self.database,self.history,self.authority,
            store_id=self.store_id,environment=self.environment,**self.keys)

    def purge(self, operation_id='fixture-purge'):
        return self.ledger.purge(self.token,self.record,'PURGE:'+self.record,operation_id=operation_id)

    def test_managed_purge_acknowledges_and_retry_reuses_receipt(self):
        receipt=self.purge();self.assertTrue(receipt['checkpointAcknowledged'])
        self.assertEqual(self.purge(),receipt)
        self.assertEqual(self.ledger.search(self.token,'banana'),[])
        with self.authority.hold(self.store_id,self.environment) as lease:
            self.assertEqual(lease.history(),self.history.read_bytes())

    def test_managed_host_reopens_after_acknowledged_delete(self):
        self.purge();self.ledger.close()
        reopened=self.open_host()
        try:self.assertEqual(reopened.search(self.token,'banana'),[])
        finally:reopened.close()

    def test_missing_source_is_not_created_by_adapter(self):
        missing=self.root/'missing.sqlite'
        with self.assertRaises(FileNotFoundError):
            CheckpointedLedgerCandidate(missing,self.history,self.authority,
                store_id=self.store_id,environment=self.environment,**self.keys)
        self.assertFalse(missing.exists())

    def test_legacy_direct_and_base_class_purge_and_append_are_refused(self):
        before=self.history.read_bytes()
        calls=(lambda:self.ledger.purge(self.token,self.record,'PURGE:'+self.record),
               lambda:Ledger.purge(self.ledger,self.token,self.record,'PURGE:'+self.record),
               lambda:self.ledger._append_deletion(self.record,'fixture-tombstone','fixture-time'))
        for call in calls:
            with self.assertRaises(CheckpointRecoveryError):call()
        self.assertEqual(self.history.read_bytes(),before)
        self.assertEqual(len(self.ledger.search(self.token,'banana')),1)

    def test_wrong_confirmation_never_fences_or_mutates(self):
        with self.assertRaises(CheckpointRecoveryError):
            self.ledger.purge(self.token,self.record,'wrong',operation_id='bad')
        with self.authority.hold(self.store_id,self.environment) as lease:self.assertEqual(lease.current().sequence,0)

    def test_existing_uncertainty_blocks_host_open(self):
        with self.authority.hold(self.store_id,self.environment) as lease:head=lease.current()
        self.authority.begin_purge('uncertain','a'*64,head)
        with self.assertRaises(CheckpointRecoveryError):self.open_host()

    def test_second_thread_cannot_use_another_threads_mutation_permission(self):
        self.ledger._checkpoint_thread=threading.get_ident()
        caught=[]
        def attempt():
            try:Ledger.purge(self.ledger,self.token,self.record,'PURGE:'+self.record)
            except Exception as exc:caught.append(exc)
        child=threading.Thread(target=attempt);child.start();child.join(timeout=10)
        self.ledger._checkpoint_thread=None
        self.assertFalse(child.is_alive());self.assertEqual(len(caught),1)
        self.assertIsInstance(caught[0],CheckpointRecoveryError)
        self.assertEqual(len(self.ledger.search(self.token,'banana')),1)

    def test_managed_host_delete_survives_original_source_and_history_loss(self):
        snapshot=self.root/'snapshot.sqlite'
        publish_snapshot_candidate(self.ledger,snapshot,self.authority,store_id=self.store_id,environment=self.environment)
        self.purge();self.ledger.close()
        self.database.rename(self.root/'unavailable-source.sqlite')
        self.history.rename(self.root/'unavailable-history.jsonl')
        restored=restore_checkpoint_candidate(snapshot,self.root/'restored.sqlite',None,self.authority,
            store_id=self.store_id,environment=self.environment,review_ref='fixture:restore',**self.keys)
        try:self.assertEqual(restored.search(self.token,'banana'),[])
        finally:restored.close()

    def test_invalid_mutation_callback_cannot_bypass_the_canonical_writer(self):
        with self.assertRaises(CheckpointRecoveryError):
            purge_checkpoint_candidate(self.ledger,self.token,self.record,'PURGE:'+self.record,self.authority,
                operation_id='bad-callback',store_id=self.store_id,environment=self.environment,
                canonical_purge=lambda *args:self.fail('arbitrary callback executed'))
        self.assertEqual(len(self.ledger.search(self.token,'banana')),1)

    def prepare_restore(self):
        snapshot=self.root/'handoff-snapshot.sqlite'
        publish_snapshot_candidate(self.ledger,snapshot,self.authority,
            store_id=self.store_id,environment=self.environment)
        self.ledger.close()
        return snapshot,self.root/'handoff.sqlite'

    def restore_host(self,snapshot,destination,history=None,**overrides):
        arguments=dict(store_id=self.store_id,environment=self.environment,
                       review_ref='fixture:offline-handoff',**self.keys)
        arguments.update(overrides)
        return restore_checkpointed_candidate(snapshot,destination,history,self.authority,**arguments)

    def test_restore_handoff_closes_plain_handle_before_protected_open(self):
        snapshot,destination=self.prepare_restore()
        plain=[]
        def capture(*args,**kwargs):
            result=restore_checkpoint_candidate(*args,**kwargs);plain.append(result);return result
        def checked_open(*args,**kwargs):
            self.assertEqual(len(plain),1)
            with self.assertRaises(sqlite3.ProgrammingError):plain[0].db.execute('SELECT 1')
            return CheckpointedLedgerCandidate(*args,**kwargs)
        with patch.object(host_module,'restore_checkpoint_candidate',side_effect=capture), \
             patch.object(host_module,'CheckpointedLedgerCandidate',side_effect=checked_open):
            restored=self.restore_host(snapshot,destination)
        try:
            self.assertIsInstance(restored,CheckpointedLedgerCandidate)
            self.assertEqual(len(restored.search(self.token,'banana')),1)
            with self.assertRaises(CheckpointRecoveryError):
                restored.purge(self.token,self.record,'PURGE:'+self.record)
        finally:restored.close()

    def test_restore_handoff_managed_delete_is_retained_and_replayed(self):
        snapshot,destination=self.prepare_restore()
        restored=self.restore_host(snapshot,destination)
        try:
            receipt=restored.purge(self.token,self.record,'PURGE:'+self.record,
                                  operation_id='recovered-writer-delete')
            self.assertTrue(receipt['checkpointAcknowledged'])
            with self.authority.hold(self.store_id,self.environment) as lease:
                self.assertEqual(lease.history(),restored.deletion_ledger_path.read_bytes())
        finally:restored.close()
        recovered_again=self.restore_host(snapshot,self.root/'handoff-again.sqlite')
        try:self.assertEqual(recovered_again.search(self.token,'banana'),[])
        finally:recovered_again.close()

    def test_restore_handoff_failed_protected_open_preserves_outputs_and_closes_plain(self):
        snapshot,destination=self.prepare_restore();plain=[]
        def capture(*args,**kwargs):
            result=restore_checkpoint_candidate(*args,**kwargs);plain.append(result);return result
        with patch.object(host_module,'restore_checkpoint_candidate',side_effect=capture), \
             patch.object(host_module,'CheckpointedLedgerCandidate',side_effect=CheckpointRecoveryError('fixture refusal')):
            with self.assertRaisesRegex(CheckpointRecoveryError,'fixture refusal'):
                self.restore_host(snapshot,destination)
        self.assertTrue(destination.is_file())
        self.assertTrue(Path(str(destination)+'.deletions.jsonl').is_file())
        self.assertEqual(len(plain),1)
        with self.assertRaises(sqlite3.ProgrammingError):plain[0].db.execute('SELECT 1')

    def test_restore_handoff_wrong_identity_creates_no_output(self):
        snapshot,destination=self.prepare_restore()
        with self.assertRaises(CheckpointRecoveryError):
            self.restore_host(snapshot,destination,store_id='00000000-0000-4000-8000-000000000000')
        self.assertFalse(destination.exists())
        self.assertFalse(Path(str(destination)+'.deletions.jsonl').exists())

    def test_restore_handoff_refuses_stale_history_before_output(self):
        snapshot=self.root/'handoff-snapshot.sqlite'
        publish_snapshot_candidate(self.ledger,snapshot,self.authority,
            store_id=self.store_id,environment=self.environment)
        stale=self.root/'stale-history.jsonl';stale.write_bytes(self.history.read_bytes())
        self.purge();self.ledger.close();destination=self.root/'handoff.sqlite'
        with self.assertRaises(CheckpointRecoveryError):self.restore_host(snapshot,destination,stale)
        self.assertFalse(destination.exists())

    def test_restore_handoff_refuses_unbound_authority_before_output(self):
        snapshot,destination=self.prepare_restore()
        with self.assertRaises(CheckpointRecoveryError):
            restore_checkpointed_candidate(snapshot,destination,None,object(),store_id=self.store_id,
                environment=self.environment,review_ref='fixture:offline-handoff',**self.keys)
        self.assertFalse(destination.exists())

    def test_restore_handoff_refuses_even_current_external_history(self):
        snapshot,destination=self.prepare_restore()
        original=self.history.read_bytes()
        with self.assertRaisesRegex(CheckpointRecoveryError,'recovery-local'):
            self.restore_host(snapshot,destination,self.history)
        self.assertFalse(destination.exists())
        self.assertEqual(self.history.read_bytes(),original)

    def test_restore_handoff_rechecks_history_after_plain_handle_closes(self):
        snapshot,destination=self.prepare_restore()
        def changed_during_handoff(*args,**kwargs):
            # Simulate an otherwise-retired source advancing the authority in the
            # close/reopen gap. This must refuse the now-stale restored copy.
            original=self.open_host()
            try:
                original.purge(self.token,self.record,'PURGE:'+self.record,
                               operation_id='fixture:intervening-delete')
            finally:original.close()
            return CheckpointedLedgerCandidate(*args,**kwargs)
        with patch.object(host_module,'CheckpointedLedgerCandidate',side_effect=changed_during_handoff):
            with self.assertRaises(CheckpointRecoveryError):self.restore_host(snapshot,destination)
        self.assertTrue(destination.exists())
        self.assertTrue(Path(str(destination)+'.deletions.jsonl').exists())


if __name__=='__main__':unittest.main()
