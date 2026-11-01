"""Relay run driver: one background native event pump per Relay run.

The API server's ``GET /v1/runs/{id}/events`` is a Server-Sent Events stream. Relay
opens exactly one reader per Relay run (started when the send is accepted), replays
from its own durable cursor, and publishes:

- approval requests (dangerous-command permission cards) the moment they appear;
- the run's final output when the stream ends.

If the pump dies (gateway restart, dropped socket) the reader resumes from the cursor
with bounded backoff, and the browser's status poll picks the run back up. There are
never two competing readers for one run: starting an existing run is a no-op.

Everything here talks to the loopback API server only, and never logs the key.
"""
from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request
from typing import Callable

import relay_decisions
import relay_events
import relay_store

TRANSIENT_STATUSES = relay_events.TRANSIENT_STATUSES


class RunDriverError(Exception):
    def __init__(self, message: str, status: int = 502, *, transient: bool = False):
        super().__init__(message)
        self.status = int(status)
        self.transient = bool(transient)


def _redact(text: object, secret: str) -> str:
    value = " ".join(str(text or "").split())
    if secret and secret in value:
        value = value.replace(secret, "[key]")
    return value


class _Pump:
    """One run's native event reader thread."""

    def __init__(self, run_id: str, session_id: str, base: str, key: str,
                 store: relay_store.RelayStore, on_approval: Callable[[dict], None] | None):
        self.run_id = run_id
        self.session_id = session_id
        self.base = base
        self.key = key
        self.store = store
        self.on_approval = on_approval
        self.lock = threading.RLock()
        self.output = ""
        self.error = ""
        self.status = "running"
        self.last_seq = -1
        self.reconnects = 0
        self.stop_flag = False
        self.thread: threading.Thread | None = None
        self.started_at = time.time()
        self.finished_at = 0.0

    # -- helpers --------------------------------------------------------------------

    def snapshot(self) -> dict:
        with self.lock:
            return {
                "run_id": self.run_id,
                "session_id": self.session_id,
                "status": self.status,
                "output": self.output,
                "error": self.error,
                "last_seq": self.last_seq,
                "reconnects": self.reconnects,
                "started_at": self.started_at,
                "finished_at": self.finished_at,
                "alive": bool(self.thread and self.thread.is_alive()),
            }

    def _native_status(self, run_id: str) -> str:
        request = urllib.request.Request(
            self.base + "/v1/runs/" + run_id,
            headers={"Accept": "application/json", "Authorization": "Bearer " + self.key},
            method="GET",
        )
        with urllib.request.urlopen(request, timeout=10) as response:
            body = json.loads(response.read().decode("utf-8") or "{}")
        return str(body.get("status") or "")

    def _handle(self, event: dict) -> None:
        name = str(event.get("event") or "")
        with self.lock:
            seq = event.get("seq")
            if isinstance(seq, int) and seq > self.last_seq:
                self.last_seq = seq
        if name == "approval.request":
            try:
                card = relay_decisions.event_to_decision(event)
            except relay_decisions.DecisionError:
                return
            if card is None:
                return
            self.store.set_pending(self.run_id, card["request_id"],
                                   json.dumps(card, ensure_ascii=False))
            self.store.update_run_state(self.run_id, relay_events.APPROVAL_STATUS)
            with self.lock:
                self.status = relay_events.APPROVAL_STATUS
            if self.on_approval:
                try:
                    self.on_approval(card)
                except Exception:
                    pass
            return
        if name in {"assistant.delta", "message.delta", "message.interim", "reasoning.available",
                    "tool.started", "tool.completed", "tool.failed", "tool.progress"}:
            return
        if name in {"assistant.complete", "message.complete"}:
            text = event.get("text") or event.get("content") or ""
            if isinstance(text, str) and text.strip():
                with self.lock:
                    self.output = text
            return
        if name in {"run.failed", "run.error"}:
            with self.lock:
                self.error = _redact(event.get("error") or event.get("message") or "The run failed.", self.key)
        if name in {"run.completed", "run.failed", "run.cancelled", "run.interrupted",
                    "run.expired", "run.unavailable"}:
            status = str(event.get("status") or name.split(".", 1)[1])
            with self.lock:
                self.status = status

    # -- the loop -------------------------------------------------------------------

    def _native_snapshot(self) -> dict:
        """Ask the API server for this run's pollable status once the stream is quiet."""
        request = urllib.request.Request(
            self.base + "/v1/runs/" + self.run_id,
            headers={"Accept": "application/json", "Authorization": "Bearer " + self.key},
            method="GET",
        )
        with urllib.request.urlopen(request, timeout=10) as response:
            return json.loads(response.read().decode("utf-8") or "{}")

    def run(self) -> None:
        while True:
            if self.stop_flag:
                break
            try:
                result = relay_events.pump_until_terminal(
                    self.base, self.key, self.run_id,
                    on_event=self._handle, last_seq=self.last_seq,
                    status_of=self._native_status)
            except relay_events.EventStreamError as exc:
                with self.lock:
                    self.reconnects += 1
                if not exc.transient:
                    # The stream is gone for good (e.g. after a gateway restart): fall
                    # back to the pollable status so a finished run is never stuck.
                    if self._absorb_native():
                        break
                    with self.lock:
                        if self.status not in relay_events.TERMINAL_STATUSES:
                            self.status = "failed"
                            self.error = str(exc)
                    break
                time.sleep(relay_events.backoff_delay(min(self.reconnects, 6)))
                continue
            except Exception as exc:  # pragma: no cover - defensive
                with self.lock:
                    self.reconnects += 1
                if self._absorb_native():
                    break
                with self.lock:
                    if self.status not in relay_events.TERMINAL_STATUSES:
                        self.status = "failed"
                        self.error = _redact(exc, self.key)
                break
            with self.lock:
                self.last_seq = max(self.last_seq, int(result.get("last_seq") or -1))
                if result.get("terminal"):
                    self.status = str(result.get("status") or self.status or "completed")
                    self.finished_at = time.time()
                    self.store.update_run_state(self.run_id, self.status)
                    break
            # Not terminal yet: the stream closed quietly (a long tool run, or the
            # gateway has not emitted a terminal event). Ask the pollable status once;
            # only a terminal answer ends the pump, otherwise we reconnect with backoff.
            if self._absorb_native():
                break
            with self.lock:
                self.reconnects += 1
            if self.stop_flag:
                break
            time.sleep(relay_events.backoff_delay(min(self.reconnects, 4)))
        if self.stop_flag:
            return
        with self.lock:
            if self.status not in relay_events.TERMINAL_STATUSES:
                self.status = "completed" if self.output else self.status or "completed"
                self.finished_at = time.time()
        self.store.update_run_state(self.run_id, self.status)

    def _absorb_native(self) -> bool:
        """Read the run's pollable status. True when it is terminal (or gone)."""
        try:
            body = self._native_snapshot()
        except Exception:
            return False
        native = str(body.get("status") or "")
        approval = body.get("approval")
        if native == relay_events.APPROVAL_STATUS and isinstance(approval, dict):
            try:
                self._handle(approval)
            except Exception:
                pass
            return False
        if native not in relay_events.TERMINAL_STATUSES:
            return False
        with self.lock:
            self.status = native
            if native == "completed":
                self.output = str(body.get("output") or self.output or "")
            else:
                self.error = _redact(body.get("error") or native, self.key)
            self.finished_at = time.time()
        self.store.update_run_state(self.run_id, native)
        return True


class RunRegistry:
    """Thread-safe registry of live pumps, keyed by Relay run id."""

    def __init__(self, store: relay_store.RelayStore, base: str, key: str,
                 on_approval: Callable[[dict], None] | None = None):
        self.store = store
        self.base = base.rstrip("/")
        self.key = key
        self.on_approval = on_approval
        self._lock = threading.RLock()
        self._pumps: dict[str, _Pump] = {}

    def start(self, run_id: str, session_id: str) -> dict:
        """Start the reader for a run this Relay server recorded. Idempotent."""
        with self._lock:
            existing = self._pumps.get(run_id)
            if existing is not None and (existing.thread and existing.thread.is_alive()):
                return existing.snapshot()
            pump = _Pump(run_id, session_id, self.base, self.key, self.store, self.on_approval)
            # Resume the cursor Relay already saw, so a reconnect replays no events twice.
            pending = self.store.pending(run_id)
            pump.last_seq = -1
            thread = threading.Thread(target=pump.run, name="relay-run-" + run_id[-12:], daemon=True)
            pump.thread = thread
            self._pumps[run_id] = pump
            thread.start()
            for row in pending:
                try:
                    payload = json.loads(row["payload"])
                except (TypeError, ValueError):
                    continue
                pump._handle(payload)
            return pump.snapshot()

    def snapshot(self, run_id: str) -> dict | None:
        with self._lock:
            pump = self._pumps.get(run_id)
        return pump.snapshot() if pump else None

    def stop(self, run_id: str) -> None:
        """Ask a pump to stop; it never blocks the caller."""
        with self._lock:
            pump = self._pumps.get(run_id)
        if pump is not None:
            pump.stop_flag = True

    def forget(self, run_id: str) -> None:
        with self._lock:
            self._pumps.pop(run_id, None)

    def live_count(self) -> int:
        with self._lock:
            return sum(1 for pump in self._pumps.values() if pump.thread and pump.thread.is_alive())
