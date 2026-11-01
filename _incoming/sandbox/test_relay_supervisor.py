"""Native Windows Phase A gate. No production imports or network connections.

Only PID reuse, contradictory snapshots, stale witnesses and unknown-exit
faults are simulated. Handle, listener, DACL, lease and abandonment are native.
"""
import ctypes
from dataclasses import replace
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

SANDBOX = Path(__file__).resolve().parent
INTERPRETER = str(Path(sys.executable).resolve(strict=True))
spec = importlib.util.spec_from_file_location("phase_a_supervisor", SANDBOX / "relay_supervisor.py")
S = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = S
spec.loader.exec_module(S)

# This complete stdlib-only program is written only to the disposable temp root.
# Helpers load an isolated copy of the Phase A module, never a Mesh module.
FIXTURE = r'''
import ctypes as C
from ctypes import wintypes as W
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import socket
import sys
import time

ROOT = Path(__file__).resolve().parent
STDLIB = Path(os.__file__).resolve().parent
OPENED = []
def contained(path, root):
    p, r = str(Path(path).resolve()).casefold(), str(root.resolve()).casefold()
    return p == r or p.startswith(r + os.sep)
def guard(event, args):
    if event == "open" and isinstance(args[0], (str, bytes, os.PathLike)):
        path = os.fsdecode(args[0])
        if not contained(path, ROOT) and not contained(path, STDLIB):
            raise RuntimeError("fixture opened outside registered roots")
        OPENED.append(str(Path(path).resolve()))
    if event in ("socket.connect", "socket.getaddrinfo", "subprocess.Popen"):
        raise RuntimeError("fixture external operation refused")
sys.addaudithook(guard)
assert sys.flags.isolated == sys.flags.no_site == sys.flags.no_user_site == 1
assert sys.flags.dont_write_bytecode == 1
assert not any(k.upper() in ("PYTHONPATH", "PYTHONHOME") for k in os.environ)
assert "site" not in sys.modules and "sitecustomize" not in sys.modules and "usercustomize" not in sys.modules

def publish(path, value):
    path = Path(path)
    temp = path.parent / ("atomic-" + str(os.getpid()) + ".tmp")
    with temp.open("xb") as f:
        f.write(json.dumps(value, sort_keys=True).encode())
        f.flush()
        os.fsync(f.fileno())
    try:
        os.link(temp, path)  # Atomic create-new publication; never replace.
    finally:
        temp.unlink()

def load_supervisor():
    spec = importlib.util.spec_from_file_location("isolated_phase_a", ROOT / "phase_a_copy.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod

mode = sys.argv[1]
if mode == "fixture":
    target, nonce, generation, data, tag, role, variant = sys.argv[2:]
    k = C.WinDLL("kernel32", use_last_error=True)
    k.GetCurrentProcess.argtypes, k.GetCurrentProcess.restype = [], W.HANDLE
    k.GetProcessTimes.argtypes, k.GetProcessTimes.restype = [W.HANDLE] + [C.POINTER(W.FILETIME)] * 4, W.BOOL
    times = [W.FILETIME() for _ in range(4)]
    assert k.GetProcessTimes(k.GetCurrentProcess(), *(C.byref(t) for t in times))
    creation = str((times[0].dwHighDateTime << 32) | times[0].dwLowDateTime)
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    sock.listen(1)  # No accept, connect, DNS or application service calls.
    host, port = sock.getsockname()
    assert 49152 <= port <= 65535 and port not in (8771, 8772, 8642, 8450)
    record = {"generation": generation, "nonce_hash": hashlib.sha256(nonce.encode()).hexdigest(),
              "pid": os.getpid(), "creation_time": creation,
              "executable": sys.executable, "interpreter_argv": sys.orig_argv[:4],
              "interpreter_flags": sys.orig_argv[1:4], "argv": sys.argv,
              "flags": {"isolated": sys.flags.isolated, "no_site": sys.flags.no_site,
                        "dont_write_bytecode": sys.flags.dont_write_bytecode,
                        "no_user_site": sys.flags.no_user_site},
              "cwd": os.getcwd(), "data_root": data, "tag": tag, "role": role,
              "handshake_path": target, "listener": {"host": host, "port": port},
              "environment_clean": True, "customizations_loaded": False,
              "modules": sorted(sys.modules), "opened": OPENED,
              "environment_keys": sorted(os.environ)}
    if variant != "missing":
        try:
            publish(target, record)
        except OSError as e:
            publish(Path(target).parent / "write-refusal.json", {"refused": True, "error": type(e).__name__, "winerror": e.winerror})
    stop = Path(target).parent / "stop"
    while variant == "ignore_stop" or not stop.exists():
        time.sleep(0.01)
    sock.close()
elif mode == "mutex-owner":
    sandbox = sys.argv[2]
    S = load_supervisor()
    controller = S.Controller(ROOT, sandbox, sys.executable)
    controller.acquire()
    controller.journal.append("launch_intent", "abandoned-fixture-intent", fixture_only=True)
    publish(ROOT / "owner-ready.json", {"name": controller.lease.name})
    while not (ROOT / "helper-stop").exists():
        time.sleep(0.01)
    # Deliberately exit without ReleaseMutex: the native OS marks it abandoned.
elif mode == "recreate":
    sandbox = sys.argv[2]
    S = load_supervisor()
    controller = S.Controller(ROOT, sandbox, sys.executable)
    try:
        controller.acquire()
    except S.Refusal as e:
        publish(ROOT / "recreation.json", {"refused": str(e), "launched": controller.child is not None})
    else:
        controller.close()
        publish(ROOT / "recreation.json", {"refused": None, "launched": False})
else:
    raise RuntimeError("unregistered helper mode")
'''

ROOTS = []
ARTIFACTS = []
OPENS = []
RETAINED_UNKNOWN = []


def await_file(path, child, seconds=2):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        child.require_live()
        if Path(path).is_file():
            return
        time.sleep(0.01)
    raise AssertionError("handshake/helper publication timeout: " + str(path))


class NativePhaseA(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if os.name != "nt":
            raise RuntimeError("BLOCKED: native Windows gate cannot be skipped")
        assert sys.flags.isolated == sys.flags.no_site == sys.flags.no_user_site == 1
        assert sys.flags.dont_write_bytecode == 1
        assert "site" not in sys.modules
        assert "sitecustomize" not in sys.modules and "usercustomize" not in sys.modules
        cls.native = S.Native()

    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="relay-phase-a-"))
        self.root = S.disposable_root(self.root, SANDBOX)
        ROOTS.append(str(self.root))
        self.controller = None
        self.helpers = []
        self.fixtures = []
        self.addCleanup(self.cleanup)
        self.script = self.root / "disposable_relay_fixture.py"
        self.script.write_text(FIXTURE, encoding="utf-8")
        (self.root / "phase_a_copy.py").write_bytes((SANDBOX / "relay_supervisor.py").read_bytes())
        self.data = self.root / "fixture-data"
        self.data.mkdir()
        self.controller = S.Controller(self.root, SANDBOX, INTERPRETER)
        self.controller.acquire()

    def cleanup(self):
        unknown = False
        for child in self.helpers:
            if child.cleanup_result is None:
                result = child._cleanup_disposable(lambda: (self.root / "helper-stop").touch())
            result = child.cleanup_result
            ARTIFACTS.append({"helper_cleanup": result, "root": str(self.root)})
            unknown |= result["event"] != "confirmed_exit"
            self.assertLessEqual(result["elapsed"], 6)
        if self.controller is not None and self.controller.child is not None:
            result = self.controller.child.cleanup_result or self.controller._cleanup_fixture()
            unknown |= result["event"] != "confirmed_exit"
            self.assertLessEqual(result["elapsed"], 6)
        for child in self.fixtures:
            ARTIFACTS.append({"fixture_cleanup": child.cleanup_result, "root": str(self.root)})
        if self.controller is not None:
            try:
                records = self.controller.journal.records()
            except S.Refusal as e:
                records = {"refused": str(e)}
            ARTIFACTS.append({"journal_records": records, "root": str(self.root)})
        if not unknown and self.controller is not None:
            self.controller.close()
        inventory = [{"path": str(p.relative_to(self.root)), "size": p.stat().st_size,
                      "directory": p.is_dir()} for p in self.root.rglob("*")]
        ARTIFACTS.append({"root": str(self.root), "inventory_before_removal": inventory,
                          "bytecode": [r for r in inventory if r["path"].endswith((".pyc", ".pyo"))],
                          "unknown_exit": unknown})
        if unknown:
            RETAINED_UNKNOWN.extend([self.controller, *self.helpers, *self.fixtures])
            raise RuntimeError("BLOCKED: unknown exit; root and exact handle retained")
        # This is the single just-created, canonical disposable root, after exit.
        S.disposable_root(self.root, SANDBOX)
        shutil.rmtree(self.root)
        ARTIFACTS.append({"root": str(self.root), "removed_after_confirmed_exit": not self.root.exists()})

    def launch(self, mode="normal", establish=False):
        child = self.controller.launch_fixture(self.script, self.root, self.data,
                                               "phase-a-disposable", "test", mode=mode)
        self.fixtures.append(child)
        if mode not in ("missing", "denied"):
            await_file(child.launch.handshake, child)
            ARTIFACTS.append({"native_handshake": child.read_handshake(), "root": str(self.root)})
        if establish:
            self.controller.establish()
        return child

    def helper(self, mode):
        argv = [INTERPRETER, *S.FLAGS, str(self.script), mode, str(SANDBOX)]
        popen = subprocess.Popen(argv, executable=INTERPRETER, shell=False, cwd=self.root, env=S.fixture_environment(),
                                 stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        launch = S.Launch(tuple(argv[:4]), tuple(argv[4:]), str(self.root), str(self.data),
                          "helper", mode, mode, "", str(self.root / "unused.json"))
        child = S.Child.__new__(S.Child)
        self.helpers.append(child)
        S.Child.__init__(child, popen, self.native, launch)
        ARTIFACTS.append({"helper_launch": argv, "root": str(self.root),
                          "pid": child.identity.pid, "creation_time": child.identity.creation_time})
        return child

    def evidence(self, child):
        record = child.read_handshake()
        return record, self.native.listener(child, record["listener"]["port"])

    def test_native_exact_identity_argv_listener_stop_and_journal(self):
        child = self.launch(establish=True)
        record = child.read_handshake()
        self.assertEqual(record["interpreter_argv"], [INTERPRETER, "-I", "-S", "-B"])
        self.assertNotIn("-B", record["argv"])
        self.assertEqual(record["argv"], list(child.launch.application_argv))
        self.assertEqual(child.identity.creation_time, str(int(child.identity.creation_time)))
        self.assertGreater(int(child.identity.creation_time), 0)
        self.assertLess(int(child.identity.creation_time), 2 ** 64)
        self.assertEqual(record["creation_time"], child.identity.creation_time)
        self.assertEqual(child.identity.pid, child._popen.pid)
        self.assertTrue(child.launch.handshake.startswith(str(self.root)))
        self.native.assert_user_only(path=Path(child.launch.handshake).parent)
        self.native.assert_user_only(handle=self.controller.lease.handle)
        self.assertTrue(self.controller.lease.name.startswith("Global\\RelayPhaseA-"))
        self.assertIn(hashlib.sha256(self.native.sid.encode()).hexdigest(), self.controller.lease.name)
        self.assertFalse(any(n in record["modules"] for n in
                             ("server", "relay_chat", "relay_runner", "site", "sitecustomize", "usercustomize")))
        self.assertEqual({k.upper() for k in record["environment_keys"]}, {"SYSTEMROOT", "LC_CTYPE"} if "LC_CTYPE" in record["environment_keys"] else {"SYSTEMROOT"})
        for p in record["opened"]:
            # Recorded at the guarded open; the atomic staging file is deleted
            # by publication, so historical containment is a lexical check.
            self.assertTrue(any(p.casefold().startswith(str(r.resolve()).casefold() + os.sep)
                                for r in (self.root, Path(os.__file__).parent)))
        result = self.controller.stop(child)
        self.assertEqual(result["event"], "confirmed_exit")
        self.assertEqual(result["code"], 0)
        self.assertTrue(child.closed)
        self.assertLessEqual(result["elapsed"], 6)
        records = self.controller.journal.records()
        self.assertEqual([r["event"] for r in records], ["launch_intent", "custody_established", "budget", "intentional_stop", "confirmed_exit"])
        self.controller.journal.require_resolved()
        self.controller.close()
        self.controller = S.Controller(self.root, SANDBOX, INTERPRETER)
        self.controller.acquire()
        self.assertIsNone(self.controller.child)  # No reconstruction from PID.

    def test_simulated_handshake_mutations_against_native_retained_child(self):
        child = self.launch()
        record, listener = self.evidence(child)
        other = self.root / "plausible-wrong.py"
        other.write_text("# unrelated\n", encoding="utf-8")
        mutations = {"tag": "other", "role": "other", "executable": str(other),
                     "cwd": str(self.data), "data_root": str(self.root),
                     "generation": "stale-generation", "pid": child.identity.pid + 1,
                     "creation_time": str(int(child.identity.creation_time) + 1),
                     "nonce_hash": "0" * 64, "handshake_path": str(other),
                     "argv": [str(other), *record["argv"][1:]],
                     "interpreter_argv": [INTERPRETER, "-I", "-S"],
                     "interpreter_flags": ["-I", "-S"],
                     "flags": {**record["flags"], "dont_write_bytecode": 0},
                     "listener": {"host": "127.0.0.1", "port": listener.port + 1}}
        for key, value in mutations.items():
            with self.subTest(field=key), self.assertRaises(S.Refusal):
                child.validate({**record, key: value}, listener)
        for argv in (["prefix " + record["argv"][0] + " suffix", *record["argv"][1:]],
                     [record["argv"][0], " ".join(record["argv"][1:])],
                     [*record["argv"], "extra"], record["argv"][:-1]):
            with self.subTest(spoof=argv), self.assertRaises(S.Refusal):
                child.validate({**record, "argv": argv}, listener)
        with self.assertRaises(S.Refusal):
            child.validate({**record, "creation_time": int(record["creation_time"])}, listener)
        self.assertFalse(child.validated)
        # Casefold path equality is accepted, exact application tokens remain exact.
        child.validate({**record, "executable": record["executable"].upper()}, listener)

    def test_simulated_listener_pid_reuse_stale_and_missing_refusal(self):
        child = self.launch()
        record, listener = self.evidence(child)
        for altered in (None, replace(listener, pid=listener.pid + 1),
                        replace(listener, creation_time=str(int(listener.creation_time) + 1)),
                        replace(listener, sampled=time.monotonic() - 2),
                        replace(listener, sampled=time.monotonic() + 2),
                        replace(listener, correlation="another-retained-handle")):
            with self.subTest(evidence=altered), self.assertRaises(S.Refusal):
                child.validate(record, altered)
        # Actual PID reuse is nondeterministic; this contradictory snapshot is labeled.
        with patch.object(child.native, "identity", return_value=replace(child.identity, creation_time="1")):
            with self.assertRaises(S.Refusal):
                child.require_live()
        with self.assertRaises(S.Refusal):
            self.native.listener(child, 8771)

    def test_native_missing_handshake_keeps_handle_for_cleanup(self):
        child = self.launch("missing")
        with self.assertRaises(S.Refusal):
            self.controller.establish()
        self.assertFalse(child.closed)
        child.require_live()

    def test_native_denied_atomic_handshake_reports_refusal(self):
        child = self.launch("denied")
        report = Path(child.launch.handshake).parent / "write-refusal.json"
        await_file(report, child)
        evidence = json.loads(report.read_text())
        self.assertTrue(evidence["refused"])
        self.assertIsNotNone(evidence["winerror"])
        self.assertTrue(Path(child.launch.handshake).is_dir())
        with self.assertRaises(S.Refusal):
            self.controller.establish()
        child.require_live()

    def test_native_create_new_cannot_overwrite_existing_handshake(self):
        child = self.launch()
        original = Path(child.launch.handshake).read_bytes()
        other = Path(child.launch.handshake).parent / "second-record.tmp"
        other.write_bytes(b"forged")
        with self.assertRaises(FileExistsError):
            os.link(other, child.launch.handshake)
        self.assertEqual(Path(child.launch.handshake).read_bytes(), original)
        self.controller.establish()
        with self.assertRaises(S.Refusal):
            self.controller.establish()  # Consumed witness cannot re-establish.

    def test_native_malformed_and_simulated_stale_handshake(self):
        child = self.launch()
        path = Path(child.launch.handshake)
        original = path.read_bytes()
        for raw in (b"{", b'{"pid":1,"pid":2}', b"null"):
            path.write_bytes(raw)
            with self.assertRaises(S.Refusal):
                self.controller.establish()
        path.write_bytes(original)
        record = child.read_handshake()
        record["generation"] = "old-controller"
        path.write_text(json.dumps(record))
        with self.assertRaises(S.Refusal):
            self.controller.establish()

    def test_native_unvalidated_and_numeric_pid_stop_refused(self):
        child = self.launch()
        for target in (child.identity.pid, child):
            with self.assertRaises(S.Refusal):
                self.controller.stop(target)
        for api in ("stop_pid", "adopt", "adopt_pid", "kill_all", "terminate_tree"):
            self.assertFalse(hasattr(self.controller, api))
        child.require_live()

    def test_native_other_listener_and_matching_tag_never_grant_custody(self):
        first = self.launch(establish=True)
        other_root = self.root / "separate-disposable-child"
        other_root.mkdir()
        script = other_root / "disposable_relay_fixture.py"
        script.write_text(FIXTURE, encoding="utf-8")
        data = other_root / "fixture-data"
        data.mkdir()
        other = S.Controller(other_root, SANDBOX, INTERPRETER)
        def cleanup_other():
            if other.child is not None:
                result = other._cleanup_fixture()
                ARTIFACTS.append({"second_fixture_cleanup": result, "root": str(other_root)})
                if result["event"] != "confirmed_exit":
                    # Parent cleanup must retain the entire root on unknown exit.
                    self.helpers.append(other.child)
                    raise RuntimeError("BLOCKED: second fixture unknown_exit")
                self.assertLessEqual(result["elapsed"], 6)
            other.close()
        self.addCleanup(cleanup_other)
        other.acquire()
        second = other.launch_fixture(script, other_root, data, "phase-a-disposable", "test")
        await_file(second.launch.handshake, second)
        other.establish()
        record = second.read_handshake()
        native_evidence = other.native.listener(second, record["listener"]["port"])
        self.assertEqual(record["tag"], first.launch.tag)
        with self.assertRaisesRegex(S.Refusal, "listener PID"):
            first.native.listener(first, native_evidence.port)
        with self.assertRaises(S.Refusal):
            first.validate(record, native_evidence)
        with self.assertRaises(S.Refusal):
            self.controller.stop(second)
        first.require_live()
        second.require_live()

    def test_native_expired_listener_and_exited_child_refuse(self):
        child = self.launch(establish=True)
        record, witness = self.evidence(child)
        time.sleep(1.05)
        with self.assertRaisesRegex(S.Refusal, "stale listener"):
            child.validate(record, witness)
        result = self.controller.stop(child)
        self.assertEqual(result["event"], "confirmed_exit")
        with self.assertRaises(S.Refusal):
            child.validate(record, witness)

    def test_simulated_unregistered_paths_refuse_before_filesystem_access(self):
        child = self.launch()
        record, witness = self.evidence(child)
        # This invented path is never resolved, statted or opened. Intercept
        # canonical() to prove the refusal precedes access to unregistered paths.
        invented = "Z:\\unregistered-phase-a-path\\never-opened.py"
        original = S.canonical
        visited = []
        def audited(path):
            visited.append(str(path))
            if str(path) == invented:
                raise AssertionError("unregistered path was inspected")
            return original(path)
        with patch.object(S, "canonical", side_effect=audited):
            for field in ("executable", "cwd", "data_root", "handshake_path"):
                with self.subTest(field=field), self.assertRaises(S.Refusal):
                    child.validate({**record, field: invented}, witness)
            for field in ("argv", "interpreter_argv"):
                with self.subTest(field=field), self.assertRaises(S.Refusal):
                    child.validate({**record, field: [invented, *record[field][1:]]}, witness)
        self.assertNotIn(invented, visited)
        with self.assertRaises(AttributeError):
            child.identity = replace(child.identity, pid=1)
        with self.assertRaises(AttributeError):
            child.launch = replace(child.launch, generation="other")

    def test_native_owned_handle_fallback_within_six_seconds(self):
        child = self.launch("ignore_stop", establish=True)
        result = self.controller.stop(child)
        self.assertEqual(result["event"], "confirmed_exit")
        self.assertEqual(result["code"], 70)
        self.assertGreaterEqual(result["elapsed"], 1.9)
        self.assertLessEqual(result["elapsed"], 6)

    def start_owner(self):
        self.controller.close()
        owner = self.helper("mutex-owner")
        await_file(self.root / "owner-ready.json", owner)
        return owner

    def test_native_cross_process_competing_lease(self):
        owner = self.start_owner()
        with self.assertRaisesRegex(S.Refusal, "competing lease"):
            self.controller.acquire()
        self.assertIsNone(self.controller.child)
        owner.require_live()

    def test_native_abandoned_mutex_with_preserving_handle(self):
        owner = self.start_owner()
        keeper = self.native.mutex(self.controller.lease.name)
        try:
            result = owner._cleanup_disposable(lambda: (self.root / "helper-stop").touch())
            self.assertEqual(result["event"], "confirmed_exit")
            self.assertLessEqual(result["elapsed"], 6)
            with self.assertRaisesRegex(S.Refusal, "abandoned lease: orphan_unknown"):
                self.controller.acquire()
            self.assertEqual(self.controller.journal.records()[-1]["event"], "orphan_unknown")
            self.assertIsNone(self.controller.child)
            helper = self.helper("recreate")
            # This helper can exit after atomic publication; wait through handle,
            # without using await_file's live-only handshake policy.
            self.assertTrue(helper.native.wait(helper._handle, 2))
            report = json.loads((self.root / "recreation.json").read_text())
            self.assertIn("unresolved journal", report["refused"])
            self.assertFalse(report["launched"])
        finally:
            self.native.k.CloseHandle(keeper)

    def test_native_abandoned_object_disappears_journal_still_blocks(self):
        owner = self.start_owner()
        # No preserving mutex handle: owner's exit destroys the named object.
        result = owner._cleanup_disposable(lambda: (self.root / "helper-stop").touch())
        self.assertEqual(result["event"], "confirmed_exit")
        helper = self.helper("recreate")
        self.assertTrue(helper.native.wait(helper._handle, 2))
        report = json.loads((self.root / "recreation.json").read_text())
        self.assertIn("unresolved journal: incomplete launch", report["refused"])
        self.assertFalse(report["launched"])
        self.assertNotIn("orphan_unknown", [r["event"] for r in self.controller.journal.records()])
        with self.assertRaisesRegex(S.Refusal, "unresolved journal"):
            self.controller.acquire()

    def test_native_incomplete_and_malformed_journal_recreation(self):
        self.controller.journal.append("launch_intent", "incomplete")
        self.controller.close()
        other = S.Controller(self.root, SANDBOX, INTERPRETER)
        with self.assertRaisesRegex(S.Refusal, "incomplete launch"):
            other.acquire()
        self.assertIsNone(other.child)
        with self.controller.journal.path.open("ab") as f:
            f.write(b"{partial")
            f.flush()
            os.fsync(f.fileno())
        with self.assertRaisesRegex(S.Refusal, "malformed"):
            other.acquire()

    def test_native_containment_reparse_and_unresolved_refusal(self):
        with self.assertRaises(S.Refusal):
            S.disposable_root(SANDBOX, SANDBOX)
        with self.assertRaises(S.Refusal):
            S.disposable_root(SANDBOX / ".verification", SANDBOX)
        with self.assertRaises(S.Refusal):
            S.canonical(self.root / "absent")
        with self.assertRaises(S.Refusal):
            S.canonical("relative")
        # Build an actual NTFS junction without a shell or privilege-dependent
        # symlink API, to prove native reparse refusal.
        junction = self.root / "junction"
        junction.mkdir()
        k = self.native.k
        k.CreateFileW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p,
                                 ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p]
        k.CreateFileW.restype = ctypes.c_void_p
        k.DeviceIoControl.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p, ctypes.c_uint32,
                                     ctypes.c_void_p, ctypes.c_uint32, ctypes.POINTER(ctypes.c_uint32), ctypes.c_void_p]
        k.DeviceIoControl.restype = ctypes.c_int
        h = k.CreateFileW(str(junction), 0x40000000, 0, None, 3, 0x02200000, None)
        self.assertNotEqual(h, ctypes.c_void_p(-1).value)
        try:
            import struct
            substitute = ("\\??\\" + str(self.data)).encode("utf-16-le")
            display = str(self.data).encode("utf-16-le")
            names = substitute + b"\0\0" + display + b"\0\0"
            body = struct.pack("<HHHH", 0, len(substitute), len(substitute) + 2, len(display)) + names
            raw = struct.pack("<IHH", 0xA0000003, len(body), 0) + body
            buffer = ctypes.create_string_buffer(raw)
            count = ctypes.c_uint32()
            self.native.check(k.DeviceIoControl(h, 0x000900A4, buffer, len(raw), None, 0, ctypes.byref(count), None))
        finally:
            k.CloseHandle(h)
        with self.assertRaisesRegex(S.Refusal, "reparse"):
            S.canonical(junction)
        junction.rmdir()  # Remove only the just-created junction, not its target.

    def test_simulated_unknown_exit_preserves_handle_and_paths(self):
        class Handle:
            closed = False
            def Close(self):
                self.closed = True
        class FakeNative:
            def __init__(self):
                self.k = self
                self.waits = []
            def wait(self, handle, seconds=0):
                self.waits.append(seconds)
                return False
            def TerminateProcess(self, handle, code):
                return True
            def check(self, value):
                pass
        child = S.Child.__new__(S.Child)
        child.closed, child._handle, child.native = False, Handle(), FakeNative()
        with patch.object(S.time, "monotonic", side_effect=[100, 100, 102, 104, 106]):
            result = child._cleanup_disposable(lambda: None)
        self.assertEqual(result["event"], "unknown_exit")
        self.assertEqual(result["elapsed"], 6)
        self.assertEqual(child.native.waits, [2, 2, 2])
        self.assertFalse(child.closed)
        self.assertFalse(child._handle.closed)
        with self.assertRaisesRegex(S.Refusal, "deadline exhausted"):
            child._cleanup_disposable(lambda: self.fail("no second cleanup budget"))
        self.controller.journal.append("unknown_exit", "simulated-only")
        self.controller.close()
        with self.assertRaisesRegex(S.Refusal, "unknown_exit"):
            self.controller.acquire()


def install_parent_guard():
    stdlib = Path(os.__file__).resolve().parent
    allowed = {str(SANDBOX / name).casefold() for name in ("relay_supervisor.py", "test_relay_supervisor.py")}
    allowed.update(str(SANDBOX / ".verification" / name).casefold() for name in
                   ("RELAY-LIFECYCLE-PHASE-A-DISPOSABLE-ROOT.txt", "RELAY-LIFECYCLE-PHASE-A-DISPOSABLE-INVENTORY.txt"))
    allowed.add(str(Path(os.devnull).resolve()).casefold())
    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    shell32.CommandLineToArgvW.argtypes = [ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_int)]
    shell32.CommandLineToArgvW.restype = ctypes.POINTER(ctypes.c_wchar_p)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.LocalFree.argtypes, kernel32.LocalFree.restype = [ctypes.c_void_p], ctypes.c_void_p
    def guard(event, args):
        if event == "open" and isinstance(args[0], (str, bytes, os.PathLike)):
            p = str(Path(os.fsdecode(args[0])).resolve()).casefold()
            roots = [str(stdlib).casefold(), *[r.casefold() for r in ROOTS]]
            if p not in allowed and not any(p == r or p.startswith(r + os.sep) for r in roots):
                # tempfile's initial candidate probe is contained in OS TEMP.
                temp = str(Path(os.environ["TEMP"]).resolve()).casefold()
                if not (p.startswith(temp + os.sep) and Path(p).parent == Path(temp)):
                    raise RuntimeError("BLOCKED: unregistered parent open: " + p)
            OPENS.append(p)
        if event in ("socket.connect", "socket.getaddrinfo"):
            raise RuntimeError("BLOCKED: network operation")
        if event == "subprocess.Popen":
            exe, argv, cwd, env = args
            if isinstance(argv, str):
                count = ctypes.c_int()
                tokens = shell32.CommandLineToArgvW(argv, ctypes.byref(count))
                if not tokens:
                    raise RuntimeError("BLOCKED: unparsed native argv")
                try:
                    argv = [tokens[i] for i in range(count.value)]
                finally:
                    kernel32.LocalFree(tokens)
            if S.canonical(exe) != S.canonical(INTERPRETER) or argv[1:4] != list(S.FLAGS):
                raise RuntimeError("BLOCKED: unregistered interpreter flags")
            if not any(S.within(cwd, r) for r in ROOTS if Path(r).exists()):
                raise RuntimeError("BLOCKED: unregistered child cwd")
            if set(env) != {"SystemRoot"}:
                raise RuntimeError("BLOCKED: unregistered environment")
    sys.addaudithook(guard)


if __name__ == "__main__":
    install_parent_guard()
    inventory_path = SANDBOX / ".verification" / "RELAY-LIFECYCLE-PHASE-A-DISPOSABLE-INVENTORY.txt"
    prior = json.loads(inventory_path.read_text(encoding="utf-8-sig")) if inventory_path.exists() else None
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(NativePhaseA))
    (SANDBOX / ".verification" / "RELAY-LIFECYCLE-PHASE-A-DISPOSABLE-ROOT.txt").write_text("\n".join(ROOTS) + "\n", encoding="utf-8")
    receipt = {"interpreter": INTERPRETER, "parent_flags": list(sys.orig_argv[1:4]),
               "roots": ROOTS, "artifacts": ARTIFACTS, "parent_open_events": OPENS,
               "all_roots_removed": all(not Path(r).exists() for r in ROOTS),
               "native": [t for t in dir(NativePhaseA) if t.startswith("test_native_")],
               "simulated": [t for t in dir(NativePhaseA) if t.startswith("test_simulated_")]}
    if prior:
        prior["roots_present_on_next_run"] = [r for r in prior["roots"] if Path(r).exists()]
        receipt["prior_run"] = prior
    inventory_path.write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    print("NATIVE_GATE=" + ("PASS" if result.wasSuccessful() else "BLOCKED"))
    print("INTERPRETER=" + INTERPRETER)
    print("DISPOSABLE_ROOTS=" + str(len(ROOTS)) + "; ALL_REMOVED=" + str(receipt["all_roots_removed"]))
    sys.exit(0 if result.wasSuccessful() else 1)
