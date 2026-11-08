"""Build/test an isolated Relay patch. Never import the live relay_server module."""
import argparse
import ast
import asyncio
import difflib
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import sys
import tempfile
import threading
import os
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
import unittest

ROUTE = '''
@app.get("/api/agents/{aid}/outbox/{send_id}/native-run")
async def native_run_receipt(aid: str, send_id: str):
    agent = AGENTS.get(aid)
    if agent is None or agent.backend != "hermes":
        return JSONResponse({"ok": False, "error": "native receipt not found"}, status_code=404)
    try:
        receipt = await relay_native_receipts.read(SESSIONS, aid, send_id, _hermes_client(agent))
    except LookupError:
        return JSONResponse({"ok": False, "error": "native receipt not found"}, status_code=404)
    except Exception:
        return JSONResponse({"ok": False, "error": "native receipt unavailable"}, status_code=503)
    return JSONResponse({"ok": True, "receipt": receipt})


'''


def replace_once(text, old, new):
    if text.count(old) != 1:
        raise RuntimeError('Source anchor missing or ambiguous; refresh/review instead of guessing')
    return text.replace(old, new, 1)


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', required=True)
    parser.add_argument('--evidence', required=True)
    parser.add_argument('--patch', required=True)
    args = parser.parse_args()
    source = Path(args.source).resolve()
    output = Path(args.evidence).resolve()
    output.mkdir(parents=True, exist_ok=False)
    module_path = Path(__file__).with_name('relay_native_receipts.py')
    original = (source / 'relay_server.py').read_text(encoding='utf-8')
    candidate = replace_once(original, 'import relay_hermes\n',
                             'import relay_hermes\nimport relay_native_receipts\n')
    candidate = replace_once(candidate, 'from relay_sessions import SessionStore\n',
                             'from relay_sessions import SessionStore, RETENTION as RELAY_RETENTION\n')
    candidate = replace_once(candidate, 'SESSIONS = SessionStore(SESSION_DB_PATH)\n',
        '# Send receipts are recovery evidence; cleanup requires deliberate operator action.\n'
        'RELAY_RETENTION["outbox"].update(max_rows=None, max_days=None,\n'
        '    note="Durable send receipts retained for recovery; no automatic pruning")\n'
        'SESSIONS = SessionStore(SESSION_DB_PATH)\n')
    candidate = replace_once(candidate,
        'async def hermes_send(a: Agent, text: str, message_id: str = "", attachments: list | None = None):',
        'async def hermes_send(a: Agent, text: str, message_id: str = "", attachments: list | None = None, *, admission_claimed=False):')
    candidate = replace_once(candidate,
        '            await hermes_send(a, text, message_id, attachments)\n',
        '            await hermes_send(a, text, message_id, attachments, admission_claimed=claim is not None)\n')
    candidate = replace_once(candidate,
        '    await client.ensure_session(session_id, title=f"Relay · {a.name}")\n',
        '    try:\n'
        '        previous = (relay_native_receipts.binding(\n'
        '            SESSIONS, a.id, message_id, client, conversation_id=session_id,\n'
        '            for_dispatch=True, fresh_claim=admission_claimed)\n'
        '            if message_id else None)\n'
        '    except Exception as exc:\n'
        '        raise HermesError("Native admission requires reconciliation; nothing resubmitted",\n'
        '                          code="native_binding_unverified") from exc\n'
        '    if previous is None:\n'
        '        await client.ensure_session(session_id, title=f"Relay · {a.name}")\n')
    candidate = replace_once(candidate,
        '    admitted = await client.submit_run(\n'
        '        text=body,\n'
        '        session_id=session_id,\n'
        '        idempotency_key=message_id or "",\n'
        '    )\n'
        '    run_id = str(admitted["run_id"])\n',
        '    if previous is not None:\n'
        '        admitted = {"run_id": previous["runId"], "replayed": True}\n'
        '    else:\n'
        '        admitted = await client.submit_run(\n'
        '            text=body, session_id=session_id, idempotency_key=message_id or "")\n'
        '    run_id = str(admitted["run_id"])\n'
        '    if message_id:\n'
        '        try:\n'
        '            relay_native_receipts.bind(SESSIONS, a.id, session_id, message_id, run_id, client)\n'
        '        except Exception as exc:\n'
        '            raise HermesError("Native acceptance could not be saved; reconcile before retry",\n'
        '                              code="native_binding_unverified") from exc\n')
    candidate = replace_once(candidate,
        '                if a.cfg.get("demo_fallback", False):\n',
        '                if a.cfg.get("demo_fallback", False) and getattr(exc, "code", "") != "native_binding_unverified":\n')
    candidate = replace_once(candidate, '@app.get("/api/agents/{aid}/outbox")\n',
                             ROUTE + '@app.get("/api/agents/{aid}/outbox")\n')
    compile(candidate, 'relay_server.py', 'exec')
    # Preserve only explicit source files. No config, credentials, attachment,
    # conversation, native memory or live database is copied or imported.
    source_files = ('relay_a2a.py', 'relay_a2a_reconcile.py', 'relay_auth.py',
                    'relay_budget.py', 'relay_channels.py', 'relay_config.py',
                    'relay_db.py', 'relay_hermes.py', 'relay_inbox.py', 'relay_mcp.py',
                    'relay_notify.py', 'relay_openclaw.py', 'relay_sessions.py', 'relay_webpush.py')
    source_hashes = {}
    for file in source_files:
        shutil.copyfile(source / file, output / file)
        source_hashes[file] = hashlib.sha256((output / file).read_bytes()).hexdigest()
    (output / 'relay_server.py').write_text(candidate, encoding='utf-8')
    shutil.copyfile(module_path, output / module_path.name)
    patch = ''.join(difflib.unified_diff(original.splitlines(True), candidate.splitlines(True),
                                       fromfile='a/relay_server.py', tofile='b/relay_server.py'))
    new_module = module_path.read_text(encoding='utf-8')
    patch += ''.join(difflib.unified_diff([], new_module.splitlines(True),
                                        fromfile='/dev/null', tofile='b/relay_native_receipts.py'))
    Path(args.patch).write_text(patch, encoding='utf-8')
    sys.path.insert(0, str(output))
    sessions = load('synthetic_relay_sessions', output / 'relay_sessions.py')
    receipts = load('synthetic_native_receipts', output / module_path.name)
    auth = load('synthetic_relay_auth', output / 'relay_auth.py')

    class Client:
        base_url = 'http://127.0.0.1:12345'
        def __init__(self):
            self.posts = 0
            self.gets = []
            self.value = {'run_id': 'run_one', 'session_id': 'rotated-session',
                          'status': 'completed', 'output': 'private synthetic output'}
        async def run_status(self, run_id):
            self.gets.append(run_id)
            if isinstance(self.value, Exception):
                raise self.value
            return self.value
        async def require_runs_api(self):
            return {}
        async def ensure_session(self, *args, **kwargs):
            return True
        async def submit_run(self, **kwargs):
            self.posts += 1
            return {'run_id': 'run_one'}
        async def stream_events(self, run_id):
            # A crash after native acceptance must still leave the binding durable.
            raise RuntimeError('synthetic event disconnect')
            yield
        async def wait_for_terminal(self, *args, **kwargs):
            return {'status': 'completed'}

    class Qualification(unittest.TestCase):
        def setUp(self):
            self.temp = tempfile.TemporaryDirectory(dir=output)
            self.path = Path(self.temp.name) / 'synthetic.sqlite'
            self.store = sessions.SessionStore(self.path)
            self.store.outbox_enqueue('echo', 'original', 'synthetic question', idem_key='send')
            self.client = Client()
        def tearDown(self):
            self.store.db.close()
            self.temp.cleanup()
        def bind(self, run='run_one'):
            receipts.bind(self.store, 'echo', 'original', 'send', run, self.client)
        def read(self):
            return asyncio.run(receipts.read(self.store, 'echo', 'send', self.client))

        def test_exact_binding_survives_reopen_and_keeps_original_session(self):
            self.bind()
            self.store.db.close()
            self.store = sessions.SessionStore(self.path)
            saved = receipts.binding(self.store, 'echo', 'send', self.client)
            self.assertEqual(saved['runId'], 'run_one')
            self.assertEqual(saved['conversationId'], 'original')
            result = self.read()
            self.assertEqual(result['nativeSessionId'], 'rotated-session')
            self.assertEqual(result['conversationId'], 'original')
            self.assertTrue(result['terminal'])
            self.assertFalse(result['writerQuiescence'])
            self.assertNotIn('output', result)
            self.assertEqual(self.client.posts, 0)

        def test_wrong_agent_conversation_endpoint_and_run_cannot_replace_binding(self):
            self.bind()
            for agent, conv, run in [('other', 'original', 'run_one'),
                                     ('echo', 'other', 'run_one'), ('echo', 'original', 'run_two')]:
                with self.assertRaises(ValueError):
                    receipts.bind(self.store, agent, conv, 'send', run, self.client)
            self.client.base_url = 'http://127.0.0.1:54321'
            self.assertEqual(self.read()['reason'], 'binding_conflict')
            self.assertEqual(self.client.gets, [])

        def test_missing_binding_is_unknown_without_any_native_request(self):
            self.assertEqual(self.read()['reason'], 'binding_missing')
            self.assertEqual(self.client.gets, [])
            self.assertEqual(self.client.posts, 0)
            with self.assertRaises(LookupError):
                asyncio.run(receipts.read(self.store, 'other', 'send', self.client))

        def test_uncertain_prebinding_admission_is_not_resubmitted(self):
            row = self.store.outbox_get('send')
            self.store.outbox_claim(row['id'])
            with self.assertRaises(ValueError):
                receipts.binding(self.store, 'echo', 'send', self.client,
                                 conversation_id='original', for_dispatch=True)
            self.store.outbox_fail(row['id'], 'synthetic lost native acceptance')
            with self.assertRaises(ValueError):
                receipts.binding(self.store, 'echo', 'send', self.client,
                                 conversation_id='original', for_dispatch=True)
            self.assertEqual(self.client.posts, 0)

        def test_conflicting_native_identity_unavailable_and_missing_session_fail_closed(self):
            self.bind()
            for status in [{'run_id': 'run_wrong', 'status': 'completed', 'session_id': 'x'},
                           {'run_id': 'run_one', 'status': 'unavailable', 'session_id': 'x'},
                           {'run_id': 'run_one', 'status': 'completed'}, RuntimeError('offline')]:
                self.client.value = status
                observed = self.read()
                self.assertEqual(observed['observation'], 'unknown')
                self.assertFalse(observed['terminal'])
                self.assertFalse(observed['writerQuiescence'])
            self.assertEqual(self.client.posts, 0)

        def test_outbox_settlement_preserves_binding_without_changing_admission_semantics(self):
            self.bind()
            row = self.store.outbox_get('send')
            self.store.outbox_settle(row['id'], 'accepted')
            self.assertEqual(receipts.binding(self.store, 'echo', 'send', self.client)['runId'], 'run_one')
            self.assertEqual(self.store.outbox_get('send')['state'], 'accepted')

        def test_two_connections_cannot_replace_each_others_native_admission(self):
            second = sessions.SessionStore(self.path)
            ready = threading.Barrier(2)
            def attempt(item):
                store, run = item
                ready.wait(timeout=5)
                try:
                    receipts.bind(store, 'echo', 'original', 'send', run, self.client)
                    return True
                except ValueError:
                    return False
            try:
                with ThreadPoolExecutor(max_workers=2) as pool:
                    outcomes = list(pool.map(attempt, [(self.store, 'run_one'), (second, 'run_two')]))
                self.assertEqual(sorted(outcomes), [False, True])
                self.assertIn(receipts.binding(self.store, 'echo', 'send', self.client)['runId'],
                              {'run_one', 'run_two'})
            finally:
                second.db.close()

        def test_integrated_send_saves_before_stream_and_recovery_does_not_submit(self):
            tree = ast.parse(candidate)
            nodes = [n for n in tree.body if isinstance(n, ast.AsyncFunctionDef)
                     and n.name in {'hermes_send', 'run_turn'}]
            self.assertEqual(len(nodes), 2)
            agent = SimpleNamespace(id='echo', name='Echo', conversation_id='original',
                                    active_run_ids=[], status='working', is_a2a=False)
            space = {'SESSIONS': self.store, 'relay_native_receipts': receipts,
                     '_hermes_client': lambda a: self.client,
                     'relay_hermes': SimpleNamespace(split_attachments=lambda t, a, **k: (t, []),
                                                    TERMINAL_STATUSES={'completed'}),
                     'HermesError': RuntimeError,
                     'IMAGE_MIME_TYPES': set(), 'RUN_SETTLE_TIMEOUT': 1, 'asyncio': asyncio}
            for name in ('set_status', 'publish', 'feed', '_dbg', '_persist_hermes_reply'):
                space[name] = lambda *a, **k: None
            space['_apply_run_event'] = lambda *a, **k: True
            exec(compile(ast.Module(body=nodes, type_ignores=[]), 'isolated-send', 'exec'), space)
            asyncio.run(space['run_turn'](agent, 'synthetic question', 'send'))
            self.assertEqual(receipts.binding(self.store, 'echo', 'send', self.client)['runId'], 'run_one')
            self.assertEqual(self.client.posts, 1)
            asyncio.run(space['run_turn'](agent, 'synthetic question', 'send'))
            self.assertEqual(self.client.posts, 1)

        def test_actual_candidate_http_route_uses_existing_auth_and_is_read_only(self):
            from fastapi import FastAPI
            from fastapi.responses import JSONResponse
            import httpx
            tree = ast.parse(candidate)
            wanted = {'AuthGate', '_authorized', '_headers_from_scope', 'native_run_receipt'}
            nodes = [n for n in tree.body if isinstance(n, (ast.ClassDef, ast.FunctionDef,
                                                          ast.AsyncFunctionDef)) and n.name in wanted]
            self.assertEqual({n.name for n in nodes}, wanted)
            app = FastAPI()
            key = 'synthetic-test-key-not-an-operator-credential'
            client_lookups = []
            def lookup_native(agent):
                client_lookups.append(agent)
                return self.client
            space = {'app': app, 'AUTH_ENABLED': True, 'AUTH_TOKEN': key,
                     'AUTH_OPEN_PATHS': frozenset({'/api/auth', '/api/unlock'}),
                     'relay_auth': auth, 'JSONResponse': JSONResponse,
                     'AGENTS': {'echo': SimpleNamespace(backend='hermes', is_a2a=False),
                                'tripp': SimpleNamespace(backend='openclaw', is_a2a=False),
                                'dsh': SimpleNamespace(backend='a2a', is_a2a=True)}, 'SESSIONS': self.store,
                     'relay_native_receipts': receipts, '_hermes_client': lookup_native}
            exec(compile(ast.Module(body=nodes, type_ignores=[]), 'isolated-http', 'exec'), space)
            app.add_middleware(space['AuthGate'])
            self.bind()
            before = self.store.db.total_changes
            async def exercise():
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                             base_url='http://synthetic') as client:
                    route = '/api/agents/echo/outbox/send/native-run'
                    for headers in ({}, {'Authorization': 'Bearer wrong'}):
                        self.assertEqual((await client.get(route, headers=headers)).status_code, 401)
                    self.assertEqual(self.client.gets, [])
                    valid = {'Authorization': 'Bearer ' + key}
                    response = await client.get(route, headers=valid)
                    self.assertEqual(response.status_code, 200)
                    body = response.json()['receipt']
                    self.assertEqual(body['runId'], 'run_one')
                    self.assertEqual(body['nativeSessionId'], 'rotated-session')
                    self.assertFalse(body['writerQuiescence'])
                    self.assertNotIn('private synthetic output', response.text)
                    self.assertEqual((await client.get('/api/agents/echo/outbox/missing/native-run',
                                                       headers=valid)).status_code, 404)
                    self.assertEqual((await client.get('/api/agents/other/outbox/send/native-run',
                                                       headers=valid)).status_code, 404)
                    reads_before = len(self.client.gets)
                    lookups_before = len(client_lookups)
                    for agent in ('tripp', 'dsh'):
                        self.assertEqual((await client.get(f'/api/agents/{agent}/outbox/send/native-run',
                                                           headers=valid)).status_code, 404)
                    self.assertEqual(len(self.client.gets), reads_before)
                    self.assertEqual(len(client_lookups), lookups_before)
                    self.assertEqual((await client.post(route, headers=valid)).status_code, 405)
            asyncio.run(exercise())
            self.assertEqual(self.store.db.total_changes, before)
            self.assertEqual(self.client.posts, 0)

        def test_complete_server_import_startup_native_http_binding_and_shutdown(self):
            import httpx
            # All app state/credentials here are synthetic; never import the live
            # server or let its background loops open the real native state store.
            config_path = output / 'synthetic-config.json'
            key_path = output / 'synthetic-relay.key'
            key_path.write_text('synthetic-relay-access', encoding='utf-8')
            config_path.write_text(json.dumps({'agents': {'echo': {
                'name': 'Synthetic Echo', 'backend': 'hermes', 'device': 'fixture',
                'url': 'http://synthetic-native', 'api_key': 'synthetic-native-access',
                'demo_fallback': False}}, 'notifications': {}}), encoding='utf-8')
            (output / 'static').mkdir(exist_ok=True)
            overrides = {'RELAY_CONFIG_PATH': str(config_path),
                         'RELAY_SESSION_DB': str(output / 'synthetic-full-server.sqlite'),
                         'RELAY_AUTH_KEY_FILE': str(key_path), 'RELAY_SKIP_OPENCLAW': '1',
                         'RELAY_ARTIFACTS_DIR': str(output / 'synthetic-artifacts'),
                         'RELAY_ATTACHMENT_STORE': str(output / 'synthetic-attachments')}
            previous = {k: os.environ.get(k) for k in overrides}
            os.environ.update(overrides)
            enabled = [True]
            # Windows creates its private wake-up socketpair while constructing
            # an event loop. Construct it before blocking all application connects.
            loop = asyncio.new_event_loop()
            library_roots = [Path(sys.prefix).resolve(), Path(sys.base_prefix).resolve()]
            def inside(path, root):
                return path == root or path.is_relative_to(root)
            def audit(event, args):
                if not enabled[0]:
                    return
                if event in {'socket.connect', 'socket.getaddrinfo', 'subprocess.Popen', 'os.system',
                             'os.startfile', 'os.startfile/2'}:
                    raise RuntimeError('Isolated qualification forbids network/process launches')
                if event == 'open' and not isinstance(args[0], int):
                    path = Path(args[0]).resolve()
                    mode = str(args[1] or '')
                    flags = int(args[2] or 0)
                    writing = any(ch in mode for ch in 'wax+') or bool(
                        flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND))
                    allowed = inside(path, output) or (not writing and any(
                        inside(path, root) for root in library_roots))
                    if not allowed:
                        raise RuntimeError('Isolated qualification refused external file access')
            sys.addaudithook(audit)
            server = None
            native_posts = []
            native_reads = []
            try:
                # Seed a real expired accepted receipt before the complete server
                # initializes its store. Startup and later prune must retain it.
                seed = sessions.SessionStore(output / 'synthetic-full-server.sqlite')
                receipt_session = seed.ensure_agent('echo')['id']
                expired = seed.outbox_enqueue('echo', receipt_session, 'synthetic historical send',
                                              idem_key='historical-send')
                seed.outbox_settle(expired['id'], 'accepted')
                with seed.db:
                    seed.db.execute("UPDATE outbox SET created_at='2000-01-01T00:00:00+00:00', "
                                    "updated_at='2000-01-01T00:00:00+00:00' WHERE id=?", (expired['id'],))
                seed.close()
                server = load('synthetic_complete_relay_server', output / 'relay_server.py')
                self.assertTrue(server.AUTH_ENABLED)
                self.assertEqual(Path(server.SESSION_DB_PATH).resolve().parent, output)
                self.assertEqual(set(server.AGENTS), {'echo'})
                self.assertEqual(server.NOTIFIER.channels, {})
                self.assertIsNotNone(server.SESSIONS.outbox_get('historical-send'))
                server.SESSIONS.prune()
                self.assertIsNotNone(server.SESSIONS.outbox_get('historical-send'))
                agent = server.AGENTS['echo']
                original_session = agent.conversation_id
                def native_http(request):
                    if request.method == 'POST' and request.url.path == '/v1/runs':
                        native_posts.append({'id': request.headers.get('Idempotency-Key'),
                                             'body': json.loads(request.content)})
                        return httpx.Response(202, json={'run_id': 'run_full', 'status': 'started'})
                    native_reads.append(request.url.path)
                    if request.url.path == '/v1/capabilities':
                        return httpx.Response(200, json={'features': {
                            'run_submission': True, 'run_status': True, 'run_events_sse': True}})
                    if request.url.path.startswith('/api/sessions/'):
                        return httpx.Response(200, json={'id': original_session})
                    if request.url.path == '/v1/runs/run_full/events':
                        payload = {'run_id': 'run_full', 'event': 'run.completed',
                                   'output': 'synthetic private answer'}
                        return httpx.Response(200, headers={'content-type': 'text/event-stream'},
                                              text='data: ' + json.dumps(payload) + '\n\n')
                    if request.url.path == '/v1/runs/run_full':
                        return httpx.Response(200, json={'run_id': 'run_full', 'status': 'completed',
                                                        'session_id': 'rotated-full-session',
                                                        'output': 'synthetic private answer'})
                    raise AssertionError('Unexpected synthetic native request')
                async def exercise():
                    native = server.HermesRunsClient('http://synthetic-native',
                                                      api_key='synthetic-native-access')
                    native._client = httpx.AsyncClient(transport=httpx.MockTransport(native_http))
                    agent.hermes = native
                    async with server.app.router.lifespan_context(server.app):
                        await asyncio.sleep(0)
                        self.assertTrue(all(task is not None and not task.done() for task in (
                            server.WATCHDOG_TASK, server.HERMES_DESKTOP_TASK, server.NOTIFICATION_TASK)))
                        store = server.SESSIONS
                        store.outbox_enqueue('echo', original_session, 'full synthetic send',
                                             idem_key='full-send')
                        await server.run_turn(agent, 'full synthetic send', 'full-send')
                        self.assertEqual(len(native_posts), 1)
                        # A real queue retry must report the uncertainty without
                        # an unhandled task or synthetic demo "success".
                        uncertain = store.outbox_enqueue('echo', original_session, 'lost synthetic send',
                                                         idem_key='lost-send')
                        store.outbox_claim(uncertain['id'])
                        store.outbox_fail(uncertain['id'], 'synthetic lost acceptance')
                        async def forbid_demo(*args, **kwargs):
                            raise AssertionError('Uncertain admission must not fall back to a demo')
                        server.demo_run = forbid_demo
                        agent.cfg['demo_fallback'] = True
                        agent.message_queue.append(('lost synthetic send', [], 'lost-send'))
                        await server.drain_hermes_messages(agent)
                        self.assertEqual(agent.status, 'stopped')
                        self.assertIsNone(agent.run_task)
                        self.assertEqual(len(native_posts), 1)
                        self.assertEqual(native_posts[0]['id'], 'full-send')
                        self.assertEqual(native_posts[0]['body']['session_id'], original_session)
                        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app),
                                                     base_url='http://synthetic-relay') as client:
                            route = '/api/agents/echo/outbox/full-send/native-run'
                            self.assertEqual((await client.get(route)).status_code, 401)
                            response = await client.get(route, headers={
                                'Authorization': 'Bearer synthetic-relay-access'})
                            self.assertEqual(response.status_code, 200)
                            receipt = response.json()['receipt']
                            self.assertEqual(receipt['conversationId'], original_session)
                            self.assertEqual(receipt['nativeSessionId'], 'rotated-full-session')
                            self.assertEqual(receipt['runId'], 'run_full')
                            self.assertFalse(receipt['writerQuiescence'])
                            self.assertNotIn('synthetic private answer', response.text)
                        await server.run_turn(agent, 'full synthetic send', 'full-send')
                        self.assertEqual(len(native_posts), 1)
                    self.assertTrue(all(task is None for task in (server.WATCHDOG_TASK,
                        server.HERMES_DESKTOP_TASK, server.NOTIFICATION_TASK)))
                loop.run_until_complete(exercise())
                self.assertIn('/v1/runs/run_full', native_reads)
            finally:
                if server is not None:
                    server.SESSIONS.close()
                loop.run_until_complete(loop.shutdown_asyncgens())
                loop.run_until_complete(loop.shutdown_default_executor())
                enabled[0] = False
                loop.close()
                for key, value in previous.items():
                    if value is None:
                        os.environ.pop(key, None)
                    else:
                        os.environ[key] = value

    result = unittest.TextTestRunner(verbosity=2).run(
        unittest.defaultTestLoader.loadTestsFromTestCase(Qualification))
    proof = {'passed': result.wasSuccessful(), 'tests': result.testsRun,
             'failures': len(result.failures), 'errors': len(result.errors),
             'baselineServerSha256': hashlib.sha256(original.encode()).hexdigest(),
             'candidateServerSha256': hashlib.sha256(candidate.encode()).hexdigest(),
             'copiedSourceSha256': source_hashes,
             'liveServiceChanges': 0, 'liveRequests': 0,
             'limitations': ['Not deployed', 'Native HTTP is synthetic, not live Hermes qualification',
                             'No writer-quiescence claim', 'Lost admission before binding remains unknown']}
    (output / 'qualification.json').write_text(json.dumps(proof, indent=2), encoding='utf-8')
    print(json.dumps(proof))
    return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':
    raise SystemExit(main())
