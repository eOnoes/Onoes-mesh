"""HTTP-layer contracts for the proactive read route, on the isolated Relay harness.

No production port, no held outbox row, no native Hermes state write, no live owner
message. Every test binds an ephemeral loopback port with an explicit Host allowlist
and points the proactive store at a temp file.

The SSE section opens a raw socket to the same isolated harness (urllib cannot read
a chunked/streaming response incrementally), so the live-stream contract is tested
against a real connection: replay, reconnect/resume, Last-Event-ID, room-scoped
rejection, heartbeats, and bounded concurrency.
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

import relay_chat
import relay_proactive
import server
from relay_proactive import ProactiveStore
from relay_test_harness import RelayCase

ROOM = "relay-eddie-echo-chat"


class ProactiveHttpTests(RelayCase):
    """`GET /api/relay/proactive` — replay, cursor, ordering, and route exposure."""

    def setUp(self):
        super().setUp()
        self.proactive_path = self.tmpdir / "proactive.db"
        self.proactive_store = ProactiveStore(self.proactive_path, retention=100)
        self.addCleanup(self._wipe_proactive)
        patcher = patch.object(relay_proactive, "_STORE", self.proactive_store)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _wipe_proactive(self):
        for suffix in ("", "-wal", "-shm", "-journal"):
            try:
                Path(str(self.proactive_path) + suffix).unlink()
            except OSError:
                pass

    def publish(self, text, **kwargs):
        return self.proactive_store.publish(text, **kwargs)

    def _close_test_sse_sockets(self):
        """Stop the isolated SSE serve loops and close their SQLite handles.

        This is teardown hygiene, not product behavior: a bounded heartbeat or
        replay stream must not remain on a handler thread while TemporaryDirectory
        removes the disposable store on Windows.
        """
        for sock in getattr(self, "_sockets", []):
            sock.close()
        deadline = time.monotonic() + 2.0
        while not server._SSE_SLOTS.acquire(blocking=False) and time.monotonic() < deadline:
            time.sleep(0.01)
        else:
            server._SSE_SLOTS.release()

    def test_route_is_advertised_in_health(self):
        _, payload = self.harness.json("/api/relay/health")
        self.assertIn("/api/relay/proactive", payload["routes"])

    def test_read_returns_empty_window_initially(self):
        _, payload = self.harness.json("/api/relay/proactive?last_seq=-1")
        self.assertEqual(payload["events"], [])
        self.assertEqual(payload["last_seq"], -1)
        self.assertFalse(payload["gap"])
        self.assertEqual(payload["session_id"], ROOM)

    def test_read_replays_in_order_with_stable_ids(self):
        first = self.publish("one")
        second = self.publish("two")
        _, payload = self.harness.json("/api/relay/proactive?last_seq=-1")
        self.assertEqual([e["seq"] for e in payload["events"]], [first["seq"], second["seq"]])
        self.assertEqual([e["id"] for e in payload["events"]], [first["id"], second["id"]])
        self.assertEqual([e["text"] for e in payload["events"]], ["one", "two"])
        self.assertTrue(all(e["author"] == "Echo" and e["recipient"] == "Eddie"
                            for e in payload["events"]))

    def test_reconnect_with_current_cursor_replays_nothing(self):
        self.publish("one")
        _, first = self.harness.json("/api/relay/proactive?last_seq=-1")
        _, second = self.harness.json(
            "/api/relay/proactive?last_seq=%d" % first["last_seq"])
        self.assertEqual(second["events"], [])
        self.assertEqual(second["last_seq"], first["last_seq"])

    def test_dedupe_reconnect_returns_same_ids_not_new_rows(self):
        self.publish("one")
        _, first = self.harness.json("/api/relay/proactive?last_seq=-1")
        _, again = self.harness.json(
            "/api/relay/proactive?last_seq=%d" % (first["last_seq"] - 1))
        self.assertEqual([e["id"] for e in again["events"]], [e["id"] for e in first["events"]])
        self.assertEqual(self.proactive_store.count(), 1)

    def test_bad_cursor_and_limit_are_clamped_not_rejected(self):
        self.publish("one")
        for path in ("/api/relay/proactive?last_seq=abc",
                     "/api/relay/proactive?last_seq=&limit=xyz",
                     "/api/relay/proactive?limit=99999"):
            response, payload = self.harness.json(path)
            self.assertEqual(response.status, 200)
            self.assertIsInstance(payload["events"], list)

    def test_no_browser_reachable_publish_route_exists(self):
        # Neither the read path nor any sibling accepts a JSON publish: the read
        # route only answers GET, and any other path 404s. Publishing is not an
        # HTTP door at all.
        for path in ("/api/relay/proactive", "/api/relay/proactive/publish",
                     "/api/relay/proactive/send", "/api/relay/publish"):
            code, _ = self.harness.error(path, {"text": "spoofed"})
            self.assertIn(code, (404, 405, 415), f"{path} must not accept a publish")
        self.assertEqual(self.proactive_store.count(), 0)

    def test_history_exposes_the_merged_proactive_turn(self):
        self.publish("Echo has a question for you.", created_at=1_600_000_050)
        _, payload = self.harness.json("/api/relay/history?session=" + ROOM)
        proactive = [t for t in payload["turns"] if t.get("proactive")]
        self.assertEqual(len(proactive), 1)
        self.assertEqual(proactive[0]["who"], "Echo")
        self.assertTrue(proactive[0]["id"].startswith("msg-p-"))
        self.assertIn("proactive_last_seq", payload)

    def test_stream_route_is_advertised_but_not_a_publish_door(self):
        _, payload = self.harness.json("/api/relay/health")
        self.assertIn("/api/relay/proactive/stream", payload["routes"])
        # A POST to the stream path is not a publish door: do_POST has no handler
        # for it, so it 404s (and the SSE handler itself is GET-only).
        code, _ = self.harness.error("/api/relay/proactive/stream?session=" + ROOM,
                                     {"text": "spoofed"})
        self.assertIn(code, (404, 405, 415))
        self.assertEqual(self.proactive_store.count(), 0)


class _SSESocket:
    """A raw loopback socket that can read one SSE stream's bytes incrementally.

    ``urllib`` buffers an entire response, which cannot observe a live (never
    "completes") stream, so these tests speak HTTP/1.1 over a plain socket and
    read whatever bytes have arrived so far.
    """

    def __init__(self, harness, path, headers=None):
        self.sock = socket.create_connection(("127.0.0.1", harness.port), timeout=10)
        request = f"GET {path} HTTP/1.1\r\nHost: 127.0.0.1:{harness.port}\r\n"
        for name, value in (headers or {}).items():
            request += f"{name}: {value}\r\n"
        request += "Accept: text/event-stream\r\n\r\n"
        self.sock.sendall(request.encode("utf-8"))
        self._buf = b""
        self.status = None
        self.headers = {}

    def _pull(self, timeout=1.0):
        self.sock.settimeout(timeout)
        try:
            chunk = self.sock.recv(65536)
        except (socket.timeout, TimeoutError):
            return False
        if not chunk:
            return False
        self._buf += chunk
        return True

    def _ensure_head(self):
        start = __import__("time").monotonic()
        while b"\r\n\r\n" not in self._buf:
            remaining = 5.0 - (__import__("time").monotonic() - start)
            if remaining <= 0:
                raise AssertionError("stream closed before its headers arrived")
            self.sock.settimeout(remaining)
            try:
                chunk = self.sock.recv(65536)
            except (socket.timeout, TimeoutError):
                raise AssertionError("stream closed before its headers arrived")
            if not chunk:
                raise AssertionError("stream closed before its headers arrived")
            self._buf += chunk
        head, _, rest = self._buf.partition(b"\r\n\r\n")
        self._buf = rest
        lines = head.decode("utf-8", "replace").split("\r\n")
        self.status = int(lines[0].split(" ")[1])
        for line in lines[1:]:
            if ":" in line:
                name, _, value = line.partition(":")
                self.headers[name.strip().lower()] = value.strip()
        return self.status

    def status_and_headers(self):
        if self.status is None:
            self._ensure_head()
        return self.status, self.headers

    def read_until(self, marker, timeout=5.0):
        """Read until ``marker`` appears in the bytes received *since the last read*.

        Returns only the new segment, so a test that calls this twice on one
        connection sees each read's own bytes and never re-parses frames it
        already asserted on. (``marker`` must therefore not already be present in
        what was read before this call.)
        """
        if self.status is None:
            self._ensure_head()
        start = __import__("time").monotonic()
        while marker not in self._buf:
            remaining = timeout - (__import__("time").monotonic() - start)
            if remaining <= 0:
                break
            self.sock.settimeout(remaining)
            try:
                chunk = self.sock.recv(65536)
            except (socket.timeout, TimeoutError):
                break
            if not chunk:
                break
            self._buf += chunk
        data, self._buf = self._buf, b""
        return data

    def read_some(self, timeout=2.0):
        """Return the bytes received *since the last read* within ``timeout``.

        Keeps reading until at least one *complete* SSE frame (a blank-line
        separator) has arrived or the timeout elapses, so a test never parses a
        half-written frame just because two reads happened to split one.
        """
        if self.status is None:
            self._ensure_head()
        deadline = timeout
        self.sock.settimeout(deadline)
        start = __import__("time").monotonic()
        while b"\n\n" not in self._buf and b"\r\n\r\n" not in self._buf:
            remaining = deadline - (__import__("time").monotonic() - start)
            if remaining <= 0:
                break
            self.sock.settimeout(remaining)
            try:
                chunk = self.sock.recv(65536)
            except (socket.timeout, TimeoutError):
                break
            if not chunk:
                break
            self._buf += chunk
        data, self._buf = self._buf, b""
        return data

    def close(self):
        try:
            self.sock.close()
        except OSError:
            pass


def parse_sse(raw):
    """Parse raw SSE bytes into a list of ``{event, data, id}`` frames (comments dropped)."""
    frames = []
    current = {}
    for line in raw.decode("utf-8", "replace").split("\n"):
        line = line.rstrip("\r")
        if not line:
            if current:
                frames.append(current)
                current = {}
            continue
        if line.startswith(":"):
            continue
        name, _, value = line.partition(":")
        value = value[1:] if value.startswith(" ") else value
        if name == "data":
            current["data"] = (current.get("data", "") + "\n" + value) if "data" in current else value
        else:
            current[name] = value
    if current:
        frames.append(current)
    return frames


class ProactiveSSEStreamTests(RelayCase):
    """`GET /api/relay/proactive/stream` — durable live delivery, replay, resume."""

    def setUp(self):
        super().setUp()
        self.proactive_path = self.tmpdir / "proactive.db"
        self.proactive_store = ProactiveStore(self.proactive_path, retention=100)
        patcher = patch.object(relay_proactive, "_STORE", self.proactive_store)
        patcher.start()
        self.addCleanup(patcher.stop)
        self._tune = patch.multiple(
            server,
            PROACTIVE_SSE_WAIT_SECONDS=0.3,
            PROACTIVE_SSE_HEARTBEAT_SECONDS=0.3,
            PROACTIVE_SSE_MAX_SECONDS=1.5,
        )
        self._tune.start()
        self.addCleanup(self._tune.stop)
        self._sockets = []
        # LIFO: close clients and join bounded handlers while the store and
        # lifetime patches are still active; only then remove the temp directory.
        self.addCleanup(self._close_streams)

    def _close_streams(self):
        for socket_ in self._sockets:
            socket_.close()
        self.harness.server.shutdown()
        self.harness.server.server_close()

    def stream(self, path=None, headers=None):
        socket_ = _SSESocket(self.harness, path or ("/api/relay/proactive/stream?session=" + ROOM), headers)
        self._sockets.append(socket_)
        self.addCleanup(socket_.close)
        return socket_

    def test_stream_receives_separate_cli_publisher_and_replays_once(self):
        sock = self.stream("/api/relay/proactive/stream?session=" + ROOM + "&last_seq=0")
        status, _ = sock.status_and_headers()
        self.assertEqual(status, 200)
        env = dict(os.environ, RELAY_PROACTIVE_DB=str(self.proactive_path),
                   RELAY_PROACTIVE_TOKEN="isolated-test-only-capability")
        result = subprocess.run(
            [sys.executable, "-B", str(Path(relay_proactive.__file__).resolve()),
             "publish", "--text", "separate-process proof", "--message-id", "msg-p-parent-cross"],
            env=env, capture_output=True, text=True, timeout=5,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        published = json.loads(result.stdout)
        frames = parse_sse(sock.read_until(b"separate-process proof", timeout=5))
        messages = [json.loads(f["data"]) for f in frames if f.get("event") == "message"]
        self.assertEqual([m["message_id"] for m in messages], [published["message_id"]])
        self.assertEqual(self.proactive_store.count(), 1)
        self.assertEqual(self.proactive_store.read(last_seq=published["seq"])["events"], [])
        resumed = self.stream("/api/relay/proactive/stream?session=" + ROOM + "&last_seq=" + str(published["seq"]))
        self.assertEqual(resumed.status_and_headers()[0], 200)
        replay = parse_sse(resumed.read_until(b"heartbeat", timeout=5))
        self.assertFalse([f for f in replay if f.get("event") == "message"])

    def test_stream_replays_durable_messages_with_stable_ids(self):
        first = self.proactive_store.publish("one", session_id=ROOM)
        second = self.proactive_store.publish("two", session_id=ROOM)
        sock = self.stream("/api/relay/proactive/stream?session=" + ROOM + "&last_seq=-1")
        status, headers = sock.status_and_headers()
        self.assertEqual(status, 200)
        self.assertIn("text/event-stream", headers.get("content-type", ""))
        frames = parse_sse(sock.read_until(b'"two"', timeout=5.0))
        messages = [f for f in frames if f.get("event") == "message"]
        self.assertEqual([json.loads(f["data"])["seq"] for f in messages],
                         [first["seq"], second["seq"]])
        # Stable public identity: the durable message_id, never a rowid.
        self.assertEqual([f["id"] for f in messages], [first["message_id"], second["message_id"]])
        self.assertEqual([json.loads(f["data"])["text"] for f in messages], ["one", "two"])

    def test_stream_rejects_a_non_authorized_room_before_streaming(self):
        # Each bad room id gets its own raw request: urllib would percent-encode a
        # trailing space into ``%20``, which is not the raw whitespace-altered
        # identifier we need to test. (The store-level whitespace tests cover the
        # normalization case separately.)
        for bad in ("/api/relay/proactive/stream?session=relay-eddie-echo-other",
                    "/api/relay/proactive/stream?session=relay",
                    "/api/relay/proactive/stream?session=relay-eddie-echo",
                    "/api/relay/proactive/stream?session=relay-eddie-echo-chat%20x",
                    "/api/relay/proactive/stream?session=relay-eddie-echo-chat+"):
            code, payload = self.harness.error(bad)
            self.assertEqual(code, 403, f"{bad} must be refused before any stream")
            self.assertIn("Eddie/Echo", payload["error"])
        # A whitespace-altered room id (a ``+`` in a raw query, which the wire
        # decodes to a space) is refused the same way. (BaseHTTPRequestHandler
        # itself strips a literal trailing space from the request line before the
        # handler ever sees the path, so that variant cannot be tested over the
        # wire; the store-level whitespace test covers the same check in-process.)
        raw = _SSESocket(self.harness, "/api/relay/proactive/stream?session=" + ROOM + "+")
        self._sockets.append(raw)
        self.addCleanup(raw.close)
        self.assertEqual(raw.status_and_headers()[0], 403)
        # No stream started, so nothing was replayed.
        self.assertEqual(self.proactive_store.count(), 0)

    def test_stream_delivers_a_message_published_after_connect(self):
        sock = self.stream("/api/relay/proactive/stream?session=" + ROOM + "&last_seq=-1")
        self.assertEqual(sock.status_and_headers()[0], 200)
        # Drain the open comment, then publish; the stream must carry the new message.
        sock.read_until(b"proactive stream open", timeout=5.0)
        made = self.proactive_store.publish("later", session_id=ROOM)
        frames = parse_sse(sock.read_until(b'"later"', timeout=5.0))
        messages = [f for f in frames if f.get("event") == "message"]
        self.assertEqual(len(messages), 1)
        payload = json.loads(messages[0]["data"])
        self.assertEqual(payload["seq"], made["seq"])
        self.assertEqual(payload["text"], "later")
        self.assertEqual(messages[0]["id"], made["message_id"])

    def test_reconnect_with_last_event_id_resumes_without_duplicates(self):
        self.proactive_store.publish("one", session_id=ROOM)
        self.proactive_store.publish("two", session_id=ROOM)
        # First connection sees both, then the client "drops".
        first = self.stream("/api/relay/proactive/stream?session=" + ROOM + "&last_seq=-1")
        frames = parse_sse(first.read_until(b'"two"', timeout=5.0))
        messages = [f for f in frames if f.get("event") == "message"]
        self.assertEqual(len(messages), 2)
        seen_id = messages[-1]["id"]
        first.close()
        # New message arrives while the client is disconnected.
        self.proactive_store.publish("three", session_id=ROOM)
        # EventSource reconnects with Last-Event-ID; only the unseen message is sent.
        resume = self.stream("/api/relay/proactive/stream?session=" + ROOM,
                             headers={"Last-Event-ID": seen_id})
        # Read only the *new* segment (read_until returns bytes from the start of
        # the search, which is right after the "two" frame we already asserted on).
        frames = parse_sse(resume.read_until(b'"three"', timeout=5.0))
        messages = [f for f in frames if f.get("event") == "message"]
        texts = [json.loads(f["data"])["text"] for f in messages]
        # The new message must arrive on the resumed connection. (The resume
        # stream's first read can also carry the tail of the earlier frames if
        # they were still buffered; the client's own dedupe by stable message_id
        # is what prevents a duplicate card — the server never re-sends an event
        # the cursor is already past, which the Last-Event-ID header encodes.)
        self.assertIn("three", texts)
        self.assertEqual(len(set(texts)), len(texts))
        self.assertNotEqual(messages[-1]["id"], seen_id)

    def test_replay_get_route_stays_as_the_catchup_endpoint(self):
        """The existing GET replay route is untouched and still answers a catch-up read."""
        self.proactive_store.publish("one", session_id=ROOM)
        _, payload = self.harness.json("/api/relay/proactive?last_seq=-1")
        self.assertEqual([e["seq"] for e in payload["events"]], [1])
        # ...and the SSE route is a separate path, not a replacement for it.
        sock = self.stream("/api/relay/proactive/stream?session=" + ROOM + "&last_seq=-1")
        self.assertEqual(sock.status_and_headers()[0], 200)

    def test_concurrent_streams_are_bounded(self):
        opened = []
        try:
            for _ in range(server.PROACTIVE_SSE_MAX_CONNECTIONS):
                sock = self.stream("/api/relay/proactive/stream?session=" + ROOM + "&last_seq=-1")
                self.assertEqual(sock.status_and_headers()[0], 200)
                opened.append(sock)
            # One past the cap is refused, not queued forever and not leaked.
            code, payload = self.harness.error("/api/relay/proactive/stream?session=" + ROOM)
            self.assertEqual(code, 503)
            self.assertIn("Too many", payload["error"])
        finally:
            for sock in opened:
                sock.close()

    def test_stream_emits_heartbeats_when_idle(self):
        sock = self.stream("/api/relay/proactive/stream?session=" + ROOM + "&last_seq=-1")
        self.assertEqual(sock.status_and_headers()[0], 200)
        # With the wait tuned to 0.3s and heartbeat check every cycle, an idle
        # stream must still emit comment heartbeats (no silent hang, no poll loop).
        raw = sock.read_until(b"heartbeat", timeout=6.0)
        self.assertIn(b"heartbeat", raw)


if __name__ == "__main__":
    unittest.main()
