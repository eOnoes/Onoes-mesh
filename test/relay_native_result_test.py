"""Isolated Relay diagnostic acceptance; no gateway/config imports or live I/O."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import unittest

SOURCE = Path(__file__).resolve().parents[1] / 'integrations/relay-result-evidence/relay_native_receipts.py'
SPEC = importlib.util.spec_from_file_location('candidate_native_receipts', SOURCE)
receipts = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(receipts)


class Store:
    def __init__(self, row):
        self.row = row

    def outbox_get(self, send_id):
        return copy.deepcopy(self.row) if send_id == 'own-send' else None


class Client:
    base_url = 'http://127.0.0.1:1'

    def __init__(self, payload):
        self.payload, self.calls = payload, []

    async def run_status(self, run_id):
        self.calls.append(run_id)
        if isinstance(self.payload, Exception):
            raise self.payload
        return copy.deepcopy(self.payload)


class ResultEvidenceTests(unittest.IsolatedAsyncioTestCase):
    async def observe(self, **changes):
        payload = {'run_id': 'run_own', 'session_id': 'own-conversation',
                   'status': 'completed', 'output': 'Own answer 🟢\n'}
        payload.update(changes)
        client = Client(payload)
        row = {'agent_id': 'echo', 'session_id': 'own-conversation',
               'transport_ref': receipts.PREFIX + json.dumps({
                   'runId': 'run_own', 'gateway': receipts.gateway_identity(client)})}
        store = Store(row)
        before = copy.deepcopy(row)
        result = await receipts.read(store, 'echo', 'own-send', client)
        self.assertEqual(client.calls, ['run_own'])
        self.assertEqual(store.row, before)
        self.assertFalse(result['writerQuiescence'])
        self.assertNotIn('Own answer', json.dumps(result))
        return result

    async def test_exact_unicode_result_digest_and_no_content(self):
        result = await self.observe()
        output = 'Own answer 🟢\n'
        self.assertEqual(result['resultEvidence'], {
            'available': True, 'encoding': 'utf-8',
            'sha256': hashlib.sha256(output.encode()).hexdigest(),
            'characters': len(output), 'bytes': len(output.encode())})
        self.assertTrue(result['terminal'])

    async def test_different_run_does_not_produce_evidence(self):
        result = await self.observe(run_id='run_other')
        self.assertEqual(result['reason'], 'native_identity_or_status_unverified')
        self.assertNotIn('resultEvidence', result)

    async def test_other_session_does_not_produce_digest(self):
        result = await self.observe(session_id='other-conversation')
        self.assertEqual(result['resultEvidence'], {
            'available': False, 'reason': 'native_session_mismatch'})

    async def test_running_output_is_not_final(self):
        result = await self.observe(status='running')
        self.assertFalse(result['terminal'])
        self.assertEqual(result['resultEvidence']['reason'], 'native_run_not_terminal')

    async def test_empty_terminal_output_has_exact_digest(self):
        result = await self.observe(output='')
        self.assertEqual(result['resultEvidence']['sha256'], hashlib.sha256(b'').hexdigest())

    async def test_structured_output_is_not_coerced(self):
        result = await self.observe(output={'text': 'sensitive content'})
        self.assertEqual(result['resultEvidence']['reason'], 'native_output_not_text')
        self.assertNotIn('sensitive content', json.dumps(result))

    async def test_missing_output_has_no_digest(self):
        result = await self.observe(output=None)
        self.assertFalse(result['resultEvidence']['available'])

    async def test_ascii_size_limit(self):
        result = await self.observe(output='x' * 1_048_577)
        self.assertEqual(result['resultEvidence']['reason'], 'native_output_too_large')

    async def test_unicode_byte_limit(self):
        result = await self.observe(output='🟢' * 262_145)
        self.assertEqual(result['resultEvidence']['reason'], 'native_output_too_large')

    async def test_invalid_unicode_is_unavailable(self):
        result = await self.observe(output='\ud800')
        self.assertEqual(result['resultEvidence']['reason'], 'native_output_invalid_utf8')

    async def test_invalid_native_status_has_no_digest(self):
        result = await self.observe(status='invented')
        self.assertNotIn('resultEvidence', result)
        self.assertFalse(result['terminal'])

    async def test_no_dispatch_for_missing_or_wrong_agent(self):
        client = Client({})
        store = Store({'agent_id': 'other', 'session_id': 'other'})
        with self.assertRaises(LookupError):
            await receipts.read(store, 'echo', 'own-send', client)
        with self.assertRaises(LookupError):
            await receipts.read(store, 'echo', 'unknown-send', client)
        self.assertEqual(client.calls, [])

    async def test_missing_binding_never_queries_or_submits(self):
        client = Client({})
        result = await receipts.read(Store({'agent_id': 'echo', 'session_id': 'own-conversation'}),
                                     'echo', 'own-send', client)
        self.assertEqual(result['reason'], 'binding_missing')
        self.assertEqual(client.calls, [])

    async def test_native_failure_keeps_unknown_outcome(self):
        client = Client(RuntimeError('private error content'))
        row = {'agent_id': 'echo', 'session_id': 'own-conversation',
               'transport_ref': receipts.PREFIX + json.dumps({
                   'runId': 'run_own', 'gateway': receipts.gateway_identity(client)})}
        result = await receipts.read(Store(row), 'echo', 'own-send', client)
        self.assertEqual(result['reason'], 'native_read_unavailable')
        self.assertFalse(result['terminal'])
        self.assertNotIn('private error', json.dumps(result))


if __name__ == '__main__':
    unittest.main()
