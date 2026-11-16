"""Real canonical SQLite fixtures only; no live database or service contact."""
from dataclasses import replace
import copy
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest

from onoes_mind.ledger import Ledger, LedgerError
from onoes_mind.recall_binding import (
    prepare_store_identity, prepare_mesh_principal, issue_mesh_recall_credential,
    RecallBinding, BoundRecallLedger,
)
from project_events_candidate import (
    ProjectEventsCandidate, EventBinding, EventError, PRINCIPAL, SCHEMA, SCOPE,
)


def event(sequence=1, **overrides):
    value = {
        "schema": SCHEMA, "eventId": "event-" + str(sequence),
        "projectId": "project-A", "cardId": "card-A", "sequence": sequence,
        "kind": "created" if sequence == 1 else "stage_changed",
        "revisions": {"task": 1, "brief": sequence, "progress": 0},
        "snapshot": {"title": "Synthetic guide", "goal": "Write a short guide",
                     "stage": "backlog" if sequence == 1 else "working",
                     "owner": "nims", "result": "", "blocker": ""},
        "evidence": [{"type": "repository", "ref": "GUIDE.md", "content_hash": "sha256:abc"}],
    }
    value.update(overrides)
    return value


class ProjectEventsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name).resolve() / "synthetic.sqlite"
        self.ledger = Ledger(self.path, environment_id="synthetic")
        self.addCleanup(lambda: self.ledger.close())
        store_id = prepare_store_identity(self.ledger, environment="synthetic",
                                          authority_ref="synthetic-owner")
        stat = self.path.stat()
        self.binding = EventBinding(str(self.path.resolve()), stat.st_dev, stat.st_ino,
                                    store_id, "synthetic", "synthetic-owner")
        self.writer = ProjectEventsCandidate(self.ledger, self.binding)
        self.writer.initialize()
        self.writer.register_project("project-A", "Synthetic project")
        self.writer.register_project("project-B", "Another project")
        self.token = self.writer.enroll(["project-A"])

    def tearDown(self):
        self.ledger.close()
        self.temp.cleanup()

    def count(self, table):
        return self.ledger.db.execute("SELECT COUNT(*) FROM " + table).fetchone()[0]

    def test_canonical_records_provenance_and_exact_receipt_survive_reopen(self):
        receipt = self.writer.submit(self.token, event())
        self.assertTrue(receipt["durable"])
        self.assertEqual(receipt["recordState"], "active")
        self.assertEqual(self.count("provenance_refs"), 1)
        self.assertTrue(self.ledger.verify_audit_chain())
        self.ledger.close()
        self.ledger = Ledger(self.path, environment_id="synthetic")
        self.writer = ProjectEventsCandidate(self.ledger, self.binding)
        self.assertEqual(receipt, self.writer.lookup(self.token, project_id="project-A", event_id="event-1"))

    def test_replay_and_every_semantic_change_conflict_without_extra_memory(self):
        original = event()
        receipt = self.writer.submit(self.token, original)
        self.assertEqual(receipt, self.writer.submit(self.token, original))
        for key in ("kind", "revisions", "snapshot", "evidence"):
            changed = copy.deepcopy(original)
            if key == "kind": changed[key] = "progress"
            elif key == "revisions": changed[key]["progress"] = 1
            elif key == "snapshot": changed[key]["goal"] = "Changed goal"
            else: changed[key][0]["content_hash"] = "sha256:def"
            with self.subTest(key=key), self.assertRaises(EventError):
                self.writer.submit(self.token, changed)
        self.assertEqual(self.count("memory_records"), 1)
        self.assertEqual(self.count("receipts"), 1)

    def test_correction_supersedes_previous_record_and_preserves_history(self):
        self.writer.submit(self.token, event())
        self.writer.submit(self.token, event(2))
        states = [r[0] for r in self.ledger.db.execute("SELECT state FROM memory_records ORDER BY rowid")]
        self.assertEqual(states, ["active"])
        revisions = self.ledger.db.execute("SELECT is_current FROM memory_revisions ORDER BY revision_id").fetchall()
        self.assertEqual([r[0] for r in revisions], [0, 1])
        self.assertEqual(self.count("memory_fts"), 1)
        self.assertEqual(self.writer.lookup(self.token, project_id="project-A", event_id="event-1")["recordState"], "superseded")
        self.assertEqual(self.count("receipts"), 2)

    def test_wrong_project_out_of_order_and_stale_revisions_are_rejected(self):
        for invalid in (event(2), event(projectId="project-B")):
            with self.assertRaises(EventError): self.writer.submit(self.token, invalid)
        self.writer.submit(self.token, event())
        stale = event(2, revisions={"task": 1, "brief": 1, "progress": 0})
        with self.assertRaises(EventError): self.writer.submit(self.token, stale)
        with self.assertRaises(EventError): self.writer.submit(self.token, event(3))
        self.assertEqual(self.count("project_sync_events"), 1)

    def test_purpose_credential_cannot_use_ordinary_writer_and_operator_cannot_use_service(self):
        with self.assertRaises(LedgerError): self.ledger.authenticate(self.token)
        with self.assertRaises(LedgerError): self.ledger.remember(self.token, {})
        self.ledger.create_principal("operator")
        operator = self.ledger.issue_credential("operator")
        with self.assertRaises(EventError): self.writer.submit(operator, event())
        self.assertEqual(self.count("memory_records"), 0)

    def test_revocation_and_changed_store_identity_fail_on_next_operation(self):
        self.writer.submit(self.token, event())
        self.ledger.rotate_credentials(PRINCIPAL)
        with self.assertRaises(EventError): self.writer.lookup(self.token, project_id="project-A", event_id="event-1")
        with self.assertRaises(EventError): self.writer.submit(self.token, event(2))
        with self.assertRaises(EventError): ProjectEventsCandidate(self.ledger, replace(self.binding, store_id="wrong"))
        self.ledger.db.execute("UPDATE recall_store_identity SET authority_ref='changed'")
        with self.assertRaises(EventError): self.writer.submit(self.token, event(2))

    def test_canonical_purge_blocks_resurrection_even_with_fresh_event_id(self):
        first = self.writer.submit(self.token, event())
        record = self.ledger.db.execute("SELECT record_id FROM project_sync_events").fetchone()[0]
        self.ledger.create_principal("operator")
        operator = self.ledger.issue_credential("operator")
        self.ledger.purge(operator, record, "PURGE:" + record)
        replay = self.writer.submit(self.token, event())
        self.assertEqual(replay["receiptId"], first["receiptId"])
        self.assertEqual(replay["recordState"], "purged")
        with self.assertRaises(EventError): self.writer.submit(self.token, event(2))
        self.assertEqual(self.count("memory_records"), 1)

    def test_atomic_rollback_if_receipt_write_fails(self):
        self.ledger.db.execute("CREATE TRIGGER fail_receipt BEFORE INSERT ON receipts BEGIN SELECT RAISE(ABORT,'synthetic failure'); END")
        with self.assertRaises(sqlite3.IntegrityError): self.writer.submit(self.token, event())
        for table in ("memory_records", "memory_revisions", "memory_fts", "project_sync_streams", "project_sync_events", "receipts", "submission_events"):
            self.assertEqual(self.count(table), 0, table)
        self.ledger.db.execute("DROP TRIGGER fail_receipt")
        self.writer.submit(self.token, event())

    def test_deleted_project_lookup_is_explicit_and_new_events_refused(self):
        self.writer.submit(self.token, event())
        self.ledger.db.execute("UPDATE project_sync_projects SET deleted=1 WHERE project_id='project-A'")
        self.assertEqual(self.writer.lookup(self.token, project_id="project-A", event_id="event-1")["recordState"], "project_deleted")
        with self.assertRaises(EventError): self.writer.submit(self.token, event(2))

    def test_unknown_fields_secret_and_bad_revisions_leave_no_bound_event(self):
        for invalid in (event(scope="agent/echo/private"), event(sequence=True),
                        event(revisions={"task": True, "brief": 1, "progress": 0})):
            with self.assertRaises(EventError): self.writer.submit(self.token, invalid)
        self.assertEqual(self.count("submission_events"), 0)

    def test_concurrent_connections_bind_same_event_once(self):
        other = Ledger(self.path, environment_id="synthetic")
        second = ProjectEventsCandidate(other, self.binding)
        barrier = threading.Barrier(2)
        outcomes, failures = [], []
        def run(writer):
            try:
                barrier.wait(timeout=5)
                outcomes.append(writer.submit(self.token, event()))
            except Exception as exc:
                failures.append(type(exc).__name__)
        threads = [threading.Thread(target=run, args=(w,)) for w in (self.writer, second)]
        try:
            for thread in threads: thread.start()
            for thread in threads: thread.join(timeout=10)
            self.assertTrue(all(not t.is_alive() for t in threads))
            self.assertEqual(failures, [])
            self.assertEqual(len(outcomes), 2)
            self.assertEqual(outcomes[0], outcomes[1])
            self.assertEqual(self.count("memory_records"), 1)
        finally:
            other.close()

    def test_canonical_receipt_corruption_and_ordinary_credential_collision_are_refused(self):
        receipt = self.writer.submit(self.token, event())
        self.ledger.db.execute("UPDATE receipts SET payload_hash='changed' WHERE receipt_id=?", (receipt["receiptId"],))
        with self.assertRaises(EventError): self.writer.lookup(self.token, project_id="project-A", event_id="event-1")
        self.ledger.issue_credential(PRINCIPAL)
        with self.assertRaises(EventError): self.writer.submit(self.token, event(2))

    def test_secret_content_does_not_bind_or_persist_any_event(self):
        value = event()
        value["snapshot"]["goal"] = "api_key=sk-" + "a" * 48
        with self.assertRaises(EventError): self.writer.submit(self.token, value)
        self.assertEqual(self.count("project_sync_events"), 0)
        self.assertEqual(self.count("memory_records"), 0)

    def test_existing_bound_reader_sees_only_latest_snapshot_and_current_provenance(self):
        prepare_mesh_principal(self.ledger, scope_id=SCOPE)
        token = issue_mesh_recall_credential(self.ledger)
        b = self.binding
        binding = RecallBinding(database_path=b.database_path, store_id=b.store_id,
            environment=b.environment, authority_ref=b.authority_ref, scope_id=SCOPE,
            file_device=b.file_device, file_inode=b.file_inode,
            credential_custodian_ref="synthetic-custodian", revocation_ref="synthetic-revoke",
            review_ref="synthetic-review")
        reader = BoundRecallLedger(self.path, binding=binding)
        try:
            self.writer.submit(self.token, event())
            original = reader.search(token, "Synthetic")
            self.assertEqual(len(original), 1)
            corrected = event(2)
            corrected["snapshot"]["goal"] = "Corrected synthetic goal"
            corrected["evidence"][0]["content_hash"] = "sha256:corrected"
            self.writer.submit(self.token, corrected)
            found = reader.search(token, "Synthetic")
            self.assertEqual(len(found), 1)
            self.assertEqual(found[0]["record_id"], original[0]["record_id"])
            self.assertIn("Corrected synthetic goal", found[0]["claim"])
            self.assertEqual(found[0]["provenance"][0]["content_hash"], "sha256:corrected")
        finally:
            reader.close()


if __name__ == "__main__":
    unittest.main()
