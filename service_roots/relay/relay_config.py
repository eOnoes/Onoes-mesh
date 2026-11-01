"""Shared configuration helpers for Relay.

Secrets live in files outside the tracked configuration. A live ``config.json``
must never carry a bearer key: use ``api_key_file`` (or ``api_key_env``) instead,
and keep the file under ``.private/`` or outside the source tree entirely.
"""
from __future__ import annotations

import os
from pathlib import Path

# A Hermes API server rejects keys shorter than this; see the handoff notes.
MIN_API_KEY_LENGTH = 16


def resolve_secret(value: str | None, *, root: Path, cfg_dir: Path | None = None) -> str:
    """Return the literal value, or read a file/env secret when the value is a reference.

    Recognised forms:
      ``file:.private/echo.key``   relative to the project root
      ``file:C:/path/to/key``      absolute
      ``env:HERMES_API_KEY``       read from the process environment
      anything else                used literally, with surrounding whitespace stripped

    Raises ``ValueError`` with a human-readable message when a reference is broken.
    """
    if value is None:
        return ""
    raw = str(value).strip()
    if not raw:
        return ""
    lowered = raw.lower()
    if lowered.startswith("file:"):
        target = Path(os.path.expandvars(raw[5:].strip())).expanduser()
        if not target.is_absolute():
            base = cfg_dir or root
            target = base / target
        try:
            secret = target.read_text(encoding="utf-8")
        except OSError as exc:
            raise ValueError(f"cannot read secret file {target}: {exc}") from exc
        # Tolerate a trailing newline and a shell-style quoted value.
        secret = secret.strip()
        if len(secret) >= 2 and secret[0] == secret[-1] and secret[0] in "\"'":
            secret = secret[1:-1]
        if not secret:
            raise ValueError(f"secret file {target} is empty")
        return secret
    if lowered.startswith("env:"):
        name = raw[4:].strip()
        secret = os.environ.get(name, "").strip()
        if not secret:
            raise ValueError(f"environment variable {name} is empty or unset")
        return secret
    return raw


def agent_api_key(cfg: dict, *, root: Path, cfg_dir: Path | None = None) -> str:
    """Resolve one agent's bearer key from api_key_file, api_key_env, or api_key."""
    if cfg.get("api_key_file"):
        return resolve_secret(f"file:{cfg['api_key_file']}", root=root, cfg_dir=cfg_dir)
    if cfg.get("api_key_env"):
        return resolve_secret(f"env:{cfg['api_key_env']}", root=root, cfg_dir=cfg_dir)
    return resolve_secret(cfg.get("api_key"), root=root, cfg_dir=cfg_dir)


def warn_weak_keys(agents: dict, log=print) -> None:
    """Warn (never raise) about authed agents whose key is missing or too short."""
    for aid, agent in agents.items():
        cfg = agent.cfg if hasattr(agent, "cfg") else agent
        if cfg.get("backend") != "hermes":
            continue
        key = getattr(agent, "api_key", "") if hasattr(agent, "api_key") else ""
        if not key:
            log(f"!! {aid}: no API key configured; Hermes requests will be unauthenticated")
        elif len(key) < MIN_API_KEY_LENGTH:
            log(f"!! {aid}: API key is shorter than {MIN_API_KEY_LENGTH} characters")
