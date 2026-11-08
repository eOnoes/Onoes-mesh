"""Opt-in installed-library qualification; never imports or starts the gateway."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', required=True)
    parser.add_argument('--evidence', required=True)
    args = parser.parse_args()
    source = Path(args.source).resolve()
    module_path = source / 'gateway/platforms/api_server_run_idempotency.py'
    output = Path(args.evidence).resolve()
    output.mkdir(parents=True, exist_ok=True)
    # The native SQLite utility can consult configuration. Give this subprocess
    # its own empty home before any vendor import; never use the operator's home.
    with tempfile.TemporaryDirectory(prefix='mesh-native-store-', dir=output) as isolated:
        isolated_root = Path(isolated).resolve()
        if isolated_root.parent != output:
            raise RuntimeError('Synthetic home escaped its designated evidence directory')
        os.environ['HERMES_HOME'] = str(Path(isolated) / 'synthetic-home')
        Path(os.environ['HERMES_HOME']).mkdir()
        sys.path.insert(0, str(source))
        spec = importlib.util.spec_from_file_location('mesh_native_store_under_test', module_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        Store = module.RunIdempotencyStore
        fingerprint = hashlib.sha256(b'synthetic frozen request').hexdigest()

        class StoreQualification(unittest.TestCase):
            def setUp(self):
                self.directory = tempfile.TemporaryDirectory(dir=isolated)
                if Path(self.directory.name).resolve().parent != isolated_root:
                    raise RuntimeError('Synthetic store escaped its designated test directory')
                self.db = str(Path(self.directory.name) / 'synthetic-runs.sqlite')
                self.stores = []

            def store(self, path=None):
                value = Store(self.db if path is None else path)
                self.stores.append(value)
                for _, _, filename in value._conn.execute('PRAGMA database_list'):
                    self.assertTrue(not filename or Path(filename).resolve().is_relative_to(isolated_root))
                return value

            def tearDown(self):
                for value in self.stores:
                    value.close()
                self.directory.cleanup()

            def reserve(self, store, key='send', run='run_one', scope='synthetic-scope'):
                return store.reserve(scope, key, fingerprint, run,
                                     {'run_id': run, 'status': 'queued', 'session_id': 'synthetic-session'},
                                     owner_pid=123, owner_started=456)

            def test_durable_reopen_preserves_exact_identity_and_request_binding(self):
                first = self.store()
                self.assertTrue(first.durable)
                outcome, original = self.reserve(first)
                self.assertEqual(outcome, 'created')
                first.close()
                self.stores.remove(first)
                second = self.store()
                outcome, saved = second.lookup('synthetic-scope', 'send', fingerprint)
                self.assertEqual(outcome, 'reused')
                self.assertEqual(saved['run_id'], original['run_id'])
                self.assertEqual(saved['owner_pid'], 123)
                self.assertEqual(saved['owner_started'], 456)
                self.assertEqual(second.lookup('synthetic-scope', 'send', 'different')[0], 'conflict')
                self.assertEqual(second.lookup('other-scope', 'send', fingerprint), ('missing', None))

            def test_two_connections_have_one_reservation_winner(self):
                first, second = self.store(), self.store()
                with ThreadPoolExecutor(max_workers=2) as pool:
                    results = list(pool.map(lambda item: self.reserve(item[0], run=item[1]),
                                            [(first, 'run_a'), (second, 'run_b')]))
                self.assertEqual(sorted(outcome for outcome, _ in results), ['created', 'reused'])
                self.assertEqual(len({record['run_id'] for _, record in results}), 1)

            def test_lookup_of_missing_key_does_not_admit_work(self):
                value = self.store()
                self.assertEqual(value.lookup('synthetic-scope', 'missing', fingerprint), ('missing', None))
                self.assertEqual(self.reserve(value, key='missing')[0], 'created')

            def test_terminal_status_persists_without_implying_writer_quiescence(self):
                value = self.store()
                self.reserve(value)
                value.update_status('run_one', {'run_id': 'run_one', 'status': 'completed'})
                saved = self.store().status_for_run('synthetic-scope', 'run_one')
                self.assertEqual(saved['status']['status'], 'completed')
                self.assertNotIn('writer_quiescence', saved['status'])
                self.assertIsNone(value.status_for_run('other-scope', 'run_one'))

            def test_unusable_storage_advertises_memory_fallback_as_not_durable(self):
                value = self.store(str(Path(self.directory.name) / 'absent-parent' / 'unusable.sqlite'))
                self.assertFalse(value.durable)
                self.assertEqual(self.reserve(value)[0], 'created')

        result = unittest.TextTestRunner(verbosity=2).run(
            unittest.defaultTestLoader.loadTestsFromTestCase(StoreQualification))
        evidence = {
            'source': str(module_path),
            'sourceSha256': hashlib.sha256(module_path.read_bytes()).hexdigest(),
            'python': sys.executable,
            'tests': result.testsRun,
            'failures': len(result.failures),
            'errors': len(result.errors),
            'passed': result.wasSuccessful(),
            'liveGatewayRequests': 0,
            'liveStoresOpened': 0,
            'scope': 'Installed standalone store with synthetic temporary data; not live gateway or quiescence qualification',
        }
        (output / 'qualification.json').write_text(json.dumps(evidence, indent=2), encoding='utf-8')
        print(json.dumps(evidence))
        return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':
    raise SystemExit(main())
