"""Isolated Relay HTTP harness: an in-process Relay handler on an ephemeral loopback port.

Each test binds ``127.0.0.1:0`` with an explicit Host allowlist, points ``relay_chat`` at
an isolated SQLite store and a fake Hermes API, and never touches the production ports or
the held outbox database.
"""
from __future__ import annotations

import io
import json
import os
import socket
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from email.message import Message
from pathlib import Path
from unittest.mock import patch

import relay_store

sys.path.insert(0, str(Path(__file__).resolve().parent))

import relay_chat  # noqa: E402
import relay_decisions  # noqa: E402
import relay_media  # noqa: E402
import relay_runner  # noqa: E402
from server import Handler  # noqa: E402
import fake_hermes  # noqa: E402

PNG_1PX = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
    "890000000d4944415478da63f8cf400f0005e102019d12f4d40000000049454e44ae426082")
JPEG_MIN = bytes.fromhex("ffd8ffe000104a46494600010100000100010000ffdb004300"
                         "080606070605080707070909080a0c140d0c0b0b0c1912130f141d1a1f1e1d1a1c1c20242e2720222c231c1c2837292c30313434341f27393d38323c2e333432ffc0000b080001000101011100ffc40014100100000000000000000000000000000000ffda0008010100003f00d2cf20ffd9")
SVG = b"<svg xmlns='http://www.w3.org/2000/svg'><script>alert(1)</script></svg>"


class RelayHarness:
    """One isolated Relay server + fake Hermes API + isolated SQLite store."""

    def __init__(self, tmpdir: Path, *, approval_forwards_reason=False):
        self.tmpdir = Path(tmpdir)
        self.fake = fake_hermes.FakeHermes(approval_forwards_reason=approval_forwards_reason)
        self.store = relay_store.reset_store_for_tests(self.tmpdir / "relay-state.db")
        relay_media.MEDIA_DIR = self.tmpdir / "media"
        relay_decisions.reset_capability_cache()
        relay_decisions._CAPABILITY = {"native": approval_forwards_reason,
                                       "how": "test",
                                       "detail": "test fixture"}
        relay_chat.STORE = self.store
        relay_chat.DECISIONS = relay_decisions.DecisionStore(
            client=relay_decisions.NativeRunClient(self.fake.base, "test-key"), store=self.store)
        relay_chat.RUNNERS = relay_runner.RunRegistry(self.store, self.fake.base, "test-key")
        relay_chat.BASE = self.fake.base
        relay_decisions.BASE = self.fake.base
        with patch.object(relay_chat, "_key", return_value="test-key"), \
                patch.object(relay_decisions, "read_api_server_key", return_value="test-key"):
            pass
        self._orig_key = relay_chat._key
        relay_chat._key = lambda: "test-key"
        self.server = self._start()

    def _start(self):
        host = "127.0.0.1:%d" % self.port if False else None
        harness = self

        class LocalHandler(Handler):
            ALLOWED_HOSTS = set()
            ALLOWED_ORIGINS = set()

        port = self._free_port()
        LocalHandler.ALLOWED_HOSTS = {f"127.0.0.1:{port}"}
        LocalHandler.ALLOWED_ORIGINS = {f"http://127.0.0.1:{port}"}
        server = ThreadingHTTPServerLocal(("127.0.0.1", port), LocalHandler)
        self.base = f"http://127.0.0.1:{port}"
        self.thread = threading.Thread(target=server.serve_forever, daemon=True)
        self.thread.start()
        return server

    @staticmethod
    def _free_port():
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        sock.close()
        return port

    @property
    def port(self):
        return self.server.server_address[1]

    def request(self, path, body=None, headers=None, method=None, raw=None, content_type="application/json"):
        data = raw if raw is not None else (json.dumps(body).encode("utf-8") if body is not None else None)
        request = urllib.request.Request(
            self.base + path,
            data=data,
            headers={"Host": f"127.0.0.1:{self.port}", "Content-Type": content_type,
                     **(headers or {})},
            method=method or ("POST" if data is not None else "GET"),
        )
        try:
            return urllib.request.urlopen(request, timeout=10)
        except urllib.error.HTTPError:
            raise

    def json(self, path, body=None, headers=None, method=None, raw=None, content_type="application/json"):
        response = self.request(path, body, headers, method, raw, content_type)
        payload = json.loads(response.read().decode("utf-8") or "{}")
        return response, payload

    def error(self, path, body=None, headers=None, method=None, raw=None, content_type="application/json"):
        try:
            self.request(path, body, headers, method, raw, content_type)
        except urllib.error.HTTPError as exc:
            payload = json.loads(exc.read().decode("utf-8") or "{}")
            return exc.code, payload
        raise AssertionError(f"{path} did not fail")

    def close(self):
        try:
            self.server.shutdown()
            self.server.server_close()
        finally:
            self.fake.close()
            relay_chat._key = self._orig_key


class ThreadingHTTPServerLocal:
    """Thin wrapper so the harness can reuse BaseHTTPRequestHandler without importing
    ThreadingHTTPServer by name into every test module."""

    def __init__(self, address, handler_cls):
        from http.server import ThreadingHTTPServer

        self._server = ThreadingHTTPServer(address, handler_cls)
        # Test-owned handler threads must finish before disposable stores vanish.
        self._server.daemon_threads = False
        self._server.block_on_close = True

    @property
    def server_address(self):
        return self._server.server_address

    def serve_forever(self):
        self._server.serve_forever()

    def shutdown(self):
        self._server.shutdown()

    def server_close(self):
        self._server.server_close()


class RelayCase(unittest.TestCase):
    """Base class: one isolated harness per test."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="relay-gaps-", dir=os.environ.get("TMPDIR"))
        self.tmpdir = Path(self._tmp.name)
        self.harness = RelayHarness(self.tmpdir)
        # unittest cleanup is LIFO: shut down/join before removing SQLite files.
        self.addCleanup(self._tmp.cleanup)
        self.addCleanup(self.harness.close)

    def stage_png(self, session_id="relay-eddie-echo-chat", name="shot.png", data=PNG_1PX):
        _, payload = self.harness.json("/api/relay/media/upload",
                                       {"data": __import__("base64").b64encode(data).decode(),
                                        "name": name, "session_id": session_id})
        return payload
