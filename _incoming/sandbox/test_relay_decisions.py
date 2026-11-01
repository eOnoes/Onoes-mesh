import copy
import io
import json
import os
import socket
import sys
import tempfile
import urllib.error
import urllib.request
import threading
import unittest
from email.message import Message
from types import SimpleNamespace
from unittest.mock import patch

import relay_chat
import relay_decisions
from server import Handler
from relay_decisions import (
    DecisionError,
    DecisionStore,
    event_to_decision,
    normalize_reason,
    redact_text,
    validate_request_id,
    validate_run_id,
)

RUN_ID = "run_relay_test"
REQUEST_ID = "request-123"
SESSION_ID = "relay-eddie-echo-test"


def approval_event(**changes):
    event = {
        "event": "approval.request",
        "run_id": RUN_ID,
        "request_id": REQUEST_ID,
        "command": "echo safe",
        "description": "temporary verification only",
        "pattern_key": "temporary-verification:abc123",
        "choices": ["once", "session", "always", "deny"],
        "allow_session": True,
        "allow_permanent": True,
    }
    event.update(changes)
    return event


class FakeClient:
    def __init__(self, response=None):
        self.calls = []
        self.response = response or {"object": "hermes.run.approval_response", "resolved": 1}

    def post_approval(self, run_id, payload):
        self.calls.append((run_id, copy.deepcopy(payload)))
        return self.response


def store(client=None, session=SESSION_ID):
    """An in-memory DecisionStore that owns RUN_ID in SESSION_ID, the way a real send does."""
    value = DecisionStore(client or FakeClient())
    value.associate_run(session, RUN_ID, {"text": "temporary"})
    value.begin(RUN_ID, {"text": "temporary"})
    return value


def register(store=None, run_id=RUN_ID, session=SESSION_ID):
    """Record run ownership in Relay's durable store so the server-side guard accepts it."""
    target = store if store is not None else relay_chat.STORE
    target.begin_run(run_id, session, body="temporary")
    return run_id


def isolated_store(tmpdir=None):
    """Point relay_chat at an isolated SQLite store (Phase 1 tests)."""
    import pathlib
    import tempfile

    import relay_store

    directory = pathlib.Path(tmpdir or tempfile.mkdtemp(prefix="relay-p1-"))
    previous = relay_chat.STORE
    relay_chat.STORE = relay_store.RelayStore(directory / "state.db")
    return previous


def bridge(decision_store=None, chat_store=None):
    """Install an isolated DecisionStore + RelayStore into relay_chat and return them.

    Every Phase 1 bridge/endpoint test calls this so the server-side run-ownership guard
    (which reads relay_chat.STORE) sees the same run the in-memory DecisionStore owns.
    """
    store = decision_store if decision_store is not None else DecisionStore(FakeClient())
    previous = isolated_store(chat_store)
    relay_chat.DECISIONS = store
    register(store.store if store.store else relay_chat.STORE)
    return store, previous


class DecisionContractTests(unittest.TestCase):
    def test_event_to_decision_preserves_native_scope_choices(self):
        value = event_to_decision(approval_event())
        self.assertEqual(value["run_id"], RUN_ID)
        self.assertEqual(value["request_id"], REQUEST_ID)
        self.assertEqual(value["choices"], ["once", "always", "deny"])
        self.assertIn("temporary-verification", value["scope"])
        self.assertNotIn("session", value["choices"])

    def test_smart_denied_once_only_stays_once_or_deny(self):
        value = event_to_decision(approval_event(choices=["once", "deny"], smart_denied=True))
        self.assertEqual(value["choices"], ["once", "deny"])

    def test_session_choice_is_rejected_for_owner_slice(self):
        with self.assertRaisesRegex(DecisionError, "Allow once, Always allow, and Deny"):
            relay_decisions.choice_for("session", ["once", "session", "always", "deny"])

    def test_stale_and_cross_run_request_ids_do_not_resolve(self):
        value = store()
        value.accept_event(approval_event())
        with self.assertRaisesRegex(DecisionError, "no longer pending"):
            value.approval_decision(RUN_ID, "request-old", "once")
        with self.assertRaisesRegex(DecisionError, "not selected by Relay"):
            value.approval_decision("run_other", REQUEST_ID, "once")

    def test_denied_reason_requires_typed_reason_path(self):
        value = store()
        value.accept_event(approval_event())
        with self.assertRaisesRegex(DecisionError, "typed-reason"):
            value.approval_decision(RUN_ID, REQUEST_ID, "deny", "not on the right control")

    def test_typed_denial_reason_is_presented_to_native_api_but_ignored_by_installed_contract(self):
        """Contract mock: the installed route has no reason field, so Relay must not send one.

        The reason is still carried on the decision record (Relay-local) and the payload
        never gains a ``reason`` key the API would silently drop.
        """
        relay_decisions._CAPABILITY = {"native": False, "how": "test", "detail": "no native reason"}
        client = FakeClient()
        value = store(client)
        value.accept_event(approval_event())
        result = value.approval_decision(RUN_ID, REQUEST_ID, "deny", "keep this local", allow_reason=True)
        self.assertEqual(result["reason"], "keep this local")
        self.assertNotIn("reason", client.calls[0][1],
                         "the installed API has no reason field; Relay must not pretend")
        self.assertFalse(result["reason_native"])
        self.assertEqual(client.calls[0][1]["resolve_all"], False)
        self.assertEqual(client.calls[0][1]["request_id"], REQUEST_ID)

    def test_always_uses_native_exact_always_choice(self):
        client = FakeClient()
        value = store(client)
        value.accept_event(approval_event())
        value.approval_decision(RUN_ID, REQUEST_ID, "always")
        self.assertEqual(client.calls[0][1]["choice"], "always")
        self.assertEqual(client.calls[0][1]["request_id"], REQUEST_ID)

    def test_allow_once_is_exact_and_once(self):
        client = FakeClient()
        value = store(client)
        value.accept_event(approval_event())
        value.approval_decision(RUN_ID, REQUEST_ID, "once")
        self.assertEqual(client.calls[0][1]["choice"], "once")
        self.assertFalse(client.calls[0][1]["resolve_all"])

    def test_deny_without_reason_is_exact(self):
        client = FakeClient()
        value = store(client)
        value.accept_event(approval_event())
        value.approval_decision(RUN_ID, REQUEST_ID, "deny")
        self.assertEqual(client.calls[0][1], {"choice": "deny", "request_id": REQUEST_ID, "resolve_all": False})

    def test_duplicate_resolution_is_prevented_server_side(self):
        value = store()
        value.accept_event(approval_event())
        value.approval_decision(RUN_ID, REQUEST_ID, "once")
        with self.assertRaisesRegex(DecisionError, "already sent"):
            value.approval_decision(RUN_ID, REQUEST_ID, "deny")

    def test_pending_survives_snapshot_and_is_scoped_to_run(self):
        value = store()
        value.accept_event(approval_event())
        snapshot = value.current(SESSION_ID)
        self.assertEqual(snapshot["state"], "decision_blocked")
        self.assertEqual(snapshot["run_id"], RUN_ID)
        self.assertEqual(snapshot["pending"][0]["request_id"], REQUEST_ID)
        self.assertEqual(value.current("relay-eddie-echo-other")["state"], "idle")

    def test_cross_room_association_is_rejected(self):
        value = store()
        with self.assertRaisesRegex(DecisionError, "another Relay room"):
            value.associate_run("relay-eddie-echo-other", RUN_ID)

    def test_replay_event_does_not_duplicate_card(self):
        value = store()
        value.accept_event(approval_event())
        value.accept_event(approval_event())
        self.assertEqual(len(value.pending_for_run(RUN_ID)), 1)

    def test_invalid_ids_and_reason_are_rejected(self):
        for bad in ("", "run/../x", None, "run with space"):
            with self.assertRaises(DecisionError):
                validate_run_id(bad)
        for bad in ("", "req/1", None, "x" * 257):
            with self.assertRaises(DecisionError):
                validate_request_id(bad)
        self.assertEqual(normalize_reason("  a \n b  "), "a b")
        self.assertEqual(normalize_reason(None), "")

    def test_secret_is_redacted_from_display_and_reason(self):
        secret = "secret-verification-key"
        with patch.dict(os.environ, {"API_SERVER_KEY": secret}, clear=False):
            self.assertNotIn(secret, redact_text("token " + secret + " end"))
            self.assertNotIn(secret, normalize_reason("token " + secret + " end"))

    def test_unknown_run_is_not_decision_blocked(self):
        value = store()
        # An unowned run has no pending approval, so it is never a decision door.
        self.assertEqual(value.pending_for_run("run_other"), [])
        self.assertNotEqual(value.run_snapshot("run_other")["state"], "decision_blocked")


class RelayChatBridgeTests(unittest.TestCase):
    def setUp(self):
        self.client = FakeClient()
        self.store, _ = bridge(DecisionStore(self.client))
        self.store.associate_run(SESSION_ID, RUN_ID)

    def test_status_waiting_for_approval_recovers_decision_card(self):
        with patch.object(relay_chat, "_call", return_value=(200, {
            "status": "waiting_for_approval",
            "session_id": SESSION_ID,
            "approval": approval_event(),
        })):
            result = relay_chat.status(RUN_ID)
        self.assertTrue(result["decision_blocked"])
        self.assertEqual(result["decision"]["request_id"], REQUEST_ID)
        self.assertEqual(relay_chat.decision_snapshot(SESSION_ID)["state"], "decision_blocked")

    def test_resolution_posts_exact_native_choice(self):
        relay_chat.accept_approval_event(approval_event(), SESSION_ID)
        result = relay_chat.resolve_decision(RUN_ID, REQUEST_ID, "always")
        self.assertEqual(result["choice"], "always")
        self.assertEqual(self.client.calls[0][1]["choice"], "always")

    def test_typed_reason_forwarded_only_for_explicit_reason_path(self):
        relay_decisions._CAPABILITY = {"native": True, "how": "test", "detail": "native"}
        try:
            relay_chat.accept_approval_event(approval_event(), SESSION_ID)
            result = relay_chat.resolve_decision(RUN_ID, REQUEST_ID, "deny", "keep it local", allow_reason=True)
            self.assertEqual(result["reason"], "keep it local")
            self.assertEqual(self.client.calls[0][1]["reason"], "keep it local")
        finally:
            relay_decisions._CAPABILITY = None

    def test_typed_reason_is_not_forwarded_when_native_unsupported(self):
        """Truthful boundary: no native reason field means no reason in the payload."""
        relay_decisions._CAPABILITY = {"native": False, "how": "test", "detail": "no reason"}
        try:
            relay_chat.accept_approval_event(approval_event(), SESSION_ID)
            result = relay_chat.resolve_decision(RUN_ID, REQUEST_ID, "deny", "keep it local", allow_reason=True)
            self.assertEqual(result["reason"], "keep it local")
            self.assertNotIn("reason", self.client.calls[0][1])
            self.assertFalse(result["reason_native"])
        finally:
            relay_decisions._CAPABILITY = None

    def test_non_approval_status_keeps_run_normal(self):
        with patch.object(relay_chat, "_call", return_value=(200, {"status": "running"})):
            result = relay_chat.status(RUN_ID)
        self.assertFalse(result["decision_blocked"])
        self.assertIsNone(result["decision"])


from http.server import BaseHTTPRequestHandler


class ServerEndpointTests(unittest.TestCase):
    def setUp(self):
        self.store, _ = bridge(DecisionStore(FakeClient()))
        self.port = self._free_port()
        self.base = "http://127.0.0.1:%d" % self.port

    def tearDown(self):
        relay_chat.DECISIONS = getattr(self, "_old_decisions", relay_chat.DECISIONS)

    @staticmethod
    def _free_port():
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            return sock.getsockname()[1]

    def _server_thread(self):
        with socket.socket() as listener:
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            listener.bind(("127.0.0.1", self.port))
            listener.listen(1)
            listener.settimeout(5)
            try:
                conn, addr = listener.accept()
            except TimeoutError:
                return
            with conn:
                conn.settimeout(5)
                try:
                    data = b""
                    while b"\r\n\r\n" not in data:
                        chunk = conn.recv(4096)
                        if not chunk:
                            return
                        data += chunk
                    head, body = data.split(b"\r\n\r\n", 1)
                    lines = head.decode("iso-8859-1").split("\r\n")
                    request_line = lines[0]
                    command, path = request_line.split(" ", 2)[:2]
                    headers = Message()
                    for line in lines[1:]:
                        key, value = line.split(":", 1)
                        headers[key.strip()] = value.strip()
                    length = int(headers.get("Content-Length", "0"))
                    while len(body) < length:
                        chunk = conn.recv(4096)
                        if not chunk:
                            break
                        body += chunk
                    handler = object.__new__(Handler)
                    handler.connection = conn
                    handler.client_address = addr
                    handler.request_version = "HTTP/1.1"
                    handler.close_connection = True
                    handler.requestline = request_line
                    handler.command = command
                    handler.path = path
                    handler.headers = headers
                    handler.rfile = io.BytesIO(body)
                    chunks = []
                    handler.wfile = SimpleNamespace(write=chunks.append, flush=lambda: None)
                    handler.status_code = None
                    handler.send_response = lambda code, message=None: setattr(handler, "status_code", code)
                    handler.send_header = lambda keyword, value: None
                    handler.end_headers = lambda: None
                    handler.log_message = lambda *args: None
                    getattr(handler, "do_" + command)()
                    payload = b"".join(chunks)
                    status = handler.status_code or 200
                    response_head = ("HTTP/1.1 %d OK\r\nContent-Length: %d\r\nConnection: close\r\n\r\n" % (status, len(payload))).encode("iso-8859-1")
                    conn.sendall(response_head + payload)
                except Exception:
                    return

    def request(self, path, body=None, header_overrides=None, method="GET"):
        payload = json.dumps(body).encode("utf-8") if body is not None else b""
        headers = {"Content-Type": "application/json", "Host": "127.0.0.1:8771"}
        headers.update(header_overrides or {})
        thread = threading.Thread(target=self._server_thread, daemon=True)
        thread.start()
        request = urllib.request.Request(self.base + path, data=payload or None, headers=headers, method=method)
        try:
            return urllib.request.urlopen(request, timeout=5)
        finally:
            thread.join(timeout=2)

    def test_decision_endpoint_requires_exact_native_payload(self):
        self.store.associate_run(SESSION_ID, RUN_ID)
        self.store.accept_event(approval_event())
        self.store.client.calls.append((RUN_ID, {}))  # stand in for the native door
        self.store.client.response = {"resolved": 1, "choice": "always"}
        response = self.request("/api/relay/decisions", {
            "action": "resolve",
            "run_id": RUN_ID,
            "request_id": REQUEST_ID,
            "choice": "always",
        }, method="POST")
        payload = json.loads(response.read().decode("utf-8"))
        self.assertEqual(response.status, 200)
        self.assertEqual(payload["choice"], "always")

    def test_decision_endpoint_rejects_plain_denial_reason(self):
        self.store.associate_run(SESSION_ID, RUN_ID)
        self.store.accept_event(approval_event())
        error = None
        try:
            self.request("/api/relay/decisions", {
                "action": "resolve", "run_id": RUN_ID, "request_id": REQUEST_ID,
                "choice": "deny", "reason": "wrong control",
            }, method="POST")
        except urllib.error.HTTPError as exc:
            error = exc
            exc.close()
        self.assertIsNotNone(error)
        self.assertEqual(error.code, 400)

    def test_decision_endpoint_typed_reason_path_requires_explicit_flag(self):
        self.store.associate_run(SESSION_ID, RUN_ID)
        self.store.accept_event(approval_event())
        response = self.request("/api/relay/decisions", {
            "action": "resolve", "run_id": RUN_ID, "request_id": REQUEST_ID,
            "choice": "deny", "reason": "keep this local", "allow_reason": True,
        }, method="POST")
        payload = json.loads(response.read().decode("utf-8"))
        self.assertEqual(payload["reason"], "keep this local")

    def test_decision_endpoint_rejects_unknown_action(self):
        error = None
        try:
            self.request("/api/relay/decisions", {"action": "pretend"}, method="POST")
        except urllib.error.HTTPError as exc:
            error = exc
            exc.close()
        self.assertIsNotNone(error)
        self.assertEqual(error.code, 400)

    def test_send_forwards_native_idempotency_header(self):
        with patch.object(relay_chat, "submit", return_value={"run_id": RUN_ID, "status": "started", "session_id": SESSION_ID}) as submit:
            response = self.request("/api/relay/send", {"text": "temporary"}, {"Idempotency-Key": "relay-key"}, method="POST")
        payload = json.loads(response.read().decode("utf-8"))
        self.assertEqual(response.status, 202)
        self.assertEqual(payload["run_id"], RUN_ID)
        self.assertEqual(submit.call_args.kwargs["idempotency_key"], "relay-key")

    def test_decision_snapshot_endpoint(self):
        self.store.associate_run(SESSION_ID, RUN_ID)
        self.store.accept_event(approval_event())
        response = self.request("/api/relay/decisions?session=" + SESSION_ID)
        payload = json.loads(response.read().decode("utf-8"))
        self.assertEqual(response.status, 200)
        self.assertEqual(payload["state"], "decision_blocked")



if __name__ == "__main__":
    unittest.main(verbosity=2)
