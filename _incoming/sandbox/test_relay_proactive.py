"""Isolated contracts for Echo-originated proactive messages.

Everything here runs against a temp SQLite file in a temp directory. No production
port, no held outbox row, no native Hermes ``state.db`` write, no external push, no
idle scheduler, and no live owner message is touched.

Provenance rules under test:
  * only Echo may author, only Eddie may receive, only the one authorized room
  * ``msg-p-`` ids never collide with, replace, or re-attribute ``msg-h-`` native ids
  * the publish door fails closed with no configured capability token
"""
from __future__ import annotations

import contextlib
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import relay_chat
import relay_proactive
from relay_proactive import ProactiveError, ProactiveStore

ROOM = "relay-eddie-echo-chat"
OTHER_ROOM = "relay-eddie-echo-other"


class ProactiveStoreTests(unittest.TestCase):
    """Every test uses its own store/file so nothing lingers between tests."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="relay-proactive-")
        self.addCleanup(self._tmp.cleanup)
        self._cwd = os.getcwd()
        os.chdir(self._tmp.name)
        self.path = Path("proactive.db")

    def tearDown(self):
        os.chdir(self._cwd)
        super().tearDown()

    def store(self, retention=5):
        return ProactiveStore("proactive.db", retention=retention)

    def publish(self, store, text="Echo has a question for you.", **kwargs):
        return store.publish(text, **kwargs)

    # -- backend-enforced author / recipient / room boundary ----------------------

    def test_only_echo_may_author(self):
        store = self.store()
        for bad in ("Eddie", "eEcho", "Echo ", "Cyony", "Trix", "", None):
            with self.assertRaises(ProactiveError) as caught:
                self.publish(store, author=bad)
            self.assertEqual(caught.exception.status, 403)
        self.assertEqual(store.count(), 0)

    def test_only_eddie_may_receive(self):
        store = self.store()
        for bad in ("Echo", "Cyony", "", None, "eddie"):
            with self.assertRaises(ProactiveError) as caught:
                self.publish(store, recipient=bad)
            self.assertEqual(caught.exception.status, 403)
        self.assertEqual(store.count(), 0)

    def test_only_the_authorized_room_is_accepted(self):
        store = self.store()
        row = self.publish(store)
        self.assertEqual(row["session_id"], ROOM)
        for bad in (OTHER_ROOM, "relay-eddie-echo", "relay", "not-a-room", "  "):
            with self.assertRaises(ProactiveError) as caught:
                self.publish(store, "another", session_id=bad)
            self.assertIn(caught.exception.status, (400, 403))
        self.assertEqual(store.count(), 1)

    def test_whitespace_altered_room_identifier_is_rejected_not_repaired(self):
        """A whitespace-altered identifier is never silently rewritten to the room.

        ``strip`` is only a null-presentation guard for ``None``/``""``; an actual
        ``" relay-eddie-echo-chat "`` (or a tab/newline variant) is refused rather
        than being normalized into the authorized room.
        """
        store = self.store()
        for bad in (" " + ROOM, ROOM + " ", "\t" + ROOM, ROOM + "\n",
                    ROOM.upper(), ROOM.replace("-", "_")):
            with self.assertRaises(ProactiveError) as caught:
                self.publish(store, "another", session_id=bad)
            self.assertEqual(caught.exception.status, 403)
        self.assertEqual(store.count(), 0)

    def test_empty_or_oversized_text_is_refused(self):
        store = self.store()
        for bad in ("", "   ", None, 42, "x" * (relay_proactive.MAX_TEXT + 1)):
            with self.assertRaises(ProactiveError):
                self.publish(store, bad)
        self.assertEqual(store.count(), 0)

    def test_message_id_must_live_in_the_proactive_namespace(self):
        store = self.store()
        with self.assertRaises(ProactiveError):
            self.publish(store, message_id="msg-h-1")
        with self.assertRaises(ProactiveError):
            self.publish(store, message_id="msg-p-")
        row = self.publish(store, message_id="msg-p-fixed0001")
        self.assertEqual(row["id"], "msg-p-fixed0001")

    # -- genuine provenance: UTC order, stable ids --------------------------------

    def test_rows_carry_genuine_provenance(self):
        store = self.store()
        row = self.publish(store)
        self.assertEqual(row["author"], "Echo")
        self.assertEqual(row["recipient"], "Eddie")
        self.assertEqual(row["session_id"], ROOM)
        self.assertTrue(row["id"].startswith("msg-p-"))
        self.assertTrue(row["created_at"].endswith("Z"))
        self.assertFalse(row["replayed"])
        with contextlib.closing(sqlite3.connect(self.path)) as db:
            columns = {r[1] for r in db.execute("PRAGMA table_info(relay_proactive)")}
        self.assertNotIn("role", columns)
        self.assertNotIn("hermes_message_id", columns)

    def test_ids_are_stable_and_seq_is_dense_and_monotonic(self):
        store = self.store()
        rows = [self.publish(store, f"m{i}") for i in range(4)]
        seqs = [r["seq"] for r in rows]
        self.assertEqual(seqs, sorted(seqs))
        self.assertEqual(len(set(seqs)), 4)
        for row in rows:
            self.assertTrue(row["id"].startswith("msg-p-"))
            window = store.read(last_seq=row["seq"] - 1)
            self.assertEqual(window["events"][0]["message_id"], row["message_id"])
            self.assertEqual(window["events"][0]["id"], row["id"])

    def test_same_id_survives_reconnect_replay(self):
        store = self.store()
        row = self.publish(store, message_id="msg-p-stable0001")
        replay = store.read(last_seq=row["seq"] - 1)["events"][0]
        self.assertEqual(replay["id"], "msg-p-stable0001")
        self.assertEqual(replay["id"], row["id"])

    def test_publish_is_idempotent_on_message_id(self):
        store = self.store()
        first = self.publish(store, message_id="msg-p-idem0001")
        again = self.publish(store, message_id="msg-p-idem0001")
        self.assertTrue(again["replayed"])
        self.assertEqual(first["seq"], again["seq"])
        self.assertEqual(store.count(), 1)
        with self.assertRaises(ProactiveError) as caught:
            self.publish(store, "different body", message_id="msg-p-idem0001")
        self.assertEqual(caught.exception.status, 409)

    def test_created_at_is_real_utc_and_ordering_follows_it(self):
        store = self.store()
        early = self.publish(store, "early", created_at=1_600_000_000)
        late = self.publish(store, "late", created_at=1_700_000_000)
        self.assertLess(early["created_at"], late["created_at"])
        self.assertTrue(early["created_at"].endswith("Z"))
        # seq order and created_at order agree for a real UTC clock.
        self.assertEqual([r["text"] for r in store.all_rows()], ["early", "late"])

    # -- bounded durable replay ----------------------------------------------------

    def test_replay_is_strictly_ordered_and_bounded(self):
        store = self.store(retention=100)
        for i in range(10):
            self.publish(store, f"m{i}")
        window = store.read(last_seq=3, limit=4)
        self.assertEqual([e["seq"] for e in window["events"]], [4, 5, 6, 7])
        self.assertEqual(window["last_seq"], 7)
        self.assertEqual(window["count"], 4)
        self.assertFalse(window["gap"])

    def test_replay_limit_is_clamped_not_honoured_blindly(self):
        store = self.store(retention=1000)
        for i in range(300):
            self.publish(store, f"m{i}")
        window = store.read(last_seq=-1, limit=10_000)
        self.assertLessEqual(window["count"], relay_proactive.DEFAULT_READ_LIMIT)
        self.assertGreater(window["count"], 0)

    def test_empty_log_reports_no_gap_and_no_events(self):
        store = self.store()
        window = store.read(last_seq=-1)
        self.assertEqual(window["events"], [])
        self.assertEqual(window["last_seq"], -1)
        self.assertFalse(window["gap"])
        self.assertEqual(window["truncated_before"], 0)

    def test_reconnect_with_current_cursor_replays_nothing(self):
        store = self.store()
        for i in range(3):
            self.publish(store, f"m{i}")
        latest = store.latest_seq()
        window = store.read(last_seq=latest)
        self.assertEqual(window["events"], [])
        self.assertEqual(window["last_seq"], latest)

    def test_cursor_gap_is_reported_and_full_window_returned(self):
        store = self.store()
        for i in range(10):
            self.publish(store, f"m{i}")
        # A retention of 5 has dropped seqs 1..5; a client at -1 must be told.
        window = store.read(last_seq=-1)
        self.assertTrue(window["gap"])
        self.assertEqual(window["truncated_before"], 6)
        self.assertEqual([e["seq"] for e in window["events"]], [6, 7, 8, 9, 10])
        # A client whose cursor is inside the retained window sees no gap.
        self.assertFalse(store.read(last_seq=7)["gap"])

    def test_durable_messages_past_the_default_retention_are_never_deleted(self):
        """Nothing is trimmed at the default retention; the replay log is not a cap.

        500 is the documented *default* retention, not a hard history cap. A store
        built with that default must keep every durable message so a reconnecting
        client can still replay the whole room conversation. Trimming only happens
        for a store explicitly configured with a smaller retention.
        """
        store = self.store(retention=relay_proactive.DEFAULT_RETENTION)
        for i in range(600):
            self.publish(store, f"m{i}")
        self.assertEqual(store.count(), 600)
        self.assertEqual([r["seq"] for r in store.all_rows()], list(range(1, 601)))
        # The very first message is still fully replayable — nothing was dropped.
        head = store.read(last_seq=-1, limit=1)["events"]
        self.assertEqual([e["seq"] for e in head], [1])
        self.assertEqual(head[0]["text"], "m0")
        # And a reconnecting cursor sees a contiguous window, never a gap.
        window = store.read(last_seq=598, limit=10)
        self.assertEqual([e["seq"] for e in window["events"]], [599, 600])
        self.assertFalse(window["gap"])

    def test_replay_pages_forward_without_destructive_history_cap(self):
        """Pagination walks the durable log in bounded pages; no page deletes rows."""
        store = self.store(retention=relay_proactive.DEFAULT_RETENTION)
        for i in range(520):
            self.publish(store, f"m{i}")
        seen = []
        cursor = -1
        pages = 0
        while True:
            window = store.read(last_seq=cursor, limit=200)
            events = window["events"]
            pages += 1
            self.assertLessEqual(len(events), 200)
            if not events:
                break
            seen.extend(e["seq"] for e in events)
            cursor = window["last_seq"]
            # Every page is a forward read: the log is never trimmed as we walk it.
            self.assertEqual(store.count(), 520)
        self.assertEqual(seen, list(range(1, 521)))
        self.assertEqual(len(seen), 520)
        # 200 + 200 + 120 = 520 in three bounded pages, plus one empty terminator
        # page to confirm the walk reached the end of the log.
        self.assertEqual(pages, 4)

    def test_bad_cursor_inputs_fall_back_instead_of_raising(self):
        store = self.store()
        self.publish(store, "m")
        for bad in (None, "abc", 1.5, object()):
            result = store.read(last_seq=bad)
            self.assertIn("events", result)
            self.assertEqual(result["last_seq"], 1)


class CapabilityTests(unittest.TestCase):
    def test_fails_closed_without_a_configured_token(self):
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop(relay_proactive.TOKEN_ENV, None)
            with self.assertRaises(ProactiveError) as caught:
                relay_proactive.publish("hi", token="anything")
        self.assertEqual(caught.exception.status, 503)

    def test_rejects_a_wrong_or_absent_presented_token(self):
        with patch.dict(os.environ, {relay_proactive.TOKEN_ENV: "right-token"}):
            for bad in ("", "wrong", None, "right-token "):
                with self.assertRaises(ProactiveError) as caught:
                    relay_proactive.publish("hi", token=bad)
                self.assertEqual(caught.exception.status, 403)

    def test_never_generates_or_prints_a_live_secret(self):
        source = Path(relay_proactive.__file__).read_text(encoding="utf-8")
        self.assertNotIn("token_hex(32)", source)
        self.assertIn("configured_token", source)


class HistoryMergeTests(unittest.TestCase):
    """relay_chat.history merges native turns and proactive rows without mutation."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="relay-merge-")
        self.addCleanup(self._tmp.cleanup)
        self._cwd = os.getcwd()
        os.chdir(self._tmp.name)
        tmp = Path(".")

        import relay_store
        import relay_sqlite_worker

        self.store = relay_store.RelayStore(tmp / "relay-state.db")
        self.proactive_store = ProactiveStore("proactive.db", retention=100)
        self.outbox_db = tmp / "outbox.db"
        # Native turns only, so nothing here depends on the (read-only) native DB.
        self.native = [
            (ROOM, 1, "user", "hello echo", 1_600_000_000),
            (ROOM, 2, "assistant", "hi eddie", 1_600_000_100),
        ]
        self._patches = [
            patch.object(relay_chat, "STORE", self.store),
            patch.object(relay_proactive, "_STORE", self.proactive_store),
            patch.object(relay_sqlite_worker, "OUTBOX_DB", self.outbox_db),
            patch.object(relay_sqlite_worker, "source_turns", side_effect=lambda: self.native),
        ]
        for item in self._patches:
            item.start()
            self.addCleanup(item.stop)
        # Windows keeps a temp directory locked while a DB handle is open; drop the
        # files explicitly so cleanup never races a lingering connection.
        self.addCleanup(self._wipe_dbs)

    def tearDown(self):
        os.chdir(self._cwd)
        super().tearDown()

    def _wipe_dbs(self):
        """Delete the store's own SQLite sidecar files before the temp dir is removed.

        ``connect_outbox`` sets ``journal_mode = WAL``, so the sidecars (``-wal`` /
        ``-shm``) exist and hold the only unflushed data. Deleting them releases the
        file handles so ``TemporaryDirectory.cleanup`` can remove the directory on
        Windows instead of hitting ``PermissionError: [WinError 32]``.
        """
        for path in ("relay-state.db", "proactive.db", "outbox.db"):
            for suffix in ("", "-wal", "-shm", "-journal"):
                try:
                    Path(path + suffix).unlink()
                except OSError:
                    pass

    def sync_native(self):
        """Materialise the native outbox rows the merge reads. No native DB is touched."""
        import relay_sqlite_worker
        relay_sqlite_worker.sync()

    def history(self):
        return relay_chat.history(ROOM)

    def test_native_ids_are_untouched_by_proactive_rows(self):
        self.sync_native()
        before = [(t["id"], t["who"], t["text"]) for t in self.history()["turns"]
                  if t["id"].startswith("msg-h-")]
        self.assertEqual(len(before), 2)
        relay_proactive.publish("Echo has a question for you.", token=self._token())
        after = self.history()["turns"]
        self.assertEqual([(t["id"], t["who"], t["text"]) for t in after if t["id"].startswith("msg-h-")], before)
        self.assertTrue(all(not t.get("proactive") for t in after if t["id"].startswith("msg-h-")))

    def test_proactive_rows_merge_in_utc_order_with_distinct_ids(self):
        self.sync_native()
        relay_proactive.publish("a question", token=self._token(), created_at=1_600_000_050)
        turns = self.history()["turns"]
        ids = [t["id"] for t in turns]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual([t["who"] for t in turns], ["Eddie", "Echo", "Echo"])
        stamps = [t["created_at"] for t in turns]
        self.assertEqual(stamps, sorted(stamps))
        proactive = [t for t in turns if t.get("proactive")]
        self.assertEqual(len(proactive), 1)
        self.assertEqual(proactive[0]["who"], "Echo")
        self.assertEqual(proactive[0]["text"], "a question")
        self.assertTrue(proactive[0]["id"].startswith("msg-p-"))

    def test_proactive_rows_never_become_an_eddie_prompt(self):
        relay_proactive.publish("Echo has a question for you.", token=self._token())
        turns = self.history()["turns"]
        echoed = [t for t in turns if t.get("proactive")]
        self.assertEqual([t["who"] for t in echoed], ["Echo"])
        # contextlib.closing so the handle is released before temp cleanup runs.
        with contextlib.closing(sqlite3.connect(self.proactive_store.path)) as db:
            roles = {r[0] for r in db.execute("SELECT DISTINCT author FROM relay_proactive")}
            recipients = {r[0] for r in db.execute("SELECT DISTINCT recipient FROM relay_proactive")}
        self.assertEqual(roles, {"Echo"})
        self.assertEqual(recipients, {"Eddie"})

    def test_history_reports_the_proactive_cursor_and_gap_flag(self):
        payload = self.history()
        self.assertIn("proactive_last_seq", payload)
        self.assertIn("proactive_gap", payload)
        self.assertEqual(payload["proactive_last_seq"], -1)
        relay_proactive.publish("one", token=self._token())
        payload = self.history()
        self.assertEqual(payload["proactive_last_seq"], 1)
        self.assertFalse(payload["proactive_gap"])

    def test_history_for_another_room_excludes_proactive_rows(self):
        relay_proactive.publish("one", token=self._token())
        other = relay_chat.history(OTHER_ROOM)
        self.assertFalse([t for t in other["turns"] if t.get("proactive")])

    def test_proactive_read_helper_is_exposed_and_ordered(self):
        relay_proactive.publish("one", token=self._token())
        relay_proactive.publish("two", token=self._token())
        window = relay_chat.proactive_read(1)
        self.assertEqual([e["seq"] for e in window["events"]], [2])
        self.assertEqual(window["last_seq"], 2)

    @staticmethod
    def _token():
        os.environ[relay_proactive.TOKEN_ENV] = "merge-test-token"
        return os.environ[relay_proactive.TOKEN_ENV]


if __name__ == "__main__":
    unittest.main()
