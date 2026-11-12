"""Actual candidate Handler, disposable HTTP port, fake owner; no model calls."""
import hashlib
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import json
import queue
from pathlib import Path
import sys
import select
import socket
import tempfile
import threading
import time
import types
import unittest
from unittest.mock import patch
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

    def test_successful_load_renews_idle_deadline_before_exposing_ready(self):
        clock, terminated = [0.0], []
        class StopWatchdog(Exception): pass
        class Child:
            pid, returncode = 123, None
            def poll(self): return self.returncode
            def terminate(self): terminated.append(clock[0]); self.returncode = 0
            def wait(self, timeout): return self.returncode
            def kill(self): raise AssertionError('No force kill expected')
        child = Child()
        ticks = []
        def sleep(seconds):
            self.assertEqual(seconds,15)
            if not ticks: raise StopWatchdog()
            target = ticks.pop(0)
            if len(ticks) == 0: self.assertEqual(terminated,[],'freshly loaded model must retain its whole idle window')
            clock[0] = target
        fake_time = types.SimpleNamespace(monotonic=lambda: clock[0],sleep=sleep)
        with patch.object(self.module,'time',fake_time), patch.object(self.module,'log',lambda *a: None), \
             patch.object(self.module,'preflight',lambda port:(True,'ok')), \
             patch.object(self.module,'resources',lambda:{'gpu_free_MiB':32000,'gpu_used_MiB':24000}), \
             patch.object(self.module,'unsupported_flags',lambda *a:[]), \
             patch.object(self.module,'MODELS',{'nemotron-3.5-bolt-74b-a9b':{'build':'fixture'}}), \
             patch.object(self.module,'save',lambda *a:None), \
             patch.object(self.module.subprocess,'Popen',lambda *a,**kw:child):
            supervisor = self.module.Supervisor()
            clock[0] = self.module.IDLE_UNLOAD_S + 100
            def ready(port):
                self.assertTrue(supervisor.loading)
                clock[0] += 50
                return True
            supervisor._wait_ready = ready
            try:
                ok, _ = supervisor.ensure(8099)
                self.assertTrue(ok)
                self.assertEqual(supervisor.last_used,clock[0],"successful load must not inherit yesterday's idle timestamp")
                ticks.extend([clock[0]+self.module.IDLE_UNLOAD_S-1,clock[0]+self.module.IDLE_UNLOAD_S])
                with self.assertRaises(StopWatchdog): supervisor.idle_watchdog()
                self.assertEqual(len(terminated),1)
                self.assertIsNone(supervisor.proc)
            finally:
                if supervisor.log_f: supervisor.log_f.close()

    def test_real_watchdog_waits_for_chat_and_unloads_only_after_renewed_idle_deadline(self):
        clock, ticks, completed = [10000.0], queue.Queue(), queue.Queue()
        started, release = threading.Event(), threading.Event()
        errors, replies, cleanup = [], [], []
        lock = threading.RLock()

        class StopWatchdog(Exception): pass
        class Child:
            pid, returncode = 123, None
            def poll(self): return self.returncode
            def terminate(self): cleanup.append('terminate-original'); self.returncode = 0
            def wait(self, timeout): cleanup.append(('wait-original', timeout)); return self.returncode
            def kill(self): raise AssertionError('Graceful fake-child exit must not escalate')
        class Connection:
            sock = None
            def connect(self): pass
            def close(self): pass
            def request(self, *args, **kwargs): pass
            def getresponse(self):
                started.set()
                if not release.wait(3): raise TimeoutError('Fixture chat was not released')
                return types.SimpleNamespace(status=200, read=lambda count:
                    b'{"choices":[{"message":{"content":"fixture answer"}}]}', close=lambda: None)

        iterations = [0]
        def next_tick(seconds):
            self.assertEqual(seconds,15)
            completed.put(iterations[0])
            if ticks.get(timeout=3) == 'stop': raise StopWatchdog()
            iterations[0] += 1
        fake_time = types.SimpleNamespace(monotonic=lambda: clock[0], sleep=next_tick)
        self.assertEqual(self.module.IDLE_UNLOAD_S,5400.0)
        with patch.object(self.module,'time',fake_time), patch.object(self.guard,'time',fake_time), \
             patch.object(self.module,'_LOCK',lock), patch.object(self.module,'log',lambda *args: None), \
             patch.object(self.module,'IDLE_UNLOAD_S',10.0):
            supervisor = self.module.Supervisor()
            child = Child()
            supervisor.proc, supervisor.port, supervisor.last_used = child, 8099, 0
            owner = types.SimpleNamespace(capture=lambda: self.owner, supervisor=supervisor)
            chat = self.guard.NemotronSupervisorChat(owner, Connection, lambda: True)
            gate = self.guard.MeshControlGate(lock, owner.capture,
                lambda *args: self.fail('No explicit control dispatch expected'), self.queue.append,
                chat=chat.send, chat_settled=chat.settled)
            body = {'id':str(uuid.uuid4()),'expected':gate.status()['expected'],'prompt':'watchdog fixture'}
            def run_chat():
                try: replies.append(gate.chat(body))
                except Exception as error: errors.append(error)
            def run_watchdog():
                try: supervisor.idle_watchdog()
                except StopWatchdog: pass
                except Exception as error: errors.append(error)
            worker = threading.Thread(target=run_chat,daemon=True)
            watchdog = threading.Thread(target=run_watchdog,daemon=True)
            try:
                worker.start()
                self.assertTrue(started.wait(2))
                clock[0] += self.module.IDLE_UNLOAD_S+1
                watchdog.start()
                self.assertEqual(completed.get(timeout=2),0)
                ticks.put('tick')
                self.assertFalse(lock.acquire(timeout=0.05), 'Actual watchdog must share the active chat lock')
                self.assertEqual(cleanup,[])
                release.set()
                worker.join(timeout=2)
                self.assertFalse(worker.is_alive())
                self.assertEqual(completed.get(timeout=2),1)
                self.assertEqual(supervisor.last_used,clock[0])
                self.assertEqual(cleanup,[])
                clock[0] = supervisor.last_used+self.module.IDLE_UNLOAD_S-1
                ticks.put('tick')
                self.assertEqual(completed.get(timeout=2),2)
                self.assertEqual(cleanup,[])
                clock[0] += 1
                ticks.put('tick')
                self.assertEqual(completed.get(timeout=2),3)
                self.assertEqual(cleanup,['terminate-original',('wait-original',25)])
                self.assertIsNone(supervisor.proc)
                self.assertIsNone(supervisor.port)
                self.assertEqual(errors,[])
                self.assertEqual(len(replies),1)
                self.assertEqual(self.queue,[])
            finally:
                release.set()
                ticks.put('stop')
                worker.join(timeout=2)
                if watchdog.ident is not None: watchdog.join(timeout=2)
                self.assertFalse(worker.is_alive())
                self.assertFalse(watchdog.is_alive())


if __name__ == "__main__":
    unittest.main()
