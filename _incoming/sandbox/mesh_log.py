"""Append-only Mesh flag log.

Records which Mesh surface raised a known flag. Does not store chat text,
idempotency keys, or credentials.
"""
import re
import sqlite3
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DB = ROOT / "data" / "mesh-log.db"
SURFACES = {"relay", "todo", "config", "nav", "sw"}
KINDS = {"error", "flag"}
EVENTS = {
    ("relay", "flag", "delivery-uncertain", "reload-pending-flag"):
        "Reload found a pending-send flag and no reply in flight. Warning painted.",
    ("relay", "flag", "send-uncertain", "send-connection-lost"):
        "Send failed without a definite refusal. Pending flag kept.",
    ("relay", "error", "room-recovery-unavailable", "room-bootstrap-failed"):
        "Room state could not be read on open.",
}
_TRIGGER = re.compile(r"^[a-z0-9-]{1,64}$")


def record(surface, kind, code, trigger):
    key = (surface, kind, code, trigger)
    if key not in EVENTS or not isinstance(trigger, str) or not _TRIGGER.fullmatch(trigger):
        raise ValueError("Unknown Mesh log event.")
    DB.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB)
    try:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS mesh_log ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, "
            "surface TEXT NOT NULL, kind TEXT NOT NULL, code TEXT NOT NULL, "
            "trigger TEXT NOT NULL, detail TEXT NOT NULL)"
        )
        cur = conn.execute(
            "INSERT INTO mesh_log (ts, surface, kind, code, trigger, detail) VALUES (?, ?, ?, ?, ?, ?)",
            (time.strftime("%Y-%m-%dT%H:%M:%S%z"), surface, kind, code, trigger, EVENTS[key]),
        )
        conn.commit()
        return {"id": cur.lastrowid, "surface": surface, "kind": kind, "code": code, "trigger": trigger, "detail": EVENTS[key]}
    finally:
        conn.close()


def recent(limit=40):
    if not isinstance(limit, int) or not 1 <= limit <= 100:
        raise ValueError("Limit must be 1 to 100.")
    if not DB.exists():
        return []
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT id, ts, surface, kind, code, trigger, detail FROM mesh_log ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    finally:
        conn.close()
    return [dict(row) for row in rows]
