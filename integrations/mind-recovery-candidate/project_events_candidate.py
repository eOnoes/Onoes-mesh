"""Disconnected Mind-owned project-event candidate; no CLI or startup hooks.

The caller supplies an already opened ledger and separately reviewed binding.
Schema creation, project registration and service enrollment are explicit owner
operations. Import/construction never provision access. Not live-qualified.
"""
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
import secrets
import threading
import uuid

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
        self.lock = threading.RLock()
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

    def initialize(self):
        """Explicit candidate migration, never called by submit/lookup/startup."""
        statements = [
            "CREATE TABLE project_sync_projects(project_id TEXT PRIMARY KEY,label TEXT NOT NULL,deleted INTEGER NOT NULL DEFAULT 0 CHECK(deleted IN (0,1)))",
            "CREATE TABLE project_sync_credentials(principal_id TEXT PRIMARY KEY REFERENCES principals(principal_id),salt TEXT NOT NULL,verifier TEXT NOT NULL,epoch INTEGER NOT NULL)",
            "CREATE TABLE project_sync_grants(principal_id TEXT NOT NULL REFERENCES principals(principal_id),project_id TEXT NOT NULL REFERENCES project_sync_projects(project_id),active INTEGER NOT NULL CHECK(active IN (0,1)),PRIMARY KEY(principal_id,project_id))",
            "CREATE TABLE project_sync_streams(card_id TEXT PRIMARY KEY,project_id TEXT NOT NULL REFERENCES project_sync_projects(project_id),sequence INTEGER NOT NULL,revisions TEXT NOT NULL)",
            "CREATE TABLE project_sync_events(event_id TEXT PRIMARY KEY,card_id TEXT NOT NULL REFERENCES project_sync_streams(card_id),project_id TEXT NOT NULL,payload_hash TEXT NOT NULL,sequence INTEGER NOT NULL,record_id TEXT NOT NULL REFERENCES memory_records(record_id),receipt_id TEXT NOT NULL REFERENCES receipts(receipt_id),UNIQUE(card_id,sequence))",
        ]
        with self.lock, self.ledger._transaction(immediate=True):
            self._binding()
            for statement in statements:
                self.db.execute(statement)

    def register_project(self, project_id, label):
        """Owner setup only; not an operation available to the service token."""
        require(identifier(project_id) and text(label, 160) and label.strip(),
                "Invalid project registration.")
        with self.lock, self.ledger._transaction(immediate=True):
            self._binding()
            self.db.execute("INSERT INTO project_sync_projects(project_id,label) VALUES(?,?)",
                            (project_id, label))

    def enroll(self, project_ids):
        """Explicit one-time candidate enrollment, not ordinary writer access."""
        require(type(project_ids) is list and 1 <= len(project_ids) <= 8
                and len(set(project_ids)) == len(project_ids)
                and all(identifier(p) for p in project_ids), "Explicit projects required.")
        token = secrets.token_urlsafe(32)
        salt, verifier = _hash_password(token)
        with self.lock, self.ledger._transaction(immediate=True):
            self._binding()
            for project in project_ids:
                require(self.db.execute("SELECT 1 FROM project_sync_projects WHERE project_id=? AND deleted=0",
                                        (project,)).fetchone(), "Unknown project.")
            self.db.execute("INSERT INTO principals(principal_id,kind) VALUES(?, 'service')", (PRINCIPAL,))
            epoch = self.db.execute("SELECT credential_epoch FROM principals WHERE principal_id=?", (PRINCIPAL,)).fetchone()[0]
            self.db.execute("INSERT INTO project_sync_credentials VALUES(?,?,?,?)", (PRINCIPAL, salt, verifier, epoch))
            self.db.executemany("INSERT INTO project_sync_grants VALUES(?,?,1)", [(PRINCIPAL, p) for p in project_ids])
        return token

    def _authorize(self, token, project):
        self._binding()
        row = self.db.execute("SELECT c.salt,c.verifier,c.epoch,p.credential_epoch,p.kind FROM project_sync_credentials c JOIN principals p USING(principal_id) WHERE c.principal_id=?", (PRINCIPAL,)).fetchone()
        require(isinstance(token, str) and len(token) <= 256 and row is not None
                and row[2] == row[3] and row[4] == "service"
                and _verify_password(token, row[0], row[1]), "Unauthorized project sync.")
        require(not self.db.execute("SELECT 1 FROM credentials WHERE principal_id=?", (PRINCIPAL,)).fetchone(),
                "Ordinary credential collision.")
        require(self.db.execute("SELECT 1 FROM project_sync_grants WHERE principal_id=? AND project_id=? AND active=1",
                                (PRINCIPAL, project)).fetchone(), "Project not permitted.")

    def _receipt(self, row):
        memory = self.db.execute("SELECT state,scope_id,project_id,principal_id FROM memory_records WHERE record_id=?", (row["record_id"],)).fetchone()
        receipt = self.db.execute("SELECT event_id,principal_id,status,record_id,payload_hash FROM receipts WHERE receipt_id=?", (row["receipt_id"],)).fetchone()
        require(memory is not None and tuple(memory)[1:] == (SCOPE, row["project_id"], PRINCIPAL)
                and receipt is not None and tuple(receipt) == (
                    row["event_id"], PRINCIPAL, "accepted", row["record_id"], row["payload_hash"]),
                "Canonical receipt binding mismatch.")
        state = memory[0]
        deleted = self.db.execute("SELECT deleted FROM project_sync_projects WHERE project_id=?", (row["project_id"],)).fetchone()[0]
        return {"schema": RECEIPT_SCHEMA, "storeId": self.binding.store_id,
                "scope": SCOPE, "principal": PRINCIPAL, "eventId": row["event_id"],
                "cardId": row["card_id"], "projectId": row["project_id"],
                "sequence": row["sequence"], "payloadHash": row["payload_hash"],
                "receiptId": row["receipt_id"], "durable": True,
                "recordState": "project_deleted" if deleted else state}

    def lookup(self, token, *, project_id, event_id):
        require(identifier(project_id) and identifier(event_id), "Invalid receipt identity.")
        with self.lock, self.ledger._transaction():
            self._authorize(token, project_id)
            row = self.db.execute("SELECT * FROM project_sync_events WHERE event_id=? AND project_id=?",
                                  (event_id, project_id)).fetchone()
            return self._receipt(row) if row else None

    def submit(self, token, event):
        # Freeze caller input before validation/authentication and any writer wait.
        event = json.loads(canonical(event))
        digest = validate_event(event)
        with self.lock, self.ledger._transaction(immediate=True):
            self._authorize(token, event["projectId"])
            existing = self.db.execute("SELECT * FROM project_sync_events WHERE event_id=?", (event["eventId"],)).fetchone()
            if existing:
                require(existing["payload_hash"] == digest, "Event payload conflict.")
                return self._receipt(existing)
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
                self.db.execute("UPDATE memory_records SET state='superseded' WHERE record_id=?", (old,))
                self.db.execute("DELETE FROM memory_fts WHERE record_id=?", (old,))
                self.db.execute("UPDATE project_sync_streams SET sequence=?,revisions=? WHERE card_id=?", (event["sequence"], canonical(event["revisions"]), event["cardId"]))
            else:
                require(event["sequence"] == 1 and event["kind"] == "created", "Initial linked snapshot required.")
                self.db.execute("INSERT INTO project_sync_streams VALUES(?,?,?,?)", (event["cardId"], event["projectId"], 1, canonical(event["revisions"])))
            record, receipt = "rec_" + uuid.uuid4().hex, "rcpt_" + uuid.uuid4().hex
            claim = canonical({"source": "workroom", "cardId": event["cardId"], **event["snapshot"]})
            memory_hash = _payload_hash(claim, "project_fact", event["projectId"])
            self.db.execute("INSERT INTO memory_records(record_id,scope_id,kind,project_id,payload_hash,state,principal_id) VALUES(?,?, 'project_fact',?,?, 'active',?)", (record, SCOPE, event["projectId"], memory_hash, PRINCIPAL))
            self.db.execute("INSERT INTO memory_revisions(record_id,claim,is_current,source_class,observed_at) VALUES(?,?,1,'workroom',?)", (record, claim, _now()))
            revision = self.db.execute("SELECT revision_id FROM memory_revisions WHERE record_id=? AND is_current=1", (record,)).fetchone()[0]
            for ref in event["evidence"]:
                self.db.execute("INSERT INTO provenance_refs(record_id,revision_id,evidence_type,locator,content_hash) VALUES(?,?,?,?,?)", (record, revision, ref["type"], ref["ref"], ref["content_hash"]))
            self.db.execute("INSERT INTO memory_fts(record_id,claim) VALUES(?,?)", (record, claim))
            self.db.execute("INSERT INTO submission_events(principal_id,event_id,status,payload_hash,record_id) VALUES(?,?,'accepted',?,?)", (PRINCIPAL, event["eventId"], digest, record))
            self.db.execute("INSERT INTO receipts(receipt_id,event_id,principal_id,status,record_id,payload_hash) VALUES(?,?,?,'accepted',?,?)", (receipt, event["eventId"], PRINCIPAL, record, digest))
            self.db.execute("INSERT INTO project_sync_events VALUES(?,?,?,?,?,?,?)", (event["eventId"], event["cardId"], event["projectId"], digest, event["sequence"], record, receipt))
            self.ledger._audit("project_event_accepted", PRINCIPAL, event["eventId"])
            row = self.db.execute("SELECT * FROM project_sync_events WHERE event_id=?", (event["eventId"],)).fetchone()
            return self._receipt(row)
