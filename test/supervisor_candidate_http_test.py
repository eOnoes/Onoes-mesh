"""Actual candidate Handler, disposable HTTP port, fake owner; no model calls."""
import hashlib
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import json
from pathlib import Path
import sys
import select
import socket
import tempfile
import threading
import time
import types
import unittest
import urllib.error
import urllib.request
import uuid


class CandidateHTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root = Path(__file__).resolve().parent.parent
        pointer = root / "data/nemotron-supervisor-candidate-latest.json"
        if not pointer.exists():
            raise unittest.SkipTest("Prepare the supervisor candidate first; no live model is needed.")
        manifest = json.loads(pointer.read_text(encoding="utf-8"))
        directory = Path(manifest["directory"]).resolve()
        if not directory.is_relative_to((root / "data/nemotron-supervisor-candidate").resolve()):
            raise ValueError("Candidate escaped its workspace")
        for entry in manifest["files"]:
            file = (directory / entry["path"]).resolve()
            if file.parent != directory or hashlib.sha256(file.read_bytes()).hexdigest() != entry["sha256"]:
                raise ValueError("Candidate hash changed; prepare it again")
        cls.manifest = manifest
        cls.temp = tempfile.TemporaryDirectory(prefix="mesh-supervisor-http-")
        launch = types.ModuleType("launch_local")
        launch.HOST = "127.0.0.1"
        launch.LOGS = Path(cls.temp.name)
        launch.MODELS = {"nemotron-3.5-bolt-74b-a9b": {}}
        launch.build_argv = lambda *args: ["D:/models/nemotron/tools/llama-b11669-cuda12.4/llama-server.exe",
            "-m", "D:/models/nemotron/NVIDIA-Nemotron-3.5-Bolt-74B-A9B-24GB.gguf",
            "--alias", "nemotron-3.5-bolt-74b-a9b", "--host", "127.0.0.1", "--port", "8199"]
        for name in ["identity", "now", "resources", "save", "unsupported_flags"]:
            setattr(launch, name, lambda *args: None)
        psutil = types.ModuleType("psutil")
        psutil.Process = lambda pid: (_ for _ in ()).throw(AssertionError("No native process lookup in fixture"))
        psutil.net_connections = lambda **kw: []
        cls.previous = {name: sys.modules.get(name) for name in ["launch_local", "psutil", "supervisor_mesh_control"]}
        sys.modules.update(launch_local=launch, psutil=psutil)
        def load(name, path):
            spec = importlib.util.spec_from_file_location(name, path)
            module = importlib.util.module_from_spec(spec)
            sys.modules[name] = module
            spec.loader.exec_module(module)
            return module
        cls.guard = load("supervisor_mesh_control", directory / "supervisor_mesh_control.py")
        cls.module = load("mesh_candidate_fixture", directory / "local_supervisor.py")

    @classmethod
    def tearDownClass(cls):
        for name, previous in cls.previous.items():
            if previous is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = previous
        sys.modules.pop("mesh_candidate_fixture", None)
        cls.temp.cleanup()

    def setUp(self):
        self.calls = []
        self.queue = []
        self.chat_calls = []
        self.owner_lock = threading.Lock()
        self.owner = {"state": "resident", "modelId": self.guard.MODEL, "ownerVerified": True,
            "identity": {"pid": 123, "createdAt": "2026-11-07T12:00:00Z", "executable": "D:/fixture/server.exe",
                         "executableSha256": "a"*64, "argvHash": "b"*64}}
        def perform(action, original):
            self.calls.append((action, original))
            self.owner = {"state": "empty", "identity": None, "clear": True}
        def chat(prompt, original, peer):
            self.assertTrue(self.owner_lock.locked())
            self.chat_calls.append(len(prompt))
            return "Candidate fixture answer"
        self.gate = self.guard.MeshControlGate(self.owner_lock, lambda: self.owner, perform, self.queue.append,
                                               chat=chat, chat_settled=lambda: True)
        self.module._MESH_ROUTES = self.guard.MeshSupervisorRoutes(self.gate,supervisor_sha256=next(x["sha256"] for x in self.manifest["files"] if x["path"]=="local_supervisor.py"))
        class Handler(self.module.Handler):
            @property
            def port(self):
                return 8099  # Protocol lane only; TCP port is disposable, not live8099.
        self.server = self.module.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.origin = "http://127.0.0.1:"+str(self.server.server_address[1])
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def request(self, path, body=None, content_type="application/json"):
        request = urllib.request.Request(self.origin+path, data=body, method="POST" if body is not None else "GET",
                                         headers={"Content-Type": content_type})
        try:
            response = self.opener.open(request, timeout=3)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            return response.status, json.loads(response.read(16384))

    def test_real_candidate_status_command_and_receipt_preserve_identity_and_deduplication(self):
        code, status = self.request("/mesh/v1/status")
        self.assertEqual(code, 200)
        expected_hash = next(x["sha256"] for x in self.manifest["files"] if x["path"] == "supervisor_mesh_control.py")
        self.assertEqual(status["moduleSha256"], expected_hash)
        operation = {"id":str(uuid.uuid4()),"action":"unload","expected":status["expected"]}
        body = json.dumps(operation).encode()
        code, ack = self.request("/mesh/v1/commands", body)
        self.assertEqual(code, 202)
        self.assertEqual(ack["bootId"], status["bootId"])
        self.assertEqual(self.request("/mesh/v1/commands", body)[0], 202)
        self.assertEqual(self.calls, [])
        self.assertEqual(len(self.queue), 1)
        self.queue.pop()()
        code, receipt = self.request("/mesh/v1/receipts/"+operation["id"])
        self.assertEqual(code, 200)
        self.assertTrue(receipt["receipt"]["readBackVerified"])
        self.assertEqual(self.request("/mesh/v1/commands", body)[0], 200)
        self.assertEqual(len(self.calls), 1)

    def test_actual_handler_rejects_large_wrong_content_and_duplicate_json_before_dispatch(self):
        for body, content_type, expected in [(b"{}","text/plain",415),(b"x"*4097,"application/json",413),
             (b'{"action":"load","action":"unload"}',"application/json",400)]:
            self.assertEqual(self.request("/mesh/v1/commands", body, content_type)[0], expected)
        self.assertEqual(self.calls, [])
        self.assertEqual(self.queue, [])
        self.assertEqual(self.request("/unrecognized-fixture-path")[0],404)

    def test_actual_handler_recovery_fences_missing_command_without_model_operation(self):
        status = self.request("/mesh/v1/status")[1]
        command = {"id":str(uuid.uuid4()),"action":"unload","expected":status["expected"]}
        body = json.dumps({"command":command,"originalBootId":status["bootId"],"currentExpected":status["expected"]}).encode()
        code, proof = self.request("/mesh/v1/recover",body)
        self.assertEqual(code,200)
        self.assertEqual(proof["recovery"]["outcome"],"UNKNOWN")
        self.assertEqual(proof["moduleSha256"],status["moduleSha256"])
        self.assertEqual(self.request("/mesh/v1/recover",body),(200,proof))
        self.assertEqual(self.request("/mesh/v1/commands",json.dumps(command).encode())[0],409)
        self.assertTrue(self.request("/mesh/v1/status")[1]["unload"])
        self.assertEqual(self.calls,[])
        self.assertEqual(self.queue,[])

    def test_actual_handler_chat_checks_original_owner_consumes_token_and_keeps_command_bounds(self):
        status = self.request("/mesh/v1/status")[1]
        request = {"id":str(uuid.uuid4()),"expected":status["expected"],"prompt":"\x01"*2500}
        encoded = json.dumps(request).encode()
        self.assertGreater(len(encoded),4096)
        code, reply = self.request("/mesh/v1/chat",encoded)
        self.assertEqual(code,200)
        self.assertEqual(reply["chat"]["response"],"Candidate fixture answer")
        self.assertNotEqual(reply["chat"]["expected"],status["expected"])
        self.assertEqual(self.request("/mesh/v1/chat",encoded)[0],409)
        self.assertEqual(self.chat_calls,[2500])
        self.assertEqual(self.request("/mesh/v1/commands",encoded)[0],413)
        self.assertEqual(self.calls,[])

    def test_receipt_reads_remain_available_when_native_owner_lock_is_busy(self):
        status = self.request("/mesh/v1/status")[1]
        operation = {"id":str(uuid.uuid4()),"action":"unload","expected":status["expected"]}
        self.request("/mesh/v1/commands",json.dumps(operation).encode())
        self.owner_lock.acquire()
        try:
            self.assertEqual(self.request("/mesh/v1/status")[0],409)
            self.assertEqual(self.request("/mesh/v1/receipts/"+operation["id"])[0],200)
        finally:
            self.owner_lock.release()
        self.assertEqual(self.calls,[])

    def test_phone_disconnect_through_actual_handler_keeps_controls_held_until_idle_readback(self):
        started, disconnected, finish, idle = (threading.Event() for _ in range(4))
        handler_error = threading.Event()
        handler_errors = []
        def capture_handler_error(*args):
            handler_errors.append(type(sys.exc_info()[1]).__name__)
            handler_error.set()
        self.server.handle_error = capture_handler_error
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
                            disconnected.set()
                            break
                except OSError:
                    disconnected.set()
                # Socket closure deliberately does not establish idle readback.
                finish.wait(4)

        backend = ThreadingHTTPServer(('127.0.0.1', 0), Backend)
        backend.daemon_threads = True
        backend_thread = threading.Thread(target=backend.serve_forever, daemon=True)
        backend_thread.start()
        owner = types.SimpleNamespace(capture=lambda: self.owner,
            supervisor=types.SimpleNamespace(proc=types.SimpleNamespace(poll=lambda: None), last_used=0))
        transport = self.guard.NemotronSupervisorChat(owner,
            connection_factory=lambda: http.client.HTTPConnection('127.0.0.1', backend.server_port, timeout=3),
            slots_reader=idle.is_set)
        self.gate = self.guard.MeshControlGate(self.owner_lock, lambda: self.owner,
            lambda *args: self.fail('Cancellation must not unload or load a model'), self.queue.append,
            chat=transport.send, chat_settled=transport.settled)
        self.module._MESH_ROUTES = self.guard.MeshSupervisorRoutes(self.gate,
            supervisor_sha256=next(x['sha256'] for x in self.manifest['files'] if x['path']=='local_supervisor.py'))
        caller = socket.create_connection(self.server.server_address, timeout=3)
        try:
            status = self.request('/mesh/v1/status')[1]
            body = json.dumps({'id':str(uuid.uuid4()), 'expected':status['expected'],
                               'prompt':'disposable cancellation test'}).encode()
            caller.sendall(('POST /mesh/v1/chat HTTP/1.1\r\nHost: localhost\r\n'
                'Content-Type: application/json\r\nContent-Length: '+str(len(body))+'\r\n\r\n').encode()+body)
            self.assertTrue(started.wait(2))
            self.assertFalse(self.owner_lock.acquire(timeout=0.05))
            caller.shutdown(socket.SHUT_RDWR)
            caller.close()
            self.assertTrue(disconnected.wait(3), 'Handler must cancel its original backend socket')
            deadline = time.monotonic()+3
            while time.monotonic()<deadline:
                code, held = self.request('/mesh/v1/status')
                if code==200: break
                finish.wait(0.02)
            self.assertEqual(code,200)
            self.assertIsNotNone(held['active'])
            self.assertFalse(held['unload'])
            self.assertIsNotNone(transport.pending)
            idle.set()
            settled = self.request('/mesh/v1/status')[1]
            self.assertIsNone(settled['active'])
            self.assertTrue(settled['unload'])
            self.assertIsNone(transport.pending)
            self.assertGreater(owner.supervisor.last_used,0)
            self.assertEqual(self.queue,[])
            handler_error.wait(0.5)
            self.assertEqual(handler_errors,[], 'An expected phone disconnect must not crash the handler')
        finally:
            finish.set()
            idle.set()
            caller.close()
            backend.shutdown()
            backend.server_close()
            backend_thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
