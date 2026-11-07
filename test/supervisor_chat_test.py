"""Guarded chat and real socket cancellation, with disposable fake model only."""
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import select
import socket
import threading
import types
import unittest
import uuid
from lib.supervisor_mesh_control import ControlRefused, MeshControlGate, NemotronSupervisorChat, MODEL
from test.supervisor_mesh_control_test import Fixture


class ChatTests(unittest.TestCase):
    def fixture(self, factory, slots=lambda: True):
        f = Fixture()
        handle = types.SimpleNamespace(poll=lambda: None)
        owner = types.SimpleNamespace(capture=lambda: f.value,
                                      supervisor=types.SimpleNamespace(proc=handle, last_used=0))
        transport = NemotronSupervisorChat(owner, connection_factory=factory, slots_reader=slots)
        f.gate = MeshControlGate(f.lock, lambda: f.value, f.perform, f.queue.append,
                                chat=transport.send, chat_settled=transport.settled)
        return f, transport, owner

    def body(self, f):
        return {"id": str(uuid.uuid4()), "expected": f.gate.status()["expected"], "prompt": "private prompt"}

    def test_chat_uses_owner_lock_and_idle_timer_consumes_token_and_keeps_no_transcript(self):
        requests = []
        class Connection:
            sock = None
            def connect(self): pass
            def close(self): pass
            def request(self, method, path, body, headers):
                self_outer.assertTrue(f.lock.locked())
                requests.append((method, path, json.loads(body)))
            def getresponse(self):
                return types.SimpleNamespace(status=200, read=lambda count: b'{"choices":[{"message":{"content":"answer"}}]}', close=lambda: None)
        self_outer = self
        f, transport, owner = self.fixture(Connection)
        body = self.body(f)
        result = f.gate.chat(body)
        self.assertEqual(result["response"], "answer")
        self.assertNotEqual(result["expected"], body["expected"])
        self.assertEqual(requests, [("POST", "/v1/chat/completions", {"model": MODEL,
                         "messages": [{"role": "user", "content": "private prompt"}], "max_tokens": 512, "stream": False})])
        self.assertGreater(owner.supervisor.last_used, 0)
        self.assertIsNone(transport.pending)
        self.assertEqual(f.calls, [])
        self.assertNotIn("private prompt", repr(vars(f.gate)))
        self.assertNotIn("private prompt", repr(vars(transport)))
        with self.assertRaisesRegex(ControlRefused, "OWNER_CHANGED"):
            f.gate.chat(body)
        self.assertEqual(len(requests), 1)

    def test_failed_transport_never_releases_controls_until_slot_readback_is_idle(self):
        idle = [True]
        class Connection:
            sock = None
            def connect(self): pass
            def close(self): pass
            def request(self, *args, **kwargs): idle[0] = False
            def getresponse(self): raise OSError("unverified backend")
        f, transport, owner = self.fixture(Connection, lambda: idle[0])
        with self.assertRaisesRegex(ControlRefused, "CHAT_OUTCOME_UNKNOWN"):
            f.gate.chat(self.body(f))
        status = f.gate.status()
        self.assertIsNotNone(status["active"])
        self.assertFalse(status["unload"])
        idle[0] = True
        self.assertIsNone(f.gate.status()["active"])
        self.assertTrue(f.gate.status()["unload"])
        self.assertEqual(f.calls, [])

    def test_cancelled_caller_interrupts_original_child_socket_even_with_connection_close_headers(self):
        started, idle, finish = threading.Event(), threading.Event(), threading.Event()
        idle.set()
        class Backend(BaseHTTPRequestHandler):
            def log_message(self, *args): pass
            def do_POST(self):
                self.rfile.read(int(self.headers['Content-Length']))
                idle.clear()
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Connection', 'close')
                self.end_headers()
                self.wfile.flush()
                started.set()
                try:
                    while not finish.wait(0.02):
                        ready, _, _ = select.select([self.connection], [], [], 0)
                        if ready and self.connection.recv(1, socket.MSG_PEEK) == b'':
                            break
                except OSError:
                    pass
                finally:
                    idle.set()
        server = ThreadingHTTPServer(('127.0.0.1', 0), Backend)
        server.daemon_threads = True
        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()
        peer, caller = socket.socketpair()
        f, transport, owner = self.fixture(lambda: http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=3), idle.is_set)
        errors = []
        body = self.body(f)
        def work():
            try: f.gate.chat(body, peer)
            except ControlRefused as error: errors.append(error.code)
        worker = threading.Thread(target=work, daemon=True)
        try:
            worker.start()
            self.assertTrue(started.wait(2))
            self.assertFalse(f.lock.acquire(timeout=0.05), 'watchdog/other controls must share this lock')
            caller.close()
            worker.join(timeout=4)
            self.assertFalse(worker.is_alive())
            self.assertEqual(errors, ['CHAT_OUTCOME_UNKNOWN'])
            self.assertTrue(idle.wait(1))
            self.assertIsNone(f.gate.status()['active'])
            self.assertTrue(f.gate.status()['unload'])
            self.assertGreater(owner.supervisor.last_used, 0)
            self.assertEqual(f.calls, [])
        finally:
            finish.set()
            caller.close()
            peer.close()
            server.shutdown()
            server.server_close()
            server_thread.join(timeout=2)
            worker.join(timeout=2)


if __name__ == '__main__':
    unittest.main()
