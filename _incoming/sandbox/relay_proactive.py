"""Echo-originated proactive messages to Eddie, with a durable room-scoped replay log.

What this module is
-------------------
A *local, additive* door for the one owner-authorized proactive contact path:
``Echo -> Eddie`` in the one authorized room ``relay-eddie-echo-chat``.

What it is **not**
------------------
* It does **not** invent an Eddie prompt, a native Hermes user message, or edit any
  native/outbox message provenance. Nothing here writes ``relay-outbox.db`` or the
  native Hermes ``state.db``. Proactive rows live in their **own** table with their
  **own** id namespace (``msg-p-...``), so a proactive message can never be confused
  with, replace, or be silently re-attributed to a native turn.
* It does **not** expose a browser-reachable "publish as Echo" POST. The browser is
  already inside the same Host/Origin allowlist as the rest of Relay; an arbitrary
  publish route there would let any page that can reach this port mint authoritative
  Echo messages. Publishing is deliberately *not* an HTTP route. The only in-process
  callers are the local parent CLI (``python -B relay_proactive.py --publish ...``)
  and the parent agent's own local Python process, both of which must hold a
  loopback-bound capability token (see Security boundary below).

* It does **not** schedule, poll for idleness, or send Web Push. Idle detection and
  external push are later, separate tasks. There is no timer, no background thread,
  and no network egress in this file.

Security boundary — read this honestly
---------------------------------------
The publish door requires a capability token (``RELAY_PROACTIVE_TOKEN``), which is
**not** generated here, never printed, and never written to disk by this module. If
the environment variable is absent or does not match the configured value, publish
fails closed.

That token is a *convention*, not strong multi-agent adversarial authentication.
Authoring this task runs on the same Windows account, same OS user, same filesystem
as the target process. Any process running as that user can read the environment
variable, read the SQLite file directly, or simply call ``ProactiveStore.publish``
in-process. There is no OS ACL separation, no per-agent credential, and no
kernel-enforced boundary. Treat this as **cooperative discipline enforced at the
backend** (so a browser or a misbehaving client cannot forge Echo messages), not as
protection against another process that shares the account and is determined to
bypass it. Strong isolation would need a separate service account and an
authenticated channel, which is out of scope for this slice.

Durable replay / cursor contract
--------------------------------
Each accepted message gets a monotonically increasing per-store ``seq`` (dense,
starting at 1). Clients reconnect with ``?last_seq=<n>`` and receive every event
with ``seq > n`` up to a bounded ``limit``, in strict ``seq`` order. If the client
is further behind than the retained window (or the requested cursor predates the
oldest retained row), the server returns ``gap: true`` and the full retained
window; the client is expected to reconcile with a history read rather than assume
it saw everything. The log is capped: when it exceeds ``retention`` rows, the
oldest are dropped and ``truncated_before`` is reported. All ordering is by
``seq``; ``created_at`` is a UTC display timestamp (``...Z``) and is never used for
gap detection, so clock skew cannot create a false gap or a false dedupe.
"""
from __future__ import annotations

import os
import secrets
import sqlite3
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

ROOM = "relay-eddie-echo-chat"
AUTHOR = "Echo"
RECIPIENT = "Eddie"
ID_NAMESPACE = "msg-p-"
DEFAULT_DB = Path(__file__).resolve().parent / "data" / "relay-proactive.db"
# A publish key must be supplied by the operator. It is never minted, logged, or
# persisted by this module.
TOKEN_ENV = "RELAY_PROACTIVE_TOKEN"
MAX_TEXT = 2000
# The replay log is **not** a destructive history cap. 500 is only the *default*
# retention bound a ``ProactiveStore`` is constructed with; the durable default
# store is intentionally unbounded (``retention=None``), so every genuine
# Echo-originated message stays readable forever. Trimming is opt-in and only
# applies to an explicitly configured smaller retention.
DEFAULT_RETENTION = None
DEFAULT_READ_LIMIT = 200
# How long a single SSE cycle waits (bounded) for the next durable message before
# deciding nothing arrived and sending a heartbeat instead. A real condition wait,
# not a poll interval: it wakes the moment a publish signals the store.
PROACTIVE_WAIT_SECONDS = 20.0

TS_CHECK = (
    "GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]"
    "T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]*Z'"
)

SCHEMA = f"""
CREATE TABLE IF NOT EXISTS relay_proactive (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id TEXT NOT NULL UNIQUE,
    session_id TEXT NOT NULL,
    author TEXT NOT NULL CHECK (author = 'Echo'),
    recipient TEXT NOT NULL CHECK (recipient = 'Eddie'),
    body TEXT NOT NULL CHECK (length(body) > 0),
    created_at TEXT NOT NULL CHECK (created_at {TS_CHECK})
) STRICT;
"""


class ProactiveError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def zulu(stamp=None) -> str:
    """A real UTC timestamp ending in Z, or nothing."""
    if stamp is None:
        moment = datetime.now(timezone.utc)
    else:
        moment = datetime.fromtimestamp(float(stamp), timezone.utc)
    return moment.strftime("%Y-%m-%dT%H:%M:%S.%fZ")


class ProactiveStore:
    """Durable proactive log + bounded replay. One connection per call."""

    def __init__(self, path=None, retention=DEFAULT_RETENTION):
        self.path = Path(path) if path else Path(
            os.environ.get("RELAY_PROACTIVE_DB") or DEFAULT_DB)
        # ``None`` means unbounded (the durable default); an integer is an opt-in
        # bounded window. This is never a *destructive* cap on the client's view:
        # it only decides whether ``_trim`` is allowed to drop the oldest rows.
        self.retention = None if retention is None else max(1, int(retention))
        self._lock = threading.RLock()
        # One change-notification condition per store. A publish (or any writer on
        # this store) signals it; a bounded SSE reader waits on it between polls so
        # new messages arrive promptly without a tight loop and without any timer.
        self._changed = threading.Condition(self._lock)

    def connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.path, timeout=20)
        db.row_factory = sqlite3.Row
        db.isolation_level = None  # explicit BEGIN/COMMIT only; never leave a txn open
        db.execute("PRAGMA journal_mode = DELETE")
        db.executescript(SCHEMA)
        return db

    # -- validation (backend-enforced boundary) ------------------------------------

    @staticmethod
    def _validate_body(text) -> str:
        body = text.strip() if isinstance(text, str) else ""
        if not body:
            raise ProactiveError("A proactive message needs text.", 400)
        if len(body) > MAX_TEXT:
            raise ProactiveError(f"Keep the proactive message under {MAX_TEXT + 1} characters.", 400)
        return body

    @staticmethod
    def _validate_room(session_id) -> str:
        if session_id in (None, ""):
            return ROOM
        # A whitespace-altered identifier is refused, never silently repaired into
        # the authorized room. The comparison is exact, on purpose: only the literal
        # room id passes, so ``" relay-eddie-echo-chat "`` (or a tab/newline/case
        # variant) is rejected rather than being normalized into a match.
        if not isinstance(session_id, str) or session_id != ROOM:
            # The authorized proactive door serves exactly one room. Every other
            # author/recipient/room combination is rejected here, at the backend,
            # rather than being filtered in the UI.
            raise ProactiveError("Proactive contact is only authorized in the Eddie/Echo room.", 403)
        return ROOM

    # -- publish -------------------------------------------------------------------

    def publish(self, text, *, session_id=ROOM, message_id=None,
                author=AUTHOR, recipient=RECIPIENT, created_at=None) -> dict:
        """Persist one genuine Echo-originated message. Idempotent on ``message_id``.

        ``author``/``recipient`` are fixed at the backend. Any other value is refused
        outright — this is not a filter applied to caller input, it is the contract.
        """
        if author != AUTHOR:
            raise ProactiveError("Only Echo may author proactive contact.", 403)
        if recipient != RECIPIENT:
            raise ProactiveError("Proactive contact is only addressed to Eddie.", 403)
        room_id = self._validate_room(session_id)
        body = self._validate_body(text)
        if message_id is None:
            message_id = ID_NAMESPACE + secrets.token_hex(12)
        elif not isinstance(message_id, str) or not message_id.startswith(ID_NAMESPACE) \
                or len(message_id) <= len(ID_NAMESPACE) or not (0 < len(message_id) <= 64):
            raise ProactiveError("A proactive message id must be a msg-p- id.", 400)
        stamp = zulu(created_at)
        with self._lock:
            db = self.connect()
            try:
                db.execute("BEGIN IMMEDIATE")
                existing = db.execute(
                    "SELECT * FROM relay_proactive WHERE message_id = ?", (message_id,)).fetchone()
                if existing is not None:
                    db.rollback()
                    if existing["body"] != body or existing["session_id"] != room_id:
                        raise ProactiveError(
                            "That message id was already used for a different message.", 409)
                    return self._row(existing, replayed=True, message_id=message_id)
                db.execute(
                    "INSERT INTO relay_proactive"
                    " (message_id, session_id, author, recipient, body, created_at)"
                    " VALUES (?, ?, ?, ?, ?, ?)",
                    (message_id, room_id, author, recipient, body, stamp))
                row = db.execute(
                    "SELECT * FROM relay_proactive WHERE message_id = ?", (message_id,)).fetchone()
                self._trim(db)
                db.commit()
            except Exception:
                # Never leave a half-open transaction holding the file on Windows.
                try:
                    db.rollback()
                except sqlite3.Error:
                    pass
                raise
            finally:
                db.close()
            # Wake any bounded SSE reader so a genuinely new durable message is
            # delivered promptly. This happens *inside* the lock, so a reader that
            # just missed the notify re-checks ``latest_seq`` under the same lock
            # and cannot lose the message.
            self._changed.notify_all()
        payload = self._row(row, replayed=False, message_id=message_id)
        return payload

    def _trim(self, db) -> None:
        # Never trim when retention is unbounded (the default). This is what keeps
        # durable proactive messages readable forever instead of being destroyed
        # at a hard cap.
        if self.retention is None:
            return
        count = db.execute("SELECT COUNT(*) FROM relay_proactive").fetchone()[0]
        if count > self.retention:
            db.execute(
                "DELETE FROM relay_proactive WHERE seq IN"
                " (SELECT seq FROM relay_proactive ORDER BY seq ASC LIMIT ?)",
                (count - self.retention,))

    @staticmethod
    def _row(row, replayed=False, message_id=None) -> dict:
        return {
            "seq": int(row["seq"]),
            # The stable public identity is always the durable message_id (which the
            # caller may supply); it is never re-derived from the rowid.
            "id": message_id or row["message_id"],
            "message_id": row["message_id"],
            "session_id": row["session_id"],
            "author": row["author"],
            "recipient": row["recipient"],
            "text": row["body"],
            "created_at": row["created_at"],
            "replayed": bool(replayed),
        }

    # -- read / replay --------------------------------------------------------------

    def read(self, last_seq=-1, limit=DEFAULT_READ_LIMIT) -> dict:
        """Bounded, strictly ordered replay for a reconnecting client.

        Returns ``{"events": [...], "last_seq": n, "gap": bool, "truncated_before": n}``.
        ``gap`` means the caller's cursor predates the oldest retained row, so the
        caller cannot assume it has seen everything and should reconcile with history.
        """
        try:
            last_seq = int(last_seq)
        except (TypeError, ValueError):
            last_seq = -1
        limit = max(1, min(int(limit), DEFAULT_READ_LIMIT))
        with self._lock:
            db = self.connect()
            try:
                oldest = db.execute(
                    "SELECT MIN(seq) AS seq, COUNT(*) AS total FROM relay_proactive").fetchone()
                oldest_seq = oldest["seq"] if oldest["seq"] is not None else 0
                total = int(oldest["total"] or 0)
                rows = db.execute(
                    "SELECT * FROM relay_proactive WHERE seq > ? ORDER BY seq ASC LIMIT ?",
                    (last_seq, limit)).fetchall()
            finally:
                db.close()
        events = [self._row(row) for row in rows]
        # A gap only exists once the log is full enough that something was actually
        # trimmed away. With nothing trimmed, a -1 cursor simply means "from the
        # beginning", which is a complete read, not a gap.
        gap = bool(total) and oldest_seq > 1 and last_seq < oldest_seq - 1
        highest = events[-1]["seq"] if events else last_seq
        return {
            "session_id": ROOM,
            "events": events,
            "last_seq": int(highest),
            "gap": bool(gap),
            "truncated_before": int(oldest_seq) if total else 0,
            "count": len(events),
        }

    def latest_seq(self) -> int:
        with self._lock:
            db = self.connect()
            try:
                row = db.execute("SELECT MAX(seq) AS seq FROM relay_proactive").fetchone()
            finally:
                db.close()
        return int(row["seq"] or 0)

    def wait_for_next(self, last_seq: int, timeout: float) -> int:
        """Block (bounded) until the log grows past ``last_seq``. Returns the new high-water mark.

        Returns ``last_seq`` unchanged when the timeout elapses first, so the caller
        can distinguish "nothing new" (send a heartbeat) from "something arrived"
        (send the replay). This is a plain ``threading.Condition`` wait — no timer,
        no background thread, no polling loop — and it wakes as soon as a publish
        signals the store, so a genuinely new durable message is delivered promptly
        rather than on a fixed poll cadence.

        ``last_seq`` is only ever a *cursor*, never a filter: it tells the reader
        where to resume, and a stale or already-seen cursor can never make a newer
        message look like an older one.
        """
        try:
            last_seq = int(last_seq)
        except (TypeError, ValueError):
            last_seq = -1
        deadline = time.monotonic() + max(0.0, float(timeout))
        with self._changed:
            # Re-check under the lock before sleeping, so a message published
            # between the caller's last read and this call is not missed. The
            # double-call is cheap and both reads are serialized by the lock.
            if self.latest_seq() > last_seq:
                return self.latest_seq()
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return last_seq
                self._changed.wait(remaining)
                current = self.latest_seq()
                if current > last_seq:
                    return current

    def all_rows(self) -> list[dict]:
        with self._lock:
            db = self.connect()
            try:
                rows = db.execute("SELECT * FROM relay_proactive ORDER BY seq ASC").fetchall()
            finally:
                db.close()
        return [self._row(row) for row in rows]

    def count(self) -> int:
        with self._lock:
            db = self.connect()
            try:
                return int(db.execute("SELECT COUNT(*) FROM relay_proactive").fetchone()[0])
            finally:
                db.close()


# ----------------------------------------------------------------------------------
# Capability token. Not a secret generator: this only *checks* one the operator set.
# ----------------------------------------------------------------------------------

def configured_token() -> str:
    return os.environ.get(TOKEN_ENV, "").strip()


def check_publish_capability(presented) -> None:
    """Fail closed when no token is configured or the presented one does not match."""
    expected = configured_token()
    if not expected:
        raise ProactiveError(
            "Proactive publishing is not configured. Set RELAY_PROACTIVE_TOKEN first.", 503)
    if not isinstance(presented, str) or not presented or not secrets.compare_digest(
            presented.encode("utf-8"), expected.encode("utf-8")):
        raise ProactiveError("That publish capability is not accepted.", 403)


_STORE: ProactiveStore | None = None
_STORE_LOCK = threading.Lock()


def get_store() -> ProactiveStore:
    global _STORE
    with _STORE_LOCK:
        if _STORE is None:
            _STORE = ProactiveStore()
        return _STORE


def publish(text, *, token, session_id=ROOM, message_id=None, author=AUTHOR,
            recipient=RECIPIENT, created_at=None) -> dict:
    """The single sanctioned publish entry point. Checks capability, then persists."""
    check_publish_capability(token)
    return get_store().publish(text, session_id=session_id, message_id=message_id,
                               author=author, recipient=recipient, created_at=created_at)


def read(last_seq=-1, limit=DEFAULT_READ_LIMIT) -> dict:
    return get_store().read(last_seq=last_seq, limit=limit)


def wait_for_next(last_seq=-1, timeout=20.0) -> int:
    """Module-level bounded wait on the shared store's change notification."""
    return get_store().wait_for_next(last_seq=last_seq, timeout=timeout)


if __name__ == "__main__":  # pragma: no cover - exercised as a CLI, not a unit path
    import argparse
    import json as _json

    parser = argparse.ArgumentParser(
        description="Publish or read Echo-originated proactive messages (parent-local only).")
    sub = parser.add_subparsers(dest="command", required=True)

    pub = sub.add_parser("publish", help="publish one genuine Echo->Eddie message")
    pub.add_argument("--text", required=True)
    pub.add_argument("--room", default=ROOM)
    pub.add_argument("--message-id", default=None)

    readp = sub.add_parser("read", help="read the bounded replay log")
    readp.add_argument("--last-seq", type=int, default=-1)
    readp.add_argument("--limit", type=int, default=DEFAULT_READ_LIMIT)

    args = parser.parse_args()
    try:
        if args.command == "publish":
            print(_json.dumps(publish(args.text, token=configured_token(),
                                      session_id=args.room, message_id=args.message_id),
                              indent=2))
        else:
            print(_json.dumps(read(last_seq=args.last_seq, limit=args.limit), indent=2))
    except ProactiveError as error:
        raise SystemExit(f"{error.status}: {error}")
