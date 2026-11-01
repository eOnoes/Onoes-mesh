"""Isolated HTTP tests for the Relay Web Push routes (source slice, no delivery).

Every test runs the real ``server.Handler`` on an ephemeral loopback port with
an isolated push database and an isolated capability, mirroring
``relay_test_harness``. Nothing here touches 8772, the production store, a real
provider, or a phone.

The HTTP layer is what has to fail closed when the *owner setup* is missing,
so those refusals are asserted first: no VAPID key and no ``cryptography``
package means enrollment must answer "setup is not ready", not "here is a
half-working feature".
"""
from __future__ import annotations

import base64
import json
import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

import relay_push  # noqa: E402
from relay_push import PushStore, mint_capability  # noqa: E402
from test_relay_push import FCM, APPLE, subscription  # noqa: E402

from http.server import ThreadingHTTPServer  # noqa: E402


class PushHTTPCase(unittest.TestCase):
    """One ephemeral handler + one isolated push database per test."""

    def setUp(self):
        # TMPDIR is explicit: the system TEMP can otherwise win on this host.
        self._tmp = tempfile.TemporaryDirectory(
            prefix="relay-push-http-", dir=os.environ.get("TMPDIR"))
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)
        self._env = mock.patch.dict(os.environ, {}, clear=False)
        self._env.start()
        self.addCleanup(self._env.stop)
        for name in (relay_push.TOKEN_ENV, relay_push.DEVICE_ENV,
                     relay_push.HOSTS_ENV, "RELAY_PUSH_DB", relay_push.VAPID_PUBLIC_ENV, relay_push.VAPID_PRIVATE_ENV):
            os.environ.pop(name, None)

        import server  # noqa: WPS433 (imported here so RELAY_PUSH_DB applies)
        self.server_module = server
        self.store = PushStore(self.dir / "push.db")
        server.RELAY_PUSH_STORE = self.store

        port = self._free_port()

        class LocalHandler(server.Handler):
            ALLOWED_HOSTS = {f"127.0.0.1:{port}"}
            ALLOWED_ORIGINS = {f"http://127.0.0.1:{port}"}

        self.httpd = ThreadingHTTPServer(("127.0.0.1", port), LocalHandler)
        self.httpd.daemon_threads = False
        self.httpd.block_on_close = True
        self.port = port
        self.base = f"http://127.0.0.1:{port}"
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self._close)

    def _close(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=10)
        self.server_module.RELAY_PUSH_STORE = None

    @staticmethod
    def _free_port():
        import socket
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        port = sock.sock.getsockname()[1] if hasattr(sock, "sock") else sock.getsockname()[1]
        sock.close()
        return port

    def request(self, path, body=None, headers=None, method=None):
        import urllib.request
        import urllib.error
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(
            self.base + path, data=data,
            headers={"Host": f"127.0.0.1:{self.port}", "Content-Type": "application/json",
                     **(headers or {})},
            method=method or ("POST" if data is not None else "GET"))
        try:
            response = urllib.request.urlopen(req, timeout=10)
        except urllib.error.HTTPError as exc:
            response = exc
        try:
            return response.status, json.loads(response.read().decode("utf-8") or "{}"), response.headers
        finally:
            response.close()

    def issue(self, device="Eddie phone", seconds=900):
        capability = mint_capability(device, expires_in=seconds)
        os.environ[relay_push.TOKEN_ENV] = capability
        return capability

    def enroll_ok(self, device="Eddie phone"):
        self.issue(device)
        code, payload, _ = self.request(
            "/api/relay/push/enroll",
            {"device": device, "subscription": subscription()},
            headers={"Authorization": f"Bearer {os.environ[relay_push.TOKEN_ENV]}"})
        self.assertEqual(code, 200, payload)
        return payload


    def provisioned(self):
        """Stand in for parent provisioning: dependency importable + VAPID set.

        The dependency itself is not installed on this host (see the receipt),
        so the *readiness probe* is stubbed at its one import point. The
        enrollment logic that runs after the probe is the real code path.
        """
        stub = mock.Mock(return_value=None)
        patcher = mock.patch.object(relay_push, "require_delivery_ready", stub)
        patcher.start()
        self.addCleanup(patcher.stop)
        os.environ[relay_push.VAPID_PUBLIC_ENV] = base64.urlsafe_b64encode(
            b"\x04" + b"D" * 64).decode().rstrip("=")
        os.environ[relay_push.VAPID_PRIVATE_ENV] = "test-private-key-not-a-real-one"
        return self

    def push_send(self, body=None, headers=None):
        """POST a push/send body; the route must not exist in this slice."""
        return self.request("/api/relay/push/send",
                            {"message_id": "m1"} if body is None else body,
                            headers=headers or {})


class OwnerSetupReadinessTests(PushHTTPCase):
    """Source completion and owner setup readiness are different things."""

    def test_status_without_setup_is_ready_to_serve_but_not_ready_to_enroll(self):
        code, payload, headers = self.request("/api/relay/push/status")
        self.assertEqual(code, 200)
        self.assertFalse(payload["configured"])
        self.assertFalse(payload["enrolled"])
        self.assertFalse(payload["enabled"])
        # Honest about the two separate blockers, so the UI can show them.
        self.assertIn("vapid", payload)
        self.assertIn("enrollment", payload)
        self.assertEqual(payload["recipient"], "Eddie")
        self.assertEqual(payload["room"], "relay-eddie-echo-chat")
        self.assertEqual(headers.get("Cache-Control"), "no-store")

    def test_enroll_with_an_unconfigured_or_wrong_capability_is_refused(self):
        # With nothing set up at all, an unprovisioned PC must still refuse the
        # *identity* half first: no capability, no enrollment, no probing.
        code, payload, _ = self.request(
            "/api/relay/push/enroll",
            {"device": "Eddie phone", "subscription": subscription()},
            headers={"Authorization": "Bearer made-up"})
        self.assertEqual(code, 503)
        self.assertIn("phone push delivery", payload["error"].lower())
        self.assertEqual(self.store.status()["enrolled"], False)

        # Once the dependency and keys *are* present, an unconfigured or wrong
        # capability is an authorization failure, not a setup one.
        self.provisioned()
        code, payload, _ = self.request(
            "/api/relay/push/enroll",
            {"device": "Eddie phone", "subscription": subscription()},
            headers={"Authorization": "Bearer made-up"})
        self.assertEqual(code, 503)
        self.assertIn("not configured", payload["error"].lower())
        self.issue("Eddie phone")
        code, payload, _ = self.request(
            "/api/relay/push/enroll",
            {"device": "Eddie phone", "subscription": subscription()},
            headers={"Authorization": f"Bearer {mint_capability('Eddie phone')}"})
        self.assertEqual(code, 403)
        self.assertEqual(self.store.status()["enrolled"], False)

    def test_enroll_without_any_authorization_header_is_403(self):
        self.issue()
        code, payload, _ = self.request(
            "/api/relay/push/enroll",
            {"device": "Eddie phone", "subscription": subscription()})
        self.assertEqual(code, 403)
        self.assertEqual(self.store.status()["enrolled"], False)

    def test_enroll_is_refused_while_delivery_is_not_provisioned(self):
        # A subscription can be cryptographically valid and still be refused,
        # because nothing on this PC can encrypt a payload for it yet.
        self.issue()
        code, payload, _ = self.request(
            "/api/relay/push/enroll",
            {"device": "Eddie phone", "subscription": subscription()},
            headers={"Authorization": f"Bearer {os.environ[relay_push.TOKEN_ENV]}"})
        self.assertEqual(code, 503, payload)
        self.assertTrue("cryptography" in payload["error"].lower() or "vapid" in payload["error"].lower())
        self.assertEqual(self.store.status()["enrolled"], False)
        # The capability is NOT burned by a setup refusal: the parent's
        # one-use grant stays usable until setup is finished. The store
        # confirms nothing was recorded.
        self.assertEqual(self.store.counts()["capabilities"], 0)
        self.assertFalse(self.store.capability_used(os.environ[relay_push.TOKEN_ENV]))

    def test_push_send_route_does_not_exist(self):
        # No standing publisher door exists in this slice. Any attempt at a
        # send endpoint falls through to the generic handler and 404s; there is
        # nothing to activate, so a grant cannot be silently reactivated.
        code, payload, _ = self.request("/api/relay/push/send", {"message_id": "m1"})
        self.assertEqual(code, 404)
        self.assertIn("error", payload)
        self.assertEqual(self.store.counts()["active"], 0)


class EnrollmentHTTPTests(PushHTTPCase):
    def test_owner_setup_handoff_requires_proxy_identity_and_is_one_use(self):
        self.provisioned()
        token = self.issue()
        os.environ["RELAY_PUSH_OWNER_LOGIN"] = "emitchell109@gmail.com"
        self.httpd.RequestHandlerClass.ALLOWED_HOSTS.add("emitchell.tail8c4a75.ts.net:8450")
        headers = {"Host": "emitchell.tail8c4a75.ts.net:8450"}
        for identity in (None, "someone-else@example.com"):
            supplied = dict(headers)
            if identity:
                supplied["Tailscale-User-Login"] = identity
            code, result, _ = self.request("/api/relay/push/setup", {}, headers=supplied)
            self.assertEqual(code, 403)
            self.assertNotIn("capability", result)
        headers["Tailscale-User-Login"] = "emitchell109@gmail.com"
        code, result, _ = self.request("/api/relay/push/setup", {}, headers=headers)
        self.assertEqual(code, 200)
        self.assertEqual(result["capability"], token)
        self.assertEqual(result["device"], "Eddie phone")
        code, _, _ = self.request("/api/relay/push/enroll", {"device":"Eddie phone","subscription":subscription()}, headers={"Authorization":"Bearer " + token})
        self.assertEqual(code, 200)
        self.assertNotIn(relay_push.TOKEN_ENV, os.environ)
        code, result, _ = self.request("/api/relay/push/setup", {}, headers=headers)
        self.assertNotEqual(code, 200)
        self.assertNotIn("capability", result)

    def test_name_alone_or_wrong_subscription_cannot_revoke(self):
        self.provisioned()
        self.enroll_ok()
        code, _, _ = self.request("/api/relay/push/revoke", {"device": "Eddie phone"})
        self.assertEqual(code, 400)
        wrong = subscription()
        wrong["keys"]["auth"] = "not-the-secret"
        code, _, _ = self.request("/api/relay/push/revoke", {"device": "Eddie phone", "subscription": wrong})
        self.assertEqual(code, 403)
        self.assertTrue(self.store.status()["enrolled"])

    """The same enrollment path, exercised once the parent has provisioned."""

    def test_enroll_status_revoke_round_trip(self):
        self.provisioned()
        payload = self.enroll_ok()
        self.assertTrue(payload["enrolled"])

        code, status, _ = self.request("/api/relay/push/status")
        self.assertEqual(code, 200)
        self.assertTrue(status["configured"])
        self.assertTrue(status["enrolled"])
        self.assertTrue(status["enabled"])
        self.assertEqual(status["device"], "Eddie phone")
        # Secrets never leave the server.
        blob = json.dumps(status)
        # The provider allowlist is public information; a subscription's
        # *endpoint* is not.
        self.assertIn("provider_hosts", status)
        for secret in ("keys", "p256dh", os.environ[relay_push.VAPID_PRIVATE_ENV]):
            self.assertNotIn(secret, blob)

        # The capability was burned at enroll time, so it is NOT a standing
        # revocation authority. The phone revokes its own enrollment, and a
        # repeated revoke is an honest no-op rather than a second effect.
        code, payload, _ = self.request("/api/relay/push/revoke", {"device": "Eddie phone", "subscription": subscription()})
        self.assertEqual(code, 200)
        self.assertTrue(payload["revoked"])
        code, payload, _ = self.request("/api/relay/push/revoke", {"device": "Eddie phone", "subscription": subscription()})
        self.assertEqual(code, 403)
        self.assertIn("error", payload)

    def test_status_never_echoes_a_subscription(self):
        self.provisioned()
        self.enroll_ok()
        code, text, _ = None, None, None
        import urllib.request
        raw = urllib.request.urlopen(self.base + "/api/relay/push/status", timeout=10).read()
        # The subscription endpoint (which contains Google's registration id)
        # must never appear. The provider *allowlist* is public and may.
        self.assertNotIn(FCM.split("/fcm/")[1].encode(), raw)
        self.assertNotIn(b'"endpoint"', raw)
        self.assertNotIn(b"p256dh", raw)

    def test_enroll_rejects_a_foreign_provider(self):
        self.provisioned()
        self.issue()
        code, payload, _ = self.request(
            "/api/relay/push/enroll",
            {"device": "Eddie phone", "subscription": subscription("https://evil.example/p")},
            headers={"Authorization": f"Bearer {os.environ[relay_push.TOKEN_ENV]}"})
        self.assertIn(code, (400, 403))
        self.assertNotIn("evil.example", json.dumps(payload))

    def test_enroll_rejects_a_wrong_device_name(self):
        self.provisioned()
        self.issue("Eddie phone")
        code, payload, _ = self.request(
            "/api/relay/push/enroll",
            {"device": "someone else", "subscription": subscription()},
            headers={"Authorization": f"Bearer {os.environ[relay_push.TOKEN_ENV]}"})
        self.assertEqual(code, 403)
        self.assertEqual(self.store.status()["enrolled"], False)

    def test_enroll_body_shape_is_validated(self):
        self.provisioned()
        self.issue()
        for body, label in [
            ({}, "empty"),
            ({"subscription": subscription()}, "no device"),
            ({"device": "Eddie phone"}, "no subscription"),
            ({"device": "Eddie phone", "subscription": {"endpoint": FCM}}, "no keys"),
            ({"device": "Eddie phone", "subscription": subscription("https://evil.example/p")}, "foreign"),
            ({"device": "Eddie phone", "subscription": subscription("http://fcm.googleapis.com/fcm/send/x")}, "insecure"),
        ]:
            with self.subTest(case=label):
                self.issue()
                code, payload, _ = self.request(
                    "/api/relay/push/enroll", body,
                    headers={"Authorization": f"Bearer {os.environ[relay_push.TOKEN_ENV]}"})
                self.assertIn(code, (400, 403), payload)
        self.assertEqual(self.store.status()["enrolled"], False)

    def test_non_json_and_oversized_bodies_are_refused(self):
        self.provisioned()
        code, _payload, _headers = 0, None, None
        import urllib.request
        import urllib.error
        req = urllib.request.Request(
            self.base + "/api/relay/push/enroll", data=b"not json",
            headers={"Host": f"127.0.0.1:{self.port}",
                     "Content-Type": "text/plain"}, method="POST")
        try:
            urllib.request.urlopen(req, timeout=10)
            self.fail("a non-JSON content type was not refused")
        except urllib.error.HTTPError as exc:
            self.assertEqual(exc.code, 415)
        self.issue()
        code, payload, _ = self.request(
            "/api/relay/push/enroll",
            {"device": "Eddie phone", "subscription": subscription()},
            headers={"Authorization": f"Bearer {os.environ[relay_push.TOKEN_ENV]}",
                     "Content-Length": "999999"})
        self.assertIn(code, (400, 413))

    def test_host_and_origin_boundaries_still_apply(self):
        self.provisioned()
        import urllib.request
        import urllib.error
        # A page from another origin cannot reach the push routes at all.
        req = urllib.request.Request(
            self.base + "/api/relay/push/status",
            headers={"Host": f"127.0.0.1:{self.port}",
                     "Origin": "https://evil.example"})
        try:
            urllib.request.urlopen(req, timeout=10)
            self.fail("foreign Origin was not refused")
        except urllib.error.HTTPError as exc:
            self.assertEqual(exc.code, 403)


if __name__ == "__main__":
    unittest.main(verbosity=2)
