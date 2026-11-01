"""Shared-token gate for Relay's own API.

Relay binds loopback and is published to the tailnet through ``tailscale serve``,
so reachability is already limited to your devices. That still leaves two holes:
anything on the tailnet could drive the agents, and a lost or unlocked phone is
enough. This adds one shared secret on top, so the tailnet is no longer the only
lock.

Two ways to present the token:
  * ``Authorization: Bearer <token>``   - scripts and curl
  * a session cookie set by ``POST /unlock`` - the PWA, entered once per device

Only ``/api/*`` is gated. The static shell stays open so the unlock form can load.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import secrets
from pathlib import Path

COOKIE_NAME = "relay_session"
# The cookie carries a digest, never the token itself, so a stolen cookie does not
# hand over a credential that is reused anywhere else.
COOKIE_MAX_AGE = 60 * 60 * 24 * 180  # 180 days


def load_token(root: Path) -> str:
    """Resolve the gate token from RELAY_AUTH_KEY_FILE, else .private/relay.key."""
    configured = os.environ.get("RELAY_AUTH_KEY_FILE", "").strip()
    path = Path(configured) if configured else root / ".private" / "relay.key"
    if not path.is_file():
        return ""
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def generate_token() -> str:
    return secrets.token_urlsafe(32)


def cookie_value(token: str) -> str:
    """The value stored in the session cookie: a digest bound to the token."""
    return hashlib.sha256(("relay-cookie:" + token).encode("utf-8")).hexdigest()


def token_matches(candidate: str, token: str) -> bool:
    if not candidate or not token:
        return False
    return hmac.compare_digest(candidate.strip(), token)


def cookie_matches(candidate: str, token: str) -> bool:
    if not candidate or not token:
        return False
    return hmac.compare_digest(candidate.strip(), cookie_value(token))


def bearer_from_header(header: str) -> str:
    if not header:
        return ""
    parts = header.split(None, 1)
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1].strip()
    return ""


def cookie_from_header(header: str) -> str:
    for chunk in (header or "").split(";"):
        name, _, value = chunk.strip().partition("=")
        if name == COOKIE_NAME:
            return value.strip()
    return ""


def session_cookie(token: str, *, secure: bool) -> str:
    parts = [
        f"{COOKIE_NAME}={cookie_value(token)}",
        "Path=/",
        "HttpOnly",
        "SameSite=Lax",
        f"Max-Age={COOKIE_MAX_AGE}",
    ]
    if secure:
        parts.append("Secure")
    return "; ".join(parts)


def clear_cookie() -> str:
    return f"{COOKIE_NAME}=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0"
