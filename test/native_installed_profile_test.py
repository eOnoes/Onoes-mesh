import copy
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('installed_profile', Path(__file__).parents[1]
                                            / 'integrations/verify-native-installed-profile.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class InstalledProfileTests(unittest.TestCase):
    def setUp(self):
        self.intent = {'sessionId': 'local-fixture', 'workspace': 'fixture-workspace',
                       'model': 'gpt-6-luna'}
        self.snapshot = {
            'found': False, 'session_id': 'local-fixture',
            'submission_id': 'codex-never-submitted', 'outcome': None,
            'profile_contract': {
                'model': 'gpt-6-luna', 'provider': 'openai-codex', 'base_url': None,
                'workspace': 'fixture-workspace', 'toolsets': ['file', 'terminal'],
                'safe_mode': True, 'ignore_user_config': True, 'follow_profile': False,
                'source': 'tool', 'max_turns': 50, 'terminal_backend': 'local',
                'closed': True, 'api_key_configured': False}}

    def test_exact_contract_exports_only_allowlisted_public_fields(self):
        self.snapshot['profile_contract']['unexpected_private_field'] = 'must-not-export'
        result = module.validate(self.snapshot, self.intent)
        self.assertIs(result['api_key_configured'], False)
        self.assertNotIn('unexpected_private_field', result)

    def test_missing_or_mismatched_authority_never_passes(self):
        changes = [('session_id', 'other'), ('submission_id', 'other'), ('found', True),
                   ('outcome', 'completed')]
        profile_changes = [('workspace', 'other'), ('provider', 'custom'),
                           ('toolsets', ['file', 'terminal', 'browser']),
                           ('base_url', 'https://example.invalid'), ('closed', False),
                           ('api_key_configured', True), ('api_key_configured', None),
                           ('follow_profile', True), ('safe_mode', False)]
        for key, value in changes + profile_changes:
            with self.subTest(key=key, value=value):
                changed = copy.deepcopy(self.snapshot)
                target = changed if (key, value) in changes else changed['profile_contract']
                target[key] = value
                with self.assertRaises(RuntimeError):
                    module.validate(changed, self.intent)
        for key in self.snapshot['profile_contract']:
            # A null endpoint is valid; an absent endpoint must still be explicit.
            changed = copy.deepcopy(self.snapshot)
            del changed['profile_contract'][key]
            with self.subTest(missing=key), self.assertRaises(RuntimeError):
                module.validate(changed, self.intent)


if __name__ == '__main__':
    unittest.main()
