"""MCP server inventory and observed state, per agent.

What is actually knowable, per backend:

* **Hermes (local desktop install)** — the configured servers are read from the
  same ``config.yaml`` the gateway uses, so the list is exact. But the *connected*
  flag lives in the gateway process's memory: ``get_mcp_status()`` in Hermes reads
  module-level runtime state and never connects, so calling it from Relay's process
  would report every server as merely "configured" — a comfortable lie. Instead we
  observe the OS: a stdio MCP server is a real child process, so we report whether
  its process is running. That is evidence, not a guess, and it is labelled as such.
* **A2A peers** — the agent card advertises skills, not MCP state. Not observable.
* **OpenClaw** — MCP lives behind his gateway protocol; not exposed to Relay.

Nothing here connects to an MCP server, spawns anything, or reads a secret.
"""
from __future__ import annotations

import json
import re
import subprocess
import time
from pathlib import Path

# Process listing is comparatively expensive (PowerShell + CIM), so cache it.
_PROC_CACHE: dict = {"at": 0.0, "rows": []}
_PROC_TTL = 8.0

_MCP_BLOCK = re.compile(r"^mcp_servers:\s*$(.*?)(?=^\S)", re.M | re.S)
_SERVER_SPLIT = re.compile(r"(?m)^  (?=[A-Za-z0-9_.-]+:\s*$)")


def parse_mcp_servers(text: str) -> list[dict]:
    """Extract configured MCP servers from Hermes' config.yaml text.

    Returns ``[{name, transport, command, script, enabled, has_env}]``. Only the
    fields needed to describe and locate a server are kept, so nothing sensitive
    (env values, tokens, urls with credentials) can leak through this path.
    """
    block = _MCP_BLOCK.search(text or "")
    if not block:
        return []
    servers: list[dict] = []
    for chunk in _SERVER_SPLIT.split(block.group(1)):
        if not chunk.strip():
            continue
        name = chunk.split(":", 1)[0].strip()
        if not name or name.startswith("#"):
            continue
        url = re.search(r"(?m)^\s+url:\s*(\S+)", chunk)
        command = re.search(r"(?m)^\s+command:\s*(.+?)\s*$", chunk)
        script = re.search(r"(?m)^\s+args:\s*\n\s+-\s*(.+?)\s*$", chunk)
        enabled = re.search(r"(?m)^\s+enabled:\s*(\S+)", chunk)
        transport = "http" if url else "stdio"
        enabled_value = True
        if enabled:
            enabled_value = enabled.group(1).strip().strip("\"'").lower() not in ("false", "0", "no", "off")
        script_value = script.group(1).strip().strip("\"'") if script else ""
        command_value = command.group(1).strip().strip("\"'") if command else ""
        servers.append({
            "name": name,
            "transport": transport,
            "command": Path(command_value).name if command_value else "",
            "script": Path(script_value).name if script_value else "",
            "script_dir": Path(script_value).parent.name if script_value else "",
            "enabled": enabled_value,
            "has_env": bool(re.search(r"(?m)^\s+env:\s*$", chunk)),
        })
    return servers


def process_commandlines() -> list[str]:
    """Command lines of running processes (cached briefly). Empty list on failure."""
    now = time.time()
    if now - _PROC_CACHE["at"] < _PROC_TTL and _PROC_CACHE["rows"]:
        return _PROC_CACHE["rows"]
    rows: list[str] = []
    try:
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command",
             "Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | "
             "Select-Object -ExpandProperty CommandLine"],
            capture_output=True, text=True, timeout=12,
            # Relay runs under pythonw.exe, which has no console. Without this flag
            # Windows gives the child PowerShell its own console window, so every MCP
            # panel refresh flashed a command window on screen - most visibly when
            # cycling agent tabs, because each switch re-inventories that agent.
            # relay_openclaw.py already set this; this call was simply missed.
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        rows = [line.strip() for line in (proc.stdout or "").splitlines() if line.strip()]
    except Exception:
        rows = []
    if rows:
        _PROC_CACHE.update({"at": now, "rows": rows})
    return rows


# Script/argument names too common to identify a process on their own.
_GENERIC_STEMS = {"server", "main", "index", "app", "run", "start", "serve", "cli"}


def _match_tokens(server: dict) -> list[str]:
    """Tokens that identify this server's process on the command line.

    Generic names are dropped rather than used: matching on ``serve`` would mark a
    server running because some unrelated process happens to contain that word.
    Callers require *every* returned token to be present.
    """
    tokens: list[str] = []
    stem = Path(server["script"]).stem if server.get("script") else ""
    if stem and stem.lower() not in _GENERIC_STEMS:
        tokens.append(stem)
    elif stem and server.get("script_dir"):
        # …/tripp-telegram-mcp/server.py -> the directory is the identifier
        directory = server["script_dir"]
        if directory.lower() not in _GENERIC_STEMS and len(directory) >= 4:
            tokens.append(directory)
    command = server.get("command", "")
    if command and Path(command).stem.lower() not in (
            "bash", "sh", "cmd", "node", "python", "pythonw", "serve"):
        tokens.append(Path(command).stem)
    tokens = [t for t in tokens if len(t) >= 4 and t.lower() not in _GENERIC_STEMS]
    return tokens or [server["name"]]


def observe(servers: list[dict], commandlines: list[str], *, self_marker: str = "probe_mcp") -> list[dict]:
    """Assemble the report: configured servers plus observed process evidence."""
    report = []
    for server in servers:
        entry = {
            "name": server["name"],
            "transport": server["transport"],
            "enabled": server["enabled"],
            "has_env": server["has_env"],
        }
        if not server["enabled"]:
            entry["status"] = "disabled"
            entry["detail"] = "disabled in config"
        elif server["transport"] == "http":
            entry["status"] = "configured"
            entry["detail"] = "remote endpoint — Relay cannot observe the session"
        else:
            tokens = _match_tokens(server)
            hit = next(
                (line for line in commandlines
                 # EVERY token must appear: one generic word matching is not evidence.
                 if all(t.lower() in line.lower() for t in tokens)
                 and self_marker.lower() not in line.lower()),
                "",
            )
            if hit:
                entry["status"] = "running"
                entry["detail"] = "process observed"
            else:
                entry["status"] = "idle"
                entry["detail"] = "configured, no process running"
        report.append(entry)
    return report


def read_config_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def inventory(config_path: Path, *, commandlines: list[str] | None = None) -> dict:
    """Full MCP report for a local Hermes install."""
    servers = parse_mcp_servers(read_config_text(config_path))
    if not servers:
        return {"ok": True, "supported": True, "observe": "config", "servers": [],
                "note": "no MCP servers configured"}
    rows = process_commandlines() if commandlines is None else commandlines
    return {
        "ok": True,
        "supported": True,
        "observe": "process",
        "servers": observe(servers, rows),
        "note": "“running” = the server's process was observed on this machine; "
                "connection state itself lives inside the agent's gateway process",
    }


def unsupported(backend: str) -> dict:
    """Honest report for backends whose MCP state Relay cannot see."""
    if backend == "a2a":
        reason = ("A2A advertises skills, not MCP server state — an on-host bridge "
                  "would be needed to report it")
    elif backend == "openclaw":
        reason = ("OpenClaw's MCP state is not exposed through the Relay adapter")
    else:
        reason = "MCP state is not exposed by this transport"
    return {"ok": True, "supported": False, "observe": "none", "servers": [],
            "reason": reason}
