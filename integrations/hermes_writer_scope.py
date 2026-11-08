"""Candidate native tools.mesh_writer_scope; no HTTP/config enrollment or release grant."""
from contextlib import contextmanager
from contextvars import ContextVar, copy_context
from concurrent.futures import Future
from pathlib import Path
import shutil
import subprocess
import threading
import time
from uuid import uuid4

_current = ContextVar('mesh_owned_writer_fence', default=None)
_lifetime = ContextVar('mesh_writer_lifetime', default=None)
_worker = ContextVar('mesh_owned_worker_ticket', default=None)


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

    def assert_current_worker(self):
        with self._lock:
            owner = _worker.get()
            record = self._pending.get(owner[1]) if owner and owner[0] is self else None
            if _lifetime.get() is not self or not record or record['state'] != 'running':
                raise RuntimeError('This worker context is no longer active')

    def _reserve(self):
        with self._lock:
            self.assert_current_worker()
            ticket = str(uuid4())
            self._pending[ticket] = {'kind': 'delegate', 'state': 'reserved', 'started': False, 'mode': 'submitting'}
            return ticket

    def _start(self, ticket):
        with self._lock:
            record = self._pending.get(ticket)
            if not record or record['started']:
                raise RuntimeError('Worker admission is missing or already consumed')
            record.update(started=True, state='running')

    def _maybe_seal(self):
        if self._root_ended and not self._pending and not self._sealed:
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
            managed = (self._root_ended and not self._pending and self._sealed and not self._fault
                       and process.get('state') in ('ended', 'not_started') and process.get('activeProcesses') == 0)
            return {'schema': 'mesh-managed-writer-lifetime/v1', 'runId': self.fence.run_id,
                    'generation': self.fence.generation, 'rootEnded': self._root_ended,
                    'pendingWorkers': [{'id': key, 'kind': value['kind'], 'state': value['state']}
                                       for key, value in self._pending.items()],
                    'processTree': process, 'managedWorkEnded': managed,
                    'writerQuiescence': False, 'reason': self._fault,
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


def submit_writer_work(executor, fn, propagate=None):
    """Use the existing executor and its context propagator, not a new worker pool."""
    if propagate is None:
        def propagate(call):
            context = copy_context()
            return lambda: context.run(call)
    lifetime = _lifetime.get()
    if lifetime is None:
        return executor.submit(propagate(fn))
    ticket = lifetime._reserve()  # Held before any worker can start.
    def tracked():
        lifetime._start(ticket)
        token = _worker.set((lifetime, ticket))
        try:
            return fn()
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
