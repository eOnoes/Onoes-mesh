import asyncio
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest

from integrations.native_gateway_transport import WorkerReceiptUnavailable, require_loopback, require_worker_receipt, validate_frame

ROOT = Path(__file__).resolve().parents[1]


class ProtocolTests(unittest.TestCase):
    def test_receipt_by_admission_or_without_retirement_cannot_replace_exact_lookup(self):
        params = type('Params', (), {'__annotations__': dict.fromkeys(['session_id', 'submission_id', 'include_result'])})
        result = type('Result', (), {'__annotations__': dict.fromkeys(['found', 'session_id', 'submission_id',
                                                                      'profile_contract', 'receipt', 'outcome'])})
        lookup = SimpleNamespace(params=params, result=result)
        for catalog in ({'prompt.receipt': lookup}, {'prompt.lookup': lookup}):
            with self.assertRaises(WorkerReceiptUnavailable):
                require_worker_receipt(catalog)

    def test_only_bounded_monotonic_allowed_requests(self):
        valid = {'id': 1, 'method': 'prompt.lookup', 'params': {}}
        self.assertEqual(validate_frame(json.dumps(valid), 0), valid)
        for change in ({'id': True}, {'id': 0}, {'id': 2**53}, {'method': 'permissions.grant'},
                       {'params': []}, {'unexpected': 'field'}):
            with self.subTest(change=change), self.assertRaises((ValueError, TypeError)):
                validate_frame(json.dumps({**valid, **change}), 0)
        with self.assertRaises(ValueError):
            validate_frame(json.dumps(valid), 1)
        with self.assertRaises(ValueError):
            validate_frame(b'x' * (1024 * 1024 + 1), 0)

    def test_remote_credentialed_and_malformed_targets_are_refused(self):
        require_loopback('http://127.0.0.1:1234', 'http')
        for target in ('http://example.invalid:1234', 'http://localhost:1234',
                       'http://user:secret@127.0.0.1:1234', 'https://127.0.0.1:1234',
                       'http://127.0.0.1:1234?token=x', 'http://127.0.0.1:1234#x',
                       'http://127.0.0.1', 'http://127.0.0.1:bad'):
            with self.subTest(target=target), self.assertRaises(ValueError):
                require_loopback(target, 'http')


def prepare_runtime(root, origin):
    native, home = root / 'native', root / 'home'
    package = native / 'hermes_cli'
    package.mkdir(parents=True)
    home.mkdir()
    (home / 'origin').write_text(origin)
    (package / '__init__.py').write_text('')
    contracts = native / 'tui_gateway' / 'contracts'
    contracts.mkdir(parents=True)
    for directory in (contracts.parent, contracts):
        (directory / '__init__.py').write_text('')
    (contracts / 'registry.py').write_text('''from types import SimpleNamespace
class Request:
    session_id: str
    submission_id: str
    include_result: bool
class Response(Request):
    found: bool
    profile_contract: dict
    receipt: dict
    outcome: str
    process_scope: dict
CANONICAL_METHODS = {'prompt.lookup': SimpleNamespace(params=Request, result=Response)}
''')
    (package / 'gateway_runtime.py').write_text('''from types import SimpleNamespace
def discover_gateway_endpoint(home, timeout=5):
    (home/'discovery-requested').touch()
    return SimpleNamespace(state='ready',endpoint=SimpleNamespace(api_origin=(home/'origin').read_text()))
''')
    (package / 'gateway_client.py').write_text('''def _session_ticket(home, endpoint, **kwargs):
    (home/'ticket-requested').write_text('synthetic-only')
    return 'synthetic-ticket'
def gateway_ws_target(endpoint, ticket):
    return endpoint.api_origin.replace('http:', 'ws:')+'/api/ws', ['mesh-fixture-v1','ticket.'+ticket]
''')
    return native, home


class ProcessTests(unittest.IsolatedAsyncioTestCase):
    async def test_missing_receipt_holds_node_transport_before_discovery(self):
        with tempfile.TemporaryDirectory(prefix='mesh-native-version-') as directory:
            native, home = prepare_runtime(Path(directory), 'http://127.0.0.1:1')
            (native / 'tui_gateway/contracts/registry.py').write_text('CANONICAL_METHODS = {}')
            module = (ROOT / 'lib/native-gateway-transport.mjs').as_uri()
            script = f"""import assert from 'node:assert/strict';
import {{createNativeGatewayTransport}} from {json.dumps(module)};
const t=createNativeGatewayTransport({{nativeRoot:process.argv[1],home:process.argv[2],pythonExecutable:process.argv[3]}});
try {{
  const receiptHold = e => e.status === 409 && /compatible Hermes worker receipt/.test(e.message);
  await assert.rejects(t.rpc('session.create', {{request_id:'fixture'}}), receiptHold);
  await assert.rejects(t.rpc('prompt.submit', {{submission_id:'fixture'}}), receiptHold);
}} finally {{ await t.close(); }}"""
            process = await asyncio.create_subprocess_exec('node', '--input-type=module', '-e', script,
                str(native), str(home), sys.executable, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
            _, stderr = await asyncio.wait_for(process.communicate(), 12)
            self.assertEqual(process.returncode, 0, stderr.decode(errors='replace'))
            self.assertFalse((home / 'discovery-requested').exists())
            self.assertFalse((home / 'ticket-requested').exists())

    async def test_real_node_python_websocket_roundtrip_and_uncertain_disconnect(self):
        from aiohttp import web
        calls, connections = [], []

        async def handler(request):
            connections.append(True)
            self.assertIn('ticket.synthetic-ticket', request.headers.get('Sec-WebSocket-Protocol', ''))
            ws = web.WebSocketResponse(protocols=['mesh-fixture-v1'])
            await ws.prepare(request)
            async for message in ws:
                frame = json.loads(message.data)
                calls.append(frame)
                if frame['params'].get('drop'):
                    await ws.close()
                    break
                if frame['params'].get('refuse'):
                    await ws.send_json({'id': frame['id'], 'error': {'message': 'private-ticket-fixture'}})
                else:
                    await ws.send_json({'id': frame['id'], 'result': {'original': frame['params']}})
            return ws

        app = web.Application()
        app.router.add_get('/api/ws', handler)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, '127.0.0.1', 0)
        await site.start()
        port = site._server.sockets[0].getsockname()[1]
        try:
            with tempfile.TemporaryDirectory(prefix='mesh-native-transport-') as directory:
                native, home = prepare_runtime(Path(directory), f'http://127.0.0.1:{port}')
                module = (ROOT / 'lib/native-gateway-transport.mjs').as_uri()
                script = f'''import assert from 'node:assert/strict';
import {{createNativeGatewayTransport}} from {json.dumps(module)};
const t=createNativeGatewayTransport({{nativeRoot:process.argv[1],home:process.argv[2],pythonExecutable:process.argv[3],timeoutMs:10000}});
try{{
 const original=await t.rpc('session.create',{{request_id:'fixed-original'}});
 assert.equal(original.original.request_id,'fixed-original');
 await assert.rejects(t.rpc('prompt.lookup',{{refuse:true}}),e=>!e.message.includes('private-ticket-fixture'));
 await assert.rejects(t.rpc('prompt.submit',{{submission_id:'original-submit',drop:true}}),/nothing was replayed/);
 await assert.rejects(t.rpc('prompt.submit',{{submission_id:'original-submit'}}),/nothing was replayed/);
}}finally{{await t.close();}}
console.log('transport fixture PASS; owned helper exit confirmed');'''
                process = await asyncio.create_subprocess_exec('node', '--input-type=module', '-e', script,
                    str(native), str(home), sys.executable, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
                try:
                    stdout, stderr = await asyncio.wait_for(process.communicate(), 20)
                except BaseException:
                    if process.returncode is None:
                        process.kill()
                    await process.wait()
                    raise
                self.assertEqual(process.returncode, 0, stderr.decode(errors='replace'))
                self.assertIn(b'owned helper exit confirmed', stdout)
                self.assertNotIn(b'private-ticket-fixture', stdout + stderr)
                self.assertEqual(len(connections), 1)
                self.assertEqual([call['method'] for call in calls], ['session.create', 'prompt.lookup', 'prompt.submit'])
                self.assertEqual(calls[-1]['params']['submission_id'], 'original-submit')
                self.assertTrue((home / 'ticket-requested').exists())
        finally:
            await runner.cleanup()

    async def test_remote_discovery_is_refused_before_requesting_a_ticket(self):
        with tempfile.TemporaryDirectory(prefix='mesh-native-deny-') as directory:
            native, home = prepare_runtime(Path(directory), 'http://example.invalid:1234')
            process = await asyncio.create_subprocess_exec(sys.executable,
                str(ROOT / 'integrations/native_gateway_transport.py'), '--native-root', str(native), '--home', str(home),
                stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
            stdout, stderr = await asyncio.wait_for(process.communicate(b''), 10)
            self.assertEqual(process.returncode, 1)
            self.assertEqual(json.loads(stdout)['type'], 'fatal')
            self.assertFalse((home / 'ticket-requested').exists())
            self.assertNotIn(b'example.invalid', stdout + stderr)


if __name__ == '__main__':
    unittest.main()
