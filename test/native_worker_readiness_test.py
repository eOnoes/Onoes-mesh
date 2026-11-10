import asyncio
import importlib.util
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('mesh_installed_profile', ROOT / 'integrations/verify-native-installed-profile.py')
verifier = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verifier)
maintenance_spec = importlib.util.spec_from_file_location('mesh_worker_maintenance', ROOT / 'integrations/prepare-native-worker-maintenance.py')
maintenance = importlib.util.module_from_spec(maintenance_spec)
maintenance_spec.loader.exec_module(maintenance)


class InstalledReadinessTests(unittest.IsolatedAsyncioTestCase):
    def test_launcher_preparation_preserves_existing_bytes_encoding_and_hidden_run(self):
        text = 'Option Explicit\r\nSet launcher = CreateObject("WScript.Shell")\r\nlauncher.Run "synthetic-command", 0, False\r\n'
        for bom, encoding in ((b'', 'utf-8'), (b'\xef\xbb\xbf', 'utf-8'), (b'\xff\xfe', 'utf-16-le'), (b'\xfe\xff', 'utf-16-be')):
            with self.subTest(encoding=encoding, bom=bom):
                original = bom + text.encode(encoding)
                candidate = maintenance.prepare_launcher(original)
                self.assertTrue(candidate.startswith(bom))
                decoded = candidate[len(bom):].decode(encoding)
                addition = ('Dim meshWorkerEnvironment\r\n'
                    'Set meshWorkerEnvironment = launcher.Environment("Process")\r\n'
                    'meshWorkerEnvironment("MESH_LOCAL_PROCESS_SCOPE") = "1"\r\n')
                self.assertEqual(candidate.replace(addition.encode(encoding), b'', 1), original)
                self.assertEqual(decoded.count('MESH_LOCAL_PROCESS_SCOPE'), 1)

    def test_existing_enrollment_or_ambiguous_launcher_requires_review(self):
        shell = 'Set launcher = CreateObject("WScript.Shell")\r\n'
        for text in ('', shell * 2, shell + "'MESH_LOCAL_PROCESS_SCOPE", shell + 'Dim meshWorkerEnvironment'):
            with self.subTest(text=text), self.assertRaises(RuntimeError):
                maintenance.prepare_launcher(text.encode())

    def snapshot(self):
        intent = {'sessionId': 'fixed-synthetic-session', 'model': 'gpt-6-luna', 'workspace': 'fixed-synthetic-workspace'}
        profile = dict(model=intent['model'], provider='openai-codex', base_url=None,
            workspace=intent['workspace'], toolsets=['file', 'terminal'], safe_mode=True,
            ignore_user_config=True, follow_profile=False, source='tool', max_turns=50,
            terminal_backend='local', closed=True, api_key_configured=False)
        return intent, {'found': False, 'session_id': intent['sessionId'],
            'submission_id': 'codex-never-submitted', 'outcome': None, 'profile_contract': profile}

    def test_missing_or_untyped_capability_never_confirms_readiness(self):
        for value in (None, False, 'true', 1, {}, []):
            with self.subTest(value=value):
                state = verifier.readiness({'process_scope_supported': value, 'outcome': 'completed'})
                self.assertEqual(state['status'], 'HELD')
                self.assertIs(state['workerRetirementVerified'], False)

    def test_capability_does_not_claim_worker_retirement_or_enrollment(self):
        state = verifier.readiness({'process_scope_supported': True})
        self.assertEqual(state['status'], 'CAPABILITY_CONFIRMED')
        self.assertIs(state['workerRetirementVerified'], False)
        self.assertIs(state['productionEnrollment'], False)

    def test_exact_unsubmitted_profile_is_required_and_arbitrary_fields_are_not_exported(self):
        intent, snapshot = self.snapshot()
        snapshot['profile_contract']['private_synthetic_field'] = 'must-not-export'
        self.assertNotIn('private_synthetic_field', verifier.validate(snapshot, intent))
        for changes in ({'found': True}, {'session_id': 'another-session'}, {'outcome': 'completed'}):
            with self.subTest(changes=changes), self.assertRaises(RuntimeError):
                verifier.validate({**snapshot, **changes}, intent)

    async def observe(self, origin, target='ws://127.0.0.1:9120/ws'):
        intent, snapshot = self.snapshot()
        calls = []
        modules = {name: ModuleType(name) for name in ('hermes_cli', 'hermes_cli.gateway_client', 'hermes_cli.gateway_runtime', 'aiohttp')}
        modules['hermes_cli'].__path__ = []
        endpoint = SimpleNamespace(api_origin=origin)
        modules['hermes_cli.gateway_runtime'].discover_gateway_endpoint = lambda *a, **kw: SimpleNamespace(state='ready', endpoint=endpoint)
        def ticket(*a, **kw):
            calls.append('ticket')
            return 'synthetic-only-ticket'
        modules['hermes_cli.gateway_client']._session_ticket = ticket
        modules['hermes_cli.gateway_client'].gateway_ws_target = lambda *a: (target, ['synthetic-protocol'])
        class Socket:
            async def __aenter__(self): return self
            async def __aexit__(self, *args): pass
            async def send_json(self, request): calls.append(request)
            async def receive_json(self): return {'id': 1, 'result': snapshot}
        class Client:
            async def __aenter__(self): return self
            async def __aexit__(self, *args): pass
            def ws_connect(self, *a, **kw): return Socket()
        modules['aiohttp'].ClientSession = Client
        with patch.dict(sys.modules, modules):
            try:
                result = await verifier.read_gateway(Path('synthetic-home'), intent)
            except RuntimeError:
                return calls, None
        return calls, result

    async def test_remote_or_credentialed_discovery_is_rejected_before_ticket(self):
        for origin in ('http://example.com', 'http://127.0.0.1.example.com', 'http://user@localhost', 'https://localhost'):
            with self.subTest(origin=origin):
                calls, result = await self.observe(origin)
                self.assertEqual(calls, [])
                self.assertIsNone(result)

    async def test_lookup_only_and_no_request_after_bad_websocket_target(self):
        calls, result = await self.observe('http://127.0.0.1:8642')
        self.assertIsNotNone(result)
        self.assertEqual(calls[0], 'ticket')
        self.assertEqual(calls[1]['method'], 'prompt.lookup')
        self.assertEqual(calls[1]['params']['submission_id'], 'codex-never-submitted')
        self.assertEqual(len(calls), 2)
        calls, result = await self.observe('http://127.0.0.1:8642', 'ws://example.com/ws')
        self.assertEqual(calls, ['ticket'])
        self.assertIsNone(result)


if __name__ == '__main__':
    unittest.main()
