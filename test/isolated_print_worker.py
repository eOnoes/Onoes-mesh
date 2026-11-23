"""Opt-in Docker fixture for the synthetic Workroom-to-Mind print assignment."""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from uuid import uuid4


CALCULATOR = r"""
const fs = require('node:fs');
const assert = require('node:assert/strict');
function calculate({brief, taskId, sendId}) {
assert.deepEqual(Object.keys(brief).sort(), ['project', 'revision', 'source', 'spec']);
assert.equal(process.getuid(), 65534);
assert.equal(process.getgid(), 65534);
const spec = /^Tray width (\d+) mm ±([\d.]+) mm\. CAD ([\w.-]+)$/.exec(brief.spec);
assert.ok(spec);
const width = Number(spec[1]), tolerance = Number(spec[2]);
assert.throws(() => fs.readFileSync('/parent-only-marker'), {code:'ENOENT'});
return {schema:'workroom-update/v1', taskId, sendId, goal:brief.spec,
    checklist:[{id:'fit', text:'Calculate the tray width range', status:'done'}],
    result:spec[3]+': '+(width-tolerance)+'–'+(width+tolerance)+' mm',
    evidence:brief.source+' / '+brief.revision};
}
"""
PROGRAM = CALCULATOR + "process.stdout.write(JSON.stringify(calculate(JSON.parse(fs.readFileSync(0,'utf8')))));"


def check_assignment(image, assignment):
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", image):
        raise ValueError("Select a local image by immutable digest")
    context = "desktop-linux"
    def docker(*args, stdin=None):
        run = subprocess.run(["docker", "--context", context, *args], input=stdin, encoding="utf-8",
                             capture_output=True, timeout=30)
        if run.returncode:
            raise RuntimeError(f"Docker {args[0]} failed: {run.stderr.strip()}")
        return run.stdout.strip()

    endpoint, = json.loads(docker("context", "inspect", context))
    assert endpoint["Endpoints"]["docker"]["Host"] == "npipe:////./pipe/dockerDesktopLinuxEngine"
    metadata, = json.loads(docker("image", "inspect", image))
    assert metadata["Id"] == image and metadata["Os"] == "linux" and not metadata["Config"].get("Volumes")
    # Positive control: the same image/user can read our one-use marker when explicitly mounted.
    with TemporaryDirectory(dir=Path.cwd()) as directory:
        marker = Path(directory) / "marker.txt"
        contents = uuid4().hex
        marker.write_text(contents, encoding="ascii")
        readback = docker("run", "--rm", "--pull=never", "--network=none", "--read-only",
                          "--user=65534:65534", "--cap-drop=ALL", "--security-opt=no-new-privileges",
                          "--mount", f"type=bind,source={marker},target=/parent-only-marker,readonly",
                          "--entrypoint=cat", image, "/parent-only-marker")
        assert readback == contents
        return run_unmounted(docker, image, metadata, assignment)


def start_with_windows_launcher(checkout, container, assignment):
    """Exercise the installed Hermes Windows launcher with a synthetic admission."""
    checkout = Path(checkout).resolve(strict=True)
    sys.path.insert(0, str(checkout))
    from gateway.mesh_assignment_process import AssignmentProcessScope

    admission = uuid4().hex
    scope = AssignmentProcessScope(SimpleNamespace(profile_id="fixture", epoch="fixture"),
                                   SimpleNamespace(session_id=assignment["sendId"]),
                                   dict(admission_id=admission, generation=1, principal_id="fixture-worker"))
    try:
        for component in (type(scope), type(scope.fence)):
            module = sys.modules[component.__module__]
            assert Path(module.__file__).resolve().parent == checkout / "gateway"
        executable = shutil.which("docker.exe")
        assert executable
        cmd = [executable, "--context", "desktop-linux", "start", "--attach", "--interactive", container]
        client_env = {key: os.environ[key] for key in ("SystemRoot", "USERPROFILE", "APPDATA",
                      "LOCALAPPDATA", "PATH", "TEMP", "TMP") if key in os.environ}
        with scope.popen(cmd, cwd=str(Path.cwd()), env=client_env, stdin=subprocess.PIPE,
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE) as child:
            try:
                stdout, stderr = child.communicate(json.dumps(assignment).encode("utf-8"), timeout=30)
            except subprocess.TimeoutExpired:
                scope.dispose()
                raise
            if child.returncode:
                raise RuntimeError(f"Scoped container start failed: {stderr.decode('utf-8', 'replace')}")
        observed = scope.retire()
        # Docker's CLI may exit just before Windows reports its last descendant gone.
        deadline = time.monotonic() + 5
        while observed["state"] == "held" and time.monotonic() < deadline:
            time.sleep(0.05)
            observed = scope.observe()
        assert observed["admissionId"] == admission and observed["sessionId"] == assignment["sendId"]
        assert observed["processTreeEnded"] and observed["assignmentLaunchSealed"], observed["state"]
        return stdout.decode("utf-8")
    finally:
        scope.dispose()


def run_unmounted(docker, image, metadata, assignment):
    label = "mesh.test.print-worker=" + uuid4().hex
    delegate_python = os.environ.get("MESH_TEST_DELEGATE_PYTHON")
    checkout = os.environ.get("MESH_TEST_WINDOWS_HERMES_CHECKOUT")
    entry = PROGRAM
    if delegate_python:
        if os.name != "nt" or not checkout:
            raise ValueError("The delegation trial requires Windows and MESH_TEST_WINDOWS_HERMES_CHECKOUT")
        entry = CALCULATOR + Path(__file__).with_name("print-acp-peer.cjs").read_text(encoding="utf-8")
    container = docker("create", "--pull=never", "--interactive", "--network=none", "--read-only",
                       "--user=65534:65534", "--cap-drop=ALL", "--security-opt=no-new-privileges",
                       "--pids-limit=32", "--memory=128m", "--cpus=0.5", "--label", label,
                       "--entrypoint=node", image, "-e", entry)
    assert re.fullmatch("[0-9a-f]{64}", container)
    try:
        actual, = json.loads(docker("inspect", container))
        host, config = actual["HostConfig"], actual["Config"]
        assert actual["Id"] == container and actual["Image"] == image
        assert config["Labels"]["mesh.test.print-worker"] == label.split("=")[1]
        assert host["NetworkMode"] == "none" and host["ReadonlyRootfs"] and not host["Privileged"]
        assert not actual["Mounts"] and not host.get("Devices") and not host.get("CapAdd")
        assert host["CapDrop"] == ["ALL"] and "no-new-privileges" in host["SecurityOpt"]
        assert config["User"] == "65534:65534" and config["Env"] == metadata["Config"]["Env"]
        if delegate_python:
            from hermes_print_delegation import delegate
            output = delegate(delegate_python, checkout, container, assignment)
            assert docker("wait", container) == "0"
        elif checkout:
            output = start_with_windows_launcher(checkout, container, assignment)
        else:
            output = docker("start", "--attach", "--interactive", container, stdin=json.dumps(assignment))
        # The Windows job owns the client process. The daemon owns the container.
        state = json.loads(docker("inspect", "--format", "{{json .State}}", container))
        assert state["Status"] == "exited" and state["ExitCode"] == 0
        return json.loads(output)
    finally:
        docker("rm", "--force", container)


if __name__ == "__main__":
    # The cross-repository test invokes Python in isolated mode.
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    print(json.dumps(check_assignment(os.environ["MESH_TEST_WORKER_IMAGE"], json.load(sys.stdin))))
