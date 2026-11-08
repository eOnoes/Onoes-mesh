"""Private Windows process-tree primitive; not an all-worker release authority.

Create suspended, assign to an unnamed non-breakaway Job, then resume. Only
processes launched by this object are affected. No PID scans or existing-process
attachment. WMI/service/broker launches and remote tools are outside this scope.
See https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects
"""
import ctypes
from ctypes import wintypes as w
from pathlib import Path
import re
import subprocess
import sys
import threading
import time


class _BasicLimits(ctypes.Structure):
    _fields_ = [("process_time", ctypes.c_longlong), ("job_time", ctypes.c_longlong),
                ("flags", w.DWORD), ("min_working_set", ctypes.c_size_t),
                ("max_working_set", ctypes.c_size_t), ("process_limit", w.DWORD),
                ("affinity", ctypes.c_size_t), ("priority", w.DWORD), ("scheduling", w.DWORD)]


class _IoCounters(ctypes.Structure):
    _fields_ = [(name, ctypes.c_ulonglong) for name in
                ("read_ops", "write_ops", "other_ops", "read_bytes", "write_bytes", "other_bytes")]


class _ExtendedLimits(ctypes.Structure):
    _fields_ = [("basic", _BasicLimits), ("io", _IoCounters),
                ("process_memory", ctypes.c_size_t), ("job_memory", ctypes.c_size_t),
                ("peak_process_memory", ctypes.c_size_t), ("peak_job_memory", ctypes.c_size_t)]


class _Accounting(ctypes.Structure):
    _fields_ = [(name, ctypes.c_longlong) for name in
                ("user_time", "kernel_time", "period_user_time", "period_kernel_time")] + [
                (name, w.DWORD) for name in ("page_faults", "total", "active", "terminated")]


class _Startup(ctypes.Structure):
    _fields_ = [("cb", w.DWORD), ("reserved", w.LPWSTR), ("desktop", w.LPWSTR),
                ("title", w.LPWSTR)] + [(name, w.DWORD) for name in
                ("x", "y", "x_size", "y_size", "x_chars", "y_chars", "fill", "flags")] + [
                ("show", w.WORD), ("reserved_size", w.WORD),
                ("reserved_bytes", ctypes.POINTER(w.BYTE)),
                ("stdin", w.HANDLE), ("stdout", w.HANDLE), ("stderr", w.HANDLE)]


class _Process(ctypes.Structure):
    _fields_ = [("process", w.HANDLE), ("thread", w.HANDLE), ("pid", w.DWORD), ("tid", w.DWORD)]


class _ThreadEntry(ctypes.Structure):
    _fields_ = [("size", w.DWORD), ("usage", w.DWORD), ("tid", w.DWORD),
                ("pid", w.DWORD), ("priority", w.LONG), ("delta", w.LONG), ("flags", w.DWORD)]


_kernel = None
if sys.platform == "win32":
    _kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    for name, args, result in [
        ("CreateJobObjectW", [w.LPVOID, w.LPCWSTR], w.HANDLE),
        ("SetInformationJobObject", [w.HANDLE, ctypes.c_int, w.LPVOID, w.DWORD], w.BOOL),
        ("QueryInformationJobObject", [w.HANDLE, ctypes.c_int, w.LPVOID, w.DWORD, w.LPVOID], w.BOOL),
        ("CreateProcessW", [w.LPCWSTR, w.LPWSTR, w.LPVOID, w.LPVOID, w.BOOL, w.DWORD,
                            w.LPVOID, w.LPCWSTR, ctypes.POINTER(_Startup), ctypes.POINTER(_Process)], w.BOOL),
        ("AssignProcessToJobObject", [w.HANDLE, w.HANDLE], w.BOOL),
        ("ResumeThread", [w.HANDLE], w.DWORD),
        ("WaitForSingleObject", [w.HANDLE, w.DWORD], w.DWORD),
        ("TerminateProcess", [w.HANDLE, w.UINT], w.BOOL),
        ("TerminateJobObject", [w.HANDLE, w.UINT], w.BOOL),
        ("CloseHandle", [w.HANDLE], w.BOOL),
        ("GetCurrentProcess", [], w.HANDLE),
        ("DuplicateHandle", [w.HANDLE, w.HANDLE, w.HANDLE, ctypes.POINTER(w.HANDLE),
                             w.DWORD, w.BOOL, w.DWORD], w.BOOL),
        ("CreateToolhelp32Snapshot", [w.DWORD, w.DWORD], w.HANDLE),
        ("Thread32First", [w.HANDLE, ctypes.POINTER(_ThreadEntry)], w.BOOL),
        ("Thread32Next", [w.HANDLE, ctypes.POINTER(_ThreadEntry)], w.BOOL),
        ("OpenThread", [w.DWORD, w.BOOL, w.DWORD], w.HANDLE),
        ("GetProcessIdOfThread", [w.HANDLE], w.DWORD),
    ]:
        fn = getattr(_kernel, name)
        fn.argtypes, fn.restype = args, result


def _check(result):
    if not result:
        raise ctypes.WinError(ctypes.get_last_error())
    return result


def _new_suspended_thread(pid):
    """Find only our newly created suspended root's unique initial thread.

    Popen closes its initial thread handle. Toolhelp is read-only; OpenThread is
    restricted to the exact new PID and ownership is checked again on the handle.
    Multiple threads or incomplete enumeration fail closed, never guess a thread.
    """
    snapshot = _kernel.CreateToolhelp32Snapshot(4, 0)
    if snapshot == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    matches = []
    try:
        entry = _ThreadEntry()
        entry.size = ctypes.sizeof(entry)
        _check(_kernel.Thread32First(snapshot, ctypes.byref(entry)))
        while True:
            if entry.size < _ThreadEntry.pid.offset + ctypes.sizeof(w.DWORD):
                raise OSError('Thread snapshot incomplete')
            if entry.pid == pid:
                matches.append(entry.tid)
            entry.size = ctypes.sizeof(entry)
            if not _kernel.Thread32Next(snapshot, ctypes.byref(entry)):
                if ctypes.get_last_error() != 18:  # ERROR_NO_MORE_FILES
                    raise ctypes.WinError(ctypes.get_last_error())
                break
    finally:
        _kernel.CloseHandle(snapshot)
    if len(matches) != 1:
        raise OSError('New suspended root thread is not unique')
    handle = _check(_kernel.OpenThread(0x0802, False, matches[0]))
    if _kernel.GetProcessIdOfThread(handle) != pid:
        _kernel.CloseHandle(handle)
        raise OSError('New root thread ownership changed')
    return handle


class WindowsWriterFence:
    """One attempt's owned process tree. Does not start a model or touch services."""
    def __init__(self, run_id, generation):
        if _kernel is None:
            raise RuntimeError("Windows process fencing is unavailable")
        if any(not isinstance(v, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", v)
               for v in (run_id, generation)):
            raise ValueError("Exact run and generation identities are required")
        self._run_id, self._generation = run_id, generation
        self._lock = threading.RLock()
        self._roots, self._failed_roots, self._failed_popen = [], [], []
        self._sealed, self._closed, self._termination = False, False, False
        self._job = _check(_kernel.CreateJobObjectW(None, None))
        limits = _ExtendedLimits()
        limits.basic.flags = 0x00002000  # KILL_ON_JOB_CLOSE; no breakaway flags.
        try:
            _check(_kernel.SetInformationJobObject(self._job, 9, ctypes.byref(limits), ctypes.sizeof(limits)))
        except BaseException:
            _kernel.CloseHandle(self._job)
            raise

    @property
    def run_id(self):
        return self._run_id

    @property
    def generation(self):
        return self._generation

    def launch(self, argv, *, cwd=None):
        with self._lock:
            if self._closed or self._sealed or self._failed_roots or self._failed_popen:
                raise RuntimeError("Attempt is sealed or closed")
            if not isinstance(argv, (list, tuple)) or not argv or any(
                    not isinstance(a, str) or "\0" in a for a in argv):
                raise ValueError("An explicit executable and argument list are required")
            if not Path(argv[0]).is_absolute() or not Path(argv[0]).is_file():
                raise ValueError("Executable must be an existing absolute file")
            command = subprocess.list2cmdline(argv)
            if len(command) > 32766:
                raise ValueError("Command line is too long")
            startup, process = _Startup(), _Process()
            startup.cb, startup.flags, startup.show = ctypes.sizeof(startup), 1, 0
            # No inherited handles, console window, job escape, or execution before containment.
            _check(_kernel.CreateProcessW(argv[0], ctypes.create_unicode_buffer(command), None, None,
                                         False, 0x08000004, None, str(cwd) if cwd else None,
                                         ctypes.byref(startup), ctypes.byref(process)))
            try:
                _check(_kernel.AssignProcessToJobObject(self._job, process.process))
                if _kernel.ResumeThread(process.thread) == 0xFFFFFFFF:
                    raise ctypes.WinError(ctypes.get_last_error())
                self._roots.append(process.process)
                return process.pid
            except BaseException:
                # Only our newly created, suspended helper; never an existing PID.
                # Keep its handle if cleanup is uncertain, so control is not lost.
                self._failed_roots.append(process.process)
                _check(_kernel.TerminateProcess(process.process, 1))
                if _kernel.WaitForSingleObject(process.process, 5000) != 0:
                    raise OSError('Newly created helper termination is unconfirmed')
                _check(_kernel.CloseHandle(process.process))
                self._failed_roots.remove(process.process)
                raise
            finally:
                _kernel.CloseHandle(process.thread)

    def popen(self, argv, *, cwd=None, env=None, stdin=subprocess.DEVNULL,
              stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=False,
              encoding=None, errors=None, start_new_session=False, creationflags=0):
        """Pipe-compatible launch for the native local-command path, without PTY/fallback.

        Return a real CPython Popen for its existing readers/stdin/poll/wait logic.
        The fence retains a separate process handle; caller handle lifetime cannot
        invalidate observation. Only hidden-console flags are accepted from callers.
        """
        with self._lock:
            if self._closed or self._sealed or self._failed_roots or self._failed_popen:
                raise RuntimeError('Attempt is sealed or cleanup is uncertain')
            if sys.implementation.name != 'cpython' or creationflags not in (0, 0x08000000):
                raise ValueError('Unsupported process implementation or creation flags')
            if not isinstance(argv, (list, tuple)) or not argv or any(
                    not isinstance(a, str) or '\0' in a for a in argv):
                raise ValueError('An explicit executable and argument list are required')
            if not Path(argv[0]).is_absolute() or not Path(argv[0]).is_file():
                raise ValueError('Executable must be an existing absolute file')
            proc = subprocess.Popen(argv, cwd=cwd, env=env, stdin=stdin, stdout=stdout,
                                    stderr=stderr, text=text, encoding=encoding, errors=errors,
                                    start_new_session=start_new_session, close_fds=True,
                                    creationflags=0x08000004)
            self._failed_popen.append(proc)  # Keep exact control until containment is confirmed.
            owned, thread = w.HANDLE(), None
            try:
                current = _kernel.GetCurrentProcess()
                _check(_kernel.DuplicateHandle(current, int(proc._handle), current,
                                              ctypes.byref(owned), 0, False, 2))
                if _kernel.WaitForSingleObject(owned, 0) != 258:
                    raise OSError('New suspended process is no longer running')
                thread = _new_suspended_thread(proc.pid)
                _check(_kernel.AssignProcessToJobObject(self._job, owned))
                if _kernel.ResumeThread(thread) != 1:
                    raise OSError('New root suspension state changed')
                self._roots.append(owned.value)
                self._failed_popen.remove(proc)
                return proc
            except BaseException:
                self._cleanup_popen(proc)
                self._failed_popen.remove(proc)
                raise
            finally:
                if thread:
                    _kernel.CloseHandle(thread)
                if owned.value and owned.value not in self._roots:
                    _kernel.CloseHandle(owned)

    @staticmethod
    def _cleanup_popen(proc):
        if proc.poll() is None:
            proc.terminate()  # Popen's retained exact handle, never a scanned PID.
        proc.wait(timeout=5)
        for pipe in (proc.stdin, proc.stdout, proc.stderr):
            if pipe is not None:
                pipe.close()

    def seal(self):
        with self._lock:
            if self._closed:
                raise RuntimeError("Attempt is closed")
            self._sealed = True

    def _active_count(self):
        info = _Accounting()
        _check(_kernel.QueryInformationJobObject(self._job, 1, ctypes.byref(info), ctypes.sizeof(info), None))
        return int(info.active)

    def snapshot(self):
        with self._lock:
            base = {"schema": "mesh-writer-process-tree/v1", "runId": self.run_id,
                    "generation": self.generation, "coverage": "windows_job_members",
                    "sealed": self._sealed, "terminationRequested": self._termination,
                    "writerQuiescence": False, "processTreeEnded": False}
            if self._closed:
                return {**base, "state": "unknown", "reason": "fence_closed"}
            if self._failed_roots or self._failed_popen:
                return {**base, "state": "unknown", "reason": "failed_launch_cleanup_unconfirmed"}
            try:
                active = self._active_count()
                roots = [_kernel.WaitForSingleObject(handle, 0) for handle in self._roots]
                if any(value not in (0, 258) for value in roots):
                    raise OSError("Root process observation unavailable")
                ended = bool(roots) and self._sealed and active == 0 and all(value == 0 for value in roots)
                return {**base, "state": "ended" if ended else "held" if roots else "not_started", "activeProcesses": active,
                        "allRootsEnded": bool(roots) and all(value == 0 for value in roots),
                        "processTreeEnded": ended}
            except OSError:
                return {**base, "state": "unknown", "reason": "process_observation_unavailable"}

    def wait(self, timeout_ms=5000):
        if not isinstance(timeout_ms, int) or not 0 <= timeout_ms <= 60000:
            raise ValueError("A bounded wait is required")
        deadline = time.monotonic() + timeout_ms / 1000
        while True:
            result = self.snapshot()
            if result["state"] in ("ended", "unknown", "not_started") or time.monotonic() >= deadline:
                return result
            time.sleep(min(0.02, max(0, deadline - time.monotonic())))

    def terminate(self):
        """Explicitly stop this object's owned tree only; not a success/ retry decision."""
        with self._lock:
            if self._closed:
                raise RuntimeError("Attempt is closed")
            self._sealed, self._termination = True, True
            _check(_kernel.TerminateJobObject(self._job, 1))
            for proc in self._failed_popen[:]:
                self._cleanup_popen(proc)
                self._failed_popen.remove(proc)
            for handle in self._failed_roots[:]:
                if _kernel.WaitForSingleObject(handle, 0) != 0:
                    _check(_kernel.TerminateProcess(handle, 1))
                    if _kernel.WaitForSingleObject(handle, 5000) != 0:
                        raise OSError('Failed launch termination is unconfirmed')
                _check(_kernel.CloseHandle(handle))
                self._failed_roots.remove(handle)
        return self.wait()

    def close(self):
        with self._lock:
            if self._closed:
                return
            if self._failed_roots or self._failed_popen:
                raise RuntimeError('Failed launch cleanup remains unconfirmed')
            if self._active_count():
                raise RuntimeError("Owned processes remain; wait or explicitly terminate this tree")
            while self._roots:
                _check(_kernel.CloseHandle(self._roots[-1]))
                self._roots.pop()
            _check(_kernel.CloseHandle(self._job))
            self._closed = True
