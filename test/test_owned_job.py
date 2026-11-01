import ctypes as C
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

from lib import owned_job as oj


class _CloseFailure:
    def __init__(self, real):
        self.real = real
        self.handles = {}
        self.closed = set()
        self.attempts = []
        self.injected = False

    def __getattr__(self, name):
        return getattr(self.real, name)

    def CreateJobObjectW(self, *args):
        handle = self.real.CreateJobObjectW(*args)
        if handle:
            self.handles['job'] = handle
        return handle

    def CreateProcessW(self, *args):
        ok = self.real.CreateProcessW(*args)
        info = C.cast(args[-1], C.POINTER(oj._ProcessInfo)).contents
        for name, handle in (('thread', info.hThread), ('process', info.hProcess)):
            if handle:
                self.handles[name] = handle
        return ok

    def CloseHandle(self, handle):
        self.attempts.append(handle)
        if handle == self.handles.get('thread') and not self.injected:
            self.injected = True
            C.set_last_error(5)
            return 0
        ok = self.real.CloseHandle(handle)
        if ok:
            self.closed.add(handle)
        return ok


@unittest.skipUnless(sys.platform == 'win32', 'Windows-only native ownership tests')
class OwnedJobTests(unittest.TestCase):
    def setUp(self):
        self.cwd = str(Path.cwd())
        self.api = oj._Win32()

    def command(self, code, *args):
        return [sys.executable, '-I', '-c', code, *map(str, args)]

    def assert_clean(self, result):
        self.assertTrue(result['cleanupVerified'], result)
        self.assertIsInstance(result['rootPid'], int)

    def handle_count(self):
        pseudo = self.api.GetCurrentProcess()
        self.assertTrue(pseudo)
        count = oj.DWORD()
        self.assertTrue(self.api.GetProcessHandleCount(pseudo, C.byref(count)))
        # GetCurrentProcess returns a borrowed pseudo-handle.
        return count.value

    def dispose_process(self, handle):
        failures = []
        try:
            state = self.api.WaitForSingleObject(handle, 0)
            if state == 258:
                if not self.api.TerminateProcess(handle, 1):
                    failures.append('fixture TerminateProcess failed')
                state = self.api.WaitForSingleObject(handle, 3000)
            if state != 0:
                failures.append('fixture process wait failed')
        finally:
            if not self.api.CloseHandle(handle):
                failures.append('fixture process CloseHandle failed')
        self.assertEqual(failures, [])

    def recover_handles(self, proxy):
        # Only exact handles acquired by this invocation are eligible.
        remaining = {name: handle for name, handle in proxy.handles.items()
                     if handle not in proxy.closed}
        failures = []
        job = remaining.get('job')
        try:
            if job:
                if not self.api.TerminateJobObject(job, 1):
                    failures.append('fixture TerminateJobObject failed')
                end = time.monotonic() + 3
                while True:
                    info = oj._Accounting()
                    used = oj.DWORD()
                    ok = self.api.QueryInformationJobObject(
                        job, 1, C.byref(info), C.sizeof(info), C.byref(used))
                    if not ok or used.value != C.sizeof(info):
                        failures.append('fixture job query failed')
                        break
                    if info.ActiveProcesses == 0:
                        break
                    if time.monotonic() >= end:
                        failures.append('fixture job wait exceeded allowance')
                        break
                    time.sleep(0.02)
            process = remaining.get('process')
            if process:
                state = self.api.WaitForSingleObject(process, 0)
                if state == 258:
                    if not self.api.TerminateProcess(process, 1):
                        failures.append('fixture root termination failed')
                    state = self.api.WaitForSingleObject(process, 3000)
                if state != 0:
                    failures.append('fixture root wait failed')
        finally:
            for name in ('thread', 'process', 'job'):
                handle = remaining.get(name)
                if handle and not self.api.CloseHandle(handle):
                    failures.append('fixture ' + name + ' close failed')
        self.assertEqual(failures, [])

    def test_normal_root_exit_zero(self):
        result = oj.run_owned(self.command('pass'), self.cwd, 2)
        self.assert_clean(result)
        self.assertEqual(result['status'], 'PASS', result)
        self.assertEqual(result['rootExitCode'], 0)
        self.assertFalse(result['timedOut'])
        self.assertIsNone(result['error'])

    def test_root_deadline(self):
        start = time.monotonic()
        result = oj.run_owned(self.command('import time; time.sleep(10)'), self.cwd, 0.3)
        self.assertLess(time.monotonic() - start, 4.5)
        self.assert_clean(result)
        self.assertEqual(result['status'], 'FAIL')
        self.assertTrue(result['timedOut'])
        self.assertIsInstance(result['rootExitCode'], int)

    def test_descendant_exit_proven_by_retained_handle(self):
        directory = Path(tempfile.mkdtemp(prefix='owned-job-retained-'))
        pid_file = directory / 'descendant.pid'
        gate = directory / 'root-exit.gate'
        code = (
            'import subprocess,sys,pathlib,time\n'
            "p=subprocess.Popen([sys.executable,'-I','-c','import time; time.sleep(20)'])\n"
            "pathlib.Path(sys.argv[1]).write_text(str(p.pid), encoding='ascii')\n"
            'while not pathlib.Path(sys.argv[2]).exists(): time.sleep(.01)\n'
        )
        results = []
        handle = None
        worker = threading.Thread(
            target=lambda: results.append(oj.run_owned(
                self.command(code, pid_file, gate), self.cwd, 4)), daemon=True)
        worker.start()
        try:
            end = time.monotonic() + 2.5
            pid = None
            while time.monotonic() < end:
                try:
                    pid = int(pid_file.read_text(encoding='ascii'))
                    break
                except (OSError, ValueError):
                    time.sleep(0.01)
            self.assertIsNotNone(pid, 'descendant identity was not published')
            # Root waits at the gate and retains Popen's process handle.
            handle = self.api.OpenProcess(0x00100000 | 0x1000 | 1, False, pid)
            self.assertTrue(handle, 'retaining descendant process handle failed')
            self.assertEqual(self.api.WaitForSingleObject(handle, 0), 258)
            gate.touch()
            worker.join(8)
            self.assertFalse(worker.is_alive())
            self.assertEqual(len(results), 1)
            self.assert_clean(results[0])
            self.assertEqual(results[0]['status'], 'PASS', results[0])
            self.assertEqual(results[0]['rootExitCode'], 0)
            self.assertFalse(results[0]['timedOut'])
            # This is independent evidence; accounting alone is insufficient.
            self.assertEqual(self.api.WaitForSingleObject(handle, 0), 0)
        finally:
            try:
                gate.touch()
            finally:
                worker.join(8)
                if handle:
                    self.dispose_process(handle)
            self.assertFalse(worker.is_alive(), 'owned worker did not finish')
        # Artifacts intentionally remain available for inspection.

    def test_nonexistent_executable_no_handle_leak(self):
        directory = Path(tempfile.mkdtemp(prefix='owned-job-missing-'))
        missing = directory / 'does-not-exist.exe'
        # The first failed CreateProcessW call initializes persistent Windows
        # runtime handles. Prime that native path directly, so the first owned
        # invocation still has to satisfy the exact before/after leak assertion.
        startup = oj._Startup()
        startup.cb = C.sizeof(startup)
        info = oj._ProcessInfo()
        command = C.create_unicode_buffer('"' + str(missing) + '"')
        self.assertFalse(self.api.CreateProcessW(
            str(missing), command, None, None, False, 0x4 | 0x08000000,
            None, self.cwd, C.byref(startup), C.byref(info)))
        self.assertEqual(self.api.last_error(), 2)
        self.assertIsNone(info.hProcess)
        self.assertIsNone(info.hThread)
        before = self.handle_count()
        result = oj.run_owned([str(missing)], self.cwd, 1)
        after = self.handle_count()
        self.assertEqual(result['status'], 'FAIL')
        self.assertIsNone(result['rootPid'])
        self.assertIsNone(result['rootExitCode'])
        self.assertFalse(result['timedOut'])
        self.assertTrue(result['cleanupVerified'], result)
        self.assertIn('CreateProcessW', result['error'])
        self.assertNotIn(str(missing), result['error'])
        self.assertEqual(after, before)

    def test_invalid_arguments_before_native_acquisition(self):
        class NoNativeCalls:
            def __getattr__(self, name):
                raise AssertionError('validation reached native API')

        good = self.command('pass')
        inputs = [(good, self.cwd, value) for value in
                  (0, -1, 31, float('nan'), float('inf'), True, '1')]
        inputs += [(value, self.cwd, 1) for value in
                   ([], [''], ['a\x00b'], ['a', None], ('a',))]
        inputs += [(good, '', 1), (good, self.cwd + '\x00', 1)]
        with oj._using_api(NoNativeCalls()):
            for argv, cwd, deadline in inputs:
                with self.subTest(argv=argv, cwd=cwd, deadline=deadline):
                    result = oj.run_owned(argv, cwd, deadline)
                    self.assertEqual(result['status'], 'FAIL')
                    self.assertEqual(result['error'], 'invalid arguments')
                    self.assertIsNone(result['rootPid'])
                    self.assertIsNone(result['rootExitCode'])
                    self.assertFalse(result['timedOut'])

    def test_acquired_thread_close_failure_cannot_pass(self):
        proxy = _CloseFailure(self.api)
        try:
            with oj._using_api(proxy):
                result = oj.run_owned(self.command('pass'), self.cwd, 2)
            self.assertTrue(proxy.injected)
            self.assertEqual(result['status'], 'FAIL')
            self.assertFalse(result['cleanupVerified'])
            self.assertEqual(result['rootExitCode'], 0)
            self.assertFalse(result['timedOut'])
            self.assertIn('CloseHandle: winerror 5', result['error'])
            self.assertEqual(set(proxy.handles), {'job', 'process', 'thread'})
            self.assertTrue(set(proxy.handles.values()) <= proxy.closed)
            self.assertEqual(proxy.attempts.count(proxy.handles['thread']), 2)
            self.assertIn(proxy.handles['process'], proxy.attempts)
            self.assertIn(proxy.handles['job'], proxy.attempts)
        finally:
            self.recover_handles(proxy)


if __name__ == '__main__':
    unittest.main()
