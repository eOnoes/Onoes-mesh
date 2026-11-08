import concurrent.futures
from pathlib import Path
import shutil
import sys
import threading
import unittest
from unittest.mock import patch
from integrations import hermes_writer_scope as scope


class FakeFence:
    def __init__(self, name):
        self.name = name

    def popen(self, argv, **kwargs):
        return self.name, argv, kwargs


class HermesWriterScopeTests(unittest.TestCase):
    def test_overlapping_thread_contexts_cannot_swap_attempts_and_restore_on_error(self):
        barrier = threading.Barrier(2)
        def run(name):
            fence = FakeFence(name)
            with scope.bind_writer_fence(fence):
                barrier.wait(timeout=5)
                with self.assertRaises(RuntimeError):
                    with scope.bind_writer_fence(FakeFence('other')):
                        self.fail('Another attempt replaced this context')
                return scope.scoped_popen([sys.executable, '-c', 'pass'])[0]
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as workers:
            first = workers.submit(run, 'first')
            second = workers.submit(run, 'second')
            self.assertEqual(first.result(timeout=5), 'first')
            self.assertEqual(second.result(timeout=5), 'second')
        with self.assertRaises(ValueError):
            with scope.bind_writer_fence(FakeFence('temporary')):
                raise ValueError('fixture')
        scope.require_supported_writer_route(local=False)  # Parent context is restored.

    def test_fenced_failure_never_uses_unfenced_fallback_and_host_path_is_used(self):
        name = Path(sys.executable).name
        expected = str(Path(shutil.which(name)).resolve())
        with scope.bind_writer_fence(FakeFence('fixture')):
            result = scope.scoped_popen([name, '-c', 'pass'], env={'PATH': 'untrusted-child-path'})
            self.assertEqual(result[1][0], expected)
            self.assertEqual(result[2]['env']['PATH'], 'untrusted-child-path')
        fence = FakeFence('failed')
        with scope.bind_writer_fence(fence), patch.object(fence, 'popen', side_effect=RuntimeError('fixture')), \
                patch.object(scope.subprocess, 'Popen', side_effect=AssertionError('Unfenced fallback')):
            with self.assertRaises(RuntimeError):
                scope.scoped_popen([sys.executable, '-c', 'pass'])

    def test_unbound_legacy_call_keeps_original_arguments(self):
        argv = [sys.executable, '-c', 'pass']
        with patch.object(scope.subprocess, 'Popen', return_value='legacy') as launch:
            self.assertEqual(scope.scoped_popen(argv, stdout=-1), 'legacy')
            launch.assert_called_once_with(argv, stdout=-1)


if __name__ == '__main__':
    unittest.main()
