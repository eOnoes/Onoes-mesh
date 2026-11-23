"""Use Hermes' ordinary delegate_task entry with a disposable ACP provider."""
import base64
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory


PROVIDER = "mesh-print-trial"
MODEL = "tinyllama-1.1b-cpu" if os.environ.get("MESH_PRINT_TRIAL_MODEL") == "tinyllama" else "offline-calculator"


def delegate(interpreter, checkout, container, assignment):
    source = Path(checkout).resolve(strict=True)
    docker = Path(shutil.which("docker.exe")).resolve(strict=True)
    with TemporaryDirectory(dir=Path.cwd()) as temp:
        root = Path(temp)
        workspace = root / "print-workspace"
        workspace.mkdir()
        (workspace / "print-trial.txt").write_text("Disposable workspace marker.", encoding="utf-8")
        env = {k: os.environ[k] for k in ("SystemRoot", "WINDIR", "SystemDrive", "COMSPEC", "PATHEXT")
               if k in os.environ}
        for key in ("HERMES_HOME", "HOME", "USERPROFILE", "APPDATA", "LOCALAPPDATA", "TEMP", "TMP"):
            directory = root / key.lower()
            directory.mkdir()
            env[key] = str(directory)
        env.update(PATH=os.pathsep.join([str(docker.parent), str(Path(interpreter).parent),
                                        str(Path(env["SystemRoot"]) / "System32")]), PYTHONUTF8="1")
        model_trial = bool(os.environ.get("MESH_TEST_PRINT_GGUF"))
        if model_trial:
            env["MESH_PRINT_TRIAL_MODEL"] = "tinyllama"
        proc = subprocess.run([interpreter, "-I", "-B", "-X", "utf8", __file__, str(source), str(docker), container],
                              cwd=workspace, env=env, input=json.dumps(assignment), encoding="utf-8",
                              capture_output=True, timeout=125 if model_trial else 55, creationflags=subprocess.CREATE_NO_WINDOW)
        if proc.returncode:
            raise RuntimeError("Disposable delegation failed: " + proc.stderr[-2600:])
        result, = [line[7:] for line in proc.stdout.splitlines() if line.startswith("RESULT ")]
        return result


def run(source, docker, container):
    def offline(event, _args):
        if event in ("socket.connect", "socket.getaddrinfo"):
            raise RuntimeError("This trial has no network provider")
    sys.addaudithook(offline)
    home = Path(os.environ["HERMES_HOME"])
    assert home == Path.cwd().parent / "hermes_home" and Path.cwd().name == "print-workspace"
    sys.path.insert(0, str(source))
    plugin = home / "plugins/model-providers" / PROVIDER
    plugin.mkdir(parents=True)
    shutil.copyfile(Path(__file__).with_name("print_acp_provider.py"), plugin / "__init__.py")
    (plugin / "plugin.yaml").write_text(f"name: {PROVIDER}\nkind: model-provider\nversion: 0.0.1\n"
                                       "description: Disposable offline print calculator\n", encoding="utf-8")
    args = ["--host", "npipe:////./pipe/dockerDesktopLinuxEngine", "start", "--attach", "--interactive", container]
    route = {"provider": PROVIDER, "model": MODEL, "command": docker, "args": args}
    settings = {"model": {"provider": PROVIDER, "default": MODEL},
                "delegation": {**route, "max_iterations": 1, "max_spawn_depth": 1},
                "plugins": {"enabled": [PROVIDER]}}
    (home / "config.yaml").write_text(json.dumps(settings), encoding="utf-8")
    os.environ["MESH_PRINT_TRIAL_COMMAND"] = docker
    os.environ["MESH_PRINT_TRIAL_ARGS"] = " ".join(args)
    from run_agent import AIAgent
    from tools.delegate_tool import delegate_task
    from agent.acp_client import ACPClient
    for obj, relative in ((AIAgent, "run_agent.py"), (delegate_task, "tools/delegate_tool.py"),
                          (ACPClient, "agent/acp_client.py")):
        assert Path(sys.modules[obj.__module__].__file__).resolve() == source / relative
    parent = AIAgent(model=MODEL, provider=PROVIDER,
                     base_url="acp://" + PROVIDER, api_key="fixture", enabled_toolsets=[],
                     quiet_mode=True, max_iterations=1)
    assignment = json.load(sys.stdin)
    encoded = base64.b64encode(json.dumps(assignment).encode("utf-8")).decode("ascii")
    try:
        response = json.loads(delegate_task(goal="Calculate the assigned tray tolerance. Return its JSON result.",
                                            context="PRINT_INPUT[" + encoded + "]", parent_agent=parent))
        if not response.get("results"):
            raise RuntimeError(str(response)[:900])
        worker, = response["results"]
        if worker.get("status") != "completed":
            raise RuntimeError(str(worker)[:1000])
        result = json.loads(worker["summary"])
        assert result["taskId"] == assignment["taskId"] and result["sendId"] == assignment["sendId"]
        print("RESULT " + json.dumps(result))
    finally:
        parent.close()


if __name__ == "__main__":
    run(Path(sys.argv[1]), sys.argv[2], sys.argv[3])
