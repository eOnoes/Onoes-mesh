"""Local Relay outbox. Copies Eddie and Echo text into a STRICT SQLite file.

This worker does not call Onoes-Mind. Rows stay held on lane B.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

HERMES_DB = Path(r"C:\Users\eMitchell109\AppData\Local\hermes\state.db")
OUTBOX_DB = Path(r"D:\Dev\Onoes-Mesh-sandbox\data\relay-outbox.db")
ROOM_PREFIX = "relay-eddie-echo"
LANE = "B"
SCOPE = "B:relay"
KIND = "relay_turn"
TS_CHECK = (
    "GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]"
    "T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]*Z'"
)

SCHEMA = f"""
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS rooms (
    session_id TEXT PRIMARY KEY,
    lane TEXT NOT NULL CHECK (lane IN ('A', 'B')),
    created_at TEXT NOT NULL CHECK (created_at {TS_CHECK})
) STRICT;
CREATE TABLE IF NOT EXISTS turns (
    id INTEGER PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES rooms(session_id),
    hermes_message_id INTEGER NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
    body TEXT NOT NULL CHECK (length(body) > 0),
    created_at TEXT NOT NULL CHECK (created_at {TS_CHECK}),
    UNIQUE (session_id, hermes_message_id)
) STRICT;
CREATE TABLE IF NOT EXISTS outbox (
    id INTEGER PRIMARY KEY,
    turn_id INTEGER NOT NULL UNIQUE REFERENCES turns(id),
    scope TEXT NOT NULL CHECK (scope = 'B:relay'),
    kind TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status = 'held'),
    created_at TEXT NOT NULL CHECK (created_at {TS_CHECK})
) STRICT;
"""


def zulu(stamp) -> str:
    if stamp is None:
        moment = datetime.now(timezone.utc)
    else:
        moment = datetime.fromtimestamp(float(stamp), timezone.utc)
    return moment.strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def connect_outbox() -> sqlite3.Connection:
    OUTBOX_DB.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(OUTBOX_DB)
    db.row_factory = sqlite3.Row
    # isolation_level=None: never leave an implicit transaction open on close, so
    # the database file is always fully released (no lingering -wal/-shm handles).
    db.isolation_level = None
    db.execute("PRAGMA foreign_keys = ON")
    try:
        db.execute("PRAGMA journal_mode = WAL")
    except sqlite3.DatabaseError:
        db.execute("PRAGMA journal_mode = DELETE")
    db.executescript(SCHEMA)
    return db


def source_turns() -> list[tuple]:
    uri = HERMES_DB.resolve().as_uri() + "?mode=ro"
    src = sqlite3.connect(uri, uri=True)
    try:
        return src.execute(
            """
            SELECT session_id, id, role, content, timestamp
            FROM messages
            WHERE session_id LIKE ? || '%'
              AND role IN ('user', 'assistant')
              AND content IS NOT NULL
              AND length(trim(content)) > 0
            ORDER BY session_id, id
            """,
            (ROOM_PREFIX,),
        ).fetchall()
    finally:
        src.close()


def sync() -> dict:
    now = zulu(None)
    rows = source_turns()
    db = connect_outbox()
    added = 0
    try:
        db.execute("BEGIN")
        for session_id, message_id, role, body, stamp in rows:
            db.execute(
                "INSERT OR IGNORE INTO rooms (session_id, lane, created_at) VALUES (?, ?, ?)",
                (session_id, LANE, now),
            )
            cur = db.execute(
                """
                INSERT OR IGNORE INTO turns
                    (session_id, hermes_message_id, role, body, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (session_id, int(message_id), role, body.strip(), zulu(stamp)),
            )
            if cur.rowcount != 1:
                continue
            turn_id = cur.lastrowid
            db.execute(
                """
                INSERT INTO outbox (turn_id, scope, kind, status, created_at)
                VALUES (?, ?, ?, 'held', ?)
                """,
                (turn_id, SCOPE, KIND, now),
            )
            added += 1
        db.execute("COMMIT")
        counts = {
            "added": added,
            "turns": db.execute("SELECT COUNT(*) FROM turns").fetchone()[0],
            "outbox": db.execute("SELECT COUNT(*) FROM outbox").fetchone()[0],
            "held": db.execute("SELECT COUNT(*) FROM outbox WHERE status = 'held'").fetchone()[0],
            "rooms": db.execute("SELECT COUNT(*) FROM rooms").fetchone()[0],
            "journal": db.execute("PRAGMA journal_mode").fetchone()[0],
        }
        return counts
    except Exception:
        db.execute("ROLLBACK")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    result = sync()
    print(
        "added {added} turns {turns} outbox {outbox} held {held} rooms {rooms} journal {journal}".format(
            **result
        )
    )
