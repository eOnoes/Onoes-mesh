import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
import unittest

from mesh_launcher_window import MeshLauncherWindow, LauncherWindowError

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(os.name == 'nt', 'Actual Windows named-launcher qualification')
class LauncherWindowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='mesh-launcher-window-', dir=ROOT/'data')
        self.addCleanup(self.temp.cleanup)
        self.workspace = Path(self.temp.name).resolve()
        (self.workspace/'integrations').mkdir()
        (self.workspace/'data/workroom-preview').mkdir(parents=True)
        (self.workspace/'data/workroom-preview/tasks.sqlite').touch()
        self.launcher = self.workspace/'integrations/restart-workroom-preview.ps1'
        shutil.copyfile(ROOT/'integrations/restart-workroom-preview.ps1', self.launcher)
        self.sha = hashlib.sha256(self.launcher.read_bytes()).hexdigest()
        self.pwsh = shutil.which('pwsh')
        self.assertIsNotNone(self.pwsh)

    def command(self, action):
        return subprocess.run([self.pwsh, '-NoProfile', '-NonInteractive', '-File', str(self.launcher),
                               '-Action', action], capture_output=True, text=True, timeout=30,
                              creationflags=subprocess.CREATE_NO_WINDOW)

    def test_real_recovery_entry_refuses_while_cutover_owns_same_mutex(self):
        before = set(self.workspace.rglob('*'))
        with MeshLauncherWindow(self.workspace, self.sha) as window:
            window.assert_held()
            result = self.command('Ensure')
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('Another named Mesh launcher operation is in progress', result.stderr)
            self.assertEqual(set(self.workspace.rglob('*')), before)
        # Status is read-only, so this demonstrates release without starting a server.
        result = self.command('Status')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(json.loads(result.stdout)['Running'])

    def test_exception_releases_mutex_and_source_drift_refuses_progress(self):
        with self.assertRaisesRegex(RuntimeError, 'simulated cutover failure'):
            with MeshLauncherWindow(self.workspace, self.sha):
                raise RuntimeError('simulated cutover failure')
        with MeshLauncherWindow(self.workspace, self.sha) as window:
            self.launcher.write_bytes(self.launcher.read_bytes()+b'\n# fixture drift\n')
            with self.assertRaisesRegex(LauncherWindowError, 'launcher changed'):
                window.assert_held()
        result = self.command('Status')
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_wrong_source_pin_and_cross_thread_use_are_refused(self):
        with self.assertRaisesRegex(LauncherWindowError, 'launcher changed'):
            with MeshLauncherWindow(self.workspace, '0'*64): pass
        with MeshLauncherWindow(self.workspace, self.sha) as window:
            errors = []
            def other_thread():
                try: window.assert_held()
                except LauncherWindowError as error: errors.append(str(error))
            thread = threading.Thread(target=other_thread)
            thread.start(); thread.join(timeout=5)
            self.assertFalse(thread.is_alive())
            self.assertEqual(len(errors), 1)
            window.assert_held()


if __name__ == '__main__': unittest.main()
