"""One explicitly granted notification attempt for an existing Eddie/Echo message.

No HTTP publisher, timer, startup hook or automatic retries. A child-only capability
is bound to one durable message ID and expires; absent capability fails closed.
Provider acceptance is not phone receipt. Raw subscriptions and keys never printed.
"""
import argparse
import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import time
from pathlib import Path

import relay_push
import relay_push_sender

TOKEN_ENV = 'RELAY_PUSH_SEND_TOKEN'


def mint_send_capability(message_id, seconds=300):
    validate_id(message_id)
    encoded = base64.urlsafe_b64encode(message_id.encode()).decode().rstrip('=')
    return f'{int(time.time() + seconds)}.{encoded}.{secrets.token_urlsafe(32)}'


def validate_id(message_id):
    if not isinstance(message_id, str) or not re.fullmatch(r'msg-p-[A-Za-z0-9_-]{1,100}', message_id):
        raise relay_push.PushError('An exact durable Relay message ID is required.', 400)


def check_capability(token, message_id):
    configured = os.environ.get(TOKEN_ENV, '')
    if not configured or not isinstance(token, str) or not hmac.compare_digest(token, configured):
        raise relay_push.PushError('Notification publishing is not authorized.', 403)
    try:
        expiry, encoded, nonce = configured.split('.')
        bound = base64.urlsafe_b64decode(encoded + '=' * (-len(encoded) % 4)).decode()
        if int(expiry) <= time.time() or bound != message_id or len(nonce) < 40:
            raise ValueError()
    except (ValueError, UnicodeError):
        raise relay_push.PushError('Notification grant expired or bound to a different message.', 403)


def notify(message_id, *, token, proactive_db, push_store, session, private_key=None):
    validate_id(message_id)
    check_capability(token, message_id)
    # Read-only: never create/alter the owner's message database here.
    uri = Path(proactive_db).resolve().as_uri() + '?mode=ro'
    db = sqlite3.connect(uri, uri=True)
    try:
        row = db.execute('SELECT session_id,author,recipient FROM relay_proactive WHERE message_id=?', (message_id,)).fetchone()
    finally:
        db.close()
    if row != (relay_push.ROOM, relay_push.AUTHOR, relay_push.RECIPIENT):
        raise relay_push.PushError('Notification requires an existing Echo-to-Eddie Relay message.', 403)
    subscription = push_store.subscription()
    if not subscription or not push_store.status().get('enabled'):
        raise relay_push.PushError('The phone is not enrolled or delivery is disabled.', 409)
    relay_push.validate_endpoint(subscription['endpoint'])
    # Unique claim is committed before network I/O. An interrupted attempt stays
    # unknown; replay does not send twice or infer success.
    identity = hashlib.sha256((subscription['endpoint'] + '\0' + subscription['auth']).encode()).hexdigest()
    db = push_store.connect()
    try:
        db.execute('CREATE TABLE IF NOT EXISTS push_delivery (message_id TEXT, device_hash TEXT, state TEXT NOT NULL, status INTEGER, token_hash TEXT NOT NULL UNIQUE, PRIMARY KEY(message_id,device_hash))')
        cursor = db.execute('INSERT OR IGNORE INTO push_delivery VALUES(?,?,?,NULL,?)', (message_id, identity, 'attempting', hashlib.sha256(token.encode()).hexdigest()))
        claimed = cursor.rowcount == 1
        db.commit()
        if not claimed:
            state = db.execute('SELECT state,status FROM push_delivery WHERE message_id=? AND device_hash=?', (message_id, identity)).fetchone()
            return {'attempted': False, 'state': state[0] if state else 'grant_already_used', 'status': state[1] if state else None, 'duplicate': True}
    finally:
        db.close()
    result = relay_push_sender.send_push(endpoint=subscription['endpoint'], subscription_key=subscription['p256dh'], auth_key=subscription['auth'], vapid_private_key=private_key or os.environ.get(relay_push.VAPID_PRIVATE_ENV, ''), session=session, timeout=10)
    state = 'provider_accepted' if result.get('ok') else result.get('code', 'failed')
    db = push_store.connect()
    try:
        db.execute('UPDATE push_delivery SET state=?,status=? WHERE message_id=? AND device_hash=?', (state, result.get('status'), message_id, identity))
        db.commit()
    finally:
        db.close()
    if result.get('code') == 'subscription_expired':
        push_store.revoke(device=subscription['device'])
    elif result.get('ok'):
        push_store.clear_failures()
    else:
        push_store.record_failure()
    return {'attempted': True, 'state': state, 'status': result.get('status'), 'phone_receipt': 'unverified'}


def main():
    parser = argparse.ArgumentParser(description='One explicitly authorized generic Relay notification')
    parser.add_argument('--message-id', required=True)
    args = parser.parse_args()
    try:
        relay_push.require_delivery_ready()
        import requests
        import relay_proactive
        with requests.Session() as session:
            session.trust_env = False
            result = notify(args.message_id, token=os.environ.get(TOKEN_ENV, ''), proactive_db=os.environ.get('RELAY_PROACTIVE_DB') or relay_proactive.DEFAULT_DB, push_store=relay_push.PushStore(), session=session)
        print(json.dumps(result))
        return 0 if result.get('state') == 'provider_accepted' else 1
    except Exception:
        # No raw provider exception/URL/subscription/key output.
        print(json.dumps({'attempted': False, 'state': 'refused_or_unavailable'}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
