import ctypes
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
from integrations import windows_writer_fence as native


@unittest.skipUnless(sys.platform == 'win32', 'Actual Windows Job Objects required')
class WindowsWriterFenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture_root = Path(__file__).resolve().parents[1] / 'data' / 'writer-fence-fixtures'
        cls.fixture_root.mkdir(parents=True, exist_ok=True)

    def cleanup_fence(self, fence):
        fence.terminate()
        fence.close()

    def test_root_exit_does_not_release_a_detached_console_child(self):
        with tempfile.TemporaryDirectory(prefix='owned-', dir=self.fixture_root) as directory:
            marker = Path(directory) / 'release-child'
            child = "import pathlib,time,sys;p=pathlib.Path(sys.argv[1]);end=time.monotonic()+15\nwhile not p.exists() and time.monotonic()<end: time.sleep(.02)"
            root = "import subprocess,sys;subprocess.Popen([sys.executable,'-c',sys.argv[1],sys.argv[2]],creationflags=subprocess.DETACHED_PROCESS|subprocess.CREATE_NEW_PROCESS_GROUP)"
            fence = native.WindowsWriterFence('fixture-run', 'generation-one')
            try:
                fence.launch([sys.executable, '-c', root, child, str(marker)])
                fence.seal()
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline:
                    held = fence.snapshot()
                    if held.get('allRootsEnded'):
                        break
                    time.sleep(.02)
                self.assertTrue(held['allRootsEnded'])
                self.assertGreater(held['activeProcesses'], 0)
                self.assertFalse(fence.wait(20)['processTreeEnded'])
                with self.assertRaises(RuntimeError):
                    fence.launch([sys.executable, '-c', 'pass'])
                with self.assertRaises(RuntimeError):
                    fence.close()
                marker.write_text('fixture child may exit')
                ended = fence.wait()
                self.assertTrue(ended['processTreeEnded'])
                self.assertFalse(ended['writerQuiescence'])
                self.assertEqual(ended['generation'], 'generation-one')
                with self.assertRaises(AttributeError):
                    fence.generation = 'a-different-attempt'
            finally:
                self.cleanup_fence(fence)

    def test_termination_is_owned_and_other_attempt_stays_running(self):
        a, b = native.WindowsWriterFence('a', 'one'), native.WindowsWriterFence('b', 'two')
        try:
            for fence in (a, b):
                fence.launch([sys.executable, '-c', 'import time;time.sleep(15)'])
                fence.seal()
            ended = a.terminate()
            self.assertTrue(ended['processTreeEnded'])
            self.assertTrue(ended['terminationRequested'])
            self.assertGreater(b.snapshot()['activeProcesses'], 0)
            self.assertFalse(b.snapshot()['processTreeEnded'])
        finally:
            self.cleanup_fence(a)
            self.cleanup_fence(b)

    def test_controller_crash_closes_its_job_and_leaves_no_running_child(self):
        with tempfile.TemporaryDirectory(prefix='crash-', dir=self.fixture_root) as directory:
            marker = Path(directory) / 'child-started'
            child = "import pathlib,sys,time;pathlib.Path(sys.argv[1]).write_text('started');time.sleep(15)"
            controller = (
                "from integrations.windows_writer_fence import WindowsWriterFence\n"
                "import os,sys,time,pathlib\n"
                "f=WindowsWriterFence('crashed-controller','one')\n"
                "f.launch([sys.executable,'-c',sys.argv[1],sys.argv[2]])\n"
                "deadline=time.monotonic()+5\n"
                "while not pathlib.Path(sys.argv[2]).exists() and time.monotonic()<deadline: time.sleep(.02)\n"
                "os._exit(0)\n")
            outer = native.WindowsWriterFence('crash-fixture-outer', 'one')
            try:
                outer.launch([sys.executable, '-c', controller, child, str(marker)],
                             cwd=Path(__file__).resolve().parents[1])
                outer.seal()
                ended = outer.wait(8000)
                self.assertTrue(marker.exists(), 'The nested child must actually start')
                self.assertTrue(ended['processTreeEnded'], ended)
                self.assertEqual(ended['activeProcesses'], 0)
                self.assertFalse(ended['writerQuiescence'])
            finally:
                self.cleanup_fence(outer)

    def test_failed_assignment_never_executes_suspended_root_or_mints_a_proof(self):
        with tempfile.TemporaryDirectory(prefix='rejected-', dir=self.fixture_root) as directory:
            marker = Path(directory) / 'must-not-run'
            fence = native.WindowsWriterFence('rejected', 'one')
            try:
                with patch.object(native._kernel, 'AssignProcessToJobObject', return_value=False):
                    ctypes.set_last_error(5)
                    with self.assertRaises(OSError):
                        fence.launch([sys.executable, '-c', 'import pathlib,sys;pathlib.Path(sys.argv[1]).touch()', str(marker)])
                fence.seal()
                self.assertFalse(marker.exists())
                self.assertEqual(fence.snapshot()['activeProcesses'], 0)
                self.assertFalse(fence.snapshot()['processTreeEnded'])
            finally:
                self.cleanup_fence(fence)

    def test_observation_error_and_closed_fence_are_unknown(self):
        fence = native.WindowsWriterFence('unavailable', 'one')
        try:
            with patch.object(native._kernel, 'QueryInformationJobObject', return_value=False):
                ctypes.set_last_error(5)
                self.assertEqual(fence.snapshot()['state'], 'unknown')
                self.assertFalse(fence.snapshot()['processTreeEnded'])
        finally:
            self.cleanup_fence(fence)
        self.assertEqual(fence.snapshot()['state'], 'unknown')

    def test_failed_launch_cleanup_keeps_control_and_never_reports_tree_ended(self):
        fence = native.WindowsWriterFence('failed-cleanup', 'one')
        try:
            with patch.object(native._kernel, 'AssignProcessToJobObject', return_value=False), \
                    patch.object(native._kernel, 'TerminateProcess', return_value=False):
                ctypes.set_last_error(5)
                with self.assertRaises(OSError):
                    fence.launch([sys.executable, '-c', 'raise Exception("must never execute")'])
            self.assertEqual(fence.snapshot()['state'], 'unknown')
            self.assertFalse(fence.snapshot()['processTreeEnded'])
            with self.assertRaises(RuntimeError):
                fence.close()
            with self.assertRaises(RuntimeError):
                fence.launch([sys.executable, '-c', 'pass'])
            self.assertFalse(fence.terminate()['processTreeEnded'])
        finally:
            self.cleanup_fence(fence)

    def test_pipe_launch_preserves_stdin_stdout_stderr_and_nonzero_exit(self):
        fence = native.WindowsWriterFence('pipe-io', 'one')
        try:
            with fence.popen([sys.executable, '-c',
                             'import sys;print(sys.stdin.read().upper());print("warning",file=sys.stderr);sys.exit(7)'],
                             stdin=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                             encoding='utf-8', errors='replace', start_new_session=True) as proc:
                out, err = proc.communicate('scoped input', timeout=5)
                self.assertEqual(proc.returncode, 7)
                self.assertEqual(out.strip(), 'SCOPED INPUT')
                self.assertEqual(err.strip(), 'warning')
            fence.seal()
            self.assertTrue(fence.wait()['processTreeEnded'])
            self.assertFalse(fence.snapshot()['writerQuiescence'])
        finally:
            self.cleanup_fence(fence)

    def test_pipe_launch_keeps_child_after_root_ends_and_caller_closes_root_handle(self):
        with tempfile.TemporaryDirectory(prefix='pipe-child-', dir=self.fixture_root) as directory:
            marker = Path(directory) / 'release'
            child = 'import sys,pathlib,time;p=pathlib.Path(sys.argv[1]);end=time.monotonic()+15\nwhile not p.exists() and time.monotonic()<end:time.sleep(.02)'
            root = 'import sys,subprocess;subprocess.Popen([sys.executable,"-c",sys.argv[1],sys.argv[2]],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL);print("root done")'
            fence = native.WindowsWriterFence('pipe-child', 'one')
            try:
                with fence.popen([sys.executable, '-c', root, child, str(marker)], text=True) as proc:
                    out, _ = proc.communicate(timeout=5)
                    self.assertEqual(out.strip(), 'root done')
                    proc._handle.Close()  # Fence observation uses its independent retained handle.
                fence.seal()
                self.assertTrue(fence.snapshot()['allRootsEnded'])
                self.assertFalse(fence.wait(20)['processTreeEnded'])
                marker.touch()
                self.assertTrue(fence.wait()['processTreeEnded'])
            finally:
                self.cleanup_fence(fence)

    def test_pipe_thread_lookup_failure_executes_nothing_and_retains_failed_cleanup(self):
        fence = native.WindowsWriterFence('pipe-refused', 'one')
        try:
            with patch.object(native, '_new_suspended_thread', side_effect=OSError('fixture unavailable')), \
                    patch.object(subprocess.Popen, 'terminate', side_effect=OSError('fixture cleanup uncertain')):
                with self.assertRaises(OSError):
                    fence.popen([sys.executable, '-c', 'raise Exception("must never execute")'])
            self.assertEqual(fence.snapshot()['state'], 'unknown')
            with self.assertRaises(RuntimeError):
                fence.close()
            self.assertFalse(fence.terminate()['processTreeEnded'])
        finally:
            self.cleanup_fence(fence)


if __name__ == '__main__':
    unittest.main()
