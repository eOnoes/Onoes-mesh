"""One-time protected provisioning, native custody and read-only handoff: TEMP only."""
from dataclasses import replace
import json
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
import unittest
from unittest.mock import patch

from onoes_mind.ledger import Ledger, LedgerError
from onoes_mind.recall_binding import RecallBinding, prepare_store_identity
from checkpointed_ledger_candidate import CheckpointedLedgerCandidate
from persistent_authority import PersistentAuthorityCandidate
from native_recall_candidate import NativeRecallHost, load_service_credential, SCOPE
import provision_recall_candidate as provision
import test_operator_setup_candidate as fixtures
from test_native_recall_candidate import NODE


@unittest.skipUnless(sys.platform=='win32','Native Windows private service custody')
class ProtectedRecallProvisionTests(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.OperatorSetupCandidateTests();self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.database=(self.fixture.data/'source.sqlite').resolve()
        self.history=self.fixture.data/'history.jsonl'
        self.environment='synthetic-provisioning'
        self.keys=dict(audit_key=secrets.token_bytes(32),deletion_key=secrets.token_bytes(32))
        source=Ledger(self.database,deletion_ledger_path=self.history,environment_id=self.environment,**self.keys)
        try:
            self.store_id=prepare_store_identity(source,environment=self.environment,authority_ref='fixture:owner')
            self.authority=PersistentAuthorityCandidate.create(self.fixture.authority,source,
                store_id=self.store_id,environment=self.environment,review_ref='fixture:authority')
        finally:source.close()
        self.writer=CheckpointedLedgerCandidate(self.database,self.history,self.authority,
            store_id=self.store_id,environment=self.environment,**self.keys)
        self.addCleanup(self.writer.close)
        stat=self.database.stat()
        self.binding=RecallBinding(str(self.database),self.store_id,self.environment,'fixture:owner',SCOPE,
            stat.st_dev,stat.st_ino,'fixture:custodian','fixture:revoke','fixture:approved-provision')
        self.credential=self.fixture.backup/'service.json'
        self.outcome=self.fixture.backup/'outcome.json'

    def run_provision(self,**changes):
        values=dict(binding=self.binding,credential_path=self.credential,outcome_path=self.outcome,
                    operation_id='fixture:one-attempt',approval_ref=self.binding.review_ref)
        values.update(changes)
        return provision.provision_reader(self.writer,**values)

    def principal_count(self):
        return self.writer.db.execute('SELECT COUNT(*) FROM principals').fetchone()[0]

    def test_empty_store_provisions_only_read_service_then_closes_writer_before_native_handoff(self):
        self.assertEqual(self.principal_count(),0);history=self.history.read_bytes()
        result=self.run_provision();saved=json.loads(self.outcome.read_text())
        self.assertEqual(saved,result);self.assertEqual(result['status'],'provisioned_inactive')
        self.assertFalse(result['readerStarted']);self.assertEqual(self.principal_count(),1)
        self.assertEqual(self.writer.db.execute('SELECT COUNT(*) FROM credentials').fetchone()[0],0)
        self.assertEqual(self.writer.db.execute('SELECT COUNT(*) FROM memory_records').fetchone()[0],0)
        self.assertEqual(self.history.read_bytes(),history)
        token=load_service_credential(self.credential,binding=self.binding)
        self.assertNotIn(token,self.outcome.read_text());self.assertNotIn(token.encode(),self.credential.read_bytes())
        with self.assertRaises(LedgerError):self.writer.authenticate(token)
        self.writer.close()  # No protected writer is retained by the reader handoff.
        host=NativeRecallHost(binding=self.binding,credential_path=self.credential);self.addCleanup(host.close)
        host.start()
        result=subprocess.run([shutil.which('node'),'--input-type=module','-e',NODE,
            str(Path(__file__).resolve().parents[2]/'lib/mind-recall.mjs')],
            input=json.dumps(host.native_options()),capture_output=True,text=True,timeout=15,
            creationflags=subprocess.CREATE_NO_WINDOW)
        self.assertEqual(result.returncode,0,result.stderr)
        response=json.loads(result.stdout);self.assertTrue(response['ok']);self.assertEqual(response['result']['records'],[])

    def test_plain_writer_mismatched_binding_and_review_ref_refuse_before_any_marker_or_mutation(self):
        plain=Ledger.__new__(Ledger)  # No constructor/file open; type refusal must happen first.
        with self.assertRaises(provision.RecallProvisionError):
            provision.provision_reader(plain,binding=self.binding,credential_path=self.credential,
                outcome_path=self.outcome,operation_id='fixture:attempt',approval_ref=self.binding.review_ref)
        for changes in ({'store_id':'00000000-0000-4000-8000-000000000001'},
                        {'file_inode':self.binding.file_inode+1},{'scope_id':'project/other/shared'},
                        {'authority_ref':'fixture:another-owner'}):
            with self.assertRaises(provision.RecallProvisionError):self.run_provision(binding=replace(self.binding,**changes))
        with self.assertRaises(provision.RecallProvisionError):self.run_provision(approval_ref='fixture:wrong-review')
        self.assertFalse(self.outcome.exists());self.assertFalse(self.credential.exists());self.assertEqual(self.principal_count(),0)

    def test_existing_credential_or_marker_is_never_overwritten_or_followed_by_grant(self):
        self.outcome.write_bytes(b'preserve outcome')
        with self.assertRaises(provision.RecallProvisionError):self.run_provision()
        self.assertEqual(self.outcome.read_bytes(),b'preserve outcome')
        self.credential.write_bytes(b'preserve credential')
        with self.assertRaises(provision.RecallProvisionError):
            self.run_provision(outcome_path=self.fixture.backup/'different-outcome.json')
        self.assertEqual(self.credential.read_bytes(),b'preserve credential');self.assertEqual(self.principal_count(),0)

    def test_existing_service_principal_blocks_reissue_even_with_different_new_paths(self):
        self.run_provision();ciphertext=self.credential.read_bytes()
        verifier=tuple(self.writer.db.execute('SELECT * FROM recall_service_credentials').fetchone())
        with patch.object(provision,'issue_mesh_recall_credential') as issue:
            with self.assertRaises(provision.RecallProvisionError):
                self.run_provision(credential_path=self.fixture.backup/'new-credential.json',
                    outcome_path=self.fixture.backup/'new-outcome.json')
            issue.assert_not_called()
        self.assertEqual(tuple(self.writer.db.execute('SELECT * FROM recall_service_credentials').fetchone()),verifier)
        self.assertEqual(self.credential.read_bytes(),ciphertext)
        self.assertFalse((self.fixture.backup/'new-outcome.json').exists())

    def test_storage_failure_preserves_partial_provision_and_unknown_outcome_without_retry(self):
        with patch.object(provision,'seal_service_credential',side_effect=OSError('fixture-secret-native-error')) as seal:
            with self.assertRaises(provision.RecallProvisionError) as error:self.run_provision()
            self.assertEqual(seal.call_count,1)
        saved=json.loads(self.outcome.read_text())
        self.assertEqual(saved['status'],'outcome_unknown');self.assertTrue(saved['mayHaveChanged'])
        self.assertEqual(saved['stage'],'protected-storage');self.assertEqual(self.principal_count(),1)
        self.assertEqual(self.writer.db.execute('SELECT COUNT(*) FROM recall_service_credentials').fetchone()[0],1)
        self.assertNotIn('fixture-secret',str(error.exception)+self.outcome.read_text())
        self.assertFalse(self.credential.exists())
        with self.assertRaises(provision.RecallProvisionError):self.run_provision()

    def test_damaged_current_history_refuses_before_provisioning(self):
        self.history.write_text('invalid synthetic history\n')
        with self.assertRaises(provision.RecallProvisionError):self.run_provision()
        self.assertEqual(self.principal_count(),0);self.assertFalse(self.outcome.exists());self.assertFalse(self.credential.exists())

    def test_provisioning_releases_authority_lease_and_managed_purge_still_works(self):
        self.run_provision()
        self.writer.create_principal('operator')
        token=self.writer.issue_credential('operator','fixture-operator-token')
        record=self.writer.remember(token,dict(event_id='fixture-later-record',kind='project_fact',
            project_id='fixture',claim='fixture later record',requested_visibility='shared'))['record_id']
        self.writer.purge(token,record,'PURGE:'+record,operation_id='fixture:managed-purge-after-provision')
        self.assertEqual(self.writer.integrity_report()['status'],'PASS')
        self.assertTrue(load_service_credential(self.credential,binding=self.binding))


if __name__=='__main__':unittest.main()
