"""Native run event reader: SSE over HTTP with a resumable sequence cursor.

``GET /v1/runs/{run_id}/events`` on the installed Hermes API server is a Server-Sent
Events stream (``id:`` sequence frames), not a JSON document. This module parses it
without any third-party dependency, reconnects on transient failures with bounded
backoff, and replays from the last sequence it saw so an approval request is never
lost across a dropped connection.

Every failure raises ``EventStreamError`` with a user-facing message; callers decide
whether to retry. Nothing here approves anything or executes a command.
"""
from __future__ import annotations

import json
import socket
import time
import urllib.error
import urllib.request

TRANSIENT_STATUSES = {429, 500, 502, 503, 504}
BACKOFF_BASE = 0.5
BACKOFF_CAP = 8.0
CONNECT_TIMEOUT = 15.0
READ_TIMEOUT = 60.0


class EventStreamError(Exception):
    def __init__(self, message: str, *, transient: bool = True, status: int = 0):
        super().__init__(message)
        self.transient = bool(transient)
        self.status = int(status)


def backoff_delay(attempt: int) -> float:
    """Bounded exponential backoff: 0.5, 1, 2, 4, 8, 8, ... seconds."""
    return min(BACKOFF_CAP, BACKOFF_BASE * (2 ** max(0, int(attempt))))


def parse_sse_block(lines: list[str]) -> tuple[int | None, dict | None, str | None]:
    """Parse one SSE block into ``(id, json_event, comment)``."""
    event_id: int | None = None
    data_lines: list[str] = []
    comment: str | None = None
    for raw in lines:
        if raw.startswith(":"):
            comment = raw[1:].strip() or comment
            continue
        field, _, value = raw.partition(":")
        if value.startswith(" "):
            value = value[1:]
        if field == "id":
            try:
                event_id = int(value.strip())
            except ValueError:
                event_id = None
        elif field == "data":
            data_lines.append(value)
    if not data_lines:
        return event_id, None, comment
    joined = "\n".join(data_lines).strip()
    if not joined:
        return event_id, None, comment
    try:
        payload = json.loads(joined)
    except json.JSONDecodeError:
        return event_id, None, comment
    return event_id, (payload if isinstance(payload, dict) else None), comment


TERMINAL_STATUSES = frozenset(
    {"completed", "failed", "cancelled", "interrupted", "expired", "unavailable"}
)
# The API server's own vocabulary: a parked run waits for a decision, not a crash.
APPROVAL_STATUS = "waiting_for_approval"
# A run is "quiet" once its stream ends without a terminal event. The reader reconnects
# a bounded number of times before handing control back to the caller, so a run that
# never emits a terminal event cannot pin a reader thread forever.
QUIET_RECONNECT_LIMIT = 3


def read_events(base: str, key: str, run_id: str, *, last_seq: int = -1,
                is_terminal=None, max_seconds: float = 0.0, opener=None,
                sleep=time.sleep) -> dict:
    """Stream native run events until the run's terminal event or ``max_seconds``.

    ``max_seconds=0`` means no wall-clock cap (the 10-minute abandonment is gone); the
    reader stops when ``is_terminal(event)`` is true. Returns
    ``{"events": [...], "last_seq": int, "terminal": bool, "elapsed": float}``.
    ``last_seq`` is the highest sequence observed so a later call resumes without gaps.
    """
    started = time.time()
    cursor = int(last_seq)
    seen: list[dict] = []
    terminal = False
    attempt = 0
    do_open = opener or urllib.request.urlopen
    while not terminal:
        if max_seconds and time.time() - started > max_seconds:
            break
        request = urllib.request.Request(
            f"{base}/v1/runs/{run_id}/events?last_seq={cursor}",
            headers={
                "Accept": "text/event-stream",
                "Authorization": "Bearer " + key,
                "Cache-Control": "no-cache",
            },
            method="GET",
        )
        try:
            response = do_open(request, timeout=CONNECT_TIMEOUT)
        except urllib.error.HTTPError as exc:
            if exc.code in TRANSIENT_STATUSES:
                sleep(backoff_delay(attempt))
                attempt += 1
                continue
            raise EventStreamError(
                f"The agent door refused the event stream ({exc.code}).",
                transient=False, status=exc.code) from None
        except (urllib.error.URLError, TimeoutError, socket.timeout, OSError):
            sleep(backoff_delay(attempt))
            attempt += 1
            continue
        attempt = 0
        with response:
            content_type = response.headers.get("Content-Type", "")
            if "text/event-stream" not in content_type:
                raise EventStreamError(
                    "The agent door returned an unknown event stream.",
                    transient=False)
            buffer: list[str] = []
            while True:
                if max_seconds and time.time() - started > max_seconds:
                    break
                try:
                    raw = response.readline()
                except (TimeoutError, socket.timeout):
                    # A quiet stream is a healthy stream: reconnect with the cursor.
                    break
                except OSError:
                    break
                if not raw:
                    break
                line = raw.decode("utf-8", "replace").rstrip("\r\n")
                if line == "":
                    event_id, payload, comment = parse_sse_block(buffer)
                    buffer = []
                    if payload is None:
                        if comment == "stream closed":
                            terminal = True
                        continue
                    if event_id is not None:
                        if event_id <= cursor:
                            continue
                        cursor = event_id
                    payload.setdefault("seq", event_id if event_id is not None else cursor)
                    seen.append(payload)
                    if is_terminal and is_terminal(payload):
                        terminal = True
                        break
                    continue
                buffer.append(line)
        if terminal or (max_seconds and time.time() - started > max_seconds):
            break
        sleep(backoff_delay(attempt))
        attempt += 1
    return {"events": seen, "last_seq": cursor, "terminal": terminal, "elapsed": round(time.time() - started, 3)}


def fetch_events(base: str, key: str, run_id: str, *, last_seq: int = -1,
                 timeout: float = 6.0) -> dict:
    """One bounded read of whatever the event stream has right now (no blocking wait).

    Used by the polling path so a browser can ask ``what changed since N`` without a
    long-lived connection. Transient failures raise a retryable ``EventStreamError``.
    """
    return read_events(base, key, run_id, last_seq=last_seq, max_seconds=timeout)



def pump_until_terminal(base: str, key: str, run_id: str, *, on_event=None,
                        last_seq: int = -1, max_seconds: float = 0.0,
                        status_of=None, opener=None, sleep=time.sleep) -> dict:
    """Drive one run to a terminal event, forwarding each event to ``on_event``.

    ``status_of(run_id)`` optionally supplies the native run status so the reader also
    stops when the API reports a terminal status (the SSE stream may already be gone
    after a gateway restart). Returns the same shape as :func:`read_events` plus
    ``"status"``. Failures raise :class:`EventStreamError` after bounded backoff; the
    caller keeps whatever was already delivered.
    """
    started = time.time()
    cursor = int(last_seq)
    delivered: list[dict] = []
    status = ""
    attempt = 0
    quiet = 0
    do_open = opener or urllib.request.urlopen
    while True:
        if max_seconds and time.time() - started > max_seconds:
            break
        request = urllib.request.Request(
            f"{base}/v1/runs/{run_id}/events?last_seq={cursor}",
            headers={
                "Accept": "text/event-stream",
                "Authorization": "Bearer " + key,
                "Cache-Control": "no-cache",
            },
            method="GET",
        )
        try:
            response = do_open(request, timeout=CONNECT_TIMEOUT)
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                # The run is gone from the gateway: report the last known status.
                break
            if exc.code in TRANSIENT_STATUSES:
                sleep(backoff_delay(attempt))
                attempt += 1
                continue
            raise EventStreamError(
                f"The agent door refused the event stream ({exc.code}).",
                transient=False, status=exc.code) from None
        except (urllib.error.URLError, TimeoutError, socket.timeout, OSError):
            sleep(backoff_delay(attempt))
            attempt += 1
            continue
        attempt = 0
        with response:
            if "text/event-stream" not in response.headers.get("Content-Type", ""):
                raise EventStreamError("The agent door returned an unknown event stream.", transient=False)
            buffer: list[str] = []
            while True:
                try:
                    raw = response.readline()
                except (TimeoutError, socket.timeout):
                    break
                except OSError:
                    break
                if not raw:
                    break
                line = raw.decode("utf-8", "replace").rstrip("\r\n")
                if line != "":
                    buffer.append(line)
                    continue
                event_id, payload, comment = parse_sse_block(buffer)
                buffer = []
                if payload is None:
                    if comment == "stream closed":
                        status = _finish(status, run_id, status_of, delivered, on_event)
                        if status in TERMINAL_STATUSES:
                            return {"events": delivered, "last_seq": cursor, "terminal": True,
                                    "status": status, "elapsed": round(time.time() - started, 3)}
                        break
                    continue
                if event_id is not None:
                    if event_id <= cursor:
                        continue
                    cursor = event_id
                payload.setdefault("seq", event_id if event_id is not None else cursor)
                delivered.append(payload)
                if on_event:
                    try:
                        on_event(payload)
                    except Exception:
                        pass
                event_status = str(payload.get("status") or "")
                if event_status in TERMINAL_STATUSES:
                    return {"events": delivered, "last_seq": cursor, "terminal": True,
                            "status": event_status, "elapsed": round(time.time() - started, 3)}
        status = _finish(status, run_id, status_of, delivered, on_event)
        if status in TERMINAL_STATUSES:
            return {"events": delivered, "last_seq": cursor, "terminal": True,
                    "status": status, "elapsed": round(time.time() - started, 3)}
        quiet += 1
        if quiet > QUIET_RECONNECT_LIMIT:
            break
        sleep(backoff_delay(attempt))
        attempt += 1
    return {"events": delivered, "last_seq": cursor, "terminal": False,
            "status": status, "elapsed": round(time.time() - started, 3)}


def _finish(status: str, run_id: str, status_of, delivered: list, on_event) -> str:
    """Ask the API for the run's current status once the stream ends."""
    if not status_of:
        return status
    try:
        value = str(status_of(run_id) or "")
    except Exception:
        return status
    return value or status
