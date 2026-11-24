"""Exercise installed Hermes discovery and calls against Mind's Windows reader."""
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys


def call_reader(tool_name):
    from hermes_constants import get_hermes_home
    from model_tools import handle_function_call
    from tools.mcp_tool_discovery import discover_mcp_tools
    from tools.mcp_tool_lifecycle import shutdown_mcp_servers

    assert get_hermes_home().resolve() == Path.cwd() / "profile"
    try:
        registered = discover_mcp_tools(allowed_mcp_names=["mind"])
        name = f"mcp__mind__{tool_name}"
        assert registered == [name], registered
        envelope = json.loads(handle_function_call(name, {"query": "tray drawing"}, enabled_tools=[name]))
        print("PROJECT-RESULT " + envelope["result"])
    finally:
        shutdown_mcp_servers()


if __name__ == "__main__":
    call_reader(sys.argv[1])
else:
    import pytest
    from onoes_mind.agent_context import AgentContextBinding
    from onoes_mind.context_enrollment import enroll_context_reader
    from onoes_mind.context_host import WindowsReaderCustody
    from onoes_mind.project_tool_grant import ReviewedProjectToolGrant, TOOL_NAME
    from test_agent_context import context_store
    from test_enrollment_store import _CREATE


def test_echo_reads_same_project_through_both_host_profiles(context_store, tmp_path):
    import yaml

    interpreter = os.environ.get("MESH_TEST_HERMES_PYTHON")
    if os.name != "nt" or not interpreter:
        pytest.skip("Requires installed Windows Hermes and the canonical Mind test fixtures")
    ledger, store, _, remember = context_store
    remember("print-brief", "Tray drawing version three")
    remember("other-drawing", "Tray drawing from another project", project="fixture-two")
    remember("private-drawing", "Tray drawing private note", private=True)
    private = tmp_path / "owner"
    private.mkdir()
    acl = tmp_path / "fixture-permissions.ps1"
    acl.write_text(_CREATE)
    subprocess.run([shutil.which("pwsh") or shutil.which("powershell"), "-NoProfile",
                    "-NonInteractive", "-File", str(acl), "-Path", str(private)],
                   check=True, capture_output=True, timeout=30)
    binding = AgentContextBinding(store, "context-echo-trial", "fixture-one")
    custody = WindowsReaderCustody(private, binding)
    enroll_context_reader(ledger, binding, operator_token="synthetic-operator",
                          save_new_token=custody.save_new)
    grant = ReviewedProjectToolGrant(private / "active-tool-grant.json", binding, "test:echo-reader")
    grant.path.write_bytes(grant.document())
    import onoes_mind
    mind_source = Path(onoes_mind.__file__).resolve().parents[1]
    results = []
    for channel in ("relay", "telegram"):
        host = private / f"{channel}.json"
        host.write_text(json.dumps({"schema": "onoes-mind/project-host/v1",
                                    "binding": asdict(binding), "channel": channel,
                                    "tool_review_ref": "test:echo-reader"}), encoding="utf-8")
        pin = hashlib.sha256(host.read_bytes()).hexdigest()
        root = tmp_path / channel
        env = {k: os.environ[k] for k in ("SystemRoot", "WINDIR", "COMSPEC", "PATHEXT",
                                          "SYSTEMDRIVE", "PATH") if k in os.environ}
        for key, folder in {"HERMES_HOME": "profile", "HOME": "home", "USERPROFILE": "home",
                            "APPDATA": "roaming", "LOCALAPPDATA": "local",
                            "TEMP": "tmp", "TMP": "tmp"}.items():
            directory = root / folder
            directory.mkdir(parents=True, exist_ok=True)
            env[key] = str(directory)
        config = {"mcp_servers": {"mind": {"command": sys.executable, "lazy": False,
                  "args": ["-B", "-m", "onoes_mind.context_host", "--profile", str(host),
                           "--profile-sha256", pin], "env": {"PYTHONPATH": str(mind_source)}}}}
        (root / "profile" / "config.yaml").write_text(yaml.safe_dump(config), encoding="utf-8")
        client = subprocess.run([interpreter, "-IB", str(Path(__file__).resolve()), TOOL_NAME],
                                cwd=root, env=env, capture_output=True, encoding="utf-8",
                                errors="replace", timeout=120, creationflags=subprocess.CREATE_NO_WINDOW)
        assert client.returncode == 0, client.stderr[-2400:]
        line, = [s for s in client.stdout.splitlines() if s.startswith("PROJECT-RESULT ")]
        response = json.loads(line.removeprefix("PROJECT-RESULT "))
        assert response["reader_principal"] == binding.principal_id
        record, = response["records"]
        assert record["claim"] == "Tray drawing version three"
        assert record["project_id"] == "fixture-one"
        results.append((response["snapshot_id"], record))
    assert results[0] == results[1]
