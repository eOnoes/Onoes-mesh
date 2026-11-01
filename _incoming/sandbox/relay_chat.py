"""Phone chat door. Localhost Hermes API only. Never log the key.

Two native transports, both discovered from the installed source:

``/v1/runs``
    Text turns only — the handler flattens a list ``input`` to its text parts. Relay
    uses it for ordinary messages and forwards the native ``Idempotency-Key``, which the
    API server stores durably (``features.runs_idempotency.durable = true``).

``/api/sessions/{id}/chat``
    The only run-scoped door that carries typed content parts to the model, so a real
    photo rides this one as an ``image_url`` part plus the ``[Image attached at: ...]``
    text handle that the installed image routing writes. It exposes no idempotency key,
    so Relay keeps its own durable key→run correlation and refuses to blind-retry.

Neither transport is ever given a browser-supplied run id: every run Relay reports was
recorded by this server in its own durable store.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import sqlite3
import threading
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

import relay_decisions
import relay_media
import relay_runner
import relay_store
import relay_turn_meta

BASE = os.environ.get("RELAY_HERMES_API_BASE", "http://127.0.0.1:8642")
SESSION_ID = "relay-eddie-echo-chat"
TITLE = "Relay Eddie Echo"
INSTRUCTIONS = (
    "You are Echo in the Relay chat with Eddie. "
    "This room is the phone page, not Telegram and not the Desktop app. "
    "Put the reply in your final answer only. "
    "Do not send a message to Telegram, Discord, email, or any other chat. "
    "Do not resume, clear, or edit the standing goal."
)
TERMINAL = {"completed", "failed", "cancelled", "interrupted", "expired", "unavailable"}

STORE = relay_store.get_store()
DECISIONS = relay_decisions.DecisionStore(store=STORE)
_DECISIONS_LOCK = threading.RLock()
RUNNERS: relay_runner.RunRegistry | None = None
_RUNNERS_LOCK = threading.Lock()


class RelayChatError(Exception):
    def __init__(self, message, status=502):
        super().__init__(message)
        self.status = status


def _decision_error(error):
    if isinstance(error, relay_decisions.DecisionError):
        return RelayChatError(str(error), error.status)
    if isinstance(error, ValueError):
        return RelayChatError(str(error), 400)
    return error


def runners() -> relay_runner.RunRegistry:
    """The shared run registry (created lazily so tests can inject their own)."""
    global RUNNERS
    with _RUNNERS_LOCK:
        if RUNNERS is None:
            RUNNERS = relay_runner.RunRegistry(STORE, BASE, _key(), on_approval=None)
        return RUNNERS


def _key():
    env = os.environ.get("API_SERVER_KEY", "").strip().strip('"').strip("'")
    if env:
        return env
    paths = [
        Path(r"C:\Users\eMitchell109\AppData\Local\hermes\.env"),
        Path(os.environ.get("LOCALAPPDATA", "")) / "hermes" / ".env",
    ]
    for path in paths:
        if not path.is_file():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.startswith("API_SERVER_KEY="):
                value = line.split("=", 1)[1].strip().strip('"').strip("'")
                if value:
                    return value
    raise RelayChatError("Agent door has no key.", status=503)


def _safe(text):
    text = " ".join(str(text or "").split())
    try:
        secret = _key()
    except RelayChatError:
        secret = ""
    if secret and secret in text:
        text = text.replace(secret, "[key]")
    return text[:180] or "Agent door refused the send."


def _call(method, path, payload=None, timeout=20):
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    headers = {"Accept": "application/json", "Authorization": "Bearer " + _key()}
    if data is not None:
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(BASE + path, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
            return response.status, json.loads(raw or "{}")
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            body = json.loads(exc.read().decode("utf-8") or "{}")
            if isinstance(body, dict):
                detail = body.get("error") or body.get("message") or body.get("code") or ""
                if isinstance(detail, dict):
                    detail = detail.get("message") or detail.get("code") or ""
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            detail = ""
        raise RelayChatError(_safe(detail) or f"Agent door returned {exc.code}.", status=exc.code) from None
    except urllib.error.URLError:
        raise RelayChatError("Agent door is down.", status=503) from None
    except TimeoutError:
        raise RelayChatError("Agent door timed out.", status=504) from None


# --------------------------------------------------------------------------------------
# Rooms (server-backed; the browser never invents one)
# --------------------------------------------------------------------------------------


def room(session_id=None):
    """Validate a Relay room id and make sure the durable store knows it."""
    if session_id in (None, ""):
        return SESSION_ID
    if not relay_store.valid_room(session_id):
        raise RelayChatError("Unknown room.", status=400)
    try:
        STORE.ensure_room(session_id)
    except ValueError as exc:
        raise RelayChatError(str(exc), status=400)
    return session_id


def rooms():
    """List Relay rooms the server knows about, most recently used first."""
    known = STORE.list_rooms()
    if not known:
        STORE.ensure_room(SESSION_ID, "Eddie + Echo")
    return STORE.list_rooms()


def select_room(session_id):
    """Server-backed active-room selection that survives a fresh browser document."""
    room_id = room(session_id)
    STORE.set_selected(room_id)
    return {"session_id": room_id, "rooms": rooms()}


def active_room(client_hint=""):
    """The room a fresh document should open: the server's stored selection."""
    return STORE.get_selected(client_hint if relay_store.valid_room(client_hint) else "")


def _ensure_session(session_id=SESSION_ID):
    try:
        status, _ = _call("GET", "/api/sessions/" + session_id)
        if status == 200:
            STORE.ensure_room(session_id)
            return
    except RelayChatError as exc:
        if exc.status not in (404, 405, 501):
            raise
        if exc.status != 404:
            return
    try:
        _call("POST", "/api/sessions", {"id": session_id, "title": TITLE})
    except RelayChatError as exc:
        if exc.status in (400, 409, 404, 405, 501):
            return
        raise
    STORE.ensure_room(session_id)


MAX_NOTE = 1000
MIN_PAPER = 1001
MAX_PAPER = 200000


def run_input(text, attachment=None):
    """Build the text turn: the note, plus the paper only once and only for the model."""
    note = text.strip() if isinstance(text, str) else ""
    paper = attachment if isinstance(attachment, str) else ""
    if paper and not MIN_PAPER <= len(paper) <= MAX_PAPER:
        raise RelayChatError("That paste still fits the box.", status=400)
    if len(note) > MAX_NOTE or not note and not paper:
        raise RelayChatError("Use 1 to 1000 characters.", status=400)
    if not paper:
        return note
    block = "Read the attached prompt.txt in full. It is the instruction for this turn.\n\n" + paper
    return note + "\n\n" + block if note else block


def _fingerprint(room_id, payload, files):
    digest = hashlib.sha256()
    digest.update(room_id.encode("utf-8"))
    digest.update(b"\x00")
    digest.update(payload.encode("utf-8"))
    for file_id in sorted(files or []):
        digest.update(b"\x00")
        digest.update(str(file_id).encode("utf-8"))
    return digest.hexdigest()


def _validate_key(key):
    if key and not (0 < len(key) <= 255 and all(33 <= ord(ch) <= 126 for ch in key)):
        raise RelayChatError("That send key is invalid.", status=400)
    return key


_SUBMIT_LOCK = threading.RLock()

def submit(text, attachment=None, session_id=None, idempotency_key=None, files=None, reply=None):
    with _SUBMIT_LOCK:
        return _submit_locked(text, attachment, session_id, idempotency_key, files, reply)

def _submit_locked(text, attachment=None, session_id=None, idempotency_key=None, files=None, reply=None):
    """Send one turn. Idempotent on the client key; never duplicates an execution."""
    room_id = room(session_id)
    key = _validate_key(idempotency_key if isinstance(idempotency_key, str) else "")
    if reply is not None and (not isinstance(reply, dict) or not isinstance(reply.get("id"), str)):
        raise RelayChatError("Invalid reply link.", status=400)
    file_ids = [str(item.get("file_id", "")) if isinstance(item, dict) else item
                for item in (files or []) if isinstance(item, (str, dict))]
    file_ids = [item for item in file_ids if item]
    payload = run_input(text, attachment)

    if key:
        prior = STORE.sent_lookup(key)
        if prior is not None:
            fingerprint = _fingerprint(room_id, payload, file_ids)
            if prior["fingerprint"] != fingerprint:
                raise RelayChatError("That send key was already used for a different message.", status=409)
            if prior["state"] == "accepted" and prior["run_id"]:
                return {"run_id": prior["run_id"], "status": "replayed", "session_id": room_id,
                        "replayed": True, "transport": prior.get("detail") or "runs"}
            if prior["state"] == "inflight":
                # An uncertain earlier submit: do not start a second execution.
                raise RelayChatError(
                    "That message is still sending. Give it a moment before retrying.", status=409)

    use_media = bool(file_ids)
    transport = "session_chat" if use_media else "runs"

    if key:
        STORE.sent_begin(key, room_id, _fingerprint(room_id, payload, file_ids))

    try:
        if use_media:
            result = _submit_media_turn(room_id, payload, file_ids)
        else:
            result = _submit_text_turn(room_id, payload, key)
    except Exception as exc:
        if key:
            if isinstance(exc, RelayChatError) and 400 <= exc.status < 500:
                STORE.sent_mark_failed(key, _safe(str(exc)))
            # Timeout/5xx is ambiguous: retain inflight, never invite a blind duplicate.
        raise

    run_id = result["run_id"]
    with _DECISIONS_LOCK:
        DECISIONS.associate_run(room_id, run_id,
                                {"text": payload, "attachment_present": use_media, "idempotency_key": key})
        DECISIONS.begin(run_id, {"text": payload, "attachment_present": use_media, "idempotency_key": key})
    STORE.update_run_state(run_id, result.get("status") or "running")
    relay_turn_meta.save(STORE, run_id, room_id, payload, str(text or ""), attachment, reply, file_ids, result.get("output", ""))
    if not use_media:
        runners().start(run_id, room_id)
    if key:
        STORE.sent_finish(key, run_id, "accepted", transport)
    return {"run_id": run_id, "status": result.get("status") or "started", "session_id": room_id,
            "replayed": bool(result.get("replayed")), "transport": transport}


def _submit_text_turn(room_id, payload, key):
    """Ordinary text turn through /v1/runs with the native idempotency key."""
    headers = {"Accept": "application/json", "Content-Type": "application/json", "Authorization": "Bearer " + _key()}
    if key:
        headers["Idempotency-Key"] = key
    body = {"input": payload, "session_id": room_id, "instructions": INSTRUCTIONS}
    request = urllib.request.Request(
        BASE + "/v1/runs",
        data=json.dumps(body).encode("utf-8"),
        method="POST",
        headers=headers,
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            raw = response.read().decode("utf-8")
            status = response.status
            result = json.loads(raw or "{}")
            replayed = response.headers.get("Idempotency-Replayed", "").lower() == "true"
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            err = json.loads(exc.read().decode("utf-8") or "{}")
            if isinstance(err, dict):
                detail = err.get("error") or err.get("message") or err.get("code") or ""
                if isinstance(detail, dict):
                    detail = detail.get("message") or detail.get("code") or ""
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            detail = ""
        raise RelayChatError(_safe(detail) or f"Agent door returned {exc.code}.", status=exc.code) from None
    except urllib.error.URLError:
        raise RelayChatError("Agent door is down.", status=503) from None
    except TimeoutError:
        raise RelayChatError("Agent door timed out.", status=504) from None
    run_id = str(result.get("run_id") or "")
    if not run_id:
        raise RelayChatError("Agent door returned no run.", status=502)
    if status == 409:
        raise RelayChatError("That send key was already used for a different message.", status=409)
    return {"run_id": run_id, "status": result.get("status") or "started", "replayed": replayed}


def _submit_media_turn(room_id, payload, file_ids):
    """Photo turn through the session-chat door that actually carries image parts.

    The verified native shape is ``content: [{type:"text", ...}, {type:"image_url", ...}]``
    with a ``data:`` url, built by ``relay_media.native_image_parts``. The caption is the
    text part; the pixels are the image part. Nothing is described instead of sent.
    """
    content = [{"type": "text", "text": payload}]
    for file_id in file_ids:
        meta = relay_media.resolve(file_id, room_id)
        raw = relay_media.resolve(file_id, room_id, with_bytes=True)["bytes"]
        content.extend(relay_media.native_image_parts("", meta, raw)[1:])
    body = {"message": content, "instructions": INSTRUCTIONS}
    status, result = _call("POST", f"/api/sessions/{room_id}/chat", body, timeout=120)
    message = result.get("message") if isinstance(result, dict) else None
    final = str((message or {}).get("content") or "") if isinstance(message, dict) else ""
    run_id = str(result.get("run_id") or "") if isinstance(result, dict) else ""
    if not run_id:
        # The session-chat door does not mint a run id; synthesise a Relay-local one so
        # the rest of the pipeline (status, decisions, stop) still has an identity.
        run_id = "relay_" + uuid.uuid4().hex[:24]
    return {"run_id": run_id, "status": "completed" if final else "running", "output": final,
            "replayed": False}


def stop(run_id):
    """Ask the native door to stop a Relay-owned run."""
    run_id = _owned_run_id(run_id)
    runners().stop(run_id)
    try:
        _, body = _call("POST", "/v1/runs/" + run_id + "/stop", {})
    except RelayChatError as exc:
        if exc.status in (404, 409):
            STORE.update_run_state(run_id, "cancelled")
            return {"run_id": run_id, "status": "cancelled"}
        raise
    status = body.get("status") or "stopping"
    STORE.update_run_state(run_id, status)
    return {"run_id": run_id, "status": status}


def _owned_run_id(run_id):
    """Accept only a run id this Relay server recorded, and only for the room it names."""
    try:
        run_id = relay_decisions.validate_run_id(run_id)
    except relay_decisions.DecisionError as error:
        raise _decision_error(error)
    room_id = STORE.run_room(run_id)
    if not room_id:
        raise RelayChatError("That is not a Relay run.", status=404)
    return run_id


def _drop_empty_selected_room(next_session_id):
    """Only /new may drop a room, and only after every saved-content check succeeds."""
    import relay_proactive
    import relay_sqlite_worker

    try:
        session_id = STORE.get_selected()
        if session_id == next_session_id:
            return
        for path, table in ((relay_sqlite_worker.OUTBOX_DB, "turns"),
                            (relay_proactive.get_store().path, "relay_proactive")):
            # Read the durable rows directly: history has bounded replay and may
            # tolerate a proactive read failure. Neither is proof of emptiness.
            db = sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True)
            try:
                if db.execute(f"SELECT 1 FROM {table} WHERE session_id = ? LIMIT 1",
                              (session_id,)).fetchone():
                    return
            finally:
                db.close()
        STORE.delete_empty_room(session_id)
    except Exception:
        # Missing/unreadable stores are unknown, never an empty-room verdict.
        return


def new_session():
    suffix = uuid.uuid4().hex[:8]
    session_id = "relay-eddie-echo-" + suffix
    _drop_empty_selected_room(session_id)
    _call("POST", "/api/sessions", {"id": session_id, "title": "Relay " + suffix})
    STORE.ensure_room(session_id, "Relay " + suffix.upper())
    STORE.set_selected(session_id)
    return {"session_id": session_id, "rooms": rooms()}


def status(run_id, session_id=None):
    """Pollable run status, always gated on Relay's own run ownership."""
    run_id = _owned_run_id(run_id)
    if session_id:
        owner = STORE.run_room(run_id)
        if owner and room(session_id) != owner:
            raise RelayChatError("That run belongs to another Relay room.", status=403)

    if run_id.startswith("relay_"):
        # Session-chat has already completed synchronously. Report completed/no-reply
        # only when Relay observed that turn's local result; a missing row is unknown,
        # not a fabricated transport failure.
        if not relay_turn_meta.has_result(STORE, run_id):
            return {"run_id": run_id, "status": "unknown", "done": False,
                    "output": "", "error": "Photo reply state is not available.",
                    "decision_blocked": False, "decision": None,
                    "transport": "session_chat"}
        output = relay_turn_meta.local_result(STORE, run_id)
        return {"run_id": run_id, "status": "completed", "done": True,
                "output": output or "", "error": "", "decision_blocked": False,
                "decision": None, "transport": "session_chat"}
    pump = runners().snapshot(run_id)
    pending = DECISIONS.pending_for_run(run_id)

    state = {
        "run_id": run_id,
        "status": (pump or {}).get("status") or "",
        "done": False,
        "decision_blocked": bool(pending),
        "decision": pending[0] if pending else None,
        "output": (pump or {}).get("output") or "",
        "error": (pump or {}).get("error") or "",
        "reconnects": (pump or {}).get("reconnects", 0),
        "transport": "",
    }

    if pending:
        state["status"] = "waiting_for_approval"
        return state

    if (pump or {}).get("status") in TERMINAL and ((pump or {}).get("status") != "completed" or (pump or {}).get("output")):
        state["done"] = True
        state["status"] = pump["status"]
        state["output"] = pump.get("output") or ""
        if state["output"]: relay_turn_meta.set_output(STORE, run_id, state["output"])
        state["error"] = _safe(pump.get("error") or "")
        return state

    # The pump has not caught up (or died): ask the native door once, without retry storms.
    try:
        _, body = _call("GET", "/v1/runs/" + run_id, timeout=10)
    except RelayChatError as exc:
        if exc.status == 404:
            # Gateway no longer knows the run: report Relay's last record truthfully.
            state["status"] = STORE.run_room(run_id) and (pump or {}).get("status") or "failed"
            state["done"] = True
            state["error"] = state["error"] or "The agent door no longer knows that run."
            return state
        state["error"] = _safe(exc)
        return state

    native_status = str(body.get("status") or "")
    approval = body.get("approval")
    if native_status == "waiting_for_approval" and isinstance(approval, dict):
        try:
            with _DECISIONS_LOCK:
                DECISIONS.associate_run(STORE.run_room(run_id) or SESSION_ID, run_id)
                decision = DECISIONS.accept_event(approval)
            state["decision_blocked"] = True
            state["decision"] = decision
            state["status"] = "waiting_for_approval"
            STORE.update_run_state(run_id, "waiting_for_approval")
            return state
        except relay_decisions.DecisionError:
            state["decision_blocked"] = True
            state["status"] = "waiting_for_approval"
            return state

    if native_status in TERMINAL:
        state["done"] = True
        state["status"] = native_status
        if native_status == "completed":
            state["output"] = str(body.get("output") or "")
            relay_turn_meta.set_output(STORE, run_id, state["output"])
        else:
            state["error"] = _safe(body.get("error") or native_status)
        STORE.update_run_state(run_id, native_status)
        runners().forget(run_id)
        return state

    state["status"] = native_status or "running"
    return state


def probe():
    """Auth check only. Does not start a run."""
    try:
        return relay_decisions.probe_api(BASE, _key())
    except relay_decisions.DecisionError as error:
        raise _decision_error(error)


def decision_snapshot(session_id):
    """Recoverable pending-decision snapshot for one room (survives refresh/restart)."""
    try:
        session_id = room(session_id)
        # Durable lifecycle is authoritative. In-memory selected_run may retain
        # a completed run indefinitely; it must never invent unfinished work.
        active = STORE.active_run(session_id)
        run_id = active.get("run_id", "")
        if not run_id:
            return {"state": "idle", "run_id": "", "session_id": session_id}
        snapshot = DECISIONS.run_snapshot(run_id)
        snapshot["state"] = "decision_blocked" if snapshot.get("pending") else active["state"]
        snapshot["session_id"] = session_id
        snapshot["selected_run"] = run_id
        return snapshot
    except relay_decisions.DecisionError as error:
        raise _decision_error(error)


def decision_list():
    with _DECISIONS_LOCK:
        return [DECISIONS.run_snapshot(run_id) for run_id in list(DECISIONS._runs)]


def accept_approval_event(event, session_id=None):
    try:
        with _DECISIONS_LOCK:
            decision = DECISIONS.accept_event(event)
            if session_id:
                DECISIONS.associate_run(session_id, decision["run_id"])
            return decision
    except relay_decisions.DecisionError as error:
        raise _decision_error(error)


def resolve_decision(run_id, request_id, choice, reason=None, *, allow_reason=False):
    """Resolve one exact approval. The run must be owned by the room it names."""
    run_id = _owned_run_id(run_id)
    try:
        with _DECISIONS_LOCK:
            return DECISIONS.approval_decision(run_id, request_id, choice, reason,
                                               allow_reason=allow_reason)
    except relay_decisions.DecisionError as error:
        raise _decision_error(error)


def answer_clarification(run_id, request_id, answer):
    """Answer an ordinary clarification through the supported steer door."""
    run_id = _owned_run_id(run_id)
    try:
        with _DECISIONS_LOCK:
            return DECISIONS.answer_clarification(run_id, request_id, answer)
    except relay_decisions.DecisionError as error:
        raise _decision_error(error)


def capability():
    """What the installed API really supports — the browser never guesses."""
    try:
        probe = relay_decisions.probe_api(BASE, _key())
    except relay_decisions.DecisionError as error:
        raise _decision_error(error)
    capability = relay_decisions.reason_capability()
    return {
        "approval_reason_native": bool(capability.get("native")),
        "approval_reason_detail": capability.get("detail", ""),
        "approval_reason_how": capability.get("how", ""),
        "run_events_sse": bool(probe.get("run_events_sse")),
        "runs_idempotency": probe.get("runs_idempotency") or {},
        "image_input": "session_chat",
        "api_base": BASE,
    }


def history(session_id, limit=400):
    """Room turns from the held local outbox, plus genuine Echo proactive messages.

    The two sources stay in separate provenance namespaces on purpose:

    * ``msg-h-`` rows are native/outbox turns, exactly as before. Nothing here
      rewrites, re-orders, or re-attributes them.
    * ``msg-p-`` rows come from ``relay_proactive`` — messages Echo genuinely
      authored and published locally. They are never converted into a fake Eddie
      prompt, never inserted into the outbox, and never given a native message id.

    Ordering is by real UTC ``created_at`` (a stable, lexicographically ordered
    ``...Z`` string). Ties break on the namespace so the merge is deterministic and
    a proactive message can never displace a native turn with the same timestamp.
    """
    import relay_proactive
    import relay_sqlite_worker

    session_id = room(session_id)
    try:
        relay_sqlite_worker.sync()
        db = relay_sqlite_worker.connect_outbox()
        try:
            rows = db.execute(
                "SELECT id, role, body, created_at FROM turns WHERE session_id = ? ORDER BY id DESC LIMIT ?",
                (session_id, int(limit)),
            ).fetchall()
        finally:
            db.close()
    except Exception:
        raise RelayChatError("The room could not be read.", status=502)
    turns = []
    for row in reversed(rows):
        turns.append({"id": "msg-h-" + str(row["id"]), "who": "Eddie" if row["role"] == "user" else "Echo", "text": row["body"],
                      "created_at": row["created_at"], "proactive": False})
    try:
        proactive = relay_proactive.read(last_seq=-1, limit=relay_proactive.DEFAULT_READ_LIMIT)
    except Exception:
        # A proactive store problem must not take the room's native history down.
        proactive = {"events": [], "gap": False, "last_seq": -1}
    for event in proactive.get("events", []):
        if event.get("session_id") != session_id:
            continue
        turns.append({"id": event["id"], "who": "Echo", "text": event.get("text", ""),
                      "created_at": event.get("created_at", ""), "proactive": True})
    turns.sort(key=lambda turn: (turn.get("created_at") or "", turn["id"]))
    payload = relay_turn_meta.decorate(STORE, session_id, turns)
    return {"session_id": session_id, "turns": payload,
            "proactive_last_seq": proactive.get("last_seq", -1),
            "proactive_gap": bool(proactive.get("gap"))}


def proactive_read(last_seq=-1, limit=None):
    """The bounded, strictly ordered proactive replay window for a reconnecting client."""
    import relay_proactive

    if limit is None:
        limit = relay_proactive.DEFAULT_READ_LIMIT
    try:
        last_seq = int(last_seq)
    except (TypeError, ValueError):
        last_seq = -1
    return relay_proactive.read(last_seq=last_seq, limit=limit)


def proactive_wait_for_next(last_seq=-1, timeout=None):
    """Bounded change-notification wait for the proactive live stream.

    Wakes as soon as a genuinely new durable message is published, or when
    ``timeout`` elapses — whichever comes first. Returns the new high-water mark,
    or ``last_seq`` unchanged if nothing arrived. No timer, no polling loop.
    """
    import relay_proactive

    if timeout is None:
        timeout = relay_proactive.PROACTIVE_WAIT_SECONDS
    try:
        last_seq = int(last_seq)
    except (TypeError, ValueError):
        last_seq = -1
    return relay_proactive.wait_for_next(last_seq=last_seq, timeout=timeout)


def media_list(session_id):
    return {"session_id": room(session_id), "media": STORE.media_for_room(session_id)}


def stage_media(raw: bytes, name, session_id):
    try:
        return relay_media.stage(raw, name, room(session_id))
    except relay_media.MediaError as error:
        raise RelayChatError(str(error), status=error.status)


def media_bytes(file_id, session_id):
    try:
        meta = relay_media.resolve(file_id, room(session_id), with_bytes=True)
    except relay_media.MediaError as error:
        raise RelayChatError(str(error), status=error.status)
    return meta


def health():
    """Distinguish this Relay build from the old static-serving process on the same port."""
    try:
        capability = relay_decisions.probe_api(BASE, _key())
        api = "up"
    except Exception:
        capability = {}
        api = "down"
    return {
        "service": "relay",
        "version": "relay-gaps-v2",
        "routes": [
            "/api/relay/health", "/api/relay/state", "/api/relay/rooms", "/api/relay/room",
            "/api/relay/send", "/api/relay/run", "/api/relay/stop", "/api/relay/new",
            "/api/relay/history", "/api/relay/proactive", "/api/relay/proactive/stream",
            "/api/relay/decisions", "/api/relay/capability",
            "/api/relay/media", "/api/relay/media/upload", "/api/relay/media/file",
        ],
        "hermes_api": api,
        "runs": runners().live_count(),
        "rooms": len(STORE.list_rooms()),
        "approval_reason_native": bool((capability or {}).get("approval_reason_native")),
    }


def native_events(run_id, last_seq=-1):
    """Poll the native SSE event stream for approval requests (bounded, no blocking)."""
    import relay_events

    run_id = _owned_run_id(run_id)
    try:
        last_seq = int(last_seq)
    except (TypeError, ValueError):
        last_seq = -1
    try:
        result = relay_events.fetch_events(BASE, _key(), run_id, last_seq=last_seq, timeout=4.0)
    except relay_events.EventStreamError as error:
        raise RelayChatError(str(error), status=503 if error.transient else 502)
    clean = []
    for event in result.get("events", []):
        name = str(event.get("event") or "")
        if name == "approval.request":
            try:
                with _DECISIONS_LOCK:
                    clean.append(DECISIONS.accept_event(event))
            except relay_decisions.DecisionError:
                continue
        elif name in {"message.delta", "message.interim", "tool.started", "tool.completed",
                      "tool.failed", "reasoning.available"}:
            continue
    return {"run_id": run_id, "events": clean, "last_seq": result.get("last_seq", last_seq),
            "terminal": bool(result.get("terminal"))}
