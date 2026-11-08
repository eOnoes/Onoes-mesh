import copy
import unittest
from integrations.relay_writer_observation import project


def native_observation():
    run = 'run_' + 'a' * 32
    generation = '22222222-2222-4222-8222-222222222222'
    return {'schema': 'mesh-native-writer-observation/v1', 'runId': run, 'observedAt': 1000,
        'ownerId': '11111111-1111-4111-8111-111111111111', 'state': 'observed',
        'observationOnly': True, 'writerQuiescence': False,
        'enrollment': {'schema': 'mesh-native-writer-enrollment/v1', 'state': 'enrolled',
            'runId': run, 'generation': generation, 'writerQuiescence': False,
            'lifetime': {'schema': 'mesh-managed-writer-lifetime/v1', 'runId': run, 'generation': generation,
                'managedWorkEnded': True, 'rootEnded': True, 'writerQuiescence': False, 'reason': '',
                'pendingWorkers': [], 'processTree': {'state': 'ended', 'sealed': True, 'activeProcesses': 0},
                'toolEffects': {'observedCalls': 2, 'activeCalls': 0, 'unverifiedCalls': 2}}}}


class RelayWriterObservationTests(unittest.TestCase):
    def test_local_completion_keeps_unverified_effects_and_drops_private_fields(self):
        observation = native_observation()
        observation['privateOutput'] = 'must not cross bridge'
        result = project(observation, observation['runId'])
        self.assertEqual(result['state'], 'observed')
        self.assertTrue(result['localWorkEnded'])
        self.assertEqual(result['unverifiedToolCalls'], 2)
        self.assertFalse(result['writerQuiescence'])
        self.assertNotIn('must not cross bridge', str(result))

    def test_crossed_run_generation_and_inconsistent_completion_stay_unknown(self):
        original = native_observation()
        variants = []
        changed = copy.deepcopy(original); changed['runId'] = 'run_other'; variants.append(changed)
        changed = copy.deepcopy(original); changed['enrollment']['lifetime']['generation'] = 'different'; variants.append(changed)
        changed = copy.deepcopy(original); changed['enrollment']['lifetime']['processTree']['activeProcesses'] = 1; variants.append(changed)
        changed = copy.deepcopy(original); changed['enrollment']['lifetime']['toolEffects']['activeCalls'] = True; variants.append(changed)
        changed = copy.deepcopy(original); changed['writerQuiescence'] = True; variants.append(changed)
        for observation in variants:
            with self.subTest(observation=observation):
                result = project(observation, original['runId'])
                self.assertEqual(result['state'], 'unknown')
                self.assertFalse(result['localWorkEnded'])
                self.assertFalse(result['writerQuiescence'])

    def test_missing_and_restarted_observations_cannot_recover_completion(self):
        for observation in [None, {}, {**native_observation(), 'state': 'unknown', 'enrollment': None}]:
            result = project(observation, 'run_' + 'a' * 32)
            self.assertEqual(result['state'], 'unknown')
            self.assertIsNone(result['generation'])
            self.assertFalse(result['localWorkEnded'])


def qualify(source):
    """Actual patched Relay reader, real synthetic SQLite binding, fixture native client."""
    import asyncio
    import hashlib
    import importlib.util
    import json
    from pathlib import Path
    import sqlite3
    import sys
    from unittest.mock import patch
    from integrations.prepare_relay_writer_observation import prepare, BASELINE
    root = prepare(source)
    spec = importlib.util.spec_from_file_location('relay_receipt_fixture', root / 'relay_native_receipts.py')
    module = importlib.util.module_from_spec(spec)
    from integrations import relay_writer_observation
    with patch.dict(sys.modules, {'relay_writer_observation': relay_writer_observation}):
        spec.loader.exec_module(module)
    run = 'run_' + 'a' * 32
    calls = []
    class Client:
        base_url = 'http://127.0.0.1:9'
        async def run_status(self, key):
            calls.append(key)
            return {'run_id': run, 'status': 'completed', 'session_id': 'rotated-fixture',
                    'writer_lifecycle': native_observation(), 'output': 'private fixture output'}
    client = Client()
    db = sqlite3.connect(root / 'synthetic-outbox.sqlite')
    db.execute('CREATE TABLE outbox (idem_key TEXT,agent_id TEXT,session_id TEXT,transport_ref TEXT)')
    reference = module.PREFIX + json.dumps({'runId': run, 'gateway': module.gateway_identity(client)})
    db.execute('INSERT INTO outbox VALUES (?,?,?,?)', ('send-fixture', 'echo', 'original-fixture', reference))
    db.commit(); db.close()
    class Store:
        def __init__(self):
            self.db = sqlite3.connect(root / 'synthetic-outbox.sqlite'); self.db.row_factory = sqlite3.Row
        def outbox_get(self, key):
            row = self.db.execute('SELECT * FROM outbox WHERE idem_key=?', (key,)).fetchone()
            return dict(row) if row else None
    for attempt in range(2):
        store = Store()
        result = asyncio.run(module.read(store, 'echo', 'send-fixture', client)); store.db.close()
        assert result['conversationId'] == 'original-fixture' and result['runId'] == run
        assert result['writerLifecycle']['localWorkEnded'] is True and result['writerQuiescence'] is False
        assert 'private fixture output' not in json.dumps(result)
    (root / 'qualified-receipt.json').write_text(json.dumps(result), encoding='utf-8')
    store = Store()
    try:
        asyncio.run(module.read(store, 'other', 'send-fixture', client))
    except LookupError:
        pass
    else:
        raise AssertionError('Crossed agent accepted')
    finally:
        store.db.close()
    assert calls == [run, run]
    report = {'state': 'candidate_only', 'qualification': 'PASS', 'liveInstallation': False,
              'sourceBaseline': BASELINE, 'checks': ['exact_saved_SQLite_send_read', 'reopened_same_binding',
              'rotated_session_preserves_conversation', 'cross_agent_refused_before_read', 'metadata_only_no_release'],
              'files': {name: hashlib.sha256((root / name).read_bytes()).hexdigest()
                        for name in ['relay_native_receipts.py', 'relay_writer_observation.py']}}
    (root / 'qualification.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    return root


if __name__ == '__main__':
    import sys
    if len(sys.argv) == 3 and sys.argv[1] == '--qualify':
        print(qualify(sys.argv[2]))
    else:
        unittest.main()
