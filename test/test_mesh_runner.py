"""Runner regressions using disposable Git repos and native stub CLI processes.

Run on Windows with: py -3.14 -m unittest discover -s test -p test_mesh_runner.py -v
Requires the runner's psutil dependency. No production jobs are invoked.
"""
import contextlib
import ctypes as C
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest import mock

from tools import mesh_runner
from lib import owned_job as oj


# Same event shape and usage as native.1.jsonl from the measured m0-hang.
# Configuration paths are fixture placeholders; nothing reads user settings.
WARNING = (
    "Codex is ignoring 3 unrecognized configuration settings. "
    "Check for typos or deprecated settings.\n"
    "  user (fixture/config.toml): `computer_use.windows.always_allowed_app_ids` is ignored.\n"
    "  user (fixture/config.toml): `profiles.ollama-launch.forced_login_method` is ignored.\n"
    "  user (fixture/config.toml): `profiles.ollama-launch.openai_base_url` is ignored."
)
USAGE = {"input_tokens": 19314, "cached_input_tokens": 13440,
         "cache_write_input_tokens": 0, "output_tokens": 42,
         "reasoning_output_tokens": 36}


def completed(kind, **fields):
    return {"type": "item.completed", "item": {"type": kind, **fields}}


def measured_events(text=""):
    return [
        {"type": "thread.started", "thread_id": "fixture-thread"},
        completed("error", id="item_0", message=WARNING),
        completed("error", id="item_1", message=WARNING),
        {"type": "turn.started"},
        completed("agent_message", id="item_2", text=text),
        {"type": "turn.completed", "usage": USAGE},
    ]


class MeshRunnerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="mesh-runner-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.repo = self.root / "fixture-repo"
        self.repo.mkdir()
        self.git("init", "-q")
        self.git("config", "user.name", "Runner Fixture")
        self.git("config", "user.email", "runner-fixture@example.invalid")
        self.git("config", "commit.gpgSign", "false")
        self.git("config", "core.hooksPath", str(self.root / "no-hooks"))
        (self.repo / ".gitignore").write_text(".runner/\n", encoding="utf-8")
        (self.repo / "seed.txt").write_text("fixture\n", encoding="utf-8")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "fixture seed")
        self.initial_commit = self.git("rev-parse", "HEAD").stdout.strip()
        self.prompt = self.root / "prompt.txt"
        self.prompt.write_text("Fixture prompt; never invoke real Codex.\n", encoding="utf-8")
        self.stub = self.root / "stub_cli.py"
        self.children = self.root / "children.txt"
        self.processes = []
        self.addCleanup(self.cleanup_processes)

    def git(self, *args, cwd=None):
        return subprocess.run(["git", "-C", str(cwd or self.repo), *args],
                              capture_output=True, text=True, check=True)

    def cleanup_processes(self):
        # Only processes launched by this test, or its uniquely named stub child.
        for proc in self.processes:
            if isinstance(proc, mesh_runner._WindowsProcess):
                proc.cleanup()
                continue
            if proc.poll() is None:
                mesh_runner.kill_tree(proc)
            proc.wait(timeout=15)
        if self.children.exists():
            for pid in map(int, self.children.read_text().splitlines()):
                try:
                    child = mesh_runner.psutil.Process(pid)
                    if str(self.stub) in child.cmdline():
                        child.kill()
                        child.wait(timeout=15)
                except mesh_runner.psutil.NoSuchProcess:
                    pass

    def run_fixture(self, events, *, exitcode=0, hang=False, idle=60, wall=60,
                    job_text=None, child=False, gate=None):
        self.stub.write_text(
            "import json, pathlib, subprocess, sys, time\n"
            "if '--fixture-child' in sys.argv:\n"
            "    time.sleep(60)\n"
            "    sys.exit(0)\n"
            "prompt = sys.stdin.read()\n"
            "assert 'Fixture prompt' in prompt and '--- RUNNER CONTRACT ---' in prompt\n"
            f"job_text = {job_text!r}\n"
            "if job_text is not None:\n"
            "    pathlib.Path('JOB.md').write_text(job_text, encoding='utf-8')\n"
            f"if {hang or child!r}:\n"
            "    child = subprocess.Popen([sys.executable, __file__, '--fixture-child'])\n"
            f"    with open({str(self.children)!r}, 'a') as f: f.write(str(child.pid) + '\\n')\n"
            f"gate = {str(gate) if gate else None!r}\n"
            "while gate and not pathlib.Path(gate).exists(): time.sleep(.01)\n"
            f"for event in {events!r}:\n"
            "    print(json.dumps(event), flush=True)\n"
            f"if {hang!r}: time.sleep(60)\n"
            f"sys.exit({exitcode!r})\n",
            encoding="utf-8",
        )
        real_launch = mesh_runner._launch_owned

        def launch(cmd, *args, **kwargs):
            if cmd[0] == str(self.stub):
                self.assertEqual(cmd[1], "exec")
                self.assertEqual(cmd[cmd.index("--sandbox") + 1], "workspace-write")
                self.assertIn('approval_policy="never"', cmd)
                self.assertEqual(cmd[cmd.index("--model") + 1], "gpt-6.1-sol")
                self.assertIn('model_reasoning_effort="high"', cmd)
                # Replace only the executable boundary with native Python. All
                # polling, clocks, log parsing, cleanup and host Git stay real.
                proc = real_launch([sys.executable, str(self.stub), *cmd[1:]],
                                  *args, **kwargs)
                self.processes.append(proc)
                return proc
            raise AssertionError("fixture attempted a non-stub CLI launch")

        argv = ["mesh_runner.py", "--repo", str(self.repo), "--job", "fixture",
                "--prompt-file", str(self.prompt), "--codex", str(self.stub),
                "--idle", str(idle), "--wall", str(wall)]
        with mock.patch.object(sys, "argv", argv), \
                mock.patch.object(mesh_runner, "_launch_owned", side_effect=launch), \
                contextlib.redirect_stdout(io.StringIO()), \
                self.assertRaises(SystemExit) as exited:
            mesh_runner.main()
        receipt = json.loads((self.repo / ".runner/fixture/RUN.json").read_text())
        self.assertIn("started", receipt)
        self.assertIn("ended", receipt)
        worktree = Path(receipt["worktree"])
        self.assertEqual(self.git("status", "--porcelain", cwd=worktree).stdout, "")
        for proc in self.processes:
            self.assertIsNotNone(proc.poll(), "fixture CLI was left running")
        return exited.exception.code, receipt

    def assert_zero_output(self, code, receipt, items, *, reason="done", returncode=0):
        self.assertEqual(code, 5)
        self.assertEqual(len(receipt["attempts"]), 2)
        for number, attempt in enumerate(receipt["attempts"], 1):
            self.assertEqual(attempt["attempt"], number)
            self.assertEqual(attempt["items"], items)
            self.assertEqual(attempt["output_items"], 0)
            self.assertEqual(attempt["tool_events"], 0)
            self.assertEqual(attempt["reason"], reason)
            self.assertEqual(attempt["returncode"], returncode)
            self.assertEqual(attempt["final_message"], "")
            self.assertGreaterEqual(attempt["seconds"], 0)

    def test_measured_warnings_and_empty_message_retry_then_exit_5(self):
        events = measured_events()
        code, receipt = self.run_fixture(events)
        self.assert_zero_output(code, receipt, 3)
        self.assertNotIn("commit", receipt)
        for attempt in receipt["attempts"]:
            self.assertEqual(attempt["usage"], USAGE)
            self.assertEqual(attempt["killed_pids"], [])
            native = Path(attempt["native_log"]).read_text().splitlines()
            self.assertEqual([json.loads(line) for line in native], events)

    def test_warnings_alone_retry_then_exit_5(self):
        code, receipt = self.run_fixture(measured_events()[:3])
        self.assert_zero_output(code, receipt, 2)

    def test_no_items_retry_then_exit_5(self):
        code, receipt = self.run_fixture([])
        self.assert_zero_output(code, receipt, 0)

    def test_nonempty_response_succeeds_and_host_commits_job_md(self):
        job_text = "Done: fixture work\nNext: fixture review\nBlocked: none\n"
        code, receipt = self.run_fixture(measured_events("Real response"), job_text=job_text)
        self.assertEqual(code, 0)
        self.assertEqual(len(receipt["attempts"]), 1)
        attempt = receipt["attempts"][0]
        self.assertEqual((attempt["items"], attempt["output_items"], attempt["tool_events"]),
                         (3, 1, 0))
        self.assertEqual(attempt["final_message"], "Real response")
        self.assertEqual(receipt["job_md"], job_text)
        self.assertNotEqual(receipt["commit"], self.initial_commit)
        self.assertEqual(self.git("rev-parse", receipt["branch"]).stdout.strip(), receipt["commit"])

    def test_later_empty_message_does_not_erase_real_output(self):
        events = measured_events("Real response") + [completed("agent_message", text="")]
        code, receipt = self.run_fixture(events)
        self.assertEqual(code, 0)
        self.assertEqual(len(receipt["attempts"]), 1)
        attempt = receipt["attempts"][0]
        self.assertEqual((attempt["items"], attempt["output_items"]), (4, 1))
        self.assertEqual(attempt["final_message"], "")

    def test_genuine_tool_events_including_failed_command_succeed(self):
        tools = [
            completed("command_execution", command="fixture-command", exit_code=7,
                      aggregated_output="fixture command failed", status="completed"),
            completed("file_change", changes=[{"path": "fixture.txt", "kind": "add"}],
                      status="completed"),
            completed("mcp_tool_call", server="fixture", tool="read_fixture",
                      arguments={}, result={"content": []}, status="completed"),
        ]
        for event in tools:
            with self.subTest(kind=event["item"]["type"]):
                code, receipt = self.run_fixture(measured_events() + [event])
                self.assertEqual(code, 0)
                self.assertEqual(len(receipt["attempts"]), 1)
                attempt = receipt["attempts"][0]
                self.assertEqual((attempt["items"], attempt["output_items"], attempt["tool_events"]),
                                 (4, 1, 1))

    def test_other_item_types_and_errors_keep_original_classification(self):
        for event in [completed("reasoning", text="Thinking about the fixture"),
                      completed("error", message="A different diagnostic"),
                      completed("future_tool_kind", text="Fixture activity")]:
            with self.subTest(item=event["item"]):
                code, receipt = self.run_fixture(measured_events() + [event])
                self.assertEqual(code, 0)
                self.assertEqual(len(receipt["attempts"]), 1)
                self.assertEqual(receipt["attempts"][0]["output_items"], 1)

    def assert_timeout_cleanup(self, receipt):
        children = list(map(int, self.children.read_text().splitlines()))
        self.assertEqual(len(children), len(receipt["attempts"]))
        for proc, child_pid, attempt in zip(self.processes, children, receipt["attempts"]):
            self.assertIn(proc.pid, attempt["killed_pids"])
            self.assertIn(child_pid, attempt["killed_pids"])
            self.assertFalse(mesh_runner.psutil.pid_exists(child_pid), "fixture child survived")
            self.assertGreaterEqual(attempt["seconds"], 1)
            self.assertLess(attempt["seconds"], 30)

    def test_idle_timeout_with_output_keeps_exit_2_cleanup_and_wip_commit(self):
        code, receipt = self.run_fixture(measured_events("Started work"), hang=True,
                                         idle=1, wall=60, job_text="Done: WIP\n")
        self.assertEqual(code, 2)
        self.assertEqual(len(receipt["attempts"]), 1)
        self.assertEqual(receipt["attempts"][0]["reason"], "idle-timeout")
        self.assertIn("commit", receipt)
        self.assert_timeout_cleanup(receipt)

    def test_wall_timeout_with_output_keeps_exit_3_and_cleanup(self):
        code, receipt = self.run_fixture(measured_events("Started work"), hang=True,
                                         idle=60, wall=1)
        self.assertEqual(code, 3)
        self.assertEqual(len(receipt["attempts"]), 1)
        self.assertEqual(receipt["attempts"][0]["reason"], "wall-timeout")
        self.assert_timeout_cleanup(receipt)

    def test_silent_idle_timeout_keeps_two_attempts_exit_5_and_cleanup(self):
        code, receipt = self.run_fixture([], hang=True, idle=1, wall=60)
        self.assertEqual(code, 5)
        self.assertEqual(len(receipt["attempts"]), 2)
        for attempt in receipt["attempts"]:
            self.assertEqual(attempt["reason"], "idle-timeout")
            self.assertEqual((attempt["items"], attempt["output_items"], attempt["tool_events"]),
                             (0, 0, 0))
        self.assert_timeout_cleanup(receipt)

    def test_failing_cli_without_real_output_preserves_returncodes_and_retry_budget(self):
        code, receipt = self.run_fixture(measured_events(), exitcode=7)
        self.assert_zero_output(code, receipt, 3, reason="codex-error", returncode=7)

    def test_nonempty_response_then_nonzero_cli_is_codex_error_and_commits_wip(self):
        code, receipt = self.run_fixture(measured_events("Progress before failure"),
                                         exitcode=7, job_text="Done: WIP\n")
        self.assertEqual(code, 4)
        self.assertEqual(len(receipt["attempts"]), 1)
        attempt = receipt["attempts"][0]
        self.assertEqual((attempt["reason"], attempt["returncode"]), ("codex-error", 7))
        self.assertEqual((attempt["items"], attempt["output_items"], attempt["tool_events"]),
                         (3, 1, 0))
        self.assertEqual(attempt["final_message"], "Progress before failure")
        self.assertEqual(attempt["usage"], USAGE)
        self.assertIn("commit", receipt)

    def test_native_natural_root_exit_cleans_retained_surviving_child(self):
        self.assertEqual(sys.platform, "win32", "native Windows acceptance requires Windows")
        gate = self.root / "root-exit.gate"
        results, errors = [], []

        def run():
            try:
                results.append(self.run_fixture(measured_events("Finished root"),
                                                child=True, gate=gate))
            except BaseException as error:
                errors.append(error)

        worker = threading.Thread(target=run, daemon=True)
        worker.start()
        api = mesh_runner._Win32()
        handle = None
        try:
            end = time.monotonic() + 10
            pid = None
            while time.monotonic() < end:
                try:
                    pid = int(self.children.read_text().splitlines()[0])
                    break
                except (OSError, ValueError, IndexError):
                    time.sleep(.01)
            self.assertIsNotNone(pid, "stub did not publish child identity")
            identity = mesh_runner.psutil.Process(pid)
            created = identity.create_time()
            self.assertIn(str(self.stub), identity.cmdline())
            handle = api.OpenProcess(0x00100000 | 0x1000 | 1, False, pid)
            self.assertTrue(handle)
            self.assertEqual(api.WaitForSingleObject(handle, 0), 258)
            belongs = C.c_int32()
            self.assertTrue(api.IsProcessInJob(handle, self.processes[0].job, C.byref(belongs)))
            self.assertTrue(belongs.value, "child was outside pre-resume custody")
            self.assertEqual(identity.create_time(), created)
            gate.touch()
            worker.join(20)
            self.assertFalse(worker.is_alive())
            self.assertEqual(errors, [])
            self.assertEqual(len(results), 1)
            code, receipt = results[0]
            self.assertEqual(code, 0)
            self.assertEqual(len(receipt["attempts"]), 1)
            attempt = receipt["attempts"][0]
            self.assertEqual((attempt["reason"], attempt["returncode"]), ("done", 0))
            self.assertIn(pid, attempt["killed_pids"])
            self.assertTrue(self.processes[0].cleanup_verified)
            # Exact kernel process object retained while alive: no PID absence
            # or post-exit tree walk can substitute for this exit proof.
            self.assertEqual(api.WaitForSingleObject(handle, 0), 0)
        finally:
            gate.touch()
            worker.join(20)
            if handle:
                if api.WaitForSingleObject(handle, 0) == 258:
                    self.assertTrue(api.TerminateProcess(handle, 1))
                    self.assertEqual(api.WaitForSingleObject(handle, 3000), 0)
                self.assertTrue(api.CloseHandle(handle))
            self.assertFalse(worker.is_alive())

    def test_host_command_failure_is_still_reported(self):
        with self.assertRaisesRegex(RuntimeError, "fixture host failure"):
            mesh_runner.sh([sys.executable, "-c",
                            "import sys; print('fixture host failure'); sys.exit(7)"])
        result = mesh_runner.sh([sys.executable, "-c", "import sys; sys.exit(7)"], check=False)
        self.assertEqual(result.returncode, 7)

    def test_empty_message_and_warning_filter_is_narrow(self):
        for text in ("", " \r\n\t"):
            self.assertFalse(mesh_runner.is_output_item({"type": "agent_message", "text": text}))
        self.assertTrue(mesh_runner.is_output_item({"type": "agent_message", "text": "response"}))
        self.assertFalse(mesh_runner.is_output_item({"type": "error", "message": WARNING}))
        self.assertTrue(mesh_runner.is_output_item({"type": "error", "message": "other error"}))
        self.assertTrue(mesh_runner.is_output_item({"type": "command_execution"}))


class NativeCustodyTests(unittest.TestCase):
    def setUp(self):
        self.assertEqual(sys.platform, "win32", "native Windows acceptance requires Windows")
        self.temp = tempfile.TemporaryDirectory(prefix="mesh-custody-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.api = oj._Win32()
        self.proofs = []
        self.addCleanup(self.dispose_proofs)

    def dispose_proofs(self):
        for handle in self.proofs:
            if self.api.WaitForSingleObject(handle, 0) == 258:
                self.assertTrue(self.api.TerminateProcess(handle, 1))
                self.assertEqual(self.api.WaitForSingleObject(handle, 3000), 0)
            self.assertTrue(self.api.CloseHandle(handle))
        self.proofs.clear()

    def retain(self, handle):
        import _winapi
        current = _winapi.GetCurrentProcess()
        proof = _winapi.DuplicateHandle(current, handle, current, 0, False,
                                       _winapi.DUPLICATE_SAME_ACCESS)
        self.proofs.append(proof)
        return proof

    def handle_count(self):
        count = oj.DWORD()
        self.assertTrue(self.api.GetProcessHandleCount(self.api.GetCurrentProcess(), C.byref(count)))
        return count.value

    def test_acquisition_failures_never_execute_root_and_release_handles(self):
        import _winapi
        sentinel = self.root / "ran.txt"
        cmd = [sys.executable, "-I", "-c",
               f"import pathlib,time; pathlib.Path({str(sentinel)!r}).touch(); time.sleep(30)"]
        real_api = mesh_runner._Win32
        real_create = _winapi.CreateProcess
        real_duplicate = _winapi.DuplicateHandle
        real_close = _winapi.CloseHandle
        # Warm only the native adapter/runtime, without launching any manager.
        with open(self.root / "warm.log", "wb") as log:
            warm = mesh_runner._WindowsProcess([sys.executable, "-I", "-c", "pass"],
                                               self.root, log, log)
            warm.cleanup()

        for failure in ("CreateJobObjectW", "SetInformationJobObject", "DuplicateHandle",
                        "CreateProcess", "AssignProcessToJobObject", "ResumeThread",
                        "stream-close"):
            with self.subTest(failure=failure):
                before = self.handle_count()
                proofs, calls = [], []
                native = real_api()

                class Proxy:
                    def __getattr__(proxy, name):
                        fn = getattr(native, name)

                        def call(*args):
                            calls.append(name)
                            if name == failure:
                                C.set_last_error(5)
                                return 0xffffffff if name == "ResumeThread" else 0
                            return fn(*args)
                        return call

                def create(*args):
                    if failure == "CreateProcess":
                        raise OSError("injected CreateProcess failure")
                    self.assertTrue(args[5] & 0x4, "root was not created suspended")
                    acquired = real_create(*args)
                    # Independent root identity survives the runner closing its
                    # own process handle, including failed pre-resume assignment.
                    current = _winapi.GetCurrentProcess()
                    proof = real_duplicate(current, acquired[0], current, 0, False,
                                           _winapi.DUPLICATE_SAME_ACCESS)
                    self.proofs.append(proof)
                    proofs.append(proof)
                    return acquired

                injected = False

                def close(handle):
                    nonlocal injected
                    if failure == "stream-close" and not injected:
                        injected = True
                        raise OSError("injected stream close failure")
                    return real_close(handle)

                def duplicate(*args):
                    if failure == "DuplicateHandle":
                        raise OSError("injected DuplicateHandle failure")
                    return real_duplicate(*args)

                with open(self.root / "out.log", "wb") as log, \
                        mock.patch.object(mesh_runner, "_Win32", return_value=Proxy()), \
                        mock.patch.object(_winapi, "CreateProcess", side_effect=create), \
                        mock.patch.object(_winapi, "DuplicateHandle", side_effect=duplicate), \
                        mock.patch.object(_winapi, "CloseHandle", side_effect=close), \
                        self.assertRaises((OSError, RuntimeError)):
                    mesh_runner._WindowsProcess(cmd, self.root, log, log)
                self.assertFalse(sentinel.exists(), "uncustodied root executed")
                if failure == "AssignProcessToJobObject":
                    self.assertNotIn("ResumeThread", calls)
                    self.assertIn("TerminateProcess", calls)
                if failure == "ResumeThread":
                    self.assertLess(calls.index("AssignProcessToJobObject"), calls.index("ResumeThread"))
                    self.assertIn("TerminateJobObject", calls)
                for proof in proofs:
                    self.assertEqual(self.api.WaitForSingleObject(proof, 0), 0)
                self.dispose_proofs()
                self.assertEqual(self.handle_count(), before, "native acquisition leaked handles")

    def exercise_exception(self, failure):
        pid_file = self.root / "child.pid"
        stub = self.root / "exception_stub.py"
        stub.write_text(
            "import pathlib,subprocess,sys,time\n"
            "sys.stdin.read()\n"
            "child = subprocess.Popen([sys.executable, '-I', '-c', 'import time; time.sleep(30)'])\n"
            f"pathlib.Path({str(pid_file)!r}).write_text(str(child.pid))\n"
            "print('{\"type\":\"item.completed\",\"item\":{\"type\":\"agent_message\",\"text\":\"working\"}}', flush=True)\n"
            "time.sleep(30)\n", encoding="utf-8")
        prompt = self.root / "prompt.txt"
        prompt.write_text("Fixture prompt", encoding="utf-8")
        args = SimpleNamespace(codex=str(stub), model="gpt-6.1-sol", effort="high",
                               prompt_file=str(prompt), idle=60, wall=60)
        real_launch = mesh_runner._launch_owned
        real_stat = Path.stat
        processes, child_proofs = [], []

        def retain_child(proc):
            end = time.monotonic() + 5
            pid = None
            while time.monotonic() < end:
                try:
                    pid = int(pid_file.read_text())
                    break
                except (OSError, ValueError):
                    time.sleep(.01)
            self.assertIsNotNone(pid, "exception stub did not spawn")
            handle = self.api.OpenProcess(0x00100000 | 0x1000 | 1, False, pid)
            self.assertTrue(handle)
            self.proofs.append(handle)
            child_proofs.append(handle)
            belongs = oj.BOOL()
            self.assertTrue(self.api.IsProcessInJob(handle, proc.job, C.byref(belongs)))
            self.assertTrue(belongs.value)
            self.assertEqual(self.api.WaitForSingleObject(handle, 0), 258)

        def launch(cmd, *launch_args):
            self.assertEqual(cmd[0], str(stub))
            proc = real_launch([sys.executable, "-I", str(stub), *cmd[1:]], *launch_args)
            processes.append(proc)
            self.retain(proc.process)
            original_poll = proc.poll
            if failure == "stdin":
                original_stdin = proc.stdin

                class BrokenInput:
                    def write(self, data):
                        raise OSError("injected stdin failure")

                    def close(self):
                        original_stdin.close()
                proc.stdin = BrokenInput()
            elif failure == "poll":
                def poll():
                    retain_child(proc)
                    raise OSError("injected poll failure")
                proc.poll = poll
            elif failure in ("OpenProcess", "IsProcessInJob", "members", "terminate", "close"):
                injected = False
                if failure == "members":
                    original = proc.api.QueryInformationJobObject

                    def query(*query_args):
                        nonlocal injected
                        if query_args[1] == 3 and not injected:
                            injected = True
                            C.set_last_error(5)
                            return 0
                        return original(*query_args)
                    proc.api.QueryInformationJobObject = query
                else:
                    name = {"terminate": "TerminateJobObject", "close": "CloseHandle"}.get(failure, failure)
                    original = getattr(proc.api, name)

                    def bad_call(*call_args):
                        nonlocal injected
                        if not injected:
                            injected = True
                            C.set_last_error(5)
                            return 0
                        return original(*call_args)
                    setattr(proc.api, name, bad_call)

                def poll():
                    retain_child(proc)
                    # Force cleanup without waiting for the idle/wall deadlines.
                    return 0
                proc.poll = poll
            else:
                proc.poll = original_poll
            return proc

        def stat(path, *stat_args, **kwargs):
            if failure == "read" and path.name == "native.1.jsonl":
                retain_child(processes[0])
                raise OSError("injected native-log read failure")
            return real_stat(path, *stat_args, **kwargs)

        with mock.patch.object(mesh_runner, "_launch_owned", side_effect=launch), \
                mock.patch.object(Path, "stat", stat), \
                self.assertRaisesRegex((OSError, RuntimeError), "injected|native custody cleanup failed"):
            mesh_runner.run_codex(args, self.root, self.root, 1)
        self.assertEqual(len(processes), 1)
        self.assertTrue(processes[0].closed)
        self.assertIsNotNone(processes[0].returncode)
        for proof in self.proofs:
            self.assertEqual(self.api.WaitForSingleObject(proof, 0), 0,
                             "owned process survived exception cleanup")
        if failure != "stdin":
            self.assertEqual(len(child_proofs), 1)
        if failure in ("stdin", "poll", "read"):
            self.assertTrue(processes[0].cleanup_verified)
        else:
            self.assertFalse(processes[0].cleanup_verified, "native failure was silently accepted")

    def test_stdin_exception_cleans_root(self):
        self.exercise_exception("stdin")

    def test_poll_exception_cleans_root_and_descendant(self):
        self.exercise_exception("poll")

    def test_live_log_read_exception_cleans_root_and_descendant(self):
        self.exercise_exception("read")

    def test_member_acquisition_failures_are_fatal_and_still_clean_job(self):
        for failure in ("OpenProcess", "IsProcessInJob", "members"):
            with self.subTest(failure=failure):
                self.exercise_exception(failure)
                self.dispose_proofs()
                (self.root / "child.pid").unlink()

    def test_termination_and_close_failures_are_fatal_even_after_retry(self):
        for failure in ("terminate", "close"):
            with self.subTest(failure=failure):
                self.exercise_exception(failure)
                self.dispose_proofs()
                (self.root / "child.pid").unlink()


if __name__ == "__main__":
    unittest.main()
