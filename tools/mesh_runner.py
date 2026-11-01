#!/usr/bin/env python3
"""
mesh_runner.py — v2 job runner for Mesh builders.

One job = one git worktree on branch job/<name>. Codex gets real tools
(workspace-write), a long wall clock and an idle timeout. Output is commits,
not serialized source. Zero-output runs are retried once. Everything is logged.

Usage:
  python mesh_runner.py --repo D:\\Dev\\Onoes-Mesh --job m1-task-persist ^
      --prompt-file jobs\\m1-task-persist.md [--wall 14400] [--idle 600] ^
      [--model gpt-6.1-sol] [--effort high] [--codex codex]

Exit codes: 0 done, 2 idle-timeout, 3 wall-timeout, 4 codex error, 5 zero output twice.
Requires: git, codex CLI, psutil (pip install psutil).
"""
import argparse, ctypes as C, datetime as dt, json, os, re, subprocess, sys, time
from pathlib import Path

try:
    import psutil
except ImportError:
    sys.exit("pip install psutil")

def now():
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")

def sh(args, cwd=None, check=True):
    r = subprocess.run(args, cwd=cwd, capture_output=True, text=True)
    if check and r.returncode != 0:
        raise RuntimeError(f"{' '.join(map(str,args))}\n{r.stdout}\n{r.stderr}")
    return r

def kill_tree(proc: subprocess.Popen):
    try:
        p = psutil.Process(proc.pid)
    except psutil.NoSuchProcess:
        return []
    kids = p.children(recursive=True)
    for c in kids + [p]:
        try: c.terminate()
        except psutil.Error: pass
    gone, alive = psutil.wait_procs(kids + [p], timeout=10)
    for c in alive:
        try: c.kill()
        except psutil.Error: pass
    return [c.pid for c in kids + [p]]


class _BasicLimits(C.Structure):
    _fields_ = [('user_time', C.c_int64), ('job_time', C.c_int64),
                ('flags', C.c_uint32), ('min_ws', C.c_size_t),
                ('max_ws', C.c_size_t), ('process_limit', C.c_uint32),
                ('affinity', C.c_size_t), ('priority', C.c_uint32),
                ('scheduling', C.c_uint32)]


class _ExtendedLimits(C.Structure):
    _fields_ = [('basic', _BasicLimits), ('io', C.c_uint64 * 6),
                ('process_memory', C.c_size_t), ('job_memory', C.c_size_t),
                ('peak_process', C.c_size_t), ('peak_job', C.c_size_t)]


class _Accounting(C.Structure):
    _fields_ = [('times', C.c_int64 * 4), ('page_faults', C.c_uint32),
                ('total', C.c_uint32), ('active', C.c_uint32),
                ('terminated', C.c_uint32)]


class _Win32:
    def __init__(self):
        expected = 144 if C.sizeof(C.c_void_p) == 8 else 112
        if C.sizeof(_ExtendedLimits) != expected or C.sizeof(_Accounting) != 48:
            raise RuntimeError('native job layout mismatch')
        dll = C.WinDLL('kernel32', use_last_error=True)
        handle, dword, boolean = C.c_void_p, C.c_uint32, C.c_int32
        signatures = {
            'CreateJobObjectW': (handle, [handle, C.c_wchar_p]),
            'SetInformationJobObject': (boolean, [handle, C.c_int, handle, dword]),
            'QueryInformationJobObject': (boolean, [handle, C.c_int, handle, dword, C.POINTER(dword)]),
            'AssignProcessToJobObject': (boolean, [handle, handle]),
            'ResumeThread': (dword, [handle]),
            'WaitForSingleObject': (dword, [handle, dword]),
            'GetExitCodeProcess': (boolean, [handle, C.POINTER(dword)]),
            'TerminateJobObject': (boolean, [handle, dword]),
            'TerminateProcess': (boolean, [handle, dword]),
            'CloseHandle': (boolean, [handle]),
            'OpenProcess': (handle, [dword, boolean, dword]),
            'IsProcessInJob': (boolean, [handle, handle, C.POINTER(boolean)]),
        }
        for name, (result, args) in signatures.items():
            fn = getattr(dll, name)
            fn.restype, fn.argtypes = result, args
            setattr(self, name, fn)


class _WindowsProcess:
    """Own the suspended root and its job until exact-process cleanup is proven.

    CPython's CreateProcess adapter supplies an explicit inherited handle list;
    unlike Popen, keep the primary thread handle until job assignment/resume.
    No breakaway flags are enabled. Descendants inherit native job custody even
    when their parent exits before the runner next polls its log.
    """
    def __init__(self, cmd, cwd, out, err):
        import _winapi
        import msvcrt

        self.api = _Win32()
        self.job = self.process = self.thread = self.stdin = None
        self.pid = self.returncode = None
        self.assigned = self.cleanup_verified = False
        self.killed_pids = []
        self.closed = False
        read_fd = write_fd = None
        inherited = []

        def release_streams():
            errors = []
            for handle in inherited:
                for unused in range(2):
                    try:
                        _winapi.CloseHandle(handle)
                        break
                    except OSError as error:
                        errors.append(str(error))
            for fd in (read_fd, write_fd):
                if fd is not None:
                    try:
                        os.close(fd)
                    except OSError as error:
                        errors.append(str(error))
            if errors:
                raise RuntimeError('native stream release failed: ' + '; '.join(errors))

        try:
            try:
                self.job = self.api.CreateJobObjectW(None, None)
                self._check(self.job, 'CreateJobObjectW')
                limits = _ExtendedLimits()
                limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
                self._check(self.api.SetInformationJobObject(
                    self.job, 9, C.byref(limits), C.sizeof(limits)), 'SetInformationJobObject')
                read_fd, write_fd = os.pipe()
                self.stdin = os.fdopen(write_fd, 'wb')
                write_fd = None  # stdin now owns it
                current = _winapi.GetCurrentProcess()
                for file in (read_fd, out.fileno(), err.fileno()):
                    inherited.append(_winapi.DuplicateHandle(
                        current, msvcrt.get_osfhandle(file), current,
                        0, True, _winapi.DUPLICATE_SAME_ACCESS))
                startup = subprocess.STARTUPINFO()
                startup.dwFlags = subprocess.STARTF_USESTDHANDLES
                startup.hStdInput, startup.hStdOutput, startup.hStdError = inherited
                startup.lpAttributeList = {'handle_list': inherited}
                self.process, self.thread, self.pid, _ = _winapi.CreateProcess(
                    None, subprocess.list2cmdline(cmd), None, None, True,
                    0x4 | subprocess.CREATE_NO_WINDOW, None, str(cwd), startup)
                self._check(self.process and self.thread and self.pid,
                            'CreateProcess incomplete acquisition')
            finally:
                # Release only parent duplicates before the root can execute.
                release_streams()
            self._check(self.api.AssignProcessToJobObject(self.job, self.process),
                        'AssignProcessToJobObject')
            self.assigned = True
            if self.api.ResumeThread(self.thread) != 1:
                raise OSError('ResumeThread failed or unexpected suspend count')
        except BaseException:
            self.cleanup()
            raise

    @staticmethod
    def _check(value, name):
        if not value:
            raise OSError(f'{name}: winerror {C.get_last_error()}')
        return value

    def _wait(self, handle, milliseconds):
        state = self.api.WaitForSingleObject(handle, milliseconds)
        if state not in (0, 258):
            raise OSError(f'WaitForSingleObject: winerror {C.get_last_error()}')
        return state

    def poll(self):
        if self.returncode is None and self._wait(self.process, 0) == 0:
            code = C.c_uint32()
            self._check(self.api.GetExitCodeProcess(self.process, C.byref(code)),
                        'GetExitCodeProcess')
            self.returncode = code.value
        return self.returncode

    def _active(self):
        info, used = _Accounting(), C.c_uint32()
        self._check(self.api.QueryInformationJobObject(
            self.job, 1, C.byref(info), C.sizeof(info), C.byref(used)),
            'QueryInformationJobObject accounting')
        if used.value != C.sizeof(info):
            raise OSError('incorrect job accounting size')
        return info.active

    def _retain_members(self, handles, deadline):
        # PID lookup is only acquisition: membership rejects PID reuse. Keep
        # exact process handles before termination, since accounting zero can
        # precede process signaling (as measured by lib/owned_job.py).
        capacity = 16
        while time.monotonic() < deadline:
            class ProcessIds(C.Structure):
                _fields_ = [('assigned', C.c_uint32), ('count', C.c_uint32),
                            ('pids', C.c_size_t * capacity)]
            info, used = ProcessIds(), C.c_uint32()
            ok = self.api.QueryInformationJobObject(
                self.job, 3, C.byref(info), C.sizeof(info), C.byref(used))
            if not ok and C.get_last_error() == 234:
                capacity = max(capacity * 2, info.assigned)
                continue
            self._check(ok, 'QueryInformationJobObject members')
            if info.count > capacity or info.count < info.assigned:
                raise OSError('incomplete job process list')
            for pid in info.pids[:info.count]:
                if pid == self.pid:
                    handles.append((pid, self.process))
                    continue
                handle = self.api.OpenProcess(0x00100000 | 0x1000, False, pid)
                self._check(handle, 'OpenProcess job member')
                # Record immediately so even membership-call failure closes it.
                handles.append((pid, handle))
                belongs = C.c_int32()
                self._check(self.api.IsProcessInJob(handle, self.job, C.byref(belongs)),
                            'IsProcessInJob')
                if not belongs.value:
                    raise OSError('job member identity changed')
            return
        raise OSError('job member acquisition allowance exceeded')

    def cleanup(self):
        if self.closed:
            return self.killed_pids
        errors, members = [], []
        deadline = time.monotonic() + 3

        def attempt(fn, *args):
            try:
                return fn(*args)
            except BaseException as error:
                errors.append(str(error))
                return None

        def boolean(name, *args):
            return self._check(getattr(self.api, name)(*args), name)

        def retry(name, *args):
            for _ in range(2):
                if attempt(boolean, name, *args):
                    return True
            return False

        # Every stage runs even if an earlier stage raises. Assignment failure
        # leaves a suspended root outside the job: terminate its retained handle.
        try:
            if self.job:
                active = attempt(self._active)
                if active != 0:
                    attempt(self._retain_members, members, deadline)
                    self.killed_pids = [pid for pid, _ in members]
                    retry('TerminateJobObject', self.job, 1)
                while active != 0 and time.monotonic() < deadline:
                    active = attempt(self._active)
                    if active != 0:
                        time.sleep(.02)
                if active != 0:
                    errors.append('job cleanup not verified')
            if self.process:
                state = attempt(self._wait, self.process, 0)
                if state != 0:
                    if not self.assigned:
                        retry('TerminateProcess', self.process, 1)
                    state = attempt(self._wait, self.process,
                                    max(0, int((deadline - time.monotonic()) * 1000)))
                if state != 0:
                    errors.append('root cleanup not verified')
                else:
                    # Avoid poll: cleanup must work even when poll itself raised.
                    code = C.c_uint32()
                    if attempt(boolean, 'GetExitCodeProcess', self.process, C.byref(code)):
                        self.returncode = code.value
            for _, handle in members:
                state = attempt(self._wait, handle,
                                max(0, int((deadline - time.monotonic()) * 1000)))
                if state != 0:
                    errors.append('job member cleanup not verified')
        finally:
            if self.stdin:
                attempt(self.stdin.close)
            for _, handle in members:
                if handle != self.process:
                    retry('CloseHandle', handle)
            for handle in (self.thread, self.process, self.job):
                if handle:
                    retry('CloseHandle', handle)
            self.closed = True
        self.cleanup_verified = not errors
        if errors:
            raise RuntimeError('native custody cleanup failed: ' + '; '.join(errors))
        return self.killed_pids


def _launch_owned(cmd, cwd, out, err):
    if sys.platform == 'win32':
        return _WindowsProcess(cmd, cwd, out, err)
    return subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=out, stderr=err, cwd=str(cwd))

def is_output_item(item):
    """Exclude only known configuration warnings and empty agent messages."""
    if item.get("type") == "agent_message":
        return bool(item.get("text", "").strip())
    if item.get("type") == "error":
        first_line = item.get("message", "").split("\n", 1)[0]
        if re.fullmatch(r"Codex is ignoring \d+ unrecognized configuration settings\. "
                        r"Check for typos or deprecated settings\.", first_line):
            return False
    return True

def run_codex(a, worktree: Path, logdir: Path, attempt: int):
    native = logdir / f"native.{attempt}.jsonl"
    stderr = logdir / f"stderr.{attempt}.log"
    cmd = [a.codex, "exec", "--skip-git-repo-check",
           "--model", a.model,
           "--config", f'model_reasoning_effort="{a.effort}"',
           "--config", 'approval_policy="never"',
           "--sandbox", "workspace-write",
           "--cd", str(worktree),
           "--json", "-"]
    prompt = Path(a.prompt_file).read_text(encoding="utf-8")
    prompt += ("\n\n--- RUNNER CONTRACT ---\n"
               "You are in a git worktree that is yours. Edit files directly, run tests, "
               "and keep going until the job's check passes. Do not ask questions; pick the "
               "simplest reading and note it in DECISIONS.md. Smart Stop Rules and action "
               "budgets do not apply to this job; the runner owns the clock. When done, write "
               "JOB.md with three lines: Done / Next / Blocked.\n")
    started = time.time()
    with open(native, "wb") as out, open(stderr, "wb") as err:
        proc = _launch_owned(cmd, worktree, out, err)
        try:
            proc.stdin.write(prompt.encode("utf-8")); proc.stdin.close()
            last_size = 0; last_change = time.time(); reason = "done"
            while proc.poll() is None:
                time.sleep(5)
                size = native.stat().st_size if native.exists() else 0
                if size != last_size:
                    last_size, last_change = size, time.time()
                # A root exiting during the sleep has a natural exit outcome.
                if proc.poll() is not None:
                    break
                if time.time() - last_change > a.idle:
                    reason = "idle-timeout"; break
                if time.time() - started > a.wall:
                    reason = "wall-timeout"; break
        finally:
            if isinstance(proc, _WindowsProcess):
                killed = proc.cleanup()
            else:
                killed = kill_tree(proc)
                proc.wait()
                proc.stdin.close()
        if reason == "done" and proc.returncode != 0:
            reason = "codex-error"
    items = output_items = tool_events = 0; usage = None; final_msg = ""
    if native.exists():
        for line in native.read_text(encoding="utf-8", errors="replace").splitlines():
            try: o = json.loads(line)
            except ValueError: continue
            if o.get("type") == "item.completed":
                items += 1
                item = o.get("item", {})
                if is_output_item(item): output_items += 1
                t = item.get("type", "")
                if t in ("command_execution", "file_change", "mcp_tool_call"): tool_events += 1
                if t == "agent_message": final_msg = o["item"].get("text", "")
            if o.get("type") == "turn.completed": usage = o.get("usage")
    return {"attempt": attempt, "reason": reason, "returncode": proc.returncode,
            "seconds": round(time.time() - started, 1), "items": items,
            "output_items": output_items,
            "tool_events": tool_events, "usage": usage, "killed_pids": killed,
            "final_message": final_msg[:2000], "native_log": str(native)}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--job", required=True)
    ap.add_argument("--prompt-file", required=True)
    ap.add_argument("--wall", type=int, default=4*3600)
    ap.add_argument("--idle", type=int, default=600)
    ap.add_argument("--model", default="gpt-6.1-sol")
    ap.add_argument("--effort", default="high")
    ap.add_argument("--codex", default="codex")
    a = ap.parse_args()
    if os.sep in a.codex or "/" in a.codex:
        a.codex = str(Path(a.codex).resolve())

    repo = Path(a.repo).resolve()
    branch = f"job/{a.job}"
    worktree = repo.parent / f"{repo.name}-wt" / a.job
    logdir = repo / ".runner" / a.job
    logdir.mkdir(parents=True, exist_ok=True)
    log = logdir / "RUN.json"

    sh(["git", "-C", str(repo), "rev-parse", "HEAD"])  # repo must have a commit
    if not worktree.exists():
        worktree.parent.mkdir(parents=True, exist_ok=True)
        if sh(["git", "-C", str(repo), "rev-parse", "--verify", branch], check=False).returncode == 0:
            sh(["git", "-C", str(repo), "worktree", "add", str(worktree), branch])
        else:
            sh(["git", "-C", str(repo), "worktree", "add", "-b", branch, str(worktree)])

    record = {"job": a.job, "branch": branch, "worktree": str(worktree),
              "started": now(), "attempts": []}
    result = None
    for attempt in (1, 2):
        result = run_codex(a, worktree, logdir, attempt)
        record["attempts"].append(result)
        log.write_text(json.dumps(record, indent=1), encoding="utf-8")
        zero_output = result["output_items"] == 0 and result["tool_events"] == 0
        if not zero_output:
            break
        print(f"[runner] attempt {attempt} produced zero output ({result['reason']}); "
              + ("retrying once" if attempt == 1 else "giving up"))

    # Always commit whatever is there, even on timeout: WIP is better than nothing.
    sh(["git", "-C", str(worktree), "add", "-A"])
    if sh(["git", "-C", str(worktree), "diff", "--cached", "--quiet"], check=False).returncode != 0:
        msg = f"job({a.job}): {result['reason']} after {result['seconds']}s"
        sh(["git", "-C", str(worktree), "commit", "-q", "-m", msg])
        record["commit"] = sh(["git", "-C", str(worktree), "rev-parse", "HEAD"]).stdout.strip()
    jobmd = worktree / "JOB.md"
    record["job_md"] = jobmd.read_text(encoding="utf-8") if jobmd.exists() else None
    record["ended"] = now()
    log.write_text(json.dumps(record, indent=1), encoding="utf-8")
    print(json.dumps({k: record[k] for k in ("job", "branch", "commit", "ended") if k in record}, indent=1))
    print(result["reason"], f"{result['seconds']}s", f"tools={result['tool_events']}")

    if zero_output: sys.exit(5)
    sys.exit({"done": 0, "idle-timeout": 2, "wall-timeout": 3}.get(result["reason"], 4))

if __name__ == "__main__":
    main()
