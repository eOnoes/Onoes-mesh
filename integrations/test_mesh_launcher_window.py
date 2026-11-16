import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import uuid
import ctypes
from ctypes import wintypes

from mesh_launcher_window import MeshLauncherWindow, LauncherWindowError

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(os.name == 'nt', 'Actual Windows named-launcher qualification')
class LauncherWindowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='mesh-launcher-window-', dir=ROOT/'data')
        self.addCleanup(self.temp.cleanup)
        self.workspace = Path(self.temp.name).resolve()/'workspace'
        (self.workspace/'integrations').mkdir(parents=True)
        (self.workspace/'data/workroom-preview').mkdir(parents=True)
        (self.workspace/'data/workroom-preview/tasks.sqlite').touch()
        self.launcher = self.workspace/'integrations/restart-workroom-preview.ps1'
        shutil.copyfile(ROOT/'integrations/restart-workroom-preview.ps1', self.launcher)
        self.sha = hashlib.sha256(self.launcher.read_bytes()).hexdigest()
        self.pwsh = shutil.which('pwsh')
        self.assertIsNotNone(self.pwsh)

    def native_child(self, window, port=None):
        node = shutil.which('node')
        self.assertIsNotNone(node)
        if port is None:
            with socket.socket() as reserve:
                reserve.bind(('127.0.0.1', 0)); port = reserve.getsockname()[1]
        entry = self.workspace/'serve.mjs'
        entry.write_text("import http from 'node:http'; import fs from 'node:fs'; "
                         "const p=JSON.parse(fs.readFileSync('data/fixture-port.json')); "
                         "http.createServer((q,s)=>s.end('fixture')).listen(p.port,'127.0.0.1',"
                         "()=>fs.writeFileSync('data/fixture-ready','ready'));", encoding='utf-8')
        (self.workspace/'data/fixture-port.json').write_text(json.dumps({'port':port}))
        ready = self.workspace/'data/fixture-ready'
        ready.unlink(missing_ok=True)
        child = subprocess.Popen([node, str(entry), '--native-mind'], cwd=self.workspace,
                                 stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW)
        def close():
            if child.poll() is None: child.terminate()
            child.wait(timeout=20)
        self.addCleanup(close)
        deadline = time.monotonic()+15
        while not ready.exists() and time.monotonic() < deadline:
            self.assertIsNone(child.poll()); time.sleep(.05)
        self.assertTrue(ready.exists())
        times = [wintypes.FILETIME() for _ in range(4)]
        self.assertTrue(window.kernel.GetProcessTimes(child._handle, *(ctypes.byref(t) for t in times)))
        ticks = (times[0].dwHighDateTime << 32) | times[0].dwLowDateTime
        attempt = self.workspace/'data'/('attempt-'+uuid.uuid4().hex+'.json')
        profile = dict(schema='onoes-mesh-native-launch/v1', workspace=str(self.workspace),
                       nodeExecutable=node, nodeSha256=hashlib.sha256(Path(node).read_bytes()).hexdigest(),
                       attemptPath=str(attempt), settings=dict(MESH_PREVIEW_PORT=str(port),
                       MESH_TAILSCALE_HOST='fixture.invalid'))
        path = self.workspace/'data'/('profile-'+uuid.uuid4().hex+'.json')
        path.write_text(json.dumps(profile), encoding='utf-8')
        sha = hashlib.sha256(path.read_bytes()).hexdigest()
        record = dict(schema='onoes-mesh-native-child/v1', profileSha256=sha, pid=child.pid,
                      creationTicks=ticks, state='input_sent', executable=node,
                      entryPoint=str(entry), credentialsInRecord=False)
        attempt.write_text(json.dumps(record), encoding='utf-8')
        return child, ticks, path, sha, attempt

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

    def test_real_native_owner_publication_then_actual_recovery_keeps_child(self):
        with MeshLauncherWindow(self.workspace, self.sha) as window:
            child, ticks, profile, sha, attempt = self.native_child(window)
            record = window.publish_native_owner(child, ticks, profile, sha, previous_sha256=None)
            self.assertEqual(record['Id'], child.pid)
            self.assertEqual(self.command('Ensure').returncode, 1)
        result = self.command('Ensure')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('is running; no restart performed', result.stdout)
        self.assertIsNone(child.poll())
        receipt = json.loads((self.workspace.parent/'workroom-ab-preview-process.json').read_text())
        self.assertEqual(receipt['Id'], child.pid)

    def test_stale_attempt_and_live_previous_owner_refuse_without_stopping_child(self):
        with MeshLauncherWindow(self.workspace, self.sha) as window:
            child, ticks, profile, sha, attempt = self.native_child(window)
            original = attempt.read_bytes()
            wrong = json.loads(original); wrong['creationTicks'] += 1
            attempt.write_text(json.dumps(wrong))
            with self.assertRaisesRegex(LauncherWindowError, 'attempt does not identify'):
                window.publish_native_owner(child, ticks, profile, sha, previous_sha256=None)
            attempt.write_bytes(original)
            record = window.publish_native_owner(child, ticks, profile, sha, previous_sha256=None)
            target = self.workspace.parent/'workroom-ab-preview-process.json'
            before = target.read_bytes()
            with self.assertRaisesRegex(LauncherWindowError, 'Previous owner is still live'):
                window.publish_native_owner(child, ticks, profile, sha,
                    previous_sha256=hashlib.sha256(before).hexdigest(),
                    beforeimage_path=self.workspace/'data/previous-owner.json')
            self.assertEqual(target.read_bytes(), before)
            self.assertFalse((self.workspace/'data/previous-owner.json').exists())
            self.assertIsNone(child.poll())

    def test_retired_owner_replacement_keeps_exact_beforeimage(self):
        with MeshLauncherWindow(self.workspace, self.sha) as window:
            child, ticks, profile, sha, _ = self.native_child(window)
            first = window.publish_native_owner(child, ticks, profile, sha, previous_sha256=None)
            target = self.workspace.parent/'workroom-ab-preview-process.json'
            before = target.read_bytes()
            child.terminate(); child.wait(timeout=20)
            second, ticks2, profile2, sha2, _ = self.native_child(window, port=first['Port'])
            backup = self.workspace/'data/previous-owner.json'
            record = window.publish_native_owner(second, ticks2, profile2, sha2,
                       previous_sha256=hashlib.sha256(before).hexdigest(), beforeimage_path=backup)
            self.assertEqual(backup.read_bytes(), before)
            self.assertEqual(record['Id'], second.pid)
        result = self.command('Ensure')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIsNone(second.poll())

    def test_declared_port_without_exact_child_listener_is_refused(self):
        with MeshLauncherWindow(self.workspace, self.sha) as window:
            child, ticks, profile, sha, attempt = self.native_child(window)
            p = json.loads(profile.read_text())
            with socket.socket() as other:
                other.bind(('127.0.0.1', 0))
                p['settings']['MESH_PREVIEW_PORT'] = str(other.getsockname()[1])
                profile.write_text(json.dumps(p)); sha = hashlib.sha256(profile.read_bytes()).hexdigest()
                a = json.loads(attempt.read_text()); a['profileSha256'] = sha
                attempt.write_text(json.dumps(a))
                with self.assertRaisesRegex(LauncherWindowError, 'does not own the loopback gateway'):
                    window.publish_native_owner(child, ticks, profile, sha, previous_sha256=None)
            self.assertFalse((self.workspace.parent/'workroom-ab-preview-process.json').exists())
            self.assertIsNone(child.poll())

    def test_reused_pid_with_different_birth_does_not_block_or_stop_unrelated_process(self):
        with MeshLauncherWindow(self.workspace,self.sha) as window:
            first,ticks,profile,sha,_=self.native_child(window)
            owner=window.publish_native_owner(first,ticks,profile,sha,previous_sha256=None)
            first.terminate();first.wait(timeout=20)
            unrelated=subprocess.Popen([sys.executable,'-I','-c','import time;time.sleep(30)'],
                creationflags=subprocess.CREATE_NO_WINDOW)
            self.addCleanup(lambda:(unrelated.terminate(),unrelated.wait(timeout=20)) if unrelated.poll() is None else None)
            # Model OS PID reuse with a real different retained process birth.
            owner['Id']=unrelated.pid
            target=self.workspace.parent/'workroom-ab-preview-process.json'
            target.write_text(json.dumps(owner));before=target.read_bytes()
            second,ticks2,profile2,sha2,_=self.native_child(window,port=owner['Port'])
            published=window.publish_native_owner(second,ticks2,profile2,sha2,
                previous_sha256=hashlib.sha256(before).hexdigest(),beforeimage_path=self.workspace/'data/reused-pid-before.json')
            self.assertEqual(published['Id'],second.pid);self.assertIsNone(unrelated.poll())


if __name__ == '__main__': unittest.main()
