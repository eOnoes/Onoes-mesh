"""Disconnected Mind-owned project-event candidate; no CLI or startup hooks.

The caller supplies an already opened ledger and separately reviewed binding.
Schema creation, project registration and service enrollment are explicit owner
operations. Import/construction never provision access. Not live-qualified.
"""
from dataclasses import dataclass
from contextlib import contextmanager, ExitStack
import hashlib
import json
from pathlib import Path
import re
import secrets
import threading
import uuid
import sqlite3
from checkpoint_candidate import history_view

from onoes_mind.ledger import (
    _hash_password, _verify_password, _secret_category,
    _payload_hash, _now,
)

PRINCIPAL = "mesh-project-sync"
SCOPE = "project/onoes-mind/shared"
SCHEMA = "onoes-mind-project-event/v1"
RECEIPT_SCHEMA = "onoes-mind-project-receipt/v1"
MAX_INTEGER = 9007199254740991


class EventError(ValueError):
    """Stable errors never echo submitted facts or credentials."""


def require(condition, message):
    if not condition:
        raise EventError(message)


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"), allow_nan=False)


def event_hash(event):
    return hashlib.sha256(canonical(event).encode("utf-8")).hexdigest()


def identifier(value):
    return isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,100}", value)


def text(value, limit):
    return (isinstance(value, str) and len(value) <= limit and "\0" not in value
            and not any(0xD800 <= ord(c) <= 0xDFFF for c in value))


def validate_event(event):
    require(type(event) is dict and set(event) == {
        "schema", "eventId", "projectId", "cardId", "sequence", "kind",
        "revisions", "snapshot", "evidence",
    }, "Invalid project event fields.")
    require(event["schema"] == SCHEMA, "Unsupported project event schema.")
    require(all(identifier(event[k]) for k in ("eventId", "projectId", "cardId")),
            "Invalid project event identity.")
    require(type(event["sequence"]) is int and 1 <= event["sequence"] <= MAX_INTEGER,
            "Invalid event sequence.")
    require(event["kind"] in {"created", "assigned", "stage_changed", "progress",
                              "blocked", "completed"}, "Invalid event kind.")
    revisions = event["revisions"]
    require(type(revisions) is dict and set(revisions) == {"task", "brief", "progress"}
            and all(type(v) is int and 0 <= v <= MAX_INTEGER for v in revisions.values())
            and revisions["task"] > 0, "Invalid source revisions.")
    snapshot = event["snapshot"]
    limits = {"title": 300, "goal": 2000, "owner": 100, "stage": 20,
              "result": 4000, "blocker": 1000}
    require(type(snapshot) is dict and set(snapshot) == set(limits)
            and all(text(snapshot[k], n) for k, n in limits.items())
            and snapshot["title"].strip()
            and snapshot["stage"] in {"backlog", "ready", "working", "needs_you", "done"},
            "Invalid shared snapshot.")
    require(event["kind"] != "completed" or snapshot["stage"] == "done",
            "Completion must describe the Done stage.")
    evidence = event["evidence"]
    require(type(evidence) is list and len(evidence) <= 12, "Invalid evidence.")
    for ref in evidence:
        require(type(ref) is dict and set(ref) == {"type", "ref", "content_hash"}
                and all(text(ref[k], n) and ref[k].strip() for k, n in
                        (("type", 50), ("ref", 500), ("content_hash", 100))),
                "Invalid evidence reference.")
    require(len(canonical(event).encode("utf-8")) <= 16384, "Project event too large.")
    require(_secret_category(event) is None, "Secret-like content refused.")
    return event_hash(event)


@dataclass(frozen=True)
class EventBinding:
    database_path: str
    file_device: int
    file_inode: int
    store_id: str
    environment: str
    authority_ref: str


class ProjectEventsCandidate:
    def __init__(self, ledger, binding):
        self.ledger, self.db, self.binding = ledger, ledger.db, binding
        self.lock = getattr(ledger, "_checkpoint_lock", threading.RLock())
        self._binding()

    def _binding(self):
        b = self.binding
        require(type(b) is EventBinding and self.ledger.path is not None,
                "An explicit existing-store binding is required.")
        path = Path(b.database_path)
        require(path.is_absolute() and path.resolve() == self.ledger.path.resolve(),
                "Store path mismatch.")
        stat = path.stat()
        require((stat.st_dev, stat.st_ino) == (b.file_device, b.file_inode),
                "Store file identity mismatch.")
        rows = self.db.execute("SELECT store_id,environment,authority_ref FROM recall_store_identity").fetchall()
        require([tuple(r) for r in rows] == [(b.store_id, b.environment, b.authority_ref)],
                "Store authority mismatch.")

    @contextmanager
    def _history_guard(self):
        # Same lock order as managed purge: authority, then the canonical DB.
        stack = ExitStack()
        try:
            authority = getattr(self.ledger, "_checkpoint_authority", None)
            lease = stack.enter_context(authority.hold(self.binding.store_id, self.binding.environment)) if authority else None
            before, lines = history_view(self.ledger, self.ledger.deletion_ledger_path,
                                         self.binding.store_id, self.binding.environment)
            if lease:
                lease.assert_current(before)
        except Exception:
            stack.close()
            raise EventError("Deletion authority unavailable.") from None
        with stack:
            yield lines
            try:
                after, _ = history_view(self.ledger, self.ledger.deletion_ledger_path,
                                        self.binding.store_id, self.binding.environment)
                require(after == before, "Deletion authority unavailable.")
                if lease:
                    lease.assert_current(after)
            except Exception:
                raise EventError("Deletion authority unavailable.") from None

    def _format(self):
        try:
            versions = self.db.execute("SELECT version FROM project_sync_format").fetchall()
        except sqlite3.Error:
            raise EventError("Project-event format unavailable.") from None
        require([tuple(v) for v in versions] == [(2,)], "Project-event format unavailable.")

    def _record_id(self, card_id):
        # A stable card anchor survives lost event/stream rows in an older backup.
        # Project/event IDs cannot be changed to evade a retained deletion.
        value = "mesh-project-card/v2\0" + self.binding.store_id + "\0" + card_id
        return "rec_mesh_" + hashlib.sha256(value.encode()).hexdigest()

    @staticmethod
    def _deleted(record_id, lines):
        fingerprint = hashlib.sha256(record_id.encode()).hexdigest()
        return any(json.loads(line)["record_fingerprint"] == fingerprint for line in lines[1:])

    def initialize(self):
        """Explicit candidate migration, never called by submit/lookup/startup."""
        statements = [
            "CREATE TABLE project_sync_format(singleton INTEGER PRIMARY KEY CHECK(singleton=1),version INTEGER NOT NULL CHECK(version=2))",
            "INSERT INTO project_sync_format VALUES(1,2)",
            "CREATE TABLE project_sync_admin_operations(operation_id TEXT PRIMARY KEY,request_hash TEXT NOT NULL,mode TEXT NOT NULL,state TEXT NOT NULL CHECK(state IN ('reserved','complete','unknown')))",
            "CREATE TABLE project_sync_projects(project_id TEXT PRIMARY KEY,label TEXT NOT NULL,deleted INTEGER NOT NULL DEFAULT 0 CHECK(deleted IN (0,1)))",
            "CREATE TABLE project_sync_credentials(principal_id TEXT PRIMARY KEY REFERENCES principals(principal_id),salt TEXT NOT NULL,verifier TEXT NOT NULL,epoch INTEGER NOT NULL)",
            "CREATE TABLE project_sync_grants(principal_id TEXT NOT NULL REFERENCES principals(principal_id),project_id TEXT NOT NULL REFERENCES project_sync_projects(project_id),active INTEGER NOT NULL CHECK(active IN (0,1)),PRIMARY KEY(principal_id,project_id))",
            "CREATE TABLE project_sync_streams(card_id TEXT PRIMARY KEY,project_id TEXT NOT NULL REFERENCES project_sync_projects(project_id),sequence INTEGER NOT NULL,revisions TEXT NOT NULL)",
            "CREATE TABLE project_sync_events(event_id TEXT PRIMARY KEY,card_id TEXT NOT NULL REFERENCES project_sync_streams(card_id),project_id TEXT NOT NULL,payload_hash TEXT NOT NULL,sequence INTEGER NOT NULL,record_id TEXT NOT NULL REFERENCES memory_records(record_id),receipt_id TEXT NOT NULL REFERENCES receipts(receipt_id),revision_id INTEGER NOT NULL REFERENCES memory_revisions(revision_id),UNIQUE(card_id,sequence))",
        ]
        with self.lock, self._history_guard(), self.ledger._transaction(immediate=True):
            self._binding()
            for statement in statements:
                self.db.execute(statement)

    def register_project(self, project_id, label):
        """Owner setup only; not an operation available to the service token."""
        require(identifier(project_id) and text(label, 160) and label.strip(),
                "Invalid project registration.")
        with self.lock, self._history_guard(), self.ledger._transaction(immediate=True):
            self._binding()
            self._format()
            self.db.execute("INSERT INTO project_sync_projects(project_id,label) VALUES(?,?)",
                            (project_id, label))

    def enroll(self, project_ids):
        """Explicit one-time candidate enrollment, not ordinary writer access."""
        require(type(project_ids) is list and 1 <= len(project_ids) <= 8
                and len(set(project_ids)) == len(project_ids)
                and all(identifier(p) for p in project_ids), "Explicit projects required.")
        token = secrets.token_urlsafe(32)
        salt, verifier = _hash_password(token)
        with self.lock, self._history_guard(), self.ledger._transaction(immediate=True):
            self._binding()
            self._format()
            for project in project_ids:
                require(self.db.execute("SELECT 1 FROM project_sync_projects WHERE project_id=? AND deleted=0",
                                        (project,)).fetchone(), "Unknown project.")
            self.db.execute("INSERT INTO principals(principal_id,kind) VALUES(?, 'service')", (PRINCIPAL,))
            epoch = self.db.execute("SELECT credential_epoch FROM principals WHERE principal_id=?", (PRINCIPAL,)).fetchone()[0]
            self.db.execute("INSERT INTO project_sync_credentials VALUES(?,?,?,?)", (PRINCIPAL, salt, verifier, epoch))
            self.db.executemany("INSERT INTO project_sync_grants VALUES(?,?,1)", [(PRINCIPAL, p) for p in project_ids])
        return token

    def replace_credential(self, project_ids, operation_id):
        """Privileged owner recovery only; never exposed by the event HTTP API."""
        require(type(project_ids) is tuple and 1 <= len(project_ids) <= 8
                and all(identifier(p) for p in project_ids)
                and tuple(sorted(set(project_ids))) == project_ids and identifier(operation_id),
                "Explicit reviewed replacement required.")
        token = secrets.token_urlsafe(32)
        salt, verifier = _hash_password(token)
        with self.lock, self._history_guard(), self.ledger._transaction(immediate=True):
            self._binding(); self._format()
            row = self.db.execute("SELECT p.kind,p.credential_epoch,c.epoch FROM principals p JOIN project_sync_credentials c USING(principal_id) WHERE p.principal_id=?", (PRINCIPAL,)).fetchone()
            require(row is not None and row[0] == 'service' and row[1] >= row[2],
                    "Existing purpose service required.")
            require(not self.db.execute("SELECT 1 FROM credentials WHERE principal_id=?", (PRINCIPAL,)).fetchone()
                    and not self.db.execute("SELECT 1 FROM scope_grants WHERE principal_id=?", (PRINCIPAL,)).fetchone(),
                    "Ordinary credential collision.")
            if self.db.execute("SELECT 1 FROM sqlite_schema WHERE name='recall_service_credentials'").fetchone():
                require(not self.db.execute("SELECT 1 FROM recall_service_credentials WHERE principal_id=?", (PRINCIPAL,)).fetchone(),
                        "Ordinary credential collision.")
            active = tuple(r[0] for r in self.db.execute("SELECT project_id FROM project_sync_grants WHERE principal_id=? AND active=1 ORDER BY project_id", (PRINCIPAL,)))
            require(active == project_ids, "Explicit reviewed projects differ from existing grants.")
            for project in project_ids:
                require(self.db.execute("SELECT 1 FROM project_sync_projects WHERE project_id=? AND deleted=0", (project,)).fetchone(), "Project is deleted.")
            operation = self.db.execute("SELECT mode,state FROM project_sync_admin_operations WHERE operation_id=?", (operation_id,)).fetchone()
            require(operation is not None and tuple(operation) == ('replace', 'reserved'),
                    "Reserved owner operation required.")
            self.ledger.rotate_credentials(PRINCIPAL)
            epoch = self.db.execute("SELECT credential_epoch FROM principals WHERE principal_id=?", (PRINCIPAL,)).fetchone()[0]
            self.db.execute("UPDATE project_sync_credentials SET salt=?,verifier=?,epoch=? WHERE principal_id=?", (salt, verifier, epoch, PRINCIPAL))
            self.db.execute("UPDATE project_sync_admin_operations SET state='unknown' WHERE operation_id=?", (operation_id,))
            self.ledger._audit('project_service_credential_replaced', PRINCIPAL, operation_id)
        return token

    def _authorize(self, token, project):
        self._binding()
        self._format()
        row = self.db.execute("SELECT c.salt,c.verifier,c.epoch,p.credential_epoch,p.kind FROM project_sync_credentials c JOIN principals p USING(principal_id) WHERE c.principal_id=?", (PRINCIPAL,)).fetchone()
        require(isinstance(token, str) and len(token) <= 256 and row is not None
                and row[2] == row[3] and row[4] == "service"
                and _verify_password(token, row[0], row[1]), "Unauthorized project sync.")
        require(not self.db.execute("SELECT 1 FROM credentials WHERE principal_id=?", (PRINCIPAL,)).fetchone(),
                "Ordinary credential collision.")
        require(self.db.execute("SELECT 1 FROM project_sync_grants WHERE principal_id=? AND project_id=? AND active=1",
                                (PRINCIPAL, project)).fetchone(), "Project not permitted.")

    def _receipt(self, row, history):
        memory = self.db.execute("SELECT state,scope_id,project_id,principal_id FROM memory_records WHERE record_id=?", (row["record_id"],)).fetchone()
        receipt = self.db.execute("SELECT event_id,principal_id,status,record_id,payload_hash FROM receipts WHERE receipt_id=?", (row["receipt_id"],)).fetchone()
        revision = self.db.execute("SELECT record_id,is_current FROM memory_revisions WHERE revision_id=?", (row["revision_id"],)).fetchone()
        require(memory is not None and tuple(memory)[1:] == (SCOPE, row["project_id"], PRINCIPAL)
                and row["record_id"] == self._record_id(row["card_id"])
                and revision is not None and revision[0] == row["record_id"]
                and receipt is not None and tuple(receipt) == (
                    row["event_id"], PRINCIPAL, "accepted", row["record_id"], row["payload_hash"]),
                "Canonical receipt binding mismatch.")
        state = memory[0]
        if self._deleted(row["record_id"], history):
            state = "purged"
        elif state in {"active", "promoted"} and not revision[1]:
            state = "superseded"
        deleted = self.db.execute("SELECT deleted FROM project_sync_projects WHERE project_id=?", (row["project_id"],)).fetchone()[0]
        return {"schema": RECEIPT_SCHEMA, "storeId": self.binding.store_id,
                "scope": SCOPE, "principal": PRINCIPAL, "eventId": row["event_id"],
                "cardId": row["card_id"], "projectId": row["project_id"],
                "sequence": row["sequence"], "payloadHash": row["payload_hash"],
                "receiptId": row["receipt_id"], "durable": True,
                "recordState": "project_deleted" if deleted else state}

    def lookup(self, token, *, project_id, event_id):
        require(identifier(project_id) and identifier(event_id), "Invalid receipt identity.")
        with self.lock, self._history_guard() as history, self.ledger._transaction():
            self._authorize(token, project_id)
            row = self.db.execute("SELECT * FROM project_sync_events WHERE event_id=? AND project_id=?",
                                  (event_id, project_id)).fetchone()
            return self._receipt(row, history) if row else None

    def submit(self, token, event):
        # Freeze caller input before validation/authentication and any writer wait.
        event = json.loads(canonical(event))
        digest = validate_event(event)
        with self.lock, self._history_guard() as history, self.ledger._transaction(immediate=True):
            self._authorize(token, event["projectId"])
            existing = self.db.execute("SELECT * FROM project_sync_events WHERE event_id=?", (event["eventId"],)).fetchone()
            if existing:
                require(existing["payload_hash"] == digest, "Event payload conflict.")
                return self._receipt(existing, history)
            record = self._record_id(event["cardId"])
            require(not self._deleted(record, history), "Deleted card history blocks replay.")
            require(self.db.execute("SELECT 1 FROM project_sync_projects WHERE project_id=? AND deleted=0", (event["projectId"],)).fetchone(), "Project is deleted.")
            require(self.ledger.shared_mutation_allowed(), "Shared storage unavailable.")
            stream = self.db.execute("SELECT * FROM project_sync_streams WHERE card_id=?", (event["cardId"],)).fetchone()
            if stream:
                require(stream["project_id"] == event["projectId"], "Card project conflict.")
                require(event["sequence"] == stream["sequence"] + 1, "Event sequence conflict.")
                require(event["kind"] != "created", "Card already registered.")
                before = json.loads(stream["revisions"])
                require(all(event["revisions"][k] >= before[k] for k in before)
                        and event["revisions"] != before, "Stale source revisions.")
                require(not self.db.execute("SELECT 1 FROM project_sync_events e JOIN memory_records m ON m.record_id=e.record_id WHERE e.card_id=? AND m.state='purged'", (event["cardId"],)).fetchone(), "Deleted card history blocks replay.")
                old = self.db.execute("SELECT record_id FROM project_sync_events WHERE card_id=? AND sequence=?", (event["cardId"], stream["sequence"])).fetchone()[0]
                prior = self.db.execute("SELECT revision_id FROM project_sync_events WHERE card_id=? AND sequence=?", (event["cardId"], stream["sequence"])).fetchone()[0]
                current = self.db.execute("SELECT revision_id FROM memory_revisions WHERE record_id=? AND is_current=1", (old,)).fetchone()
                require(old == record and current is not None and current[0] == prior, "Card memory changed outside this stream.")
                self.db.execute("UPDATE memory_revisions SET is_current=0 WHERE record_id=? AND is_current=1", (old,))
                self.db.execute("DELETE FROM memory_fts WHERE record_id=?", (old,))
                self.db.execute("UPDATE project_sync_streams SET sequence=?,revisions=? WHERE card_id=?", (event["sequence"], canonical(event["revisions"]), event["cardId"]))
            else:
                require(event["sequence"] == 1 and event["kind"] == "created", "Initial linked snapshot required.")
                self.db.execute("INSERT INTO project_sync_streams VALUES(?,?,?,?)", (event["cardId"], event["projectId"], 1, canonical(event["revisions"])))
            receipt = "rcpt_" + uuid.uuid4().hex
            claim = canonical({"source": "workroom", "cardId": event["cardId"], **event["snapshot"]})
            memory_hash = _payload_hash(claim, "project_fact", event["projectId"])
            if stream:
                self.db.execute("UPDATE memory_records SET payload_hash=?,state='active' WHERE record_id=?", (memory_hash, record))
            else:
                self.db.execute("INSERT INTO memory_records(record_id,scope_id,kind,project_id,payload_hash,state,principal_id) VALUES(?,?, 'project_fact',?,?, 'active',?)", (record, SCOPE, event["projectId"], memory_hash, PRINCIPAL))
            self.db.execute("INSERT INTO memory_revisions(record_id,claim,is_current,source_class,observed_at) VALUES(?,?,1,'workroom',?)", (record, claim, _now()))
            revision = self.db.execute("SELECT revision_id FROM memory_revisions WHERE record_id=? AND is_current=1", (record,)).fetchone()[0]
            for ref in event["evidence"]:
                self.db.execute("INSERT INTO provenance_refs(record_id,revision_id,evidence_type,locator,content_hash) VALUES(?,?,?,?,?)", (record, revision, ref["type"], ref["ref"], ref["content_hash"]))
            self.db.execute("INSERT INTO memory_fts(record_id,claim) VALUES(?,?)", (record, claim))
            self.db.execute("INSERT INTO submission_events(principal_id,event_id,status,payload_hash,record_id) VALUES(?,?,'accepted',?,?)", (PRINCIPAL, event["eventId"], digest, record))
            self.db.execute("INSERT INTO receipts(receipt_id,event_id,principal_id,status,record_id,payload_hash) VALUES(?,?,?,'accepted',?,?)", (receipt, event["eventId"], PRINCIPAL, record, digest))
            self.db.execute("INSERT INTO project_sync_events VALUES(?,?,?,?,?,?,?,?)", (event["eventId"], event["cardId"], event["projectId"], digest, event["sequence"], record, receipt, revision))
            self.ledger._audit("project_event_accepted", PRINCIPAL, event["eventId"])
            row = self.db.execute("SELECT * FROM project_sync_events WHERE event_id=?", (event["eventId"],)).fetchone()
            return self._receipt(row, history)
