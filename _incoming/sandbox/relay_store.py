"""Durable Relay state: rooms, run ownership, decisions, sent keys, staged media.

Additive SQLite in the sandbox ``data`` directory. This file never touches the held
outbox rows (``rooms``/``turns``/``outbox`` in relay_sqlite_worker) and never calls
Onoes-Mind. ``relay-outbox.db`` stays exactly where the parent left it; Relay's own
state lives in a separate database so a schema change here cannot disturb held data.

Every write is scoped to a Relay room id (``relay-eddie-echo...``). Run ids are only
accepted for a room that the server itself recorded, so a browser cannot make Relay
adopt an arbitrary client-supplied run id.
"""
from __future__ import annotations

import os
import re
import sqlite3
import threading
import time
from pathlib import Path

DEFAULT_DB = Path(__file__).resolve().parent / "data" / "relay-state.db"
ROOM_RE = re.compile(r"^relay-eddie-echo(-[a-z0-9]{1,16})?$")
ROOM_PREFIX = "relay-eddie-echo"
# TS_CHECK mirrors the outbox schema style: a real UTC timestamp or nothing.
TS_CHECK = "GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]*Z'"

SCHEMA = f"""
CREATE TABLE IF NOT EXISTS relay_rooms (
    session_id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    created_at TEXT NOT NULL CHECK (created_at {TS_CHECK}),
    last_active REAL NOT NULL,
    archived INTEGER NOT NULL DEFAULT 0 CHECK (archived IN (0, 1))
) STRICT;
CREATE TABLE IF NOT EXISTS relay_runs (
    run_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    state TEXT NOT NULL,
    body TEXT NOT NULL DEFAULT '',
    transport TEXT NOT NULL DEFAULT 'runs',
    idempotency_key TEXT NOT NULL DEFAULT '',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
) STRICT;
CREATE INDEX IF NOT EXISTS relay_runs_room ON relay_runs (session_id, created_at);
CREATE TABLE IF NOT EXISTS relay_pending (
    run_id TEXT NOT NULL,
    request_id TEXT NOT NULL,
    payload TEXT NOT NULL,
    created_at REAL NOT NULL,
    PRIMARY KEY (run_id, request_id)
) STRICT;
CREATE TABLE IF NOT EXISTS relay_decisions (
    run_id TEXT NOT NULL,
    request_id TEXT NOT NULL,
    session_id TEXT NOT NULL DEFAULT '',
    choice TEXT NOT NULL,
    reason TEXT NOT NULL DEFAULT '',
    reason_native INTEGER NOT NULL DEFAULT 0 CHECK (reason_native IN (0, 1)),
    resolved_at REAL NOT NULL,
    PRIMARY KEY (run_id, request_id)
) STRICT;
CREATE TABLE IF NOT EXISTS relay_sent_keys (
    key TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    fingerprint TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('inflight', 'accepted', 'failed')),
    detail TEXT NOT NULL DEFAULT '',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
) STRICT;
CREATE TABLE IF NOT EXISTS relay_selected (
    session_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL DEFAULT '',
    updated_at REAL NOT NULL
) STRICT;
CREATE TABLE IF NOT EXISTS relay_media (
    file_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    name TEXT NOT NULL,
    mime TEXT NOT NULL,
    size INTEGER NOT NULL,
    sha256 TEXT NOT NULL,
    width INTEGER NOT NULL DEFAULT 0,
    height INTEGER NOT NULL DEFAULT 0,
    created_at REAL NOT NULL
) STRICT;
CREATE INDEX IF NOT EXISTS relay_media_room ON relay_media (session_id, created_at);
"""


def zulu(stamp: float | None = None) -> str:
    import datetime

    moment = (
        datetime.datetime.now(datetime.timezone.utc)
        if stamp is None
        else datetime.datetime.fromtimestamp(float(stamp), datetime.timezone.utc)
    )
    return moment.strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def valid_room(session_id: object) -> bool:
    return isinstance(session_id, str) and bool(ROOM_RE.match(session_id))


class RelayStore:
    """Thread-safe durable Relay state. One connection per call, short transactions."""

    def __init__(self, path: Path | str | None = None):
        self.path = Path(path) if path else Path(os.environ.get("RELAY_STATE_DB") or DEFAULT_DB)
        self._lock = threading.RLock()
        self._ensure()

    # -- plumbing -------------------------------------------------------------------

    def connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.path, timeout=20)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys = ON")
        try:
            db.execute("PRAGMA journal_mode = WAL")
        except sqlite3.DatabaseError:
            db.execute("PRAGMA journal_mode = DELETE")
        return db

    def _ensure(self) -> None:
        with self._lock:
            db = self.connect()
            try:
                db.executescript(SCHEMA)
                db.commit()
            finally:
                db.close()

    # -- rooms ----------------------------------------------------------------------

    def ensure_room(self, session_id: str, title: str = "") -> dict:
        if not valid_room(session_id):
            raise ValueError("Unknown room.")
        now = time.time()
        with self._lock:
            db = self.connect()
            try:
                db.execute("BEGIN IMMEDIATE")
                db.execute(
                    "INSERT OR IGNORE INTO relay_rooms (session_id, title, created_at, last_active, archived)"
                    " VALUES (?, ?, ?, ?, 0)",
                    (session_id, (title or session_id)[-60:], zulu(now), now),
                )
                if title:
                    db.execute(
                        "UPDATE relay_rooms SET title = ? WHERE session_id = ? AND title <> ?",
                        (title[-60:], session_id, title[-60:]),
                    )
                row = db.execute(
                    "SELECT session_id, title, archived FROM relay_rooms WHERE session_id = ?",
                    (session_id,),
                ).fetchone()
                db.commit()
            finally:
                db.close()
        return {"session_id": row["session_id"], "title": row["title"], "archived": bool(row["archived"])}

    def list_rooms(self) -> list[dict]:
        with self._lock:
            db = self.connect()
            try:
                rows = db.execute(
                    "SELECT session_id, title, archived, last_active FROM relay_rooms"
                    " ORDER BY last_active DESC, session_id"
                ).fetchall()
            finally:
                db.close()
        return [
            {"session_id": r["session_id"], "title": r["title"], "archived": bool(r["archived"]),
             "last_active": r["last_active"]}
            for r in rows
        ]

    def archive_room(self, session_id: str) -> None:
        """Archive a room. Existing rows are kept; nothing is deleted."""
        if not valid_room(session_id):
            raise ValueError("Unknown room.")
        with self._lock:
            db = self.connect()
            try:
                db.execute("UPDATE relay_rooms SET archived = 1 WHERE session_id = ?", (session_id,))
                db.commit()
            finally:
                db.close()

    def delete_empty_room(self, session_id: str) -> None:
        """Drop only the room row after /new checked its outbox and proactive rows."""
        if not valid_room(session_id):
            raise ValueError("Unknown room.")
        with self._lock:
            db = self.connect()
            try:
                db.execute(
                    "DELETE FROM relay_rooms WHERE session_id = ?"
                    " AND NOT EXISTS (SELECT 1 FROM relay_runs WHERE session_id = ?)"
                    " AND NOT EXISTS (SELECT 1 FROM relay_media WHERE session_id = ?)",
                    (session_id, session_id, session_id),
                )
                db.commit()
            finally:
                db.close()

    def touch_room(self, session_id: str) -> None:
        if not valid_room(session_id):
            return
        with self._lock:
            db = self.connect()
            try:
                db.execute(
                    "INSERT OR IGNORE INTO relay_rooms (session_id, title, created_at, last_active, archived)"
                    " VALUES (?, ?, ?, ?, 0)",
                    (session_id, session_id[-16:], zulu(), time.time()),
                )
                db.execute(
                    "UPDATE relay_rooms SET last_active = ? WHERE session_id = ?", (time.time(), session_id)
                )
                db.commit()
            finally:
                db.close()

    # -- selected room (server-backed) ----------------------------------------------

    def get_selected(self, client_hint: str = "") -> str:
        with self._lock:
            db = self.connect()
            try:
                row = db.execute("SELECT session_id FROM relay_selected LIMIT 1").fetchone()
            finally:
                db.close()
        stored = row["session_id"] if row else ""
        if valid_room(stored):
            return stored
        return client_hint if valid_room(client_hint) else ROOM_PREFIX + "-chat"

    def set_selected(self, session_id: str) -> str:
        """Server-backed active-room selection. One row, rewritten atomically."""
        if not valid_room(session_id):
            raise ValueError("Unknown room.")
        with self._lock:
            db = self.connect()
            try:
                db.execute("BEGIN IMMEDIATE")
                # Drop any historical rows so the table can never hold two answers.
                db.execute("DELETE FROM relay_selected")
                db.execute(
                    "INSERT INTO relay_selected (session_id, updated_at) VALUES (?, ?)",
                    (session_id, time.time()),
                )
                db.commit()
                row = db.execute("SELECT session_id FROM relay_selected LIMIT 1").fetchone()
            finally:
                db.close()
        return row["session_id"]

    # -- runs -----------------------------------------------------------------------

    def begin_run(
        self,
        run_id: str,
        session_id: str,
        *,
        body: str = "",
        transport: str = "runs",
        idempotency_key: str = "",
    ) -> dict:
        if not valid_room(session_id):
            raise ValueError("That room is not a Relay room.")
        now = time.time()
        with self._lock:
            db = self.connect()
            try:
                db.execute("BEGIN IMMEDIATE")
                row = db.execute("SELECT session_id FROM relay_runs WHERE run_id = ?", (run_id,)).fetchone()
                if row is not None and row["session_id"] != session_id:
                    db.rollback()
                    raise ValueError("That run belongs to another Relay room.")
                db.execute(
                    "INSERT OR IGNORE INTO relay_runs"
                    " (run_id, session_id, state, body, transport, idempotency_key, created_at, updated_at)"
                    " VALUES (?, ?, 'running', ?, ?, ?, ?, ?)",
                    (run_id, session_id, (body or "")[:2000], transport, idempotency_key or "", now, now),
                )
                db.execute(
                    "UPDATE relay_rooms SET last_active = ? WHERE session_id = ?", (now, session_id)
                )
                db.execute("INSERT OR IGNORE INTO relay_rooms (session_id, title, created_at, last_active, archived)"
                           " VALUES (?, ?, ?, ?, 0)", (session_id, session_id[-16:], zulu(now), now))
                # Only a run this server recorded may become the room's selected run.
                db.execute("DELETE FROM relay_selected")
                db.execute(
                    "INSERT INTO relay_selected (session_id, updated_at) VALUES (?, ?)", (session_id, now)
                )
                db.commit()
            finally:
                db.close()
        return {"run_id": run_id, "session_id": session_id}

    def run_room(self, run_id: str) -> str:
        """The Relay room that owns ``run_id``; empty when Relay never recorded it."""
        with self._lock:
            db = self.connect()
            try:
                row = db.execute("SELECT session_id FROM relay_runs WHERE run_id = ?", (run_id,)).fetchone()
            finally:
                db.close()
        return row["session_id"] if row else ""

    def update_run_state(self, run_id: str, state: str) -> None:
        with self._lock:
            try:
                db = self.connect()
            except (OSError, sqlite3.Error):
                return
            try:
                db.execute("UPDATE relay_runs SET state = ?, updated_at = ? WHERE run_id = ?",
                           (state, time.time(), run_id))
                db.commit()
            except sqlite3.Error:
                pass
            finally:
                db.close()

    def runs_for_room(self, session_id: str) -> list[dict]:
        with self._lock:
            db = self.connect()
            try:
                rows = db.execute(
                    "SELECT run_id, state, created_at, updated_at FROM relay_runs WHERE session_id = ?"
                    " ORDER BY created_at",
                    (session_id,),
                ).fetchall()
            finally:
                db.close()
        return [dict(r) for r in rows]

    def active_run(self, session_id: str) -> dict:
        """Latest non-terminal run recorded for a room; ``{}`` when the room is idle."""
        with self._lock:
            db = self.connect()
            try:
                row = db.execute(
                    "SELECT run_id, state, created_at, updated_at FROM relay_runs"
                    " WHERE session_id = ? AND state NOT IN ('completed', 'failed', 'cancelled',"
                    " 'interrupted', 'expired', 'unavailable')"
                    " ORDER BY created_at DESC LIMIT 1",
                    (session_id,),
                ).fetchone()
            finally:
                db.close()
        return dict(row) if row else {}

    # -- pending approvals ----------------------------------------------------------

    def set_pending(self, run_id: str, request_id: str, payload_json: str) -> None:
        with self._lock:
            db = self.connect()
            try:
                db.execute("BEGIN IMMEDIATE")
                db.execute("DELETE FROM relay_decisions WHERE run_id = ? AND request_id = ?", (run_id, request_id))
                db.execute(
                    "INSERT OR REPLACE INTO relay_pending (run_id, request_id, payload, created_at)"
                    " VALUES (?, ?, ?, ?)",
                    (run_id, request_id, payload_json, time.time()),
                )
                db.commit()
            finally:
                db.close()

    def pending(self, run_id: str) -> list[dict]:
        with self._lock:
            db = self.connect()
            try:
                rows = db.execute(
                    "SELECT request_id, payload, created_at FROM relay_pending WHERE run_id = ? ORDER BY created_at",
                    (run_id,),
                ).fetchall()
            finally:
                db.close()
        return [dict(r) for r in rows]

    def pending_request(self, run_id: str, request_id: str) -> dict | None:
        with self._lock:
            db = self.connect()
            try:
                row = db.execute(
                    "SELECT request_id, payload, created_at FROM relay_pending WHERE run_id = ? AND request_id = ?",
                    (run_id, request_id),
                ).fetchone()
            finally:
                db.close()
        return dict(row) if row else None

    def clear_pending(self, run_id: str, request_id: str) -> None:
        with self._lock:
            db = self.connect()
            try:
                db.execute("DELETE FROM relay_pending WHERE run_id = ? AND request_id = ?", (run_id, request_id))
                db.commit()
            finally:
                db.close()

    def record_decision(
        self,
        run_id: str,
        request_id: str,
        choice: str,
        reason: str = "",
        *,
        session_id: str = "",
        reason_native: bool = False,
    ) -> dict:
        """Record one exact-once decision. Returns the record; raises on a duplicate."""
        now = time.time()
        with self._lock:
            db = self.connect()
            try:
                db.execute("BEGIN IMMEDIATE")
                existing = db.execute(
                    "SELECT choice, reason, resolved_at FROM relay_decisions WHERE run_id = ? AND request_id = ?",
                    (run_id, request_id),
                ).fetchone()
                if existing is not None:
                    db.rollback()
                    raise FileExistsError("That decision was already sent.")
                db.execute("DELETE FROM relay_pending WHERE run_id = ? AND request_id = ?", (run_id, request_id))
                db.execute(
                    "INSERT INTO relay_decisions"
                    " (run_id, request_id, session_id, choice, reason, reason_native, resolved_at)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (run_id, request_id, session_id, choice, reason, 1 if reason_native else 0, now),
                )
                db.commit()
            finally:
                db.close()
        return {
            "run_id": run_id,
            "request_id": request_id,
            "choice": choice,
            "reason": reason,
            "reason_native": bool(reason_native),
            "resolved_at": now,
        }

    def decision_for(self, run_id: str, request_id: str) -> dict | None:
        with self._lock:
            db = self.connect()
            try:
                row = db.execute(
                    "SELECT run_id, request_id, choice, reason, reason_native, resolved_at FROM relay_decisions"
                    " WHERE run_id = ? AND request_id = ?",
                    (run_id, request_id),
                ).fetchone()
            finally:
                db.close()
        if row is None:
            return None
        out = dict(row)
        out["reason_native"] = bool(out["reason_native"])
        return out

    def decisions_for_room(self, session_id: str, limit: int = 50) -> list[dict]:
        with self._lock:
            db = self.connect()
            try:
                rows = db.execute(
                    "SELECT run_id, request_id, choice, reason, reason_native, resolved_at FROM relay_decisions"
                    " WHERE session_id = ? ORDER BY resolved_at DESC LIMIT ?",
                    (session_id, int(limit)),
                ).fetchall()
            finally:
                db.close()
        out = []
        for row in rows:
            item = dict(row)
            item["reason_native"] = bool(item["reason_native"])
            out.append(item)
        return out

    # -- sent keys (durable idempotent send) ----------------------------------------

    def sent_lookup(self, key: str) -> dict | None:
        with self._lock:
            db = self.connect()
            try:
                row = db.execute(
                    "SELECT key, session_id, run_id, fingerprint, state, detail, created_at FROM relay_sent_keys"
                    " WHERE key = ?",
                    (key,),
                ).fetchone()
            finally:
                db.close()
        return dict(row) if row else None

    def sent_begin(self, key: str, session_id: str, fingerprint: str) -> dict:
        """Insert an inflight row for a fresh key. Returns the winning row (the older one on a race)."""
        now = time.time()
        with self._lock:
            db = self.connect()
            try:
                db.execute("BEGIN IMMEDIATE")
                row = db.execute("SELECT * FROM relay_sent_keys WHERE key = ?", (key,)).fetchone()
                if row is None:
                    db.execute(
                        "INSERT INTO relay_sent_keys (key, session_id, run_id, fingerprint, state, created_at, updated_at)"
                        " VALUES (?, ?, '', ?, 'inflight', ?, ?)",
                        (key, session_id, fingerprint, now, now),
                    )
                    db.commit()
                    row = db.execute("SELECT * FROM relay_sent_keys WHERE key = ?", (key,)).fetchone()
                else:
                    db.rollback()
            finally:
                db.close()
        return dict(row)

    def sent_finish(self, key: str, run_id: str, state: str, detail: str = "") -> None:
        if state not in {"accepted", "failed"}:
            raise ValueError("Use accepted or failed.")
        with self._lock:
            db = self.connect()
            try:
                db.execute(
                    "UPDATE relay_sent_keys SET run_id = ?, state = ?, detail = ?, updated_at = ? WHERE key = ?",
                    (run_id, state, detail[:300], time.time(), key),
                )
                db.commit()
            finally:
                db.close()

    def sent_mark_failed(self, key: str, detail: str = "") -> None:
        with self._lock:
            db = self.connect()
            try:
                db.execute(
                    "UPDATE relay_sent_keys SET state = 'failed', detail = ?, updated_at = ?"
                    " WHERE key = ? AND state = 'inflight'",
                    (detail[:300], time.time(), key),
                )
                db.commit()
            finally:
                db.close()

    # -- staged media metadata ------------------------------------------------------

    def media_add(self, file_id: str, session_id: str, name: str, mime: str, size: int, sha256: str,
                  width: int = 0, height: int = 0) -> dict:
        if not valid_room(session_id):
            raise ValueError("Unknown room.")
        now = time.time()
        with self._lock:
            db = self.connect()
            try:
                db.execute(
                    "INSERT OR REPLACE INTO relay_media"
                    " (file_id, session_id, name, mime, size, sha256, width, height, created_at)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (file_id, session_id, name[:80], mime, int(size), sha256, int(width), int(height), now),
                )
                db.commit()
            finally:
                db.close()
        return self.media_get(file_id) or {}

    def media_get(self, file_id: str) -> dict | None:
        with self._lock:
            db = self.connect()
            try:
                row = db.execute("SELECT * FROM relay_media WHERE file_id = ?", (file_id,)).fetchone()
            finally:
                db.close()
        return dict(row) if row else None

    def media_for_room(self, session_id: str, limit: int = 100) -> list[dict]:
        with self._lock:
            db = self.connect()
            try:
                rows = db.execute(
                    "SELECT file_id, name, mime, size, width, height, created_at FROM relay_media"
                    " WHERE session_id = ? ORDER BY created_at DESC LIMIT ?",
                    (session_id, int(limit)),
                ).fetchall()
            finally:
                db.close()
        return [dict(r) for r in rows]


_STORE: RelayStore | None = None
_STORE_LOCK = threading.Lock()


def get_store() -> RelayStore:
    global _STORE
    with _STORE_LOCK:
        if _STORE is None:
            _STORE = RelayStore()
        return _STORE


def reset_store_for_tests(path: Path | str) -> RelayStore:
    """Point the module singleton at an isolated database (tests only)."""
    global _STORE
    with _STORE_LOCK:
        _STORE = RelayStore(path)
        return _STORE
