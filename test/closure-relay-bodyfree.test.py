"""Pure ASGI regression of the actual production class, never its startup module."""
import ast
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
DEPENDENCIES = ROOT / 'test/app03-m4-link-runtime/Lib/site-packages'
sys.path.insert(0, str(DEPENDENCIES))

source = ROOT / 'service_roots/relay/mesh_runtime.py'
if len(sys.argv) > 1:
    if len(sys.argv) != 3 or sys.argv[1] != '--source':
        raise SystemExit('Usage: closure-relay-bodyfree.test.py [--source path]')
    source = Path(sys.argv[2]).resolve()
    if source != ROOT / '.runner/inputs/mesh_runtime-before.py':
        raise SystemExit('Only the admitted prior source is accepted')

tree = ast.parse(source.read_bytes(), filename=str(source))
classes = [node for node in tree.body if isinstance(node, ast.ClassDef)
           and node.name == 'ConfinedGate']
if len(classes) != 1:
    raise RuntimeError('Exactly one actual production ConfinedGate is required')


class ListenerAddress:
    """Address only; no socket or listener is created."""
    def getsockname(self):
        return ('127.0.0.1', 43127)


namespace = {'listener': ListenerAddress(), 'capability': 'synthetic-in-memory-only'}
exec(compile(ast.Module(body=classes, type_ignores=[]), str(source), 'exec'), namespace)
ConfinedGate = namespace['ConfinedGate']


def scope_for(method='POST', path='/api/agents/mesh/message'):
    return {'type': 'http', 'method': method, 'path': path,
            'client': ('127.0.0.1', 12345),
            'headers': [(b'host', b'127.0.0.1:43127'),
                        (b'origin', b'http://127.0.0.1:43127'),
                        (b'authorization', ('Bearer ' + namespace['capability']).encode())]}


def header(scope, name, value):
    scope['headers'] = [(key, data) for key, data in scope['headers'] if key != name]
    if value is not None:
        scope['headers'].append((name, value))


class ConfinedGateTests(unittest.TestCase):
    def invoke(self, scope):
        received, delegated, messages = [], [], []

        async def receive():
            received.append(True)
            raise AssertionError('No receive call is admitted in this pure test')

        async def send(message):
            messages.append(message)

        async def app(actual_scope, actual_receive, actual_send):
            delegated.append((actual_scope is scope, actual_receive is receive,
                              actual_send is send))

        # All admitted coroutines complete immediately in memory. No event loop,
        # socket, transport, fixture, process or production-module import is needed.
        call = ConfinedGate(app)(scope, receive, send)
        try:
            call.send(None)
        except StopIteration:
            pass
        else:
            call.close()
            self.fail('Unexpected asynchronous suspension')
        return received, delegated, messages

    def denial(self, scope):
        received, delegated, messages = self.invoke(scope)
        self.assertEqual(len(received), 0)
        self.assertEqual(len(delegated), 0)
        self.assertEqual([message['type'] for message in messages],
                         ['http.response.start', 'http.response.body'])
        self.assertEqual(messages[0]['status'], 403)
        self.assertFalse(messages[1].get('more_body', False))
        self.assertEqual(sum(len(message.get('body', b'')) for message in messages),
                         0, 'denial body must contain zero bytes')

    def delegation(self, scope):
        received, delegated, messages = self.invoke(scope)
        self.assertEqual(len(received), 0)
        self.assertEqual(delegated, [(True, True, True)])
        self.assertEqual(messages, [])


def denied_test(change):
    def check(self):
        scope = scope_for()
        change(scope)
        self.denial(scope)
    return check


denials = {
    'client_remote': lambda s: s.update(client=('192.0.2.1', 12345)),
    'client_missing': lambda s: s.pop('client'),
    'host_wrong': lambda s: header(s, b'host', b'localhost:43127'),
    'host_missing': lambda s: header(s, b'host', None),
    'host_malformed': lambda s: header(s, b'host', b'127.0.0.1:invalid'),
    'origin_wrong': lambda s: header(s, b'origin', b'https://127.0.0.1:43127'),
    'origin_missing': lambda s: header(s, b'origin', None),
    'origin_malformed': lambda s: header(s, b'origin', b'null'),
    'authorization_wrong': lambda s: header(s, b'authorization', b'Bearer wrong'),
    'authorization_missing': lambda s: header(s, b'authorization', None),
    'authorization_empty': lambda s: header(s, b'authorization', b''),
    'authorization_malformed': lambda s: header(s, b'authorization', b'Bearer'),
    'authorization_nonascii': lambda s: header(s, b'authorization', b'\xff'),
    'headers_empty': lambda s: s.update(headers=[]),
    'headers_wrong_case': lambda s: s.update(headers=[(k.upper(), v) for k, v in s['headers']]),
    'duplicate_authorization_invalid_last': lambda s: s['headers'].append((b'authorization', b'Bearer wrong')),
    'path_wrong': lambda s: s.update(path='/api/agents/mesh/message/'),
    'method_wrong': lambda s: s.update(method='GET'),
}
for name, change in denials.items():
    setattr(ConfinedGateTests, 'test_denied_' + name, denied_test(change))

for method, path in [('GET', '/'), ('GET', '/api/agents'), ('GET', '/api/auth'),
                     ('GET', '/api/agents/mesh/sessions'),
                     ('POST', '/api/agents/mesh/message')]:
    def allowed(self, method=method, path=path):
        self.delegation(scope_for(method, path))
    setattr(ConfinedGateTests, 'test_allowed_' + method + path.replace('/', '_'), allowed)

for kind in ['lifespan', 'websocket']:
    def non_http(self, kind=kind):
        self.delegation({'type': kind})
    setattr(ConfinedGateTests, 'test_non_http_' + kind, non_http)

if __name__ == '__main__':
    unittest.main(argv=[sys.argv[0]], verbosity=2)
