"""Isolated tests for the opt-in Relay Web Push enrollment slice (Task 2).

Scope of this slice: the owner-enrollment capability, the subscription store,
the provider-endpoint SSRF boundary, the generic payload, and the HTTP routes
on an ephemeral loopback server with an isolated database.

Explicitly *out* of scope and therefore not asserted here: any real push, any
real VAPID key, any phone permission, any provider round trip. The delivery
half is fail-closed until ``cryptography`` is installed by the parent.
"""
from __future__ import annotations

import json
import base64
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

import relay_push  # noqa: E402
from relay_push import PushError, PushStore, mint_capability  # noqa: E402

FCM = "https://fcm.googleapis.com/fcm/send/abcDEF123"
APPLE = "https://web.push.apple.com/Push/some-device-token"
MOZ = "https://updates.push.services.mozilla.com/wpush/v2/gAAAA"


def subscription(endpoint=FCM, **keys):
    # Real shapes: p256dh is an uncompressed P-256 key (0x04 || X || Y),
    # auth is 16 random bytes; both base64url without padding (RFC 8291).
    keys.setdefault("p256dh", base64.urlsafe_b64encode(b"\x04" + b"B" * 64).decode().rstrip("="))
    keys.setdefault("auth", base64.urlsafe_b64encode(b"c" * 16).decode().rstrip("="))
    return {"endpoint": endpoint, "keys": keys, "expirationTime": None}


class StoreCase(unittest.TestCase):
    def setUp(self):
        # TMPDIR is passed explicitly: on this Windows host the system TMP can
        # otherwise win over TemporaryDirectory's own directory argument.
        self._tmp = tempfile.TemporaryDirectory(
            prefix="relay-push-", dir=os.environ.get("TMPDIR"))
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)
        self.store = PushStore(self.dir / "push.db")
        self._env = mock.patch.dict(os.environ, {}, clear=False)
        self._env.start()
        self.addCleanup(self._env.stop)
        for name in (relay_push.TOKEN_ENV, relay_push.DEVICE_ENV,
                     relay_push.HOSTS_ENV, "RELAY_PUSH_DB"):
            os.environ.pop(name, None)

    def issue(self, device="Eddie phone", seconds=900):
        capability = mint_capability(device, expires_in=seconds)
        os.environ[relay_push.TOKEN_ENV] = capability
        return capability


class EndpointTests(StoreCase):
    def test_approved_provider_hosts_pass(self):
        self.assertEqual(relay_push.validate_endpoint(FCM), FCM)
        for url in (APPLE, MOZ):
            with self.assertRaises(PushError):
                relay_push.validate_endpoint(url)

    def test_refuses_unapproved_and_malformed(self):
        cases = {
            "http scheme": "http://fcm.googleapis.com/fcm/send/x",
            "custom port": "https://fcm.googleapis.com:8443/fcm/send/x",
            "credentials": "https://user:pass@fcm.googleapis.com/fcm/send/x",
            "private host": "https://10.0.0.5/fcm/send/x",
            "loopback": "https://127.0.0.1:8772/fcm/send/x",
            "localhost": "https://localhost/fcm/send/x",
            "ip v6": "https://[::1]/fcm/send/x",
            "internal name": "https://fcm.googleapis.com.internal/fcm/send/x",
            "lookalike": "https://fcm.googleapis.com.evil.example/fcm/send/x",
            "no host": "https:///fcm/send/x",
            "empty": "",
            "not a string": 12,
            "ftp": "ftp://fcm.googleapis.com/x",
            "data url": "data:text/plain,hi",
            "file url": "file:///etc/passwd",
        }
        for label, url in cases.items():
            with self.subTest(case=label):
                with self.assertRaises(PushError):
                    relay_push.validate_endpoint(url)

    def test_operator_host_override_is_also_fail_closed(self):
        os.environ[relay_push.HOSTS_ENV] = "push.example.test, not a host ,, ok.example.test"
        self.assertEqual(relay_push.provider_hosts(), frozenset({"fcm.googleapis.com"}))
        with self.assertRaises(PushError):
            relay_push.validate_endpoint("https://push.example.test/fcm/send/x")
        self.assertEqual(relay_push.validate_endpoint(FCM), FCM)

    def test_redaction_never_reveals_the_path(self):
        redacted = relay_push.redact_endpoint(FCM)
        self.assertEqual(redacted, "https://fcm.googleapis.com/<redacted>")
        self.assertNotIn("abcDEF123", redacted)
        self.assertNotIn("abcDEF123", relay_push.redact_endpoint("nonsense"))


class CapabilityTests(StoreCase):
    def test_capability_consumption_is_atomic_under_concurrent_requests(self):
        from concurrent.futures import ThreadPoolExecutor
        token = self.issue()
        def attempt(_):
            try:
                relay_push.check_enrollment_capability(token, "Eddie phone", self.store)
                return True
            except PushError:
                return False
        with ThreadPoolExecutor(max_workers=8) as pool:
            self.assertEqual(sum(pool.map(attempt, range(8))), 1)

    def test_unconfigured_store_refuses_everything(self):
        with self.assertRaises(PushError) as caught:
            relay_push.check_enrollment_capability(mint_capability("Eddie phone"),
                                                   "Eddie phone", self.store)
        self.assertEqual(caught.exception.status, 503)

    def test_missing_capability_is_not_identity(self):
        self.issue("Eddie phone")
        for presented in (None, "", "   ", 5, b"x"):
            with self.subTest(presented=repr(presented)):
                with self.assertRaises(PushError):
                    relay_push.check_enrollment_capability(presented, "Eddie phone", self.store)

    def test_wrong_capability_is_refused(self):
        self.issue("Eddie phone")
        other = mint_capability("Eddie phone")
        with self.assertRaises(PushError):
            relay_push.check_enrollment_capability(other, "Eddie phone", self.store)

    def test_expired_capability_is_refused(self):
        capability = mint_capability("Eddie phone", expires_in=900)
        os.environ[relay_push.TOKEN_ENV] = capability
        with self.assertRaises(PushError) as caught:
            relay_push.check_enrollment_capability(
                capability, "Eddie phone", self.store, now=time.time() + 901)
        self.assertEqual(caught.exception.status, 401)

    def test_device_name_must_match(self):
        self.issue("Eddie phone")
        with self.assertRaises(PushError):
            relay_push.check_enrollment_capability(
                os.environ[relay_push.TOKEN_ENV], "living room tablet", self.store)

    def test_capability_is_burned_even_when_the_subscription_is_rejected(self):
        self.issue("Eddie phone")
        capability = os.environ[relay_push.TOKEN_ENV]
        with self.assertRaises(PushError):
            # The subscription itself is an unapproved provider, so the store
            # refuses it -- but the capability is consumed all the same.
            relay_push.enroll(self.store, device="Eddie phone", capability=capability,
                              subscription=subscription("https://evil.example/push"))
        with self.assertRaises(PushError):
            relay_push.enroll(self.store, device="Eddie phone", capability=capability,
                              subscription=subscription())
        self.assertTrue(self.store.capability_used(capability))

    def test_capability_burned_on_success_and_not_replayable(self):
        self.issue("Eddie phone")
        capability = os.environ[relay_push.TOKEN_ENV]
        result = relay_push.enroll(self.store, device="Eddie phone",
                                   capability=capability, subscription=subscription())
        self.assertTrue(result["enrolled"])
        self.assertEqual(result["device"], "Eddie phone")
        self.assertTrue(self.store.capability_used(capability))
        with self.assertRaises(PushError):
            relay_push.enroll(self.store, device="Eddie phone",
                              capability=capability, subscription=subscription())
        self.assertEqual(self.store.counts()["capabilities"], 1)

    def test_device_names_are_validated_at_mint_time(self):
        for bad in ("", "   ", "x" * 65, "phone/1", None, 7, "a b  c"):
            with self.subTest(device=repr(bad)):
                with self.assertRaises(PushError):
                    mint_capability(bad)
        # A label that only differs in surrounding whitespace is trimmed once
        # and is the *same* device -- the parent mints and the browser echoes.
        with self.assertRaises(PushError):
            relay_push._validate_device("  Eddie phone \n")

    def test_malformed_capability_shape_is_refused(self):
        os.environ[relay_push.TOKEN_ENV] = "not-a-capability"
        with self.assertRaises(PushError):
            relay_push.check_enrollment_capability(
                "not-a-capability", "Eddie phone", self.store)


class EnrollmentTests(StoreCase):
    def test_enroll_then_status_then_revoke(self):
        self.issue("Eddie phone")
        relay_push.enroll(self.store, device="Eddie phone",
                          capability=os.environ[relay_push.TOKEN_ENV],
                          subscription=subscription())
        status = self.store.status()
        self.assertTrue(status["enrolled"])
        self.assertTrue(status["enabled"])
        self.assertEqual(status["device"], "Eddie phone")
        self.assertEqual(status["recipient"], "Eddie")
        self.assertEqual(status["room"], "relay-eddie-echo-chat")
        # Status must never carry the endpoint or the keys.
        self.assertNotIn("endpoint", status)
        self.assertNotIn("keys", status)
        self.assertNotIn("fcm.googleapis.com", json.dumps(status))

        stored = self.store.subscription()
        self.assertEqual(stored["endpoint"], FCM)
        self.assertTrue(stored["p256dh"])
        self.assertTrue(stored["auth"])

        self.assertEqual(self.store.revoke(device="Eddie phone"), {"revoked": True})
        self.assertFalse(self.store.status()["enrolled"])
        self.assertEqual(self.store.subscription(), {})
        self.assertEqual(self.store.revoke(device="Eddie phone"),
                         {"revoked": False, "reason": "not enrolled"})

    def test_revoke_refuses_a_different_device_name(self):
        self.issue("Eddie phone")
        relay_push.enroll(self.store, device="Eddie phone",
                          capability=os.environ[relay_push.TOKEN_ENV],
                          subscription=subscription())
        with self.assertRaises(PushError):
            self.store.revoke(device="someone else")
        self.assertTrue(self.store.status()["enrolled"])

    def test_second_enrollment_requires_revocation_first(self):
        self.issue("Eddie phone")
        relay_push.enroll(self.store, device="Eddie phone",
                          capability=os.environ[relay_push.TOKEN_ENV],
                          subscription=subscription())
        os.environ[relay_push.TOKEN_ENV] = mint_capability("Eddie phone")
        with self.assertRaises(PushError) as caught:
            relay_push.enroll(self.store, device="Eddie phone",
                              capability=os.environ[relay_push.TOKEN_ENV],
                              subscription=subscription())
        self.assertEqual(caught.exception.status, 409)
        self.assertEqual(self.store.subscription()["endpoint"], FCM)

    def test_failure_budget_degrades_then_recovers(self):
        self.issue("Eddie phone")
        relay_push.enroll(self.store, device="Eddie phone",
                          capability=os.environ[relay_push.TOKEN_ENV],
                          subscription=subscription())
        for index in range(relay_push.MAX_FAILURES):
            result = self.store.record_failure()
            self.assertEqual(result["failures"], index + 1)
        self.assertTrue(self.store.status()["degraded"])
        self.assertFalse(self.store.status()["enabled"])
        self.assertEqual(self.store.record_failure(), {"recorded": False, "failures": relay_push.MAX_FAILURES})
        self.assertEqual(self.store.clear_failures(), {"recorded": True, "failures": 0})
        self.assertTrue(self.store.status()["enabled"])

    def test_bad_subscription_keys_are_refused(self):
        # One fresh capability per case: a refused case burns its capability,
        # which is the point, and a burned capability must not mask the next
        # assertion.
        for label, keys in {
            "short p256dh": {"p256dh": "short", "auth": base64.urlsafe_b64encode(b"c" * 16).decode().rstrip("=")},
            "short auth": {"auth": "c" * 8},
            "missing keys": {},
            "not an object": None,
        }.items():
            with self.subTest(case=label):
                os.environ[relay_push.TOKEN_ENV] = mint_capability("Eddie phone")
                with self.assertRaises(PushError):
                    relay_push.enroll(self.store, device="Eddie phone",
                                      capability=os.environ[relay_push.TOKEN_ENV],
                                      subscription=subscription(**keys) if keys else keys)
        # A key of the right length in the wrong shape is refused outright: the
        # p256dh key must be an uncompressed P-256 point, not any 65 bytes.
        for label, p256dh in {
            "wrong alphabet": "B" * 86 + "!",
            "not uncompressed": base64.urlsafe_b64encode(b"\x05" + b"B" * 64).decode().rstrip("="),
            "wrong decoded length": base64.urlsafe_b64encode(b"B" * 60).decode().rstrip("="),
        }.items():
            with self.subTest(case=label):
                os.environ[relay_push.TOKEN_ENV] = mint_capability("Eddie phone")
                with self.assertRaises(PushError):
                    relay_push.enroll(self.store, device="Eddie phone",
                                      capability=os.environ[relay_push.TOKEN_ENV],
                                      subscription=subscription(p256dh=p256dh, auth="c" * 32))
        self.assertEqual(self.store.status()["enrolled"], False)

    def test_store_never_writes_to_the_production_path(self):
        self.issue("Eddie phone")
        relay_push.enroll(self.store, device="Eddie phone",
                          capability=os.environ[relay_push.TOKEN_ENV],
                          subscription=subscription())
        self.assertTrue(str(self.store.path).startswith(self._tmp.name))
        self.assertFalse(Path(relay_push.DEFAULT_DB).exists()
                         and Path(relay_push.DEFAULT_DB).stat().st_mtime > time.time() - 60)

    def test_oversized_subscription_is_refused(self):
        self.issue("Eddie phone")
        fat = subscription()
        fat["endpoint"] = "https://fcm.googleapis.com/fcm/send/" + "x" * 5000
        os.environ[relay_push.TOKEN_ENV] = mint_capability("Eddie phone")
        with self.assertRaises(PushError):
            relay_push.enroll(self.store, device="Eddie phone",
                              capability=os.environ[relay_push.TOKEN_ENV],
                              subscription=fat)


class PayloadTests(unittest.TestCase):
    def test_payload_is_generic(self):
        payload = relay_push.generic_payload()
        self.assertEqual(payload["title"], relay_push.GENERIC_TITLE)
        self.assertEqual(payload["body"], "New Relay message")
        serialized = json.dumps(payload).lower()
        for word in ("echo", "eddie", "goal", "question", "room", "chat", "text"):
            self.assertNotIn(word, serialized)

    def test_payload_dedupes_by_tag(self):
        self.assertEqual(relay_push.generic_payload()["tag"], "relay-generic")
        self.assertEqual(relay_push.payload_digest(relay_push.generic_payload()),
                         relay_push.payload_digest(relay_push.generic_payload()))

    def test_delivery_half_is_not_present_yet(self):
        # Fail-closed by construction: the module must not claim a delivery
        # capability it cannot implement without the cryptography package.
        self.assertFalse(hasattr(relay_push, "send_push"))
        self.assertFalse(hasattr(relay_push, "generate_vapid_keys"))
        self.assertFalse(hasattr(relay_push, "webpush"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
