"""Onoes-Mesh: disk-backed to-do, served only on 127.0.0.1:8771."""
import base64
import copy
import json
import importlib.util
import os
import sys
import threading
import time
import uuid
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs

import relay_chat
import relay_goal
import relay_media
import relay_proactive
import relay_push
import relay_sqlite_worker
import mesh_log

ROOT = Path(__file__).resolve().parent
# Reuse the preview collector without relying on cwd or PYTHONPATH.
_system_spec = importlib.util.spec_from_file_location(
    "mesh_system_dashboard", ROOT / "mesh-system-dashboard" / "system_dashboard.py")
system_dashboard = importlib.util.module_from_spec(_system_spec)
_system_spec.loader.exec_module(system_dashboard)
DATA = ROOT / "data"
STORE = DATA / "cards.json"
HANDOFF = DATA / "handoff.json"
SERVICE_TAG = "onoes-mesh"
SERVICE_ROLE = "web"
ALLOWED_HOSTS = {"127.0.0.1:8771", "127.0.0.1:8772", "emitchell.tail8c4a75.ts.net:8450"}
ALLOWED_ORIGINS = {"http://127.0.0.1:8771", "http://127.0.0.1:8772", "https://emitchell.tail8c4a75.ts.net:8450"}
LOCK = threading.RLock()

# -- proactive SSE (durable Echo->Eddie live delivery) ------------------------------
#
# This route is the *live* door for the one authorized proactive path: Echo -> Eddie
# in the one authorized room. It is GET-only and room-scoped, and it never exposes a
# publish/POST door — there is no way for a browser (or any HTTP client) to mint an
# Echo message through this server.
#
# Bounded by construction: a fixed number of concurrent connections, a bounded wait
# per cycle (so a heartbeat is sent on a real cadence), a bounded replay page per
# cycle, and a hard cap on total stream duration. No background thread, no timer
# outside the connection's own serve loop.
PROACTIVE_SSE_PATH = "/api/relay/proactive/stream"
PROACTIVE_SSE_MAX_CONNECTIONS = 8
PROACTIVE_SSE_MAX_SECONDS = 1800
PROACTIVE_SSE_WAIT_SECONDS = 20.0
PROACTIVE_SSE_HEARTBEAT_SECONDS = 15.0
PROACTIVE_SSE_MAX_PAGE = 200
_SSE_SLOTS = threading.Semaphore(PROACTIVE_SSE_MAX_CONNECTIONS)

# Opt-in Web Push (Task 2 slice): a read-only readiness probe plus a
# capability-gated enrollment door and a self-service revoke. Nothing here
# sends a push -- the delivery half stays fail-closed until the parent
# installs the dependency and provisions keys (see
# RELAY-WEB-PUSH-IMPLEMENTATION-RECEIPT.md).
PUSH_STATUS_PATH = "/api/relay/push/status"
PUSH_ENROLL_PATH = "/api/relay/push/enroll"
PUSH_REVOKE_PATH = "/api/relay/push/revoke"
PUSH_SEND_PATH = "/api/relay/push/send"
PUSH_SETUP_PATH = "/api/relay/push/setup"

# Opt-in Web Push (Task 2 slice). The store is a module attribute so an
# isolated test can point the real handler at a temporary database without
# touching the owner's file. Nothing here sends a push: the delivery half
# stays fail-closed until the parent installs the dependency and provisions
# keys (see RELAY-WEB-PUSH-IMPLEMENTATION-RECEIPT.md).
RELAY_PUSH_STORE = None
_PUSH_STORE_LOCK = threading.Lock()
PUSH_ENROLL_MAX_BYTES = 16384


def runtime_options(argv):
    """Parse the small, visible identity tag used by process inspections.

    The tag is deliberately carried in the command line as well as in health
    responses, so an agent inspecting Windows processes can distinguish Mesh
    from another Python service before stopping anything. Unknown options fail
    closed rather than being silently ignored.
    """
    port = 8771
    tag = SERVICE_TAG
    role = SERVICE_ROLE
    port_seen = False
    for argument in list(argv)[1:]:
        if argument.isdigit() and not port_seen:
            port = int(argument)
            port_seen = True
        elif argument.startswith("--mesh-service="):
            tag = argument.split("=", 1)[1]
        elif argument.startswith("--mesh-role="):
            role = argument.split("=", 1)[1]
        else:
            raise SystemExit("Unknown server option. Use PORT [--mesh-service=TAG] [--mesh-role=ROLE].")
    safe = lambda value: bool(value) and all(ch.isalnum() or ch in ".-_" for ch in value)
    if not safe(tag) or not safe(role):
        raise SystemExit("Mesh service tag and role must be safe non-empty tokens.")
    return port, tag, role


def push_store():
    """The one enrollment store, opened lazily on first use."""
    global RELAY_PUSH_STORE
    if RELAY_PUSH_STORE is None:
        with _PUSH_STORE_LOCK:
            if RELAY_PUSH_STORE is None:
                RELAY_PUSH_STORE = relay_push.PushStore()
    return RELAY_PUSH_STORE


def atomic_json(path, value):
    temp = path.with_suffix(".json.tmp")
    try:
        with temp.open("w", encoding="utf-8", newline="\n") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        if temp.exists():
            temp.unlink()


def read_state():
    with STORE.open(encoding="utf-8") as stream:
        return json.load(stream)


def sync_handoff(state):
    active = next((c for c in state["cards"] if not c["sample"] and c["state"] == "ready"), None)
    if active:
        atomic_json(HANDOFF, {"id": active["id"], "title": active["title"], "state": "ready"})
        return
    if not HANDOFF.exists():
        return
    previous = json.loads(HANDOFF.read_text(encoding="utf-8"))
    card = next((c for c in state["cards"] if c["id"] == previous.get("id")), None)
    if card and card["state"] == "paused":
        atomic_json(HANDOFF, {"id": card["id"], "title": card["title"], "state": "paused"})
        return
    HANDOFF.unlink()


def mark_finished(card):
    if card["state"] not in {"ready", "paused"}:
        raise ValueError("Only a card Echo is holding can be finished.")
    card.update(state="finished", line="finished")


def play_room(body):
    """Play stays in the server-selected room; a client cannot invent one."""
    selected = relay_chat.active_room() or relay_chat.SESSION_ID
    requested = body.get("session_id", selected)
    if not relay_chat.relay_store.valid_room(requested) or requested != selected:
        raise relay_chat.RelayChatError("Unknown room.", status=400)
    return selected


def start_card_turn(text, session_id):
    # Share the sender's lock so another send cannot slip between check and submit.
    with relay_chat._SUBMIT_LOCK:
        if relay_chat.STORE.active_run(session_id):
            return {"line": "working on this, next.", "session_id": session_id}
        try:
            started = relay_chat.submit(text, session_id=session_id)
            if not started.get("run_id"):
                raise ValueError("Submit returned no run id.")
        except Exception:
            # The hold is already durable. A sender failure must not undo it or
            # report the file save as a started run.
            return {"line": "start failed. Card stays ready.", "session_id": session_id}
        return {"line": "received, ready to operate", "run_id": started["run_id"],
                "session_id": session_id}


def initialize():
    DATA.mkdir(exist_ok=True)
    if not STORE.exists():
        seed = json.loads((ROOT / "seed.json").read_text(encoding="utf-8"))
        atomic_json(STORE, {"version": 1, "headers": seed["headers"], "cards": seed["cards"]})
    state = read_state()  # Never replace existing data on parse failure.
    ready = [c for c in state["cards"] if not c["sample"] and c["state"] == "ready"]
    if len(ready) > 1:
        raise RuntimeError("More than one live card is ready; repair cards.json before starting.")
    sync_handoff(state)  # Recover a handoff interrupted after cards.json was committed.


class Handler(BaseHTTPRequestHandler):
    def reply(self, status, payload, content_type="application/json; charset=utf-8"):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8") if content_type.startswith("application/json") else payload
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Mesh-Service", SERVICE_TAG)
        self.send_header("X-Mesh-Role", SERVICE_ROLE)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self'; img-src 'self' data:; object-src 'none'; frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(body)

    # -- proactive SSE: durable Echo->Eddie live delivery ---------------------------

    def _sse_field(self, name, value):
        """Write one SSE field. Newlines inside a value are split into separate
        ``data:`` lines, exactly as the spec requires, so a multi-line message body
        cannot smuggle extra fields or break the frame."""
        for line in str(value).split("\n"):
            self.wfile.write(f"{name}: {line}\n".encode("utf-8"))

    def _sse_comment(self, text):
        self.wfile.write(f": {text}\n\n".encode("utf-8"))

    def _sse_flush(self):
        self.wfile.flush()

    def _proactive_cursor(self):
        """The resume cursor for this stream: ``?last_seq`` if present, otherwise a
        ``Last-Event-ID`` header (how EventSource reconnects), otherwise -1 (the
        beginning of the durable log)."""
        query = parse_qs(self.path.split("?", 1)[1] if "?" in self.path else "", keep_blank_values=False)
        cursor = (query.get("last_seq") or [None])[0]
        if cursor is None:
            cursor = self.headers.get("Last-Event-ID") or "-1"
        try:
            return int(cursor)
        except (TypeError, ValueError):
            return -1

    def proactive_stream(self):
        """GET-only, room-scoped SSE stream for proactive messages.

        Contract (all enforced here, in the backend):

        * Room scope: the query's ``session`` must be exactly the one authorized
          room, or the request is refused with ``403`` before any stream starts.
          A whitespace-altered or look-alike room id is rejected, never repaired.
        * Resume: the cursor comes from ``?last_seq`` (or a ``Last-Event-ID``
          header) and is never used as a filter — it only says where to continue.
          A stale or already-seen cursor can never make a newer message look like
          an older one, because ordering is by the durable ``seq`` alone.
        * Replay: every cycle re-reads the durable log with a bounded page
          (``PROACTIVE_SSE_MAX_PAGE``) and emits each unseen event with its stable
          ``message_id`` as the SSE event id, so a client that missed a page
          reconnects and resumes without loss and without duplicates.
        * Bounded: a semaphore caps concurrent connections; every wait is a bounded
          ``Condition.wait`` (no timer, no polling loop); a heartbeat is written on
          a real cadence; and ``PROACTIVE_SSE_MAX_SECONDS`` caps total stream time.
        * No publish door: this is a read-only stream. Nothing here accepts, mints,
          or forwards an Echo message from an HTTP request.
        """
        # Refuse anything but the one authorized room, before any stream starts.
        query = parse_qs(self.path.split("?", 1)[1] if "?" in self.path else "", keep_blank_values=False)
        requested_room = (query.get("session") or [relay_proactive.ROOM])[0]
        if requested_room != relay_proactive.ROOM:
            self.reply(403, {"error": "Proactive contact is only authorized in the Eddie/Echo room."})
            return
        if not _SSE_SLOTS.acquire(blocking=False):
            self.reply(503, {"error": "Too many proactive streams. Retry shortly."})
            return
        try:
            # Bounded total stream lifetime. This is a hard cap, not a timer: the
            # loop simply checks the deadline each cycle and ends cleanly.
            deadline = time.monotonic() + PROACTIVE_SSE_MAX_SECONDS
            cursor = self._proactive_cursor()
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Connection", "close")
            self.end_headers()
            self._sse_comment("proactive stream open")
            self._sse_flush()
            last_beat = time.monotonic()
            while time.monotonic() < deadline:
                window = relay_proactive.read(last_seq=cursor, limit=PROACTIVE_SSE_MAX_PAGE)
                for event in window.get("events", []):
                    # Stable public identity: the durable message_id, never a rowid.
                    self._sse_field("id", event["message_id"])
                    self._sse_field("event", "message")
                    payload = {
                        "session_id": event["session_id"],
                        "seq": event["seq"],
                        "id": event["id"],
                        "message_id": event["message_id"],
                        "author": event["author"],
                        "recipient": event["recipient"],
                        "text": event["text"],
                        "created_at": event["created_at"],
                        "replayed": event.get("replayed", False),
                    }
                    self._sse_field("data", json.dumps(payload, ensure_ascii=False))
                    self.wfile.write(b"\n")
                    cursor = max(cursor, int(event["seq"]))
                if window.get("gap"):
                    # The client's cursor predates the oldest retained row. The
                    # durable log is the reconciliation path; say so explicitly so
                    # the client can do a history read rather than assume it saw
                    # everything.
                    self._sse_field("event", "gap")
                    self._sse_field("data", json.dumps({
                        "session_id": window.get("session_id", relay_proactive.ROOM),
                        "truncated_before": window.get("truncated_before", 0),
                    }, ensure_ascii=False))
                    self.wfile.write(b"\n")
                # Bounded wait: this wakes as soon as a publish signals the store,
                # or at the heartbeat cadence, whichever comes first. No polling
                # loop, no timer, no background thread.
                relay_proactive.wait_for_next(cursor, timeout=PROACTIVE_SSE_WAIT_SECONDS)
                now = time.monotonic()
                if now - last_beat >= PROACTIVE_SSE_HEARTBEAT_SECONDS:
                    self._sse_comment(f"heartbeat seq={cursor}")
                    last_beat = now
                self._sse_flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            # The client went away (tab closed, phone lost signal). Nothing to do:
            # the durable log keeps every message, and a reconnect resumes cleanly.
            pass
        finally:
            _SSE_SLOTS.release()

    def push_status(self):
        """Read-only readiness/enrollment state. Never returns a subscription.

        This is the endpoint the Settings page polls. It answers 200 even when
        nothing is provisioned, because "not ready yet" is a state the owner
        has to be able to see, not an error. ``vapid`` and ``enrollment`` name
        the two independent blockers so the UI can show them separately from
        source completion.
        """
        try:
            status = push_store().status()
        except OSError:
            self.reply(500, {"error": "The notification store is not readable on the PC."})
            return
        status["vapid"] = relay_push.vapid_ready()
        status["enrollment"] = bool(os.environ.get(relay_push.TOKEN_ENV, "").strip())
        status["ready"] = status["vapid"] and relay_push.cryptography_available()
        status["public_key"] = os.environ.get(relay_push.VAPID_PUBLIC_ENV, "") if status["ready"] else ""
        status["owner_setup"] = bool(os.environ.get("RELAY_PUSH_OWNER_LOGIN"))
        status["provider_hosts"] = sorted(relay_push.provider_hosts())
        status["permission_api"] = True
        self.reply(200, status)

    def push_setup(self):
        # Serve strips spoofed incoming identity headers and supplies the authenticated
        # tailnet login. Trust only the existing loopback proxy + exact private Host.
        # Same-account local processes remain a disclosed cooperative boundary.
        owner = os.environ.get("RELAY_PUSH_OWNER_LOGIN", "")
        identities = self.headers.get_all("Tailscale-User-Login", [])
        hosts = self.headers.get_all("Host", [])
        if (not owner or identities != [owner] or hosts != ["emitchell.tail8c4a75.ts.net:8450"]
                or self.client_address[0] != "127.0.0.1"):
            self.reply(403, {"error": "Use Eddie's authenticated private Tailscale connection for phone setup."})
            return
        self._read_json_body(1024)
        token = os.environ.get(relay_push.TOKEN_ENV, "")
        try:
            expiry, device = relay_push.parse_capability(token)
            if push_store().capability_used(token):
                raise relay_push.PushError("Phone setup was already used.", 403)
            relay_push.require_delivery_ready()
        except relay_push.PushError as error:
            self.reply(error.status, {"error": str(error)})
            return
        # No secrets in URL, history, file attachment or Telegram. Only the
        # authenticated owner's deliberate enable gesture requests this handoff.
        self.reply(200, {"capability": token, "device": device})

    def push_enroll(self):
        """One deliberate, capability-gated enrollment from the owner's phone.

        The request must carry the parent-issued one-use capability the PC set
        in its own environment; the browser cannot mint one. The capability is
        consumed before the subscription is inspected, so a rejected request
        still cannot be retried. No subscription material is ever echoed back
        or logged.
        """
        store = push_store()
        presented = self.headers.get("Authorization", "")
        if presented[:7].lower() == "bearer ":
            presented = presented[7:].strip()
        # Content type is checked before the body is read, so a non-JSON
        # request never reaches the JSON parser below.
        if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
            self.reply(415, {"error": "JSON required."})
            return
        body = self._read_json_body(PUSH_ENROLL_MAX_BYTES)
        device = body.get("device")
        subscription = body.get("subscription")
        if not isinstance(device, str) or not isinstance(subscription, dict):
            raise ValueError("This device has no owner enrollment. Setup is not ready.")
        # Identity comes first. A request with no capability is refused as
        # unauthorized, never as unprovisioned, so an unprovisioned PC cannot
        # be used to probe what a real enrollment would say.
        if not presented:
            self.reply(403, {"error": "This device has no owner enrollment. Setup is not ready."})
            return
        try:
            relay_push.require_delivery_ready()
        except relay_push.PushError as error:
            # Fail closed *before* burning the capability: setup is the
            # parent's job, and a half-ready install should not consume the
            # owner's one-use grant.
            self.reply(error.status, {"error": str(error)})
            return
        try:
            result = relay_push.enroll(store, device=device,
                                       capability=presented, subscription=subscription)
        except relay_push.PushError as error:
            self.reply(error.status, {"error": str(error)})
            return
        os.environ.pop(relay_push.TOKEN_ENV, None)
        self.reply(200, result)

    def push_revoke(self):
        """Revoke this device's enrollment.

        Deliberately *not* capability-gated: the phone that enrolled is the
        phone that un-enrolls, and the enrollment capability was already spent
        at enroll time. The device name must still match, so a stray tap on
        someone else's page cannot revoke the owner's phone.
        """
        if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
            self.reply(415, {"error": "JSON required."})
            return
        body = self._read_json_body(4096)
        device = body.get("device")
        if not isinstance(device, str) or not isinstance(body.get("subscription"), dict):
            raise ValueError("This browser must present its subscription to revoke.")
        try:
            result = push_store().revoke_by_subscription(device, body["subscription"])
        except relay_push.PushError as error:
            self.reply(error.status, {"error": str(error)})
            return
        self.reply(200, result)

    def _read_json_body(self, limit):
        if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
            raise ValueError("JSON required.")
        length = int(self.headers.get("Content-Length", "0"))
        if not 0 < length <= limit:
            raise ValueError("Request is empty or too large.")
        body = json.loads(self.rfile.read(length))
        if not isinstance(body, dict):
            raise ValueError("A JSON object is required.")
        return body

    def local_request(self):
        hosts = self.headers.get_all("Host", [])
        allowed_hosts = getattr(self, "ALLOWED_HOSTS", ALLOWED_HOSTS)
        if len(hosts) != 1 or hosts[0] not in allowed_hosts:
            self.reply(403, {"error": "Use http://127.0.0.1:8771/"})
            return False
        origins = self.headers.get_all("Origin", [])
        allowed_origins = getattr(self, "ALLOWED_ORIGINS", ALLOWED_ORIGINS)
        if len(origins) > 1 or (origins and origins[0] not in allowed_origins):
            self.reply(403, {"error": "Local page requests only."})
            return False
        return True

    def do_GET(self):
        if not self.local_request():
            return
        if self.path.split("?", 1)[0] == "/api/system/metrics":
            state = system_dashboard.collect_state()
            self.reply(200, {**state["metrics"], "llm": state["llm"]})
            return
        if self.path.split("?", 1)[0] == PUSH_STATUS_PATH:
            self.push_status()
            return
        if self.path.split("?", 1)[0] == PROACTIVE_SSE_PATH:
            self.proactive_stream()
            return
        if self.path.split("?", 1)[0] == "/api/mesh/log":
            try:
                limit = int(parse_qs(self.path.split("?", 1)[1] if "?" in self.path else "").get("limit", ["40"])[0])
            except ValueError:
                self.reply(400, {"error": "Limit must be 1 to 100."})
                return
            try:
                self.reply(200, {"events": mesh_log.recent(limit)})
            except ValueError as error:
                self.reply(400, {"error": str(error)})
            return
        if self.path == "/api/state":
            with LOCK:
                self.reply(200, read_state())
            return
        if self.path.split("?", 1)[0] == "/api/handoff":
            with LOCK:
                handoff = json.loads(HANDOFF.read_text(encoding="utf-8")) if HANDOFF.exists() else {"state": "none"}
                self.reply(200, handoff)
            return
        if self.path.split("?", 1)[0] == "/api/relay/goal":
            self.reply(200, relay_goal.snapshot())
            return
        if self.path.split("?", 1)[0] == "/api/relay/health":
            health = relay_chat.health()
            health.update({"service_tag": SERVICE_TAG, "service_role": SERVICE_ROLE})
            self.reply(200, health)
            return
        if self.path.split("?", 1)[0] == "/api/relay/capability":
            try:
                self.reply(200, relay_chat.capability())
            except relay_chat.RelayChatError as error:
                self.reply(error.status, {"error": str(error)})
            return
        if self.path.split("?", 1)[0] == "/api/relay/state":
            query = parse_qs(self.path.split("?", 1)[1] if "?" in self.path else "", keep_blank_values=False)
            hint = (query.get("session") or [""])[0]
            try:
                selected = relay_chat.active_room(hint)
                self.reply(200, {"session_id": selected, "rooms": relay_chat.rooms()})
            except relay_chat.RelayChatError as error:
                self.reply(error.status, {"error": str(error)})
            return
        if self.path.split("?", 1)[0] == "/api/relay/rooms":
            try:
                self.reply(200, {"rooms": relay_chat.rooms()})
            except relay_chat.RelayChatError as error:
                self.reply(error.status, {"error": str(error)})
            return
        if self.path.split("?", 1)[0] == "/api/relay/media":
            query = parse_qs(self.path.split("?", 1)[1] if "?" in self.path else "", keep_blank_values=False)
            session_id = (query.get("session") or [""])[0]
            try:
                self.reply(200, relay_chat.media_list(session_id))
            except relay_chat.RelayChatError as error:
                self.reply(error.status, {"error": str(error)})
            return
        if self.path.split("?", 1)[0] == "/api/relay/media/file":
            query = parse_qs(self.path.split("?", 1)[1] if "?" in self.path else "", keep_blank_values=False)
            try:
                meta = relay_chat.media_bytes((query.get("id") or [""])[0], (query.get("session") or [""])[0])
            except relay_chat.RelayChatError as error:
                self.reply(error.status, {"error": str(error)})
                return
            self.send_response(200)
            self.send_header("Content-Type", meta["mime"])
            self.send_header("Content-Length", str(meta["size"]))
            self.send_header("Cache-Control", "private, max-age=31536000, immutable")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write((relay_media.MEDIA_DIR / meta["file_id"]).read_bytes())
            return
        if self.path.split("?", 1)[0] == "/api/relay/run":
            query = parse_qs(self.path.split("?", 1)[1] if "?" in self.path else "", keep_blank_values=False)
            try:
                self.reply(200, relay_chat.status((query.get("id") or [""])[0],
                                                  session_id=(query.get("session") or [""])[0]))
            except relay_chat.RelayChatError as error:
                self.reply(error.status, {"error": str(error)})
            return
        if self.path.split("?", 1)[0] == "/api/relay/decisions":
            query = parse_qs(self.path.split("?", 1)[1] if "?" in self.path else "", keep_blank_values=False)
            session_id = (query.get("session") or [""])[0]
            try:
                self.reply(200, relay_chat.decision_snapshot(session_id))
            except relay_chat.RelayChatError as error:
                self.reply(error.status, {"error": str(error)})
            return
        if self.path.split("?", 1)[0] == "/api/relay/decision-events":
            query = parse_qs(self.path.split("?", 1)[1] if "?" in self.path else "", keep_blank_values=False)
            try:
                last_seq = int((query.get("last_seq") or ["-1"])[0])
            except ValueError:
                last_seq = -1
            try:
                self.reply(200, relay_chat.native_events((query.get("id") or [""])[0], last_seq))
            except relay_chat.RelayChatError as error:
                self.reply(error.status, {"error": str(error)})
            return
        if self.path.split("?", 1)[0] == "/api/relay/proactive":
            query = parse_qs(self.path.split("?", 1)[1] if "?" in self.path else "", keep_blank_values=False)
            try:
                last_seq = int((query.get("last_seq") or ["-1"])[0])
            except ValueError:
                last_seq = -1
            try:
                limit = int((query.get("limit") or [""])[0]) if query.get("limit") else None
            except ValueError:
                limit = None
            try:
                self.reply(200, relay_chat.proactive_read(last_seq, limit))
            except relay_chat.RelayChatError as error:
                self.reply(error.status, {"error": str(error)})
            return
        if self.path.split("?", 1)[0] == "/api/relay/history":
            query = parse_qs(self.path.split("?", 1)[1] if "?" in self.path else "", keep_blank_values=False)
            session_id = (query.get("session") or ["relay-eddie-echo-chat"])[0]
            try:
                self.reply(200, relay_chat.history(session_id))
            except relay_chat.RelayChatError as error:
                self.reply(error.status, {"error": str(error)})
            return
        path = self.path.split("?", 1)[0]
        routes = {
            "/": ("index.html", "text/html; charset=utf-8"),
            "/app.js": ("app.js", "text/javascript; charset=utf-8"),
            "/pwa.js": ("pwa.js", "text/javascript; charset=utf-8"),
            "/push-settings.js": ("push-settings.js", "text/javascript; charset=utf-8"),
            "/mesh-sw.js": ("mesh-sw.js", "text/javascript; charset=utf-8"),
            "/manifest.webmanifest": ("manifest.webmanifest", "application/manifest+json; charset=utf-8"),
            "/mesh-badge-r-96.png": ("mesh-badge-r-96.png", "image/png"),
            "/mesh-icon-192.png": ("mesh-icon-192.png", "image/png"),
            "/mesh-icon-512.png": ("mesh-icon-512.png", "image/png"),
        }
        if path == "/favicon.ico":
            self.reply(204, b"", "image/x-icon")
        elif path in routes:
            name, mime = routes[path]
            self.reply(200, (ROOT / name).read_bytes(), mime)
        else:
            self.reply(404, {"error": "Not found."})

    def do_POST(self):
        if not self.local_request():
            return
        path = self.path.split("?", 1)[0]
        if path.startswith("/api/system/"):
            self.reply(404, {"error": "Not found."})
            return
        if path == "/api/mesh/log":
            try:
                body = self._read_json_body(1024)
                self.reply(201, mesh_log.record(body.get("surface"), body.get("kind"), body.get("code"), body.get("trigger")))
            except (ValueError, json.JSONDecodeError) as error:
                self.reply(400, {"error": str(error)})
            return
        if path in (PUSH_ENROLL_PATH, PUSH_REVOKE_PATH, PUSH_SETUP_PATH):
            # Own dispatch: the push door reads its body with its own limit and
            # answers its own refusals, and it never falls through to the
            # card/state writer below.
            try:
                if path == PUSH_SETUP_PATH:
                    self.push_setup()
                elif path == PUSH_ENROLL_PATH:
                    self.push_enroll()
                else:
                    self.push_revoke()
            except relay_push.PushError as error:
                self.reply(error.status, {"error": str(error)})
            except (ValueError, json.JSONDecodeError) as error:
                self.reply(400, {"error": str(error)})
            except OSError:
                self.reply(500, {"error": "Disk write failed. Reload to check the saved state."})
            return
        if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
            self.reply(415, {"error": "JSON required."})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            path = self.path.split("?", 1)[0]
            limits = {"/api/relay/send": 1048576, "/api/relay/media/upload": 9437184}
            limit = limits.get(path, 8192)
            if not 0 < length <= limit:
                raise ValueError("Request is empty or too large.")
            body = json.loads(self.rfile.read(length))
            if not isinstance(body, dict):
                raise ValueError("A JSON object is required.")
            if self.path.split("?", 1)[0] == "/api/relay/goal":
                action = body.get("action")
                text = body.get("text", "")
                if action not in {"set", "clear", "pause", "resume"}:
                    raise ValueError("Use set, clear, pause, or resume.")
                if action == "set" and not isinstance(text, str):
                    raise ValueError("Goal text must be a string.")
                self.reply(200, relay_goal.apply(action, text))
                return
            if path == "/api/relay/media/upload":
                self.reply(201, relay_chat.stage_media(
                    base64.b64decode(body.get("data", ""), validate=True) if isinstance(body.get("data"), str) else b"",
                    body.get("name", ""),
                    body.get("session_id", ""),
                ))
                return
            if path == "/api/relay/room":
                self.reply(200, relay_chat.select_room(body.get("session_id", "")))
                return
            if path == "/api/relay/stop":
                self.reply(200, relay_chat.stop(body.get("run_id", "")))
                return
            if path == "/api/relay/new":
                self.reply(200, relay_chat.new_session())
                return
            if path == "/api/relay/send":
                self.reply(202, relay_chat.submit(
                    body.get("text", ""),
                    body.get("attachment"),
                    body.get("session_id"),
                    idempotency_key=self.headers.get("Idempotency-Key", ""),
                    files=body.get("files"),
                    reply=body.get("reply"),
                ))
                return
            if path == "/api/relay/decisions":
                if body.get("action") == "answer":
                    self.reply(200, relay_chat.answer_clarification(
                        body.get("run_id", ""), body.get("request_id", ""), body.get("answer", "")))
                    return
                if body.get("action") != "resolve":
                    raise ValueError("Use resolve or answer.")
                self.reply(200, relay_chat.resolve_decision(
                    body.get("run_id", ""),
                    body.get("request_id", ""),
                    body.get("choice", ""),
                    body.get("reason"),
                    allow_reason=bool(body.get("allow_reason")),
                ))
                return
            play_turn = None
            with LOCK:
                state = copy.deepcopy(read_state())
                if self.path == "/api/cards":
                    title = body.get("title", "")
                    note = body.get("note", "")
                    if not isinstance(title, str) or not title.strip() or len(title.strip()) > 40:
                        raise ValueError("Use a title of 1 to 40 characters.")
                    if not isinstance(note, str) or len(note.strip()) > 1000:
                        raise ValueError("Keep the note under 1001 characters.")
                    state["cards"].append({"id": "c" + uuid.uuid4().hex, "header": "unfiled", "title": title.strip(), "note": note.strip(), "who": "Eddie", "added": datetime.now(timezone.utc).isoformat(), "state": "idle", "line": "unfiled", "sample": False, "pinned": False, "trashedAt": None})
                else:
                    parts = self.path.strip("/").split("/")
                    if len(parts) != 4 or parts[:2] != ["api", "cards"]:
                        self.reply(404, {"error": "Not found."})
                        return
                    card = next((c for c in state["cards"] if c["id"] == parts[2]), None)
                    if card is None:
                        self.reply(404, {"error": "Card not found."})
                        return
                    action = parts[3]
                    if action not in {"play", "pause", "pin", "trash", "restore", "finish", "edit"}:
                        raise ValueError("Unknown action.")
                    if card["sample"] and action != "pin":
                        raise ValueError("Sample only. Add a card to hand real work to Echo.")
                    if action == "play":
                        if card["state"] == "finished":
                            raise ValueError("This card is already finished.")
                        if card["state"] not in {"idle", "paused", "ready"}:
                            raise ValueError("Recover this card before playing it.")
                        session_id = play_room(body)
                        line = card.get("line", "")
                        text = card["title"]
                        if line and line != "ready for Echo":
                            text += "\n" + line
                        play_turn = (text, session_id)
                        for other in state["cards"]:
                            if not other["sample"] and other["id"] != card["id"] and other["state"] == "ready":
                                other.update(state="paused", line="paused")
                        card.update(state="ready", line="ready for Echo")
                    elif action == "pause":
                        if card["state"] != "ready":
                            raise ValueError("Only a ready card can be paused.")
                        card.update(state="paused", line="paused")
                    elif action == "pin":
                        if card["state"] == "trash":
                            raise ValueError("Recover this card before pinning it.")
                        card["pinned"] = not card["pinned"]
                    elif action == "trash":
                        card.update(state="trash", line="trash", pinned=False, trashedAt=datetime.now(timezone.utc).isoformat())
                    elif action == "restore":
                        if card["state"] != "trash":
                            raise ValueError("This card is not in trash.")
                        card.update(state="idle", line="unfiled", trashedAt=None)
                    elif action == "edit":
                        title = body.get("title", "")
                        note = body.get("note", "")
                        if not isinstance(title, str) or not title.strip() or len(title.strip()) > 40:
                            raise ValueError("Use a title of 1 to 40 characters.")
                        if not isinstance(note, str) or len(note.strip()) > 1000:
                            raise ValueError("Keep the note under 1001 characters.")
                        card["title"] = title.strip()
                        card["note"] = note.strip()
                    elif action == "finish":
                        mark_finished(card)
                atomic_json(STORE, state)
                sync_handoff(state)
                result = start_card_turn(*play_turn) if play_turn else {}
                self.reply(200, {**state, **result})
        except relay_chat.RelayChatError as error:
            self.reply(error.status, {"error": str(error)})
        except (ValueError, json.JSONDecodeError) as error:
            self.reply(400, {"error": str(error)})
        except OSError:
            self.reply(500, {"error": "Disk write failed. Reload to check the saved state."})


if __name__ == "__main__":
    import relay_push_keys
    relay_push_keys.apply_environment()
    initialize()
    port, SERVICE_TAG, SERVICE_ROLE = runtime_options(sys.argv)
    if not 1024 <= port <= 65535:
        raise SystemExit("Use a local port from 1024 to 65535.")
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"Onoes-Mesh at http://127.0.0.1:{port}/ — local disk handoff only.", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
