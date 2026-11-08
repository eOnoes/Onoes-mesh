"""Candidate native tools.mesh_writer_scope; no HTTP/config enrollment or release grant."""
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
import shutil
import subprocess

_current = ContextVar('mesh_owned_writer_fence', default=None)


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
    if _current.get() is not None and (not local or use_pty or persist_on_release):
        raise RuntimeError('Scoped writer requires a local pipe route without retained background work')


def scoped_popen(argv, **kwargs):
    fence = _current.get()
    if fence is None:
        return subprocess.Popen(argv, **kwargs)
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
