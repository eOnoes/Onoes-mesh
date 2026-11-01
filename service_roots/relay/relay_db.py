"""Database bootstrap, migrations, and operational hardening for Relay.

Phase 1.6 / 1.7. Before this module existed the store created its tables with
`CREATE TABLE IF NOT EXISTS` and never recorded a schema version (`user_version`
was 0 on a database that had been live for weeks). That works exactly once: it can
create a schema, and it can never change one. Anything that needs to add a column
or a table to a database that already holds the operator's conversations had no
mechanism at all.

Two rules this module exists to enforce:

1. **Every schema change is a numbered, ordered, one-way step.** `user_version`
   records how far a database has come. A step runs once; re-running `migrate()` is
   a no-op. New steps are appended, never edited.
2. **Adopting an existing database is a migration like any other.** Relay's live
   database has data and `user_version = 0`. Step 1 is the historical schema written
   idempotently, so stamping an existing database and creating a fresh one are the
   same code path -- which means the upgrade path is exercised by every fresh install
   rather than only by the one machine that happens to be old.

Operational hardening (1.6) lives here too, because it has to be applied on every
connection rather than remembered at each call site:

- `journal_mode=WAL` -- concurrent reads during a write.
- `busy_timeout` -- before this, a competing writer produced an immediate
  `database is locked` instead of waiting. SQLite's default timeout is 5 seconds
  only via `sqlite3.connect(timeout=...)`, which the store passed as 0.75 s.
- `synchronous=NORMAL` -- the correct pairing with WAL: durable across application
  crashes, which is what the kill test exercises, without an fsync per commit.
- `foreign_keys=ON` -- per-connection in SQLite and therefore easy to lose.

**WAL checkpointing** is the fix for a live defect rather than a nicety. SQLite
checkpoints automatically at 1000 pages, but a long-lived reader -- and Relay holds
one connection for the life of the process -- can hold the WAL open indefinitely. The
live database had reached a **4.1 MB WAL against a 360 KB database**, and nothing ever
reclaimed it. `checkpoint()` truncates it; `wal_pages_after_checkpoint` in health
makes the growth visible instead of silent.
"""
from __future__ import annotations

import sqlite3
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

#: Schema version this build expects. Bump only by appending a migration below.
SCHEMA_VERSION = 4

#: Applied on every connection, in this order, outside any transaction.
#: `journal_mode` cannot change inside one, which is why the old code -- which set it
#: inside `with self.db:` -- was relying on the file header already saying WAL.
_PRAGMAS = (
    "PRAGMA journal_mode=WAL",
    "PRAGMA busy_timeout=5000",
    "PRAGMA synchronous=NORMAL",
    "PRAGMA foreign_keys=ON",
)


def utc_now() -> str:
    """Timestamp for storage. UTC, second resolution, ISO 8601.

    Phase 1.11: store UTC, render local. Rendering belongs to the UI; a stored
    timestamp is never local, because a stored local timestamp is unreadable the
    moment the machine changes timezone or the clock crosses a DST boundary.
    """
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def utc_days_ago(days: int) -> str:
    """UTC timestamp `days` in the past, in exactly the format `utc_now` produces.

    Same format and same offset means lexicographic string comparison is a valid
    date comparison, which is why retention compares timestamps as strings and never
    parses them back into datetimes.
    """
    return (datetime.now(timezone.utc)
            - timedelta(days=int(days))).isoformat(timespec="seconds")


# --------------------------------------------------------------------- steps --
# Step 1 -- the historical schema, verbatim from relay_sessions.SessionStore and
# written with IF NOT EXISTS so that adopting a live database and creating an empty
# one are the same operation. Do not edit: it has already run on the live database.
_STEP_1_BASELINE = """
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL,
    title TEXT NOT NULL,
    preview TEXT NOT NULL DEFAULT '',
    backend_key TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS sessions_agent_updated
    ON sessions(agent_id, updated_at DESC);
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    attachments TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS messages_session
    ON messages(session_id, id);
CREATE TABLE IF NOT EXISTS active_sessions (
    agent_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS activity (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id TEXT NOT NULL,
    session_id TEXT,
    ts TEXT NOT NULL,
    kind TEXT NOT NULL,
    name TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT '',
    detail TEXT NOT NULL DEFAULT '',
    duration_ms INTEGER,
    run_id TEXT
);
CREATE INDEX IF NOT EXISTS activity_agent_id
    ON activity(agent_id, id DESC);
CREATE INDEX IF NOT EXISTS activity_session
    ON activity(session_id, id);
"""

# Step 2 -- Phase 1.1 (event journal), 1.2 (durable outbox), 1.12 (read state).
#
# The journal is the backbone: SSE resume (1.3), gap detection, honest receipts
# (1.4), cursor pagination (1.5) and read state (1.12) all read from it. `seq` is a
# global monotonic cursor for the whole database; `conv_seq` is per conversation, so
# one conversation's ordering never depends on how busy another one was. Both are
# assigned inside the caller's transaction, so a reader can never observe a gap that
# later fills in.
_STEP_2_JOURNAL_AND_OUTBOX = """
CREATE TABLE IF NOT EXISTS events (
    seq        INTEGER PRIMARY KEY AUTOINCREMENT,
    conv_seq   INTEGER,
    session_id TEXT,
    agent_id   TEXT NOT NULL,
    type       TEXT NOT NULL,
    payload    TEXT NOT NULL DEFAULT '{}',
    ts         TEXT NOT NULL,
    idem_key   TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS events_idem
    ON events(idem_key) WHERE idem_key IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS events_conv_seq
    ON events(session_id, conv_seq) WHERE session_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS events_agent_seq
    ON events(agent_id, seq);
CREATE INDEX IF NOT EXISTS events_type_seq
    ON events(type, seq);

-- Durable outbox (1.2): a send is persisted BEFORE the transport is called, so a
-- crash between "user pressed send" and "agent acknowledged" cannot lose the
-- message. An interrupted row is recovered from its state, not from memory.
CREATE TABLE IF NOT EXISTS outbox (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id      TEXT NOT NULL,
    agent_id        TEXT NOT NULL,
    content         TEXT NOT NULL,
    attachments     TEXT NOT NULL DEFAULT '[]',
    idem_key        TEXT NOT NULL,
    state           TEXT NOT NULL,
    attempts        INTEGER NOT NULL DEFAULT 0,
    transport_ref   TEXT,
    error           TEXT NOT NULL DEFAULT '',
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    next_attempt_at TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS outbox_idem ON outbox(idem_key);
CREATE INDEX IF NOT EXISTS outbox_state ON outbox(state, next_attempt_at);
CREATE INDEX IF NOT EXISTS outbox_session ON outbox(session_id, id);
"""

#: Step 3 -- Phase 2.1/2.6/2.7: the durable notification inbox.
#:
#: The inbox is the record of truth for "was I told?", so it is written for *every*
#: notification regardless of whether any other channel succeeded. That is what makes a
#: total channel failure visible instead of silent, which is the whole point of 2.6:
#: silence is never the failure mode.
#:
#: `dedup_key` is unique and is the primary defence against duplicates. The policy doc
#: is explicit that this belongs with the event record rather than in the notifier, so
#: the key is derived from the journal event's identity: same event, one notification,
#: ever -- not "one per process lifetime", which is what an in-memory set would give.
_STEP_3_NOTIFICATIONS = """
CREATE TABLE IF NOT EXISTS notifications (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    event_seq    INTEGER,
    agent_id     TEXT NOT NULL,
    session_id   TEXT,
    category     TEXT NOT NULL,
    urgency      TEXT NOT NULL,
    state        TEXT NOT NULL DEFAULT 'inbox',
    title        TEXT NOT NULL,
    body         TEXT NOT NULL DEFAULT '',
    deep_link    TEXT NOT NULL DEFAULT '',
    created_at   TEXT NOT NULL,
    deliver_at   TEXT,
    delivered_at TEXT,
    read_at      TEXT,
    delivery     TEXT NOT NULL DEFAULT '{}',
    dedup_key    TEXT,
    -- Repeat aggregation: "3 runs failed" is one notification with a count, not three
    -- notifications. Defaults to 1 because a single event is already one occurrence.
    aggregate_count INTEGER NOT NULL DEFAULT 1
);
CREATE UNIQUE INDEX IF NOT EXISTS notifications_dedup
    ON notifications(dedup_key) WHERE dedup_key IS NOT NULL;
CREATE INDEX IF NOT EXISTS notifications_agent_id
    ON notifications(agent_id, id DESC);
CREATE INDEX IF NOT EXISTS notifications_pending
    ON notifications(state, deliver_at);
"""

#: Step 4 -- Phase 2.6: Web Push subscriptions.
#:
#: A subscription is a push endpoint plus the user agent's public key and auth secret,
#: which are what RFC 8291 needs to encrypt for that specific device. They are secrets
#: in their own right: anyone holding the endpoint can send to the device, and the auth
#: secret is what makes a forged frame fail.
#:
#: `disabled_at` exists so a subscription the push service has retired (404/410) is
#: remembered as gone rather than retried forever -- and so it is visible in health that
#: it happened, instead of the device silently dropping off the list.
_STEP_4_PUSH_SUBSCRIPTIONS = """
CREATE TABLE IF NOT EXISTS push_subscriptions (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    endpoint     TEXT NOT NULL,
    p256dh       TEXT NOT NULL,
    auth         TEXT NOT NULL,
    device       TEXT NOT NULL DEFAULT '',
    created_at   TEXT NOT NULL,
    last_ok_at   TEXT,
    fail_count   INTEGER NOT NULL DEFAULT 0,
    disabled_at  TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS push_subscriptions_endpoint
    ON push_subscriptions(endpoint);
"""

#: Ordered one-way migrations. Append only -- an entry that has run somewhere is
#: frozen, because editing it silently skips the change on every database that
#: already passed it.
MIGRATIONS: tuple[tuple[int, str], ...] = (
    (1, _STEP_1_BASELINE),
    (2, _STEP_2_JOURNAL_AND_OUTBOX),
    (3, _STEP_3_NOTIFICATIONS),
    (4, _STEP_4_PUSH_SUBSCRIPTIONS),
)

#: Columns added by ALTER rather than CREATE, applied once by the step that owns them.
#: SQLite has no `ADD COLUMN IF NOT EXISTS`, so presence is checked first.
_ADDED_COLUMNS: tuple[tuple[int, str, str, str], ...] = (
    # (step, table, column, declaration) -- 1.12 read state
    (2, "sessions", "last_read_seq", "INTEGER NOT NULL DEFAULT 0"),
)


def apply_pragmas(conn: sqlite3.Connection, *, attempts: int = 6) -> None:
    """Apply connection settings. Must not run inside a transaction.

    Pragmas are applied with a short retry, because of a failure the kill test found
    in the field: `PRAGMA journal_mode=WAL` can raise `disk I/O error` on a database
    whose previous process was hard-killed mid-write. SQLite has to recover the
    write-ahead log before it will touch the header, and the OS may still be releasing
    the dead process's file handles for a moment.

    The old behaviour -- fail immediately -- meant **Relay could refuse to start after
    a crash**, which is the one moment it most needs to come back. Losing that race is
    transient, so it is retried; and if `journal_mode` still cannot be re-stated, that
    is survivable rather than fatal, because the mode is persisted in the database
    header and was already WAL. The other pragmas are connection settings with no
    such excuse, so they still raise.
    """
    for pragma in _PRAGMAS:
        last: Exception | None = None
        for attempt in range(attempts):
            try:
                conn.execute(pragma)
                last = None
                break
            except sqlite3.OperationalError as exc:
                last = exc
                time.sleep(0.1 * (attempt + 1))
        if last is None:
            continue
        if pragma.strip().upper().startswith("PRAGMA JOURNAL_MODE"):
            continue
        raise last


def connect(path: str | Path) -> sqlite3.Connection:
    """Open the store: hardened, migratable, ready to use."""
    conn = sqlite3.connect(str(path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    apply_pragmas(conn)
    migrate(conn)
    return conn


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone() is not None


def migrate(conn: sqlite3.Connection, *, target: int | None = None) -> int:
    """Bring `conn` up to `target` (default `SCHEMA_VERSION`). Returns the version.

    Each step commits on its own. A failed step rolls back and leaves
    `user_version` where it was, so a half-applied migration is never recorded as
    applied -- the next start retries it rather than running the one after it.
    """
    want = SCHEMA_VERSION if target is None else int(target)
    current = int(conn.execute("PRAGMA user_version").fetchone()[0])
    if current >= want:
        return current

    for step, script in MIGRATIONS:
        if step <= current or step > want:
            continue
        try:
            conn.executescript(script)
            for owner, table, column, decl in _ADDED_COLUMNS:
                if owner != step:
                    continue
                if _table_exists(conn, table) and column not in _columns(conn, table):
                    conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")
            # `user_version` cannot be parameterised, and `step` is an int literal
            # from MIGRATIONS rather than anything caller-supplied.
            conn.execute(f"PRAGMA user_version={int(step)}")
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        current = step
    return current


def schema_version(conn: sqlite3.Connection) -> int:
    return int(conn.execute("PRAGMA user_version").fetchone()[0])


def checkpoint(conn: sqlite3.Connection, mode: str = "TRUNCATE") -> dict:
    """Fold the write-ahead log back into the database and truncate it.

    `TRUNCATE` (not `PASSIVE`) because the point is to reclaim the file: PASSIVE
    leaves the WAL at its high-water mark, which is exactly the state the live
    database was stuck in at 4.1 MB. A checkpoint cannot complete while another
    connection holds a read transaction, so a `busy` result is reported rather than
    treated as an error -- it means "try again later", not "something is broken".
    """
    mode = str(mode).upper()
    if mode not in {"PASSIVE", "FULL", "RESTART", "TRUNCATE"}:
        mode = "TRUNCATE"
    busy, log_pages, checkpointed = conn.execute(
        f"PRAGMA wal_checkpoint({mode})"
    ).fetchone()
    return {"busy": int(busy), "log_pages": int(log_pages),
            "checkpointed": int(checkpointed), "mode": mode}


def stats(path: str | Path) -> dict:
    """Sizes for health (1.5). Reports what is on disk, not what we hope is."""
    path = Path(path)
    out: dict = {"exists": path.is_file()}
    try:
        out["db_bytes"] = path.stat().st_size if path.is_file() else 0
    except OSError:
        out["db_bytes"] = 0
    wal = path.with_name(path.name + "-wal")
    shm = path.with_name(path.name + "-shm")
    for key, target in (("wal_bytes", wal), ("shm_bytes", shm)):
        try:
            out[key] = target.stat().st_size if target.is_file() else 0
        except OSError:
            out[key] = 0
    return out
