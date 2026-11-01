"""Real encryption with isolated stores and provider transport: never a real push."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import relay_proactive
import relay_push
import relay_push_notify
from test_relay_push_sender import MockSession, _ephemeral_receiver_subscription, _ephemeral_vapid_key


class NotifyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=os.environ.get('TMPDIR') or 'C:/Users/eMitchell109/AppData/Local/hermes/cache/scratch')
        self.addCleanup(self.temp.cleanup)
        self.push = relay_push.PushStore(Path(self.temp.name) / 'push.db')
        self.proactive = relay_proactive.ProactiveStore(Path(self.temp.name) / 'proactive.db')
        self.message = 'msg-p-isolated-push-001'
        self.proactive.publish('This private conversation must never appear in the push payload', message_id=self.message)
        endpoint, pub, auth = _ephemeral_receiver_subscription()
        self.push.save_subscription('Eddie phone', {'endpoint':endpoint, 'keys':{'p256dh':pub, 'auth':auth}}, capability='isolated', capability_expires_at=9999999999)
        self.key = _ephemeral_vapid_key()
        self.token = relay_push_notify.mint_send_capability(self.message)
        self.env = patch.dict(os.environ, {relay_push_notify.TOKEN_ENV:self.token})
        self.env.start()
        self.addCleanup(self.env.stop)

    def send(self, session, message=None, token=None):
        return relay_push_notify.notify(message or self.message, token=self.token if token is None else token, proactive_db=self.proactive.path, push_store=self.push, session=session, private_key=self.key)

    def test_real_encrypted_once_and_durable_duplicate(self):
        provider = MockSession()
        result = self.send(provider)
        self.assertEqual(result['state'], 'provider_accepted')
        self.assertEqual(result['phone_receipt'], 'unverified')
        self.assertEqual(len(provider.calls), 1)
        self.assertNotIn(b'private conversation', provider.calls[0]['kwargs']['data'])
        # New store object models a separate process, not in-memory dedup.
        self.push = relay_push.PushStore(self.push.path)
        again = self.send(provider)
        self.assertFalse(again['attempted'])
        self.assertTrue(again['duplicate'])
        self.assertEqual(len(provider.calls), 1)

    def test_refuses_missing_wrong_expired_and_other_message_grant(self):
        provider = MockSession()
        for token in ('', 'wrong'):
            with self.assertRaises(relay_push.PushError):
                self.send(provider, token=token)
        with self.assertRaises(relay_push.PushError):
            self.send(provider, message='msg-p-other')
        expired = relay_push_notify.mint_send_capability(self.message, seconds=-1)
        with patch.dict(os.environ, {relay_push_notify.TOKEN_ENV:expired}):
            with self.assertRaises(relay_push.PushError):
                self.send(provider, token=expired)
        self.assertEqual(provider.calls, [])

    def test_no_notification_without_durable_message(self):
        missing = 'msg-p-missing'
        token = relay_push_notify.mint_send_capability(missing)
        provider = MockSession()
        with patch.dict(os.environ, {relay_push_notify.TOKEN_ENV:token}):
            with self.assertRaises(relay_push.PushError):
                self.send(provider, message=missing, token=token)
        self.assertEqual(provider.calls, [])

    def test_expired_subscription_revoked_and_no_repeat(self):
        provider = MockSession(status=410)
        self.assertEqual(self.send(provider)['state'], 'subscription_expired')
        self.assertFalse(self.push.status()['enabled'])
        with self.assertRaises(relay_push.PushError):
            self.send(provider)
        self.assertEqual(len(provider.calls), 1)

    def test_rejected_attempt_not_retried(self):
        provider = MockSession(status=503)
        result = self.send(provider)
        self.assertNotEqual(result['state'], 'provider_accepted')
        self.assertFalse(self.send(provider)['attempted'])
        self.assertEqual(len(provider.calls), 1)
        self.assertEqual(self.push.status()['failures'], 1)


if __name__ == '__main__':
    unittest.main()
