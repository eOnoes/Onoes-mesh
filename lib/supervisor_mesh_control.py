"""Identity-bound command gate for an owner-retaining model supervisor.

Prepared component, not installed in the running supervisor. The owner supplies
capture()/perform(action, original_snapshot), both called under its existing lock.
Only a verified Nemotron resident or a verified empty lane is eligible. No PID
termination, model command line, network endpoint or arbitrary profile lives here.
"""
import copy
import datetime
import re
from pathlib import PureWindowsPath, Path
import hashlib
import json
import threading
import uuid
import urllib.request

MODEL = "nemotron-3.5-bolt-74b-a9b"
_MODULE_SHA256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


class ControlRefused(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


class MeshControlGate:
    def __init__(self, owner_lock, capture, perform, launch=None):
        self._owner = owner_lock
        self._capture = capture
        self._perform = perform
        self._launch = launch or self._thread
        self._meta = threading.RLock()
        self._boot = str(uuid.uuid4())
        self._revision = 0
        self._signature = None
        self._active = None
        self._receipts = {}

    @property
    def boot_id(self):
        return self._boot

    @staticmethod
    def _thread(work):
        threading.Thread(target=work, daemon=True).start()

    @staticmethod
    def _hash(value):
        return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

    def _observe(self):
        value = copy.deepcopy(self._capture())
        if (not isinstance(value, dict) or set(value) - {"state", "clear", "modelId", "identity", "ownerVerified"}
                or value.get("state") not in ("empty", "resident", "uncertain")):
            raise ControlRefused("OWNER_EVIDENCE_INVALID")
        signature = self._hash(value)
        with self._meta:
            if signature != self._signature:
                self._signature = signature
                self._revision += 1
            token = self._hash([self._boot, self._revision, signature])
        return value, signature, token

    @staticmethod
    def _valid_identity(identity):
        if not isinstance(identity, dict) or set(identity) - {"pid", "createdAt", "executable", "executableSha256", "argvHash", "cwd"}:
            return False
        try:
            created = datetime.datetime.fromisoformat(identity.get("createdAt", "").replace("Z", "+00:00"))
            return (type(identity.get("pid")) is int and identity["pid"] > 0 and created.tzinfo is not None
                    and isinstance(identity.get("executable"), str) and PureWindowsPath(identity["executable"]).is_absolute()
                    and all(isinstance(identity.get(k), str) and re.fullmatch(r"[0-9a-fA-F]{64}", identity[k])
                            for k in ("executableSha256", "argvHash"))
                    and ("cwd" not in identity or isinstance(identity["cwd"], str) and PureWindowsPath(identity["cwd"]).is_absolute()))
        except (ValueError, TypeError, AttributeError):
            return False

    @staticmethod
    def _eligible(action, value):
        if action == "load":
            return value.get("state") == "empty" and value.get("clear") is True and value.get("identity") is None and value.get("modelId") is None
        identity = value.get("identity")
        return (value.get("state") == "resident" and value.get("modelId") == MODEL
                and value.get("ownerVerified") is True and MeshControlGate._valid_identity(identity))

    def status(self):
        if not self._owner.acquire(timeout=0.2):
            raise ControlRefused("OWNER_BUSY")
        try:
            value, _, token = self._observe()
            with self._meta:
                return {"bootId": self._boot, "expected": token, "owner": value,
                        "active": self._active, "load": self._active is None and self._eligible("load", value),
                        "unload": self._active is None and self._eligible("unload", value)}
        finally:
            self._owner.release()

    def receipt(self, operation_id):
        with self._meta:
            if operation_id not in self._receipts:
                raise ControlRefused("RECEIPT_UNKNOWN")
            return copy.deepcopy(self._receipts[operation_id])

    def submit(self, body):
        if not isinstance(body, dict) or set(body) != {"id", "action", "expected"}:
            raise ControlRefused("INVALID_COMMAND")
        try:
            parsed = uuid.UUID(body["id"])
            if str(parsed) != body["id"] or parsed.version != 4:
                raise ValueError()
        except (ValueError, TypeError, AttributeError):
            raise ControlRefused("INVALID_COMMAND") from None
        action = body["action"]
        if action not in ("load", "unload") or not isinstance(body["expected"], str) or not re.fullmatch(r"[0-9a-f]{64}", body["expected"]):
            raise ControlRefused("INVALID_COMMAND")
        fingerprint = self._hash(body)
        operation_id = body["id"]
        with self._meta:
            old = self._receipts.get(operation_id)
            if old:
                if old["fingerprint"] != fingerprint:
                    raise ControlRefused("COMMAND_ID_CONFLICT")
                return copy.deepcopy(old)
        if not self._owner.acquire(timeout=0.2):
            raise ControlRefused("OWNER_BUSY")
        try:
            original, signature, token = self._observe()
            with self._meta:
                # Recheck after acquiring the native owner lock: concurrent submits
                # cannot reserve or execute the same request twice.
                old = self._receipts.get(operation_id)
                if old:
                    if old["fingerprint"] != fingerprint:
                        raise ControlRefused("COMMAND_ID_CONFLICT")
                    return copy.deepcopy(old)
                if self._active is not None:
                    raise ControlRefused("OPERATION_IN_PROGRESS")
                if body["expected"] != token:
                    raise ControlRefused("OWNER_CHANGED")
                if not self._eligible(action, original):
                    raise ControlRefused("ACTION_UNAVAILABLE")
                self._revision += 1  # Consume the precondition, including on failure.
                reserved_revision = self._revision
                self._active = operation_id
                self._receipts[operation_id] = {"id": operation_id, "action": action,
                    "fingerprint": fingerprint, "state": "ACCEPTED", "readBackVerified": False, "ownerCallStarted": False}
                # Eviction cannot authorize replay: every accepted command consumes
                # a monotonically increasing token; a new boot has a different ID.
                while len(self._receipts) > 64:
                    oldest = next(iter(self._receipts))
                    if oldest == self._active:
                        break
                    del self._receipts[oldest]
        finally:
            self._owner.release()

        def work():
            locked = False
            owner_called = False
            result = {"state": "UNKNOWN", "readBackVerified": False}
            try:
                locked = self._owner.acquire(timeout=0.2)
                if not locked:
                    raise ControlRefused("OWNER_BUSY")
                current, current_signature, _ = self._observe()
                if current_signature != signature or self._revision != reserved_revision or not self._eligible(action, current):
                    raise ControlRefused("OWNER_CHANGED")
                with self._meta:
                    self._receipts[operation_id]["state"] = "RUNNING"
                    self._receipts[operation_id]["ownerCallStarted"] = True
                owner_called = True
                self._perform(action, copy.deepcopy(original))
                after, _, _ = self._observe()
                verified = self._eligible("unload" if action == "load" else "load", after)
                result = {"state": "COMPLETED" if verified else "UNKNOWN", "readBackVerified": verified}
            except ControlRefused as error:
                if not owner_called:
                    result["state"] = "REFUSED"
                result["reason"] = error.code
            except Exception:
                result["reason"] = "OWNER_OPERATION_FAILED"
            finally:
                if locked:
                    self._owner.release()
                with self._meta:
                    self._receipts[operation_id].update(result)
                    self._active = None

        try:
            self._launch(work)
        except Exception:
            with self._meta:
                self._receipts[operation_id].update(state="UNKNOWN", reason="DISPATCH_FAILED", readBackVerified=False)
                self._active = None
        return self.receipt(operation_id)


class NemotronSupervisorOwner:
    """Binding for the existing supervisor's retained Popen, not a PID adopter.

    Construction/capture are read-only. Only MeshControlGate may call perform,
    under that supervisor's existing lock. This binding is not installed yet.
    """
    EXECUTABLE = PureWindowsPath("D:/models/nemotron/tools/llama-b11669-cuda12.4/llama-server.exe")
    MODEL_FILE = PureWindowsPath("D:/models/nemotron/NVIDIA-Nemotron-3.5-Bolt-74B-A9B-24GB.gguf")
    PORT = 8099
    CHILD_PORT = 8199

    def __init__(self, supervisor, expected_argv, executable_sha256, process_reader=None,
                 port_clear=None, hash_executable=None, health=None):
        if (not isinstance(expected_argv, list) or not expected_argv
                or not all(isinstance(arg, str) for arg in expected_argv)
                or PureWindowsPath(expected_argv[0]) != self.EXECUTABLE
                or not isinstance(executable_sha256, str)
                or not re.fullmatch(r"[0-9a-fA-F]{64}", executable_sha256)):
            raise ValueError("Unqualified Nemotron profile")
        for flag, value in [("--alias", MODEL), ("--host", "127.0.0.1"), ("--port", str(self.CHILD_PORT))]:
            if expected_argv.count(flag) != 1 or expected_argv.index(flag) + 1 >= len(expected_argv) or expected_argv[expected_argv.index(flag) + 1] != value:
                raise ValueError("Unqualified Nemotron arguments")
        if (expected_argv.count("-m") != 1 or expected_argv.index("-m") + 1 >= len(expected_argv)
                or PureWindowsPath(expected_argv[expected_argv.index("-m") + 1]) != self.MODEL_FILE):
            raise ValueError("Unqualified Nemotron model file")
        self.supervisor = supervisor
        self.argv = list(expected_argv)
        self.exe_hash = executable_sha256.lower()
        if process_reader is None or port_clear is None:
            import psutil
            process_reader = process_reader or psutil.Process
            port_clear = port_clear or (lambda: not any(c.status == "LISTEN" and c.laddr.port == self.CHILD_PORT for c in psutil.net_connections(kind="tcp")))
        self.process_reader = process_reader
        self.port_clear = port_clear
        self.hash_executable = hash_executable or self._file_hash
        self.health = health or self._health

    @staticmethod
    def _file_hash(path):
        with open(path, "rb") as handle:
            return hashlib.file_digest(handle, "sha256").hexdigest()

    def _health(self):
        values = []
        for path in ("/health", "/v1/models"):
            request = urllib.request.Request("http://127.0.0.1:" + str(self.CHILD_PORT) + path, method="GET")
            # Explicit no-redirect/no-proxy transport; no generation or admin call.
            class NoRedirect(urllib.request.HTTPRedirectHandler):
                def redirect_request(self, req, fp, code, msg, headers, newurl):
                    return None
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
            with opener.open(request, timeout=2) as response:
                data = response.read(16385)
                if response.status != 200 or len(data) > 16384:
                    return False
                values.append(json.loads(data))
        return values[0].get("status") == "ok" and any(row.get("id") == MODEL for row in values[1].get("data", []))

    def capture(self):
        try:
            owner = self.supervisor
            original = owner.proc
            if self.hash_executable(str(self.EXECUTABLE)).lower() != self.exe_hash:
                return {"state": "uncertain"}
            if original is None:
                if owner.port is None and not owner.loading and self.port_clear():
                    return {"state": "empty", "identity": None, "clear": True}
                return {"state": "uncertain"}
            if owner.port != self.PORT or owner.loading or original.poll() is not None:
                return {"state": "uncertain"}
            live = self.process_reader(original.pid)
            saved = owner.ident
            if (saved.get("pid") != original.pid or saved.get("created") != live.create_time()
                    or PureWindowsPath(saved.get("exe", "")) != self.EXECUTABLE
                    or PureWindowsPath(live.exe()) != self.EXECUTABLE
                    or saved.get("cmdline") != self.argv or live.cmdline() != self.argv
                    or PureWindowsPath(live.cwd()) != self.EXECUTABLE.parent
                    or not any(c.status == "LISTEN" and c.laddr.port == self.CHILD_PORT and c.laddr.ip == "127.0.0.1" for c in live.net_connections(kind="tcp"))):
                return {"state": "uncertain"}
            identity = {"pid": original.pid,
                        "createdAt": datetime.datetime.fromtimestamp(saved["created"], datetime.timezone.utc).isoformat(),
                        "executable": str(self.EXECUTABLE), "executableSha256": self.exe_hash,
                        "argvHash": MeshControlGate._hash(self.argv), "cwd": live.cwd()}
            if not MeshControlGate._valid_identity(identity):
                return {"state": "uncertain"}
            return {"state": "resident", "modelId": MODEL, "identity": identity, "ownerVerified": True}
        except Exception:
            return {"state": "uncertain"}

    def perform(self, action, original):
        if self.capture() != original or not MeshControlGate._eligible(action, original):
            raise ControlRefused("OWNER_CHANGED")
        if action == "load":
            ok, _ = self.supervisor.ensure(self.PORT)
            if not ok or not self.health():
                raise ControlRefused("MODEL_READBACK_UNVERIFIED")
        elif action == "unload":
            # The supervisor terminates its original retained Popen handle itself.
            # This binding never terminates a discovered PID or another model.
            self.supervisor.unload("Mesh identity-bound owner request")
        else:
            raise ControlRefused("INVALID_COMMAND")


class MeshSupervisorRoutes:
    """Prepared routing seam; owns no listener and leaves legacy routes alone."""
    SCHEMA = "mesh-supervisor-control/v1"

    def __init__(self, gate):
        self.gate = gate

    @staticmethod
    def _unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate field")
            result[key] = value
        return result

    def envelope(self, value):
        return {"schemaVersion": self.SCHEMA, "moduleSha256": _MODULE_SHA256,
                "bootId": self.gate.boot_id, "modelId": MODEL, **value}

    def handle(self, port, method, path, body=b"", content_type=None):
        result = self._handle(port, method, path, body, content_type)
        return None if result is None else (result[0], self.envelope(result[1]))

    def _handle(self, port, method, path, body=b"", content_type=None):
        if not isinstance(path, str) or not path.startswith("/mesh/v1/"):
            return None
        if port != NemotronSupervisorOwner.PORT:
            return 404, {"error": "ROUTE_UNAVAILABLE"}
        try:
            if path == "/mesh/v1/status":
                if method != "GET":
                    return 405, {"error": "METHOD_NOT_ALLOWED"}
                return 200, {"schemaVersion": self.SCHEMA, "moduleSha256": _MODULE_SHA256, "modelId": MODEL, **self.gate.status()}
            receipt = re.fullmatch(r"/mesh/v1/receipts/([0-9a-f-]{36})", path)
            if receipt:
                if method != "GET":
                    return 405, {"error": "METHOD_NOT_ALLOWED"}
                return 200, {"schemaVersion": self.SCHEMA, "moduleSha256": _MODULE_SHA256, "bootId": self.gate.boot_id, "receipt": self.gate.receipt(receipt[1])}
            if path != "/mesh/v1/commands":
                return 404, {"error": "ROUTE_UNAVAILABLE"}
            if method != "POST":
                return 405, {"error": "METHOD_NOT_ALLOWED"}
            if not isinstance(content_type, str) or content_type.split(";", 1)[0].strip().lower() != "application/json":
                return 415, {"error": "JSON_REQUIRED"}
            if not isinstance(body, bytes) or len(body) > 4096:
                return 413, {"error": "COMMAND_TOO_LARGE"}
            try:
                command = json.loads(body, object_pairs_hook=self._unique)
            except (ValueError, UnicodeDecodeError):
                return 400, {"error": "INVALID_COMMAND"}
            value = self.gate.submit(command)
            return (202 if value["state"] in ("ACCEPTED", "RUNNING") else 200), {"schemaVersion": self.SCHEMA, "moduleSha256": _MODULE_SHA256, "bootId": self.gate.boot_id, "receipt": value}
        except ControlRefused as error:
            code = 400 if error.code == "INVALID_COMMAND" else 404 if error.code == "RECEIPT_UNKNOWN" else 503 if error.code == "OWNER_EVIDENCE_INVALID" else 409
            return code, {"error": error.code}
        except Exception:
            return 503, {"error": "CONTROL_UNAVAILABLE"}
