"""Inactive local authority candidate. Explicit creation only; no default/live path.

Protects against mismatched copies and interrupted managed operations under an
independently selected, retained current journal. NOT same-login/admin or whole-PC
rollback resistance. No runtime enrollment, service, credentials or ACL changes.
"""
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
import json
import os
import re
import sqlite3
import uuid

from onoes_mind.enrollment_store import qualify_private_storage
from checkpoint_candidate import (Head, SnapshotReceipt, context, history_view,
                                   canonical, require, CheckpointRecoveryError)

SCHEMA = 'onoes-mind-checkpoint-authority-candidate/v1'


def digest(value):
    return isinstance(value, str) and re.fullmatch('[a-f0-9]{64}', value) is not None


def bounded_id(value):
    return isinstance(value, str) and 0 < len(value) <= 128 and '\x00' not in value


@dataclass(frozen=True)
class AuthorityBinding:
    path: str
    device: int
    inode: int
    authority_id: str
    store_id: str
    environment: str


class PersistentAuthorityCandidate:
    def __init__(self, binding):
        require(type(binding) is AuthorityBinding, 'Reviewed authority binding required.')
        context(binding.store_id, binding.environment)
        require(str(uuid.UUID(binding.authority_id)) == binding.authority_id,
                'Canonical authority identity required.')
        self.binding = binding
        self.path = Path(binding.path)
        self._guard_path()
        qualify_private_storage(self.path.parent)
        qualify_private_storage(self.path, kind='file')
        with self._transaction() as db:
            require(db.execute('PRAGMA quick_check').fetchone()[0] == 'ok', 'Authority integrity failed.')
            self._head(db)  # SQLite integrity alone does not prove the required logical head exists.

    @classmethod
    def create(cls, directory, ledger, *, store_id, environment, review_ref):
        """Prepared trusted-operator enrollment; references do not grant permission."""
        require(bounded_id(review_ref), 'Explicit source review reference required.')
        root = qualify_private_storage(directory)
        require(not any(root.iterdir()), 'A new empty private authority directory is required.')
        head, _ = history_view(ledger, ledger.deletion_ledger_path, store_id, environment)
        path = root / 'current-checkpoint.sqlite'
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(descriptor)
        authority_id = str(uuid.uuid4())
        db = sqlite3.connect(path)
        try:
            db.execute('PRAGMA journal_mode=DELETE')
            db.execute('PRAGMA synchronous=FULL')
            db.executescript('CREATE TABLE identity(id INTEGER PRIMARY KEY CHECK(id=1),body TEXT NOT NULL);'
                'CREATE TABLE head(id INTEGER PRIMARY KEY CHECK(id=1),body TEXT NOT NULL,blocked INTEGER NOT NULL CHECK(blocked IN(0,1)));'
                'CREATE TABLE snapshots(dbhash TEXT,metahash TEXT,body TEXT NOT NULL,PRIMARY KEY(dbhash,metahash));'
                "CREATE TABLE purges(id TEXT PRIMARY KEY,hash TEXT NOT NULL,ticket TEXT NOT NULL,prior TEXT NOT NULL,state TEXT NOT NULL CHECK(state IN('pending','completed')),receipt TEXT);")
            with db:
                db.execute('INSERT INTO identity VALUES(1,?)', (canonical(dict(schema=SCHEMA,
                    authority_id=authority_id, store_id=store_id, environment=environment,
                    review_ref=review_ref)).decode(),))
                db.execute('INSERT INTO head VALUES(1,?,0)', (canonical(asdict(head)).decode(),))
        finally:
            db.close()
        info = path.stat()
        return cls(AuthorityBinding(str(path), info.st_dev, info.st_ino,
                                    authority_id, store_id, environment))

    def _guard_path(self):
        require(self.path.is_absolute() and self.path.resolve(strict=True) == self.path
                and self.path.is_file() and not self.path.is_symlink(), 'Canonical authority file required.')
        info = self.path.stat()
        require((info.st_dev, info.st_ino) == (self.binding.device, self.binding.inode),
                'Authority physical file identity changed; do not adopt a copy.')

    def _identity(self, db):
        rows = db.execute('SELECT body FROM identity WHERE id=1').fetchall()
        require(len(rows) == 1, 'Authority identity is missing.')
        record = json.loads(rows[0][0])
        require(record.get('schema') == SCHEMA and record.get('authority_id') == self.binding.authority_id
                and record.get('store_id') == self.binding.store_id
                and record.get('environment') == self.binding.environment, 'Authority identity mismatch.')

    @contextmanager
    def _transaction(self):
        self._guard_path()
        db = sqlite3.connect(self.path.as_uri() + '?mode=rw', uri=True, timeout=0)
        try:
            db.execute('PRAGMA synchronous=FULL')
            db.execute('BEGIN IMMEDIATE')
            self._identity(db)
            yield db
            self._guard_path()
            db.commit()
            self._guard_path()
        finally:
            db.rollback()
            db.close()

    def _head(self, db):
        row = db.execute('SELECT body,blocked FROM head WHERE id=1').fetchone()
        require(row is not None and row[1] in (0, 1), 'Authority head is missing or invalid.')
        head = Head(**json.loads(row[0]))
        self._validate_head(head)
        return head, row[1]

    def _validate_head(self, head):
        require(type(head) is Head and head.store_id == self.binding.store_id
                and head.environment == self.binding.environment and type(head.sequence) is int
                and head.sequence >= 0 and digest(head.history_sha256), 'Checkpoint head is invalid.')

    @contextmanager
    def hold(self, store_id, environment):
        require((store_id, environment) == (self.binding.store_id, self.binding.environment),
                'Requested checkpoint context mismatch.')
        with self._transaction() as db:
            head, blocked = self._head(db)
            require(not blocked, 'Unacknowledged purge blocks recovery; inspect the same intent.')
            lease = AuthorityLease(self, db, head)
            try:
                yield lease
            finally:
                lease.active = False

    def begin_purge(self, operation_id, payload_hash, actual):
        require(bounded_id(operation_id) and digest(payload_hash), 'Bounded purge identity/hash required.')
        self._validate_head(actual)
        with self._transaction() as db:
            old = db.execute('SELECT hash,state,receipt FROM purges WHERE id=?', (operation_id,)).fetchone()
            if old:
                require(old[0] == payload_hash and old[1] == 'completed',
                        'Divergent or uncertain purge remains held.')
                return {'completed':True, 'receipt':json.loads(old[2])}
            head, blocked = self._head(db)
            require(not blocked and head == actual, 'Purge is not at the current acknowledged head.')
            ticket = str(uuid.uuid4())
            db.execute('UPDATE head SET blocked=1 WHERE id=1')
            db.execute("INSERT INTO purges VALUES(?,?,?,?,'pending',NULL)",
                       (operation_id, payload_hash, ticket, canonical(asdict(head)).decode()))
        return {'completed':False, 'ticket':ticket}

    def ack_purge(self, operation_id, payload_hash, ticket, head):
        require(bounded_id(operation_id) and digest(payload_hash) and bounded_id(ticket),
                'Exact purge acknowledgement identity required.')
        self._validate_head(head)
        with self._transaction() as db:
            row = db.execute('SELECT hash,ticket,prior,state,receipt FROM purges WHERE id=?', (operation_id,)).fetchone()
            require(row is not None and (row[0], row[1]) == (payload_hash, ticket), 'Purge ticket mismatch.')
            if row[3] == 'completed':
                receipt = json.loads(row[4])
                require(receipt['sequence'] == head.sequence and receipt['historySha256'] == head.history_sha256,
                        'Completed acknowledgement diverged.')
                return receipt
            prior = Head(**json.loads(row[2]))
            current, blocked = self._head(db)
            require(blocked == 1 and current == prior and head.sequence == prior.sequence + 1
                    and head.history_sha256 != prior.history_sha256, 'Purge head does not follow its durable intent.')
            receipt = dict(operationId=operation_id, checkpointAcknowledged=True,
                           sequence=head.sequence, historySha256=head.history_sha256)
            db.execute('UPDATE head SET body=?,blocked=0 WHERE id=1', (canonical(asdict(head)).decode(),))
            db.execute("UPDATE purges SET state='completed',receipt=? WHERE id=?", (canonical(receipt).decode(),operation_id))
        return receipt


class AuthorityLease:
    def __init__(self, authority, db, head):
        self.authority, self.db, self.head, self.active = authority, db, head, True

    def _check(self):
        require(self.active and self.db.in_transaction, 'Authority lease is no longer held.')
        self.authority._guard_path()
        current, blocked = self.authority._head(self.db)
        require(not blocked and current == self.head, 'Current authority head changed.')

    def current(self):
        self._check()
        return self.head

    def assert_current(self, expected):
        self._check()
        require(expected == self.head, 'Requested authority head mismatch.')

    def register_snapshot(self, receipt):
        self._check()
        require(type(receipt) is SnapshotReceipt and receipt.store_id == self.head.store_id
                and receipt.environment == self.head.environment and receipt.sequence == self.head.sequence
                and receipt.history_prefix_sha256 == self.head.history_sha256
                and digest(receipt.database_sha256) and digest(receipt.metadata_sha256),
                'Snapshot registration does not match current authority.')
        body = canonical(asdict(receipt)).decode()
        old = self.db.execute('SELECT body FROM snapshots WHERE dbhash=? AND metahash=?',
                             (receipt.database_sha256, receipt.metadata_sha256)).fetchone()
        require(not old or old[0] == body, 'Snapshot registration diverged.')
        if not old:
            self.db.execute('INSERT INTO snapshots VALUES(?,?,?)',
                            (receipt.database_sha256, receipt.metadata_sha256, body))

    def snapshot_receipt(self, database_hash, metadata_hash):
        self._check()
        require(digest(database_hash) and digest(metadata_hash), 'Snapshot hashes required.')
        row = self.db.execute('SELECT body FROM snapshots WHERE dbhash=? AND metahash=?',
                              (database_hash, metadata_hash)).fetchone()
        return SnapshotReceipt(**json.loads(row[0])) if row else None
