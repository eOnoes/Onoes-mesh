"""Protected revocation guard/failure cases; synthetic private TEMP stores only."""
from dataclasses import replace
import json
import sys
import unittest
from unittest.mock import patch
import test_provision_recall_candidate as fixtures
import provision_recall_candidate as operations
from onoes_mind.ledger import Ledger


@unittest.skipUnless(sys.platform=='win32','Actual private Windows temporary store')
class ProtectedRevokeTests(unittest.TestCase):
    def setUp(self):
        self.f=fixtures.ProtectedRecallProvisionTests();self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.outcome=self.f.fixture.backup/'revocation.json'

    def revoke(self,writer=None,**changes):
        values=dict(binding=self.f.binding,outcome_path=self.outcome,
            operation_id='fixture:revoke',approval_ref=self.f.binding.review_ref)
        values.update(changes)
        return operations.revoke_reader(self.f.writer if writer is None else writer,**values)

    def test_missing_service_wrong_writer_binding_and_existing_marker_cannot_rotate(self):
        with self.assertRaises(operations.RecallProvisionError):self.revoke()
        self.assertFalse(self.outcome.exists())
        self.f.run_provision();cipher=self.f.credential.read_bytes()
        with self.assertRaises(operations.RecallProvisionError):self.revoke(Ledger.__new__(Ledger))
        for change in ({'store_id':'00000000-0000-4000-8000-000000000001'},
                       {'file_inode':self.f.binding.file_inode+1},{'scope_id':'project/other/shared'},
                       {'authority_ref':'fixture:wrong-owner'}):
            with self.assertRaises(operations.RecallProvisionError):self.revoke(binding=replace(self.f.binding,**change))
        with self.assertRaises(operations.RecallProvisionError):self.revoke(approval_ref='fixture:wrong-review')
        with self.assertRaises(ValueError):replace(self.f.binding,scope_id='agent/echo/private')
        self.assertFalse(self.outcome.exists())
        self.outcome.write_text('existing marker')
        with self.assertRaises(operations.RecallProvisionError):self.revoke()
        self.assertEqual(self.outcome.read_text(),'existing marker')
        # Use a distinct, deliberate test target; never overwrite an old outcome.
        new=self.outcome.with_name('deliberate-revocation.json')
        result=self.revoke(outcome_path=new)
        self.assertEqual(result['status'],'revoked');self.assertEqual(result['epochAfter'],result['epochBefore']+1)
        self.assertEqual(self.f.credential.read_bytes(),cipher)
        self.assertEqual(self.f.writer.db.execute('SELECT COUNT(*) FROM credentials').fetchone()[0],0)
        self.assertEqual(self.f.writer.db.execute('SELECT COUNT(*) FROM memory_records').fetchone()[0],0)
        extra=self.outcome.with_name('no-second-rotation.json')
        with self.assertRaises(operations.RecallProvisionError):self.revoke(outcome_path=extra)
        self.assertFalse(extra.exists())

    def test_failure_during_canonical_rotation_preserves_uncertain_marker_and_never_retries(self):
        self.f.run_provision();cipher=self.f.credential.read_bytes()
        canonical=self.f.writer.rotate_credentials
        def fail_after_call(principal):
            pending=json.loads(self.outcome.read_text())
            self.assertEqual(pending['status'],'revocation_pending');self.assertTrue(pending['mayHaveChanged'])
            canonical(principal)
            raise RuntimeError('synthetic-private-error-do-not-echo')
        with patch.object(self.f.writer,'rotate_credentials',side_effect=fail_after_call) as rotate:
            with self.assertRaises(operations.RecallProvisionError) as denied:self.revoke()
            self.assertEqual(rotate.call_count,1)
        self.assertNotIn('synthetic-private-error',str(denied.exception))
        saved=json.loads(self.outcome.read_text());self.assertEqual(saved['status'],'outcome_unknown')
        self.assertTrue(saved['mayHaveChanged']);self.assertEqual(self.f.credential.read_bytes(),cipher)
        with patch.object(self.f.writer,'rotate_credentials') as rotate:
            with self.assertRaises(operations.RecallProvisionError):self.revoke()
            rotate.assert_not_called()


if __name__=='__main__':unittest.main()
