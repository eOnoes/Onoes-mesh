import ctypes as C
from pathlib import Path
import sys
import unittest

from lib import owned_job as oj
from test import test_owned_job as legacy


class OwnedCaptureTests(unittest.TestCase):
    def setUp(self):
        self.assertEqual(sys.platform, 'win32', 'Native Windows required; no skips')
        self.cwd = str(Path.cwd())
        self.api = oj._Win32()

    def run_code(self, code, timeout=2):
        return oj.run_owned([sys.executable, '-I', '-c', code], self.cwd, timeout, capture_output=True)

    def test_actual_stdout_stderr_and_nonzero(self):
        result = self.run_code("import sys; print('real stdout'); print('real stderr',file=sys.stderr); sys.exit(7)")
        self.assertEqual(result['stdout'], 'real stdout\r\n')
        self.assertEqual(result['stderr'], 'real stderr\r\n')
        self.assertEqual(result['rootExitCode'], 7)
        self.assertEqual(result['status'], 'FAIL')
        self.assertTrue(result['cleanupVerified'], result)

    def test_large_output_avoids_pipe_deadlock(self):
        result = self.run_code("import sys; sys.stdout.write('x'*524288); sys.stderr.write('y'*262144)")
        self.assertEqual(result['status'], 'PASS', result['error'])
        self.assertEqual(result['stdout'], 'x'*524288)
        self.assertEqual(result['stderr'], 'y'*262144)
        self.assertTrue(result['cleanupVerified'])

    def test_timeout_retains_actual_output_and_verified_cleanup(self):
        result = self.run_code("import time; print('before timeout',flush=True); time.sleep(10)", .3)
        self.assertEqual(result['stdout'], 'before timeout\r\n')
        self.assertTrue(result['timedOut'])
        self.assertTrue(result['cleanupVerified'], result)
        self.assertEqual(result['status'], 'FAIL')

    def test_assign_failure_never_resumes_or_executes(self):
        class NoAssign:
            def __init__(self, api): self.api = api; self.resumed = False
            def __getattr__(self, name): return getattr(self.api, name)
            def AssignProcessToJobObject(self, *args): C.set_last_error(5); return 0
            def ResumeThread(self, *args): self.resumed = True; return self.api.ResumeThread(*args)
        proxy = NoAssign(self.api)
        with oj._using_api(proxy): result = self.run_code("print('must never run')")
        self.assertFalse(proxy.resumed)
        self.assertEqual(result['stdout'], '')
        self.assertEqual(result['status'], 'FAIL')
        self.assertTrue(result['cleanupVerified'], result)

    def test_close_failure_cannot_be_success_with_capture(self):
        proxy = legacy._CloseFailure(self.api)
        try:
            with oj._using_api(proxy): result = self.run_code("print('real output')")
            self.assertTrue(proxy.injected)
            self.assertEqual(result['status'], 'FAIL')
            self.assertFalse(result['cleanupVerified'])
            self.assertEqual(result['stdout'], 'real output\r\n')
        finally:
            legacy.OwnedJobTests.recover_handles(self, proxy)

    def test_capture_handles_do_not_leak(self):
        self.assertEqual(self.run_code('pass')['status'], 'PASS')
        def count():
            value = oj.DWORD()
            self.assertTrue(self.api.GetProcessHandleCount(self.api.GetCurrentProcess(), C.byref(value)))
            return value.value
        before = count()
        for _ in range(3): self.assertEqual(self.run_code("print('capture')")['status'], 'PASS')
        self.assertEqual(count(), before)

if __name__ == '__main__':
    unittest.main()
