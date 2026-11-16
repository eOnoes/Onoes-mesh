"""Prepared populated-store archive tests; all keys/data are synthetic fixtures."""
import contextlib
import getpass
import io
import json
import os
from pathlib import Path
import shutil
import sqlite3
import unittest
from unittest.mock import patch
import warnings
import uuid

import project_backup_candidate as backup


class BackupPasswordTests(unittest.TestCase):
    def test_hidden_password_confirmation_and_no_echo_fallback(self):
        secret='synthetic-backup-passphrase-2026'
        with patch('getpass.getpass',side_effect=[secret,secret]):
            self.assertEqual(backup.prompt_archive_password(),secret)
        with patch('getpass.getpass',side_effect=[secret,'different']):
            with self.assertRaises(ValueError): backup.prompt_archive_password()
        def cannot_hide(*args,**kwargs):
            warnings.warn('cannot hide',getpass.GetPassWarning)
        with patch('getpass.getpass',side_effect=cannot_hide):
            with self.assertRaises(getpass.GetPassWarning): backup.prompt_archive_password()


@unittest.skipUnless(os.name=='nt','Windows DPAPI/private-folder fixture')
class PreparedProjectArchiveTests(unittest.TestCase):
    def setUp(self):
        import test_encrypted_backup_candidate as fixtures
        self.case=fixtures.EncryptedBackupTests();self.case.setUp();self.addCleanup(self.case.doCleanups)
        target=Path('E:/App-Backups/Onoes-Mind/Candidates/Existing-project-backup-2026-11-16')
        target.mkdir(parents=True,exist_ok=True)
        self.case.destination=target/(self._testMethodName+'-'+uuid.uuid4().hex+'.7z')

    def run_backup(self,**overrides):
        c=self.case
        options=dict(publication=c.publication,authority=c.fixture.authority,review_ref='fixture:existing-store-backup')
        options.update(overrides)
        return backup.archive_prepared_project_backup(c.source,c.stage,c.output,c.destination,c.tool,c.password,**options)

    def test_populated_project_receipts_and_later_purge_survive_archive_rehearsal(self):
        from checkpoint_candidate import publish_snapshot_candidate
        from project_events_candidate import EventBinding,ProjectEventsCandidate
        from test_project_events_candidate import event
        c=self.case;f=c.fixture;ledger=f.ledger;s=ledger.path.stat()
        writer=ProjectEventsCandidate(ledger,EventBinding(str(ledger.path.resolve()),s.st_dev,s.st_ino,f.store_id,f.environment,'fixture:source'))
        writer.initialize();writer.register_project('project-A','Synthetic archived project');token=writer.enroll(['project-A'])
        first=writer.submit(token,event());writer.submit(token,event(2))
        snapshot='project-snapshot.sqlite'
        c.publication=publish_snapshot_candidate(ledger,c.source/snapshot,f.authority,store_id=f.store_id,environment=f.environment)
        record=ledger.db.execute('SELECT record_id FROM project_sync_events LIMIT 1').fetchone()[0]
        ledger.purge(f.token,record,'PURGE:'+record,operation_id='synthetic-prepared-archive-later-purge')
        shutil.copyfile(f.history,c.source/'snapshot-deletion-history.jsonl')
        source_before=(c.source/'encrypted-key-enrollment.json').read_bytes()
        output=io.StringIO();observed={}
        import checkpointed_ledger_candidate as recovery
        original=recovery.restore_checkpointed_candidate
        def observe_restore(*args,**kwargs):
            recovered=original(*args,**kwargs);stat=recovered.path.stat()
            view=ProjectEventsCandidate(recovered,EventBinding(str(recovered.path.resolve()),stat.st_dev,stat.st_ino,f.store_id,f.environment,'fixture:source'))
            observed['receiptState']=view.lookup(token,project_id='project-A',event_id='event-1')['recordState']
            observed['search']=recovered.search(f.token,'Synthetic')
            return recovered
        with contextlib.redirect_stdout(output),patch.object(recovery,'restore_checkpointed_candidate',side_effect=observe_restore):
            receipt=self.run_backup(source_snapshot=snapshot)
        self.assertEqual(receipt['projectReceiptCount'],2)
        self.assertEqual(receipt['archiveRehearsal'],'PASS')
        self.assertFalse(receipt['credentialRecoveryQualified']);self.assertFalse(receipt['sourceLedgerOpened'])
        self.assertEqual((c.source/'encrypted-key-enrollment.json').read_bytes(),source_before)
        restored=sqlite3.connect((c.output/'verified-restored.sqlite').as_uri()+'?mode=ro',uri=True)
        try:
            self.assertEqual(restored.execute('SELECT count(*) FROM project_sync_events').fetchone()[0],2)
            self.assertEqual(observed,dict(receiptState='purged',search=[]))
        finally: restored.close()
        self.assertNotIn(token,json.dumps(receipt)+output.getvalue())
        self.assertNotIn(first['receiptId'],json.dumps(receipt))
        self.assertEqual(json.loads((c.stage/'initialized-backup-rehearsal-receipt.json').read_text()),receipt)
        proof=Path(__file__).resolve().parents[2]/'data/project-existing-backup-proof-20261116.json'
        proof.write_text(json.dumps(dict(**receipt,syntheticOnly=True,laterPurgeHidden=True,
            existingKeyPackageUnchanged=True),indent=2)+'\n',encoding='utf-8')

    def test_invalid_review_and_existing_rehearsal_refuse_before_archive(self):
        c=self.case
        with self.assertRaises(ValueError):self.run_backup(review_ref='\nnot a review')
        self.assertFalse(c.destination.exists());self.assertEqual(list(c.stage.iterdir()),[])
        (c.output/'user-work.txt').write_text('preserve',encoding='utf-8')
        with self.assertRaises(ValueError):self.run_backup()
        self.assertFalse(c.destination.exists());self.assertEqual((c.output/'user-work.txt').read_text(),'preserve')

    def test_wrong_receipt_readback_never_reports_success_and_preserves_archive(self):
        import checkpointed_ledger_candidate as restore
        c=self.case;original=restore.restore_checkpointed_candidate
        def missing_receipt(*args,**kwargs):
            ledger=original(*args,**kwargs)
            ledger.db.execute('CREATE TABLE project_sync_events(receipt_id TEXT)')
            ledger.db.execute("INSERT INTO project_sync_events VALUES ('unexpected-row')");ledger.db.commit()
            return ledger
        with patch.object(restore,'restore_checkpointed_candidate',side_effect=missing_receipt):
            with self.assertRaises(ValueError):self.run_backup(source_snapshot='first-empty-snapshot.sqlite')
        self.assertTrue(c.destination.is_file())
        self.assertFalse((c.stage/'initialized-backup-rehearsal-receipt.json').exists())
        self.assertTrue((c.output/'verified-restored.sqlite').exists())


if __name__=='__main__':unittest.main()
