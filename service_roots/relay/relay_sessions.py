"""Small local conversation store for Relay.

Message bodies stay on this PC. Attachment contents are never stored; only the
display metadata already emitted by Relay is retained.
"""
from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

import relay_db


def _iso(value) -> str:
    """Coerce a datetime or string to the ISO form this store writes.

    Handing a `datetime` straight to sqlite3 hits the deprecated default adapter, which
    renders a *different* string -- space separator, local offset -- than the ISO form
    stored everywhere else. Comparisons then silently go wrong, which is the worst
    possible failure for a time-bounded query. Coercing in one place removes the whole
    class rather than the one instance that happened to warn.
    """
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat(timespec="seconds")
    return str(value)


def _now() -> str:
    """UTC, second resolution. Delegates so there is one timestamp convention.

    Phase 1.11: the store was already UTC, but as a private copy of the rule. Now
    the rule lives in `relay_db.utc_now` and the rest of the codebase can adopt the
    same one instead of agreeing with it by accident.
    """
    return relay_db.utc_now()


def _title(text: str) -> str:
    clean = " ".join(str(text).split())
    if not clean:
        return "New conversation"
    return clean[:48] + ("…" if len(clean) > 48 else "")


#: Retention policy, one entry per store (Phase 1.10). This table *is* the policy:
#: a store missing from it is unbounded by oversight, and the point of writing it down
#: is that "unbounded" becomes a decision instead of an accident.
#:
#: Both bounds are applied oldest-first. For the journal that is a correctness
#: requirement rather than tidiness: gap detection compares a resuming client against
#: the *global* minimum seq, which is only a truthful watermark while pruning removes
#: a contiguous prefix from the oldest end. A hole in the middle would make a client
#: that missed nothing look like it missed something, and one that missed something
#: look fine.
RETENTION: dict[str, dict] = {
    "events": {"max_rows": 200_000, "max_days": 180},
    "activity": {"max_rows": 20_000, "max_days": 365},
    "outbox": {"max_rows": 5_000, "max_days": 30,
               # Never pruned at any age: these are the rows that still need a person.
               # A dead or interrupted send is the last thing to throw away.
               "keep_states": ("dead", "retrying", "pending", "sending")},
    "messages": {"max_rows": None, "max_days": None,
                 "note": "conversation history -- kept indefinitely, by decision"},
    "sessions": {"max_rows": None, "max_days": None,
                 "note": "conversation index -- kept indefinitely, by decision"},
}


class SessionStore:
    #: Writes between opportunistic WAL checkpoints. SQLite's own auto-checkpoint
    #: cannot reclaim the log while Relay holds its one long-lived connection, which
    #: is how the live database reached a 4.1 MB WAL against a 360 KB database.
    CHECKPOINT_EVERY = 500

    #: Writes between retention passes. Retention costs a few MAX()/COUNT() queries, so
    #: it rides the same write counter as checkpointing rather than running on a timer.
    PRUNE_EVERY = 2000

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        # Connection hardening, schema creation and migrations all live in relay_db.
        # The inline DDL this replaced could create a schema and never change one:
        # `user_version` stayed 0 for the life of the deployment.
        self.db = relay_db.connect(self.path)
        self._writes = 0
        self.last_checkpoint: dict | None = None
        self.last_prune: dict | None = None
        # Reclaim whatever the previous process left behind. The old code never
        # checkpointed at all, so the first start after this ships is the one that
        # cleans up the backlog.
        self.checkpoint()
        self.prune()

    # ------------------------------------------------------------ durability --
    def checkpoint(self) -> dict:
        """Trim the write-ahead log. Never raises: a busy log is not a failure."""
        try:
            with self.lock:
                self.last_checkpoint = relay_db.checkpoint(self.db)
        except Exception:
            self.last_checkpoint = {"busy": None, "mode": "TRUNCATE",
                                    "log_pages": None, "checkpointed": None,
                                    "error": "checkpoint failed"}
        return self.last_checkpoint

    def _note_write(self) -> None:
        """Count writes toward the next checkpoint and the next retention pass."""
        self._writes += 1
        if self._writes % self.CHECKPOINT_EVERY == 0:
            self.checkpoint()
        if self._writes % self.PRUNE_EVERY == 0:
            self.prune()

    def durability_stats(self) -> dict:
        """Sizes and versions for health (1.5). Reports what is on disk."""
        out = relay_db.stats(self.path)
        out["schema_version"] = relay_db.schema_version(self.db)
        out["expected_schema_version"] = relay_db.SCHEMA_VERSION
        out["schema_current"] = out["schema_version"] == out["expected_schema_version"]
        try:
            with self.lock:
                out["journal_events"] = int(self.db.execute(
                    "SELECT COUNT(*) FROM events").fetchone()[0])
                out["journal_max_seq"] = int(self.db.execute(
                    "SELECT COALESCE(MAX(seq),0) FROM events").fetchone()[0])
        except Exception:
            out["journal_events"] = None
            out["journal_max_seq"] = None
        out["last_checkpoint"] = self.last_checkpoint
        return out

    def ensure_agent(self, agent_id: str, *, backend_key: str | None = None,
                     title: str | None = None) -> dict:
        with self.lock:
            row = self.db.execute(
                """SELECT s.* FROM sessions s JOIN active_sessions a
                   ON a.session_id=s.id WHERE a.agent_id=?""", (agent_id,)
            ).fetchone()
            if row:
                return dict(row)
            return self.create(agent_id, title=title or "New conversation",
                               backend_key=backend_key, activate=True)

    def create(self, agent_id: str, *, title: str = "New conversation",
               backend_key: str | None = None, activate: bool = True) -> dict:
        sid = str(uuid.uuid4())
        stamp = _now()
        with self.lock, self.db:
            self.db.execute(
                """INSERT INTO sessions
                   (id,agent_id,title,preview,backend_key,created_at,updated_at)
                   VALUES(?,?,?,?,?,?,?)""",
                (sid, agent_id, title, "", backend_key, stamp, stamp),
            )
            if activate:
                self.db.execute(
                    """INSERT INTO active_sessions(agent_id,session_id) VALUES(?,?)
                       ON CONFLICT(agent_id) DO UPDATE SET session_id=excluded.session_id""",
                    (agent_id, sid),
                )
        return self.get(agent_id, sid)

    def get(self, agent_id: str, session_id: str) -> dict:
        with self.lock:
            row = self.db.execute(
                "SELECT * FROM sessions WHERE agent_id=? AND id=?",
                (agent_id, session_id),
            ).fetchone()
        if not row:
            raise KeyError("conversation not found")
        return dict(row)

    def active(self, agent_id: str) -> dict:
        with self.lock:
            row = self.db.execute(
                """SELECT s.* FROM sessions s JOIN active_sessions a
                   ON a.session_id=s.id WHERE a.agent_id=?""", (agent_id,)
            ).fetchone()
        if not row:
            raise KeyError("active conversation not found")
        return dict(row)

    def activate(self, agent_id: str, session_id: str) -> dict:
        row = self.get(agent_id, session_id)
        with self.lock, self.db:
            self.db.execute(
                """INSERT INTO active_sessions(agent_id,session_id) VALUES(?,?)
                   ON CONFLICT(agent_id) DO UPDATE SET session_id=excluded.session_id""",
                (agent_id, session_id),
            )
        return row

    def list(self, agent_id: str) -> list[dict]:
        active_id = self.active(agent_id)["id"]
        with self.lock:
            rows = self.db.execute(
                """SELECT id,title,preview,backend_key,created_at,updated_at,last_read_seq
                   FROM sessions WHERE agent_id=? ORDER BY updated_at DESC""",
                (agent_id,),
            ).fetchall()
        return [{**dict(row), "active": row["id"] == active_id} for row in rows]

    def touch(self, agent_id: str, session_id: str, text: str) -> None:
        preview = " ".join(str(text).split())[:96]
        stamp = _now()
        with self.lock, self.db:
            row = self.db.execute(
                "SELECT title FROM sessions WHERE agent_id=? AND id=?",
                (agent_id, session_id),
            ).fetchone()
            if not row:
                raise KeyError("conversation not found")
            title = _title(text) if row["title"] == "New conversation" else row["title"]
            self.db.execute(
                """UPDATE sessions SET title=?,preview=?,updated_at=?
                   WHERE agent_id=? AND id=?""",
                (title, preview, stamp, agent_id, session_id),
            )

    def add_message(self, agent_id: str, session_id: str, role: str, content: str,
                    attachments: list | None = None) -> None:
        stamp = _now()
        encoded = json.dumps(attachments or [], separators=(",", ":"))
        with self.lock, self.db:
            self.db.execute(
                """INSERT INTO messages(session_id,role,content,attachments,created_at)
                   VALUES(?,?,?,?,?)""",
                (session_id, role, content, encoded, stamp),
            )
        self.touch(agent_id, session_id, content)
        self._note_write()

    def messages(self, agent_id: str, session_id: str, limit: int = 200) -> list[dict]:
        self.get(agent_id, session_id)
        with self.lock:
            rows = self.db.execute(
                """SELECT role,content,attachments,created_at FROM (
                     SELECT id,role,content,attachments,created_at FROM messages
                     WHERE session_id=? ORDER BY id DESC LIMIT ?
                   ) ORDER BY id""",
                (session_id, limit),
            ).fetchall()
        return [
            {"k": row["role"], "t": row["content"],
             "attachments": json.loads(row["attachments"]), "created_at": row["created_at"]}
            for row in rows
        ]

    def wire_history(self, agent_id: str, session_id: str, limit: int = 20) -> list[dict]:
        rows = self.messages(agent_id, session_id, limit)
        return [
            {"role": "user" if row["k"] == "you" else "assistant", "content": row["t"]}
            for row in rows if row["k"] in {"you", "ag"}
        ]

    # ------------------------------------------------------------ activity --
    MAX_ACTIVITY = 20000          # per database, pruned oldest-first
    _ACTIVITY_PRUNE_EVERY = 200   # inserts between prune passes

    def log_activity(self, agent_id: str, *, kind: str, name: str = "", status: str = "",
                     detail: str = "", duration_ms: int | None = None,
                     session_id: str | None = None, run_id: str | None = None) -> None:
        """Append one activity row. Never raises: logging must not break a run."""
        try:
            if isinstance(duration_ms, str):
                duration_ms = None
            with self.lock, self.db:
                self.db.execute(
                    """INSERT INTO activity
                       (agent_id,session_id,ts,kind,name,status,detail,duration_ms,run_id)
                       VALUES(?,?,?,?,?,?,?,?,?)""",
                    (agent_id, session_id, _now(), str(kind)[:32], str(name or "")[:120],
                     str(status or "")[:24], str(detail or "")[:600], duration_ms, run_id),
                )
                self._activity_writes = getattr(self, "_activity_writes", 0) + 1
                if self._activity_writes % self._ACTIVITY_PRUNE_EVERY == 0:
                    self.db.execute(
                        """DELETE FROM activity WHERE id <= (
                             SELECT id FROM activity ORDER BY id DESC
                             LIMIT 1 OFFSET ?)""",
                        (self.MAX_ACTIVITY,),
                    )
            self._note_write()
        except Exception:
            pass

    def activity(self, agent_id: str, *, limit: int = 200,
                 before_id: int | None = None) -> list[dict]:
        """Newest-first activity for one agent, optionally paging backwards."""
        try:
            raw = 200 if limit is None else int(limit)
        except (TypeError, ValueError):
            raw = 200
        limit = max(1, min(raw, 1000))
        params: list = [agent_id]
        where = "agent_id=?"
        if before_id:
            where += " AND id<?"
            params.append(int(before_id))
        params.append(limit)
        with self.lock:
            rows = self.db.execute(
                f"""SELECT id, session_id, ts, kind, name, status, detail, duration_ms, run_id
                    FROM activity WHERE {where} ORDER BY id DESC LIMIT ?""",
                params,
            ).fetchall()
        return [dict(row) for row in rows]

    def latest_activity_by_kind(self, agent_id: str, kind: str) -> dict | None:
        """Newest activity row of one kind -- the newest backup receipt (1.9)."""
        with self.lock:
            row = self.db.execute(
                """SELECT id, ts, name, status, detail FROM activity
                   WHERE agent_id=? AND kind=? ORDER BY id DESC LIMIT 1""",
                (agent_id, str(kind)[:32])).fetchone()
        return dict(row) if row else None

    def activity_count(self, agent_id: str) -> int:
        with self.lock:
            return int(self.db.execute(
                "SELECT COUNT(*) FROM activity WHERE agent_id=?", (agent_id,)
            ).fetchone()[0])

    # ------------------------------------------------------------- journal --
    # Phase 1.1. The live feed was in-memory only: `publish()` pushed dicts onto
    # per-subscriber queues with no sequence number, and the SSE stream carried no
    # `id:` field. A client that reconnected got a fresh snapshot and then whatever
    # happened next -- everything in between vanished, with nothing to say so.
    #
    # The journal is the ordering authority. `seq` is global and monotonic across the
    # whole database; `conv_seq` is per conversation, so one busy conversation cannot
    # renumber another. Both are assigned inside the caller's transaction, so a
    # reader never sees a gap that later fills in.

    def append_event(self, agent_id: str, type: str, payload: dict | None = None,
                     *, session_id: str | None = None,
                     idem_key: str | None = None) -> int:
        """Append one event. Returns its global `seq`.

        With an `idem_key`, a repeat returns the original `seq` and writes nothing --
        so a retried request cannot produce a second event. This is the durable
        counterpart of the in-memory receipt window in the server.
        """
        encoded = json.dumps(payload or {}, separators=(",", ":"), default=str)
        stamp = _now()
        with self.lock, self.db:
            if idem_key:
                row = self.db.execute(
                    "SELECT seq FROM events WHERE idem_key=?", (idem_key,)
                ).fetchone()
                if row:
                    return int(row["seq"])
            conv_seq = None
            if session_id:
                conv_seq = int(self.db.execute(
                    "SELECT COALESCE(MAX(conv_seq),0)+1 FROM events WHERE session_id=?",
                    (session_id,),
                ).fetchone()[0])
            cur = self.db.execute(
                """INSERT INTO events(conv_seq,session_id,agent_id,type,payload,ts,idem_key)
                   VALUES(?,?,?,?,?,?,?)""",
                (conv_seq, session_id, agent_id, str(type)[:48], encoded, stamp,
                 idem_key),
            )
            seq = int(cur.lastrowid)
        self._note_write()
        return seq

    def events_since(self, agent_id: str, after_seq: int, limit: int = 500) -> list[dict]:
        """Events for one agent strictly after `after_seq`, oldest first.

        The SSE resume read. Bounded by `limit` so a client returning after a long
        absence cannot pull an unbounded backlog in one request; the caller checks
        `has_more` and decides whether to page or to resync from a snapshot.
        """
        with self.lock:
            rows = self.db.execute(
                """SELECT seq,conv_seq,session_id,agent_id,type,payload,ts
                   FROM events WHERE agent_id=? AND seq>? ORDER BY seq LIMIT ?""",
                (agent_id, int(after_seq), max(1, min(int(limit), 5000))),
            ).fetchall()
        return [{"seq": int(r["seq"]), "conv_seq": r["conv_seq"],
                 "session_id": r["session_id"], "type": r["type"],
                 "payload": json.loads(r["payload"]), "ts": r["ts"]} for r in rows]

    def events_span(self, agent_id: str | None = None) -> dict:
        """Oldest and newest retained seq, for one agent or for the whole journal.

        Gap detection must use the **global** span, not the per-agent one. `seq` is
        global, so one agent's seqs are not contiguous -- if this agent's oldest
        retained event is seq 10 and a client asks for everything after 5, that is
        only safe when nothing below 10 was ever pruned. Retention prunes
        oldest-first across the whole journal, so `global min_seq` is the real
        watermark: a client resuming below it has provably missed events Relay no
        longer holds, and must be told rather than quietly given less history.
        """
        with self.lock:
            if agent_id:
                row = self.db.execute(
                    "SELECT COALESCE(MIN(seq),0) AS lo, COALESCE(MAX(seq),0) AS hi,"
                    " COUNT(*) AS n FROM events WHERE agent_id=?", (agent_id,)
                ).fetchone()
            else:
                row = self.db.execute(
                    "SELECT COALESCE(MIN(seq),0) AS lo, COALESCE(MAX(seq),0) AS hi,"
                    " COUNT(*) AS n FROM events"
                ).fetchone()
        return {"min_seq": int(row["lo"]), "max_seq": int(row["hi"]),
                "count": int(row["n"])}

    # ------------------------------------------------------------- outbox --
    # Phase 1.2. `message()` used to append to an in-memory queue after persisting
    # the message row. A crash between the two left a message that was stored,
    # displayed, and never sent -- with nothing recording that it had not been.
    # The rule now is: persist the intent first, then dispatch, then settle.

    OUTBOX_STATES = ("pending", "sending", "accepted", "failed", "retrying", "dead")
    MAX_ATTEMPTS = 5

    def outbox_enqueue(self, agent_id: str, session_id: str, content: str, *,
                       attachments: list | None = None, idem_key: str) -> dict:
        """Record the intent to send. Returns the existing row on a repeat key."""
        encoded = json.dumps(attachments or [], separators=(",", ":"))
        stamp = _now()
        with self.lock, self.db:
            row = self.db.execute(
                "SELECT * FROM outbox WHERE idem_key=?", (idem_key,)
            ).fetchone()
            if row:
                return dict(row)
            cur = self.db.execute(
                """INSERT INTO outbox(session_id,agent_id,content,attachments,idem_key,
                                      state,attempts,created_at,updated_at)
                   VALUES(?,?,?,?,?,'pending',0,?,?)""",
                (session_id, agent_id, content, encoded, idem_key, stamp, stamp),
            )
            oid = int(cur.lastrowid)
            row = self.db.execute("SELECT * FROM outbox WHERE id=?", (oid,)).fetchone()
        self._note_write()
        return dict(row)

    def outbox_claim(self, outbox_id: int) -> dict | None:
        """Move a row to `sending` and count the attempt. None if it is not claimable.

        Claiming is the commit point for "Relay is about to call the transport", so
        a row found in `sending` after a restart is a row whose outcome is unknown.
        """
        stamp = _now()
        with self.lock, self.db:
            cur = self.db.execute(
                """UPDATE outbox SET state='sending', attempts=attempts+1, updated_at=?
                   WHERE id=? AND state IN ('pending','retrying')""",
                (stamp, int(outbox_id)),
            )
            if cur.rowcount == 0:
                return None
            row = self.db.execute("SELECT * FROM outbox WHERE id=?",
                                  (int(outbox_id),)).fetchone()
        return dict(row)

    def outbox_settle(self, outbox_id: int, state: str, *,
                      transport_ref: str | None = None, error: str = "") -> dict | None:
        """Record the outcome. `accepted` means the transport took it, nothing more."""
        if state not in self.OUTBOX_STATES:
            raise ValueError(f"unknown outbox state {state!r}")
        stamp = _now()
        with self.lock, self.db:
            self.db.execute(
                """UPDATE outbox SET state=?, transport_ref=COALESCE(?,transport_ref),
                       error=?, updated_at=? WHERE id=?""",
                (state, transport_ref, str(error or "")[:600], stamp, int(outbox_id)),
            )
            row = self.db.execute("SELECT * FROM outbox WHERE id=?",
                                  (int(outbox_id),)).fetchone()
        return dict(row) if row else None

    def outbox_fail(self, outbox_id: int, error: str) -> dict | None:
        """Retry, or give up honestly once attempts are exhausted.

        A row that has exhausted its attempts becomes `dead` rather than disappearing
        or retrying forever: a stuck message the operator can see is worth more than a
        tidy queue that silently swallowed it.
        """
        stamp = _now()
        with self.lock, self.db:
            row = self.db.execute("SELECT attempts FROM outbox WHERE id=?",
                                  (int(outbox_id),)).fetchone()
            if not row:
                return None
            attempts = int(row["attempts"])
            nxt = "dead" if attempts >= self.MAX_ATTEMPTS else "retrying"
            self.db.execute(
                "UPDATE outbox SET state=?, error=?, updated_at=? WHERE id=?",
                (nxt, str(error or "")[:600], stamp, int(outbox_id)),
            )
            out = self.db.execute("SELECT * FROM outbox WHERE id=?",
                                  (int(outbox_id),)).fetchone()
        return dict(out) if out else None

    def outbox_recover(self) -> int:
        """Return interrupted sends to `pending`. Called once, at startup.

        Exit test 1.1 in one function: a row left in `sending` means Relay died
        between persisting the intent and learning the outcome. Relay cannot know
        whether the agent received it, so it must not silently drop it and must not
        silently duplicate it -- it marks it retrying and records why.
        """
        stamp = _now()
        with self.lock, self.db:
            cur = self.db.execute(
                """UPDATE outbox
                      SET state='retrying', updated_at=?,
                          error=CASE WHEN error='' THEN ? ELSE error END
                    WHERE state='sending'""",
                (stamp, "interrupted by a Relay restart; delivery outcome unknown"),
            )
            changed = int(cur.rowcount or 0)
        if changed:
            self._note_write()
        return changed

    def outbox_pending(self, agent_id: str | None = None, limit: int = 100) -> list[dict]:
        """Rows to (re)dispatch, oldest first."""
        sql = ("SELECT * FROM outbox WHERE state IN ('pending','retrying')")
        params: list = []
        if agent_id:
            sql += " AND agent_id=?"
            params.append(agent_id)
        sql += " ORDER BY id LIMIT ?"
        params.append(max(1, min(int(limit), 1000)))
        with self.lock:
            rows = self.db.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    def outbox_recent(self, agent_id: str | None = None, limit: int = 50) -> list[dict]:
        """Newest-first receipts across every state (1.4).

        `outbox_pending` answers "what still needs sending"; this answers "what
        happened to what I sent", including the dead ones -- which is the question
        worth being able to ask after something went wrong.
        """
        sql = "SELECT * FROM outbox"
        params: list = []
        if agent_id:
            sql += " WHERE agent_id=?"
            params.append(agent_id)
        sql += " ORDER BY id DESC LIMIT ?"
        params.append(max(1, min(int(limit), 500)))
        with self.lock:
            rows = self.db.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    def outbox_get(self, idem_key: str) -> dict | None:
        with self.lock:
            row = self.db.execute("SELECT * FROM outbox WHERE idem_key=?",
                                  (idem_key,)).fetchone()
        return dict(row) if row else None

    def outbox_counts(self) -> dict:
        """Per-state depth for health (1.5). Queue depth has to be visible."""
        with self.lock:
            rows = self.db.execute(
                "SELECT state, COUNT(*) AS n FROM outbox GROUP BY state").fetchall()
        counts = {s: 0 for s in self.OUTBOX_STATES}
        for row in rows:
            counts[str(row["state"])] = int(row["n"])
        counts["total"] = sum(counts[s] for s in self.OUTBOX_STATES)
        return counts

    # ---------------------------------------------------------- retention --
    # Phase 1.10. The journal is append-only and, until now, nothing bounded it.

    def _prune_prefix(self, table: str, key: str, spec: dict,
                      *, ts_column: str = "ts") -> int:
        """Delete a contiguous prefix of `table` from the oldest end.

        The cutoff is always expressed as a value of `key` -- a monotonic surrogate --
        even for the age rule, so age pruning cannot punch a hole in the middle. That
        is what keeps the journal's global `min_seq` an honest gap watermark.
        """
        cut = None
        max_rows = spec.get("max_rows")
        if max_rows:
            high = int(self.db.execute(
                f"SELECT COALESCE(MAX({key}),0) FROM {table}").fetchone()[0])
            if high > int(max_rows):
                cut = high - int(max_rows)
        max_days = spec.get("max_days")
        if max_days:
            row = self.db.execute(
                f"SELECT COALESCE(MAX({key}),0) FROM {table} WHERE {ts_column} < ?",
                (relay_db.utc_days_ago(max_days),)).fetchone()
            by_age = int(row[0])
            cut = by_age if cut is None else max(cut, by_age)
        if not cut:
            return 0
        cur = self.db.execute(f"DELETE FROM {table} WHERE {key} <= ?", (int(cut),))
        return int(cur.rowcount or 0)

    def _prune_outbox(self, spec: dict) -> int:
        """Prune settled receipts only. Rows still needing attention are never removed."""
        keep = tuple(spec.get("keep_states") or ())
        if not keep:
            return 0
        placeholders = ",".join("?" for _ in keep)
        where = f"state NOT IN ({placeholders})"
        settled = list(keep)
        cut = None
        max_days = spec.get("max_days")
        if max_days:
            row = self.db.execute(
                f"SELECT COALESCE(MAX(id),0) FROM outbox WHERE {where} AND updated_at < ?",
                settled + [relay_db.utc_days_ago(max_days)]).fetchone()
            cut = int(row[0]) or None
        max_rows = spec.get("max_rows")
        if max_rows:
            count = int(self.db.execute(
                f"SELECT COUNT(*) FROM outbox WHERE {where}", settled).fetchone()[0])
            if count > int(max_rows):
                row = self.db.execute(
                    f"SELECT id FROM outbox WHERE {where} ORDER BY id DESC LIMIT 1 OFFSET ?",
                    settled + [int(max_rows) - 1]).fetchone()
                if row:
                    by_count = int(row[0])
                    cut = by_count if cut is None else max(cut, by_count)
        if not cut:
            return 0
        cur = self.db.execute(
            f"DELETE FROM outbox WHERE id <= ? AND {where}", [int(cut)] + settled)
        return int(cur.rowcount or 0)

    def prune(self, *, now: str | None = None) -> dict:
        """Apply the retention policy. Returns rows removed per store.

        Never raises. Retention is housekeeping, and housekeeping that can take the
        chat down is worse than a table that grew a little.
        """
        removed: dict = {}
        try:
            with self.lock, self.db:
                removed["events"] = self._prune_prefix(
                    "events", "seq", RETENTION["events"], ts_column="ts")
                removed["outbox"] = self._prune_outbox(RETENTION["outbox"])
                # Activity's row bound is enforced inline in `log_activity`; only its
                # age bound is applied here, so the two do not fight over the same table.
                removed["activity"] = self._prune_prefix(
                    "activity", "id",
                    {"max_rows": None,
                     "max_days": RETENTION["activity"].get("max_days")},
                    ts_column="ts")
        except Exception as exc:
            removed["error"] = f"{type(exc).__name__}: {exc}"
        self.last_prune = {"at": now or _now(), "removed": removed}
        # Deliberately does NOT call `_note_write`: that counter can itself trigger a
        # prune pass, so counting a prune as a write would let the two recurse into
        # each other. A pruning pass does not need to advance the write counter.
        return removed

    def retention_stats(self) -> dict:
        """Per-store size plus the policy that bounds it (1.10), for health."""
        counts: dict = {}
        with self.lock:
            for table in ("sessions", "messages", "activity", "events", "outbox"):
                try:
                    counts[table] = int(self.db.execute(
                        f"SELECT COUNT(*) FROM {table}").fetchone()[0])
                except Exception:
                    counts[table] = None
        over = [name for name, spec in RETENTION.items()
                if spec.get("max_rows") and (counts.get(name) or 0) > spec["max_rows"]]
        return {"counts": counts, "policy": RETENTION,
                "over_threshold": over, "last_prune": self.last_prune}

    # ------------------------------------------------- read state (1.12) --
    # The column has existed since the Phase 1 migration; nothing wrote it. Read state
    # is derived from the journal's per-conversation sequence rather than tracked per
    # message, so it cannot drift out of step with the transcript.

    def mark_read(self, agent_id: str, session_id: str, seq: int | None = None) -> int:
        """Record how far a conversation has been read. Returns the new mark.

        With no `seq`, marks everything currently in the conversation as read -- which
        is what opening it means.
        """
        with self.lock, self.db:
            row = self.db.execute(
                "SELECT id FROM sessions WHERE agent_id=? AND id=?",
                (agent_id, session_id)).fetchone()
            if not row:
                raise KeyError("conversation not found")
            if seq is None:
                seq = int(self.db.execute(
                    "SELECT COALESCE(MAX(conv_seq),0) FROM events WHERE session_id=?",
                    (session_id,)).fetchone()[0])
            self.db.execute(
                "UPDATE sessions SET last_read_seq=? WHERE agent_id=? AND id=?",
                (int(seq), agent_id, session_id))
        return int(seq)

    def unread_count(self, agent_id: str, session_id: str) -> int:
        """Events newer than the read mark. Zero when there is nothing to catch up on.

        Returns 0 for a conversation that does not exist rather than raising: this is
        called while building a list, and one bad row must not fail the whole list.
        """
        with self.lock:
            row = self.db.execute(
                "SELECT last_read_seq FROM sessions WHERE agent_id=? AND id=?",
                (agent_id, session_id)).fetchone()
            if not row:
                return 0
            mark = int(row["last_read_seq"] or 0)
            return int(self.db.execute(
                "SELECT COUNT(*) FROM events WHERE session_id=? AND conv_seq>?",
                (session_id, mark)).fetchone()[0])

    # ------------------------------------------- cursor pagination (1.5) --
    def messages_page(self, agent_id: str, session_id: str, *, limit: int = 100,
                      before_id: int | None = None,
                      after_id: int | None = None) -> dict:
        """One window of a conversation, addressed by cursor rather than a fixed cap.

        `messages()` clamps to a fixed limit and silently discards the remainder, which
        is why the client could only ever see the newest window and never reach the
        rest of a long conversation. A cursor makes the whole transcript reachable:
        page backwards with `before_id`, forwards with `after_id`, and `has_more` says
        whether there is more in that direction.
        """
        self.get(agent_id, session_id)
        limit = max(1, min(int(limit or 100), 500))
        where = ["session_id=?"]
        params: list = [session_id]
        if before_id:
            where.append("id<?")
            params.append(int(before_id))
        if after_id:
            where.append("id>?")
            params.append(int(after_id))
        # Backwards paging walks newest-first so `LIMIT` takes the rows nearest the
        # cursor, then the window is flipped for display. Forwards paging is already
        # in reading order.
        order = "ASC" if after_id else "DESC"
        with self.lock:
            rows = self.db.execute(
                f"""SELECT id,role,content,attachments,created_at FROM messages
                    WHERE {' AND '.join(where)} ORDER BY id {order} LIMIT ?""",
                params + [limit + 1]).fetchall()
        has_more = len(rows) > limit
        rows = rows[:limit]
        if not after_id:
            rows = list(reversed(rows))
        return {
            "messages": [{"id": r["id"], "k": r["role"], "t": r["content"],
                          "attachments": json.loads(r["attachments"]),
                          "created_at": r["created_at"]} for r in rows],
            "has_more": has_more,
            "oldest_id": rows[0]["id"] if rows else None,
            "newest_id": rows[-1]["id"] if rows else None,
        }

    # ------------------------------------------------- notifications (2.x) --
    # Phase 2. The inbox is written for every notification whatever the other channels
    # do, because it is the record of truth for "was I told?" -- and a total channel
    # failure has to be visible rather than silent.

    def notify_record(self, agent_id: str, category: str, *, urgency: str,
                      title: str, body: str = "", deep_link: str = "",
                      session_id: str | None = None, event_seq: int | None = None,
                      dedup_key: str | None = None, state: str = "inbox",
                      deliver_at: str | None = None) -> tuple[dict, bool]:
        """Write one inbox row. Returns `(row, created)`.

        `created` is False when `dedup_key` has been seen before, which is the whole
        duplicate defence: same event, one notification, ever. It is a database
        uniqueness constraint rather than an in-memory set precisely so that it still
        holds across a Relay restart.
        """
        stamp = relay_db.utc_now()
        with self.lock, self.db:
            if dedup_key:
                row = self.db.execute(
                    "SELECT * FROM notifications WHERE dedup_key=?", (dedup_key,)
                ).fetchone()
                if row:
                    return dict(row), False
            cur = self.db.execute(
                """INSERT INTO notifications
                   (event_seq,agent_id,session_id,category,urgency,state,title,body,
                    deep_link,created_at,deliver_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                (event_seq, agent_id, session_id, str(category)[:32],
                 str(urgency)[:16], str(state)[:16], str(title)[:200],
                 str(body or ""), str(deep_link or ""), stamp, deliver_at),
            )
            new_id = int(cur.lastrowid)
            if dedup_key:
                self.db.execute("UPDATE notifications SET dedup_key=? WHERE id=?",
                                (dedup_key, new_id))
            row = self.db.execute("SELECT * FROM notifications WHERE id=?",
                                  (new_id,)).fetchone()
        self._note_write()
        return dict(row), True

    def notify_find(self, dedup_key: str) -> dict | None:
        """Look up an existing notification without writing anything.

        Deliberately separate from `notify_record`. An earlier version did the dedup
        check by *inserting*, which meant the real insert afterwards collided with the
        row it had just created and returned that half-built row -- so the notification
        was stored with an empty deep link and the caller's fields silently discarded.
        """
        if not dedup_key:
            return None
        with self.lock:
            row = self.db.execute(
                "SELECT * FROM notifications WHERE dedup_key=?", (dedup_key,)
            ).fetchone()
        return dict(row) if row else None

    def notifications_list(self, agent_id: str | None = None, *, limit: int = 50,
                           unread_only: bool = False,
                           include_states: tuple[str, ...] = ("inbox",)) -> list[dict]:
        """Newest-first inbox. Deferred rows are hidden until they are due."""
        sql = "SELECT * FROM notifications"
        where: list[str] = []
        params: list = []
        if agent_id:
            where.append("agent_id=?")
            params.append(agent_id)
        if include_states:
            where.append("state IN (%s)" % ",".join("?" for _ in include_states))
            params.extend(include_states)
        if unread_only:
            where.append("read_at IS NULL")
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY id DESC LIMIT ?"
        params.append(max(1, min(int(limit), 500)))
        with self.lock:
            rows = self.db.execute(sql, params).fetchall()
        return [dict(row) for row in rows]

    def notifications_mark_read(self, agent_id: str | None = None,
                                ids: list[int] | None = None) -> int:
        stamp = relay_db.utc_now()
        with self.lock, self.db:
            if ids:
                marks = ",".join("?" for _ in ids)
                cur = self.db.execute(
                    f"UPDATE notifications SET read_at=? WHERE read_at IS NULL AND id IN ({marks})",
                    [stamp] + [int(i) for i in ids])
            elif agent_id:
                cur = self.db.execute(
                    "UPDATE notifications SET read_at=? WHERE read_at IS NULL AND agent_id=?",
                    (stamp, agent_id))
            else:
                cur = self.db.execute(
                    "UPDATE notifications SET read_at=? WHERE read_at IS NULL", (stamp,))
        return int(cur.rowcount or 0)

    def notifications_due(self, *, now: str | datetime | None = None,
                          limit: int = 100) -> list[dict]:
        """Deferred notifications whose quiet-hours window has passed.

        `now` is coerced to the stored ISO form by `_iso`, so a caller may pass either.
        """
        stamp = _iso(now) if now is not None else relay_db.utc_now()
        with self.lock:
            rows = self.db.execute(
                """SELECT * FROM notifications
                   WHERE state='deferred' AND deliver_at IS NOT NULL AND deliver_at<=?
                   ORDER BY id LIMIT ?""",
                (stamp, max(1, min(int(limit), 500)))).fetchall()
        return [dict(row) for row in rows]

    def notification_mark(self, note_id: int, *, state: str,
                          delivery: dict | None = None,
                          delivered: bool = False) -> dict | None:
        stamp = relay_db.utc_now()
        encoded = json.dumps(delivery or {}, separators=(",", ":"), default=str)
        with self.lock, self.db:
            self.db.execute(
                """UPDATE notifications
                      SET state=?,
                          delivery=CASE WHEN ?='{}' THEN delivery ELSE ? END,
                          delivered_at=CASE WHEN ? THEN ? ELSE delivered_at END
                    WHERE id=?""",
                (str(state)[:16], encoded, encoded, 1 if delivered else 0, stamp,
                 int(note_id)))
            row = self.db.execute("SELECT * FROM notifications WHERE id=?",
                                  (int(note_id),)).fetchone()
        return dict(row) if row else None

    def notification_counts(self) -> dict:
        """Depth and recency for health (2.7)."""
        with self.lock:
            rows = self.db.execute(
                "SELECT state, COUNT(*) AS n FROM notifications GROUP BY state").fetchall()
            unread = int(self.db.execute(
                "SELECT COUNT(*) FROM notifications WHERE read_at IS NULL"
            ).fetchone()[0])
            last_ok = self.db.execute(
                """SELECT MAX(delivered_at) FROM notifications
                   WHERE delivered_at IS NOT NULL AND urgency='immediate'"""
            ).fetchone()[0]
            last_any = self.db.execute(
                "SELECT MAX(created_at) FROM notifications").fetchone()[0]
            last_fail = self.db.execute(
                """SELECT delivery, id FROM notifications
                   WHERE delivery LIKE '%"ok": false%' ORDER BY id DESC LIMIT 1"""
            ).fetchone()
        counts = {str(row["state"]): int(row["n"]) for row in rows}
        counts["total"] = sum(counts.values())
        return {"by_state": counts, "unread": unread,
                "last_delivered_at": last_ok, "last_created_at": last_any,
                "last_failure": (dict(last_fail) if last_fail else None)}

    def notification_set_link(self, note_id: int, link: str) -> dict | None:
        """Finalise a notification's deep link once its row id exists.

        The link wants the notification id, which is assigned by the insert -- so it
        cannot be built before it. Building it early produced `n=` empty, which lands
        the operator on the conversation and makes them hunt for the approval.
        """
        with self.lock, self.db:
            self.db.execute("UPDATE notifications SET deep_link=? WHERE id=?",
                            (str(link), int(note_id)))
            row = self.db.execute("SELECT * FROM notifications WHERE id=?",
                                  (int(note_id),)).fetchone()
        return dict(row) if row else None

    def notification_bump(self, note_id: int, *, title: str | None = None) -> dict | None:
        """Count one more repeat onto an existing notification (2.3 aggregation).

        Returns the updated row so the caller can re-dispatch it with the new count.
        """
        with self.lock, self.db:
            self.db.execute(
                """UPDATE notifications
                      SET aggregate_count = aggregate_count + 1,
                          title = COALESCE(?, title)
                    WHERE id=?""",
                (title, int(note_id)))
            row = self.db.execute("SELECT * FROM notifications WHERE id=?",
                                  (int(note_id),)).fetchone()
        return dict(row) if row else None

    def notification_recent_for_dedup(self, category: str, session_id: str | None,
                                      *, since: str, agent_id: str | None = None) -> list[dict]:
        """Rows used to apply per-category rate limits and repeat aggregation.

        Scoped by agent as well as conversation. Without the agent filter, two different
        agents' errors inside the rate window collapsed into a single notification --
        so a failure on Cyony was silently absorbed into Echo's message and the operator
        never learned Cyony was broken.
        """
        sql = ("SELECT * FROM notifications WHERE category=? AND created_at>=?")
        params: list = [str(category)[:32], _iso(since)]
        if agent_id:
            sql += " AND agent_id=?"
            params.append(agent_id)
        if session_id:
            sql += " AND session_id=?"
            params.append(session_id)
        sql += " ORDER BY id DESC LIMIT 50"
        with self.lock:
            rows = self.db.execute(sql, params).fetchall()
        return [dict(row) for row in rows]

    # --------------------------------------- push subscriptions (2.6) --
    # A subscription is the user agent's public key and auth secret for one device.
    # Both are secrets: the endpoint alone lets anyone send to the device, and the auth
    # secret is what makes a forged frame fail RFC 8291 authentication.

    def push_subscription_add(self, endpoint: str, p256dh: str, auth: str,
                              *, device: str = "") -> dict:
        """Register (or re-register) a device. Idempotent on the endpoint."""
        stamp = relay_db.utc_now()
        with self.lock, self.db:
            self.db.execute(
                """INSERT INTO push_subscriptions(endpoint,p256dh,auth,device,created_at)
                   VALUES(?,?,?,?,?)
                   ON CONFLICT(endpoint) DO UPDATE SET
                       p256dh=excluded.p256dh, auth=excluded.auth,
                       device=excluded.device, disabled_at=NULL, fail_count=0""",
                (str(endpoint), str(p256dh), str(auth), str(device or "")[:80], stamp))
            row = self.db.execute(
                "SELECT * FROM push_subscriptions WHERE endpoint=?",
                (str(endpoint),)).fetchone()
        self._note_write()
        return dict(row)

    def push_subscriptions(self, *, active_only: bool = True) -> list[dict]:
        sql = "SELECT * FROM push_subscriptions"
        if active_only:
            sql += " WHERE disabled_at IS NULL"
        sql += " ORDER BY id"
        with self.lock:
            rows = self.db.execute(sql).fetchall()
        return [dict(row) for row in rows]

    def push_subscription_mark(self, sub_id: int, *, ok: bool) -> dict | None:
        """Record a delivery attempt against one device."""
        stamp = relay_db.utc_now()
        with self.lock, self.db:
            if ok:
                self.db.execute(
                    """UPDATE push_subscriptions
                          SET last_ok_at=?, fail_count=0 WHERE id=?""",
                    (stamp, int(sub_id)))
            else:
                self.db.execute(
                    "UPDATE push_subscriptions SET fail_count=fail_count+1 WHERE id=?",
                    (int(sub_id),))
            row = self.db.execute("SELECT * FROM push_subscriptions WHERE id=?",
                                  (int(sub_id),)).fetchone()
        return dict(row) if row else None

    def push_subscription_disable(self, sub_id: int) -> dict | None:
        """Retire a device the push service has told us is gone (404/410).

        Remembered rather than deleted so health can show that a device dropped off
        instead of it silently disappearing from the list.
        """
        stamp = relay_db.utc_now()
        with self.lock, self.db:
            self.db.execute(
                "UPDATE push_subscriptions SET disabled_at=? WHERE id=?",
                (stamp, int(sub_id)))
            row = self.db.execute("SELECT * FROM push_subscriptions WHERE id=?",
                                  (int(sub_id),)).fetchone()
        return dict(row) if row else None

    def push_subscription_counts(self) -> dict:
        with self.lock:
            active = int(self.db.execute(
                "SELECT COUNT(*) FROM push_subscriptions WHERE disabled_at IS NULL"
            ).fetchone()[0])
            disabled = int(self.db.execute(
                "SELECT COUNT(*) FROM push_subscriptions WHERE disabled_at IS NOT NULL"
            ).fetchone()[0])
            last_ok = self.db.execute(
                "SELECT MAX(last_ok_at) FROM push_subscriptions").fetchone()[0]
        return {"active": active, "disabled": disabled, "last_ok_at": last_ok}

    def notifications_foldable(self, *, limit: int = 200) -> list[dict]:
        """Suppressed notifications waiting to be summarised into a digest (2.4).

        `suppressed` rows are the ones quiet hours held back. A separate `folded` state
        marks the ones already summarised, so a digest cannot fold the same event twice
        -- and no schema change is needed, because `state` is free-form text.
        """
        with self.lock:
            rows = self.db.execute(
                """SELECT * FROM notifications WHERE state='suppressed'
                   ORDER BY id LIMIT ?""",
                (max(1, min(int(limit), 1000)),)).fetchall()
        return [dict(row) for row in rows]

    def notifications_mark_folded(self, ids: list[int]) -> int:
        """Mark summarised rows so the next digest does not repeat them."""
        if not ids:
            return 0
        marks = ",".join("?" for _ in ids)
        with self.lock, self.db:
            cur = self.db.execute(
                f"UPDATE notifications SET state='folded' WHERE state='suppressed' "
                f"AND id IN ({marks})",
                [int(i) for i in ids])
        return int(cur.rowcount or 0)

    def close(self) -> None:
        with self.lock:
            self.db.close()
