"""Windows Phase A custody for disposable fixtures only; no Relay integration.

Journal/PID records are refusal evidence, never authority to reconstruct custody.
The only process authority is the handle returned by this module's Popen call.
"""
from __future__ import annotations

import ctypes as C
from ctypes import wintypes as W
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import secrets
import socket
import stat
import subprocess
import sys
import time


class Refusal(RuntimeError):
    pass


FLAGS = ("-I", "-S", "-B")
FORBIDDEN_PORTS = frozenset((8771, 8772, 8642, 8450))
WAIT_OBJECT_0, WAIT_ABANDONED, WAIT_TIMEOUT = 0, 128, 258


def canonical(path):
    """Require absolute, existing paths with no reparse component, then casefold."""
    p = Path(path)
    if not p.is_absolute():
        raise Refusal("relative path")
    for component in (p, *p.parents):
        try:
            info = component.lstat()
        except OSError as e:
            raise Refusal("unresolved path") from e
        if info.st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT:
            raise Refusal("reparse ambiguity")
    return str(p.resolve(strict=True)).casefold()


def within(path, root):
    p, r = canonical(path), canonical(root)
    return p == r or p.startswith(r.rstrip("\\/") + os.sep)


def corroborate_path(value, expected):
    """Reject unregistered child paths before any filesystem access to them."""
    if not isinstance(value, str) or not Path(value).is_absolute():
        raise Refusal("missing/relative corroborating path")
    if os.path.normpath(value).casefold() != os.path.normpath(str(expected)).casefold():
        raise Refusal("unregistered corroborating path")
    if canonical(value) != canonical(expected):
        raise Refusal("canonical path contradiction")


def disposable_root(root, sandbox):
    if within(root, sandbox) or within(sandbox, root):
        raise Refusal("root overlaps sandbox")
    return Path(root).resolve(strict=True)


class SECURITY_ATTRIBUTES(C.Structure):
    _fields_ = [("nLength", W.DWORD), ("lpSecurityDescriptor", W.LPVOID),
                ("bInheritHandle", W.BOOL)]


class TCP_ROW(C.Structure):
    _fields_ = [(n, W.DWORD) for n in
                ("state", "address", "port", "remote_address", "remote_port", "pid")]


class Native:
    def __init__(self):
        if os.name != "nt":
            raise Refusal("BLOCKED: native Windows required")
        self.k = C.WinDLL("kernel32", use_last_error=True)
        self.a = C.WinDLL("advapi32", use_last_error=True)
        self.ip = C.WinDLL("iphlpapi", use_last_error=True)
        declarations = (
            (self.k, "GetCurrentProcess", [], W.HANDLE),
            (self.k, "GetProcessId", [W.HANDLE], W.DWORD),
            (self.k, "GetProcessTimes", [W.HANDLE] + [C.POINTER(W.FILETIME)] * 4, W.BOOL),
            (self.k, "QueryFullProcessImageNameW", [W.HANDLE, W.DWORD, W.LPWSTR, C.POINTER(W.DWORD)], W.BOOL),
            (self.k, "GetExitCodeProcess", [W.HANDLE, C.POINTER(W.DWORD)], W.BOOL),
            (self.k, "WaitForSingleObject", [W.HANDLE, W.DWORD], W.DWORD),
            (self.k, "TerminateProcess", [W.HANDLE, W.UINT], W.BOOL),
            (self.k, "CloseHandle", [W.HANDLE], W.BOOL),
            (self.k, "LocalFree", [W.HLOCAL], W.HLOCAL),
            (self.k, "CreateDirectoryW", [W.LPCWSTR, C.POINTER(SECURITY_ATTRIBUTES)], W.BOOL),
            (self.k, "CreateMutexW", [C.POINTER(SECURITY_ATTRIBUTES), W.BOOL, W.LPCWSTR], W.HANDLE),
            (self.k, "ReleaseMutex", [W.HANDLE], W.BOOL),
            (self.a, "OpenProcessToken", [W.HANDLE, W.DWORD, C.POINTER(W.HANDLE)], W.BOOL),
            (self.a, "GetTokenInformation", [W.HANDLE, C.c_int, W.LPVOID, W.DWORD, C.POINTER(W.DWORD)], W.BOOL),
            (self.a, "ConvertSidToStringSidW", [W.LPVOID, C.POINTER(W.LPWSTR)], W.BOOL),
            (self.a, "ConvertStringSecurityDescriptorToSecurityDescriptorW", [W.LPCWSTR, W.DWORD, C.POINTER(W.LPVOID), C.POINTER(W.DWORD)], W.BOOL),
            (self.a, "GetSecurityInfo", [W.HANDLE, C.c_int, W.DWORD, W.LPVOID, W.LPVOID, C.POINTER(W.LPVOID), W.LPVOID, C.POINTER(W.LPVOID)], W.DWORD),
            (self.a, "GetNamedSecurityInfoW", [W.LPWSTR, C.c_int, W.DWORD, W.LPVOID, W.LPVOID, C.POINTER(W.LPVOID), W.LPVOID, C.POINTER(W.LPVOID)], W.DWORD),
            (self.a, "GetAce", [W.LPVOID, W.DWORD, C.POINTER(W.LPVOID)], W.BOOL),
            (self.ip, "GetExtendedTcpTable", [W.LPVOID, C.POINTER(W.DWORD), W.BOOL, W.ULONG, C.c_int, W.ULONG], W.DWORD),
        )
        for dll, name, args, result in declarations:
            fn = getattr(dll, name)
            fn.argtypes, fn.restype = args, result
        self.sid = self._current_sid()

    @staticmethod
    def check(ok):
        if not ok:
            raise C.WinError(C.get_last_error())

    def _sid_string(self, sid):
        out = W.LPWSTR()
        self.check(self.a.ConvertSidToStringSidW(sid, C.byref(out)))
        try:
            return out.value
        finally:
            self.k.LocalFree(C.cast(out, W.HLOCAL))

    def _current_sid(self):
        token = W.HANDLE()
        self.check(self.a.OpenProcessToken(self.k.GetCurrentProcess(), 8, C.byref(token)))
        try:
            size = W.DWORD()
            self.a.GetTokenInformation(token, 1, None, 0, C.byref(size))
            buf = C.create_string_buffer(size.value)
            self.check(self.a.GetTokenInformation(token, 1, buf, size, C.byref(size)))
            return self._sid_string(C.cast(buf, C.POINTER(W.LPVOID))[0])
        finally:
            self.k.CloseHandle(token)

    def _security(self):
        sd = W.LPVOID()
        self.check(self.a.ConvertStringSecurityDescriptorToSecurityDescriptorW(
            "D:P(A;;GA;;;" + self.sid + ")", 1, C.byref(sd), None))
        return sd, SECURITY_ATTRIBUTES(C.sizeof(SECURITY_ATTRIBUTES), sd, False)

    def private_directory(self, path):
        sd, sa = self._security()
        try:
            self.check(self.k.CreateDirectoryW(str(path), C.byref(sa)))
        finally:
            self.k.LocalFree(sd)
        self.assert_user_only(path=path)

    def mutex(self, name):
        if not name.startswith("Global\\RelayPhaseA-"):
            raise Refusal("Global lease required")
        sd, sa = self._security()
        try:
            h = self.k.CreateMutexW(C.byref(sa), False, name)
            self.check(h)
        finally:
            self.k.LocalFree(sd)
        try:
            self.assert_user_only(handle=h)
        except BaseException:
            self.k.CloseHandle(h)
            raise
        return h

    def assert_user_only(self, *, path=None, handle=None):
        acl, sd = W.LPVOID(), W.LPVOID()
        if path is not None:
            canonical(path)
            err = self.a.GetNamedSecurityInfoW(str(path), 1, 4, None, None, C.byref(acl), None, C.byref(sd))
        else:
            err = self.a.GetSecurityInfo(handle, 6, 4, None, None, C.byref(acl), None, C.byref(sd))
        if err:
            raise C.WinError(err)
        try:
            if not acl:
                raise Refusal("null DACL")
            # ACL header: BYTE revision, BYTE reserved, WORD size, WORD count.
            count = C.c_ushort.from_address(acl.value + 4).value
            if count != 1:
                raise Refusal("DACL is not user-only")
            ace = W.LPVOID()
            self.check(self.a.GetAce(acl, 0, C.byref(ace)))
            if C.c_ubyte.from_address(ace.value).value != 0:
                raise Refusal("DACL grant missing")
            if self._sid_string(ace.value + 8) != self.sid:
                raise Refusal("DACL grants another principal")
            mask = W.DWORD.from_address(ace.value + 4).value
            if mask not in (0x10000000, 0x1F0001, 0x1F01FF):
                raise Refusal("DACL access mask")
        finally:
            self.k.LocalFree(sd)

    def identity(self, handle):
        pid = self.k.GetProcessId(handle)
        self.check(pid)
        times = [W.FILETIME() for _ in range(4)]
        self.check(self.k.GetProcessTimes(handle, *(C.byref(t) for t in times)))
        creation = (times[0].dwHighDateTime << 32) | times[0].dwLowDateTime
        buf, size = C.create_unicode_buffer(32768), W.DWORD(32768)
        self.check(self.k.QueryFullProcessImageNameW(handle, 0, buf, C.byref(size)))
        return Identity(pid, str(creation), canonical(buf.value))

    def wait(self, handle, seconds=0):
        result = self.k.WaitForSingleObject(handle, max(0, int(seconds * 1000)))
        if result not in (WAIT_OBJECT_0, WAIT_TIMEOUT):
            raise Refusal("unknown_exit: wait failed")
        return result == WAIT_OBJECT_0

    def exit_code(self, handle):
        code = W.DWORD()
        self.check(self.k.GetExitCodeProcess(handle, C.byref(code)))
        return code.value

    def listener(self, child, port):
        """Local IP Helper snapshot only, never connects or probes an endpoint."""
        if type(port) is not int or not 49152 <= port <= 65535 or port in FORBIDDEN_PORTS:
            raise Refusal("not an allowed ephemeral port")
        child.require_live()
        start = time.monotonic()
        size = W.DWORD()
        err = self.ip.GetExtendedTcpTable(None, C.byref(size), False, 2, 3, 0)
        if err != 122:
            raise Refusal("listener sizing failed")
        buf = C.create_string_buffer(size.value)
        err = self.ip.GetExtendedTcpTable(buf, C.byref(size), False, 2, 3, 0)
        if err:
            raise Refusal("listener sampling race")
        count = W.DWORD.from_buffer(buf).value
        if 4 + count * C.sizeof(TCP_ROW) > size.value:
            raise Refusal("listener table incomplete")
        matches = []
        for i in range(count):
            row = TCP_ROW.from_buffer(buf, 4 + i * C.sizeof(TCP_ROW))
            # Read only this child's assigned loopback endpoint as evidence.
            if row.address == int.from_bytes(socket.inet_aton("127.0.0.1"), "little") and socket.ntohs(row.port & 0xFFFF) == port and row.state == 2:
                matches.append(row.pid)
        child.require_live()
        if matches != [child.identity.pid] or time.monotonic() - start > 1:
            raise Refusal("listener PID/missing/race evidence")
        return ListenerEvidence("127.0.0.1", port, child.identity.pid,
                                child.identity.creation_time, start, child._correlation)


@dataclass(frozen=True)
class Identity:
    pid: int
    creation_time: str  # unsigned FILETIME decimal, never a display timestamp
    executable: str


@dataclass(frozen=True)
class ListenerEvidence:
    host: str
    port: int
    pid: int
    creation_time: str
    sampled: float
    correlation: str


@dataclass(frozen=True)
class Launch:
    interpreter_argv: tuple
    application_argv: tuple
    cwd: str
    data_root: str
    tag: str
    role: str
    generation: str
    nonce_hash: str
    handshake: str


class Journal:
    """Append-only durable records; malformed or incomplete histories refuse."""
    def __init__(self, directory, native):
        canonical(directory)
        native.assert_user_only(path=directory)
        self.path = Path(directory) / "custody.jsonl"
        if os.path.lexists(self.path):
            canonical(self.path)

    def append(self, event, generation=None, **fields):
        if os.path.lexists(self.path):
            canonical(self.path)
        canonical(self.path.parent)
        record = {"event": event, "generation": generation, **fields}
        raw = (json.dumps(record, sort_keys=True) + "\n").encode("utf-8")
        with self.path.open("ab", buffering=0) as f:
            if f.write(raw) != len(raw):
                raise Refusal("journal short write")
            os.fsync(f.fileno())

    def records(self):
        if not os.path.lexists(self.path):
            return []
        canonical(self.path)
        try:
            raw = self.path.read_bytes()
            if not raw.endswith(b"\n"):
                raise ValueError("partial record")
            return [json.loads(line) for line in raw.splitlines()]
        except (ValueError, OSError) as e:
            raise Refusal("unresolved journal: malformed") from e

    def require_resolved(self):
        states = {}
        for r in self.records():
            if not isinstance(r, dict):
                raise Refusal("unresolved journal: record")
            event, gen = r.get("event"), r.get("generation")
            if event in ("orphan_unknown", "unknown_exit"):
                raise Refusal("unresolved journal: " + event)
            prev = states.get(gen)
            allowed = {"launch_intent": (None,), "custody_established": ("launch_intent",),
                       "budget": ("custody_established",), "intentional_stop": ("budget", "launch_intent"),
                       "confirmed_exit": ("intentional_stop",)}
            if not gen or event not in allowed or prev not in allowed[event]:
                raise Refusal("unresolved journal: contradictory order")
            states[gen] = event
        if any(s != "confirmed_exit" for s in states.values()):
            raise Refusal("unresolved journal: incomplete launch")


class Lease:
    def __init__(self, native, journal, root):
        self.native, self.journal = native, journal
        user = hashlib.sha256(native.sid.encode()).hexdigest()
        identity = hashlib.sha256(canonical(root).encode()).hexdigest()
        self.name = "Global\\RelayPhaseA-" + user + "-" + identity
        self.handle, self.owned = None, False

    def acquire(self):
        if self.handle is not None:
            raise Refusal("lease already opened")
        self.handle = self.native.mutex(self.name)
        result = self.native.k.WaitForSingleObject(self.handle, 0)
        if result in (WAIT_OBJECT_0, WAIT_ABANDONED):
            self.owned = True
        try:
            if result == WAIT_ABANDONED:
                self.journal.append("orphan_unknown", reason="WAIT_ABANDONED")
                raise Refusal("abandoned lease: orphan_unknown")
            if result != WAIT_OBJECT_0:
                raise Refusal("competing lease or unknown wait")
            self.journal.require_resolved()
        except BaseException:
            self.close()
            raise

    def close(self):
        if self.handle is not None:
            if self.owned:
                self.native.check(self.native.k.ReleaseMutex(self.handle))
            self.native.check(self.native.k.CloseHandle(self.handle))
            self.handle, self.owned = None, False


class Child:
    def __init__(self, popen, native, launch):
        self._popen, self.native, self._launch = popen, native, launch
        self._handle = popen._handle  # Returned CreateProcess handle, never reopened.
        self._correlation = secrets.token_hex(32)
        self.closed, self.validated = False, False
        self._cleanup_result = None
        self._identity = native.identity(self._handle)
        self.require_live()

    @property
    def launch(self):
        return self._launch

    @property
    def identity(self):
        return self._identity

    @property
    def cleanup_result(self):
        return getattr(self, "_cleanup_result", None)

    def require_live(self):
        if self.closed or self.native.wait(self._handle):
            raise Refusal("retained child not live")
        if self.native.identity(self._handle) != self.identity:
            raise Refusal("contradictory retained-handle identity")
        if self.native.exit_code(self._handle) != 259:
            raise Refusal("contradictory exit evidence")

    def read_handshake(self):
        self.require_live()
        path = Path(self.launch.handshake)
        canonical(path)
        try:
            if path.stat().st_size > 65536:
                raise ValueError("oversize")
            # Reject duplicate JSON keys rather than accepting an ambiguous record.
            def unique(pairs):
                out = {}
                for k, v in pairs:
                    if k in out:
                        raise ValueError("duplicate key")
                    out[k] = v
                return out
            record = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique)
        except (OSError, ValueError) as e:
            raise Refusal("missing/malformed handshake") from e
        self.require_live()
        return record

    def validate(self, record, listener):
        self.require_live()
        if not isinstance(record, dict) or not isinstance(listener, ListenerEvidence):
            raise Refusal("missing evidence")
        launch, identity = self.launch, self.identity
        exact = {"generation": launch.generation, "nonce_hash": launch.nonce_hash,
                 "pid": identity.pid, "creation_time": identity.creation_time,
                 "tag": launch.tag, "role": launch.role,
                 "interpreter_flags": list(FLAGS),
                 "flags": {"isolated": 1, "no_site": 1, "dont_write_bytecode": 1, "no_user_site": 1},
                 "environment_clean": True, "customizations_loaded": False}
        for key, value in exact.items():
            if record.get(key) != value or type(record.get(key)) is not type(value):
                raise Refusal("handshake mismatch: " + key)
        if any(type(v) is not int for v in record["flags"].values()):
            raise Refusal("non-integer interpreter flags")
        for key, expected in (("executable", identity.executable), ("cwd", launch.cwd),
                              ("data_root", launch.data_root), ("handshake_path", launch.handshake)):
            corroborate_path(record.get(key), expected)
        if identity.executable != canonical(launch.interpreter_argv[0]):
            raise Refusal("retained executable mismatch")
        if launch.interpreter_argv[1:] != FLAGS:
            raise Refusal("interpreter argv mismatch")
        for key, expected in (("interpreter_argv", launch.interpreter_argv),
                              ("argv", launch.application_argv)):
            got = record.get(key)
            if not isinstance(got, list) or not got or tuple(got[1:]) != expected[1:]:
                raise Refusal("exact argv mismatch: " + key)
            corroborate_path(got[0], expected[0])
        if not isinstance(record.get("listener"), dict):
            raise Refusal("missing listener")
        if record["listener"] != {"host": listener.host, "port": listener.port}:
            raise Refusal("listener endpoint mismatch")
        if listener.host != "127.0.0.1" or listener.pid != identity.pid or listener.creation_time != identity.creation_time or listener.correlation != self._correlation:
            raise Refusal("listener custody mismatch")
        if not 0 <= time.monotonic() - listener.sampled <= 1:
            raise Refusal("stale listener evidence")
        # Re-sample immediately before granting custody; supplied evidence alone
        # can never grant authority, even if accidentally fabricated by a caller.
        self.native.listener(self, listener.port)
        self.require_live()
        self.validated = True

    def _cleanup_disposable(self, request_exit):
        """One six-second budget. Unknown exit keeps handle and paths retained."""
        if self.closed:
            raise Refusal("handle already closed")
        if self.cleanup_result is not None:
            raise Refusal("unknown_exit deadline exhausted; retain handle and paths")
        start = time.monotonic()
        errors = []
        try:
            request_exit()
        except Exception as e:
            errors.append(type(e).__name__)
        def wait_until(offset):
            return self.native.wait(self._handle, max(0, start + offset - time.monotonic()))
        try:
            confirmed = wait_until(2)
            if not confirmed:
                # Private fixture-only fallback, never exposed as a PID kill API.
                self.native.check(self.native.k.TerminateProcess(self._handle, 70))
                confirmed = wait_until(4)
            if not confirmed:
                confirmed = wait_until(6)
        except Exception as e:
            errors.append(type(e).__name__)
            try:
                confirmed = wait_until(6)
            except Exception:
                confirmed = False
        elapsed = time.monotonic() - start
        if not confirmed:
            self._cleanup_result = {"event": "unknown_exit", "elapsed": elapsed, "errors": errors}
            return self._cleanup_result
        code = self.native.exit_code(self._handle)
        self._popen.returncode = code
        # subprocess owns this handle object. Close only after a signaled wait.
        self._handle.Close()
        self.closed = True
        self._cleanup_result = {"event": "confirmed_exit", "code": code, "elapsed": elapsed, "errors": errors}
        return self._cleanup_result


class Controller:
    def __init__(self, root, sandbox, interpreter):
        self.root = disposable_root(root, sandbox)
        self.interpreter = str(Path(interpreter).resolve(strict=True))
        if canonical(self.interpreter) != canonical(sys.executable):
            raise Refusal("current absolute interpreter required")
        self.native = Native()
        control = self.root / "control"
        if not control.exists():
            self.native.private_directory(control)
        if not within(control, self.root):
            raise Refusal("control containment")
        self.journal = Journal(control, self.native)
        self.lease = Lease(self.native, self.journal, self.root)
        self.child = None

    def acquire(self):
        self.lease.acquire()

    def launch_fixture(self, script, cwd, data_root, tag, role, *, mode="normal"):
        if not self.lease.owned or self.child is not None:
            raise Refusal("exclusive lease required")
        self.journal.require_resolved()
        for path in (script, cwd, data_root):
            if not within(path, self.root):
                raise Refusal("fixture path outside disposable root")
        if Path(script).name != "disposable_relay_fixture.py" or mode not in ("normal", "missing", "denied", "ignore_stop"):
            raise Refusal("named disposable fixture only")
        generation, nonce = secrets.token_hex(24), secrets.token_hex(32)
        handshake_dir = self.root / ("handshake-" + generation)
        self.native.private_directory(handshake_dir)
        handshake = handshake_dir / "record.json"
        if mode == "denied":
            self.native.private_directory(handshake)
        app = (str(Path(script).resolve()), "fixture", str(handshake), nonce,
               generation, str(Path(data_root).resolve()), tag, role, mode)
        interp = (self.interpreter, *FLAGS)
        launch = Launch(interp, app, str(Path(cwd).resolve()), str(Path(data_root).resolve()),
                        tag, role, generation, hashlib.sha256(nonce.encode()).hexdigest(), str(handshake))
        self.journal.append("launch_intent", generation, interpreter_argv=list(interp),
                            application_argv=list(app), cwd=launch.cwd, data_root=launch.data_root,
                            handshake=launch.handshake, tag=tag, role=role)
        popen = subprocess.Popen([*interp, *app], executable=self.interpreter, shell=False, cwd=launch.cwd,
                                 env=fixture_environment(), stdin=subprocess.DEVNULL,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        # Assign custody immediately so handshake/identity failure cannot lose it.
        child = Child.__new__(Child)
        self.child = child
        Child.__init__(child, popen, self.native, launch)
        return child

    def establish(self):
        if self.child is None or self.child.validated:
            raise Refusal("one fresh handshake required")
        record = self.child.read_handshake()
        endpoint = record.get("listener", {}) if isinstance(record, dict) else {}
        if endpoint.get("host") != "127.0.0.1":
            raise Refusal("loopback required")
        listener = self.native.listener(self.child, endpoint.get("port"))
        self.child.validate(record, listener)
        gen = self.child.launch.generation
        self.journal.append("custody_established", gen, pid=self.child.identity.pid,
                            creation_time=self.child.identity.creation_time,
                            executable=self.child.identity.executable)
        self.journal.append("budget", gen, cleanup_seconds=6, listener_seconds=1)

    def stop(self, child):
        if child is not self.child or not isinstance(child, Child) or not child.validated:
            raise Refusal("stop requires this controller's validated retained child")
        child.require_live()
        return self._cleanup_fixture()

    def _cleanup_fixture(self):
        # Tests retain this exact launched handle even when validation refused.
        if self.child is None:
            return None
        child = self.child
        if child.cleanup_result is not None:
            raise Refusal("cleanup budget already exhausted; retain unknown custody")
        self.journal.append("intentional_stop", child.launch.generation)
        def graceful():
            target = Path(child.launch.handshake).parent / "stop"
            canonical(target.parent)
            with target.open("xb") as f:
                f.write(b"exit\n")
        result = child._cleanup_disposable(graceful)
        self.journal.append(result["event"], child.launch.generation,
                            **{k: v for k, v in result.items() if k != "event"})
        if result["event"] == "confirmed_exit":
            self.child = None
        return result

    def close(self):
        if self.child is not None:
            raise Refusal("retained child/unknown exit prevents controller close")
        self.lease.close()


def fixture_environment(**registered):
    """No inherited credentials or Python customization environment."""
    env = {"SystemRoot": os.environ["SystemRoot"]}
    env.update(registered)
    if any(k.upper() in ("PYTHONPATH", "PYTHONHOME") for k in env):
        raise Refusal("Python environment customization")
    return env
