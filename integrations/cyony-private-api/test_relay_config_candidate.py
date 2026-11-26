from hashlib import sha256
import json
import unittest

from relay_config_candidate import RelayConfigHold, parse, prepare_relay_config, restore_relay_config

BASE = {'host': '127.0.0.1', 'port': 8787, 'notify': {'enabled': True}, 'agents': {
    'echo': {'backend': 'hermes', 'url': 'http://127.0.0.1:8642', 'api_key_file': '.private/echo.key'},
    'cyony': {'name': 'Cyony', 'backend': 'a2a', 'device': 'cloud', 'url': 'http://old.invalid:9900',
              'api_key_file': '.private/cyony.key', 'max_turns': 50, 'demo_fallback': False,
              'budget': {'max_turns': 50}},
    'dsh': {'backend': 'a2a', 'url': 'http://127.0.0.1:4123/a2a'}}}
RAW = (json.dumps(BASE, indent=2) + '\n').encode()
DIR = 'D:/Apps/Relay/.private'
KEY = DIR + '/cyony-native-hermes.key'
HOST = 'cloud.example.ts.net'


def prepare(raw=RAW, **kw):
    options = dict(expected_sha256=sha256(raw).hexdigest(), hostname=HOST,
                   credential_directory=DIR, credential_file=KEY)
    options.update(kw)
    return prepare_relay_config(raw, **options)


class RelayConfigTests(unittest.TestCase):
    def test_only_cyony_route_changes(self):
        proposed = prepare()
        value = parse(proposed)
        self.assertEqual(value['agents']['echo'], BASE['agents']['echo'])
        self.assertEqual(value['agents']['dsh'], BASE['agents']['dsh'])
        row = value['agents']['cyony']
        self.assertEqual(row['backend'], 'hermes')
        self.assertEqual(row['url'], 'https://' + HOST + '/relay-native')
        self.assertEqual(row['max_turns'], 50)
        self.assertEqual(row['budget'], BASE['agents']['cyony']['budget'])
        self.assertFalse(row['demo_fallback'])
        self.assertEqual(value['notify'], BASE['notify'])
        self.assertEqual(restore_relay_config(proposed, original=RAW, proposed=proposed), RAW)

    def test_stale_source_refused(self):
        with self.assertRaises(RelayConfigHold):
            prepare(RAW + b' ', expected_sha256=sha256(RAW).hexdigest())

    def test_reused_old_credential_refused(self):
        with self.assertRaises(RelayConfigHold):
            prepare(credential_file=DIR + '/cyony.key')

    def test_new_credential_cannot_be_network_or_outside_private(self):
        for path in ('D:/elsewhere/cyony.key', '//server/share/cyony.key',
                     DIR + '/../cyony.key', DIR + '/cyony.env'):
            with self.subTest(path=path), self.assertRaises(RelayConfigHold):
                prepare(credential_file=path)

    def test_hostname_cannot_smuggle_port_query_or_plain_http(self):
        for host in ('http://cloud.example.ts.net', HOST + ':9000', HOST + '?token=x',
                     'cloud.example.com', HOST + '/other', HOST + '@attacker.invalid'):
            with self.subTest(host=host), self.assertRaises(RelayConfigHold):
                prepare(hostname=host)

    def test_alternate_inline_or_environment_secret_refused(self):
        for field in ('api_key', 'api_key_env'):
            changed = json.loads(RAW); changed['agents']['cyony'][field] = 'fixture-only'
            with self.subTest(field=field), self.assertRaises(RelayConfigHold):
                prepare(json.dumps(changed).encode())

    def test_backend_or_demo_drift_refused(self):
        for field, value in (('backend', 'hermes'), ('device', 'laptop'), ('demo_fallback', True)):
            changed = json.loads(RAW); changed['agents']['cyony'][field] = value
            with self.subTest(field=field), self.assertRaises(RelayConfigHold):
                prepare(json.dumps(changed).encode())

    def test_duplicate_keys_refused(self):
        with self.assertRaises(RelayConfigHold):
            prepare(RAW.replace(b'"host":', b'"port": 9999, "host":', 1))

    def test_concurrent_edit_not_overwritten_on_rollback(self):
        proposed = prepare()
        with self.assertRaises(RelayConfigHold):
            restore_relay_config(proposed + b' ', original=RAW, proposed=proposed)


if __name__ == '__main__':
    unittest.main(verbosity=2)
