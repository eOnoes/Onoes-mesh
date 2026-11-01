import ctypes as C
import math
import os
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path

DWORD = C.c_uint32
BOOL = C.c_int32
HANDLE = C.c_void_p
SIZE_T = C.c_size_t


class _Startup(C.Structure):
    _fields_ = [
        ('cb', DWORD), ('lpReserved', C.c_wchar_p),
        ('lpDesktop', C.c_wchar_p), ('lpTitle', C.c_wchar_p),
        ('dwX', DWORD), ('dwY', DWORD), ('dwXSize', DWORD),
        ('dwYSize', DWORD), ('dwXCountChars', DWORD),
        ('dwYCountChars', DWORD), ('dwFillAttribute', DWORD),
        ('dwFlags', DWORD), ('wShowWindow', C.c_uint16),
        ('cbReserved2', C.c_uint16), ('lpReserved2', C.c_void_p),
        ('hStdInput', HANDLE), ('hStdOutput', HANDLE),
        ('hStdError', HANDLE),
    ]


class _ProcessInfo(C.Structure):
    _fields_ = [('hProcess', HANDLE), ('hThread', HANDLE),
                ('dwProcessId', DWORD), ('dwThreadId', DWORD)]


class _StartupEx(C.Structure):
    _fields_ = [('StartupInfo', _Startup), ('lpAttributeList', C.c_void_p)]


class _BasicLimits(C.Structure):
    _fields_ = [
        ('PerProcessUserTimeLimit', C.c_int64),
        ('PerJobUserTimeLimit', C.c_int64), ('LimitFlags', DWORD),
        ('MinimumWorkingSetSize', SIZE_T),
        ('MaximumWorkingSetSize', SIZE_T), ('ActiveProcessLimit', DWORD),
        ('Affinity', SIZE_T), ('PriorityClass', DWORD),
        ('SchedulingClass', DWORD),
    ]


class _IO(C.Structure):
    _fields_ = [(name, C.c_uint64) for name in (
        'ReadOperationCount', 'WriteOperationCount', 'OtherOperationCount',
        'ReadTransferCount', 'WriteTransferCount', 'OtherTransferCount')]


class _ExtendedLimits(C.Structure):
    _fields_ = [
        ('BasicLimitInformation', _BasicLimits), ('IoInfo', _IO),
        ('ProcessMemoryLimit', SIZE_T), ('JobMemoryLimit', SIZE_T),
        ('PeakProcessMemoryUsed', SIZE_T), ('PeakJobMemoryUsed', SIZE_T),
    ]


class _Accounting(C.Structure):
    _fields_ = [
        ('TotalUserTime', C.c_int64), ('TotalKernelTime', C.c_int64),
        ('ThisPeriodTotalUserTime', C.c_int64),
        ('ThisPeriodTotalKernelTime', C.c_int64),
        ('TotalPageFaultCount', DWORD), ('TotalProcesses', DWORD),
        ('ActiveProcesses', DWORD), ('TotalTerminatedProcesses', DWORD),
    ]


class _Win32:
    def __init__(self):
        if sys.platform != 'win32':
            raise RuntimeError('Windows required')
        wide = C.sizeof(HANDLE) == 8
        expected = (104, 24, 144, 48) if wide else (68, 16, 112, 48)
        actual = tuple(C.sizeof(t) for t in (
            _Startup, _ProcessInfo, _ExtendedLimits, _Accounting))
        if actual != expected:
            raise RuntimeError('native layout mismatch')
        self._dll = C.WinDLL('kernel32', use_last_error=True)
        signatures = {
            'CreateJobObjectW': (HANDLE, [C.c_void_p, C.c_wchar_p]),
            'SetInformationJobObject': (BOOL, [HANDLE, C.c_int, C.c_void_p, DWORD]),
            'QueryInformationJobObject': (BOOL, [HANDLE, C.c_int, C.c_void_p, DWORD, C.POINTER(DWORD)]),
            'CreateProcessW': (BOOL, [C.c_wchar_p, C.POINTER(C.c_wchar), C.c_void_p, C.c_void_p, BOOL, DWORD, C.c_void_p, C.c_wchar_p, C.POINTER(_Startup), C.POINTER(_ProcessInfo)]),
            'AssignProcessToJobObject': (BOOL, [HANDLE, HANDLE]),
            'ResumeThread': (DWORD, [HANDLE]),
            'WaitForSingleObject': (DWORD, [HANDLE, DWORD]),
            'GetExitCodeProcess': (BOOL, [HANDLE, C.POINTER(DWORD)]),
            'TerminateJobObject': (BOOL, [HANDLE, DWORD]),
            'TerminateProcess': (BOOL, [HANDLE, DWORD]),
            'CloseHandle': (BOOL, [HANDLE]),
            'OpenProcess': (HANDLE, [DWORD, BOOL, DWORD]),
            'IsProcessInJob': (BOOL, [HANDLE, HANDLE, C.POINTER(BOOL)]),
            'GetCurrentProcess': (HANDLE, []),
            'GetProcessHandleCount': (BOOL, [HANDLE, C.POINTER(DWORD)]),
            'InitializeProcThreadAttributeList': (BOOL, [C.c_void_p, DWORD, DWORD, C.POINTER(SIZE_T)]),
            'UpdateProcThreadAttribute': (BOOL, [C.c_void_p, DWORD, SIZE_T, C.c_void_p, SIZE_T, C.c_void_p, C.c_void_p]),
            'DeleteProcThreadAttributeList': (None, [C.c_void_p]),
        }
        for name, (result, args) in signatures.items():
            fn = getattr(self._dll, name)
            fn.restype = result
            fn.argtypes = args
            setattr(self, name, fn)

    def last_error(self):
        return C.get_last_error()


_override = ContextVar('owned_job_native_override', default=None)


@contextmanager
def _using_api(api):
    token = _override.set(api)
    try:
        yield
    finally:
        _override.reset(token)


def run_owned(argv: list[str], cwd: str, timeout_seconds: float, *, capture_output=False, cancel_requested=None) -> dict:
    if not capture_output:
        return _run_owned(argv, cwd, timeout_seconds, cancel_requested=cancel_requested)
    # Seekable files avoid pipe deadlocks. The exact three handles are inherited
    # through STARTUPINFOEX; job assignment still precedes the first instruction.
    result = dict(status='FAIL', rootPid=None, rootExitCode=None,
                  timedOut=False, cleanupVerified=False, error='capture unavailable',
                  stdout='', stderr='')
    if sys.platform != 'win32':
        result['error'] = 'Windows required'
        return result
    import msvcrt
    try:
        with open(os.devnull, 'rb') as stdin, tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
            handles = [msvcrt.get_osfhandle(f.fileno()) for f in (stdin, stdout, stderr)]
            for handle in handles:
                os.set_handle_inheritable(handle, True)
            result = _run_owned(argv, cwd, timeout_seconds, _capture_handles=handles, cancel_requested=cancel_requested)
            stdout.seek(0); stderr.seek(0)
            result['stdout'] = stdout.read().decode('utf-8', errors='replace')
            result['stderr'] = stderr.read().decode('utf-8', errors='replace')
    except Exception:
        result.update(status='FAIL', cleanupVerified=False, error='capture operation failed')
    return result


def _run_owned(argv: list[str], cwd: str, timeout_seconds: float, *, _capture_handles=None, cancel_requested=None) -> dict:
    result = dict(status='FAIL', rootPid=None, rootExitCode=None,
                  timedOut=False, cleanupVerified=False, error=None)
    try:
        valid = (
            isinstance(argv, list) and bool(argv)
            and all(isinstance(s, str) and bool(s) and '\x00' not in s for s in argv)
            and isinstance(cwd, str) and bool(cwd) and '\x00' not in cwd
            and Path(cwd).is_dir()
            and isinstance(timeout_seconds, (int, float))
            and not isinstance(timeout_seconds, bool)
            and math.isfinite(timeout_seconds)
            and 0 < timeout_seconds <= 30
            and (cancel_requested is None or callable(cancel_requested))
        )
    except Exception:
        valid = False
    if not valid:
        result['error'] = 'invalid arguments'
        return result
    if sys.platform != 'win32':
        result['error'] = 'Windows required'
        return result

    errors = []
    cleaning = False
    cleanup_bad = False
    api = None
    job = process = thread = None
    assigned = False
    zero = False
    root_done = False
    members = []
    member_handles = []
    attributes = None
    attributes_initialized = False
    deadline = time.monotonic() + timeout_seconds

    def fail(message):
        nonlocal cleanup_bad
        if cleaning:
            cleanup_bad = True
        if message not in errors:
            errors.append(message)

    class Cancelled(Exception):
        pass

    def check_cancel():
        if cancel_requested is None:
            return False
        try:
            requested = bool(cancel_requested())
        except Exception:
            fail('cancellation check raised')
            requested = True  # Fail closed, retaining native cleanup custody.
        if requested:
            result['cancelled'] = True
            fail('execution cancelled')
        return requested

    def cancellation_point():
        if check_cancel():
            raise Cancelled()

    def native_error(name):
        try:
            code = int(api.last_error())
        except Exception:
            fail(name + ': last-error retrieval failed')
            return
        fail(name + ': winerror ' + str(code))

    def call(name, *args):
        try:
            return getattr(api, name)(*args)
        except Exception:
            fail(name + ': native call raised')
            return None

    def boolean(name, *args):
        value = call(name, *args)
        if not value:
            native_error(name)
            return False
        return True

    def wait(handle, milliseconds):
        value = call('WaitForSingleObject', handle, milliseconds)
        if value == 0 or value == 258:
            return value
        if value == 0xffffffff:
            native_error('WaitForSingleObject')
        elif value is not None:
            fail('WaitForSingleObject: unexpected result')
        return None

    def exit_code():
        code = DWORD()
        if boolean('GetExitCodeProcess', process, C.byref(code)):
            result['rootExitCode'] = int(code.value)

    def active():
        info = _Accounting()
        used = DWORD()
        if not boolean('QueryInformationJobObject', job, 1, C.byref(info),
                       C.sizeof(info), C.byref(used)):
            return None
        if used.value != C.sizeof(info):
            fail('QueryInformationJobObject: incorrect result size')
            return None
        return int(info.ActiveProcesses)

    def retain_members():
        # Accounting can reach zero before terminated processes are signaled.
        # Retain exact process objects before termination, checking job membership
        # so a reused PID cannot become cleanup evidence for this invocation.
        capacity = 16
        while time.monotonic() < cleanup_end:
            class ProcessIds(C.Structure):
                _fields_ = [('assigned', DWORD), ('count', DWORD),
                            ('pids', SIZE_T * capacity)]

            info = ProcessIds()
            used = DWORD()
            ok = call('QueryInformationJobObject', job, 3, C.byref(info),
                      C.sizeof(info), C.byref(used))
            if not ok:
                if ok is not None and api.last_error() == 234:
                    capacity = max(capacity * 2, info.assigned)
                    continue
                native_error('QueryInformationJobObject')
                return
            if info.count > capacity or info.count < info.assigned:
                fail('QueryInformationJobObject: incomplete process list')
                return
            for pid in info.pids[:info.count]:
                if pid == result['rootPid']:
                    continue  # The root process handle is already retained.
                handle = call('OpenProcess', 0x00100000 | 0x1000, False, pid)
                if not handle:
                    native_error('OpenProcess')
                    continue
                member_handles.append(handle)
                belongs = BOOL()
                if boolean('IsProcessInJob', handle, job, C.byref(belongs)):
                    if belongs.value:
                        members.append(handle)
                    else:
                        fail('job member identity changed')
            return
        fail('job member acquisition allowance exceeded')

    def close(handle):
        if not handle:
            return True
        for unused in range(2):
            if boolean('CloseHandle', handle):
                return True
        return False

    try:
        api = _override.get()
        if api is None:
            api = _Win32()
        job = call('CreateJobObjectW', None, None)
        if not job:
            native_error('CreateJobObjectW')
        else:
            limits = _ExtendedLimits()
            limits.BasicLimitInformation.LimitFlags = 0x2000
            configured = boolean('SetInformationJobObject', job, 9,
                                 C.byref(limits), C.sizeof(limits))
            if configured:
                cancellation_point()
                startup = _Startup()
                startup.cb = C.sizeof(startup)
                flags = 0x4 | 0x08000000
                if _capture_handles is not None:
                    size = SIZE_T()
                    call('InitializeProcThreadAttributeList', None, 1, 0, C.byref(size))
                    if not size.value:
                        raise RuntimeError('capture attributes unavailable')
                    attributes = C.create_string_buffer(size.value)
                    if not boolean('InitializeProcThreadAttributeList', attributes, 1, 0, C.byref(size)):
                        raise RuntimeError('capture attributes unavailable')
                    attributes_initialized = True
                    inherited = (HANDLE * 3)(*_capture_handles)
                    if not boolean('UpdateProcThreadAttribute', attributes, 0, 0x20002,
                                   C.byref(inherited), C.sizeof(inherited), None, None):
                        raise RuntimeError('capture handle list unavailable')
                    extended = _StartupEx()
                    extended.StartupInfo.cb = C.sizeof(extended)
                    extended.StartupInfo.dwFlags = 0x100
                    extended.StartupInfo.hStdInput, extended.StartupInfo.hStdOutput, extended.StartupInfo.hStdError = _capture_handles
                    extended.lpAttributeList = C.cast(attributes, C.c_void_p)
                    startup = extended
                    flags |= 0x80000
                pi = _ProcessInfo()
                command = C.create_unicode_buffer(subprocess.list2cmdline(argv))
                created = boolean('CreateProcessW', argv[0], command, None, None,
                                  _capture_handles is not None, flags, None, cwd,
                                  C.cast(C.byref(startup), C.POINTER(_Startup)), C.byref(pi))
                process, thread = pi.hProcess, pi.hThread
                if created:
                    result['rootPid'] = int(pi.dwProcessId)
                    if not process or not thread or not pi.dwProcessId:
                        fail('CreateProcessW: incomplete acquisition')
                    else:
                        assigned = boolean('AssignProcessToJobObject', job, process)
                        if assigned:
                            cancellation_point()
                            resumed = call('ResumeThread', thread)
                            if resumed == 0xffffffff:
                                native_error('ResumeThread')
                            elif resumed != 1:
                                fail('ResumeThread: unexpected suspend count')
                            else:
                                while True:
                                    cancellation_point()
                                    state = wait(process, 0)
                                    if state == 0:
                                        root_done = True
                                        exit_code()
                                        break
                                    if state is None:
                                        break
                                    remaining = deadline - time.monotonic()
                                    if remaining <= 0:
                                        result['timedOut'] = True
                                        fail('execution deadline exceeded')
                                        break
                                    state = wait(process, max(1, min(50, int(remaining * 1000))))
                                    if state == 0:
                                        root_done = True
                                        exit_code()
                                        break
                                    if state is None:
                                        break
    except Cancelled:
        pass
    except Exception:
        fail('owned operation raised')
    finally:
        cleaning = True
        cleanup_end = time.monotonic() + 3.0
        try:
            if job:
                count = active()
                if count != 0:
                    retain_members()
                    for unused in range(2):
                        if boolean('TerminateJobObject', job, 1):
                            break
                    while True:
                        count = active()
                        if count == 0:
                            break
                        remaining = cleanup_end - time.monotonic()
                        if remaining <= 0:
                            fail('job cleanup allowance exceeded')
                            break
                        time.sleep(min(0.02, remaining))
                zero = count == 0
            for handle in members:
                remaining_ms = max(0, int((cleanup_end - time.monotonic()) * 1000))
                if wait(handle, remaining_ms) != 0:
                    fail('job member cleanup not verified')
            if process:
                state = wait(process, 0)
                if state == 258 and not assigned:
                    for unused in range(2):
                        if boolean('TerminateProcess', process, 1):
                            break
                if state != 0:
                    remaining_ms = max(0, int((cleanup_end - time.monotonic()) * 1000))
                    state = wait(process, remaining_ms)
                root_done = state == 0
                if root_done:
                    if result['rootExitCode'] is None:
                        exit_code()
                else:
                    fail('root cleanup not verified')
        except Exception:
            fail('cleanup raised')
        finally:
            if attributes_initialized:
                call('DeleteProcThreadAttributeList', attributes)
            # Job custody ends last. Every failed close remains an error,
            # even when its one bounded retry succeeds.
            members_closed = True
            for handle in member_handles:
                if not close(handle):
                    members_closed = False
            thread_closed = close(thread)
            process_closed = close(process)
            job_closed = close(job)
            result['cleanupVerified'] = bool(
                job and zero and (not process or root_done)
                and members_closed and thread_closed and process_closed and job_closed
                and not cleanup_bad)

    cleaning = False
    check_cancel()  # A cancellation racing root exit/cleanup cannot become PASS.
    if process and result['rootExitCode'] not in (None, 0):
        fail('root exited with nonzero code')
    if not result['cleanupVerified']:
        fail('cleanup not verified')
    if not errors and not result['timedOut'] and result['rootExitCode'] == 0:
        result['status'] = 'PASS'
    result['error'] = '; '.join(errors) if errors else None
    return result
