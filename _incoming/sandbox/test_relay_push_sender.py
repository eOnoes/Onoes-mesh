"""Isolated tests for the real Relay Web Push sender.

Run from the sandbox root with the existing vendored Web Push dependencies:

    PYTHONPATH=.webpush-lib python -m unittest -v test_relay_push_sender.py

The suite uses ephemeral P-256 keys only, builds an ephemeral receiver
subscription, and injects an in-memory HTTP session. It never reads or writes
the owner's production key, environment, subscription store, or network.
"""

import base64
import inspect
import json
import unittest
from unittest import mock

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from requests import Request, Response
from requests.exceptions import TooManyRedirects

import relay_push_sender as sender

try:
    import pywebpush
except ImportError:  # pragma: no cover - the documented dependency is required.
    pywebpush = None


def _raw(data):
    """Normalize the request body into a bytes-like object for inspection."""
    if isinstance(data, bytes):
        return data
    if isinstance(data, Request):
        return data.body
    if isinstance(data, (bytearray, memoryview)):
        return bytes(data)
    return data.encode("utf-8") if isinstance(data, str) else data


class _NoRedirectAdaptedSession:
    """Matches the real Session.post redirect contract while recording the request."""

    def __init__(self, wrapped):
        self._wrapped = wrapped

    def post(self, url, **kwargs):
        kwargs.setdefault("allow_redirects", True)
        return self._wrapped.post(url, **kwargs)


class MockSession:
    """In-memory replacement for requests.Session with request inspection."""

    def __init__(self, *, status=201, json_body=None, error=None):
        self.status = status
        self.json_body = json_body if json_body is not None else {"message_id": "mock-message-123"}
        self.error = error
        self.calls = []

    def post(self, url, data=None, headers=None, **kwargs):
        # pywebpush's WebPusher calls this as post(endpoint, timeout=...,
        # data=encoded, headers=signed). Forward data/headers explicitly so
        # the mock sees the same transport signature as requests.Session.post.
        self.calls.append({"url": url, "kwargs": {**kwargs, "data": data, "headers": headers}})
        if self.error is not None:
            raise self.error
        response = Response()
        response.status_code = self.status
        response._content = json.dumps(self.json_body).encode("utf-8")
        response.url = url
        return response


class RedirectingSession:
    """A session that must not be asked to follow provider redirects."""

    def __init__(self):
        self.calls = 0

    def post(self, url, **kwargs):
        self.calls += 1
        raise TooManyRedirects("redirect loop")


def _ephemeral_receiver_subscription():
    receiver_private = ec.generate_private_key(ec.SECP256R1())
    receiver_public = receiver_private.public_key()
    p256dh = base64.urlsafe_b64encode(
        receiver_public.public_bytes(
            serialization.Encoding.X962,
            serialization.PublicFormat.UncompressedPoint,
        )
    ).decode("ascii").rstrip("=")
    auth = base64.urlsafe_b64encode(b"test-auth-secret").decode("ascii").rstrip("=")
    endpoint = sender.PROVIDER_PREFIX + "ephemeral-receiver-token"
    return endpoint, p256dh, auth


def _ephemeral_vapid_key():
    private = ec.generate_private_key(ec.SECP256R1())
    return base64.urlsafe_b64encode(
        private.private_bytes(
            serialization.Encoding.DER,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    ).decode("ascii").rstrip("=")


@unittest.skipIf(pywebpush is None, "pywebpush is required")
class SenderTests(unittest.TestCase):
    def setUp(self):
        # The real p256dh key must be a compressed/uncompressed P-256 EC point,
        # not arbitrary bytes disguised as base64url; generate a receiver key
        # exactly as a browser Web Push subscription does.
        self.endpoint, self.subscription_key, self.auth_key = _ephemeral_receiver_subscription()
        self.vapid_private_key = _ephemeral_vapid_key()
        self.claims = {"sub": "mailto:relay-test@onoes.invalid"}

    def _send(self, session, **overrides):
        arguments = {
            "endpoint": self.endpoint,
            "subscription_key": self.subscription_key,
            "auth_key": self.auth_key,
            "vapid_private_key": self.vapid_private_key,
            "vapid_claims": self.claims,
            "session": session,
            "timeout": 3,
            "silent": False,
        }
        arguments.update(overrides)
        return sender.send_push(**arguments)

    def test_real_payload_encryption_and_vapid_signature_with_201(self):
        session = MockSession()
        with mock.patch("pywebpush.webpush", wraps=pywebpush.webpush) as webpush:
            result = self._send(session)

        self.assertEqual(result, {"ok": True, "status": 201})
        self.assertEqual(webpush.call_count, 1)
        arguments, keywords = webpush.call_args
        self.assertEqual(keywords["content_encoding"], "aes128gcm")
        self.assertEqual(keywords["vapid_claims"]["sub"], self.claims["sub"])
        self.assertEqual(keywords["vapid_claims"]["aud"], sender.PROVIDER_ORIGIN)
        self.assertGreater(keywords["vapid_claims"]["exp"], 0)
        self.assertIs(keywords["requests_session"]._session, session)
        self.assertEqual(
            keywords["subscription_info"],
            {"endpoint": self.endpoint, "keys": {"p256dh": self.subscription_key, "auth": self.auth_key}},
        )

        # Verify that pywebpush actually called the injected session.post with
        # real encrypted bytes, a VAPID Authorization header, and
        # allow_redirects=False.
        self.assertEqual(len(session.calls), 1)
        call = session.calls[0]
        self.assertEqual(call["url"], self.endpoint)
        self.assertIs(call["kwargs"]["allow_redirects"], False)
        # pywebpush 2.5 passes encrypted data and signed VAPID headers as
        # separate session.post arguments; inspect the recorded values.
        headers = call["kwargs"].get("headers") or {}
        self.assertIn("Authorization", headers)
        self.assertTrue(headers["Authorization"].startswith("vapid t="))
        self.assertIn("k=", headers["Authorization"])
        body = call["kwargs"]["data"]
        self.assertIsInstance(body, bytes)
        self.assertGreaterEqual(len(body), 20)
        self.assertNotIn(b"Onoes Mesh", body)
        self.assertNotIn(b"New Relay message", body)
        self.assertNotIn(b"relay-eddie-echo-chat", body)

    def test_receiver_decrypts_actual_aes128gcm_payload(self):
        import http_ece
        private = ec.generate_private_key(ec.SECP256R1())
        public = private.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
        auth = b"0123456789abcdef"
        session = MockSession()
        result = self._send(session,
            subscription_key=base64.urlsafe_b64encode(public).decode().rstrip("="),
            auth_key=base64.urlsafe_b64encode(auth).decode().rstrip("="))
        self.assertTrue(result["ok"])
        plaintext = http_ece.decrypt(session.calls[0]["kwargs"]["data"], private_key=private, auth_secret=auth, version="aes128gcm")
        payload = json.loads(plaintext)
        self.assertEqual(payload["notification"]["body"], "New Relay message")
        self.assertNotIn("relay-eddie-echo-chat", plaintext.decode())

    def test_fixed_generic_payload_and_boolean_silent(self):
        payload = json.loads(sender.build_payload(silent=True))
        self.assertEqual(payload["notification"]["title"], "Onoes Mesh")
        self.assertEqual(payload["notification"]["body"], "New Relay message")
        self.assertIs(payload["notification"]["renotify"], True)
        self.assertIs(payload["notification"]["silent"], True)
        self.assertEqual(payload["data"], {"kind": "relay", "version": 1})
        with self.assertRaises(sender.PushDeliveryError):
            sender.build_payload(silent="yes")

    def test_expired_subscription_maps_410_to_subscription_expired(self):
        response = Response()
        response.status_code = 410
        response._content = b'{"error":{"code":"NOT_FOUND","message":"gone"}}'
        session = MockSession(error=pywebpush.WebPushException("expired", response=response))
        result = self._send(session)
        self.assertEqual(result, {"ok": False, "code": "subscription_expired", "status": 410})

    def test_redirect_is_reported_without_a_second_request(self):
        session = RedirectingSession()
        result = self._send(session)
        self.assertEqual(result, {"ok": False, "code": "redirect_blocked", "status": None})
        self.assertEqual(session.calls, 1)

    def test_real_410_and_http_redirect_outcomes(self):
        self.assertEqual(self._send(MockSession(status=410))["code"], "subscription_expired")
        session = MockSession(status=302)
        result = self._send(session)
        self.assertEqual(result["code"], "redirect_blocked")
        self.assertEqual(len(session.calls), 1)
        self.assertFalse(session.calls[0]["kwargs"]["allow_redirects"])

    def test_no_content_202_is_success(self):
        self.assertEqual(self._send(MockSession(status=202)), {"ok": True, "status": 202})

    def test_invalid_target_and_nonfinite_timeout_never_touch_transport(self):
        for target in ["https://fcm.googleapis.com/fcm/send/x?secret=x", "https://fcm.googleapis.com/fcm/send/x#x", "https://evil.example/fcm/send/x", "https://fcm.googleapis.com:443/fcm/send/x", "https://fcm.googleapis.com/fcm/send/x\n"]:
            session = MockSession()
            self.assertFalse(self._send(session, endpoint=target)["ok"])
            self.assertEqual(session.calls, [])
        for value in (float("nan"), float("inf"), 0):
            session = MockSession()
            self.assertFalse(self._send(session, timeout=value)["ok"])
            self.assertEqual(session.calls, [])

    def test_timeout_is_sanitized(self):
        from requests.exceptions import ReadTimeout
        session = MockSession(error=ReadTimeout("secret endpoint timeout"))
        result = self._send(session)
        self.assertEqual(result, {"ok": False, "code": "timeout", "status": None})

    def test_no_exception_message_contains_subscription_material(self):
        from requests.exceptions import ReadTimeout
        session = MockSession(error=ReadTimeout("secret endpoint timeout"))
        result = self._send(session)
        serialized = repr(result)
        self.assertNotIn(self.endpoint, serialized)
        self.assertNotIn(self.subscription_key, serialized)
        self.assertNotIn(self.auth_key, serialized)
        self.assertNotIn("secret endpoint", serialized)

    def test_http_receipt_does_not_require_provider_message_id(self):
        session = MockSession(json_body={"messageId": "  "})
        result = self._send(session)
        self.assertEqual(result, {"ok": True, "status": 201})

    def test_call_has_no_automatic_retry(self):
        session = MockSession(error=ReadTimeoutSafeError())
        first = self._send(session)
        second = self._send(session)
        self.assertEqual(first, second)
        self.assertEqual(len(session.calls), 2)  # One attempt per explicit call.

    def test_send_push_receives_secrets_explicitly_not_production_environment(self):
        signature = inspect.signature(sender.send_push)
        for required in ("endpoint", "subscription_key", "auth_key", "vapid_private_key", "session"):
            self.assertIn(required, signature.parameters)
            self.assertIsNotNone(signature.parameters[required].default)
        self.assertFalse(hasattr(sender, "load_production_keys"))


class ReadTimeoutSafeError(Exception):
    pass


if __name__ == "__main__":
    unittest.main(verbosity=2)
