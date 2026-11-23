"""Windows qualification for Echo's installed Hermes client and the Mind project reader."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from dataclasses import asdict


def run_registry_check(directory, python, mind, profile, pin):
    """Run inside an isolated Hermes interpreter with a synthetic profile."""
    import yaml

    home = Path(os.environ["HERMES_HOME"])
    assert home.resolve() == directory / "hermes"
    assert profile.resolve() == directory / "owner" / "reader.json"
    server = {
        "command": python,
        "args": ["-B", "-m", "onoes_mind.context_host", "--profile", str(profile),
                 "--profile-sha256", pin],
        "env": {"PYTHONPATH": mind, "PYTHONDONTWRITEBYTECODE": "1"},
        "lazy": False,
    }
    with (home / "config.yaml").open("x", encoding="utf-8") as config:
        yaml.safe_dump({"mcp_servers": {"pilot": server}}, config)
    from tools.mcp_tool_discovery import discover_mcp_tools
    from tools.mcp_tool_lifecycle import shutdown_mcp_servers
    from tools.registry import registry

    registered = discover_mcp_tools(allowed_mcp_names=["pilot"])
    try:
        registry_path = Path(sys.modules["tools.registry"].__file__).resolve()
        print("MESH_RESULT", json.dumps({"registered": registered, "registry": str(registry_path)}), flush=True)
        for line in sys.stdin:
            request = json.loads(line)
            tool = next(name for name in registered if name.endswith("_" + request["name"]))
            print("MESH_RESULT", json.dumps({"reply": registry.dispatch(tool, request["arguments"])}), flush=True)
    finally:
        shutdown_mcp_servers()


def payload(value):
    """Unwrap the Hermes and MCP text envelopes to find the actual Mind response."""
    if isinstance(value, str):
        try:
            return payload(json.loads(value))
        except ValueError:
            return None
    if isinstance(value, dict):
        if isinstance(value.get("records"), list) or ("content_role" in value and "record" in value):
            return value
        children = value.values()
    elif isinstance(value, list):
        children = value
    else:
        return None
    for child in children:
        found = payload(child)
        if found is not None:
            return found
    return None


if __name__ == "__main__":
    run_registry_check(Path(sys.argv[1]), sys.argv[2], sys.argv[3], Path(sys.argv[4]), sys.argv[5])
else:
    from test_agent_context import context_store
    from test_enrollment_store import _CREATE
    from onoes_mind.agent_context import AgentContextBinding
    from onoes_mind.context_enrollment import enroll_context_reader
    from onoes_mind.context_host import WindowsReaderCustody
    from onoes_mind.project_tool_grant import ReviewedProjectToolGrant, SKILL_TOOL_NAME, TOOL_NAME
    from onoes_mind.shared_skill import reviewed_skill_envelope


def test_echo_uses_current_guide_and_keeps_search_after_withdrawal(context_store, tmp_path):
    import queue
    from threading import Thread

    hermes = Path(os.environ["MESH_TEST_HERMES_PYTHON"]).resolve(strict=True)
    import onoes_mind.context_host as host
    mind = Path(host.__file__).resolve().parents[1]
    writer, store, _, remember = context_store
    project = "fixture-one"
    spec = remember("shell", "Printable armor spec revision two", project)["record_id"]
    source = "project:frame/fit-guide"
    current_guide = b"Keep the black frame installed while swapping the removable shell."
    guide = tmp_path / "fit-guide.txt"
    guide.write_bytes(current_guide)
    digest = hashlib.sha256(guide.read_bytes()).hexdigest()
    record = writer.remember("synthetic-operator", reviewed_skill_envelope(
        event_id="frame-guide", project_id=project, title="Panel fit check", source_ref=source,
        review_ref="review:frame-guide", document=guide.read_bytes(), approved_sha256=digest))
    binding = AgentContextBinding(store, "context-trial", project)
    owner = tmp_path / "owner"
    owner.mkdir()
    script = tmp_path / "fixture-permissions.ps1"
    script.write_text(_CREATE)
    subprocess.run([shutil.which("pwsh") or "powershell", "-NoProfile", "-NonInteractive",
                    "-File", str(script), "-Path", str(owner)], check=True, capture_output=True,
                   timeout=20, creationflags=subprocess.CREATE_NO_WINDOW)
    custody = WindowsReaderCustody(owner, binding)
    enroll_context_reader(writer, binding, operator_token="synthetic-operator", save_new_token=custody.save_new)
    profile = owner / "reader.json"
    profile.write_text(json.dumps({"schema": "onoes-mind/project-host/v1", "binding": asdict(binding),
                                   "channel": "relay", "tool_review_ref": "review:search",
                                   "skill_review_ref": "review:guide"}), encoding="utf-8")
    for filename, name, review in [("active-tool-grant.json", TOOL_NAME, "search"),
                                   ("active-skill-grant.json", SKILL_TOOL_NAME, "guide")]:
        grant = ReviewedProjectToolGrant(owner / filename, binding, "review:" + review, name)
        grant.path.write_bytes(grant.document())

    env = {k: os.environ[k] for k in ("SystemRoot", "WINDIR", "COMSPEC", "SYSTEMDRIVE", "PATHEXT") if k in os.environ}
    shell = Path(shutil.which("pwsh") or shutil.which("powershell")).resolve(strict=True)
    env["PATH"] = os.pathsep.join([str(shell.parent), str(Path(sys.executable).parent),
                                  str(Path(env["SystemRoot"]) / "System32")])
    for key, name in [("HOME","home"), ("USERPROFILE","home"), ("HERMES_HOME","hermes"),
                      ("LOCALAPPDATA","local"), ("APPDATA","roaming"), ("TMP","tmp"), ("TEMP","tmp")]:
        directory = tmp_path / name
        directory.mkdir(exist_ok=True)
        env[key] = str(directory)
    args = [str(hermes), "-I", str(Path(__file__).resolve()), str(tmp_path), sys.executable,
            str(mind), str(profile), hashlib.sha256(profile.read_bytes()).hexdigest()]
    responses = queue.Queue()
    with (tmp_path / "client.log").open("w") as log, subprocess.Popen(
        args, env=env, cwd=tmp_path, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=log, text=True, encoding="utf-8", creationflags=subprocess.CREATE_NO_WINDOW,
    ) as client:
        def listen():
            for line in client.stdout:
                if line.startswith("MESH_RESULT "):
                    responses.put(json.loads(line.removeprefix("MESH_RESULT ")))
            responses.put(None)
        listener = Thread(target=listen, daemon=True)
        listener.start()

        def receive():
            value = responses.get(timeout=45)
            assert value is not None, "Hermes closed before returning its response"
            return value

        def ask(name, arguments):
            client.stdin.write(json.dumps({"name": name, "arguments": arguments}) + "\n")
            client.stdin.flush()
            return receive()["reply"]

        def verify():
            return ask(SKILL_TOOL_NAME, {"source_ref": source, "sha256": hashlib.sha256(guide.read_bytes()).hexdigest()})

        try:
            discovery = receive()
            assert Path(discovery["registry"]) == hermes.parents[2] / "workspace/tools/registry.py"
            tools = discovery["registered"]
            assert len(tools) == 2
            for name in (TOOL_NAME, SKILL_TOOL_NAME):
                assert any(tool.endswith("_" + name) for tool in tools)
            answer = payload(verify())
            assert answer["content_role"] == "reference_data"
            assert answer["record"]["record_id"] == record["record_id"]
            assert "review:frame-guide" in str(answer["record"])
            guide.write_bytes(b"An outdated copy of the panel guide.")
            stale = verify()
            assert payload(stale) is None and record["record_id"] not in str(stale)
            assert "Project context unavailable" in str(stale)
            guide.write_bytes(current_guide)
            (owner / "active-skill-grant.json").rename(owner / "withdrawn-skill-grant.json")
            denied = verify()
            assert payload(denied) is None and "Tool unavailable for this binding" in str(denied)
            result = payload(ask(TOOL_NAME, {"query": "Printable armor spec"}))
            assert [r["record_id"] for r in result["records"]] == [spec]
        finally:
            client.stdin.close()
            try:
                client.wait(timeout=25)
            except subprocess.TimeoutExpired:
                client.kill()
                client.wait()
                raise
            listener.join(timeout=3)
        assert client.returncode == 0
