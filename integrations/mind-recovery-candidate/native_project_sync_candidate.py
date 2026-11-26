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
import sqlite3
import threading

from onoes_mind.enrollment_store import qualify_private_storage
from onoes_mind.runtime_keys import _crypt
from onoes_mind.ledger import _verify_password
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


def credential_context(binding, project_ids, review_ref):
    """Pure purpose entropy; keep the existing sealed-file representation stable."""
    require(type(binding) is EventBinding)
    require(type(project_ids) is tuple and 1 <= len(project_ids) <= 8
            and all(identifier(p) for p in project_ids)
            and tuple(sorted(set(project_ids))) == project_ids)
    require(type(review_ref) is str and 1 <= len(review_ref) <= 300
            and review_ref.strip() == review_ref
            and not any(ord(c) < 32 or ord(c) == 127 for c in review_ref))
    raw = json.dumps(dict(purpose=SCHEMA, principal=PRINCIPAL, scope=SCOPE,
        binding=asdict(binding), projects=project_ids, reviewRef=review_ref),
        sort_keys=True, separators=(',', ':')).encode('utf-8')
    require(len(raw) <= 8192)
    return raw


def context(events, project_ids, review_ref):
    require(type(events) is ProjectEventsCandidate
            and type(events.ledger) is CheckpointedLedgerCandidate)
    raw = credential_context(events.binding, project_ids, review_ref)
    b = events.binding
    require((events.ledger._checkpoint_store_id, events.ledger._checkpoint_environment)
            == (b.store_id, b.environment))
    database = qualify_private_storage(Path(b.database_path), kind='file')
    require(database.resolve(strict=True) == database)
    events._binding()
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


def _unseal(path, entropy):
    target = qualify_private_storage(Path(path), kind='file')
    envelope = json.loads(read_plain(target, 8192), object_pairs_hook=unique)
    require(type(envelope) is dict and set(envelope) == {'schema','protection','bindingSha256','ciphertext'}
            and envelope['schema'] == SCHEMA and envelope['protection'] == 'windows-current-user'
            and envelope['bindingSha256'] == hashlib.sha256(entropy).hexdigest())
    require(type(envelope['ciphertext']) is str and len(envelope['ciphertext']) <= 4096)
    token = _crypt(base64.b64decode(envelope['ciphertext'], validate=True), entropy, protect=False).decode('ascii')
    token_bytes(token)
    return token


def load_project_credential(path, *, events, project_ids, review_ref):
    """Secret-bearing return for trusted native constructor/pipe input only."""
    token = None
    try:
        entropy = context(events, project_ids, review_ref)
        token = _unseal(path, entropy)
        authorize(events, token, project_ids, review_ref)
        return token
    except Exception:
        raise ProjectCredentialError('Protected project-sync credential unavailable or binding refused.') from None
    finally:
        token = None  # Reference clearing only; not guaranteed memory erasure.


def load_project_client_credential(path, *, binding, project_ids, review_ref):
    """Reload client custody using read-only identity/grant metadata, never keys.

    The caller must separately attest the service process/destination. This does
    not qualify deletion authority or authorize a write; the receiver enforces
    those on every request. No memory content is read by this function.
    """
    token = db = None
    try:
        entropy = credential_context(binding, project_ids, review_ref)
        database = qualify_private_storage(Path(binding.database_path), kind='file')
        require(database.resolve(strict=True) == database)
        stat = database.stat()
        require((stat.st_dev,stat.st_ino) == (binding.file_device,binding.file_inode))
        token = _unseal(path, entropy)
        db = sqlite3.connect(database.as_uri()+'?mode=ro', uri=True)
        db.execute('PRAGMA query_only=ON')
        require([Path(r[2]).resolve() for r in db.execute('PRAGMA database_list') if r[1]=='main'] == [database])
        metadata = {'sqlite_master','sqlite_schema','recall_store_identity','project_sync_format',
            'principals','project_sync_credentials','credentials','scope_grants','recall_service_credentials',
            'project_sync_grants','project_sync_projects'}
        def metadata_only(action, table, _column, _database, _trigger):
            if action == sqlite3.SQLITE_READ:
                return sqlite3.SQLITE_OK if table in metadata else sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK if action in (sqlite3.SQLITE_SELECT,sqlite3.SQLITE_TRANSACTION) else sqlite3.SQLITE_DENY
        db.set_authorizer(metadata_only)
        db.execute('BEGIN')
        require(db.execute('SELECT store_id,environment,authority_ref FROM recall_store_identity').fetchall()
                == [(binding.store_id,binding.environment,binding.authority_ref)])
        require(db.execute('SELECT version FROM project_sync_format').fetchall() == [(2,)])
        row = db.execute('SELECT c.salt,c.verifier,c.epoch,p.credential_epoch,p.kind FROM project_sync_credentials c JOIN principals p USING(principal_id) WHERE c.principal_id=?',(PRINCIPAL,)).fetchone()
        require(row is not None and row[2] == row[3] and row[4] == 'service'
                and _verify_password(token,row[0],row[1]))
        require(not db.execute('SELECT 1 FROM credentials WHERE principal_id=?',(PRINCIPAL,)).fetchone()
                and not db.execute('SELECT 1 FROM scope_grants WHERE principal_id=?',(PRINCIPAL,)).fetchone())
        if db.execute("SELECT 1 FROM sqlite_schema WHERE name='recall_service_credentials'").fetchone():
            require(not db.execute('SELECT 1 FROM recall_service_credentials WHERE principal_id=?',(PRINCIPAL,)).fetchone())
        require(tuple(r[0] for r in db.execute('SELECT project_id FROM project_sync_grants WHERE principal_id=? AND active=1 ORDER BY project_id',(PRINCIPAL,))) == project_ids)
        for project in project_ids:
            require(db.execute('SELECT 1 FROM project_sync_projects WHERE project_id=? AND deleted=0',(project,)).fetchone())
        db.execute('COMMIT'); require(db.total_changes == 0)
        qualify_private_storage(database,kind='file'); stat = database.stat()
        require((stat.st_dev,stat.st_ino) == (binding.file_device,binding.file_inode))
        return token
    except Exception:
        raise ProjectCredentialError('Read-only project client custody unavailable or binding refused.') from None
    finally:
        if db is not None: db.close()
        token = None


def _stage_project_credential(path, token, entropy):
    """Write fresh private custody and verify it before a grant can take effect."""
    try:
        raw = token_bytes(token)
        target = Path(path)
        require(target.is_absolute() and '..' not in target.parts and not os.path.lexists(target))
        parent = qualify_private_storage(target.parent)
        require(parent.resolve(strict=True) == parent)
        identity = (parent.stat().st_dev, parent.stat().st_ino)
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
        require(_unseal(target, entropy) == token)
        qualify_private_storage(parent)
        require((parent.stat().st_dev, parent.stat().st_ino) == identity)
        return dict(schema=SCHEMA, protected=True, bindingSha256=envelope['bindingSha256'],
                    fileSha256=hashlib.sha256(data).hexdigest())
    except Exception:
        raise ProjectCredentialError('Project-sync credential was not committed successfully; preserve files.') from None


def seal_project_credential(path, token, *, events, project_ids, review_ref):
    """Seal once; never issue, replace, rebind or silently repair credentials."""
    try:
        entropy = context(events, project_ids, review_ref)
        authorize(events, token, project_ids, review_ref)
        storage = _stage_project_credential(path, token, entropy)
        require(load_project_credential(path, events=events, project_ids=project_ids, review_ref=review_ref) == token)
        return storage
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
                 credential_path, project_ids, review_ref, agent_home_bindings=(), agent_home_port=0, handoff_binding=None, project_reader_bindings=()):
        require(type(agent_home_bindings) is tuple and len(agent_home_bindings) <= 5)
        require(type(agent_home_port) is int and 0 <= agent_home_port <= 65535
                and (agent_home_bindings or agent_home_port == 0))
        if handoff_binding is not None:
            from onoes_mind.handoff_channel import HandoffBinding
            require(bool(agent_home_bindings) and isinstance(handoff_binding,HandoffBinding)
                    and handoff_binding.project_id in project_ids
                    and handoff_binding.store.scope_id == 'project/onoes-mind/shared'
                    and all(getattr(handoff_binding.store,key) == getattr(binding,key) for key in
                        ('database_path','store_id','environment','authority_ref','file_device','file_inode')))
        require(type(project_reader_bindings) is tuple and len(project_reader_bindings) <= 8
                and (not project_reader_bindings or bool(agent_home_bindings)))
        if project_reader_bindings:
            from onoes_mind.agent_context import AgentContextBinding
            from onoes_mind.project_tool_grant import ReviewedProjectToolGrant,TOOL_NAME
            principals=[]
            for row in project_reader_bindings:
                require(type(row) is tuple and len(row)==2)
                selected,grant=row
                require(isinstance(selected,AgentContextBinding) and isinstance(grant,ReviewedProjectToolGrant)
                        and grant.binding==selected and grant.tool_name==TOOL_NAME
                        and all(getattr(selected.store,key)==getattr(binding,key) for key in
                            ('database_path','store_id','environment','authority_ref','file_device','file_inode')))
                principals.append(selected.principal_id)
            require(principals==sorted(set(principals)))
        self.project_reader_bindings = project_reader_bindings
        self.project_readers = []
        self.handoff_binding = handoff_binding
        self.binding = binding
        self.history_path, self.authority = history_path, authority
        self.keys = dict(audit_key=audit_key, deletion_key=deletion_key)
        self.credential_path, self.projects, self.review = credential_path, project_ids, review_ref
        self.lease = self.ledger = self.events = self.server = None
        self.home_bindings = agent_home_bindings
        self.home_port = agent_home_port
        self.home_server = None
        self.writer_lock = threading.RLock()
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
            self.server = ProjectEventsServerCandidate(self.events, project_ids=self.projects,
                writer_lock=self.writer_lock)
            if self.home_bindings:
                # Source-only opt-in. No enrollment, scope selection from HTTP,
                # second ledger, second lease, or startup discovery.
                from onoes_mind.agent_home import AgentHome
                from onoes_mind.agent_home_http import AgentHomeServer
                homes = tuple(AgentHome(self.ledger, binding) for binding in self.home_bindings)
                options = {}
                if self.handoff_binding is not None:
                    from onoes_mind.handoff_channel import HandoffChannel
                    options['handoff_channel'] = HandoffChannel(self.ledger,self.handoff_binding)
                if self.project_reader_bindings:
                    from onoes_mind.agent_context import ProjectContextReader
                    from onoes_mind.project_context_http import ProjectReadEndpoint
                    from onoes_mind.project_tool_grant import TOOL_NAME
                    endpoints=[]
                    for selected,grant in self.project_reader_bindings:
                        qualify_private_storage(grant.path,kind='file')
                        require(grant(selected,TOOL_NAME) is True)
                        reader=ProjectContextReader(selected.store.database_path,binding=selected)
                        self.project_readers.append(reader)
                        def current_grant(bound,name,grant=grant):
                            qualify_private_storage(grant.path,kind='file')
                            return grant(bound,name)
                        endpoints.append(ProjectReadEndpoint(reader,current_grant))
                    options['project_readers']=tuple(endpoints)
                self.home_server = AgentHomeServer(homes,writer_lock=self.writer_lock,port=self.home_port,**options)
            self.server.start()
            if self.home_server is not None:self.home_server.start()
            return self.status()
        except Exception:
            self.close()
            raise ProjectCredentialError('Protected project-sync service did not start; preserve files.') from None

    def status(self):
        return dict(ready=not self.stopped and self.lease is not None and self.lease.handle is not None and self.server is not None
                    and self.server.thread is not None and self.server.thread.is_alive()
                    and (not self.home_bindings or (self.home_server is not None
                        and self.home_server._thread is not None and self.home_server._thread.is_alive())))

    def agent_home_options(self):
        """Non-secret connection descriptors for explicitly attached homes only."""
        require(self.status()['ready'] and self.home_server is not None)
        from onoes_mind.agent_home_http import home_binding_sha256
        return dict(baseUrl=self.home_server.base_url, agents={
            actor:home_binding_sha256(home.binding) for actor,home in self.home_server.homes.items()})

    def project_read_options(self):
        require(self.status()['ready'] and self.home_server is not None and bool(self.project_reader_bindings))
        from onoes_mind.project_context_http import context_binding_sha256
        return dict(baseUrl=self.home_server.base_url,readers={
            reader.context_binding.principal_id:dict(bindingSha256=context_binding_sha256(reader.context_binding),
                projectId=reader.context_binding.project_id,scopeId=reader.context_binding.store.scope_id)
            for reader in self.project_readers})

    def handoff_options(self):
        """Non-secret descriptor for the explicit owner-only record refresh."""
        require(self.status()['ready'] and self.home_server is not None and self.handoff_binding is not None)
        from onoes_mind.handoff_channel import handoff_binding_sha256
        return dict(baseUrl=self.home_server.base_url,bindingSha256=handoff_binding_sha256(self.handoff_binding),
                    recordId=self.handoff_binding.record_id,projectId=self.handoff_binding.project_id,
                    author=self.handoff_binding.author)

    def native_options(self):
        """Secret return for direct native constructor/pipe use, never logs/files."""
        require(self.status()['ready'])
        with self.writer_lock:
            token = load_project_credential(self.credential_path, events=self.events,
                project_ids=self.projects, review_ref=self.review)
        address, port = self.server.address
        require(address == '127.0.0.1')
        return dict(baseUrl=f'http://127.0.0.1:{port}/', token=token, storeId=self.binding.store_id)

    def close(self):
        self.stopped = True
        # Never release the lifetime lock ahead of listener/writer retirement.
        # A failed close preserves the lease for explicit handling; no restart.
        if self.home_server is not None:
            self.home_server.close(); self.home_server = None
        if self.server is not None:
            self.server.close(); self.server = None
        while self.project_readers:
            self.project_readers[-1].close(); self.project_readers.pop()
        if self.ledger is not None:
            self.ledger.close(); self.ledger = self.events = None
        if self.lease is not None:
            self.lease.close(); self.lease = None
        self.keys = None
