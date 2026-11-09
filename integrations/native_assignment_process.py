"""Assignment-owned process observation; never a whole-writer clearance receipt."""
import os
import re
import threading


class AssignmentProcessScope:
    def __init__(self, authority, ref, row, *, fence_factory=None):
        admission = row.get('admission_id')
        generation = row.get('generation')
        if (not isinstance(admission, str) or not re.fullmatch('[a-f0-9]{32}', admission)
                or type(generation) is not int or generation < 1
                or not isinstance(row.get('principal_id'), str) or not row['principal_id']):
            raise ValueError('Exact native assignment identity is required')
        if fence_factory is None:
            from integrations.windows_writer_fence import WindowsWriterFence
            fence_factory = WindowsWriterFence
        self.identity = dict(admissionId=admission, sessionId=ref.session_id,
                             profileId=str(authority.profile_id), principalId=row['principal_id'],
                             executionGeneration=generation)
        self.fence = fence_factory(admission, str(generation))
        self.lock = threading.RLock()
        self.sealed = False
        self.launched = False
        self.fault = False
        self.cached = None

    def popen(self, argv, **kwargs):
        with self.lock:
            if self.sealed or self.launched or self.fault:
                raise RuntimeError('Native assignment launch is sealed or already reserved')
            if kwargs.pop('close_fds', True) is not True:
                raise ValueError('Native assignment must close unrelated handles')
            # Reserve the only root before launch. Failure cannot authorize another root.
            self.launched = True
            try:
                return self.fence.popen(argv, **kwargs)
            except BaseException:
                self.fault = True
                raise

    def retire(self):
        # Serialize with a factory still running in acquire_process's background thread.
        # A factory that has not entered yet will reject after this seals the scope.
        with self.lock:
            if not self.sealed:
                self.sealed = True
                self.fence.seal()
            return self.observe()

    def observe(self):
        with self.lock:
            if self.cached is not None:
                return dict(self.cached)
            observed = self.fence.snapshot()
            result = {**observed, **self.identity, 'assignmentLaunchSealed': self.sealed,
                      'writerQuiescence': False}
            if self.fault:
                result.update(state='unknown', processTreeEnded=False, reason='assignment_launch_failed')
            # A sealed empty Job cannot acquire new descendants; retain its immutable
            # observation before closing handles. No ordinary session is terminated.
            if not self.fault and self.sealed and observed['state'] in ('ended', 'not_started'):
                self.fence.close()
                self.cached = dict(result)
            return result

    def dispose(self):
        """Owner shutdown only; explicit termination is never natural completion."""
        with self.lock:
            if self.cached is not None:
                return dict(self.cached)
            self.sealed = True
            self.fence.seal()
            result = self.fence.terminate()
            self.fence.close()
            self.cached = {**result, **self.identity, 'assignmentLaunchSealed': True,
                           'writerQuiescence': False}
            return dict(self.cached)


def make_assignment_scope(authority, ref, row):
    # Dedicated owner enrollment only. This module has no installer or public control.
    if os.environ.get('MESH_LOCAL_PROCESS_SCOPE') != '1':
        return None
    if os.name != 'nt':
        raise RuntimeError('This assignment process profile requires Windows')
    scopes = getattr(authority, '_mesh_assignment_processes', None)
    if scopes is None:
        scopes = authority._mesh_assignment_processes = {}
    if row['admission_id'] in scopes:
        raise RuntimeError('The native admission already owns a process scope')
    scope = AssignmentProcessScope(authority, ref, row)
    scopes[row['admission_id']] = scope
    return scope
