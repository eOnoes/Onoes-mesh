#!/usr/bin/env python3
"""
relay — one web terminal for all your agents.

A thin proxy that sits in front of your agent gateways (Hermes API server,
OpenClaw gateway) and fans their events out to a single terminal-style PWA.

Run:   python relay_server.py
Open:  http://localhost:8787

Hermes agents use the native Runs API (real streaming, tool progress, stop,
approvals, steer) and Hermes owns the conversation transcript. OpenClaw always
uses its authenticated native adapter. Both require `demo_fallback: false`.
"""
import asyncio
import base64
import binascii
import contextlib
import hashlib
import json
import os
import re
import shutil
import sqlite3
import sys
import time
import uuid
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

import relay_a2a
import relay_auth
import relay_channels
import relay_db
import relay_hermes
import relay_mcp
import relay_notify
import relay_webpush
from relay_a2a import A2AError, A2AClient
from relay_config import agent_api_key, warn_weak_keys
from relay_hermes import HermesError, HermesRunsClient
from relay_openclaw import OpenClawAdapter
from relay_sessions import SessionStore

ROOT = Path(__file__).parent
CONFIG_PATH = Path(os.environ.get("RELAY_CONFIG_PATH", ROOT / "config.json"))
STATIC = ROOT / "static"
SESSION_DB_PATH = Path(os.environ.get("RELAY_SESSION_DB", ROOT / ".private" / "relay.sqlite3"))

config = json.loads(CONFIG_PATH.read_text())
WATCHDOG_SECONDS = config.get("watchdog_seconds", 90)
MAX_ATTACHMENTS = 4
MAX_ATTACHMENT_BYTES = 8 * 1024 * 1024
MAX_TEXT_ATTACHMENT_BYTES = 512 * 1024
MAX_TOTAL_ATTACHMENT_BYTES = 16 * 1024 * 1024
IMAGE_MIME_TYPES = {"image/png", "image/jpeg", "image/webp", "image/gif"}
TEXT_MIME_TYPES = {
    "text/plain", "text/markdown", "text/csv", "text/html", "text/css",
    "text/xml", "application/json", "application/xml",
    "application/javascript", "application/x-javascript",
}
TEXT_EXTENSIONS = {
    ".txt", ".md", ".csv", ".json", ".log", ".py", ".js", ".ts",
    ".tsx", ".jsx", ".html", ".css", ".xml", ".yaml", ".yml", ".ps1",
}
# Grace period for a run's terminal status to appear after its event stream ends.
RUN_SETTLE_TIMEOUT = 15.0


# ---------------------------------------------------------------- state ----
class Agent:
    def __init__(self, aid: str, cfg: dict):
        self.id = aid
        self.cfg = cfg
        self.name = cfg["name"]
        self.backend = cfg["backend"]          # "hermes" | "openclaw" | "a2a"
        self.device = cfg.get("device", "")
        self.url = cfg.get("url", "")
        self.status = "idle"                   # idle|working|stalled|waiting|stopped|done
        self.goal = {"text": cfg.get("goal", ""), "steps": [], "turns": 0,
                     "max_turns": cfg.get("max_turns", 60)}
        self.feed = []                          # [[text, cls, ts], ...] terminal lines
        self.msgs = []                          # [{"k": "you"|"ag", "t": str}]
        self.approval = None                    # {"id": native request id, "cmd": str}
        self.last_activity = time.time()
        self.subs = []                          # asyncio.Queue per SSE subscriber
        self.run_task = None
        self.session_id = None                  # gateway-side session/run id
        self.desktop_session_id = None          # mirrored Hermes Desktop session id
        self.goal_control_task = None           # resumed Desktop goal turn
        self.conversation_id = None             # Relay's durable conversation id
        self.message_queue = deque()            # accepted user messages waiting for Hermes
        self.message_ids = set()                # recent client ids for retry deduplication
        self.message_id_order = deque()
        # Hermes native Runs API state (see relay_hermes.py).
        self.api_key = agent_api_key(cfg, root=ROOT, cfg_dir=CONFIG_PATH.parent)
        self.hermes: HermesRunsClient | None = None
        # A2A transport state (see relay_a2a.py) for peers with no native API.
        self.a2a: A2AClient | None = None
        self.a2a_task_id: str | None = None
        self.capabilities: dict = {}             # last probed gateway capability report
        self.active_run_ids = []                # live native run ids, oldest first
        self.run_events = []                    # native events retained for forensics
        self.run_usage = {}                     # last terminal usage payload
        self._answer_parts = []                 # streamed deltas for the live run
        self._answer_persisted = False          # guard against double-persisting a reply

    @property
    def is_a2a(self) -> bool:
        return self.backend == "a2a"

    @property
    def run_id(self) -> str | None:
        """The native run currently being driven, if any."""
        return self.active_run_ids[0] if self.active_run_ids else None

    def running(self) -> bool:
        """True while Relay is actively driving a run or a Desktop goal continuation."""
        return bool(
            (self.run_task and not self.run_task.done())
            or (self.goal_control_task and not self.goal_control_task.done())
            or self.active_run_ids
            or self.a2a_task_id
        )

    def take_answer(self) -> str:
        """Return the accumulated streamed answer, once."""
        text = "".join(self._answer_parts).strip()
        self._answer_parts = []
        return text

    def snapshot(self):
        return {"id": self.id, "name": self.name, "backend": self.backend,
                "device": self.device, "status": self.status, "goal": self.goal,
                "feed": self.feed[-200:], "msgs": self.msgs[-200:],
                "approval": self.approval, "url": self.url,
                "conversation_id": self.conversation_id,
                "activeRunIds": list(self.active_run_ids),
                "usage": self.run_usage,
                **({"meshTaskLinks": MESH_LINK.references(self.conversation_id),
                    "meshPendingLinks": MESH_LINK.unlinked(self.conversation_id)}
                   if self.backend == "mesh" else {})}


AGENTS = {aid: Agent(aid, cfg) for aid, cfg in config["agents"].items()}
SESSIONS = SessionStore(SESSION_DB_PATH)
if config.get("mesh_only"):
    from mesh_link import MeshLink
    MESH_LINK = MeshLink(SESSIONS)
OPENCLAW_ADAPTERS: dict[str, OpenClawAdapter] = {}
WATCHDOG_TASK: asyncio.Task | None = None
NOTIFICATION_TASK: asyncio.Task | None = None
#: Last pass of the deferred-notification drain, surfaced through health so the loop is
#: observable rather than assumed.
LAST_DRAIN: dict = {"at": None, "due": 0, "delivered": 0}
#: Last digest pass, surfaced through health for the same reason.
LAST_DIGEST: dict = {"checked_at": None, "at": None, "held": 0, "folded": 0,
                     "digests": 0, "last_reason": None}
HERMES_DESKTOP_TASK: asyncio.Task | None = None
SESSION_SWITCH_LOCKS = {aid: asyncio.Lock() for aid in AGENTS}
GOAL_CONTROL_LOCKS = {aid: asyncio.Lock() for aid in AGENTS}
MESSAGE_LOCKS = {aid: asyncio.Lock() for aid in AGENTS}


def bootstrap_conversations() -> None:
    """Attach each agent to its active conversation and load stored history.

    Every backend except OpenClaw keeps its visible history in Relay's SQLite
    store — OpenClaw agents get theirs from the native adapter snapshot. This
    used to check ``backend == "hermes"``, which silently dropped the A2A
    agents' history on every restart.
    """
    for aid, agent in AGENTS.items():
        backend_key = agent.cfg.get("session_key") if agent.backend == "openclaw" else None
        title = f"Current {agent.name} conversation" if agent.backend == "openclaw" else "New conversation"
        session = SESSIONS.ensure_agent(aid, backend_key=backend_key, title=title)
        agent.conversation_id = session["id"]
        if agent.backend != "openclaw":
            agent.msgs = SESSIONS.messages(aid, session["id"])


bootstrap_conversations()

# Phase 1.2 crash recovery. A row still in `sending` means Relay died between
# persisting the intent and learning the outcome. Relay cannot know whether the agent
# received it, so it deliberately does neither of the two tempting things: it does not
# silently resend (that risks the duplicate side effect exit test 1.1 forbids) and it
# does not drop the row (that is the message loss this phase exists to stop). It marks
# it retrying, records why, and leaves it visible for the operator to decide.
RECOVERED_SENDS = SESSIONS.outbox_recover()
if RECOVERED_SENDS:
    print(f"[relay] recovered {RECOVERED_SENDS} interrupted send(s) with an unknown "
          f"delivery outcome; left visible as retrying rather than resent or lost",
          file=sys.stderr)

warn_weak_keys(AGENTS, log=lambda msg: print(f"[relay] {msg}", file=sys.stderr))


def _native_openclaw(a: Agent) -> OpenClawAdapter | None:
    return OPENCLAW_ADAPTERS.get(a.id)


def _decorate_native_snapshot(a: Agent, snapshot: dict) -> dict:
    result = dict(snapshot)
    result["conversation_id"] = a.conversation_id
    return result


def _openclaw_adapter(a: Agent, session_key: str) -> OpenClawAdapter:
    return OpenClawAdapter(
        os.environ.get(f"RELAY_{a.id.upper()}_STATE_DIR", a.cfg.get("state_dir", ROOT / ".private" / a.id)),
        node=a.cfg.get("node", "node"), session_key=session_key, url=a.url,
    )


def _busy(a: Agent) -> bool:
    adapter = _native_openclaw(a)
    if adapter and adapter.snapshot:
        return bool(adapter.snapshot.get("activeRunIds"))
    return a.running()


def _load_local_conversation(a: Agent, session_id: str) -> None:
    a.conversation_id = session_id
    a.msgs = SESSIONS.messages(a.id, session_id)
    a.feed = []
    a.goal = {"text": "", "steps": [], "turns": 0,
              "max_turns": a.cfg.get("max_turns", 60)}
    a.approval = None
    a.status = "idle"
    a.active_run_ids = []
    a.a2a_task_id = None
    a.run_usage = {}
    a.take_answer()
    a._answer_persisted = False


def _api_error(exc: Exception, *, unavailable: bool = False):
    message = str(exc)
    if isinstance(exc, HermesError):
        if exc.is_busy:
            return JSONResponse({"ok": False, "error": message}, status_code=429,
                                headers={"Retry-After": "5"})
        if exc.status == 404:
            return JSONResponse({"ok": False, "error": message}, status_code=409)
    status = 503 if unavailable or "unavailable" in message.lower() or "disconnected" in message.lower() else 409
    return JSONResponse({"ok": False, "error": message}, status_code=status)


def _receipt(row: dict | None) -> dict:
    """What Relay can actually know about a send (1.4).

    `accepted` means a transport took the message. That is the strongest claim
    available here, and it is weaker than "delivered": Relay cannot observe another
    agent's inbox, so it must never say the word.
    """
    if not row:
        return {}
    return {"state": row.get("state"), "attempts": row.get("attempts"),
            "transport_ref": row.get("transport_ref") or None,
            "error": row.get("error") or None,
            "created_at": row.get("created_at")}


def _remember_message(a: Agent, message_id: str) -> None:
    """Keep a bounded receipt window so a retried mobile POST is accepted once."""
    if message_id in a.message_ids:
        return
    if len(a.message_id_order) >= 1000:
        a.message_ids.discard(a.message_id_order.popleft())
    a.message_id_order.append(message_id)
    a.message_ids.add(message_id)


def publish(a: Agent, ev: dict):
    """Journal the event, then fan out to SSE subscribers.

    Phase 1.1. The fan-out is still in-memory, and that is fine -- a live subscriber
    *should* get events pushed. What was not fine is that in-memory was the only
    copy: an event published while nobody was listening, or while a phone was
    between cell towers, was gone with no trace. Now every event is written to the
    durable journal and carries its global `seq`, so a client that missed something
    can ask for exactly what it missed instead of silently losing it.
    """
    a.last_activity = time.time()
    ev = dict(ev)
    try:
        ev["seq"] = SESSIONS.append_event(
            a.id, str(ev.get("type") or "event"),
            {k: v for k, v in ev.items() if k != "type"},
            session_id=a.conversation_id,
        )
    except Exception as exc:
        # Journaling must never break the live feed. The event still reaches
        # subscribers; it simply cannot be replayed, and health will show the journal
        # is not advancing.
        print(f"[relay] journal append failed for {a.id}: {exc}", file=sys.stderr)
    for q in list(a.subs):
        try:
            q.put_nowait(ev)
        except asyncio.QueueFull:
            pass


# ------------------------------------------------------- notifications ----
# Phase 2. The plane is deliberately separate from the event feed: `publish` is "the
# UI should know this happened", `_notify` is "a person should be interrupted". Mixing
# them is how a chat app becomes an alarm that nobody reads.
NOTIFIER = relay_notify.Notifier(
    SESSIONS,
    # Quiet hours are OFF. The operator declined them, and the notification policy keeps
    # them as a documented capability rather than a mandatory behaviour -- so the switch
    # lives in config (`notify.quiet_hours.enabled`, default false) and the pure policy in
    # `relay_notify.decide` still implements them for anything that asks.
    quiet=bool(((config.get("notify") or {}).get("quiet_hours") or {})
               .get("enabled", False)))
# Phase 2.6: channels are off unless configured, and a channel whose secret cannot be
# read from `.private` counts as not configured rather than taking Relay down with it.
# Nothing is assumed present, so "no channel configured" in health is a true statement.
NOTIFIER.channels.update(relay_channels.load_channels(config, ROOT, store=SESSIONS))


def _notify(a: Agent, category: str, *, title: str, body: str = "",
            dedup_key: str = "", event_seq: int | None = None) -> dict:
    """Raise one notification. Never raises -- a notification must not break a run.

    `title` is the part that can leave the host, so it stays generic. Anything
    descriptive belongs in `body`, which only the inbox ever sees (2.8).
    """
    try:
        return NOTIFIER.notify(a.id, category, title=title, body=body,
                               session_id=a.conversation_id, dedup_key=dedup_key,
                               event_seq=event_seq)
    except Exception as exc:
        print(f"[relay] notify failed for {a.id}/{category}: {exc}", file=sys.stderr)
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def notification_health() -> dict:
    """What Relay can honestly say about its own notification plane (2.7).

    "Push is configured" is not health; "a critical notification succeeded 4 minutes
    ago" is. Channels are reported as they are, including `not configured`, rather than
    assumed present.
    """
    counts = SESSIONS.notification_counts()
    channels = {name: bool(NOTIFIER.channels.get(name)) for name in ("webpush", "ntfy")}
    any_channel = any(channels.values())
    return {
        "channels": channels,
        "any_channel_configured": any_channel,
        "counts": counts,
        "last_critical_delivered_at": counts.get("last_delivered_at"),
        "last_created_at": counts.get("last_created_at"),
        "last_failure": counts.get("last_failure"),
        # Reported, not enforced as a top-level failure while no channel exists yet: a
        # permanently red screen for a channel that was never configured would train the
        # operator to ignore the health page, which is how real alarms get missed. Once
        # a channel IS configured, a failed delivery does degrade.
        "state": ("ok" if any_channel else "no channel configured"),
        # A device that has been retired shows up here as `disabled` rather than
        # vanishing, so "my phone stopped getting notifications" has an answer.
        "devices": SESSIONS.push_subscription_counts(),
        # 2.4: the deferred-notification drain's last pass. A `due` count that never
        # clears means the drain is not running, and an `at` that never advances means
        # the same thing -- which is why both are reported rather than just one.
        "drain": dict(LAST_DRAIN),
        "digest": dict(LAST_DIGEST),
        "ceiling": ("if the host is off nothing generates events and no channel can "
                    "help; redundancy does not fix a producer that is not running"),
    }


def feed(a: Agent, text: str, cls: str = "dm"):
    # Phase 1.11: stored in UTC, rendered locally by the client. `time.strftime("%H:%M")`
    # baked the *server's* timezone into the payload, which is wrong the moment the
    # phone is in another one and unreadable after a DST change, because nothing
    # recorded which offset produced it. The activity trail already worked this way;
    # this makes the feed agree with it instead of contradicting it.
    a.feed.append([text, cls, relay_db.utc_now()])
    # Warnings and errors are the lines worth keeping in the durable trail; routine
    # "$ tool" lines are recorded with structure at their own mapping points.
    if cls == "wr":
        _activity(a, kind="note", name="notice", status="warn", detail=text)
    publish(a, {"type": "feed", "text": text, "cls": cls,
                "ts": a.feed[-1][2]})


def _activity(a: Agent, *, kind: str, name: str = "", status: str = "",
              detail: str = "", duration_ms: int | None = None) -> None:
    """Record one durable activity row for this agent (never raises)."""
    try:
        SESSIONS.log_activity(
            a.id, kind=kind, name=name, status=status, detail=detail,
            duration_ms=duration_ms, session_id=a.conversation_id,
            run_id=a.run_id or a.a2a_task_id,
        )
    except Exception:
        pass


# ------------------------------------------------------- agent artefacts ----
# How a file comes *back* from an agent. Every transport here is text in / text out,
# so the file travels as a reference inside the reply and Relay does the delivery:
#
#   [[relay-attachment: tldr.html]]                     the explicit form, preferred
#   D:\...\.private\artifacts\tldr.html                 a bare path, alone on a line
#
# The bare-path form exists because that is what agents actually do unprompted -
# Echo answered a request for a report with exactly that and nothing else. A marker
# nobody has been told about would mean the feature never fires in practice.
#
# Either way the path must resolve *inside* the artifacts directory. A reply is
# untrusted text, and letting it name any file on the machine would turn "show me a
# report" into "read me your secrets".
ARTIFACTS_DIR = Path(os.environ.get("RELAY_ARTIFACTS_DIR", ROOT / ".private" / "artifacts"))
ATTACHMENT_STORE = Path(os.environ.get("RELAY_ATTACHMENT_STORE", ROOT / ".private" / "attachments"))
MAX_ARTIFACT_BYTES = 24 * 1024 * 1024

_ARTIFACT_MARKER = re.compile(r"\[\[\s*relay-attachment\s*:\s*(.+?)\s*\]\]", re.I)

_ARTIFACT_MIME = {
    ".html": "text/html", ".htm": "text/html", ".css": "text/css",
    ".js": "text/javascript", ".json": "application/json", ".txt": "text/plain",
    ".md": "text/markdown", ".csv": "text/csv", ".xml": "application/xml",
    ".svg": "image/svg+xml", ".png": "image/png", ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg", ".webp": "image/webp", ".gif": "image/gif",
    ".pdf": "application/pdf", ".mp3": "audio/mpeg", ".wav": "audio/wav",
    ".ogg": "audio/ogg", ".m4a": "audio/mp4", ".flac": "audio/flac",
}


def _artifact_path(raw: str) -> Path | None:
    """Resolve a name to a real file inside ARTIFACTS_DIR, or None.

    Absolute or relative, it must land inside the artifacts directory once resolved -
    which is what stops a reply naming C:\\Windows\\... or ..\\..\\secrets.
    """
    cleaned = str(raw or "").strip().strip('"').strip("'").strip("`").strip()
    if not cleaned:
        return None
    candidate = Path(cleaned)
    target = candidate if candidate.is_absolute() else (ARTIFACTS_DIR / candidate)
    try:
        resolved, root = target.resolve(), ARTIFACTS_DIR.resolve()
    except OSError:
        return None
    if resolved != root and root not in resolved.parents:
        return None
    return resolved if resolved.is_file() else None


def store_artifact(path: Path) -> dict | None:
    """Copy the agent's file into Relay's own store so the reference cannot rot.

    The agent's working directory is not a safe place to point at long term: it gets
    cleaned, the run ends, the file moves. Content-addressed, so the same report
    delivered twice costs one copy.
    """
    try:
        data = path.read_bytes()
    except OSError:
        return None
    if not data or len(data) > MAX_ARTIFACT_BYTES:
        return None
    digest = hashlib.sha256(data).hexdigest()
    home = ATTACHMENT_STORE / digest[:2] / digest
    meta_file = home / "meta.json"
    mime = _ARTIFACT_MIME.get(path.suffix.lower(), "application/octet-stream")
    safe_name = re.sub(r"[^\w.\- ]+", "_", path.name)[:120] or "attachment"
    if not meta_file.is_file():
        try:
            home.mkdir(parents=True, exist_ok=True)
            (home / safe_name).write_bytes(data)
            meta_file.write_text(json.dumps({
                "id": digest, "name": path.name, "file": safe_name,
                "type": mime, "size": len(data),
            }, indent=2), encoding="utf-8")
        except OSError:
            return None
    return {"id": digest, "name": path.name, "type": mime, "size": len(data)}


def extract_artifacts(text: str) -> tuple[str, list]:
    """Pull agent artefacts out of a reply. Returns (reply_without_them, attachments)."""
    if not text:
        return text, []
    found: list[dict] = []
    seen: set[str] = set()

    def take(raw: str) -> bool:
        target = _artifact_path(raw)
        if not target:
            return False
        stored = store_artifact(target)
        if not stored or stored["id"] in seen:
            return False
        seen.add(stored["id"])
        found.append(stored)
        return True

    cleaned = _ARTIFACT_MARKER.sub(lambda m: "" if take(m.group(1)) else m.group(0), text)

    # A line that is *only* a path inside the artifacts dir. Deliberately strict:
    # a line with prose around it is left alone, so a reply that merely mentions a
    # file in passing is not silently rewritten.
    kept: list[str] = []
    for line in cleaned.splitlines():
        bare = line.strip().strip('"').strip("'").strip("`")
        looks_like_path = bool(
            re.match(r"^[A-Za-z]:[\\/]", bare) or bare.startswith("/") or bare.startswith("\\\\")
        )
        if looks_like_path and _artifact_path(bare) and take(bare):
            continue
        kept.append(line)
    cleaned = "\n".join(kept).strip()
    return cleaned, found


def say(a: Agent, who: str, text: str, attachments: list | None = None):
    # A reply from an agent may carry artefacts. Extracting here rather than at each
    # transport means Hermes, A2A and everything added later get delivery for free -
    # `say` is the one choke point they all pass through.
    if who == "ag":
        text, found = extract_artifacts(text)
        if found:
            attachments = list(attachments or []) + found
    msg = {"k": who, "t": text}
    if attachments:
        msg["attachments"] = [
            {"name": item["name"], "type": item["type"], "size": item["size"],
             **({"id": item["id"]} if item.get("id") else {})}
            for item in attachments
        ]
    a.msgs.append(msg)
    if a.backend != "openclaw" and a.conversation_id:
        SESSIONS.add_message(a.id, a.conversation_id, who, text,
                             msg.get("attachments", []))
    publish(a, {"type": "msg", **msg})


def set_status(a: Agent, status: str):
    a.status = status
    publish(a, {"type": "status", "status": status})


def set_goal(a: Agent, text: str, steps: list, max_turns: int = 60):
    a.goal = {"text": text, "steps": steps, "turns": 0, "max_turns": max_turns}
    publish(a, {"type": "goal", "goal": a.goal})


def set_step(a: Agent, idx: int, state: str, stamp: str = ""):
    # state: "d" done | "a" active | "p" pending | "w" warn/waiting
    if 0 <= idx < len(a.goal["steps"]):
        a.goal["steps"][idx][2] = state
        if stamp:
            a.goal["steps"][idx][1] = stamp
        publish(a, {"type": "step", "idx": idx, "state": state, "stamp": stamp})


def bump_turn(a: Agent, n: int = 1):
    a.goal["turns"] += n
    publish(a, {"type": "turns", "turns": a.goal["turns"]})


def _hermes_state_db(a: Agent) -> Path | None:
    """Return the local Hermes state database used by the Desktop app."""
    configured = str(a.cfg.get("state_db") or "").strip()
    if configured:
        return Path(os.path.expandvars(configured)).expanduser()
    if a.device == "pc" and os.environ.get("LOCALAPPDATA"):
        return Path(os.environ["LOCALAPPDATA"]) / "hermes" / "state.db"
    return None


#: How old a recorded backup receipt may be before it counts as stale (1.9). The
#: receipt job runs daily, so 36 hours means "a run was missed", not "it is a little
#: late".
RECEIPT_MAX_AGE_HOURS = 36


def _agent_state_stores(a: Agent) -> list[dict]:
    """Agent-side memory Relay can *observe*. Relay never writes to any of these.

    Phase 1.9. Echo's `state.db`, Cyony's volume and DSH's session store hold the
    agents' actual memory, and Relay's own backup covers none of them. Relay cannot
    claim an agent's backup succeeded -- it has no way to know, and inventing that
    claim is exactly what `docs/precedence-rule.md` forbids. What it can do is look,
    record that it looked, and turn an unowned store into a visible gap.
    """
    stores: list[dict] = []
    # Only for agents whose memory genuinely is Hermes' state.db. `_hermes_state_db`
    # falls back to the local Hermes path for *any* PC agent, so applying it blindly
    # labelled Hermes' 6 GB database as DSH's memory store -- a wrong answer that looks
    # entirely plausible in a report, which is the worst kind.
    if a.backend == "hermes" or a.cfg.get("state_db"):
        db = _hermes_state_db(a)
        if db is not None:
            stores.append({"label": "hermes state.db", "path": str(db)})
    for item in (a.cfg.get("state_stores") or []):
        if isinstance(item, str):
            stores.append({"label": Path(item).name or item, "path": item})
        elif isinstance(item, dict) and item.get("path"):
            path = str(item["path"])
            stores.append({"label": str(item.get("label") or Path(path).name or path),
                           "path": path})
    default_hours = float(a.cfg.get("state_store_max_age_hours", 48))
    for store in stores:
        store["max_age_hours"] = default_hours
    return stores


def _receipt_age_hours(row: dict | None) -> float | None:
    if not row or not row.get("ts"):
        return None
    try:
        when = datetime.fromisoformat(str(row["ts"]))
    except ValueError:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return round((datetime.now(timezone.utc) - when).total_seconds() / 3600, 1)


def observe_agent_stores(*, record: bool = False) -> list[dict]:
    """Observe every configured agent-side store, reporting only what was seen.

    Deliberately shallow: `stat()` on the path, never a recursive walk. This is called
    from `/api/health`, and walking a 6 GB store on every health request to produce a
    number nobody asked for would be a bad trade. The receipt tool does the deeper look.
    """
    now = time.time()
    seen: list[dict] = []
    for a in AGENTS.values():
        for store in _agent_state_stores(a):
            entry = {"agent": a.id, "label": store["label"], "path": store["path"],
                     "max_age_hours": store["max_age_hours"]}
            path = Path(store["path"])
            try:
                info = path.stat()
                is_dir = path.is_dir()
                entry.update({"exists": True, "kind": "dir" if is_dir else "file",
                              "bytes": None if is_dir else info.st_size,
                              "age_hours": round((now - info.st_mtime) / 3600, 1)})
            except OSError as exc:
                entry.update({"exists": False, "kind": None, "bytes": None,
                              "age_hours": None, "error": type(exc).__name__})
            if not entry["exists"]:
                entry["state"] = "missing"
            elif entry["age_hours"] is None:
                entry["state"] = "unknown"
            elif entry["age_hours"] > float(store["max_age_hours"]):
                entry["state"] = "stale"
            else:
                entry["state"] = "recent"
            seen.append(entry)
            if record:
                # A receipt records that Relay *looked*, and what it saw. It is not a
                # statement that the agent's own backup worked.
                SESSIONS.log_activity(
                    a.id, kind="backup", name=entry["label"],
                    status={"recent": "ok", "stale": "stale",
                            "missing": "missing"}.get(entry["state"], "unknown"),
                    detail=(f"observed {entry['path']} state={entry['state']} "
                            f"age={entry['age_hours']}h"))
    return seen


def _hermes_agent_source(a: Agent) -> Path | None:
    """Locate the installed Hermes package that owns the goal manager API."""
    configured = str(a.cfg.get("hermes_source") or "").strip()
    if configured:
        candidate = Path(os.path.expandvars(configured)).expanduser()
    else:
        db_path = _hermes_state_db(a)
        candidate = db_path.parent / "hermes-agent" if db_path else None
    return candidate if candidate and (candidate / "hermes_cli" / "goals.py").is_file() else None


def _control_hermes_desktop_goal(a: Agent, session_id: str, action: str) -> str | None:
    """Apply one action through Hermes' public GoalManager, never raw SQL."""
    source = _hermes_agent_source(a)
    if not source:
        raise RuntimeError("Hermes goal controls are unavailable on this device")
    source_text = str(source)
    if source_text not in sys.path:
        sys.path.insert(0, source_text)
    from hermes_cli.goals import GoalManager

    manager = GoalManager(session_id=session_id)
    if action == "pause":
        if manager.pause(reason="user-paused") is None:
            raise RuntimeError("There is no active goal to pause")
        return None
    if action == "resume":
        if manager.resume() is None:
            raise RuntimeError("There is no paused goal to resume")
        return manager.next_continuation_prompt()
    if action == "delete":
        if not manager.has_goal():
            raise RuntimeError("There is no goal to delete")
        manager.clear()
        return None
    raise ValueError(f"Unsupported goal action: {action}")


async def _continue_hermes_desktop_goal(a: Agent, session_id: str, prompt: str):
    """Run Hermes' continuation prompt against the same persisted Desktop session."""
    import httpx

    headers = {"Authorization": f"Bearer {a.api_key}"} if a.api_key else {}
    endpoint = f"{a.url.rstrip('/')}/api/sessions/{session_id}/chat"
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(None)) as client:
            response = await client.post(endpoint, json={"message": prompt}, headers=headers)
        if response.status_code in (401, 403):
            raise RuntimeError("Hermes rejected the Relay API key")
        if response.status_code != 200:
            raise RuntimeError(f"Hermes continuation returned {response.status_code}")
        payload = response.json()
        answer = str((payload.get("message") or {}).get("content") or "").strip()
        if answer:
            say(a, "ag", answer)
    except Exception as exc:
        _dbg(a.id, f"desktop goal continuation failed: {type(exc).__name__}: {exc}")
        feed(a, f"!! goal resumed, but continuation failed: {exc}", "wr")
        set_status(a, "waiting")
    finally:
        a.goal_control_task = None


def _todo_steps(raw: str | None) -> list[list[str]]:
    try:
        payload = json.loads(raw or "{}")
    except (TypeError, json.JSONDecodeError):
        return []
    todos = payload.get("todos") if isinstance(payload, dict) else None
    if not isinstance(todos, list):
        return []
    by_id = {
        str(item.get("id", "")): item for item in todos
        if isinstance(item, dict) and str(item.get("id", "")).strip()
    }

    def depth(item: dict) -> int:
        seen = set()
        parent = str(item.get("parent") or "")
        result = 0
        while parent and parent in by_id and parent not in seen and result < 3:
            seen.add(parent)
            result += 1
            parent = str(by_id[parent].get("parent") or "")
        return result

    state_map = {"completed": "d", "in_progress": "a", "cancelled": "w"}
    steps = []
    for item in todos:
        if not isinstance(item, dict):
            continue
        item_text = str(item.get("content") or "").strip()
        if not item_text:
            continue
        steps.append(["  " * depth(item) + item_text, "",
                      state_map.get(str(item.get("status")), "p")])
    return steps


def _read_hermes_desktop_goal(a: Agent) -> dict | None:
    """Read the newest Hermes Desktop session's real goal and todo state."""
    db_path = _hermes_state_db(a)
    if not db_path or not db_path.is_file():
        return None
    uri = f"file:{db_path.as_posix()}?mode=ro"
    with contextlib.closing(sqlite3.connect(uri, uri=True, timeout=0.75)) as db:
        db.row_factory = sqlite3.Row
        session = db.execute(
            """SELECT id, COALESCE(last_activity_at, started_at) AS updated_at
               FROM sessions
               WHERE source = 'desktop' AND COALESCE(hidden, 0) = 0
               ORDER BY COALESCE(last_activity_at, started_at) DESC LIMIT 1"""
        ).fetchone()
        if not session:
            return None
        meta = db.execute(
            "SELECT value FROM state_meta WHERE key = ?",
            (f"goal:{session['id']}",),
        ).fetchone()
        if not meta:
            return {"session_id": session["id"], "goal": None}
        try:
            native = json.loads(meta["value"])
        except (TypeError, json.JSONDecodeError):
            return None
        todo = db.execute(
            """SELECT content FROM messages
               WHERE session_id = ? AND tool_name IN ('todo_list', 'todo')
                 AND content IS NOT NULL
               ORDER BY id DESC LIMIT 1""",
            (session["id"],),
        ).fetchone()
    native_status = str(native.get("status") or "")
    if native_status == "cleared":
        return {"session_id": session["id"], "status": "idle", "goal": None}
    waiting = bool(native.get("waiting_on_pid") or native.get("waiting_on_session")
                   or native.get("waiting_until"))
    relay_status = (
        "done" if native_status == "done" else
        "waiting" if native_status == "paused" or waiting else
        "working" if native_status == "active" else "idle"
    )
    return {
        "session_id": session["id"],
        "status": relay_status,
        "goal": {
            "text": str(native.get("goal") or "").strip(),
            "steps": _todo_steps(todo["content"] if todo else None),
            "turns": int(native.get("turns_used") or 0),
            "max_turns": int(native.get("max_turns") or a.cfg.get("max_turns", 60)),
            "source": "hermes_desktop",
            "controls": ["pause", "resume", "delete"],
            "native_status": native_status,
            "reason": str(native.get("paused_reason") or native.get("last_reason") or ""),
        },
    }


def _apply_hermes_desktop_snapshot(a: Agent, snapshot: dict) -> None:
    """Apply one confirmed Desktop snapshot to Relay and its SSE subscribers."""
    a.desktop_session_id = snapshot.get("session_id")
    mirrored = snapshot.get("goal")
    if mirrored is None:
        if a.goal.get("source") == "hermes_desktop":
            a.goal = {"text": "", "steps": [], "turns": 0,
                      "max_turns": a.cfg.get("max_turns", 60)}
            publish(a, {"type": "goal", "goal": a.goal})
            set_status(a, "idle")
        return
    a.goal = mirrored
    publish(a, {"type": "goal", "goal": a.goal})
    set_status(a, snapshot["status"])


async def hermes_desktop_loop():
    """Mirror local Hermes Desktop goals into Relay's existing SSE contract."""
    signatures: dict[str, str] = {}
    while True:
        for a in AGENTS.values():
            if a.backend != "hermes" or _hermes_state_db(a) is None:
                continue
            try:
                snapshot = await asyncio.to_thread(_read_hermes_desktop_goal, a)
            except Exception as exc:
                _dbg(a.id, f"desktop goal mirror failed: {type(exc).__name__}: {exc}")
                continue
            signature = json.dumps(snapshot, sort_keys=True, ensure_ascii=False)
            if signatures.get(a.id) == signature:
                continue
            signatures[a.id] = signature
            if not snapshot:
                continue
            _apply_hermes_desktop_snapshot(a, snapshot)
        await asyncio.sleep(1.0)


# ------------------------------------------------------------- adapters ----
# NOTE: these speak to the *local gateways*, not the desktop apps.
# Hermes:  OpenAI-compatible API server, port 8642 by default
#          (API_SERVER_ENABLED=true in ~/.hermes/.env). /v1/runs streams run
#          progress. Schemas change between releases — the handlers below
#          pass through whatever fields they find; tighten them once you see
#          real payloads (they land in relay_debug.log when debug=true).
# OpenClaw: gateway control plane, port 18789, WebSocket API.
DEBUG = config.get("debug", False)
_debuglog = ROOT / "relay_debug.log"


def _parse_attachments(raw_files) -> list:
    if raw_files is None:
        return []
    if not isinstance(raw_files, list):
        raise ValueError("attachments must be a list")
    if len(raw_files) > MAX_ATTACHMENTS:
        raise ValueError(f"choose no more than {MAX_ATTACHMENTS} attachments")
    parsed = []
    total = 0
    for raw in raw_files:
        if not isinstance(raw, dict):
            raise ValueError("invalid attachment")
        name = Path(str(raw.get("name") or "attachment")).name[:180]
        mime = str(raw.get("type") or "application/octet-stream").lower().split(";", 1)[0]
        data_url = raw.get("data")
        if not isinstance(data_url, str) or not data_url.startswith("data:") or "," not in data_url:
            raise ValueError(f"{name}: invalid attachment data")
        header, encoded = data_url.split(",", 1)
        if ";base64" not in header.lower():
            raise ValueError(f"{name}: attachment must be base64 encoded")
        header_mime = header[5:].split(";", 1)[0].lower()
        if header_mime:
            mime = header_mime
        is_image = mime in IMAGE_MIME_TYPES
        is_text = mime in TEXT_MIME_TYPES or Path(name).suffix.lower() in TEXT_EXTENSIONS
        if not (is_image or is_text):
            raise ValueError(f"{name}: this file type is not supported yet")
        try:
            data = base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError):
            raise ValueError(f"{name}: invalid base64 data")
        size = len(data)
        limit = MAX_ATTACHMENT_BYTES if is_image else MAX_TEXT_ATTACHMENT_BYTES
        if size > limit:
            label = "8 MB" if is_image else "512 KB"
            raise ValueError(f"{name}: file exceeds the {label} limit")
        total += size
        if total > MAX_TOTAL_ATTACHMENT_BYTES:
            raise ValueError("attachments exceed the 16 MB total limit")
        item = {"name": name, "type": mime, "size": size, "data": data_url}
        if is_text:
            try:
                item["text"] = data.decode("utf-8")
            except UnicodeDecodeError:
                raise ValueError(f"{name}: text file must use UTF-8 encoding")
        parsed.append(item)
    return parsed


def _dbg(agent_id: str, payload: str):
    if DEBUG:
        with _debuglog.open("a") as f:
            # Local time on purpose: this is a host-side diagnostic log read on the
            # host, not stored user data, and matching the operator's wall clock is
            # what makes it useful when correlating with something they just saw.
            f.write(f"[{time.strftime('%H:%M:%S')}] {agent_id} {payload}\n")


#: Phase 1.8: rotate a log once it passes this size, keeping one previous file.
LOG_MAX_BYTES = 5 * 1024 * 1024


def rotate_log(path: Path, *, max_bytes: int = LOG_MAX_BYTES, keep: int = 1) -> dict:
    """Rotate `path` to `path.1` when it has grown past `max_bytes`.

    Only safe for logs this process opens per write. `relay-run.log` is *not* one of
    those: the shell redirect in `start-relay.cmd` holds an open handle for the life of
    the process, and Windows will not rename a file with an open handle. That log is
    rotated by the launcher before it opens the redirect instead -- which is why this
    lives in two places rather than one tidy place.
    """
    result: dict = {"path": str(path), "rotated": False}
    try:
        if not path.is_file():
            return result
        size = path.stat().st_size
        result["bytes"] = size
        if size <= max_bytes:
            return result
        for index in range(keep, 0, -1):
            older = path.with_name(f"{path.name}.{index}")
            newer = (path.with_name(f"{path.name}.{index + 1}") if index < keep
                     else path)
            if older.exists():
                older.unlink()
            if newer.exists():
                newer.rename(older)
        result["rotated"] = True
    except OSError as exc:
        # Rotation is housekeeping. A failure here must not stop Relay starting.
        result["error"] = f"{type(exc).__name__}: {exc}"
    return result


# Rotate the debug log at startup. It is opened per write, so no handle is held.
LOG_ROTATION = rotate_log(_debuglog)


# ------------------------------------------------- Hermes native Runs API ----
def _hermes_client(a: Agent) -> HermesRunsClient:
    """Return this agent's long-lived Hermes client."""
    if a.hermes is None:
        a.hermes = HermesRunsClient(
            a.url,
            a.api_key,
            model=a.cfg.get("model", ""),
            session_key=f"relay:{a.id}:{a.conversation_id or 'default'}",
        )
    return a.hermes


def _hermes_run_id(a: Agent) -> str | None:
    return a.active_run_ids[0] if a.active_run_ids else None


def _record_run_event(a: Agent, event: dict) -> None:
    """Keep a bounded native-event trail for diagnostics (never in the feed)."""
    a.run_events.append(event)
    if len(a.run_events) > 400:
        del a.run_events[:200]
    if DEBUG:
        with contextlib.suppress(Exception):
            _dbg(a.id, json.dumps(event)[:500])


def _apply_run_event(a: Agent, event: dict) -> bool:
    """Map one native Hermes run event onto Relay's existing SSE contract.

    Returns True when the event is terminal for this run.
    """
    name = str(event.get("event") or "")
    if not name:
        return False

    if name == relay_hermes.EVENT_MESSAGE_DELTA:
        delta = event.get("delta")
        if delta:
            a._answer_parts.append(str(delta))
        return False

    if name == relay_hermes.EVENT_TOOL_STARTED:
        tool = str(event.get("tool") or "?")
        preview = str(event.get("preview") or "").strip()
        feed(a, f"$ {tool}{' · ' + preview if preview else ''}", "dm")
        _activity(a, kind="tool", name=tool, status="started", detail=preview)
        return False

    if name == relay_hermes.EVENT_TOOL_COMPLETED:
        tool = str(event.get("tool") or "?")
        duration = relay_hermes._fmt_duration(event.get("duration"))
        suffix = f" · {duration}" if duration else ""
        failed = bool(event.get("error"))
        if failed:
            feed(a, f"✗ {tool} failed{suffix}", "wr")
        else:
            feed(a, f"✓ {tool}{suffix}", "ok")
        try:
            ms = int(float(event.get("duration")) * 1000)
        except (TypeError, ValueError):
            ms = None
        _activity(a, kind="tool", name=tool, status="failed" if failed else "ok",
                  detail=str(event.get("preview") or ""), duration_ms=ms)
        return False

    if name == relay_hermes.EVENT_REASONING:
        text = relay_hermes._clip(event.get("text"))
        if text:
            feed(a, f"⋯ {text}", "dm")
        return False

    if name == relay_hermes.EVENT_SUBAGENT_START:
        label = relay_hermes._clip(event.get("goal") or event.get("subagent_id") or "subagent")
        feed(a, f"↳ subagent started: {label}", "dm")
        _activity(a, kind="delegation", name=str(event.get("subagent_id") or "subagent"),
                  status="started", detail=label)
        return False

    if name == relay_hermes.EVENT_SUBAGENT_COMPLETE:
        status = str(event.get("status") or "done")
        cost = event.get("cost_usd")
        suffix = f" · ${float(cost):.4f}" if isinstance(cost, (int, float)) and cost else ""
        feed(a, f"↳ subagent {status}{suffix}", "ok" if status == "done" else "wr")
        _activity(a, kind="delegation", name=str(event.get("subagent_id") or "subagent"),
                  status=status,
                  detail=relay_hermes._clip(event.get("summary") or event.get("goal") or "", 300))
        return False

    if name == relay_hermes.EVENT_APPROVAL_REQUEST:
        # Hermes supplies the exact request id and the choices it will accept.
        a.approval = {"id": str(event.get("request_id") or ""),
                      "cmd": str(event.get("command") or event.get("preview") or "approval required"),
                      "choices": list(event.get("choices") or [])}
        publish(a, {"type": "approval", "cmd": a.approval["cmd"], "id": a.approval["id"],
                    "choices": a.approval["choices"]})
        set_status(a, "waiting")
        _activity(a, kind="approval", name="approval", status="waiting",
                  detail=a.approval["cmd"])
        # An agent is stopped until a human decides, so this breaks through quiet hours.
        # The command goes in `body` (inbox only); `title` is the generic string that a
        # push or ntfy payload may carry -- "Approval needed: delete D:\Dev\prod-db"
        # would hand the operation to a third party.
        _notify(a, "approval", title="Approval needed",
                body=f"{a.name}: {a.approval['cmd']}",
                dedup_key=f"approval:{a.id}:{a.approval['id']}")
        return False

    if name == relay_hermes.EVENT_APPROVAL_RESPONDED:
        if str(event.get("request_id") or "") == str((a.approval or {}).get("id") or ""):
            a.approval = None
            publish(a, {"type": "approval", "cmd": None})
            set_status(a, "working")
        return False

    if name == relay_hermes.EVENT_RUN_STEERED:
        feed(a, "$ steer accepted", "dm")
        return False

    if name.startswith("run."):
        state = name.split(".", 1)[1]
        usage = event.get("usage")
        if isinstance(usage, dict) and usage:
            a.run_usage = usage
        output = event.get("output")
        if output and not a._answer_persisted and not a._answer_parts:
            # No deltas arrived (or the stream was re-attached late): use the
            # terminal payload so the reply is not lost.
            a._answer_parts.append(str(output))
        a.approval = None
        publish(a, {"type": "approval", "cmd": None})
        if state in {"completed"}:
            feed(a, "── run completed ──", "wr")
            set_status(a, "done")
        elif state in {"cancelled", "stopped"}:
            feed(a, "── run stopped ──", "wr")
            set_status(a, "stopped")
        elif state == "interrupted":
            feed(a, f"!! run interrupted: {relay_hermes._clip(event.get('error'))}", "wr")
            set_status(a, "stopped")
        else:
            feed(a, f"!! run failed: {relay_hermes._clip(event.get('error'))}", "wr")
            set_status(a, "stopped")
        _activity(a, kind="run", name=name, status=state,
                  detail=relay_hermes._clip(event.get("error") or
                                            (f"usage {usage}" if usage else ""), 200))
        return True

    return False


def _persist_hermes_reply(a: Agent, final_status: dict) -> None:
    """Persist the agent's reply exactly once, from the terminal payload."""
    if a._answer_persisted:
        return
    a._answer_persisted = True
    text = a.take_answer()
    if text:
        say(a, "ag", text)


async def hermes_send(a: Agent, text: str, message_id: str = "", attachments: list | None = None):
    """Run one turn through Hermes' native Runs API.

    The conversation id is handed to Hermes as ``session_id``, so Hermes owns the
    transcript. Relay does not resend history, which is what removes the old
    duplicated/truncated context and makes the session shared with the Desktop
    app and Telegram.
    """
    attachments = attachments or []
    body, unsupported = relay_hermes.split_attachments(
        text, attachments, image_types=IMAGE_MIME_TYPES
    )
    if unsupported:
        feed(a, "!! this transport cannot send images (Hermes /v1/runs takes text only): "
                + ", ".join(unsupported), "wr")
    if not body.strip():
        set_status(a, "done")
        return

    client = _hermes_client(a)
    await client.require_runs_api()
    session_id = a.conversation_id or str(uuid.uuid4())
    a.conversation_id = session_id
    await client.ensure_session(session_id, title=f"Relay · {a.name}")

    a._answer_parts = []
    a._answer_persisted = False
    set_status(a, "working")
    admitted = await client.submit_run(
        text=body,
        session_id=session_id,
        idempotency_key=message_id or "",
    )
    run_id = str(admitted["run_id"])
    a.active_run_ids = [run_id]
    publish(a, {"type": "status", "status": a.status, "runId": run_id})
    if admitted.get("replayed"):
        feed(a, "$ run already admitted; re-attaching to its event stream", "dm")

    terminal = False
    try:
        async for event in client.stream_events(run_id):
            _record_run_event(a, event)
            if _apply_run_event(a, event):
                terminal = True
                break
    except asyncio.CancelledError:
        # Stop was pressed: let the native stop path settle the run, then persist.
        raise
    except Exception as exc:
        _dbg(a.id, f"run event stream failed: {type(exc).__name__}: {exc}")
        feed(a, f"!! event stream interrupted ({exc}); reconciling run status", "wr")

    if not terminal:
        # The stream ended or dropped without a terminal event: poll the run so
        # a reboot, reconnect, or dropped SSE cannot lose the outcome.
        try:
            status = await client.wait_for_terminal(
                run_id, timeout=RUN_SETTLE_TIMEOUT
            )
        except Exception as exc:
            _dbg(a.id, f"run status poll failed: {type(exc).__name__}: {exc}")
            status = {}
        state = str(status.get("status") or "")
        if state in relay_hermes.TERMINAL_STATUSES:
            _apply_run_event(a, {
                "event": f"run.{state}",
                "output": status.get("output"),
                "error": status.get("error"),
                "usage": status.get("usage"),
            })
        elif state:
            feed(a, f"!! run is still {state}; Relay will reconcile on refresh", "wr")

    _persist_hermes_reply(a, {})
    if run_id in a.active_run_ids:
        a.active_run_ids.remove(run_id)
    publish(a, {"type": "status", "status": a.status, "runId": None})


# ------------------------------------------------------- A2A transport ----
# For peers that expose a conversation but no native Hermes API surface.
def _a2a_client(a: Agent) -> A2AClient:
    """Return this agent's long-lived A2A client."""
    if a.a2a is None:
        a.a2a = A2AClient(a.url, a.api_key)
    return a.a2a


def _apply_a2a_event(a: Agent, event: dict) -> bool:
    """Map one A2A stream event onto Relay's browser contract.

    A2A exposes task states and streamed text; it has no tool-level, approval, or
    steering events, so nothing here fabricates them.
    """
    kind = event.get("kind")
    if kind == "accepted":
        return False
    if kind == "context":
        return False
    if kind == "artifact":
        text = str(event.get("text") or "")
        if text:
            a._answer_parts.append(text)
        return False
    if kind == "status":
        state = str(event.get("state") or "")
        if state == relay_a2a.STATE_INPUT_REQUIRED:
            # She is asking a clarifying question; that is not completion.
            feed(a, "── she is waiting on your answer ──", "wr")
        set_status(a, str(event.get("status") or "working"))
        _activity(a, kind="run", name=f"a2a {state}", status="working")
        return False
    if kind == "terminal":
        state = str(event.get("state") or "")
        text = str(event.get("text") or "")
        _activity(a, kind="run", name=f"a2a {state or 'unknown'}", status=state,
                  detail=relay_hermes._clip(text, 200))
        if text and not a._answer_parts:
            a._answer_parts.append(text)
        clean, needs_input = relay_a2a.strip_input_required("".join(a._answer_parts))
        a._answer_parts = [clean] if clean else []
        # A clarification is a real, answerable outcome and must win over the
        # generic "stream ended early" case: the marker arrives on that same event.
        if needs_input or state == relay_a2a.STATE_INPUT_REQUIRED:
            if clean:
                say(a, "ag", clean)
                a._answer_persisted = True
            feed(a, "── she is waiting on your answer ──", "wr")
            set_status(a, "waiting")
            return True
        if event.get("truncated"):
            feed(a, "!! the A2A stream ended without a terminal state; the reply may be "
                    "incomplete", "wr")
            set_status(a, "stopped")
            return True
        if state == relay_a2a.STATE_COMPLETED:
            feed(a, "── task completed ──", "wr")
            set_status(a, "done")
        else:
            label = state.replace("TASK_STATE_", "").lower() or "failed"
            if clean:
                say(a, "ag", clean)
                a._answer_persisted = True
            feed(a, f"!! task {label}", "wr")
            set_status(a, "stopped")
        return True
    return False


async def a2a_send(a: Agent, text: str, message_id: str = "",
                   attachments: list | None = None):
    """Run one turn against an A2A peer.

    The peer's ``contextId`` is Relay's durable conversation id, so the peer keeps
    the conversation memory across turns and across a Relay restart.
    """
    body, unsupported = relay_hermes.split_attachments(
        text, attachments or [], image_types=IMAGE_MIME_TYPES
    )
    if unsupported:
        feed(a, "!! this A2A transport cannot send images: " + ", ".join(unsupported), "wr")

    client = _a2a_client(a)
    a._answer_parts = []
    a._answer_persisted = False
    a.a2a_task_id = None
    context_id = a.conversation_id or str(uuid.uuid4())
    a.conversation_id = context_id
    set_status(a, "working")

    terminal = False
    async for event in client.stream(body, context_id=context_id, request_id=message_id):
        if event.get("kind") == "status" and event.get("task_id"):
            a.a2a_task_id = str(event["task_id"])
        if event.get("kind") == "terminal" and event.get("task_id"):
            a.a2a_task_id = str(event["task_id"])
        _record_run_event(a, {"transport": "a2a", **event})
        if _apply_a2a_event(a, event):
            terminal = True
            # Keep consuming rather than breaking: the transport yields the terminal
            # event last and then returns, so letting the iterator finish closes its
            # HTTP stream cleanly instead of abandoning a suspended generator.

    if not terminal:
        feed(a, "!! the A2A turn ended without a terminal state", "wr")
        set_status(a, "stopped")

    _persist_hermes_reply(a, {})
    a.a2a_task_id = None
    publish(a, {"type": "status", "status": a.status, "runId": None})


async def run_turn(a: Agent, text: str, message_id: str = "",
                   attachments: list | None = None):
    """Dispatch one turn to whichever transport this agent is configured for.

    Phase 1.2. `run_turn` is the one place every transport converges, so it is where
    the outbox is claimed and settled. Claiming is the commit point: a row still in
    `sending` after a restart is a row whose outcome Relay genuinely does not know.
    """
    row = None
    if message_id:
        try:
            row = SESSIONS.outbox_get(message_id)
        except Exception:
            row = None
    claim = None
    if row and row.get("state") in ("pending", "retrying"):
        try:
            claim = SESSIONS.outbox_claim(row["id"])
        except Exception:
            claim = None

    try:
        if a.is_a2a:
            await a2a_send(a, text, message_id, attachments)
        else:
            await hermes_send(a, text, message_id, attachments)
    except Exception as exc:
        if claim:
            try:
                SESSIONS.outbox_fail(claim["id"], f"{type(exc).__name__}: {exc}")
            except Exception:
                pass
        raise                    # the caller keeps its existing error handling
    if claim:
        try:
            SESSIONS.outbox_settle(claim["id"], "accepted")
        except Exception:
            pass


async def drain_hermes_messages(a: Agent):
    """Deliver accepted messages in order instead of dropping a burst."""
    try:
        while a.message_queue:
            item = a.message_queue.popleft()
            text, attachments, message_id = item
            try:
                await run_turn(a, text, message_id, attachments)
            except (HermesError, A2AError, asyncio.TimeoutError) as exc:
                _dbg(a.id, f"turn failed: {type(exc).__name__}: {exc}")
                if a.cfg.get("demo_fallback", False):
                    await demo_run(a, text, attachments)
                else:
                    feed(a, f"!! {a.name} unavailable: {exc}", "wr")
                    set_status(a, "stopped")
                    # An error is an immediate category: a run stopped and nobody is
                    # watching. Keyed on the turn so a retry storm is one notification.
                    _notify(a, "error", title=f"{a.name} unavailable",
                            body=str(exc), dedup_key=f"error:{a.id}:{message_id}")
    finally:
        a.run_task = None


# ------------------------------------------------------------ demo mode ----
# Scripted runs so the UI is alive before the real gateways are wired in.
DEMO_SCRIPTS = {
    "echo": [
        ("goal", "build relay proxy — one API in front of both gateways", [
            ["Scaffold FastAPI project", "", "p"], ["Session schema + SQLite", "", "p"],
            ["Hermes /v1/runs adapter", "", "p"], ["OpenClaw WebSocket adapter", "", "p"],
            ["SSE fan-out to browser", "", "p"], ["Stall watchdog timer", "", "p"],
            ["PWA manifest + icons", "", "p"]]),
        ("feed", "$ uv init relay && cd relay", "dm"), ("ok", "✓ scaffolded · 1.2s"),
        ("feed", "$ write relay/models.py", "dm"), ("ok", "✓ sessions table"),
        ("step", 0, "d"), ("step", 1, "d"),
        ("feed", "$ POST echo:8642/v1/runs", "dm"), ("feed", "← 200 · run_01JX · 1.2s", "dm"),
        ("step", 2, "d"),
        ("feed", "$ ws tripp:18789", "dm"), ("feed", "← connected · 4 msgs", "dm"),
        ("step", 3, "d"), ("step", 4, "a"),
        ("feed", "$ write relay/adapters/openclaw.py", "dm"), ("ok", "✓ 84 lines"),
        ("step", 4, "d"), ("step", 5, "a"),
        ("say", "ag", "Steps 1–4 done — both gateway adapters are talking. Watchdog next."),
        ("feed", "$ write relay/watchdog.py", "dm"), ("ok", "✓ armed · 90s idle threshold"),
        ("step", 5, "d"), ("step", 6, "a"),
        ("feed", "$ write manifest.json", "dm"), ("ok", "✓ installable PWA"),
        ("step", 6, "d"),
        ("done", "goal achieved · 24 turns · zero nudges"),
    ],
    "tripp": [
        ("goal", "compare VPS options for Cyony migration", [
            ["Collect pricing pages", "", "p"], ["Summarize bandwidth caps", "", "p"],
            ["Draft comparison table", "", "p"], ["Send recommendation", "", "p"]]),
        ("feed", "$ tool browser.fetch hetzner.com/pricing", "dm"),
        ("feed", "← 200 · 12 rows", "dm"), ("step", 0, "d"),
        ("feed", "$ tool browser.fetch digitalocean.com/pricing", "dm"),
        ("feed", "← 200 · 9 rows", "dm"),
        ("feed", "$ tool browser.fetch vultr.com/pricing", "dm"),
        ("feed", "← 200 · 10 rows", "dm"), ("step", 1, "d"), ("step", 2, "a"),
        ("stall", None),
    ],
    "cyony": [
        ("goal", "migrate relay sessions to Postgres", [
            ["Backup SQLite", "", "p"], ["Write docker-compose.yml", "", "p"],
            ["Start relay-db container", "", "p"], ["Run migration script", "", "p"]]),
        ("feed", "$ pg_dump relay.db → backup.sql", "dm"), ("ok", "✓ 2.1mb · sha verified"),
        ("step", 0, "d"),
        ("feed", "$ write docker-compose.yml", "dm"), ("ok", "✓ relay-db service defined"),
        ("step", 1, "d"),
        ("appr", "docker compose up -d relay-db"),
    ],
}


async def demo_run(a: Agent, user_text: str, attachments: list | None = None):
    script = DEMO_SCRIPTS.get(a.id, DEMO_SCRIPTS["echo"])
    if a.status in ("stalled",) and user_text.strip().lower() in ("continue", "y", "nudge"):
        feed(a, "$ resume · continuing", "dm")
        return
    set_status(a, "working")
    for item in script:
        await asyncio.sleep(1.4 if item[0] not in ("stall",) else 0.5)
        if a.status != "working":          # stopped mid-run
            return
        kind = item[0]
        if kind == "goal":
            set_goal(a, item[1], item[2], a.goal["max_turns"])
        elif kind == "feed":
            feed(a, item[1], item[2])
        elif kind == "ok":
            feed(a, item[1], "ok")
        elif kind == "step":
            set_step(a, item[1], item[2], relay_db.utc_now() if item[2] == "d" else "")
            bump_turn(a)
        elif kind == "say":
            say(a, item[1], item[2])
        elif kind == "appr":
            a.approval = {"cmd": item[1]}
            publish(a, {"type": "approval", "cmd": item[1]})
            set_status(a, "waiting")
            return
        elif kind == "stall":
            set_status(a, "stalled")
            return
        elif kind == "done":
            feed(a, "── " + item[1] + " ──", "wr")
            set_status(a, "done")
            return


async def watchdog_loop():
    """Flag agents that go quiet with an unfinished goal."""
    while True:
        await asyncio.sleep(5)
        for a in AGENTS.values():
            if _native_openclaw(a):
                continue
            threshold = float(a.cfg.get("watchdog_seconds") or WATCHDOG_SECONDS)
            quiet = time.time() - a.last_activity
            if a.status == "working" and quiet > threshold:
                set_status(a, "stalled")
                feed(a, f"!! no output for {int(quiet)}s · watchdog tripped", "wr")
            elif a.status == "stalled" and quiet > threshold * 3:
                feed(a, "!! still stalled · this goal needs a fix, not a poke", "wr")
                a.last_activity = time.time()   # nag every 3x threshold


# ----------------------------------------------------------------- api ----
app = FastAPI(title="relay")
app.mount("/static", StaticFiles(directory=STATIC), name="static")

# ---------------------------------------------------------------- auth ----
# Deny-by-default gate for /api/*. This is a pure-ASGI middleware rather than a
# per-route dependency on purpose: a dependency has to be remembered on every new
# route, and the one time it is forgotten the endpoint is silently public.
# Wrapping the app makes a route added later private until it is deliberately
# opened, and it leaves streaming responses unwrapped.
AUTH_TOKEN = relay_auth.load_token(ROOT)
AUTH_ENABLED = bool(AUTH_TOKEN)
AUTH_OPEN_PATHS = frozenset({"/api/auth", "/api/unlock"})


def _headers_from_scope(scope) -> dict:
    return {
        k.decode("latin-1").lower(): v.decode("latin-1")
        for k, v in scope.get("headers", [])
    }


def _authorized(headers: dict) -> bool:
    bearer = relay_auth.bearer_from_header(headers.get("authorization", ""))
    if relay_auth.token_matches(bearer, AUTH_TOKEN):
        return True
    cookie = relay_auth.cookie_from_header(headers.get("cookie", ""))
    return relay_auth.cookie_matches(cookie, AUTH_TOKEN)


class AuthGate:
    """Refuse anything under /api/ that presents neither the token nor its cookie."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http" or not AUTH_ENABLED:
            return await self.app(scope, receive, send)
        path = scope.get("path", "")
        if not path.startswith("/api/") or path in AUTH_OPEN_PATHS:
            return await self.app(scope, receive, send)
        if _authorized(_headers_from_scope(scope)):
            return await self.app(scope, receive, send)
        response = JSONResponse(
            {"auth_required": True, "error": "Relay needs an access token."},
            status_code=401,
        )
        return await response(scope, receive, send)


app.add_middleware(AuthGate)


@app.get("/api/auth")
def auth_status(request: Request):
    return JSONResponse({
        "auth_enabled": AUTH_ENABLED,
        "authed": _authorized(_headers_from_scope(request.scope)),
    })


@app.post("/api/unlock")
async def unlock(request: Request):
    try:
        body = await request.json()
    except Exception:
        body = {}
    candidate = str((body or {}).get("token") or "")
    if not AUTH_ENABLED or not relay_auth.token_matches(candidate, AUTH_TOKEN):
        return JSONResponse(
            {"ok": False, "error": "that access token does not match"},
            status_code=401,
        )
    forwarded = request.headers.get("x-forwarded-proto", "")
    resp = JSONResponse({"ok": True})
    resp.headers["Set-Cookie"] = relay_auth.session_cookie(
        AUTH_TOKEN,
        secure=(request.url.scheme == "https" or forwarded.lower() == "https"),
    )
    return resp


@app.post("/api/lock")
def lock():
    resp = JSONResponse({"ok": True})
    resp.headers["Set-Cookie"] = relay_auth.clear_cookie()
    return resp


# --------------------------------------------------------------- health ----
# Phase 0.9. Deliberately gated like everything else under /api/: it names paths,
# row counts and backup state, which is not information for an unauthenticated
# caller. The point of this endpoint is to be *true*, not pretty - it reports what
# it can observe and says "unknown" rather than guessing.
STARTED_AT = time.time()
BACKUP_STATUS = ROOT / ".private" / "backup-status.json"
BACKUP_STALE_AFTER_HOURS = 36


def _dir_bytes(path: Path) -> int:
    if not path.exists():
        return 0
    if path.is_file():
        return path.stat().st_size
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())


def _backup_health() -> dict:
    if not BACKUP_STATUS.is_file():
        return {"state": "never", "ok": False, "detail": "no backup has ever run"}
    try:
        st = json.loads(BACKUP_STATUS.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"state": "unreadable", "ok": False, "detail": f"{type(exc).__name__}: {exc}"}
    age_hours = None
    try:
        from datetime import datetime, timezone
        at = datetime.fromisoformat(st["at"])
        if at.tzinfo is None:
            at = at.replace(tzinfo=timezone.utc)
        age_hours = round((datetime.now(timezone.utc) - at).total_seconds() / 3600, 1)
    except Exception:
        pass
    ok = bool(st.get("ok")) and age_hours is not None and age_hours <= BACKUP_STALE_AFTER_HOURS
    return {
        "state": "fresh" if ok else ("failed" if not st.get("ok") else "stale"),
        "ok": ok,
        "at": st.get("at"),
        "age_hours": age_hours,
        "stale_after_hours": BACKUP_STALE_AFTER_HOURS,
        "set": st.get("set"),
        "dest": st.get("dest"),
        "bytes": st.get("bytes"),
        "rows": st.get("row_counts"),
        "error": st.get("error"),
    }


@app.get("/api/attachments/{att_id}")
def get_attachment(att_id: str):
    """Serve an artefact an agent produced. Gated like everything under /api/.

    This is what turns "the report is at D:\\..." into something the operator can
    actually open - including from a phone, which is the whole point. Relay is the
    origin the phone already talks to, so the bytes never need a path the phone
    cannot reach.
    """
    if not re.fullmatch(r"[0-9a-f]{64}", att_id or ""):
        return JSONResponse({"error": "unknown attachment"}, status_code=404)
    home = ATTACHMENT_STORE / att_id[:2] / att_id
    meta_file = home / "meta.json"
    if not meta_file.is_file():
        return JSONResponse({"error": "unknown attachment"}, status_code=404)
    try:
        meta = json.loads(meta_file.read_text(encoding="utf-8"))
    except Exception:
        return JSONResponse({"error": "unreadable attachment metadata"}, status_code=500)
    path = home / str(meta.get("file") or "")
    if not path.is_file():
        return JSONResponse({"error": "attachment bytes are missing"}, status_code=410)

    name = str(meta.get("name") or "attachment").replace('"', "")
    mime = str(meta.get("type") or "application/octet-stream")
    headers = {
        "X-Content-Type-Options": "nosniff",
        "Content-Disposition": f'inline; filename="{name}"',
        # Content-addressed, so this is safe to hold forever and cheap to re-read.
        "Cache-Control": "private, max-age=31536000, immutable",
    }
    # Agent-authored documents are untrusted content. `sandbox` gives the document an
    # opaque origin, so its scripts cannot reach /api/* with the operator's cookie -
    # while CSS, <details> and ordinary rendering all keep working. The report format
    # this exists for needs no JavaScript at all, so the guard costs nothing.
    # Note: allow-popups-to-escape-sandbox is deliberately NOT set; a popup inherits
    # this sandbox, so it cannot shed the opaque origin by opening a new window.
    if mime in ("text/html", "application/xhtml+xml", "image/svg+xml"):
        headers["Content-Security-Policy"] = "sandbox allow-scripts allow-popups allow-downloads"
    return FileResponse(path, media_type=mime, headers=headers)


#: Retention threshold (1.10). The journal is append-only and nothing bounds it yet,
#: so health goes red above this rather than letting it grow unnoticed. When pruning
#: lands this stays as the "pruning is not keeping up" alarm.
JOURNAL_WARN_EVENTS = 200_000


@app.get("/api/health")
def health():
    db = SESSION_DB_PATH
    db_bytes = db.stat().st_size if db.is_file() else 0
    wal = db.with_name(db.name + "-wal")
    counts: dict = {}
    try:
        if db.is_file():
            con = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True, timeout=2)
            try:
                present = {r[0] for r in con.execute(
                    "select name from sqlite_master where type='table'")}
                for t in ("sessions", "messages", "activity", "active_sessions"):
                    if t in present:
                        counts[t] = con.execute(f'select count(*) from "{t}"').fetchone()[0]
                counts["_user_version"] = con.execute("pragma user_version").fetchone()[0]
            finally:
                con.close()
    except Exception as exc:
        counts = {"error": f"{type(exc).__name__}: {exc}"}

    disks = {}
    for label, target in (("database", db.parent), ("backups", Path(r"C:\RelayBackups"))):
        try:
            probe = target if target.exists() else target.anchor
            usage = shutil.disk_usage(str(probe))
            disks[label] = {
                "path": str(target),
                "free_bytes": usage.free,
                "total_bytes": usage.total,
                "free_pct": round(usage.free / usage.total * 100, 1) if usage.total else None,
            }
        except Exception as exc:
            disks[label] = {"path": str(target), "error": f"{type(exc).__name__}: {exc}"}

    log = ROOT / ".private" / "relay-run.log"
    backup = _backup_health()
    durability = SESSIONS.durability_stats()
    outbox = SESSIONS.outbox_counts()
    retention = SESSIONS.retention_stats()
    # 1.9: agent-side stores Relay can see but does not own.
    agent_stores = observe_agent_stores()
    agent_receipts = {}
    for _a in AGENTS.values():
        if _agent_state_stores(_a):
            agent_receipts[_a.id] = {
                "last_receipt_age_hours":
                    _receipt_age_hours(SESSIONS.latest_activity_by_kind(_a.id, "backup")),
                "max_age_hours": RECEIPT_MAX_AGE_HOURS,
            }
    agent_store_alerts = bool(config.get("agent_store_alerts", False))
    agents = []
    for a in AGENTS.values():
        snap = a.snapshot()
        conn = snap.get("connection")
        # Relay only knows what the transport actually reported. The Agent object has
        # no reachable attribute at all, so reporting `false` here would be inventing a
        # fact - which docs/precedence-rule.md forbids. Unknown is null, not false.
        reachable = None
        if isinstance(conn, str) and conn:
            reachable = conn not in ("disconnected", "unknown", "")
        agents.append({
            "id": a.id,
            "backend": a.backend,
            "status": a.status,
            "connection": conn or "unknown",
            "reachable": reachable,
        })
    degraded = []
    if not backup["ok"]:
        degraded.append(f"backup {backup['state']}")
    for d, info in disks.items():
        if info.get("free_pct") is not None and info["free_pct"] < 5:
            degraded.append(f"{d} disk {info['free_pct']}% free")
    if counts.get("error"):
        degraded.append("database unreadable")
    if isinstance(backup.get("rows"), dict):
        for t in ("messages", "sessions"):
            if t in backup["rows"] and t in counts and counts[t] < backup["rows"][t]:
                degraded.append(f"{t} fewer than the last backup")
    if not durability.get("schema_current", True):
        degraded.append(f"schema version {durability.get('schema_version')} "
                        f"(expected {durability.get('expected_schema_version')})")
    if outbox.get("dead"):
        degraded.append(f"{outbox['dead']} message(s) undeliverable")
    if (durability.get("journal_events") or 0) > JOURNAL_WARN_EVENTS:
        degraded.append(f"journal {durability['journal_events']} events "
                        f"(retention threshold {JOURNAL_WARN_EVENTS})")
    for store in retention["over_threshold"]:
        degraded.append(f"{store} over its retention bound")
    # Notification health (2.7). A configured channel whose last delivery failed is a
    # real degradation; having no channel configured yet is reported in the payload
    # instead, so a not-yet-built feature cannot mask a genuine failure elsewhere.
    notifications = notification_health()
    if notifications["any_channel_configured"] and notifications["last_failure"]:
        degraded.append("notification channel last delivery failed")
    # A *missing* agent-side store is unambiguously wrong, so it always degrades.
    # Staleness degrades only when the operator opts in via `agent_store_alerts`,
    # because otherwise shipping this would flip a previously-green screen red for
    # stores the receipt job has not observed yet -- an alarm nobody asked for, which
    # is how real alarms come to be ignored. The state is reported either way.
    for entry in agent_stores:
        if entry["state"] == "missing":
            degraded.append(f"{entry['agent']} {entry['label']} is missing")
        elif agent_store_alerts and entry["state"] == "stale":
            degraded.append(f"{entry['agent']} {entry['label']} unchanged for "
                            f"{entry['age_hours']}h")
    if agent_store_alerts:
        for _aid, _info in agent_receipts.items():
            _age = _info["last_receipt_age_hours"]
            if _age is None:
                degraded.append(f"{_aid} has no agent-backup receipt")
            elif _age > RECEIPT_MAX_AGE_HOURS:
                degraded.append(f"{_aid} agent-backup receipt is {_age}h old")

    return JSONResponse({
        "ok": not degraded,
        "degraded": degraded,
        "service": {
            "uptime_seconds": round(time.time() - STARTED_AT, 1),
            "pid": os.getpid(),
            "auth_enabled": AUTH_ENABLED,
            "config": str(CONFIG_PATH),
        },
        "database": {
            "path": str(db), "bytes": db_bytes,
            "wal_bytes": wal.stat().st_size if wal.is_file() else 0,
            "rows": counts,
        },
        "disks": disks,
        "logs": {
            "relay_run_bytes": log.stat().st_size if log.is_file() else 0,
            "relay_run_previous_bytes": (
                log.with_name(log.name + ".1").stat().st_size
                if log.with_name(log.name + ".1").is_file() else 0),
            "relay_debug_bytes": (
                _debuglog.stat().st_size if _debuglog.is_file() else 0),
            "max_bytes": LOG_MAX_BYTES,
            "debug_rotation": LOG_ROTATION,
        },
        "backup": backup,
        # Phase 1.5: queue depth and journal size, so a stalled send or an unbounded
        # journal is visible on the health screen instead of only in the database.
        # `retrying` is reported but does NOT degrade: Relay cannot yet resolve an
        # interrupted send, and a permanently red screen would hide everything else.
        # `dead` does degrade -- that one is a definite failure.
        "durability": durability,
        "outbox": outbox,
        # Phase 1.10: one line per store, plus the policy that bounds it. A store with
        # no bound says so explicitly rather than being silently unbounded.
        "retention": retention,
        # Phase 1.9: what the agents' own memory stores look like from here. Relay
        # observes and records; it never writes to them and never claims their backups
        # worked, because it cannot see that.
        "agent_stores": agent_stores,
        "agent_store_receipts": agent_receipts,
        "agent_store_alerts": agent_store_alerts,
        # Phase 2.7: what Relay can honestly say about its own notification plane.
        "notifications": notifications,
        "agents": agents,
    })


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/api/agents")
def list_agents():
    snapshots = []
    for a in AGENTS.values():
        adapter = _native_openclaw(a)
        if adapter and adapter.snapshot:
            snapshots.append(_decorate_native_snapshot(a, adapter.snapshot))
        elif adapter:
            initial = a.snapshot()
            initial.update(status="waiting", connection="connecting")
            initial["capabilities"] = {"demo_fallback": False}
            snapshots.append(initial)
        else:
            snapshots.append(a.snapshot())
    return JSONResponse(snapshots)


async def _hermes_reachability(a: Agent) -> dict:
    """Confirm the gateway is alive and report what it advertises."""
    if a.is_a2a:
        # An A2A peer reports its own capability set; the absent features are
        # real absences, not probe failures.
        report = await asyncio.wait_for(_a2a_client(a).capabilities(), timeout=12)
        return report
    client = _hermes_client(a)
    probe = await asyncio.wait_for(client.probe(), timeout=12)
    features = probe.get("capabilities") or {}
    feature = HermesRunsClient._feature  # staticmethod: call on the class
    return {
        "transport": "hermes_runs",
        "reachable": True,
        "models": probe.get("models") or [],
        "runs_api": feature(features, "run_submission"),
        "run_stop": feature(features, "run_stop"),
        "run_approval": feature(features, "run_approval_response"),
        "run_steer": feature(features, "run_steer"),
        "tool_progress": feature(features, "tool_progress_events"),
        "sessions": feature(features, "session_resources"),
    }


async def _refresh_agent(a: Agent) -> dict:
    """Quietly pull confirmed goal/checklist state without messaging the agent."""
    adapter = _native_openclaw(a)
    if adapter:
        await asyncio.wait_for(adapter.call("heartbeat"), timeout=12)
        snapshot = _decorate_native_snapshot(a, adapter.snapshot or a.snapshot())
        return {"id": a.id, "ok": True, "source": "openclaw", "agent": snapshot}
    if a.backend == "openclaw":
        raise RuntimeError("OpenClaw adapter is unavailable")

    reachability = await _hermes_reachability(a)
    a.capabilities = reachability
    if a.is_a2a:
        return {"id": a.id, "ok": True, "source": "a2a", "agent": a.snapshot(),
                "capabilities": reachability,
                "note": "A2A gives chat, streaming, lifecycle, and stop; tool progress, "
                        "approvals, steering, and goals need an on-host bridge"}
    # A local Desktop state database is the only source of a real goal/checklist
    # for a Hermes agent; remote agents cannot expose it without a bridge.
    if _hermes_state_db(a) is not None:
        snapshot = await asyncio.to_thread(_read_hermes_desktop_goal, a)
        if snapshot:
            _apply_hermes_desktop_snapshot(a, snapshot)
        return {"id": a.id, "ok": True, "source": "hermes_desktop",
                "agent": a.snapshot(), "capabilities": reachability}
    return {"id": a.id, "ok": True, "source": "hermes_runs", "agent": a.snapshot(),
            "capabilities": reachability,
            "note": "goal/checklist telemetry needs an on-host bridge; chat, tools, "
                    "stop, and approvals are live"}


@app.post("/api/heartbeat")
async def heartbeat():
    """Refresh every configured agent when a phone opens or foregrounds Relay."""
    async def one(a: Agent) -> dict:
        try:
            return await _refresh_agent(a)
        except Exception as exc:
            _dbg(a.id, f"heartbeat refresh failed: {type(exc).__name__}: {exc}")
            adapter = _native_openclaw(a)
            current = (_decorate_native_snapshot(a, adapter.snapshot)
                       if adapter and adapter.snapshot else a.snapshot())
            return {"id": a.id, "ok": False, "source": a.backend,
                    "agent": current, "error": str(exc),
                    "capabilities": getattr(a, "capabilities", {})}

    results = await asyncio.gather(*(one(a) for a in AGENTS.values()))
    return JSONResponse({"ok": True, "agents": results, "refreshed_at": time.time()})


@app.get("/api/agents/{aid}/stream")
async def stream(aid: str, request: Request):
    a = AGENTS[aid]
    adapter = _native_openclaw(a)
    if adapter:
        async def native_gen():
            iterator = adapter.events().__aiter__()
            pending = asyncio.create_task(anext(iterator))
            try:
                while True:
                    ready, _ = await asyncio.wait({pending}, timeout=15)
                    if not ready:
                        yield ": relay-heartbeat\n\n"
                        continue
                    try:
                        ev = pending.result()
                    except StopAsyncIteration:
                        return
                    pending = asyncio.create_task(anext(iterator))
                    if ev.get("type") == "snapshot" and ev.get("agent"):
                        ev = {**ev, "agent": _decorate_native_snapshot(a, ev["agent"])}
                    yield f"data: {json.dumps(ev)}\n\n"
            finally:
                if not pending.done():
                    pending.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await pending

        return StreamingResponse(native_gen(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache",
                                          "X-Accel-Buffering": "no"})

    q = asyncio.Queue(maxsize=500)
    # Subscribe BEFORE reading the journal. The other order leaves a window in which
    # an event is published after the replay read but before the subscription exists,
    # and it is delivered by neither -- the exact silent loss this phase removes.
    a.subs.append(q)

    last_seen: int | None = None
    raw = (request.headers.get("last-event-id")
           or request.query_params.get("last_event_id"))
    if raw is not None and str(raw).strip():
        try:
            last_seen = int(str(raw).strip())
        except (TypeError, ValueError):
            last_seen = None

    replay: list[dict] = []
    gap_notice = None
    if last_seen is not None:
        try:
            span = SESSIONS.events_span()          # global watermark, not per-agent
            if not span["count"]:
                # Nothing was ever journaled: there is no history to resume from, so
                # treat the client as fresh rather than sending it silence.
                last_seen = None
            elif last_seen < span["min_seq"] - 1:
                # Events the client never saw have been pruned. Say so, then resync.
                gap_notice = {"type": "gap", "after": last_seen,
                              "oldest_available": span["min_seq"],
                              "newest": span["max_seq"]}
            else:
                replay = SESSIONS.events_since(a.id, last_seen)
        except Exception as exc:
            gap_notice = {"type": "gap", "after": last_seen,
                          "error": f"could not read the journal: {exc}"[:200]}

    def frame(ev: dict) -> str:
        head = f"id: {ev['seq']}\n" if isinstance(ev.get("seq"), int) else ""
        return f"{head}data: {json.dumps(ev)}\n\n"

    async def gen():
        # A fresh client gets a snapshot, which is the only way it can learn current
        # state. A resuming client gets exactly the events it missed -- and is told
        # plainly when those are no longer held, rather than being handed a shorter
        # history that looks complete.
        if last_seen is None:
            yield f"data: {json.dumps({'type': 'snapshot', 'agent': a.snapshot()})}\n\n"
        elif gap_notice:
            yield frame(gap_notice)
            yield f"data: {json.dumps({'type': 'snapshot', 'agent': a.snapshot()})}\n\n"

        highest = last_seen or 0
        try:
            for row in replay:
                highest = max(highest, int(row["seq"]))
                yield f"id: {row['seq']}\ndata: {json.dumps({'type': row['type'], **row['payload'], 'seq': row['seq']})}\n\n"
            while True:
                try:
                    ev = await asyncio.wait_for(q.get(), timeout=15)
                except asyncio.TimeoutError:
                    # Keep mobile browsers and tailnet intermediaries from
                    # silently expiring an otherwise idle event stream.
                    yield ": relay-heartbeat\n\n"
                    continue
                seq = ev.get("seq")
                if isinstance(seq, int) and seq <= highest:
                    continue          # already delivered by the replay
                if isinstance(seq, int):
                    highest = seq
                yield frame(ev)
        except asyncio.CancelledError:
            pass
        finally:
            if q in a.subs:
                a.subs.remove(q)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})


@app.get("/api/agents/{aid}/sessions")
def list_sessions(aid: str):
    if aid not in AGENTS:
        return JSONResponse({"ok": False, "error": "agent not found"}, status_code=404)
    sessions = SESSIONS.list(aid)
    # Phase 1.12: how much of each conversation is unseen. Additive field; the UI that
    # acts on it lands in Phase 3.
    for session in sessions:
        session["unread"] = SESSIONS.unread_count(aid, session["id"])
    return JSONResponse({"ok": True, "sessions": sessions})


@app.get("/api/agents/{aid}/sessions/{session_id}/messages")
def session_messages(aid: str, session_id: str, limit: int = 100,
                     before: int | None = None, after: int | None = None):
    """Cursor-paged transcript (1.5).

    Additive: the SSE snapshot still carries a recent window for the live view, and
    this is how a client reaches the rest of a long conversation instead of being
    silently capped at the newest page.
    """
    if aid not in AGENTS:
        return JSONResponse({"ok": False, "error": "agent not found"}, status_code=404)
    try:
        page = SESSIONS.messages_page(aid, session_id, limit=limit,
                                      before_id=before, after_id=after)
    except KeyError:
        return JSONResponse({"ok": False, "error": "conversation not found"},
                            status_code=404)
    return JSONResponse({"ok": True, "agent": aid, "session_id": session_id, **page})


@app.post("/api/agents/{aid}/sessions/{session_id}/read")
async def mark_session_read(aid: str, session_id: str, req: Request):
    """Record a conversation's read mark (1.12)."""
    if aid not in AGENTS:
        return JSONResponse({"ok": False, "error": "agent not found"}, status_code=404)
    body = {}
    with contextlib.suppress(Exception):
        body = await req.json()
    seq = body.get("seq") if isinstance(body, dict) else None
    try:
        mark = SESSIONS.mark_read(aid, session_id,
                                  int(seq) if seq is not None else None)
    except KeyError:
        return JSONResponse({"ok": False, "error": "conversation not found"},
                            status_code=404)
    except (TypeError, ValueError):
        return JSONResponse({"ok": False, "error": "seq must be an integer"},
                            status_code=400)
    return JSONResponse({"ok": True, "session_id": session_id,
                         "last_read_seq": mark,
                         "unread": SESSIONS.unread_count(aid, session_id)})


@app.get("/api/agents/{aid}/mcps")
async def list_mcps(aid: str):
    """MCP servers for one agent: the configured list plus what Relay can observe.

    Only a local Hermes install is inspectable. The report says which servers were
    observed running rather than claiming a connection Relay cannot see.
    """
    if aid not in AGENTS:
        return JSONResponse({"ok": False, "error": "agent not found"}, status_code=404)
    a = AGENTS[aid]
    if a.backend != "hermes":
        return JSONResponse(relay_mcp.unsupported(a.backend))
    db_path = _hermes_state_db(a)
    if db_path is None:
        return JSONResponse(relay_mcp.unsupported("hermes-remote"))
    config_path = Path(a.cfg.get("hermes_config") or (db_path.parent / "config.yaml"))
    if not config_path.is_file():
        return JSONResponse({"ok": True, "supported": True, "observe": "config", "servers": [],
                             "note": f"no Hermes config at {config_path}"})
    # PowerShell process query is blocking; keep it off the event loop.
    report = await asyncio.to_thread(relay_mcp.inventory, config_path)
    return JSONResponse(report)


@app.get("/api/agents/{aid}/activity")
def list_activity(aid: str, limit: int = 200, before: int | None = None):
    """Durable record of what this agent did: tools, runs, approvals, delegations.

    Unlike the live feed, this survives a Relay restart, so it is the thing to
    review after something went wrong.
    """
    if aid not in AGENTS:
        return JSONResponse({"ok": False, "error": "agent not found"}, status_code=404)
    rows = SESSIONS.activity(aid, limit=limit, before_id=before)
    return JSONResponse({
        "ok": True,
        "agent": aid,
        "count": SESSIONS.activity_count(aid),
        "returned": len(rows),
        "activity": rows,
    })


@app.get("/api/agents/{aid}/outbox")
def list_outbox(aid: str, limit: int = 50):
    """Send receipts (1.2/1.4): what Relay actually knows about each outbound message.

    A new route rather than extra fields on the send response, so the browser-facing
    contract is untouched. The states are admission facts only: `accepted` means a
    transport took the message, and Relay never reports "delivered" because it cannot
    observe another agent's inbox.
    """
    if aid not in AGENTS:
        return JSONResponse({"ok": False, "error": "agent not found"}, status_code=404)
    try:
        rows = SESSIONS.outbox_recent(aid, limit=limit)
        counts = SESSIONS.outbox_counts()
    except Exception as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=503)
    return JSONResponse({
        "ok": True,
        "agent": aid,
        "counts": counts,
        "recovered_at_startup": RECOVERED_SENDS,
        "receipts": [{"idem_key": row["idem_key"], **_receipt(row)} for row in rows],
    })


@app.get("/api/notifications")
def list_notifications(agent: str | None = None, limit: int = 50,
                       unread: bool = False, states: str = "inbox"):
    """The durable notification inbox (2.6): always written, never dropped.

    This is the record of truth for "was I told?", and it is what makes a total channel
    failure visible instead of silent.
    """
    include = tuple(part for part in str(states or "inbox").split(",") if part)
    rows = SESSIONS.notifications_list(agent, limit=limit, unread_only=unread,
                                       include_states=include or ("inbox",))
    return JSONResponse({"ok": True, "notifications": rows,
                         "counts": SESSIONS.notification_counts(),
                         "health": notification_health()})


@app.post("/api/notifications/read")
async def read_notifications(req: Request):
    """Mark the inbox read, all of it or a named subset."""
    body = {}
    with contextlib.suppress(Exception):
        body = await req.json()
    agent = body.get("agent") if isinstance(body, dict) else None
    ids = body.get("ids") if isinstance(body, dict) else None
    try:
        changed = SESSIONS.notifications_mark_read(agent, ids=ids)
    except Exception as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)
    return JSONResponse({"ok": True, "marked": changed,
                         "counts": SESSIONS.notification_counts()})


@app.get("/api/notifications/vapid")
def notification_vapid_key():
    """The public key a client needs to create a restricted subscription (RFC 8292 §4.1).

    Returned whenever a signing key exists, with `enabled` saying whether anything will
    actually be sent. Subscribing while it is disabled is not broken, just early.
    """
    notify = (config.get("notify") or {}).get("webpush") or {}
    key, subject = relay_channels.load_vapid_key(ROOT, notify)
    if key is None:
        return JSONResponse({"ok": False,
                             "error": "push signing key is not configured"},
                            status_code=503)
    return JSONResponse({
        "ok": True,
        "enabled": bool(notify.get("enabled")),
        "public_key": relay_webpush.b64url_encode(
            relay_webpush.public_bytes(key.public_key())),
        "subject": subject,
        "devices": SESSIONS.push_subscription_counts(),
    })


@app.post("/api/notifications/subscribe")
async def subscribe_push(req: Request):
    """Register a device for push (2.6).

    Validated hard at subscribe time. An endpoint Relay will POST to is a *capability*,
    so a bad one is refused here with a clear reason rather than failing at 3am inside a
    notification -- and the endpoint check is what stops a stored subscription pointing
    the notification plane at the operator's own network.
    """
    body = {}
    with contextlib.suppress(Exception):
        body = await req.json()
    if not isinstance(body, dict):
        return JSONResponse({"ok": False, "error": "expected a JSON object"},
                            status_code=400)

    keys = body.get("keys") if isinstance(body.get("keys"), dict) else {}
    try:
        endpoint = relay_channels.validate_push_endpoint(
            str(body.get("endpoint") or "").strip())
    except ValueError as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)

    p256dh = str(keys.get("p256dh") or "").strip()
    auth = str(keys.get("auth") or "").strip()
    try:
        point = relay_webpush.b64url_decode(p256dh)
        secret = relay_webpush.b64url_decode(auth)
    except Exception:
        return JSONResponse({"ok": False, "error": "keys are not valid base64url"},
                            status_code=400)
    if len(point) != 65 or point[0] != 0x04:
        return JSONResponse(
            {"ok": False, "error": "p256dh must be an uncompressed P-256 point"},
            status_code=400)
    if len(secret) != 16:
        return JSONResponse({"ok": False, "error": "auth must be 16 octets"},
                            status_code=400)

    try:
        row = SESSIONS.push_subscription_add(endpoint, p256dh, auth,
                                            device=str(body.get("device") or ""))
    except Exception as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=503)

    notify = (config.get("notify") or {}).get("webpush") or {}
    return JSONResponse({"ok": True, "id": row["id"], "device": row["device"],
                         "enabled": bool(notify.get("enabled")),
                         "devices": SESSIONS.push_subscription_counts()})


@app.post("/api/notifications/test")
async def test_notification(req: Request):
    """Raise a real notification through the whole plane, so a channel can be proven.

    Every notification system needs this. Without it the only way to find out whether
    your phone will actually ring is to wait for something to genuinely go wrong -- and
    then discover it does not work at the worst possible moment.

    It goes through the normal path (policy, inbox, channels), so what it proves is the
    real thing rather than a special case that only tests well.
    """
    body = {}
    with contextlib.suppress(Exception):
        body = await req.json()
    body = body if isinstance(body, dict) else {}
    agent_id = str(body.get("agent") or "").strip() or next(iter(AGENTS), "")
    agent = AGENTS.get(agent_id)
    if agent is None:
        return JSONResponse({"ok": False, "error": f"unknown agent {agent_id!r}"},
                            status_code=404)
    try:
        result = NOTIFIER.notify(
            agent_id, str(body.get("category") or "approval").strip().lower(),
            title="Test notification",
            body="sent from Relay to prove the notification path works",
            session_id=agent.conversation_id)
    except ValueError as exc:                     # unknown category
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)
    return JSONResponse({"ok": True, "agent": agent_id, "result": result,
                         "health": notification_health()})


@app.get("/api/activity")
def list_all_activity(limit: int = 200):
    """Activity across every agent, newest first."""
    merged: list[dict] = []
    for aid in AGENTS:
        for row in SESSIONS.activity(aid, limit=limit):
            row["agent_id"] = aid
            merged.append(row)
    merged.sort(key=lambda r: r["id"], reverse=True)
    return JSONResponse({"ok": True, "activity": merged[:max(1, min(limit, 1000))]})


async def _activate_session(a: Agent, session_id: str):
    async with SESSION_SWITCH_LOCKS[a.id]:
        current = SESSIONS.active(a.id)
        target = SESSIONS.get(a.id, session_id)
        if current["id"] == target["id"]:
            return target
        if _busy(a):
            raise RuntimeError("wait for the current run to finish before switching conversations")
        if a.backend == "openclaw":
            session_key = target.get("backend_key")
            if not session_key:
                raise RuntimeError("this Tripp conversation has no native session key")
            replacement = _openclaw_adapter(a, session_key)
            await replacement.start()
            previous = OPENCLAW_ADAPTERS.get(a.id)
            OPENCLAW_ADAPTERS[a.id] = replacement
            SESSIONS.activate(a.id, session_id)
            a.conversation_id = session_id
            if previous:
                await previous.close()
        else:
            SESSIONS.activate(a.id, session_id)
            _load_local_conversation(a, session_id)
        return target


@app.post("/api/agents/{aid}/sessions")
async def create_session(aid: str, req: Request):
    if aid not in AGENTS:
        return JSONResponse({"ok": False, "error": "agent not found"}, status_code=404)
    a = AGENTS[aid]
    if _busy(a):
        return JSONResponse(
            {"ok": False, "error": "wait for the current run to finish before starting a new conversation"},
            status_code=409,
        )
    body = await req.json()
    title = str(body.get("title") or "New conversation").strip()[:80] or "New conversation"
    backend_key = None
    if a.backend == "openclaw":
        base = a.cfg.get("session_key", f"agent:{aid}:relay")
        backend_key = f"{base}:{uuid.uuid4().hex[:12]}"
    created = SESSIONS.create(aid, title=title, backend_key=backend_key, activate=False)
    try:
        await _activate_session(a, created["id"])
    except Exception as exc:
        return _api_error(exc)
    return JSONResponse({"ok": True, "session": created})


@app.post("/api/agents/{aid}/sessions/{session_id}/activate")
async def activate_session(aid: str, session_id: str):
    if aid not in AGENTS:
        return JSONResponse({"ok": False, "error": "agent not found"}, status_code=404)
    try:
        session = await _activate_session(AGENTS[aid], session_id)
    except KeyError:
        return JSONResponse({"ok": False, "error": "conversation not found"}, status_code=404)
    except Exception as exc:
        return _api_error(exc)
    return JSONResponse({"ok": True, "session": session})


@app.post("/api/agents/{aid}/message")
async def message(aid: str, req: Request):
    a = AGENTS[aid]
    body = await req.json()
    if a.backend == "mesh":
        return await MESH_LINK.message(a, body, req.headers.get("x-mesh-intent", ""))
    text = str(body.get("text", "")).strip()
    try:
        attachments = _parse_attachments(body.get("files"))
    except ValueError as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)
    if not text and not attachments:
        return JSONResponse({"ok": False, "error": "write a message or attach a file"}, status_code=400)
    message_id = body.get("id")
    if not isinstance(message_id, str) or not message_id.strip():
        return JSONResponse(
            {"ok": False, "error": "refresh Relay before sending; a stable message id is required"},
            status_code=400,
        )
    message_id = message_id.strip()
    display_text = text or "Please review the attached files."
    async with MESSAGE_LOCKS[aid]:
        # Durable idempotency first (1.2). `a.message_ids` below is in memory only, so
        # before this a replayed POST after a Relay restart was accepted a second time
        # and sent twice. The response shape is deliberately unchanged: the PWA reads
        # this exact object, and receipts belong on their own endpoint rather than
        # bolted onto a contract the browser already relies on.
        try:
            existing = SESSIONS.outbox_get(message_id)
        except Exception:
            existing = None
        if existing is not None:
            return JSONResponse({"ok": True, "duplicate": True})
        if message_id in a.message_ids:
            return JSONResponse({"ok": True, "duplicate": True})

        adapter = _native_openclaw(a)
        if adapter:
            try:
                result = await adapter.call(
                    "send", id=message_id, text=text, files=[{
                        "name": item["name"], "type": item["type"], "data": item["data"],
                    } for item in attachments],
                )
            except Exception as exc:
                return _api_error(exc)
            _remember_message(a, message_id)
            SESSIONS.touch(a.id, a.conversation_id, display_text)
            return JSONResponse({"ok": True, "result": result})
        if a.backend == "openclaw":
            return JSONResponse(
                {"ok": False, "error": "Tripp native adapter is unavailable; demo fallback is disabled"},
                status_code=503,
            )

        if a.goal_control_task and not a.goal_control_task.done():
            return JSONResponse(
                {"ok": False, "error": f"{a.name} is continuing the Desktop goal; pause it before sending another message"},
                status_code=409,
            )

        # Own delivery order. A burst is acknowledged quickly, shown once, and
        # then drained to Hermes one run at a time. Hermes owns the transcript.
        was_busy = a.running()
        if not was_busy:
            a.goal = {"text": a.goal["text"], "steps": [], "turns": 0,
                      "max_turns": a.goal["max_turns"]}
        # Persist the intent BEFORE anything can dispatch it. This is the rule that
        # makes a crash mid-send survivable: the message is already a durable row, so
        # a restart can say what became of it instead of having no record at all.
        try:
            SESSIONS.outbox_enqueue(a.id, a.conversation_id, display_text,
                                    attachments=attachments, idem_key=message_id)
        except Exception as exc:
            return JSONResponse(
                {"ok": False,
                 "error": f"could not record the message before sending it: {exc}"},
                status_code=503)
        say(a, "you", display_text, attachments)
        a.message_queue.append((display_text, attachments, message_id))
        _remember_message(a, message_id)
        if not was_busy:
            a.run_task = asyncio.create_task(drain_hermes_messages(a))
        return JSONResponse({"ok": True, "queued": len(a.message_queue)})


@app.post("/api/agents/{aid}/stop")
async def stop(aid: str):
    a = AGENTS[aid]
    adapter = _native_openclaw(a)
    if adapter:
        try:
            return JSONResponse({"ok": True, "result": await adapter.call("stop")})
        except Exception as exc:
            return _api_error(exc)
    if a.backend == "openclaw":
        return JSONResponse(
            {"ok": False, "error": "Tripp native adapter is unavailable; no stop was reported"},
            status_code=503,
        )

    if a.is_a2a:
        # A2A has no interrupt; tasks/cancel is the native cancellation primitive.
        task_id = a.a2a_task_id or ""
        if not task_id:
            a.message_queue.clear()
            set_status(a, "stopped")
            return JSONResponse({"ok": True, "task_id": "", "result": "nothing running"})
        try:
            result = await _a2a_client(a).cancel(task_id)
        except Exception as exc:
            _dbg(a.id, f"A2A cancel failed: {type(exc).__name__}: {exc}")
            feed(a, f"!! cancel could not be confirmed with {a.name}: {exc}", "wr")
            return _api_error(exc)
        feed(a, "── cancel requested · waiting for the peer to confirm ──", "wr")
        return JSONResponse({"ok": True, "task_id": task_id, "result": result})

    # Interrupt on the agent, not just on Relay's local HTTP read loop. Without
    # this the turn kept running server-side after the UI said "stopped".
    run_id = _hermes_run_id(a)
    result: dict = {}
    if run_id:
        try:
            result = await _hermes_client(a).stop_run(run_id)
        except Exception as exc:
            _dbg(a.id, f"native stop failed: {type(exc).__name__}: {exc}")
            feed(a, f"!! stop could not be confirmed with {a.name}: {exc}", "wr")
            return _api_error(exc)
    # The driving task still owns the run: it will observe the terminal event
    # and settle. Do not clear active_run_ids here or the terminal event is lost.
    a.message_queue.clear()
    a.approval = None
    publish(a, {"type": "approval", "cmd": None})
    set_status(a, "stopped")
    feed(a, "── stopped by you · Hermes run interrupted ──", "wr")
    return JSONResponse({"ok": True, "run_id": run_id, "result": result})


@app.post("/api/agents/{aid}/goal/control")
async def goal_control(aid: str, req: Request):
    """Pause, resume, or clear a mirrored Hermes Desktop goal."""
    if aid not in AGENTS:
        return JSONResponse({"ok": False, "error": "agent not found"}, status_code=404)
    a = AGENTS[aid]
    body = await req.json()
    action = str(body.get("action") or "").strip().lower()
    if action not in {"pause", "resume", "delete"}:
        return JSONResponse({"ok": False, "error": "invalid goal action"}, status_code=400)
    if a.backend != "hermes" or a.goal.get("source") != "hermes_desktop":
        return JSONResponse(
            {"ok": False, "error": "this goal does not expose native controls"},
            status_code=409,
        )
    session_id = str(a.desktop_session_id or "").strip()
    if not session_id:
        return JSONResponse({"ok": False, "error": "Hermes Desktop session is unavailable"}, status_code=409)

    async with GOAL_CONTROL_LOCKS[aid]:
        try:
            if action == "resume" and a.goal_control_task and not a.goal_control_task.done():
                raise RuntimeError("A goal continuation is already running")
            prompt = await asyncio.to_thread(_control_hermes_desktop_goal, a, session_id, action)
            snapshot = await asyncio.to_thread(_read_hermes_desktop_goal, a)
            if snapshot:
                a.desktop_session_id = snapshot.get("session_id") or session_id
                if snapshot.get("goal") is None:
                    a.goal = {"text": "", "steps": [], "turns": 0,
                              "max_turns": a.cfg.get("max_turns", 60)}
                    publish(a, {"type": "goal", "goal": a.goal})
                    set_status(a, "idle")
                else:
                    a.goal = snapshot["goal"]
                    publish(a, {"type": "goal", "goal": a.goal})
                    set_status(a, snapshot["status"])
            if action == "resume" and prompt:
                set_status(a, "working")
                a.goal_control_task = asyncio.create_task(
                    _continue_hermes_desktop_goal(a, session_id, prompt)
                )
            return JSONResponse({"ok": True, "action": action, "goal": a.goal})
        except Exception as exc:
            _dbg(a.id, f"goal control failed: {type(exc).__name__}: {exc}")
            return _api_error(exc)


@app.post("/api/agents/{aid}/nudge")
async def nudge(aid: str, req: Request):
    a = AGENTS[aid]
    adapter = _native_openclaw(a)
    if adapter:
        body = await req.json()
        message_id = body.get("id")
        if not isinstance(message_id, str) or not message_id.strip():
            return JSONResponse({"ok": False, "error": "stable nudge id required"}, status_code=400)
        try:
            return JSONResponse({"ok": True, "result": await adapter.call("nudge", id=message_id)})
        except Exception as exc:
            return _api_error(exc)
    if a.backend == "openclaw":
        return JSONResponse(
            {"ok": False, "error": "Tripp native adapter is unavailable; nudge was not sent"},
            status_code=503,
        )

    if a.is_a2a:
        # A2A has no steering, so a nudge is an ordinary follow-up turn. Say so
        # rather than implying the live task was redirected.
        return JSONResponse(
            {"ok": False,
             "error": "A2A has no mid-task steering; send a normal message to continue "
                      "the conversation instead"},
            status_code=409,
        )

    # Prefer a real mid-run steer; fall back to a new turn when nothing is live.
    run_id = _hermes_run_id(a)
    if run_id:
        try:
            await _hermes_client(a).steer_run(run_id, "continue")
        except HermesError as exc:
            _dbg(a.id, f"steer rejected: {exc}")
            return _api_error(exc)
        feed(a, "$ nudge · steering the live run", "dm")
        set_status(a, "working")
        return JSONResponse({"ok": True, "steered": True, "run_id": run_id})
    if a.status == "stalled":
        set_status(a, "working")
        feed(a, "$ nudge · continuing", "dm")
        if a.cfg.get("demo_fallback", False):
            a.run_task = asyncio.create_task(demo_run(a, "continue"))
    return JSONResponse({"ok": True})


@app.post("/api/agents/{aid}/approve")
async def approve(aid: str, req: Request):
    a = AGENTS[aid]
    body = await req.json()
    adapter = _native_openclaw(a)
    if adapter:
        approval_id = body.get("id")
        if not isinstance(approval_id, str) or not approval_id.strip():
            return JSONResponse({"ok": False, "error": "exact pending approval id required"}, status_code=400)
        try:
            result = await adapter.call(
                "approve", id=approval_id, approved=bool(body.get("approved")),
                always=bool(body.get("always")),
            )
            return JSONResponse({"ok": True, "result": result})
        except Exception as exc:
            return _api_error(exc)
    if a.backend == "openclaw":
        return JSONResponse(
            {"ok": False, "error": "Tripp native adapter is unavailable; approval was not changed"},
            status_code=503,
        )

    if a.is_a2a:
        # A2A gives remote peers no operator surface, so there is nothing to
        # resolve. Refuse honestly instead of pretending an approval landed.
        return JSONResponse(
            {"ok": False,
             "error": "A2A peers expose no approval surface; this task cannot be approved "
                      "from Relay"},
            status_code=409,
        )

    # Resolve the approval on the agent, using Hermes' native choice vocabulary.
    # The old behaviour cleared a UI field and posted the literal text "y" as a
    # new message, which never actually resolved anything.
    run_id = _hermes_run_id(a)
    if not run_id:
        return JSONResponse(
            {"ok": False, "error": "no active run is waiting for approval"}, status_code=409
        )
    if body.get("approved"):
        choice = "always" if body.get("always") else ("session" if body.get("session") else "once")
    else:
        choice = "deny"
    request_id = str(body.get("id") or (a.approval or {}).get("id") or "").strip()
    try:
        result = await _hermes_client(a).approve_run(
            run_id, choice=choice, request_id=request_id
        )
    except HermesError as exc:
        _dbg(a.id, f"approval failed: {exc}")
        return _api_error(exc)
    resolved = int(result.get("resolved") or 0)
    if not resolved:
        return JSONResponse(
            {"ok": False, "error": "the agent reports no pending approval for that request"},
            status_code=409,
        )
    a.approval = None
    publish(a, {"type": "approval", "cmd": None})
    say(a, "you", choice)
    set_status(a, "working")
    return JSONResponse({"ok": True, "choice": choice, "resolved": resolved})


async def _demo_finish(a: Agent):
    """Finish cyony-style approval scripts in demo mode."""
    for line, cls in [("$ docker compose up -d relay-db", "dm"), ("✓ container up · healthy", "ok"),
                      ("$ python migrate.py", "dm"), ("✓ 1,204 sessions migrated", "ok")]:
        await asyncio.sleep(1.2)
        if a.status != "working":
            return
        feed(a, line, cls)
    if len(a.goal["steps"]) > 2:
        set_step(a, 2, "d", relay_db.utc_now())
        set_step(a, 3, "d", relay_db.utc_now())
    feed(a, "── goal achieved ──", "wr")
    set_status(a, "done")


def generate_digest(*, now=None) -> dict:
    """Fold suppressed notifications into one digest per agent (2.4).

    Two traps this exists to avoid, both of which are silent losses:

    1. **It must not run during quiet hours.** A digest is itself an aggregate category,
       so one generated at 02:00 would be suppressed and fold into a digest that is never
       sent -- the same dead end as the deferral bug, one layer up.
    2. **It must not fold rows whose digest was itself suppressed.** If the rate limit
       suppresses the digest, folding anyway would mark the held events as summarised
       when no summary was ever delivered. They stay held instead, and the next pass
       picks them up once the limit has passed.
    """
    now = now or datetime.now().astimezone()
    # Recorded on every pass, including the ones that do nothing. Without this the
    # health block reads `at: null` when nothing has been held, which is
    # indistinguishable from the step never running -- the same "ran and found nothing"
    # versus "never runs" ambiguity that made the deferral bug invisible for rounds.
    LAST_DIGEST["checked_at"] = relay_db.utc_now()
    if NOTIFIER.quiet and relay_notify.in_quiet_hours(now):
        LAST_DIGEST["last_reason"] = "quiet hours"
        return {"ok": False, "reason": "quiet hours"}
    rows = SESSIONS.notifications_foldable()
    if not rows:
        LAST_DIGEST["last_reason"] = "nothing held"
        return {"ok": False, "reason": "nothing held"}

    grouped: dict[str, list[dict]] = {}
    for row in rows:
        grouped.setdefault(str(row.get("agent_id") or ""), []).append(row)

    folded = 0
    digests = 0
    for agent_id, group in grouped.items():
        agent = AGENTS.get(agent_id)
        if agent is None:
            # No such agent any more: fold them rather than retrying forever, since
            # there is nobody left to tell.
            folded += SESSIONS.notifications_mark_folded([r["id"] for r in group])
            continue
        title, body = relay_notify.summarise(group)
        report = NOTIFIER.notify(agent_id, "digest", title=title, body=body,
                                 session_id=agent.conversation_id,
                                 dedup_key=f"digest:{agent_id}:{group[0]['id']}")
        if report.get("state") == "suppressed":
            continue          # keep them held; folding now would lose the summary
        folded += SESSIONS.notifications_mark_folded([r["id"] for r in group])
        digests += 1

    LAST_DIGEST.update({"at": relay_db.utc_now(), "held": len(rows),
                        "folded": folded, "digests": digests})
    return {"ok": True, "held": len(rows), "folded": folded, "digests": digests}


async def notification_loop():
    """Deliver notifications that quiet hours deferred, once their window has closed.

    Phase 2.4, and it exists because without it the deferral path was dead: a `waiting`
    notification suppressed at 02:00 was written as `deferred` and then delivered by
    nothing at all, which makes "deferred" indistinguishable from "deleted". The policy
    is explicit that silence must never be the failure mode, and a queue nobody drains
    is the quietest possible way to break that.
    """
    while True:
        try:
            due = SESSIONS.notifications_due()
            delivered = 0
            for note in due:
                if NOTIFIER.deliver_existing(note).get("ok"):
                    delivered += 1
            # Recorded so the loop is *observable*: "a background task exists" is not
            # evidence that it runs, and this project has been bitten by that before.
            LAST_DRAIN.update({"at": relay_db.utc_now(), "due": len(due),
                               "delivered": delivered})
            # Then fold whatever was held back into a digest.
            generate_digest()
        except Exception as exc:
            # Never let the drain take the server down; the rows stay `deferred` and the
            # next pass picks them up.
            print(f"[relay] notification drain failed: {exc}", file=sys.stderr)
            LAST_DRAIN["error"] = f"{type(exc).__name__}: {exc}"
        await asyncio.sleep(60)


@app.on_event("startup")
async def startup():
    global WATCHDOG_TASK, HERMES_DESKTOP_TASK, NOTIFICATION_TASK
    if config.get("mesh_only"):
        return  # No agent transports, notifications or watchdog in Mesh-only mode.
    WATCHDOG_TASK = asyncio.create_task(watchdog_loop())
    HERMES_DESKTOP_TASK = asyncio.create_task(hermes_desktop_loop())
    NOTIFICATION_TASK = asyncio.create_task(notification_loop())
    # Set RELAY_SKIP_OPENCLAW=1 to run the Hermes paths in isolation (used by the
    # end-to-end test, where the OpenClaw child process cannot be spawned).
    if os.environ.get("RELAY_SKIP_OPENCLAW") == "1":
        return
    for aid, a in AGENTS.items():
        if a.backend != "openclaw":
            continue
        if a.cfg.get("demo_fallback", True):
            raise RuntimeError(f"{aid}: OpenClaw demo_fallback must be false")
        session = SESSIONS.active(aid)
        session_key = session.get("backend_key") or a.cfg.get("session_key", f"agent:{aid}:relay")
        adapter = _openclaw_adapter(a, session_key)
        OPENCLAW_ADAPTERS[aid] = adapter
        await adapter.start()


@app.on_event("shutdown")
async def shutdown():
    global WATCHDOG_TASK, HERMES_DESKTOP_TASK, NOTIFICATION_TASK
    for adapter in OPENCLAW_ADAPTERS.values():
        with contextlib.suppress(Exception):
            await adapter.close()
    OPENCLAW_ADAPTERS.clear()
    for a in AGENTS.values():
        if a.hermes is not None:
            await a.hermes.aclose()
            a.hermes = None
    if WATCHDOG_TASK:
        WATCHDOG_TASK.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await WATCHDOG_TASK
        WATCHDOG_TASK = None
    if NOTIFICATION_TASK:
        NOTIFICATION_TASK.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await NOTIFICATION_TASK
        NOTIFICATION_TASK = None
    if HERMES_DESKTOP_TASK:
        HERMES_DESKTOP_TASK.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await HERMES_DESKTOP_TASK
        HERMES_DESKTOP_TASK = None


if __name__ == "__main__":
    # Loopback by default: Relay's own API has no authentication, so it must not
    # be reachable off-host. Publish it with `tailscale serve` when needed.
    uvicorn.run(app, host=config.get("host", "127.0.0.1"), port=config.get("port", 8787))
