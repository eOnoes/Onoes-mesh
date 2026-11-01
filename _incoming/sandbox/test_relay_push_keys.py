import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock
import relay_push_keys
import relay_push


@unittest.skipUnless(os.name == 'nt', 'Windows DPAPI only')
class ProtectedKeysTests(unittest.TestCase):
    def test_default_store_constructor_uses_explicit_environment_name(self):
        with tempfile.TemporaryDirectory(dir=os.environ.get('TMPDIR')) as directory:
            path = str(Path(directory) / 'push.db')
            with mock.patch.dict(os.environ, {'RELAY_PUSH_DB':path}, clear=True):
                store = relay_push.PushStore()
                self.assertEqual(store.counts()['active'], 0)
            with mock.patch.dict(os.environ, {}, clear=True), mock.patch.object(relay_push, 'DEFAULT_DB', path):
                store = relay_push.PushStore()
                self.assertEqual(store.counts()['active'], 0)

    def test_real_main_with_protected_keys_and_default_database(self):
        import json
        import shutil
        import socket
        import subprocess
        import sys
        import time
        import urllib.request
        root = Path(__file__).resolve().parent
        with tempfile.TemporaryDirectory(dir=os.environ.get('TMPDIR')) as directory:
            isolated = Path(directory)
            for source in root.glob('*.py'):
                shutil.copy2(source, isolated / source.name)
            shutil.copy2(root / 'seed.json', isolated / 'seed.json')
            key_path = isolated / 'ephemeral.dpapi'
            relay_push_keys.provision(key_path)
            with socket.socket() as probe:
                probe.bind(('127.0.0.1',0))
                port = probe.getsockname()[1]
            env = dict(os.environ)
            for name in ('RELAY_PUSH_DB', relay_push.TOKEN_ENV, relay_push.VAPID_PUBLIC_ENV, relay_push.VAPID_PRIVATE_ENV):
                env.pop(name, None)
            env.update(RELAY_PUSH_KEY_FILE=str(key_path), RELAY_PUSH_ENROLL_UNTIL=str(time.time()+60), RELAY_PUSH_ENROLL_DEVICE='Eddie phone')
            child = subprocess.Popen([sys.executable,'-B','server.py',str(port)],cwd=isolated,env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
            try:
                deadline = time.monotonic()+8
                result=None
                while time.monotonic()<deadline and child.poll() is None:
                    try:
                        request = urllib.request.Request(f'http://127.0.0.1:{port}/api/relay/push/status', headers={'Host':'127.0.0.1:8772'})
                        with urllib.request.urlopen(request,timeout=.3) as response:
                            result=json.load(response)
                        break
                    except OSError:
                        time.sleep(.05)
                self.assertIsNotNone(result, 'Actual isolated __main__ status route failed.')
                self.assertTrue(result['ready'])
                self.assertTrue(result['enrollment'])
                self.assertFalse(result['enrolled'])
                self.assertTrue((isolated/'data/relay-push.db').exists())
            finally:
                if child.poll() is None:
                    child.terminate()  # only this test-owned ephemeral process
                child.communicate(timeout=5)

    def test_protected_roundtrip_and_expiring_enrollment(self):
        import pywebpush  # Load native dependencies before clearing test-only environment.
        with tempfile.TemporaryDirectory(dir=os.environ.get('TMPDIR')) as directory:
            path = Path(directory) / 'ephemeral-vapid.dpapi'
            self.assertTrue(relay_push_keys.provision(path)['roundtrip'])
            data = relay_push_keys.load(path)
            self.assertNotIn(data['private'].encode(), path.read_bytes())
            with self.assertRaises(FileExistsError):
                relay_push_keys.provision(path)
            with mock.patch.dict(os.environ, {'RELAY_PUSH_KEY_FILE':str(path), 'RELAY_PUSH_ENROLL_UNTIL':'1100', relay_push.DEVICE_ENV:'Eddie phone'}, clear=True):
                with mock.patch('time.time', return_value=1000):
                    relay_push_keys.apply_environment()
                    self.assertEqual(relay_push.parse_capability(os.environ[relay_push.TOKEN_ENV])[1], 'Eddie phone')
                    relay_push.require_delivery_ready()
            with mock.patch.dict(os.environ, {'RELAY_PUSH_KEY_FILE':str(path), 'RELAY_PUSH_ENROLL_UNTIL':'999', relay_push.DEVICE_ENV:'Eddie phone'}, clear=True):
                with mock.patch('time.time', return_value=1000):
                    relay_push_keys.apply_environment()
                    self.assertNotIn(relay_push.TOKEN_ENV, os.environ)
