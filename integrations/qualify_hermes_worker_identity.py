"""Observe ordinary Hermes delegation on Windows using disposable profiles and a local marker."""
import ctypes
from ctypes import wintypes
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading


def process_token_in_use():
    """A Windows thread with ERROR_NO_TOKEN uses its process security token."""
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    security = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel.GetCurrentThread.restype = wintypes.HANDLE
    security.OpenThreadToken.argtypes = (wintypes.HANDLE, wintypes.DWORD, wintypes.BOOL,
                                        ctypes.POINTER(wintypes.HANDLE))
    token = wintypes.HANDLE()
    if security.OpenThreadToken(kernel.GetCurrentThread(), 0x0008, True, ctypes.byref(token)):
        kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
        kernel.CloseHandle(token)
        return False
    error = ctypes.get_last_error()
    if error != 1008:
        raise ctypes.WinError(error)
    return True


def observe(source):
    # Import only after redirecting profile and user paths in the parent.
    root = Path.cwd()
    assert Path(os.environ["HERMES_HOME"]) == root / "parent"
    def local_only(event, _args):
        if event in ("socket.connect", "socket.getaddrinfo"):
            raise RuntimeError("The marker fixture does not need network access")
    sys.addaudithook(local_only)
    sys.path.insert(0, str(source))
    from hermes_constants import get_hermes_home
    from tools import daemon_pool, delegate_tool, delegate_tool_child_run, delegate_tool_routes

    module_hashes = {}
    for module in (daemon_pool, delegate_tool, delegate_tool_child_run, delegate_tool_routes):
        path = Path(module.__file__).resolve()
        relative = Path(*module.__name__.split(".")).with_suffix(".py")
        assert path == source / relative
        module_hashes[relative.as_posix()] = sha256(path.read_bytes()).hexdigest()
    assert get_hermes_home().resolve() == root / "parent"
    parent_thread = threading.get_native_id()
    parent_pid = os.getpid()
    assert process_token_in_use()
    results = {}
    for routed in (False, True):
        class Marker:
            def run_conversation(self, **kwargs):
                marker = dict(
                    pid=os.getpid(),
                    thread=threading.get_native_id(),
                    processToken=process_token_in_use(),
                    selectedProfile=get_hermes_home().resolve().name,
                )
                return dict(completed=True, final_response=json.dumps(marker))

        child = Marker()
        if routed:
            child._delegate_profile_home = root / "worker"
        result = delegate_tool._run_single_child(0, "Local marker", child=child)
        assert result.get("status") == "completed", result.get("error") or result.get("status")
        observed = json.loads(result["summary"])
        observed["sameProcess"] = observed.pop("pid") == parent_pid
        observed["differentThread"] = observed.pop("thread") != parent_thread
        assert observed["selectedProfile"] == ("worker" if routed else "parent")
        assert get_hermes_home().resolve() == root / "parent"
        results["routed" if routed else "ordinary"] = observed
    print("RESULT " + json.dumps(dict(moduleHashes=module_hashes, observations=results)))


def qualify(interpreter, source):
    with tempfile.TemporaryDirectory(prefix="mesh-delegation-") as name:
        root = Path(name).resolve()
        env = {key: os.environ[key] for key in ("SystemRoot", "WINDIR", "COMSPEC", "PATHEXT", "SYSTEMDRIVE")
               if key in os.environ}
        for key, directory in {"HERMES_HOME":"parent", "HOME":"home", "USERPROFILE":"home",
                               "APPDATA":"roaming", "LOCALAPPDATA":"local", "TEMP":"tmp", "TMP":"tmp"}.items():
            folder = root / directory
            folder.mkdir(exist_ok=True)
            env[key] = str(folder)
        (root / "worker").mkdir()
        env["PATH"] = os.pathsep.join((str(interpreter.parent), str(Path(env["SystemRoot"]) / "System32")))
        proc = subprocess.run([str(interpreter), "-IB", str(Path(__file__).resolve()), "--observe", str(source)],
                              cwd=root, env=env, capture_output=True, text=True, errors="replace",
                              creationflags=subprocess.CREATE_NO_WINDOW, timeout=90)
        if proc.returncode:
            raise RuntimeError(proc.stderr[-2200:])
        line, = [line for line in proc.stdout.splitlines() if line.startswith("RESULT ")]
        return json.loads(line.removeprefix("RESULT "))


if __name__ == "__main__":
    if os.name != "nt" or len(sys.argv) != 3:
        raise SystemExit("Usage on Windows: qualify_hermes_worker_identity.py HERMES_PYTHON HERMES_SOURCE")
    source = Path(sys.argv[2]).resolve(strict=True)
    if sys.argv[1] == "--observe":
        observe(source)
    else:
        print(json.dumps(qualify(Path(sys.argv[1]).resolve(strict=True), source), indent=2))
