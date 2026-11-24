"""Check Hermes worker tool visibility with disposable profiles and two harmless MCP tools.

Run on Windows with: python qualify_hermes_reader_delegation.py PATH_TO_HERMES_PYTHON [HERMES_SOURCE]
The check starts local standard-I/O tool servers. It never opens a model session.
"""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace


SCRIPT = Path(__file__).resolve()
READER = "print_reader"
UTILITY = "worker_utility"


def serve():
    from mcp.server.mcpserver import MCPServer

    server = MCPServer("fixture")

    @server.tool()
    def marker() -> str:
        """Return a constant test marker."""
        return "sample"

    server.run(transport="stdio")


def check_platform_selection(config, reader_server):
    from hermes_cli.tools_config import _get_platform_tools

    chat_platforms = ("api_server", "telegram")
    platforms = (*chat_platforms, "cli", "discord")
    before = {platform: _get_platform_tools(config, platform) for platform in platforms}
    # Simulate adding a reader to an existing gateway that has an ordinary MCP server.
    after = {**config, "mcp_servers": {**config["mcp_servers"], READER: reader_server}}
    default_visibility = {
        platform: READER in _get_platform_tools(after, platform) for platform in platforms
    }
    assert all(default_visibility.values()), default_visibility

    selected = {
        "api_server": [UTILITY, READER],
        "telegram": [UTILITY, READER],
        "cli": [UTILITY],
        "discord": ["no_mcp"],
    }
    # Set the same base Hermes toolsets in both comparisons so any drift is
    # attributable to adding the reader.
    baseline = {**config, "platform_toolsets": {
        platform: [name for name in names if name != READER]
        for platform, names in selected.items()
    }}
    constrained = {**after, "platform_toolsets": selected}
    for platform in platforms:
        previous = _get_platform_tools(baseline, platform)
        current = _get_platform_tools(constrained, platform)
        assert current == previous | ({READER} if platform in chat_platforms else set())
        assert (UTILITY in current) == (platform != "discord")
    assert all(UTILITY in toolsets for toolsets in before.values())
    return {
        "defaultReaderPlatforms": [p for p in platforms if default_visibility[p]],
        "selectedReaderPlatforms": list(chat_platforms),
    }


def check(case, source=None):
    import faulthandler
    if source is not None:
        sys.path.insert(0, str(source))
    import yaml
    from hermes_constants import get_hermes_home

    profile = (Path.cwd() / "profile").resolve(strict=True)
    if get_hermes_home().resolve() != profile:
        raise RuntimeError("A disposable Hermes profile is required")
    faulthandler.dump_traceback_later(55)
    names = [UTILITY] if case == "worker-profile" else [READER, UTILITY]
    server = {"command": sys.executable, "args": ["-I", str(SCRIPT), "--serve"], "lazy": False}
    config = {"mcp_servers": {name: server for name in names}}
    if case == "explicit":
        config["delegation"] = {"inherit_mcp_toolsets": False}
    with (profile / "config.yaml").open("x", encoding="utf-8") as output:
        yaml.safe_dump(config, output)

    from tools.mcp_tool_discovery import discover_mcp_tools
    from tools.mcp_tool_lifecycle import shutdown_mcp_servers
    from tools.delegate_tool_toolsets import _resolve_child_toolsets
    from model_tools import get_tool_definitions, get_toolset_for_tool
    if source is not None:
        for name in ("model_tools", "tools.delegate_tool_toolsets", "tools.mcp_tool_discovery"):
            path = Path(sys.modules[name].__file__).resolve()
            assert path == source / Path(*name.split(".")).with_suffix(".py"), name

    def catalog(enabled, disabled):
        schemas = get_tool_definitions(enabled, disabled, quiet_mode=True,
                                       skip_tool_search_assembly=True)
        return {schema["function"]["name"] for schema in schemas}

    try:
        registered = set(discover_mcp_tools(allowed_mcp_names=names))
        reader = f"mcp__{READER}__marker"
        utility = f"mcp__{UTILITY}__marker"
        assert {f"mcp__{name}__marker" for name in names} <= registered, registered
        assert {tool.split("__")[1] for tool in registered} == set(names)
        parent = SimpleNamespace(
            enabled_toolsets=sorted({get_toolset_for_tool(tool) for tool in registered}),
            disabled_toolsets=[],
        )
        parent_tools = catalog(parent.enabled_toolsets, [])
        assert registered <= parent_tools
        assert (reader in parent_tools) == (case != "worker-profile")
        rows = {}
        for label, requested in [("assigned", [get_toolset_for_tool(utility)]), ("unspecified", None)]:
            enabled, disabled = _resolve_child_toolsets(parent, requested, "leaf")
            child_tools = catalog(enabled, disabled)
            assert utility in child_tools, (case, label, "missing worker utility")
            expected = case == "default" or (case == "explicit" and label == "unspecified")
            assert (reader in child_tools) == expected, (case, label, "unexpected reader visibility")
            if not expected:
                assert not any(tool.startswith(f"mcp__{READER}__") for tool in child_tools)
            rows[label] = {"reader": reader in child_tools, "utility": utility in child_tools}
        if case == "worker-profile":
            rows["platformSelection"] = check_platform_selection(config, server)
        print("RESULT " + json.dumps(rows))
    finally:
        shutdown_mcp_servers()
        faulthandler.cancel_dump_traceback_later()


def qualify(interpreter, source=None):
    results = {}
    with tempfile.TemporaryDirectory(prefix="mesh-worker-tools-") as temp:
        for case in ("default", "explicit", "worker-profile"):
            root = Path(temp) / case
            env = {key: os.environ[key] for key in ("SystemRoot", "WINDIR", "COMSPEC",
                                                     "PATHEXT", "SYSTEMDRIVE") if key in os.environ}
            for key, directory in {"HERMES_HOME": "profile", "HOME": "home", "USERPROFILE": "home",
                                   "APPDATA": "roaming", "LOCALAPPDATA": "local",
                                   "TEMP": "tmp", "TMP": "tmp"}.items():
                path = root / directory
                path.mkdir(parents=True, exist_ok=True)
                env[key] = str(path)
            env["PATH"] = os.pathsep.join([str(interpreter.parent), str(Path(env["SystemRoot"]) / "System32")])
            with (root / "diagnostic.log").open("w+", encoding="utf-8") as log:
                try:
                    command = [str(interpreter), "-IB", str(SCRIPT), "--check", case]
                    if source is not None:
                        command.append(str(source))
                    proc = subprocess.run(command,
                                          cwd=root, env=env, stdout=subprocess.PIPE, stderr=log,
                                          text=True, errors="replace", timeout=90,
                                          creationflags=subprocess.CREATE_NO_WINDOW)
                except subprocess.TimeoutExpired:
                    log.seek(0)
                    raise RuntimeError(f"{case} timed out\n{log.read()[-3800:]}") from None
                log.seek(0)
                diagnostics = log.read() if proc.returncode else ""
            if proc.returncode:
                raise RuntimeError(f"{case} failed\n{diagnostics[-2500:]}")
            result, = [line.removeprefix("RESULT ") for line in proc.stdout.splitlines()
                       if line.startswith("RESULT ")]
            results[case] = json.loads(result)
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    if sys.argv[1:] == ["--serve"]:
        serve()
    elif len(sys.argv) in (3, 4) and sys.argv[1] == "--check":
        check(sys.argv[2], Path(sys.argv[3]).resolve(strict=True) if len(sys.argv) == 4 else None)
    elif len(sys.argv) in (2, 3):
        qualify(Path(sys.argv[1]).resolve(strict=True),
                Path(sys.argv[2]).resolve(strict=True) if len(sys.argv) == 3 else None)
    else:
        raise SystemExit(__doc__)
