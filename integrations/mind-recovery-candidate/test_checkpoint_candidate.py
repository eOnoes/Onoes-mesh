"""Disposable authority fixture. This is NOT a production freshness provider."""
from contextlib import contextmanager, closing
from dataclasses import asdict
from pathlib import Path
import hashlib
import json
import secrets
import sqlite3
import sys
import tempfile
import unittest
import uuid
from unittest.mock import patch

sys.path.insert(0, 'D:/Dev/Onoes-Mind')
from onoes_mind import Ledger
from onoes_mind.recall_binding import prepare_store_identity
from onoes_mind.store_init import restore_new_ledger
from checkpoint_candidate import (Head, SnapshotReceipt, CheckpointRecoveryError,
    history_view, publish_snapshot_candidate, purge_checkpoint_candidate,
    restore_checkpoint_candidate)


class FixtureAuthority:
    """SQLite persists acknowledgement/uncertainty across fixture restarts.

    Independence/currentness is ASSUMED from the test's explicit source selection;
    no filesystem, same-login, machine or administrator anti-rollback claim.
    """
    def __init__(self, path, initial=None):
        self.path = path
        self.fail_ack = self.fail_commit = False
        with closing(self.connect()) as db, db:
            db.executescript('CREATE TABLE IF NOT EXISTS head(id PRIMARY KEY,body,blocked);'
                             'CREATE TABLE IF NOT EXISTS snapshots(dbhash,metahash,body,PRIMARY KEY(dbhash,metahash));'
                             'CREATE TABLE IF NOT EXISTS purges(id PRIMARY KEY,hash,ticket,state,receipt);')
            if initial is not None:
                db.execute('INSERT INTO head VALUES(1,?,0)', (json.dumps(asdict(initial)),))

    def connect(self):
        return sqlite3.connect(self.path, timeout=0)

    @contextmanager
    def hold(self, store_id, environment):
        db = self.connect()
        try:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT body,blocked FROM head WHERE id=1').fetchone()
            if not row or row[1]:
                raise CheckpointRecoveryError('Checkpoint is missing or a purge is unacknowledged.')
            head = Head(**json.loads(row[0]))
            if (head.store_id, head.environment) != (store_id, environment):
                raise CheckpointRecoveryError('Authority identity mismatch.')
            class Lease:
                def current(self):
                    return head
                def assert_current(self, expected):
                    latest = db.execute('SELECT body,blocked FROM head WHERE id=1').fetchone()
                    if latest[1] or Head(**json.loads(latest[0])) != expected:
                        raise CheckpointRecoveryError('Checkpoint changed.')
                def register_snapshot(self, receipt):
                    db.execute('INSERT INTO snapshots VALUES(?,?,?)',
                               (receipt.database_sha256, receipt.metadata_sha256, json.dumps(asdict(receipt))))
                def snapshot_receipt(self, data, meta):
                    r = db.execute('SELECT body FROM snapshots WHERE dbhash=? AND metahash=?', (data, meta)).fetchone()
                    return SnapshotReceipt(**json.loads(r[0])) if r else None
            yield Lease()
            if self.fail_commit:
                raise CheckpointRecoveryError('Fixture acknowledgement lost before commit.')
            db.commit()
        finally:
            db.rollback()
            db.close()

    def begin_purge(self, operation_id, payload_hash, actual):
        with closing(self.connect()) as db, db:
            db.execute('BEGIN IMMEDIATE')
            old = db.execute('SELECT hash,ticket,state,receipt FROM purges WHERE id=?', (operation_id,)).fetchone()
            if old:
                if old[0] != payload_hash or old[2] != 'completed':
                    raise CheckpointRecoveryError('Divergent or uncertain purge is held.')
                return {'completed': True, 'receipt': json.loads(old[3])}
            row = db.execute('SELECT body,blocked FROM head').fetchone()
            if row[1] or Head(**json.loads(row[0])) != actual:
                raise CheckpointRecoveryError('Purge is not at the current checkpoint.')
            ticket = str(uuid.uuid4())
            db.execute('UPDATE head SET blocked=1')
            db.execute('INSERT INTO purges VALUES(?,?,?,?,NULL)', (operation_id, payload_hash, ticket, 'pending'))
        return {'completed': False, 'ticket': ticket}

    def ack_purge(self, operation_id, payload_hash, ticket, head, history=None):
        if self.fail_ack:
            raise CheckpointRecoveryError('Fixture checkpoint acknowledgement unavailable.')
        with closing(self.connect()) as db, db:
            db.execute('BEGIN IMMEDIATE')
            old = db.execute('SELECT hash,ticket,state FROM purges WHERE id=?', (operation_id,)).fetchone()
            if old != (payload_hash, ticket, 'pending'):
                raise CheckpointRecoveryError('Purge ticket mismatch.')
            receipt = {'operationId': operation_id, 'checkpointAcknowledged': True, 'sequence': head.sequence}
            db.execute('UPDATE head SET body=?,blocked=0', (json.dumps(asdict(head)),))
            db.execute("UPDATE purges SET state='completed',receipt=? WHERE id=?", (json.dumps(receipt), operation_id))
        return receipt


class RecoveryCandidateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.keys = dict(audit_key=secrets.token_bytes(32), deletion_key=secrets.token_bytes(32))
        self.environment = 'synthetic-checkpoint-candidate'
        self.history = self.root / 'synthetic-history.jsonl'
        self.ledger = Ledger(self.root / 'source.sqlite', deletion_ledger_path=self.history,
                             environment_id=self.environment, **self.keys)
        self.store_id = prepare_store_identity(self.ledger, environment=self.environment,
                                               authority_ref='fixture:explicit-source')
        head, _ = history_view(self.ledger, self.history, self.store_id, self.environment)
        self.authority = FixtureAuthority(self.root / 'independent-fixture-authority.sqlite', head)
        self.snapshot, self.target = self.root / 'backup.sqlite', self.root / 'restored.sqlite'

    def tearDown(self):
        self.ledger.close()
        self.temp.cleanup()

    def remember(self, text):
        if not hasattr(self, 'token'):
            self.ledger.create_principal('operator')
            self.token = self.ledger.issue_credential('operator', 'fixture-only-token')
        return self.ledger.remember(self.token, dict(event_id=str(uuid.uuid4()), claim=text,
            kind='project_fact', project_id='onoes-mind', requested_visibility='shared'))['record_id']

    def publish(self):
        return publish_snapshot_candidate(self.ledger, self.snapshot, self.authority,
                                           store_id=self.store_id, environment=self.environment)

    def restore(self, **kwargs):
        args = dict(snapshot=self.snapshot, destination=self.target, deletion_history=self.history,
                    authority=self.authority, store_id=self.store_id, environment=self.environment,
                    review_ref='fixture:review-only', **self.keys)
        args.update(kwargs)
        return restore_checkpoint_candidate(**args)

    def purge(self, record, operation_id=None):
        return purge_checkpoint_candidate(self.ledger, self.token, record, 'PURGE:' + record,
            self.authority, operation_id=operation_id or str(uuid.uuid4()),
            store_id=self.store_id, environment=self.environment)

    def test_empty_unchanged_snapshot_restores_only_with_registered_current_proof(self):
        self.publish()
        restored = self.restore()
        try:
            self.assertEqual(restored.integrity_report()['status'], 'PASS')
            self.assertEqual(restored.db.execute('SELECT count(*) FROM memory_records').fetchone()[0], 0)
        finally:
            restored.close()

    def test_populated_unchanged_snapshot_preserves_actual_search(self):
        self.remember('fixture banana project')
        self.publish()
        restored = self.restore()
        try:
            self.assertEqual(len(restored.search(self.token, 'banana')), 1)
        finally:
            restored.close()

    def test_later_purges_replay_complete_chain_before_any_recall(self):
        first = self.remember('fixture banana project')
        second = self.remember('fixture melon project')
        self.publish()
        self.purge(first)
        self.purge(second)
        restored = self.restore()
        try:
            self.assertEqual(restored.search(self.token, 'banana'), [])
            self.assertEqual(restored.search(self.token, 'melon'), [])
            self.assertEqual(restored.db.execute("SELECT count(*) FROM memory_records WHERE state='purged'").fetchone()[0], 2)
        finally:
            restored.close()

    def test_old_valid_history_cannot_substitute_for_current_acknowledged_head(self):
        record = self.remember('fixture banana')
        self.publish()
        stale = self.root / 'old-valid-history.jsonl'
        stale.write_bytes(self.history.read_bytes())
        self.purge(record)
        with self.assertRaises(CheckpointRecoveryError):
            self.restore(deletion_history=stale)
        self.assertFalse(self.target.exists())

    def test_missing_snapshot_registration_is_not_self_attestation(self):
        self.ledger.backup(self.snapshot)
        with self.assertRaises(CheckpointRecoveryError):
            self.restore()
        self.assertFalse(self.target.exists())

    def test_wrong_store_environment_and_missing_review_refuse_before_target(self):
        self.publish()
        for extra in ({'store_id':str(uuid.uuid4())}, {'environment':'wrong-fixture'}, {'review_ref':''}):
            with self.subTest(extra=extra), self.assertRaises(CheckpointRecoveryError):
                self.restore(**extra)
            self.assertFalse(self.target.exists())

    def test_corrupt_truncated_or_missing_history_refuses(self):
        record = self.remember('fixture banana')
        self.publish()
        self.purge(record)
        valid = self.history.read_bytes()
        for bad in (b'', valid[:-8], valid.replace(b'chain_hash', b'chain_wrong')):
            self.history.write_bytes(bad)
            with self.assertRaises(CheckpointRecoveryError):
                self.restore()
            self.assertFalse(self.target.exists())
        self.history.write_bytes(valid)

    def test_registered_snapshot_bytes_and_metadata_are_both_bound(self):
        self.publish()
        metadata = Path(str(self.snapshot) + '.meta')
        original = metadata.read_bytes()
        value = json.loads(original);value['snapshot_at'] = 'different-fixture-time'
        metadata.write_text(json.dumps(value))
        with self.assertRaises(CheckpointRecoveryError):
            self.restore()
        self.assertFalse(self.target.exists())

    def test_unacknowledged_purge_blocks_recovery_after_authority_restart(self):
        record = self.remember('fixture banana')
        self.publish()
        self.authority.fail_ack = True
        with self.assertRaises(CheckpointRecoveryError):
            self.purge(record, 'same-purge-operation')
        self.authority = FixtureAuthority(self.authority.path)
        with self.assertRaises(CheckpointRecoveryError):
            self.restore()
        self.assertFalse(self.target.exists())
        self.assertEqual(self.ledger.search(self.token, 'banana'), [])

    def test_acknowledged_purge_retry_is_same_receipt_without_second_tombstone(self):
        record = self.remember('fixture banana')
        self.publish()
        receipt = self.purge(record, 'same-purge-operation')
        self.authority = FixtureAuthority(self.authority.path)
        self.assertEqual(self.purge(record, 'same-purge-operation'), receipt)
        self.assertEqual(len(self.history.read_text().splitlines()) - 1, 1)

    def test_changed_purge_payload_under_same_operation_is_rejected(self):
        first = self.remember('fixture banana')
        second = self.remember('fixture melon')
        self.publish();self.purge(first, 'bound-operation')
        with self.assertRaises(CheckpointRecoveryError):
            self.purge(second, 'bound-operation')
        self.assertEqual(len(self.ledger.search(self.token, 'melon')), 1)

    def test_lost_snapshot_ack_leaves_no_accepted_registration(self):
        self.authority.fail_commit = True
        with self.assertRaises(CheckpointRecoveryError):
            self.publish()
        self.authority = FixtureAuthority(self.authority.path)
        with self.assertRaises(CheckpointRecoveryError):
            self.restore()
        self.assertFalse(self.target.exists())

    def test_failed_authority_exit_after_copy_preserves_target_but_never_returns_success(self):
        self.publish();self.authority.fail_commit = True
        with self.assertRaises(CheckpointRecoveryError):
            self.restore()
        self.assertTrue(self.target.exists())
        db = sqlite3.connect(self.target);db.execute('BEGIN EXCLUSIVE');db.rollback();db.close()

    def test_existing_destination_is_preserved(self):
        self.publish();self.target.write_bytes(b'keep-existing-fixture')
        with self.assertRaises(CheckpointRecoveryError):
            self.restore()
        self.assertEqual(self.target.read_bytes(), b'keep-existing-fixture')

    def test_unmanaged_later_purge_cannot_hide_behind_old_checkpoint(self):
        record = self.remember('fixture banana');self.publish()
        self.ledger.purge(self.token, record, 'PURGE:' + record)
        with self.assertRaises(CheckpointRecoveryError):
            self.restore()
        self.assertFalse(self.target.exists())

    def test_default_canonical_restore_still_refuses_equal_history(self):
        self.publish()
        with self.assertRaisesRegex(Exception, 'not newer'):
            restore_new_ledger(self.snapshot, self.target, self.history, **self.keys,
                environment_id=self.environment, expected_deletion_sha256=hashlib.sha256(self.history.read_bytes()).hexdigest(),
                review_ref='fixture:unchanged-default')
        self.assertFalse(self.target.exists())

    def test_wrong_producer_identity_refuses_before_purge(self):
        record = self.remember('fixture banana')
        with self.assertRaises(CheckpointRecoveryError):
            purge_checkpoint_candidate(self.ledger, self.token, record, 'PURGE:' + record,
                self.authority, operation_id='wrong-store-operation', store_id=str(uuid.uuid4()),
                environment=self.environment)
        self.assertEqual(len(self.ledger.search(self.token, 'banana')), 1)
        self.assertEqual(len(self.history.read_text().splitlines()), 1)

    def test_unconfirmed_or_wrong_operation_ack_never_reports_purge_success(self):
        record = self.remember('fixture banana')
        self.authority.ack_purge = lambda *args: {'operationId':'different-operation',
                                                'checkpointAcknowledged':True,'sequence':1}
        with self.assertRaisesRegex(CheckpointRecoveryError, 'acknowledgement'):
            self.purge(record, 'exact-operation')
        self.authority = FixtureAuthority(self.authority.path)
        with self.assertRaises(CheckpointRecoveryError):
            with self.authority.hold(self.store_id, self.environment):
                self.fail('Unacknowledged mutation was accepted.')

    def test_held_restore_checkpoint_excludes_a_concurrent_managed_purge(self):
        record = self.remember('fixture banana');self.publish()
        with self.authority.hold(self.store_id, self.environment):
            with self.assertRaises(sqlite3.OperationalError):
                self.purge(record)
        self.assertEqual(len(self.ledger.search(self.token, 'banana')), 1)

    def test_wrong_audit_or_deletion_keys_refuse_a_populated_snapshot(self):
        record = self.remember('fixture banana');self.publish();self.purge(record)
        for override in ({'audit_key':secrets.token_bytes(32)}, {'deletion_key':secrets.token_bytes(32)}):
            with self.subTest(key=next(iter(override))), self.assertRaises(CheckpointRecoveryError):
                self.restore(**override)
            self.assertFalse(self.target.exists())

    def test_malformed_purge_admission_cannot_mutate_the_ledger(self):
        record = self.remember('fixture banana')
        for response in ({}, {'completed':False}, {'completed':False,'ticket':'invalid'}):
            self.authority.begin_purge = lambda *args, r=response: r
            with self.assertRaises((CheckpointRecoveryError, ValueError)):
                self.purge(record)
            self.assertEqual(len(self.ledger.search(self.token, 'banana')), 1)
            self.assertEqual(len(self.history.read_text().splitlines()), 1)

    def test_canonical_chain_verifier_receives_the_exact_captured_bytes(self):
        expected = self.history.read_bytes()
        original = self.ledger.verify_deletion_ledger
        def check():
            self.assertEqual(self.ledger.deletion_ledger_path.read_text().encode(), expected)
            self.assertNotIsInstance(self.ledger.deletion_ledger_path, Path)
            return original()
        with patch.object(self.ledger, 'verify_deletion_ledger', side_effect=check):
            history_view(self.ledger, self.history, self.store_id, self.environment)

    def test_unauthorized_purge_cannot_even_reserve_a_recovery_fence(self):
        record = self.remember('fixture banana');self.publish()
        self.ledger.create_principal('echo')
        echo = self.ledger.issue_credential('echo', 'fixture-only-echo-token')
        with self.assertRaises(CheckpointRecoveryError):
            purge_checkpoint_candidate(self.ledger, echo, record, 'PURGE:' + record,
                self.authority, operation_id='unauthorized-operation',
                store_id=self.store_id, environment=self.environment)
        restored = self.restore()
        try:
            self.assertEqual(len(restored.search(self.token, 'banana')), 1)
        finally:
            restored.close()


if __name__ == '__main__':
    unittest.main()
