"""Inactive custody for an already issued project-sync service credential.

No enrollment, rotation, recovery, CLI or startup is provided. The caller owns
reviewed authorization and exclusive protected-writer lifecycle. Current-user
DPAPI does not isolate the token from other same-login/admin processes.
"""
import base64
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path

from onoes_mind.enrollment_store import qualify_private_storage
from onoes_mind.runtime_keys import _crypt
from checkpoint_candidate import read_plain
from checkpointed_ledger_candidate import CheckpointedLedgerCandidate
from project_events_candidate import ProjectEventsCandidate, EventBinding, PRINCIPAL, SCOPE, identifier
from project_events_http_candidate import ProjectEventsServerCandidate

SCHEMA = 'onoes-mind-project-sync-credential/v1'


class ProjectCredentialError(RuntimeError):
    pass


def require(ok):
    if not ok:
        raise ProjectCredentialError('Protected project-sync credential unavailable or binding refused.')


def context(events, project_ids, review_ref):
    require(type(events) is ProjectEventsCandidate
            and type(events.ledger) is CheckpointedLedgerCandidate)
    require(type(project_ids) is tuple and 1 <= len(project_ids) <= 8
            and all(identifier(p) for p in project_ids)
            and tuple(sorted(set(project_ids))) == project_ids)
    require(type(review_ref) is str and 1 <= len(review_ref) <= 300
            and review_ref.strip() == review_ref
            and not any(ord(c) < 32 or ord(c) == 127 for c in review_ref))
    b = events.binding
    require((events.ledger._checkpoint_store_id, events.ledger._checkpoint_environment)
            == (b.store_id, b.environment))
    database = qualify_private_storage(Path(b.database_path), kind='file')
    require(database.resolve(strict=True) == database)
    events._binding()
    raw = json.dumps(dict(purpose=SCHEMA, principal=PRINCIPAL, scope=SCOPE,
        binding=asdict(b), projects=project_ids, reviewRef=review_ref),
        sort_keys=True, separators=(',', ':')).encode('utf-8')
    require(len(raw) <= 8192)
    return raw


def token_bytes(token):
    require(type(token) is str and 16 <= len(token) <= 256
            and all(33 <= ord(c) <= 126 for c in token))
    return token.encode('ascii')


def authorize(events, token, project_ids, review_ref):
    context(events, project_ids, review_ref)
    token_bytes(token)
    # Validate current epoch, exact grants and retained deletion authority. No
    # generic operator/read credential or broadened project grant is accepted.
    with events.lock, events._history_guard(), events.ledger._transaction():
        for project in project_ids:
            events._authorize(token, project)
            require(events.db.execute('SELECT 1 FROM project_sync_projects WHERE project_id=? AND deleted=0',
                                      (project,)).fetchone())
        active = tuple(row[0] for row in events.db.execute(
            'SELECT project_id FROM project_sync_grants WHERE principal_id=? AND active=1 ORDER BY project_id',
            (PRINCIPAL,)))
        require(active == project_ids)
        require(not events.db.execute('SELECT 1 FROM scope_grants WHERE principal_id=?', (PRINCIPAL,)).fetchone())
        if events.db.execute("SELECT 1 FROM sqlite_schema WHERE name='recall_service_credentials'").fetchone():
            require(not events.db.execute('SELECT 1 FROM recall_service_credentials WHERE principal_id=?',
                                          (PRINCIPAL,)).fetchone())


def unique(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result)
        result[key] = value
    return result


def load_project_credential(path, *, events, project_ids, review_ref):
    """Secret-bearing return for trusted native constructor/pipe input only."""
    token = None
    try:
        entropy = context(events, project_ids, review_ref)
        target = qualify_private_storage(Path(path), kind='file')
        envelope = json.loads(read_plain(target, 8192), object_pairs_hook=unique)
        require(type(envelope) is dict and set(envelope) == {'schema','protection','bindingSha256','ciphertext'}
                and envelope['schema'] == SCHEMA and envelope['protection'] == 'windows-current-user'
                and envelope['bindingSha256'] == hashlib.sha256(entropy).hexdigest())
        require(type(envelope['ciphertext']) is str and len(envelope['ciphertext']) <= 4096)
        token = _crypt(base64.b64decode(envelope['ciphertext'], validate=True), entropy, protect=False).decode('ascii')
        authorize(events, token, project_ids, review_ref)
        return token
    except Exception:
        raise ProjectCredentialError('Protected project-sync credential unavailable or binding refused.') from None
    finally:
        token = None  # Reference clearing only; not guaranteed memory erasure.


def seal_project_credential(path, token, *, events, project_ids, review_ref):
    """Seal once; never issue, replace, rebind or silently repair credentials."""
    try:
        entropy = context(events, project_ids, review_ref)
        raw = token_bytes(token)
        target = Path(path)
        require(target.is_absolute() and '..' not in target.parts and not os.path.lexists(target))
        parent = qualify_private_storage(target.parent)
        require(parent.resolve(strict=True) == parent)
        identity = (parent.stat().st_dev, parent.stat().st_ino)
        authorize(events, token, project_ids, review_ref)
        encrypted = _crypt(raw, entropy, protect=True)
        envelope = dict(schema=SCHEMA, protection='windows-current-user',
            bindingSha256=hashlib.sha256(entropy).hexdigest(),
            ciphertext=base64.b64encode(encrypted).decode('ascii'))
        data = (json.dumps(envelope, indent=2) + '\n').encode('utf-8')
        qualify_private_storage(parent)
        require((parent.stat().st_dev, parent.stat().st_ino) == identity)
        with target.open('xb') as output:
            output.write(data); output.flush(); os.fsync(output.fileno())
        qualify_private_storage(target, kind='file')
        require(read_plain(target, 8192) == data)
        require(load_project_credential(target, events=events, project_ids=project_ids, review_ref=review_ref) == token)
        qualify_private_storage(parent)
        require((parent.stat().st_dev, parent.stat().st_ino) == identity)
        return dict(schema=SCHEMA, protected=True, bindingSha256=envelope['bindingSha256'],
                    fileSha256=hashlib.sha256(data).hexdigest())
    except Exception:
        raise ProjectCredentialError('Project-sync credential was not committed successfully; preserve files.') from None


class ProjectServiceLease:
    """Kernel-held lifetime lock at the fixed canonical-store location.

    The file is retained after close/crash; its existence is not the lock. No
    PID, timestamp, file age or stale-file deletion can grant ownership.
    """
    HEADER = b'Onoes project-sync service lease v1\n'

    def __init__(self, binding):
        self.handle = None
        require(type(binding) is EventBinding)
        database = qualify_private_storage(Path(binding.database_path), kind='file')
        require(database.resolve(strict=True) == database)
        stat = database.stat()
        require((stat.st_dev, stat.st_ino) == (binding.file_device, binding.file_inode))
        parent = qualify_private_storage(database.parent)
        self.path = parent / '.project-sync-service.lock'
        try:
            # Never inherit this handle into a worker/child process.
            flags = os.O_RDWR | os.O_BINARY | os.O_NOINHERIT
            try:
                fd = os.open(self.path, flags | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(fd, 'wb') as created:
                    created.write(self.HEADER); created.flush(); os.fsync(created.fileno())
            except FileExistsError:
                pass
            qualify_private_storage(self.path, kind='file')
            require(read_plain(self.path, 128) == self.HEADER)
            self.handle = self.path.open('r+b')
            import msvcrt
            msvcrt.locking(self.handle.fileno(), msvcrt.LK_NBLCK, 1)
            # Opening an existing file never grants ownership without this lock.
            qualify_private_storage(self.path, kind='file')
            current = self.path.stat(); opened = os.fstat(self.handle.fileno())
            require((current.st_dev, current.st_ino) == (opened.st_dev, opened.st_ino))
            require(self.handle.read() == self.HEADER)
        except Exception:
            if self.handle is not None:
                self.handle.close(); self.handle = None
            raise ProjectCredentialError('Project-sync service ownership unavailable; preserve files.') from None

    def close(self):
        if self.handle is not None:
            self.handle.close(); self.handle = None


class NativeProjectSyncHost:
    """Own one protected writer/listener; no discovery, setup or auto recovery."""
    def __init__(self, *, binding, history_path, authority, audit_key, deletion_key,
                 credential_path, project_ids, review_ref):
        self.binding = binding
        self.history_path, self.authority = history_path, authority
        self.keys = dict(audit_key=audit_key, deletion_key=deletion_key)
        self.credential_path, self.projects, self.review = credential_path, project_ids, review_ref
        self.lease = self.ledger = self.events = self.server = None
        self.stopped = False

    def start(self):
        require(not self.stopped and self.lease is None)
        try:
            self.lease = ProjectServiceLease(self.binding)
            self.ledger = CheckpointedLedgerCandidate(self.binding.database_path, self.history_path,
                self.authority, store_id=self.binding.store_id, environment=self.binding.environment, **self.keys)
            self.events = ProjectEventsCandidate(self.ledger, self.binding)
            # No listener exists until current credential and exact grants pass.
            load_project_credential(self.credential_path, events=self.events,
                project_ids=self.projects, review_ref=self.review)
            self.server = ProjectEventsServerCandidate(self.events, project_ids=self.projects)
            self.server.start()
            return self.status()
        except Exception:
            self.close()
            raise ProjectCredentialError('Protected project-sync service did not start; preserve files.') from None

    def status(self):
        return dict(ready=not self.stopped and self.lease is not None and self.lease.handle is not None and self.server is not None
                    and self.server.thread is not None and self.server.thread.is_alive())

    def native_options(self):
        """Secret return for direct native constructor/pipe use, never logs/files."""
        require(self.status()['ready'])
        token = load_project_credential(self.credential_path, events=self.events,
            project_ids=self.projects, review_ref=self.review)
        address, port = self.server.address
        require(address == '127.0.0.1')
        return dict(baseUrl=f'http://127.0.0.1:{port}/', token=token, storeId=self.binding.store_id)

    def close(self):
        self.stopped = True
        # Never release the lifetime lock ahead of listener/writer retirement.
        # A failed close preserves the lease for explicit handling; no restart.
        if self.server is not None:
            self.server.close(); self.server = None
        if self.ledger is not None:
            self.ledger.close(); self.ledger = self.events = None
        if self.lease is not None:
            self.lease.close(); self.lease = None
        self.keys = None
