"""Compose real candidate checkpoints/deletions with synthetic project events."""
from pathlib import Path
import unittest
import json
import uuid
import shutil

import test_checkpointed_ledger_candidate as fixtures
import test_encrypted_backup_candidate as encrypted_fixtures
from checkpoint_candidate import publish_snapshot_candidate, history_view
from checkpointed_ledger_candidate import restore_checkpointed_candidate
from project_events_candidate import ProjectEventsCandidate, EventBinding, EventError
from test_project_events_candidate import event
from onoes_mind.runtime_keys import unprotect_runtime_keys


class ProjectSyncRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.CheckpointedLedgerTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.ledger = self.fixture.ledger
        self.writer = self.bind(self.ledger)
        self.writer.initialize()
        self.writer.register_project("project-A", "Synthetic project")
        self.token = self.writer.enroll(["project-A"])
        self.snapshot = self.fixture.root / "project-snapshot.sqlite"

    def bind(self, ledger):
        stat = ledger.path.stat()
        return ProjectEventsCandidate(ledger, EventBinding(str(ledger.path.resolve()), stat.st_dev,
            stat.st_ino, self.fixture.store_id, self.fixture.environment, "fixture:source"))

    def publish(self):
        return publish_snapshot_candidate(self.ledger, self.snapshot, self.fixture.authority,
            store_id=self.fixture.store_id, environment=self.fixture.environment)

    def restore(self):
        self.ledger.close()
        restored = restore_checkpointed_candidate(self.snapshot,
            self.fixture.root / "recovered.sqlite", None, self.fixture.authority,
            **self.fixture.keys, store_id=self.fixture.store_id,
            environment=self.fixture.environment, review_ref="synthetic-project-recovery")
        self.addCleanup(restored.close)
        return restored

    def purge_project_record(self):
        record = self.ledger.db.execute("SELECT record_id FROM project_sync_events ORDER BY sequence DESC LIMIT 1").fetchone()[0]
        return self.ledger.purge(self.fixture.token, record, "PURGE:" + record,
                                 operation_id="synthetic-project-purge")

    def test_receipt_and_provenance_survive_protected_snapshot_restore(self):
        receipt = self.writer.submit(self.token, event())
        self.publish()
        restored = self.restore()
        with self.assertRaises(EventError):
            ProjectEventsCandidate(restored, self.writer.binding)
        writer = self.bind(restored)
        self.assertEqual(writer.lookup(self.token, project_id="project-A", event_id="event-1"), receipt)
        self.assertEqual(restored.db.execute("SELECT count(*) FROM provenance_refs WHERE locator='GUIDE.md'").fetchone()[0], 1)

    def test_later_delete_cannot_reappear_when_backup_predates_card_creation(self):
        self.publish()  # The project exists, but this card/receipt was not yet created.
        self.writer.submit(self.token, event())
        self.purge_project_record()
        restored = self.restore()
        writer = self.bind(restored)
        self.assertIsNone(writer.lookup(self.token, project_id="project-A", event_id="event-1"))
        with self.assertRaises(EventError):
            writer.submit(self.token, event())
        with self.assertRaises(EventError):
            writer.submit(self.token, event(eventId="replacement-event"))

    def test_later_delete_remains_absent_when_snapshot_contains_the_card(self):
        original = self.writer.submit(self.token, event())
        self.publish()
        self.purge_project_record()
        restored = self.restore()
        writer = self.bind(restored)
        replay = writer.submit(self.token, event())
        self.assertEqual(replay["receiptId"], original["receiptId"])
        self.assertEqual(replay["recordState"], "purged")
        with self.assertRaises(EventError):
            writer.submit(self.token, event(2))

    def test_unacknowledged_delete_intent_blocks_reads_and_new_updates(self):
        head, _ = history_view(self.ledger, self.fixture.history, self.fixture.store_id, self.fixture.environment)
        self.fixture.authority.begin_purge("synthetic-pending", "a" * 64, head)
        with self.assertRaises(EventError): self.writer.submit(self.token, event())
        with self.assertRaises(EventError): self.writer.lookup(self.token, project_id="project-A", event_id="event-1")
        self.assertEqual(self.ledger.db.execute("SELECT count(*) FROM project_sync_events").fetchone()[0], 0)

    def test_rolled_back_valid_history_cannot_bypass_the_current_authority(self):
        old = self.fixture.history.read_bytes()
        self.writer.submit(self.token, event())
        self.purge_project_record()
        self.fixture.history.write_bytes(old)
        with self.assertRaises(EventError):
            self.writer.submit(self.token, event(cardId="new-card", eventId="new-event"))
        self.assertEqual(self.ledger.db.execute("SELECT count(*) FROM project_sync_events").fetchone()[0], 1)

    def test_missing_format_marker_is_not_silently_migrated(self):
        self.writer.submit(self.token, event())
        self.ledger.db.execute("DROP TABLE project_sync_format")
        with self.assertRaises(EventError): self.writer.submit(self.token, event(2))
        self.assertFalse(self.ledger.db.execute("SELECT 1 FROM sqlite_schema WHERE name='project_sync_format'").fetchone())


class EncryptedProjectSyncRecoveryTests(unittest.TestCase):
    def test_encrypted_E_archive_preserves_receipts_and_later_deletion_after_source_loss(self):
        case = encrypted_fixtures.EncryptedBackupTests()
        case.setUp()
        self.addCleanup(case.doCleanups)
        fixture = case.fixture
        ledger = fixture.ledger
        stat = ledger.path.stat()
        binding = EventBinding(str(ledger.path.resolve()), stat.st_dev, stat.st_ino,
                               fixture.store_id, fixture.environment, "fixture:source")
        writer = ProjectEventsCandidate(ledger, binding)
        writer.initialize(); writer.register_project("project-A", "Synthetic recovery project")
        token = writer.enroll(["project-A"])
        first = writer.submit(token, event())
        second = writer.submit(token, event(2))
        snapshot_name = "project-populated.sqlite"
        case.publication = publish_snapshot_candidate(ledger, case.source / snapshot_name,
            fixture.authority, store_id=fixture.store_id, environment=fixture.environment)
        record = ledger.db.execute("SELECT record_id FROM project_sync_events LIMIT 1").fetchone()[0]
        ledger.purge(fixture.token, record, "PURGE:" + record, operation_id="synthetic-archive-purge")
        shutil.copyfile(fixture.history, case.source / "snapshot-deletion-history.jsonl")
        target = Path("E:/App-Backups/Onoes-Mind/Candidates/Project-sync-recovery-2026-11-15")
        target.mkdir(parents=True, exist_ok=True)
        case.destination = target / ("Synthetic-project-receipts-" + str(uuid.uuid4()) + ".7z")
        receipt = case.export(source_snapshot=snapshot_name)
        ledger.close()
        # Only these owned synthetic files are renamed; retained authority is independent.
        fixture.database.rename(fixture.database.with_name("source-unavailable.sqlite"))
        fixture.history.rename(fixture.history.with_name("history-unavailable.jsonl"))
        for name in (snapshot_name, snapshot_name + ".meta", "encrypted-key-enrollment.json", "snapshot-deletion-history.jsonl"):
            path = case.source / name
            path.rename(path.with_name(name + ".fixture-unavailable"))
        fixture.keys = None
        extracted = case.unpack(receipt)
        self.assertFalse(extracted["activated"])
        package = json.loads((case.output / "encrypted-key-enrollment.json").read_text())
        keys = unprotect_runtime_keys(package["runtime_envelope"], store_id=fixture.store_id,
                                      environment_id=fixture.environment)
        restored = restore_checkpointed_candidate(case.output / "snapshot.sqlite", case.output / "restored.sqlite",
            None, fixture.authority, **keys, store_id=fixture.store_id, environment=fixture.environment,
            review_ref="synthetic-project-archive-readback")
        self.addCleanup(restored.close)
        stat = restored.path.stat()
        recovered = ProjectEventsCandidate(restored, EventBinding(str(restored.path.resolve()), stat.st_dev,
            stat.st_ino, fixture.store_id, fixture.environment, "fixture:source"))
        for old, event_id in ((first, "event-1"), (second, "event-2")):
            found = recovered.lookup(token, project_id="project-A", event_id=event_id)
            self.assertEqual(found["receiptId"], old["receiptId"])
            self.assertEqual(found["recordState"], "purged")
        with self.assertRaises(EventError): recovered.submit(token, event(3))
        self.assertEqual(restored.search(fixture.token, "Synthetic"), [])
        self.assertEqual(len(restored.search(fixture.token, "banana")), 1)
        self.assertEqual(restored.db.execute("SELECT count(*) FROM project_sync_events").fetchone()[0], 2)
        result = {"archive":str(case.destination), "archiveSha256":receipt["archiveSha256"],
                  "syntheticOnly":True,"activated":False,"sourceAndHistoryUnavailable":True,
                  "integrityKeysRecoveredFromArchive":True,"receiptIdsPreserved":True,
                  "laterDeletionStillAbsent":True,"independentCurrentAuthorityRetained":True,
                  "credentialRecoveryQualified":False,"retainedSyntheticServiceTokenUsed":True}
        proof = Path(__file__).resolve().parents[2] / "data/project-sync-encrypted-recovery-result-20261115.json"
        proof.write_text(json.dumps(result, indent=2) + "\n")
        print("PROJECT_SYNC_ENCRYPTED_RECOVERY_PROOF=" + str(proof), flush=True)


if __name__ == "__main__":
    unittest.main()
