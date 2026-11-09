"""Candidate native tools.mesh_writer_scope; no HTTP/config enrollment or release grant."""
from contextlib import contextmanager
from contextvars import ContextVar, copy_context
from concurrent.futures import Future
from pathlib import Path
import shutil
import re
import subprocess
import threading
import time
from types import SimpleNamespace
from uuid import uuid4

_current = ContextVar('mesh_owned_writer_fence', default=None)
_lifetime = ContextVar('mesh_writer_lifetime', default=None)
_worker = ContextVar('mesh_owned_worker_ticket', default=None)
_canonical_claim = ContextVar('mesh_canonical_writer_claim', default=None)
_unspecified_environment = object()


class WriterRunRegistry:
    """In-process direct-run enrollment; no HTTP/config activation or release grant.

    Entries survive delivery completion/cancellation. A later durable consumer must
    acknowledge retirement; this candidate deliberately provides no forget/retry API.
    """
    def __init__(self, fence_factory, *, max_entries=256):
        if not callable(fence_factory) or type(max_entries) is not int or not 1 <= max_entries <= 4096:
            raise ValueError('A trusted fence factory and bounded capacity are required')
        self._factory, self._limit = fence_factory, max_entries
        self._lock, self._entries = threading.RLock(), {}
        self._owner_id = str(uuid4())

    @property
    def owner_id(self):
        return self._owner_id

    def enroll(self, run):
        run_id = getattr(run, 'run_id', None)
        if not isinstance(run_id, str) or not re.fullmatch(r'run_[0-9a-f]{32}', run_id):
            raise ValueError('A native generated run ID is required')
        if getattr(run, 'admission', None) is not None:
            raise RuntimeError('Canonical session-owner execution is not a direct managed run')
        with self._lock:
            if run_id in self._entries:
                raise RuntimeError('Native run enrollment is already reserved')
            if len(self._entries) >= self._limit:
                raise RuntimeError('Native writer enrollment capacity is held')
            if getattr(run, 'writer_lifetime', None) is not None or getattr(run, 'writer_generation', ''):
                raise RuntimeError('A caller cannot supply native lifetime enrollment')
            generation = str(uuid4())
            entry = {'run': run, 'generation': generation, 'state': 'reserved', 'fence': None, 'lifetime': None}
            self._entries[run_id] = entry  # Reserve before resource creation; unknown failures stay held.
            try:
                fence = entry['fence'] = self._factory(run_id, generation)
                if (getattr(fence, 'run_id', None) != run_id or getattr(fence, 'generation', None) != generation
                        or not callable(getattr(fence, 'popen', None))):
                    raise RuntimeError('Factory returned a mismatched native process fence')
                lifetime = entry['lifetime'] = WriterLifetime(fence)
                run.writer_lifetime, run.writer_generation = lifetime, generation
                entry['state'] = 'enrolled'
                return lifetime
            except BaseException:
                entry['state'] = 'unknown'
                raise

    def snapshot(self, run_id):
        with self._lock:
            entry = self._entries.get(run_id)
            if entry is None:
                return None
            lifetime = entry['lifetime']
            return {'schema': 'mesh-native-writer-enrollment/v1', 'runId': run_id,
                    'generation': entry['generation'], 'state': entry['state'],
                    'lifetime': lifetime.snapshot() if lifetime is not None else None,
                    'writerQuiescence': False}


def observe_writer_run(registry, run_id):
    """Fresh server observation; cached status/delivery can never grant release."""
    result = {'schema': 'mesh-native-writer-observation/v1', 'runId': run_id,
              'observedAt': int(time.time() * 1000), 'ownerId': None,
              'state': 'not_configured', 'enrollment': None,
              'observationOnly': True, 'writerQuiescence': False}
    if registry is None:
        return result
    result['state'] = 'unknown'
    if not isinstance(registry, WriterRunRegistry):
        return result
    result['ownerId'] = registry.owner_id
    try:
        enrollment = registry.snapshot(run_id)
        if enrollment is not None:
            result['enrollment'] = enrollment
            if enrollment['state'] == 'enrolled':
                result['state'] = 'observed'
    except Exception:
        pass  # Missing process observation must remain unknown, never reuse a stale receipt.
    return result


def enroll_direct_writer_run(registry, run):
    """Called only by the native direct-executor branch, before agent construction."""
    if registry is None:
        return None  # Unconfigured gateway keeps its original behavior, without new proof.
    if not isinstance(registry, WriterRunRegistry):
        raise RuntimeError('Native writer registry must be installed in-process')
    return registry.enroll(run)


class WriterLifetime:
    """Track actual managed callables/futures; never grant whole-worker release.

    Constructed by a trusted future native-run factory, not HTTP request fields.
    Root admission starts held. Unknown submissions stay held unless their callable
    later actually returns. A forced delivery/finalization record cannot settle a
    ticket; only its observed callable/future lifecycle can do so.
    """
    def __init__(self, fence):
        self.fence = fence
        self._lock = threading.RLock()
        self._pending = {'root': {'kind': 'foreground', 'state': 'reserved', 'started': False}}
        self._root_started = self._root_ended = self._sealed = False
        self._fault = ''
        self._tool_calls = 0
        self._tool_active = set()
        self._tool_uncertain = 0

    def _begin_tool(self):
        with self._lock:
            self.assert_current_worker()
            ticket = str(uuid4())
            self._tool_calls += 1
            self._tool_active.add(ticket)
            return ticket

    def _end_tool(self, ticket):
        with self._lock:
            if ticket not in self._tool_active:
                self._fault = 'tool_lifecycle_unconfirmed'
                return
            self._tool_active.remove(ticket)
            # A returned handler/middleware is not proof that an external service
            # stopped. Only a separately qualified adapter may ever settle effects.
            self._tool_uncertain += 1
            self._maybe_seal()

    def assert_current_worker(self):
        with self._lock:
            owner = _worker.get()
            record = self._pending.get(owner[1]) if owner and owner[0] is self else None
            if _lifetime.get() is not self or not record or record['state'] != 'running':
                raise RuntimeError('This worker context is no longer active')

    def _reserve(self, kind='delegate'):
        with self._lock:
            self.assert_current_worker()
            ticket = str(uuid4())
            self._pending[ticket] = {'kind': kind, 'state': 'reserved', 'started': False, 'mode': 'submitting'}
            return ticket

    def _start(self, ticket):
        with self._lock:
            record = self._pending.get(ticket)
            if not record or record['started']:
                raise RuntimeError('Worker admission is missing or already consumed')
            record.update(started=True, state='running')

    def _maybe_seal(self):
        if self._root_ended and not self._pending and not self._tool_active and not self._sealed:
            try:
                self.fence.seal()
                self._sealed = True
            except BaseException:
                self._fault = 'process_fence_unavailable'

    def _returned(self, ticket):
        with self._lock:
            record = self._pending.get(ticket)
            if not record:
                self._fault = 'worker_lifecycle_unconfirmed'
                return
            record['state'] = 'returned'
            # No future was returned after an uncertain submit. The actual callable
            # returning is still affirmative evidence that this admitted body ended.
            if record.get('mode') == 'unknown':
                self._pending.pop(ticket)
            self._maybe_seal()

    def _submission_unknown(self, ticket):
        with self._lock:
            record = self._pending[ticket]
            record['mode'] = 'unknown'
            if record['state'] == 'returned':
                self._pending.pop(ticket)
            elif not record['started']:
                record['state'] = 'unknown'
            self._maybe_seal()

    def _attach(self, ticket, future):
        if not isinstance(future, Future):
            self._submission_unknown(ticket)
            raise TypeError('A native concurrent future is required')
        with self._lock:
            self._pending[ticket]['mode'] = 'future'
        def done(observed):
            with self._lock:
                record = self._pending.get(ticket)
                if not record:
                    return
                if not observed.done() or record['started'] and record['state'] != 'returned':
                    self._fault = 'future_lifecycle_unconfirmed'
                    return
                # A genuine future cancelled/rejected before starting cannot run
                # its callable. A running future cannot become done before return.
                self._pending.pop(ticket)
                self._maybe_seal()
        future.add_done_callback(done)

    def snapshot(self):
        with self._lock:
            process = self.fence.snapshot()
            managed = (self._root_ended and not self._pending and not self._tool_active and self._sealed and not self._fault
                       and process.get('state') in ('ended', 'not_started') and process.get('activeProcesses') == 0)
            return {'schema': 'mesh-managed-writer-lifetime/v1', 'runId': self.fence.run_id,
                    'generation': self.fence.generation, 'rootEnded': self._root_ended,
                    'pendingWorkers': [{'id': key, 'kind': value['kind'], 'state': value['state']}
                                       for key, value in self._pending.items()],
                    'processTree': process, 'managedWorkEnded': managed,
                    'writerQuiescence': False, 'reason': self._fault,
                    'toolEffects': {'observedCalls': self._tool_calls, 'activeCalls': len(self._tool_active),
                                    'unverifiedCalls': self._tool_uncertain,
                                    'effectsSettled': self._tool_calls == 0,
                                    'policy': 'no_external_effect_adapter_qualified'},
                    'coverage': 'instrumented_foreground_delegate_and_job_members_only'}

    def wait(self, timeout_ms=5000):
        if not isinstance(timeout_ms, int) or not 0 <= timeout_ms <= 60000:
            raise ValueError('A bounded observation wait is required')
        deadline = time.monotonic() + timeout_ms / 1000
        while True:
            result = self.snapshot()
            if result['managedWorkEnded'] or time.monotonic() >= deadline:
                return result
            time.sleep(min(.02, max(0, deadline - time.monotonic())))


@contextmanager
def writer_tool_effect():
    """Observe before middleware; no arguments, results, credentials or memory retained."""
    lifetime = _lifetime.get()
    if lifetime is None:
        yield
        return
    ticket = lifetime._begin_tool()
    try:
        yield
    finally:
        lifetime._end_tool(ticket)


async def require_managed_session_owner(adapter, session_id):
    """Refuse unmanaged/live-chat targets before native run reservation or handoff.

    A configured registry is for a bounded managed-worker lane. Existing personal
    conversations are not silently moved to a second writer or a different chat.
    """
    registry = getattr(adapter, '_mesh_writer_runs', None)
    if registry is None:
        return
    if not isinstance(registry, WriterRunRegistry):
        raise RuntimeError('Managed worker registry is unverified')
    if not session_id:
        return
    import asyncio
    db = await adapter._ensure_session_db_async()
    if db is None:
        raise RuntimeError('Managed conversation ownership is unavailable')
    session = await asyncio.to_thread(db.get_session, session_id)
    if session is None:
        return  # New API target; no existing conversation is being taken over.
    if session.get('source') != 'api_server':
        raise RuntimeError('Managed work requires an API-owned conversation')
    from gateway.session_authorities import active_authority
    authority = active_authority(adapter.gateway_runner)
    if authority is not None:
        from gateway.platforms.api_server_bot_chat import bot_chat_tip
        if await asyncio.to_thread(bot_chat_tip, authority, session_id) is not None:
            raise RuntimeError('Live Bot Chat execution is not a managed worker')
    else:
        from tools.bot_live_delivery import find_canonical_live_owner
        owner = await asyncio.to_thread(find_canonical_live_owner, Path(db.db_path).parent)
        if owner is not None and await asyncio.to_thread(db.get_compression_tip, session_id) == owner['session_id']:
            raise RuntimeError('A live chat owner already holds this conversation')


@contextmanager
def canonical_admission_writer_scope(authority, ref, row, adapter):
    """Enroll only the currently claimed, durable native API-run admission.

    Native admission authorization stays authoritative. This validates its current
    execution stamp, not a caller-supplied run/lifetime or an HTTP observer.
    """
    registry = getattr(adapter, '_mesh_writer_runs', None)
    run_id = row.get('request_id')
    if registry is None or not isinstance(run_id, str) or not run_id.startswith('run_'):
        yield
        return
    if not isinstance(registry, WriterRunRegistry) or not re.fullmatch(r'run_[0-9a-f]{32}', run_id):
        raise RuntimeError('Canonical native run enrollment is unverified')
    if _canonical_claim.get() is not None or _lifetime.get() is not None:
        raise RuntimeError('Canonical execution cannot replace an existing writer claim')
    from gateway.platforms.api_server_authority_runs import run_admission
    owned = run_admission(adapter, run_id)
    fields = ('admission_id', 'request_id', 'target_session_id', 'principal_id', 'owner_epoch', 'generation', 'status', 'payload')
    scope = row.get('payload', {}).get('api_turn_v1', {}).get('run_owner_scope')
    if (owned is None or owned[0] is not authority
            or ref.profile_id != authority.profile_id or row.get('target_session_id') != ref.session_id
            or row.get('principal_id') != 'api' or row.get('owner_epoch') != authority.epoch
            or row.get('status') != 'started' or type(row.get('generation')) is not int or row['generation'] < 1
            or not isinstance(scope, str) or not re.fullmatch(r'[0-9a-f]{64}', scope)
            or any(owned[1].get(key) != row.get(key) for key in fields)):
        raise RuntimeError('Canonical admission identity is unverified')
    live = authority.sessions[ref.session_id]
    with live.event_stream.lock:
        stamp = live.event_stream.execution
        expected = {'authority_epoch': authority.epoch, 'execution_generation': row['generation'],
                    'admission_id': row['admission_id']}
        if stamp != expected or authority.executing.get(ref.session_id) != row['generation']:
            raise RuntimeError('Canonical execution claim is no longer current')
        run = SimpleNamespace(run_id=run_id, admission=None, writer_lifetime=None, writer_generation='',
                              canonical_claim=dict(expected))
        lifetime = registry.enroll(run)  # Duplicate/recovered enrollment remains held, never replaced.
    with bind_canonical_writer_claim(lifetime):
        yield


@contextmanager
def bind_canonical_writer_claim(lifetime):
    """Carry a trusted reserved claim to its real worker; observer exit never settles it.

    This is an in-process seam only. Admission/owner enrollment is not implemented
    here, and no request field may supply this binding.
    """
    if (not isinstance(lifetime, WriterLifetime) or _canonical_claim.get() is not None
            or _lifetime.get() is not None):
        raise RuntimeError('A distinct trusted canonical claim is required')
    claim = (lifetime, lifetime.fence.run_id, lifetime.fence.generation)
    token = _canonical_claim.set(claim)
    try:
        yield
    finally:
        _canonical_claim.reset(token)  # Not a worker completion event.


@contextmanager
def canonical_writer_foreground_scope():
    claim = _canonical_claim.get()
    if claim is None:
        yield
        return
    lifetime, run_id, generation = claim
    with writer_foreground_scope(lifetime, expected_run_id=run_id, expected_generation=generation):
        yield


@contextmanager
def writer_foreground_scope(lifetime, *, expected_run_id=None, expected_generation=None):
    if lifetime is None:
        yield
        return
    if not isinstance(lifetime, WriterLifetime) or _lifetime.get() not in (None, lifetime):
        raise RuntimeError('Invalid native writer lifetime binding')
    if (expected_run_id is not None and (not expected_run_id or expected_run_id != lifetime.fence.run_id)
            or expected_generation is not None and (not expected_generation or expected_generation != lifetime.fence.generation)):
        raise RuntimeError('Native run/generation does not match its writer lifetime')
    with bind_writer_fence(lifetime.fence):
        lifetime._start('root')
        lifetime._root_started = True
        owner, ticket = _lifetime.set(lifetime), _worker.set((lifetime, 'root'))
        try:
            yield
        finally:
            _worker.reset(ticket)
            _lifetime.reset(owner)
            with lifetime._lock:
                lifetime._pending.pop('root')
                lifetime._root_ended = True
                lifetime._maybe_seal()


def submit_writer_work(executor, fn, propagate=None, *args, **kwargs):
    """Use the existing executor and its context propagator, not a new worker pool."""
    if propagate is None:
        def propagate(call):
            context = copy_context()
            return lambda *call_args, **call_kwargs: context.run(call, *call_args, **call_kwargs)
    lifetime = _lifetime.get()
    if lifetime is None:
        return executor.submit(propagate(fn), *args, **kwargs)
    ticket = lifetime._reserve()  # Held before any worker can start.
    def tracked():
        lifetime._start(ticket)
        token = _worker.set((lifetime, ticket))
        try:
            return fn(*args, **kwargs)
        finally:
            _worker.reset(token)
            lifetime._returned(ticket)
    try:
        future = executor.submit(propagate(tracked))
    except BaseException:
        lifetime._submission_unknown(ticket)
        raise
    lifetime._attach(ticket, future)
    return future


def start_writer_observed_thread(thread):
    """Observe a native title thread through join; preserve its target/profile context.

    This observes an existing dedicated callback, not a new managed tool context.
    External side effects are not settled by a successful thread join.
    """
    lifetime = _lifetime.get()
    if lifetime is None:
        thread.start()
        return
    if type(thread) is not threading.Thread or thread.ident is not None:
        raise RuntimeError('An unstarted native thread is required')
    ticket = lifetime._reserve('background')
    future = Future()
    lifetime._attach(ticket, future)
    lifetime._start(ticket)
    def observe():
        try:
            thread.join()  # Includes native target cleanup and threading exception handling.
        except BaseException:
            with lifetime._lock:
                record = lifetime._pending.get(ticket)
                if record:
                    record.update(mode='unknown', state='unknown')
            return
        lifetime._returned(ticket)
        future.set_result(None)
    try:
        thread.start()
        threading.Thread(target=observe, daemon=True, name='mesh-background-observer').start()
    except BaseException:
        with lifetime._lock:
            record = lifetime._pending.get(ticket)
            if record:
                record.update(mode='unknown', state='unknown')
        raise  # An uncertain start/observer never authorizes a retry or release.


@contextmanager
def bind_writer_fence(fence):
    if not callable(getattr(fence, 'popen', None)):
        raise ValueError('A server-owned process fence is required')
    if _current.get() is not None and _current.get() is not fence:
        raise RuntimeError('Cannot replace another attempt in the same context')
    token = _current.set(fence)
    try:
        yield
    finally:
        _current.reset(token)


def require_supported_writer_route(*, local, use_pty=False, persist_on_release=False):
    if _lifetime.get() is not None:
        _lifetime.get().assert_current_worker()
    if _current.get() is not None and (not local or use_pty or persist_on_release):
        raise RuntimeError('Scoped writer requires a local pipe route without retained background work')


def require_writer_local_environment(environment, active_environment=_unspecified_environment):
    """Reject remote/plugin or mismatched cached file backends in an enrolled call."""
    if _current.get() is None:
        return
    if _lifetime.get() is not None:
        _lifetime.get().assert_current_worker()
    from tools.environments.local import LocalEnvironment
    if type(environment) is not LocalEnvironment:
        raise RuntimeError('Scoped file tools require the native local environment')
    if active_environment is not _unspecified_environment and environment is not active_environment:
        raise RuntimeError('Cached file environment no longer matches the active environment')


def scoped_popen(argv, **kwargs):
    fence = _current.get()
    if fence is None:
        return subprocess.Popen(argv, **kwargs)
    if _lifetime.get() is not None:
        _lifetime.get().assert_current_worker()
    if not isinstance(argv, (list, tuple)) or not argv or not isinstance(argv[0], str):
        raise ValueError('A qualified executable argument list is required')
    argv = list(argv)
    if not Path(argv[0]).is_absolute():
        if Path(argv[0]).name != argv[0]:
            raise ValueError('Relative executable paths are unavailable')
        # Use the host PATH, not caller-supplied child environment/PATH.
        executable = shutil.which(argv[0])
        if not executable:
            raise RuntimeError('Configured local executable is unavailable')
        argv[0] = str(Path(executable).resolve())
    return fence.popen(argv, **kwargs)  # Failure never falls back to an unfenced launch.
