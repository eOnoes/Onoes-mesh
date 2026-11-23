"""Observe the installed Windows assignment launcher using a disposable parent-owned file."""
import argparse
import hashlib
import inspect
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from uuid import uuid4


CHILD = """
import hashlib, json, os, subprocess, sys
from pathlib import Path
print(json.dumps({
    "pid": os.getpid(),
    "markerHash": hashlib.sha256(Path(sys.argv[1]).read_bytes()).hexdigest(),
    "account": subprocess.check_output([sys.argv[2], "/user", "/fo", "csv", "/nh"]).hex(),
}))
"""


def observe(checkout):
    if os.name != "nt":
        raise RuntimeError("This check exercises the Windows assignment launcher")
    sys.path.insert(0, str(checkout))
    from gateway.mesh_assignment_process import AssignmentProcessScope

    assignment = SimpleNamespace(session_id="synthetic-file-access")
    authority = SimpleNamespace(profile_id="synthetic-profile", epoch="synthetic-epoch")
    row = dict(admission_id=uuid4().hex, generation=1, principal_id="synthetic-worker")
    scope = AssignmentProcessScope(authority, assignment, row)
    try:
        module_hashes = {}
        for component in (AssignmentProcessScope, type(scope.fence)):
            source = Path(inspect.getfile(component)).resolve()
            if source.parent != checkout / "gateway":
                raise RuntimeError("Launcher component came from another checkout")
            module_hashes[source.name] = hashlib.sha256(source.read_bytes()).hexdigest()
        with TemporaryDirectory() as parent, TemporaryDirectory() as work:
            marker = Path(parent) / "synthetic-marker"
            marker.write_bytes(secrets.token_bytes(32))
            expected = hashlib.sha256(marker.read_bytes()).hexdigest()
            whoami = str(Path(os.environ["SystemRoot"]) / "System32" / "whoami.exe")
            parent_account = subprocess.check_output([whoami, "/user", "/fo", "csv", "/nh"]).hex()
            # The Windows venv shim spawns a grandchild. Launch its Python binary directly.
            child = scope.popen([sys._base_executable, "-I", "-B", "-c", CHILD, str(marker), whoami],
                                cwd=work, env={"SystemRoot": os.environ["SystemRoot"]})
            output, _ = child.communicate(timeout=15)
            if child.returncode:
                raise RuntimeError(f"Marker observation failed with exit code {child.returncode}")
            result = json.loads(output)
            if result["pid"] != child.pid or child.pid == os.getpid() or result["markerHash"] != expected:
                raise RuntimeError("Child identity or marker digest did not match")
            return {"sourceSha256": module_hashes, "separateChild": True,
                    "sameWindowsAccount": result["account"] == parent_account,
                    "readParentCreatedMarkerOutsideWorkFolder": True}
    finally:
        scope.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("checkout", type=Path)
    args = parser.parse_args()
    print(json.dumps(observe(args.checkout.resolve()), indent=2))
