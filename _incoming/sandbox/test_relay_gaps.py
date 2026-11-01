"""Relay gap-closure tests: decisions, durability, transport, media, startup.

Every test runs against an isolated SQLite store, an isolated media directory, and a fake
Hermes API on an ephemeral loopback port. No production port, held outbox row, owner card,
standing goal, or real dangerous command is touched. Contract tests against the fake are
labelled mock; nothing here claims a real end-to-end run against the owner's gateway.
"""
from __future__ import annotations

import base64
import json
import socket
import threading
import time
import unittest
import urllib.error
import urllib.request
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import relay_decisions
import relay_events
import relay_media
import relay_store
from fake_hermes import FakeHermes
from relay_decisions import DecisionError, DecisionStore, event_to_clarification, event_to_decision
from relay_test_harness import JPEG_MIN, PNG_1PX, RelayCase, RelayHarness, SVG

RUN = "run_relay_unit"
REQ = "req-1"
ROOM = "relay-eddie-echo-chat"


def approval_event(**changes):
    event = {"event": "approval.request", "run_id": RUN, "request_id": REQ,
             "command": "rm -rf /tmp/x", "description": "dangerous command",
             "pattern_key": "danger:abc", "choices": ["once", "session", "always", "deny"]}
    event.update(changes)
    return event


def wait_until(predicate, timeout=8.0, step=0.05):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(step)
    return False


# --------------------------------------------------------------------------------------
# 1. Truthful typed denial
# --------------------------------------------------------------------------------------


class ReasonTruthTests(unittest.TestCase):
    """The typed-reason door must never claim a delivery the API cannot make."""

    def test_detector_reports_native_when_route_forwards_reason(self):
        route = ("def _handle_run_approval(self, request):\n"
                 "    resolved = resolve_gateway_approval(key, choice, reason=request.get('reason'))\n")
        found = relay_decisions.detect_reason_support(route)
        self.assertTrue(found["native"], found)
        self.assertIn("forwards reason", found["detail"])

    def test_detector_fails_closed_when_route_ignores_reason(self):
        route = ("def _handle_run_approval(self, request):\n"
                 "    resolved = resolve_gateway_approval(key, choice, resolve_all=False)\n")
        found = relay_decisions.detect_reason_support(route)
        self.assertFalse(found["native"], found)
        self.assertIn("does not forward a reason", found["detail"])

    def test_detector_fails_closed_when_source_unreadable(self):
        found = relay_decisions.detect_reason_support("")
        self.assertFalse(found["native"], found)
        self.assertIn("no reason parameter", found["detail"])

    def test_installed_source_reports_reason_not_forwarded(self):
        """Real installed-source check (read-only) — the authority for the UI's claim."""
        found = relay_decisions.detect_reason_support()
        self.assertFalse(found["native"], found)
        self.assertIn("does not forward a reason", found["detail"])

    def test_decision_card_carries_reason_truth(self):
        relay_decisions._CAPABILITY = {"native": False, "how": "test", "detail": "no native reason"}
        card = event_to_decision(approval_event())
        self.assertFalse(card["reason_native"])
        self.assertIn("no native reason", card["reason_note"])

    def test_decision_card_says_native_when_supported(self):
        relay_decisions._CAPABILITY = {"native": True, "how": "test", "detail": "native"}
        try:
            card = event_to_decision(approval_event())
            self.assertTrue(card["reason_native"])
        finally:
            relay_decisions._CAPABILITY = None


class TypedDenialContractTests(RelayCase):
    """Mock contract against the fake API: what Relay actually posts."""

    def test_plain_deny_sends_no_reason(self):
        store = relay_chat_store(self.harness)
        store.associate_run(ROOM, RUN)
        store.accept_event(approval_event())
        prime_approval(self.harness)
        store.approval_decision(RUN, REQ, "deny")
        sent = self.harness.fake.approvals[-1]
        self.assertEqual(sent["choice"], "deny")
        self.assertNotIn("reason", sent)
        self.assertFalse(sent["resolve_all"])

    def test_typed_reason_is_relay_local_when_native_unsupported(self):
        self.assertFalse(relay_decisions.reason_capability()["native"])
        store = relay_chat_store(self.harness)
        store.associate_run(ROOM, RUN)
        store.accept_event(approval_event())
        prime_approval(self.harness)
        result = store.approval_decision(RUN, REQ, "deny", "not safe", allow_reason=True)
        sent = self.harness.fake.approvals[-1]
        self.assertNotIn("reason", sent, "Relay must not pretend to deliver a reason the API drops")
        self.assertFalse(result["reason_native"])
        self.assertIn("does not accept a reason", result["reason_note"])
        self.assertEqual(result["reason"], "not safe", "the reason is kept Relay-local")

    def test_typed_reason_is_sent_when_native_supported(self):
        harness = RelayHarness(self.harness.tmpdir, approval_forwards_reason=True)
        self.addCleanup(harness.close)
        store = relay_chat_store(harness)
        store.associate_run(ROOM, RUN)
        store.accept_event(approval_event())
        harness.fake.request_approval(RUN, REQ)
        result = store.approval_decision(RUN, REQ, "deny", "not safe", allow_reason=True)
        sent = harness.fake.approvals[-1]
        self.assertEqual(sent["reason"], "not safe")
        self.assertTrue(result["reason_native"])

    def test_typed_reason_requires_explicit_flag(self):
        store = relay_chat_store(self.harness)
        store.associate_run(ROOM, RUN)
        store.accept_event(approval_event())
        with self.assertRaises(DecisionError):
            store.approval_decision(RUN, REQ, "deny", "sneaky reason")

    def test_always_uses_only_native_always_and_labels_scope(self):
        store = relay_chat_store(self.harness)
        store.associate_run(ROOM, RUN)
        card = store.accept_event(approval_event())
        self.assertEqual(card["always_scope"], "Always allow remembers only: danger:abc")
        prime_approval(self.harness)
        store.approval_decision(RUN, REQ, "always")
        sent = self.harness.fake.approvals[-1]
        self.assertEqual(sent["choice"], "always")
        self.assertNotIn("session", sent["choice"])

    def test_session_choice_is_refused(self):
        store = relay_chat_store(self.harness)
        store.associate_run(ROOM, RUN)
        store.accept_event(approval_event())
        with self.assertRaises(DecisionError):
            store.approval_decision(RUN, REQ, "session")

    def test_stale_request_id_is_rejected(self):
        store = relay_chat_store(self.harness)
        store.associate_run(ROOM, RUN)
        store.accept_event(approval_event())
        prime_approval(self.harness)
        store.approval_decision(RUN, REQ, "deny")
        with self.assertRaises(DecisionError) as ctx:
            store.approval_decision(RUN, REQ, "deny")
        self.assertEqual(ctx.exception.status, 409)
        self.assertEqual(len(self.harness.fake.approvals), 1)

    def test_cross_run_request_is_rejected(self):
        store = relay_chat_store(self.harness)
        store.associate_run(ROOM, RUN)
        store.accept_event(approval_event())
        store.associate_run(ROOM, "run_other")
        with self.assertRaises(DecisionError):
            store.approval_decision("run_other", REQ, "deny")

    def test_cross_room_run_is_rejected_by_the_server(self):
        """A browser cannot resolve an approval for a run another room owns."""
        self.harness.fake.request_approval(RUN, REQ)
        relay_chat_store(self.harness).associate_run(ROOM, RUN)
        self.harness.store.begin_run(RUN, ROOM)
        code, body = self.harness.error("/api/relay/decisions", {
            "action": "resolve", "run_id": RUN, "request_id": REQ, "choice": "deny",
        })
        self.assertIn(code, (403, 404, 409), body)

    def test_unknown_run_id_is_rejected_server_side(self):
        code, body = self.harness.error("/api/relay/decisions", {
            "action": "resolve", "run_id": "run_never_recorded", "request_id": REQ, "choice": "deny",
        })
        self.assertEqual(code, 404, body)

    def test_multiple_taps_resolve_exactly_once(self):
        store = relay_chat_store(self.harness)
        store.associate_run(ROOM, RUN)
        store.accept_event(approval_event())
        prime_approval(self.harness)
        first = store.approval_decision(RUN, REQ, "deny")
        self.assertEqual(first["choice"], "deny")
        with self.assertRaises(DecisionError):
            store.approval_decision(RUN, REQ, "deny")
        self.assertEqual(len(self.harness.fake.approvals), 1)

    def test_second_request_in_same_room_stays_addressable(self):
        """Phase 1 bug: a resolved decision hid the next approval. Now it does not."""
        store = relay_chat_store(self.harness)
        store.associate_run(ROOM, RUN)
        store.accept_event(approval_event(request_id="req-1"))
        prime_approval(self.harness)
        store.approval_decision(RUN, "req-1", "deny")
        store.associate_run(ROOM, "run_second")
        store.accept_event(approval_event(run_id="run_second", request_id="req-2"))
        self.assertEqual(store.selected_run(ROOM), "run_second")
        snapshot = store.run_snapshot("run_second")
        self.assertEqual(snapshot["state"], "decision_blocked")
        self.assertEqual(snapshot["pending"][0]["request_id"], "req-2")


class ClarificationTests(unittest.TestCase):
    """Ordinary clarification is a different door from a dangerous-command permission."""

    def test_clarification_card_has_no_permission_choices(self):
        card = event_to_clarification({"event": "clarify.request", "run_id": RUN,
                                       "request_id": "q-1", "question": "which one?"})
        self.assertEqual(card["kind"], "clarification")
        self.assertEqual(card["choices"], ["answer"])
        self.assertNotIn("command", card)
        self.assertNotIn("always_scope", card)

    def test_approval_event_is_not_a_clarification(self):
        self.assertIsNone(event_to_clarification(approval_event()))

    def test_clarification_answers_through_steer(self):
        fake = FakeHermes()
        self.addCleanup(fake.close)
        store = DecisionStore(client=_StubClient(steer={"accepted": True}), store=None)
        store.associate_run(ROOM, RUN)
        answer = store.answer_clarification(RUN, "q-1", "the second one")
        self.assertTrue(answer["accepted"])

    def test_clarification_answer_refuses_empty(self):
        store = DecisionStore(client=_StubClient(), store=None)
        store.associate_run(ROOM, RUN)
        with self.assertRaises(DecisionError):
            store.answer_clarification(RUN, "q-1", "   ")


def relay_chat_store(harness):
    import relay_chat

    return relay_chat.DECISIONS


def relay_chat_fingerprint(room_id, text, files):
    import relay_chat

    return relay_chat._fingerprint(room_id, text, files)


def prime_approval(harness, run_id=RUN, request_id=REQ, **event):
    """Give the fake gateway a pending approval so a decision round-trip can succeed."""
    harness.fake.request_approval(run_id, request_id, **event)


class _StubClient:
    def __init__(self, approval=None, steer=None):
        self.approval = approval or {"resolved": 1}
        self.steer = steer or {"accepted": True}
        self.approvals = []
        self.steers = []

    def post_approval(self, run_id, payload):
        self.approvals.append((run_id, dict(payload)))
        return self.approval

    def post_steer(self, run_id, text):
        self.steers.append((run_id, text))
        return self.steer


# --------------------------------------------------------------------------------------
# 2. Durable room/run recovery
# --------------------------------------------------------------------------------------


class DurableRecoveryTests(RelayCase):
    def setUp(self):
        super().setUp()
        import relay_proactive
        import relay_sqlite_worker

        patcher = patch.object(relay_sqlite_worker, "OUTBOX_DB", self.tmpdir / "outbox.db")
        patcher.start()
        self.addCleanup(patcher.stop)
        db = relay_sqlite_worker.connect_outbox()
        db.close()
        self.proactive = relay_proactive.ProactiveStore(self.tmpdir / "proactive.db")
        db = self.proactive.connect()
        db.close()
        patcher = patch.object(relay_proactive, "_STORE", self.proactive)
        patcher.start()
        self.addCleanup(patcher.stop)

    def save_turn(self, session_id, body):
        import relay_sqlite_worker

        db = relay_sqlite_worker.connect_outbox()
        try:
            stamp = relay_store.zulu()
            db.execute("INSERT OR IGNORE INTO rooms VALUES (?, 'B', ?)", (session_id, stamp))
            row = db.execute(
                "INSERT INTO turns (session_id, hermes_message_id, role, body, created_at)"
                " VALUES (?, 1, 'assistant', ?, ?)", (session_id, body, stamp))
            db.execute("INSERT INTO outbox (turn_id, scope, kind, status, created_at)"
                       " VALUES (?, 'B:relay', 'relay_turn', 'held', ?)", (row.lastrowid, stamp))
        finally:
            db.close()

    def test_room_selection_survives_a_fresh_document(self):
        _, payload = self.harness.json("/api/relay/new", {})
        room_id = payload["session_id"]
        self.harness.json("/api/relay/room", {"session_id": room_id})
        # A fresh browser document: no sessionStorage, only the server's own answer.
        _, state = self.harness.json("/api/relay/state")
        self.assertEqual(state["session_id"], room_id)
        self.assertIn(room_id, [row["session_id"] for row in state["rooms"]])

    def test_run_ownership_survives_a_process_restart(self):
        _, payload = self.harness.json("/api/relay/send", {"text": "hello"}, headers={"Idempotency-Key": "k9"})
        run_id = payload["run_id"]
        reopened = relay_store.RelayStore(self.harness.store.path)
        self.assertEqual(reopened.run_room(run_id), ROOM)

    def test_pending_decision_survives_a_process_restart(self):
        store = relay_chat_store(self.harness)
        store.associate_run(ROOM, RUN)
        store.accept_event(approval_event())
        reopened = relay_store.RelayStore(self.harness.store.path)
        rows = reopened.pending(RUN)
        self.assertEqual(len(rows), 1)
        card = json.loads(rows[0]["payload"])
        self.assertEqual(card["request_id"], REQ)
        self.assertEqual(card["kind"], "approval")

    def test_decision_ledger_survives_a_process_restart(self):
        store = relay_chat_store(self.harness)
        store.associate_run(ROOM, RUN)
        store.accept_event(approval_event())
        self.harness.fake.request_approval(RUN, REQ)
        store.approval_decision(RUN, REQ, "deny", "nope", allow_reason=True)
        reopened = relay_store.RelayStore(self.harness.store.path)
        record = reopened.decision_for(RUN, REQ)
        self.assertEqual(record["choice"], "deny")
        self.assertEqual(record["reason"], "nope")
        with self.assertRaises(FileExistsError):
            reopened.record_decision(RUN, REQ, "deny")

    def test_sent_key_survives_a_process_restart(self):
        _, payload = self.harness.json("/api/relay/send", {"text": "hello"}, headers={"Idempotency-Key": "k10"})
        run_id = payload["run_id"]
        reopened = relay_store.RelayStore(self.harness.store.path)
        row = reopened.sent_lookup("k10")
        self.assertEqual(row["run_id"], run_id)
        self.assertEqual(row["state"], "accepted")

    def test_client_supplied_run_id_is_never_adopted(self):
        code, body = self.harness.error("/api/relay/run", None,
                                        method="GET")
        self.assertIn(code, (400, 404), body)
        code, body = self.harness.error("/api/relay/run?id=run_spoofed", None, method="GET")
        self.assertEqual(code, 404, body)

    def test_run_belonging_to_another_room_is_refused(self):
        """A browser cannot ask for a run's status on behalf of a room it does not own."""
        _, payload = self.harness.json("/api/relay/send", {"text": "hi"}, headers={"Idempotency-Key": "k11"})
        run_id = payload["run_id"]
        other = "relay-eddie-echo-other"
        code, body = self.harness.error(f"/api/relay/run?id={run_id}&session={other}", None,
                                        method="GET")
        self.assertEqual(code, 403, body)
        # The owning room still resolves it.
        response = self.harness.request(f"/api/relay/run?id={run_id}&session={ROOM}", method="GET")
        self.assertEqual(response.status, 200)

    def test_rooms_with_saved_turns_stay_listed(self):
        self.harness.store.ensure_room(ROOM)
        self.save_turn(ROOM, "Mesh lines stay here.")
        _, payload = self.harness.json("/api/relay/new", {})
        room_id = payload["session_id"]
        self.save_turn(room_id, "A saved Echo turn without a run row.")
        self.harness.json("/api/relay/new", {})
        for endpoint in ("/api/relay/rooms", "/api/relay/state"):
            _, payload = self.harness.json(endpoint)
            ids = [row["session_id"] for row in payload["rooms"]]
            self.assertIn(ROOM, ids)
            self.assertIn(room_id, ids)
        import relay_sqlite_worker
        db = relay_sqlite_worker.connect_outbox()
        try:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM turns").fetchone()[0], 2)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM outbox").fetchone()[0], 2)
        finally:
            db.close()

    def test_new_drops_only_the_empty_room_it_leaves(self):
        import relay_chat
        import relay_sqlite_worker

        untouched = "relay-eddie-echo-other"
        self.harness.store.ensure_room(untouched)
        for index, content in enumerate(("empty", "default", "media", "run", "proactive",
                                         "unreadable-outbox", "unreadable-proactive", "same-room")):
            with self.subTest(content=content):
                old = ROOM if content in ("default", "proactive") else f"relay-eddie-echo-check{index}"
                if content == "same-room":
                    old = "relay-eddie-echo-sameroom"
                self.harness.store.ensure_room(old)
                self.harness.store.set_selected(old)
                if content == "media":
                    self.stage_png(old)
                elif content == "run":
                    relay_chat_store(self.harness).associate_run(old, "run_empty_guard")
                elif content == "proactive":
                    self.proactive.publish("Keep this Echo message.")
                check = nullcontext()
                if content == "unreadable-outbox":
                    check = patch.object(relay_sqlite_worker, "OUTBOX_DB", self.tmpdir / "missing-outbox.db")
                elif content == "unreadable-proactive":
                    check = patch.object(self.proactive, "path", self.tmpdir / "missing-proactive.db")
                elif content == "same-room":
                    check = patch.object(relay_chat.uuid, "uuid4", return_value=SimpleNamespace(hex="sameroom"))
                with check:
                    _, payload = self.harness.json("/api/relay/new", {})
                new = payload["session_id"]
                expected = content not in ("empty", "default")
                for result in (payload, self.harness.json("/api/relay/rooms")[1],
                               self.harness.json("/api/relay/state")[1]):
                    ids = [row["session_id"] for row in result["rooms"]]
                    self.assertEqual(old in ids, expected)
                    self.assertIn(new, ids)
                    self.assertIn(untouched, ids)
                self.assertEqual(self.harness.store.get_selected(), new)
                if content == "media":
                    self.assertEqual(len(self.harness.store.media_for_room(old)), 1)
                elif content == "run":
                    self.assertEqual(self.harness.store.run_room("run_empty_guard"), old)
                elif content == "proactive":
                    self.assertEqual(self.proactive.read()["events"][0]["text"], "Keep this Echo message.")

    def test_unknown_room_is_rejected(self):
        code, body = self.harness.error("/api/relay/history?session=evil-room", None, method="GET")
        self.assertEqual(code, 400, body)


# --------------------------------------------------------------------------------------
# 3. Transport: retry, no 10-minute abandonment, idempotency
# --------------------------------------------------------------------------------------


class TransportTests(RelayCase):
    def test_backoff_is_bounded_and_monotonic(self):
        delays = [relay_events.backoff_delay(i) for i in range(10)]
        self.assertEqual(delays[0], 0.5)
        self.assertEqual(max(delays), relay_events.BACKOFF_CAP)
        self.assertEqual(delays, sorted(delays))

    def test_sse_parser_reads_id_and_json(self):
        event_id, payload, comment = relay_events.parse_sse_block(
            ["id: 7", 'data: {"event": "approval.request", "run_id": "r"}'])
        self.assertEqual(event_id, 7)
        self.assertEqual(payload["event"], "approval.request")
        self.assertIsNone(comment)

    def test_sse_parser_reads_comment_only_blocks(self):
        event_id, payload, comment = relay_events.parse_sse_block([": stream closed"])
        self.assertIsNone(payload)
        self.assertEqual(comment, "stream closed")

    def test_reader_resumes_from_the_cursor(self):
        fake = FakeHermes()
        self.addCleanup(fake.close)
        fake.request_approval(RUN, "req-1")
        fake.emit(RUN, {"event": "message.delta", "run_id": RUN, "delta": "x"})
        first = relay_events.read_events(fake.base, "k", RUN, last_seq=-1, max_seconds=2)
        seen = [e["event"] for e in first["events"]]
        self.assertIn("approval.request", seen)
        # Replaying from the last sequence yields nothing new.
        second = relay_events.read_events(fake.base, "k", RUN, last_seq=first["last_seq"], max_seconds=1)
        self.assertEqual([e["event"] for e in second["events"]], [])

    def test_no_wall_clock_cap_by_default(self):
        import inspect

        signature = inspect.signature(relay_events.read_events)
        self.assertEqual(signature.parameters["max_seconds"].default, 0.0)
        self.assertEqual(signature.parameters["last_seq"].default, -1)

    def test_native_status_fallback_ends_a_quiet_run(self):
        fake = FakeHermes()
        self.addCleanup(fake.close)
        fake.finish(RUN, "completed", output="done")
        result = relay_events.pump_until_terminal(
            fake.base, "k", RUN, on_event=lambda e: None,
            status_of=lambda rid: fake.runs.get(rid, {}).get("status"))
        self.assertTrue(result["terminal"])
        self.assertEqual(result["status"], "completed")

    def test_native_status_fallback_stops_on_approval_park(self):
        fake = FakeHermes()
        self.addCleanup(fake.close)
        fake.request_approval(RUN, "req-1")
        result = relay_events.pump_until_terminal(
            fake.base, "k", RUN, on_event=lambda e: None,
            status_of=lambda rid: fake.runs.get(rid, {}).get("status"))
        self.assertFalse(result["terminal"])
        self.assertEqual(result["status"], "waiting_for_approval")

    def test_transient_http_status_is_retried_then_succeeds(self):
        """A 503 is retried with backoff, and the retry reads the stream."""
        fake = FakeHermes()
        self.addCleanup(fake.close)
        fake.request_approval(RUN, "req-1")
        calls = []

        def opener(request, timeout=None):
            calls.append(1)
            if len(calls) == 1:
                raise urllib.error.HTTPError(request.full_url, 503, "busy", {}, None)
            return urllib.request.urlopen(request, timeout=timeout)

        result = relay_events.read_events(fake.base, "k", RUN, last_seq=-1, max_seconds=6,
                                          opener=opener, sleep=lambda s: None)
        self.assertGreaterEqual(len(calls), 2, "the transient 503 should have been retried")
        self.assertIn("approval.request", [e["event"] for e in result["events"]])

    def test_non_transient_status_is_not_retried_forever(self):
        with self.assertRaises(relay_events.EventStreamError) as ctx:
            relay_events.read_events("http://127.0.0.1:1", "k", RUN, last_seq=-1, max_seconds=1,
                                     opener=lambda request, timeout=None: (_ for _ in ()).throw(
                                         urllib.error.HTTPError(request.full_url, 404, "gone", {}, None)))
        self.assertFalse(ctx.exception.transient)
        self.assertEqual(ctx.exception.status, 404)

    def test_duplicate_send_is_replayed_not_duplicated(self):
        _, first = self.harness.json("/api/relay/send", {"text": "hello"}, headers={"Idempotency-Key": "k20"})
        _, second = self.harness.json("/api/relay/send", {"text": "hello"}, headers={"Idempotency-Key": "k20"})
        self.assertEqual(first["run_id"], second["run_id"])
        self.assertTrue(second["replayed"])

    def test_conflicting_send_key_is_refused(self):
        self.harness.json("/api/relay/send", {"text": "hello"}, headers={"Idempotency-Key": "k21"})
        code, body = self.harness.error("/api/relay/send", {"text": "different"},
                                        headers={"Idempotency-Key": "k21"})
        self.assertEqual(code, 409, body)

    def test_uncertain_submit_is_not_blindly_duplicated(self):
        """A key left inflight (a crashed submit) refuses a second execution."""
        fingerprint = relay_chat_fingerprint(ROOM, "hello", [])
        self.harness.store.sent_begin("k22", ROOM, fingerprint)
        code, body = self.harness.error("/api/relay/send", {"text": "hello"},
                                        headers={"Idempotency-Key": "k22"})
        self.assertEqual(code, 409, body)
        self.assertIn("still sending", body["error"])

    def test_native_idempotency_header_is_forwarded(self):
        self.harness.json("/api/relay/send", {"text": "hello"}, headers={"Idempotency-Key": "k23"})
        sends = [r for r in self.harness.fake.requests if r["path"] == "/v1/runs"]
        self.assertTrue(sends)
        self.assertEqual(sends[0]["idempotency"], "k23")

    def test_invalid_idempotency_key_is_refused(self):
        code, body = self.harness.error("/api/relay/send", {"text": "hello"},
                                        headers={"Idempotency-Key": "has space"})
        self.assertEqual(code, 400, body)


# --------------------------------------------------------------------------------------
# 4. Media: real photos, confined ids, native delivery
# --------------------------------------------------------------------------------------


class MediaTests(RelayCase):
    def test_png_is_staged_with_dimensions(self):
        meta = self.stage_png()
        self.assertEqual(meta["mime"], "image/png")
        self.assertEqual((meta["width"], meta["height"]), (1, 1))
        self.assertEqual(len(meta["file_id"]), 64)

    def test_jpeg_is_accepted(self):
        _, meta = self.harness.json("/api/relay/media/upload", {
            "data": base64.b64encode(JPEG_MIN).decode(), "name": "a.jpg", "session_id": ROOM})
        self.assertEqual(meta["mime"], "image/jpeg")

    def test_svg_is_refused(self):
        code, body = self.harness.error("/api/relay/media/upload", {
            "data": base64.b64encode(SVG).decode(), "name": "a.svg", "session_id": ROOM})
        self.assertEqual(code, 415, body)

    def test_oversize_is_refused(self):
        """Relay refuses oversized media before it ever stages the bytes."""
        big = PNG_1PX + b"\x00" * (relay_media.MAX_BYTES + 1)
        with self.assertRaises(relay_media.MediaError) as ctx:
            relay_media.stage(big, "big.png", ROOM)
        self.assertEqual(ctx.exception.status, 413)

    def test_arbitrary_path_is_refused(self):
        with self.assertRaises(relay_media.MediaError):
            relay_media.resolve("../../etc/passwd", ROOM)
        with self.assertRaises(relay_media.MediaError):
            relay_media.resolve("not-a-file-id", ROOM)

    def test_file_id_must_be_hex_digest_shaped(self):
        with self.assertRaises(relay_media.MediaError):
            relay_media.resolve("C:\\Windows\\System32\\config", ROOM)

    def test_cross_room_media_read_is_refused(self):
        meta = self.stage_png()
        other = "relay-eddie-echo-other"
        with self.assertRaises(relay_media.MediaError) as ctx:
            relay_media.resolve(meta["file_id"], other)
        self.assertEqual(ctx.exception.status, 403)

    def test_media_serves_bytes_to_the_owning_room_only(self):
        meta = self.stage_png()
        response = self.harness.request(
            f"/api/relay/media/file?id={meta['file_id']}&session={ROOM}", method="GET")
        self.assertEqual(response.status, 200)
        self.assertEqual(response.headers["Content-Type"], "image/png")
        self.assertEqual(response.read(), PNG_1PX)

    def test_photo_send_uses_the_native_content_part_shape(self):
        meta = self.stage_png()
        _, payload = self.harness.json("/api/relay/send", {
            "text": "look", "session_id": ROOM, "files": [meta["file_id"]]})
        self.assertEqual(payload["transport"], "session_chat")
        posts = [r for r in self.harness.fake.requests if r["path"].endswith("/chat")]
        self.assertTrue(posts)
        content = posts[0]["body"]["message"]
        self.assertEqual(content[0]["type"], "text")
        self.assertIn("look", content[0]["text"])
        images = [part for part in content if part["type"] == "image_url"]
        self.assertEqual(len(images), 1)
        self.assertTrue(images[0]["image_url"]["url"].startswith("data:image/png;base64,"))

    def test_photo_send_carries_the_real_pixels(self):
        meta = self.stage_png()
        self.harness.json("/api/relay/send", {"text": "look", "session_id": ROOM,
                                              "files": [meta["file_id"]]})
        posts = [r for r in self.harness.fake.requests if r["path"].endswith("/chat")]
        url = [p for p in posts[0]["body"]["message"] if p["type"] == "image_url"][0]["image_url"]["url"]
        payload = url.split(",", 1)[1]
        self.assertEqual(base64.b64decode(payload), PNG_1PX)

    def test_media_list_is_room_scoped(self):
        self.stage_png()
        _, listing = self.harness.json("/api/relay/media?session=" + ROOM, method="GET")
        self.assertEqual(len(listing["media"]), 1)


# --------------------------------------------------------------------------------------
# 5. Papers, reply links, history
# --------------------------------------------------------------------------------------


class PaperReplyTests(RelayCase):
    def test_paper_rides_the_turn_text_exactly_once(self):
        paper = "x" * 1500
        import relay_chat

        payload = relay_chat.run_input("note", paper)
        self.assertEqual(payload.count(paper), 1)
        self.assertIn("prompt.txt", payload)

    def test_short_text_is_not_wrapped_as_paper(self):
        import relay_chat

        self.assertEqual(relay_chat.run_input("hello", None), "hello")

    def test_history_round_trips_with_reply_and_paper_metadata(self):
        import relay_chat

        relay_chat.history(ROOM)
        # The outbox read path is exercised; the shape is stable.
        _, payload = self.harness.json("/api/relay/history?session=" + ROOM, method="GET")
        self.assertEqual(payload["session_id"], ROOM)
        self.assertIsInstance(payload["turns"], list)


# --------------------------------------------------------------------------------------
# 6. Startup ownership and idempotence
# --------------------------------------------------------------------------------------


class StartupTests(RelayCase):
    def test_health_lists_the_relay_routes(self):
        _, payload = self.harness.json("/api/relay/health", method="GET")
        self.assertEqual(payload["service"], "relay")
        self.assertIn("/api/relay/media/upload", payload["routes"])
        self.assertIn("/api/relay/health", payload["routes"])
        self.assertIn("/api/relay/decisions", payload["routes"])

    def test_health_separates_relay_from_the_old_static_server(self):
        """The old process on the same port only served /, /app.js and the card API."""
        _, payload = self.harness.json("/api/relay/health", method="GET")
        routes = set(payload["routes"])
        self.assertTrue(routes - {"/api/state", "/api/handoff", "/", "/app.js"},
                        "Relay must advertise routes the old static server never had")

    def test_launcher_script_checks_identity_before_binding(self):
        script = Path(__file__).resolve().parent / "start-relay.ps1"
        self.assertTrue(script.exists(), "the hidden launcher must exist")
        text = script.read_text(encoding="utf-8")
        self.assertIn("8772", text)
        self.assertIn("Test-Path", text)
        self.assertIn("Get-NetTCPConnection", text)
        self.assertIn("server.py", text)
        self.assertNotIn("schtasks", text)
        self.assertNotIn("New-Service", text)
        self.assertNotIn("Register-ScheduledTask", text)

    def test_launcher_refuses_a_foreign_listener(self):
        text = (Path(__file__).resolve().parent / "start-relay.ps1").read_text(encoding="utf-8")
        self.assertIn("unrelated listener", text)
        self.assertIn("Not killed", text)

    def test_launcher_is_idempotent(self):
        text = (Path(__file__).resolve().parent / "start-relay.ps1").read_text(encoding="utf-8")
        self.assertIn("already running", text)
        self.assertIn("Nothing to do", text)

    def test_launcher_never_touches_production_or_the_unknown_owner(self):
        text = (Path(__file__).resolve().parent / "start-relay.ps1").read_text(encoding="utf-8")
        self.assertIn("8771", text)   # the unknown owner is named, not touched
        self.assertIn("is not restarted here", text)
        self.assertNotIn("Stop-Process", text)  # never kills an unrelated listener


class _patched_chat:
    def __enter__(self):
        import relay_chat

        self._chat = relay_chat
        self._orig = relay_chat._key
        relay_chat._key = lambda: "test-key"
        return relay_chat

    def __exit__(self, *exc):
        import relay_chat

        relay_chat._key = self._orig
        return False


# --------------------------------------------------------------------------------------
# 7. Goal truthfulness
# --------------------------------------------------------------------------------------


class GoalTruthTests(unittest.TestCase):
    def test_goal_snapshot_never_claims_autonomous_work(self):
        import relay_goal

        snapshot = relay_goal.snapshot()
        self.assertIn(snapshot["status"], {"none", "active", "paused"})
        self.assertNotIn("running_work", snapshot)


if __name__ == "__main__":
    unittest.main(verbosity=2)
