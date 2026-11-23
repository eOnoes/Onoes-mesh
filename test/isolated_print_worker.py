"""Opt-in Docker fixture for the synthetic Workroom-to-Mind print assignment."""
import json
import re
import subprocess
from uuid import uuid4


PROGRAM = r"""
const fs = require('node:fs');
const assert = require('node:assert/strict');
const brief = JSON.parse(fs.readFileSync(0, 'utf8'));
assert.deepEqual(Object.keys(brief).sort(), ['project', 'revision', 'source', 'spec']);
assert.equal(process.getuid(), 65534);
assert.equal(process.getgid(), 65534);
const spec = /^Tray width (\d+) mm ±([\d.]+) mm\. CAD ([\w.-]+)$/.exec(brief.spec);
assert.ok(spec);
const width = Number(spec[1]), tolerance = Number(spec[2]);
process.stdout.write(JSON.stringify({project:brief.project, revision:brief.revision, source:brief.source,
    cad:spec[3], minMm:width-tolerance, maxMm:width+tolerance}));
"""


def check_assignment(image, brief):
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", image):
        raise ValueError("Select a local image by immutable digest")
    context = "desktop-linux"
    def docker(*args, stdin=None):
        run = subprocess.run(["docker", "--context", context, *args], input=stdin, encoding="utf-8",
                             capture_output=True, timeout=30, check=True)
        return run.stdout.strip()

    endpoint, = json.loads(docker("context", "inspect", context))
    assert endpoint["Endpoints"]["docker"]["Host"] == "npipe:////./pipe/dockerDesktopLinuxEngine"
    metadata, = json.loads(docker("image", "inspect", image))
    assert metadata["Id"] == image and metadata["Os"] == "linux" and not metadata["Config"].get("Volumes")
    label = "mesh.test.print-worker=" + uuid4().hex
    container = docker("create", "--pull=never", "--interactive", "--network=none", "--read-only",
                       "--user=65534:65534", "--cap-drop=ALL", "--security-opt=no-new-privileges",
                       "--pids-limit=32", "--memory=128m", "--cpus=0.5", "--label", label,
                       "--entrypoint=node", image, "-e", PROGRAM)
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
        output = docker("start", "--attach", "--interactive", container, stdin=json.dumps(brief))
        state = json.loads(docker("inspect", "--format", "{{json .State}}", container))
        assert state["Status"] == "exited" and state["ExitCode"] == 0
        return json.loads(output)
    finally:
        docker("rm", "--force", container)
