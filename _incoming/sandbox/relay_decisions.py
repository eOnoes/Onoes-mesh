"""Phase 2 Relay decision bridge: truthful approvals, durable records, clarifications.

A live approval is already correlated to one run and one exact ``request_id`` by Hermes.
This module presents that native request to the Relay owner and posts a decision back
through the installed API contract. It never widens a run to another room, never invents
an approval choice, and never executes a dangerous command itself.

Truthfulness rule (owner-approved): a typed denial reason is a *native* delivery only
when the installed API actually accepts one. ``POST /v1/runs/{id}/approval`` is inspected
at runtime — when it forwards ``reason`` into ``resolve_gateway_approval``, Relay sends
the reason and labels it native. When it does not, Relay refuses to pretend: the typed
reason is stored and shown as Relay-local, and the owner is told plainly that the agent
will only learn "denied by user", not why.
"""
from __future__ import annotations

import hashlib
import inspect
import json
import os
import threading
import time
import urllib.error
import urllib.request
from collections import OrderedDict
from dataclasses import dataclass

import relay_store

BASE = os.environ.get("RELAY_HERMES_API_BASE", "http://127.0.0.1:8642")
ALLOWED_CHOICES = ("once", "session", "always", "deny")
# Owner-facing native choices for this slice. `session` is deliberately not offered:
# Relay must not widen a run-scoped approval into a whole-session permission.
NATIVE_SCOPE_CHOICES = ("once", "always")
RUN_ID_CHARS = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-")
REQUEST_ID_MAX = 256
REASON_MAX = 280  # mirrors the gateway approval deny-reason cap
DECISION_CACHE_MAX = 128
DISPLAY_COMMAND_MAX = 500
DISPLAY_DESCRIPTION_MAX = 500


class DecisionError(Exception):
    """A user-visible Relay decision validation/API failure."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class DecisionRecord:
    run_id: str
    request_id: str
    choice: str
    reason: str
    resolved: int
    reason_native: bool = False

    def as_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "request_id": self.request_id,
            "choice": self.choice,
            "reason": self.reason,
            "reason_native": bool(self.reason_native),
            "resolved": self.resolved,
        }


# --------------------------------------------------------------------------------------
# Native capability discovery (read-only, cached)
# --------------------------------------------------------------------------------------


def detect_reason_support(source: str | None = None) -> dict:
    """Decide whether the installed approval endpoint really forwards a typed reason.

    Two read-only probes:

    1. Source probe — the installed ``_handle_run_approval`` body is inspected for a call
       that forwards ``reason`` into ``resolve_gateway_approval``. This is the authority.
    2. Signature probe — ``resolve_gateway_approval``'s own signature is checked for a
       ``reason`` parameter (native plumbing exists even when the route ignores it).

    Returns ``{"native": bool, "how": str, "detail": str}``. An unreadable source yields
    ``native=False`` with the reason recorded, so Relay fails closed rather than claiming
    a delivery the API cannot make.
    """
    if source is not None:
        text = source
        where = "provided source"
    else:
        base = os.environ.get("HERMES_HOME") or os.path.join(
            os.environ.get("LOCALAPPDATA", "") or r"C:\Users\eMitchell109\AppData\Local",
            "hermes", "hermes-agent")
        candidates = [
            os.path.join(base, "gateway", "platforms", "api_server_runs.py"),
            r"C:\Users\eMitchell109\AppData\Local\hermes\hermes-agent\gateway\platforms\api_server_runs.py",
        ]
        text = ""
        where = "installed source"
        for candidate in candidates:
            try:
                if os.path.isfile(candidate):
                    with open(candidate, encoding="utf-8", errors="replace") as stream:
                        text = stream.read()
                    where = candidate
                    break
            except OSError:
                continue
        if not text:
            return {"native": False, "how": "unavailable",
                    "detail": "the installed approval source could not be read"}
    window = text
    index = text.find("def _handle_run_approval")
    if index >= 0:
        end = text.find("\ndef ", index + 10)
        window = text[index: end if end > index else index + 8000]
    forwards = "reason=" in window and "resolve_gateway_approval" in window
    signature_ok = _resolve_gateway_accepts_reason()
    if forwards:
        return {"native": True, "how": "route+signature",
                "detail": f"{where} forwards reason into resolve_gateway_approval"}
    if not text.strip():
        return {"native": False, "how": "absent",
                "detail": "the installed approval API exposes no reason parameter"}
    if signature_ok:
        return {"native": False, "how": "signature-only",
                "detail": ("the installed approval route does not forward a reason to "
                           "resolve_gateway_approval, so a typed reason never reaches the agent")}
    return {"native": False, "how": "absent",
            "detail": "the installed approval API exposes no reason parameter"}


def _resolve_gateway_accepts_reason() -> bool:
    """True when the installed ``resolve_gateway_approval`` accepts a ``reason``.

    The gateway source is read directly (never imported into this process) so the check
    is self-contained and cannot be fooled by an unrelated module on sys.path.
    """
    base = os.environ.get("HERMES_HOME") or os.path.join(
        os.environ.get("LOCALAPPDATA", "") or r"C:\Users\eMitchell109\AppData\Local",
        "hermes", "hermes-agent")
    for candidate in (os.path.join(base, "tools", "approval.py"),
                      r"C:\Users\eMitchell109\AppData\Local\hermes\hermes-agent\tools\approval.py"):
        try:
            if not os.path.isfile(candidate):
                continue
            with open(candidate, encoding="utf-8", errors="replace") as stream:
                text = stream.read()
        except OSError:
            continue
        index = text.find("def resolve_gateway_approval")
        if index < 0:
            continue
        end = text.find(") -> ", index)
        signature = text[index: end if end > index else index + 400]
        return "reason" in signature
    return False


_CAPABILITY_LOCK = threading.Lock()
_CAPABILITY: dict | None = None


def reason_capability(force: bool = False) -> dict:
    """Cached truth about native typed-reason delivery."""
    global _CAPABILITY
    with _CAPABILITY_LOCK:
        if _CAPABILITY is None or force:
            _CAPABILITY = detect_reason_support()
        return dict(_CAPABILITY)


def reset_capability_cache() -> None:
    global _CAPABILITY
    with _CAPABILITY_LOCK:
        _CAPABILITY = None


# --------------------------------------------------------------------------------------
# Validators and redaction
# --------------------------------------------------------------------------------------


class NativeRunClient:
    """Small HTTP seam; isolated tests substitute this without a real gateway."""

    def __init__(self, base: str = BASE, key: str | None = None):
        self.base = str(base).rstrip("/")
        self.key = key if key is not None else read_api_server_key()

    def get_run(self, run_id: str, timeout: float = 10) -> dict:
        return self._call("GET", f"/v1/runs/{run_id}", None, timeout=timeout)

    def post_approval(self, run_id: str, payload: dict, timeout: float = 20) -> dict:
        return self._call("POST", f"/v1/runs/{run_id}/approval", payload,
                          timeout=timeout, success=(200,))

    def post_steer(self, run_id: str, text: str, timeout: float = 20) -> dict:
        return self._call("POST", f"/v1/runs/{run_id}/steer", {"input": text},
                          timeout=timeout, success=(200,))

    def _call(self, method: str, path: str, payload: dict | None, *, timeout: float,
              success: tuple[int, ...] = (200,)) -> dict:
        if not self.key:
            raise DecisionError("The local Relay door has no agent API key.", 503)
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            self.base + path, data=data, method=method,
            headers={"Accept": "application/json",
                     "Authorization": "Bearer " + self.key,
                     "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                raw = response.read().decode("utf-8")
                return json.loads(raw or "{}")
        except urllib.error.HTTPError as exc:
            detail = ""
            try:
                body = json.loads(exc.read().decode("utf-8") or "{}")
                if isinstance(body, dict):
                    error = body.get("error")
                    if isinstance(error, dict):
                        detail = str(error.get("message") or error.get("code") or "")
                    elif isinstance(error, str):
                        detail = error
                    detail = detail or str(body.get("message") or body.get("code") or "")
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                detail = ""
            raise DecisionError(redact_text(detail) or f"The agent door returned {exc.code}.", exc.code) from None
        except urllib.error.URLError:
            raise DecisionError("The agent door is down.", 503) from None
        except TimeoutError:
            raise DecisionError("The agent door timed out.", 504) from None


def read_api_server_key() -> str:
    """Read the existing local key without logging or returning it to a browser."""
    value = os.environ.get("API_SERVER_KEY", "").strip().strip('"').strip("'")
    if value:
        return value
    candidates = [
        r"C:\Users\eMitchell109\AppData\Local\hermes\.env",
        os.path.join(os.environ.get("LOCALAPPDATA", ""), "hermes", ".env")
        if os.environ.get("LOCALAPPDATA") else "",
    ]
    for candidate in candidates:
        if not candidate:
            continue
        path = os.path.abspath(candidate)
        try:
            if not os.path.isfile(path):
                continue
            with open(path, encoding="utf-8") as stream:
                for line in stream:
                    if line.startswith("API_SERVER_KEY="):
                        value = line.split("=", 1)[1].strip().strip('"').strip("'")
                        if value:
                            return value
        except OSError:
            continue
    raise DecisionError("The local Relay door has no agent API key.", 503)


def validate_run_id(run_id: object) -> str:
    if not isinstance(run_id, str) or not run_id or any(c not in RUN_ID_CHARS for c in run_id):
        raise DecisionError("That is not a Relay run.")
    return run_id


def validate_request_id(request_id: object) -> str:
    if not isinstance(request_id, str) or not request_id or len(request_id) > REQUEST_ID_MAX:
        raise DecisionError("That approval request is invalid.")
    if any(not (c.isalnum() or c in "-_") for c in request_id):
        raise DecisionError("That approval request is invalid.")
    return request_id


def normalize_reason(value: object) -> str:
    if value in (None, ""):
        return ""
    if not isinstance(value, str):
        raise DecisionError("The denial reason must be text.")
    reason = " ".join(value.split())[:REASON_MAX].strip()
    return redact_text(reason)


def redact_text(value: object) -> str:
    """Mask known bearer material before display or audit output."""
    text = " ".join(str(value or "").split())
    try:
        secret = read_api_server_key()
    except DecisionError:
        secret = ""
    if secret:
        text = text.replace(secret, "[key]")
    return text


def choice_for(choice: object, allowed_choices: list[str]) -> str:
    value = str(choice or "").strip().lower()
    if value not in ALLOWED_CHOICES or value not in allowed_choices:
        raise DecisionError("That choice is not allowed for this approval.")
    if value == "session":
        raise DecisionError("Relay exposes only Allow once, Always allow, and Deny.")
    return value


# --------------------------------------------------------------------------------------
# Event normalisation
# --------------------------------------------------------------------------------------


def _pattern_and_scope(event: dict) -> tuple[str, str]:
    """The exact scope the native ``always`` choice would remember.

    The installed approval event carries the flags Hermes itself used to build its
    ``choices``; the remembered rule lives in the gateway's permanent allowlist keyed by
    the approval rule key. Relay never invents a broader scope than the event exposes.
    """
    pattern = str(event.get("pattern_key") or "").strip()
    if not pattern:
        # Fall back to the redacted command itself; never wider than what the owner sees.
        pattern = str(event.get("command") or "").strip()[:DISPLAY_COMMAND_MAX]
    if not pattern:
        return "", "the exact flagged action (no pattern key exposed)"
    scope = f"the exact pattern Hermes recorded: {pattern}"
    if bool(event.get("smart_denied")):
        scope += " (smart-denied: Hermes refuses repeats regardless of this choice)"
    return pattern, scope


def event_to_decision(event: object) -> dict | None:
    """Normalise one native approval.request event into a Relay card payload."""
    if not isinstance(event, dict) or event.get("event") != "approval.request":
        return None
    run_id = validate_run_id(event.get("run_id"))
    request_id = validate_request_id(event.get("request_id"))
    raw_choices = event.get("choices")
    if not isinstance(raw_choices, list) or not raw_choices:
        raise DecisionError("The agent door returned an approval with no allowed choices.", 502)
    choices: list[str] = []
    for value in raw_choices:
        choice = str(value or "").strip().lower()
        if choice in ALLOWED_CHOICES and choice not in choices:
            choices.append(choice)
    if not choices or "deny" not in choices:
        raise DecisionError("The agent door returned an approval with no safe deny choice.", 502)
    if not any(choice in choices for choice in ("once", "always")):
        raise DecisionError("The agent door returned an approval with no approval choice.", 502)
    owner_choices = [c for c in NATIVE_SCOPE_CHOICES if c in choices] + ["deny"]
    command = redact_text(event.get("command"))[:DISPLAY_COMMAND_MAX]
    description = redact_text(event.get("description"))[:DISPLAY_DESCRIPTION_MAX]
    pattern, scope = _pattern_and_scope(event)
    capability = reason_capability()
    return {
        "run_id": run_id,
        "request_id": request_id,
        "kind": "approval",
        "command": command or "(redacted request)",
        "description": description,
        "pattern_key": pattern,
        "scope": scope,
        "choices": owner_choices,
        "always_scope": (f"Always allow remembers only: {pattern}"
                         if pattern and "always" in owner_choices else ""),
        "reason_native": bool(capability.get("native")),
        "reason_note": capability.get("detail", ""),
        "received_at": event.get("created_at") or event.get("received_at") or time.time(),
        "identity": decision_identity(run_id, request_id, command, description),
        "state": "pending",
    }


def event_to_clarification(event: object) -> dict | None:
    """Normalise a native clarify request into a Relay clarification card.

    Ordinary clarification (the agent asking a question) is a different door from a
    dangerous-command permission: it carries no command, no pattern and no allow scope.
    """
    if not isinstance(event, dict):
        return None
    name = str(event.get("event") or "")
    if name not in {"clarify.request", "question.request", "clarify"}:
        return None
    run_id = validate_run_id(event.get("run_id"))
    request_id = validate_request_id(event.get("request_id") or f"clarify-{run_id}")
    question = redact_text(event.get("question") or event.get("text") or event.get("description"))
    if not question:
        return None
    return {
        "run_id": run_id,
        "request_id": request_id,
        "kind": "clarification",
        "question": question[:DISPLAY_DESCRIPTION_MAX],
        "scope": "an ordinary question from Echo — no command is waiting",
        "choices": ["answer"],
        "reason_native": False,
        "reason_note": "",
        "received_at": event.get("created_at") or time.time(),
        "identity": decision_identity(run_id, request_id, question, ""),
        "state": "pending",
    }


def decision_identity(run_id: str, request_id: str, command: str, description: str) -> str:
    payload = json.dumps([run_id, request_id, command, description],
                         ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:16]


# --------------------------------------------------------------------------------------
# Store
# --------------------------------------------------------------------------------------


class DecisionStore:
    """Thread-safe run ownership + pending approvals + exact-once decision ledger.

    Backed by the durable Relay store when one is supplied, so a pending approval and an
    already-sent decision survive a process restart. The in-memory mirrors keep the
    original Phase 1 contract intact for callers that do not pass a store.
    """

    def __init__(self, client=None, max_decisions: int = DECISION_CACHE_MAX,
                 store: relay_store.RelayStore | None = None):
        self.client = client or NativeRunClient()
        self.store = store
        self._lock = threading.RLock()
        self._runs: OrderedDict[str, dict] = OrderedDict()
        self._pending: dict[tuple[str, str], dict] = {}
        self._resolved: "OrderedDict[tuple[str, str], dict]" = OrderedDict()
        self._max_decisions = max(1, int(max_decisions))

    # -- ownership -----------------------------------------------------------------

    def associate_run(self, session_id: str, run_id: str, body: object = None) -> dict:
        session_id = str(session_id or "").strip()
        run_id = validate_run_id(run_id)
        if not relay_store.valid_room(session_id):
            raise DecisionError("That room is not a Relay room.")
        with self._lock:
            record = self._runs.get(run_id)
            if record is not None and record["session_id"] != session_id:
                raise DecisionError("That run belongs to another Relay room.", 409)
            if record is None:
                record = {"session_id": session_id, "run_id": run_id,
                          "body": normalize_submit_body(body), "decision": None,
                          "created_at": time.time()}
                self._runs[run_id] = record
        if self.store is not None:
            try:
                self.store.begin_run(run_id, session_id,
                                     body=str((body or {}).get("text", "")) if isinstance(body, dict) else "")
            except ValueError as exc:
                raise DecisionError(str(exc), 409)
        return {"run_id": run_id, "session_id": session_id}

    def room_of(self, run_id: str) -> str:
        """Server-side room guard for a run id; empty when Relay never recorded it."""
        with self._lock:
            record = self._runs.get(run_id)
            if record is not None:
                return record["session_id"]
        if self.store is not None:
            return self.store.run_room(run_id)
        return ""

    def selected_run(self, session_id: str) -> str:
        """The room's current run. A resolved decision does NOT hide the next one.

        Phase 1 bug fixed here: the old selector skipped any run that had already
        resolved a decision, so a second approval in the same room became
        unaddressable. Ownership, not decision state, is what selects a run.
        """
        with self._lock:
            for run_id, record in reversed(self._runs.items()):
                if record["session_id"] == session_id:
                    return run_id
        return ""

    def begin(self, run_id: str, body: dict | None = None) -> None:
        """Mark a Relay run as actively owning the decision lane."""
        run_id = validate_run_id(run_id)
        with self._lock:
            record = self._runs.get(run_id)
            if record is None:
                raise DecisionError("That run is not a Relay run.", 409)
            record.setdefault("state", "pending")
            if body:
                record["body"] = normalize_submit_body(body)

    # -- pending approvals ---------------------------------------------------------

    def accept_event(self, event: object) -> dict:
        decision = event_to_decision(event)
        if decision is None:
            raise DecisionError("That is not an approval decision request.")
        run_id, request_id = decision["run_id"], decision["request_id"]
        with self._lock:
            record = self._runs.get(run_id)
            if record is None:
                raise DecisionError("That approval run is not selected by Relay.", 409)
            if self.has_decision(run_id, request_id):
                raise DecisionError("That decision was already sent.", 409)
            self._pending[(run_id, request_id)] = decision
            record["state"] = "pending"
            record["last_approval"] = decision
        if self.store is not None:
            try:
                self.store.set_pending(run_id, request_id, json.dumps(decision, ensure_ascii=False))
            except Exception:
                pass
        return dict(decision)

    def accept_clarification(self, event: object) -> dict:
        card = event_to_clarification(event)
        if card is None:
            raise DecisionError("That is not a clarification request.")
        return dict(card)

    def pending_for(self, run_id: str, request_id: str) -> dict | None:
        with self._lock:
            value = self._pending.get((run_id, request_id))
            if value is not None:
                return dict(value)
        if self.store is not None:
            row = self.store.pending_request(run_id, request_id)
            if row:
                try:
                    return json.loads(row["payload"])
                except (TypeError, ValueError):
                    return None
        return None

    def pending_for_run(self, run_id: str) -> list[dict]:
        run_id = validate_run_id(run_id)
        with self._lock:
            found = [dict(v) for (pending_run, _), v in self._pending.items() if pending_run == run_id]
        if found or self.store is None:
            return found
        restored: list[dict] = []
        for row in self.store.pending(run_id):
            try:
                restored.append(json.loads(row["payload"]))
            except (TypeError, ValueError):
                continue
        if restored:
            with self._lock:
                for card in restored:
                    self._pending.setdefault((run_id, card.get("request_id", "")), card)
        return restored

    # -- decisions -----------------------------------------------------------------

    def has_decision(self, run_id: str, request_id: str) -> bool:
        with self._lock:
            if (run_id, request_id) in self._resolved:
                return True
        if self.store is not None and self.store.decision_for(run_id, request_id) is not None:
            return True
        return False

    def record_decision(self, run_id: str, request_id: str, choice: str, reason: str = "",
                        resolved: int = 1, reason_native: bool = False,
                        session_id: str = "") -> DecisionRecord:
        key = (run_id, request_id)
        record = DecisionRecord(run_id=run_id, request_id=request_id, choice=choice,
                                reason=reason, resolved=int(resolved),
                                reason_native=bool(reason_native))
        if self.store is not None:
            try:
                self.store.record_decision(run_id, request_id, choice, reason,
                                           session_id=session_id or self.room_of(run_id),
                                           reason_native=reason_native)
            except FileExistsError as exc:
                raise DecisionError(str(exc), 409)
        with self._lock:
            if key in self._resolved:
                raise DecisionError("That decision was already sent.", 409)
            run = self._runs.get(run_id)
            if run is not None:
                run["decision"] = record.as_dict()
                run["state"] = "resolved"
            self._resolved[key] = record.as_dict()
            self._pending.pop(key, None)
            self._resolved.move_to_end(key)
            while len(self._resolved) > self._max_decisions:
                self._resolved.popitem(last=False)
        return record

    def approval_decision(self, run_id: str, request_id: str, choice: object,
                          reason: object = None, *, allow_reason: bool = False) -> dict:
        """Resolve exactly one run/request approval; never resolve-all.

        ``allow_reason=True`` is the explicit typed-reason UI path. The reason is sent to
        the native API **only** when the installed endpoint really forwards it; otherwise
        it is kept Relay-local and the response says so out loud.
        """
        run_id = validate_run_id(run_id)
        request_id = validate_request_id(request_id)
        capability = reason_capability()
        with self._lock:
            record = self._runs.get(run_id)
            if record is None:
                raise DecisionError("That approval run is not selected by Relay.", 409)
            pending = self._pending.get((run_id, request_id))
            if pending is None:
                if self.has_decision(run_id, request_id):
                    raise DecisionError("That decision was already sent.", 409)
                raise DecisionError("That approval is no longer pending.", 409)
            allowed = list(pending["choices"])
            normalized = choice_for(choice, allowed)
            normalized_reason = normalize_reason(reason) if normalized == "deny" else ""
            if normalized_reason and not allow_reason:
                raise DecisionError("Use the typed-reason control for a denial reason.", 400)
        payload = {"choice": normalized, "request_id": request_id, "resolve_all": False}
        native_reason = bool(capability.get("native"))
        if normalized_reason and native_reason:
            payload["reason"] = normalized_reason
        try:
            response = self.client.post_approval(run_id, payload)
        except DecisionError as exc:
            message = str(exc).lower()
            if "approval_not_pending" in message or "no pending approval" in message:
                with self._lock:
                    self._pending.pop((run_id, request_id), None)
                if self.store is not None:
                    self.store.clear_pending(run_id, request_id)
            raise
        if int(response.get("resolved") or 0) <= 0:
            raise DecisionError("That approval is no longer pending.", 409)
        decision = self.record_decision(
            run_id, request_id, normalized, normalized_reason,
            resolved=int(response.get("resolved") or 1),
            reason_native=native_reason and bool(normalized_reason),
            session_id=record["session_id"])
        result = decision.as_dict()
        if normalized_reason and not native_reason:
            result["reason_native"] = False
            result["reason_note"] = (
                "kept in Relay only: the installed approval API does not accept a reason, "
                "so Echo is told the command was denied by user — not why")
        return result

    # -- clarification answer ------------------------------------------------------

    def answer_clarification(self, run_id: str, request_id: str, answer: object) -> dict:
        """Answer an ordinary clarification through the supported native steer door."""
        run_id = validate_run_id(run_id)
        text = " ".join(str(answer or "").split())
        if not text:
            raise DecisionError("Type an answer.", 400)
        if len(text) > 2000:
            raise DecisionError("Keep the answer under 2000 characters.", 400)
        with self._lock:
            record = self._runs.get(run_id)
            if record is None:
                raise DecisionError("That run is not selected by Relay.", 409)
        try:
            response = self.client.post_steer(run_id, text)
        except DecisionError as exc:
            if exc.status == 409:
                raise DecisionError("Echo is no longer waiting on that question.", 409)
            raise
        return {"run_id": run_id, "accepted": bool(response.get("accepted")), "answer": text[:200]}

    # -- snapshots -----------------------------------------------------------------

    def run_snapshot(self, run_id: str) -> dict:
        run_id = validate_run_id(run_id)
        pending = self.pending_for_run(run_id)
        with self._lock:
            record = self._runs.get(run_id)
            decision = record.get("decision") if record else None
            session_id = record["session_id"] if record else (self.room_of(run_id) or "")
            state = (record or {}).get("state") or "running"
        if pending:
            return {"state": "decision_blocked", "run_id": run_id, "session_id": session_id,
                    "pending": pending, "decision": decision}
        if decision:
            return {"state": "resolved", "run_id": run_id, "session_id": session_id,
                    "decision": decision, "pending": []}
        return {"state": state or "running", "run_id": run_id, "session_id": session_id,
                "pending": [], "decision": None}

    def current(self, session_id: str) -> dict:
        run_id = self.selected_run(session_id)
        if not run_id:
            return {"state": "idle", "run_id": ""}
        return self.run_snapshot(run_id)

    def submit(self, text: str, attachment: str | None, session_id: str | None,
               idempotency_key: str | None = None):
        raise NotImplementedError("Use relay_chat.submit, which calls associate_run().")


def normalize_submit_body(body: object) -> dict:
    if not isinstance(body, dict):
        return {}
    allowed = {"text", "attachment_present", "idempotency_key"}
    normalized = {}
    if isinstance(body.get("text"), str):
        normalized["text"] = body["text"][:1000]
    if bool(body.get("attachment_present")):
        normalized["attachment_present"] = True
    key = body.get("idempotency_key")
    if isinstance(key, str) and key:
        normalized["idempotency_key"] = key[:128]
    return {k: v for k, v in normalized.items() if k in allowed}


def snapshot_for_room(store: DecisionStore, session_id: str) -> dict:
    return store.current(session_id)


def probe_api(base: str | None = None, key: str | None = None) -> dict:
    """Auth/capability probe that does not create a run."""
    client = NativeRunClient(base or BASE, key)
    response = client._call("GET", "/v1/capabilities", None, timeout=10)
    features = response.get("features") if isinstance(response, dict) else {}
    features = features if isinstance(features, dict) else {}
    capability = reason_capability()
    return {
        "status": 200,
        "approval_events": bool(features.get("approval_events")),
        "run_approval_response": bool(features.get("run_approval_response")),
        "run_events_sse": bool(features.get("run_events_sse")),
        "runs_idempotency": features.get("runs_idempotency")
        if isinstance(features.get("runs_idempotency"), dict) else {},
        "approval_reason_native": bool(capability.get("native")),
        "approval_reason_detail": capability.get("detail", ""),
    }
