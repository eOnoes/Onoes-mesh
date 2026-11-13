from copy import copy
from pathlib import Path
import queue
import socket
import subprocess
import sys
import threading
import unittest

from integrations.native_transport_hold import hold_loopback_transports, assert_loopback_hold


ROOT = Path(__file__).resolve().parents[1]
PROTECTED = {3081, 4123, 4320, 8452, 8453, 8642}


def seed():
    handle = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    handle.bind(('127.0.0.1', 0))
    if handle.getsockname()[1] in PROTECTED:
        handle.close()
        raise RuntimeError('Fixture must not use an application port.')
    return handle


@unittest.skipUnless(sys.platform == 'win32', 'Actual Windows socket semantics required')
class NativeTransportHoldTests(unittest.TestCase):
    def competitor(self, endpoint, option):
        code = '''import json,socket,sys
address,port,option=sys.argv[1],int(sys.argv[2]),sys.argv[3]
s=socket.socket(socket.AF_INET6 if ':' in address else socket.AF_INET,socket.SOCK_STREAM)
try:
 if option!='none':s.setsockopt(socket.SOL_SOCKET,getattr(socket,option),1)
 try:s.bind((address,port));print(json.dumps({'blocked':False}))
 except OSError as e:print(json.dumps({'blocked':True,'error':e.winerror}))
finally:s.close()
'''
        import json
        result = subprocess.run([sys.executable, '-c', code, endpoint[0], str(endpoint[1]), option],
                                capture_output=True, text=True, timeout=10,
                                creationflags=subprocess.CREATE_NO_WINDOW)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_hold_blocks_real_peer_binds_and_connections_without_listening(self):
        handle = seed()
        endpoint = handle.getsockname()
        handle.close()
        with hold_loopback_transports([endpoint]) as lease:
            proof = assert_loopback_hold(lease, [endpoint])
            self.assertFalse(proof['workerRetirementEstablished'])
            self.assertFalse(proof['coversDirectExecution'])
            for option in ['none', 'SO_REUSEADDR', 'SO_EXCLUSIVEADDRUSE']:
                with self.subTest(option=option):
                    result = self.competitor(endpoint, option)
                    self.assertTrue(result['blocked'])
                    self.assertIn(result['error'], [10013, 10048])
            with self.assertRaises(OSError):
                socket.create_connection(endpoint, timeout=1)
        self.assertFalse(self.competitor(endpoint, 'SO_EXCLUSIVEADDRUSE')['blocked'])

    def test_existing_listener_is_refused_and_remains_usable(self):
        with seed() as original:
            original.listen(1)
            endpoint = original.getsockname()
            with self.assertRaises(OSError):
                with hold_loopback_transports([endpoint]):
                    self.fail('Must not displace an original listener')
            with socket.create_connection(endpoint, timeout=1) as client:
                client.sendall(b'owned-fixture')
                original.settimeout(1)
                connection, _ = original.accept()
                with connection:
                    connection.settimeout(1)
                    self.assertEqual(connection.recv(32), b'owned-fixture')

    def test_partial_acquisition_rolls_back_only_its_own_sockets(self):
        handles = sorted([seed(), seed()], key=lambda value: value.getsockname()[1])
        free, original = handles
        endpoint, occupied = free.getsockname(), original.getsockname()
        free.close()
        try:
            original.listen(1)
            with self.assertRaises(OSError):
                with hold_loopback_transports([endpoint, occupied]):
                    self.fail('Partial acquisition must never yield a lease')
            self.assertFalse(self.competitor(endpoint, 'SO_EXCLUSIVEADDRUSE')['blocked'])
            self.assertTrue(self.competitor(occupied, 'SO_EXCLUSIVEADDRUSE')['blocked'])
        finally:
            original.close()

    def test_exact_private_lease_scope_thread_and_lifetime(self):
        handle = seed()
        endpoint = handle.getsockname()
        handle.close()
        with hold_loopback_transports([endpoint]) as lease:
            for invalid in [object(), copy(lease), assert_loopback_hold(lease, [endpoint])]:
                with self.assertRaises(RuntimeError):
                    assert_loopback_hold(invalid, [endpoint])
            with self.assertRaises(RuntimeError):
                assert_loopback_hold(lease, [('::1', endpoint[1])])
            results = queue.Queue()
            def other_thread():
                try:
                    assert_loopback_hold(lease, [endpoint])
                except RuntimeError:
                    results.put('refused')
            thread = threading.Thread(target=other_thread, daemon=True)
            thread.start()
            thread.join(2)
            self.assertFalse(thread.is_alive())
            self.assertEqual(results.get(timeout=1), 'refused')
        with self.assertRaises(RuntimeError):
            assert_loopback_hold(lease, [endpoint])

    def test_validation_refuses_public_wildcard_guessed_or_duplicate_bindings(self):
        for values in [[], [('0.0.0.0', 51234)], [('::', 51234)], [('localhost', 51234)],
                       [('100.72.250.65', 51234)], [('127.0.0.1', 0)], [('127.0.0.1', True)],
                       [('127.0.0.1', 51234)] * 2]:
            with self.subTest(values=values), self.assertRaises(ValueError):
                with hold_loopback_transports(values):
                    self.fail('Invalid endpoints must be refused before acquiring sockets')

    def test_ipv4_and_ipv6_exact_endpoints_are_both_excluded(self):
        handle = seed()
        endpoint = handle.getsockname()
        handle.close()
        endpoints = [endpoint, ('::1', endpoint[1])]
        with hold_loopback_transports(endpoints) as lease:
            self.assertEqual(len(assert_loopback_hold(lease, endpoints)['endpoints']), 2)
            for item in endpoints:
                self.assertTrue(self.competitor(item, 'SO_REUSEADDR')['blocked'])

    def test_owned_process_exit_releases_kernel_reservation(self):
        for command in ['release', 'crash']:
            with self.subTest(command=command):
                handle = seed()
                endpoint = handle.getsockname()
                handle.close()
                code = '''import os,sys
from integrations.native_transport_hold import hold_loopback_transports
with hold_loopback_transports([('127.0.0.1',int(sys.argv[1]))]):
 print('held',flush=True)
 if sys.stdin.readline().strip()=='crash':os._exit(0)
'''
                process = subprocess.Popen([sys.executable, '-c', code, str(endpoint[1])], cwd=ROOT,
                                           stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                           stderr=subprocess.PIPE, text=True,
                                           creationflags=subprocess.CREATE_NO_WINDOW)
                try:
                    ready = queue.Queue()
                    threading.Thread(target=lambda: ready.put(process.stdout.readline()), daemon=True).start()
                    self.assertEqual(ready.get(timeout=10).strip(), 'held')
                    self.assertTrue(self.competitor(endpoint, 'SO_REUSEADDR')['blocked'])
                    _, error = process.communicate(command + '\n', timeout=10)
                    self.assertEqual(process.returncode, 0, error)
                    self.assertFalse(self.competitor(endpoint, 'SO_EXCLUSIVEADDRUSE')['blocked'])
                finally:
                    if process.poll() is None:
                        process.kill()
                    process.communicate(timeout=5)


if __name__ == '__main__':
    unittest.main()
