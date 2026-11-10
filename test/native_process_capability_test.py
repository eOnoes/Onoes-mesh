import ast
import asyncio
from pathlib import Path
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


class NativeProcessCapabilityTests(unittest.IsolatedAsyncioTestCase):
    async def observe(self, flag, platform='nt', *, denied=False, saved=None):
        # Exact method extracted from the prepared, non-installed native candidate.
        source = (ROOT / 'test/fixtures/native-process-lookup.py').read_text()
        namespace = {'asyncio': asyncio, 'RuntimeStoreError': RuntimeError}
        exec(compile(ast.parse(source), '<candidate native lookup>', 'exec'), namespace)
        calls = []

        def authorize(*args):
            calls.append(args[-1])
            if denied:
                raise RuntimeError('denied')

        async def receipt(*args):
            return {'execution_generation': 1}

        owner = SimpleNamespace(authority=SimpleNamespace(db=object(), authorize=authorize),
            actor=SimpleNamespace(subject='synthetic-principal'), receipt=receipt)
        modules = {name: ModuleType(name) for name in ('gateway', 'gateway.session_policy',
            'gateway.mesh_assignment_process', 'hermes_state_runtime', 'hermes_state_local')}
        modules['gateway'].__path__ = []
        modules['hermes_state_runtime'].find_session_admission = lambda *a, **kw: saved
        modules['hermes_state_local'].local_receipt = lambda *a: None
        modules['gateway.session_policy'].restore_policy = lambda p: p
        modules['gateway.mesh_assignment_process'].describe_profile = lambda *a: {}
        with patch.dict('sys.modules', modules), patch('os.name', platform), patch.dict('os.environ', {'MESH_LOCAL_PROCESS_SCOPE': flag}):
            result = await namespace['lookup'](owner, SimpleNamespace(session_id='synthetic-session'),
                {'session_id': 'synthetic-session', 'submission_id': 'never-submitted'})
        self.assertEqual(calls, ['session:read'])
        return result

    async def test_disabled_or_nonliteral_flag_cannot_advertise_support(self):
        for flag in ('', '0', 'true', 'yes'):
            with self.subTest(flag=flag):
                result = await self.observe(flag)
                self.assertIs(result['process_scope_supported'], False)
                self.assertIs(result['found'], False)

    async def test_windows_explicit_enrollment_advertises_support_without_creating_an_admission(self):
        result = await self.observe('1')
        self.assertIs(result['process_scope_supported'], True)
        self.assertIs(result['found'], False)
        self.assertNotIn('process_scope', result)
        self.assertIs((await self.observe('1', platform='posix'))['process_scope_supported'], False)

    async def test_authorization_still_precedes_capability_disclosure(self):
        with self.assertRaisesRegex(RuntimeError, 'denied'):
            await self.observe('1', denied=True)

    async def test_capability_does_not_invent_a_scope_for_a_legacy_admission(self):
        result = await self.observe('1', saved={'admission_id': 'synthetic-existing', 'outcome': 'completed'})
        self.assertIs(result['process_scope_supported'], True)
        self.assertIs(result['found'], True)
        self.assertNotIn('process_scope', result)


if __name__ == '__main__':
    unittest.main()
