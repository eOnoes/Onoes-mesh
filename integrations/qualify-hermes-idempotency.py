"""Opt-in installed-library qualification; never imports or starts the gateway."""
import argparse
import ast
import asyncio
import hashlib
import importlib.util
import json
import os
import logging
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
        runs_path = source / 'gateway/platforms/api_server_runs.py'
        # Compile only this reviewed standalone function, never module imports,
        # decorators, gateway initialization or access to a real session store.
        tree = ast.parse(runs_path.read_text(encoding='utf-8'))
        resolver_nodes = [node for node in tree.body
                          if isinstance(node, ast.AsyncFunctionDef)
                          and node.name == '_resolve_live_session_id']
        if len(resolver_nodes) != 1 or resolver_nodes[0].decorator_list:
            raise RuntimeError('Expected one undecorated native continuation resolver')
        namespace = {'asyncio': asyncio, 'logger': logging.getLogger('synthetic-continuation')}
        exec(compile(ast.Module(body=resolver_nodes, type_ignores=[]), str(runs_path), 'exec'), namespace)
        resolve_session = namespace['_resolve_live_session_id']

        class SyntheticGateway:
            def __init__(self, database):
                self.database = database

            async def _ensure_session_db_async(self):
                return self.database

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

            def test_native_continuation_selects_live_tip_from_original_id(self):
                class SyntheticSessions:
                    def resolve_resume_session_id(inner, original):
                        self.assertEqual(original, 'original-conversation')
                        return 'continued-session'
                result = asyncio.run(resolve_session(SyntheticGateway(SyntheticSessions()),
                                                     'original-conversation'))
                self.assertEqual(result, 'continued-session')

            def test_native_continuation_without_resolver_preserves_original_id(self):
                for database in (None, object()):
                    self.assertEqual(asyncio.run(resolve_session(SyntheticGateway(database), 'original')),
                                     'original')

            def test_native_continuation_error_or_empty_result_preserves_original_id(self):
                class EmptySessions:
                    def resolve_resume_session_id(inner, original):
                        return None
                class FailedSessions:
                    def resolve_resume_session_id(inner, original):
                        raise RuntimeError('synthetic resolver failure')
                for database in (EmptySessions(), FailedSessions()):
                    self.assertEqual(asyncio.run(resolve_session(SyntheticGateway(database), 'original')),
                                     'original')

            def test_rotated_status_keeps_original_request_fingerprint_binding(self):
                value = self.store()
                value.reserve('scope', 'send', fingerprint, 'run_rotated',
                              {'status': 'queued', 'session_id': 'continued-session'},
                              owner_pid=123, owner_started=456)
                reopened = self.store()
                outcome, saved = reopened.lookup('scope', 'send', fingerprint)
                self.assertEqual(outcome, 'reused')
                self.assertEqual(saved['run_id'], 'run_rotated')
                self.assertEqual(saved['status']['session_id'], 'continued-session')
                self.assertEqual(reopened.lookup('scope', 'send', 'changed-request')[0], 'conflict')

        result = unittest.TextTestRunner(verbosity=2).run(
            unittest.defaultTestLoader.loadTestsFromTestCase(StoreQualification))
        evidence = {
            'source': str(module_path),
            'sourceSha256': hashlib.sha256(module_path.read_bytes()).hexdigest(),
            'continuationSource': str(runs_path),
            'continuationSourceSha256': hashlib.sha256(runs_path.read_bytes()).hexdigest(),
            'python': sys.executable,
            'tests': result.testsRun,
            'failures': len(result.failures),
            'errors': len(result.errors),
            'passed': result.wasSuccessful(),
            'liveGatewayRequests': 0,
            'liveStoresOpened': 0,
            'scope': 'Installed standalone store and extracted continuation resolver with synthetic data; not live gateway, actual session mapping or quiescence qualification',
        }
        (output / 'qualification.json').write_text(json.dumps(evidence, indent=2), encoding='utf-8')
        print(json.dumps(evidence))
        return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':
    raise SystemExit(main())
