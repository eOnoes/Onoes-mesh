"""Candidate Relay native receipts. No dispatch, credentials or gateway imports."""
import asyncio
import hashlib
import json
import re

PREFIX = 'hermes-run-v1:'
RUN_ID = re.compile(r'run_[A-Za-z0-9_-]{1,128}\Z')
STATUSES = frozenset({'queued', 'running', 'waiting_for_approval', 'completed',
                      'failed', 'cancelled', 'interrupted', 'expired', 'unknown'})
TERMINAL = frozenset({'completed', 'failed', 'cancelled', 'interrupted', 'expired'})


def gateway_identity(client):
    """Pin the configured endpoint without exposing its address or credentials."""
    address = str(client.base_url).rstrip('/')
    if not address:
        raise ValueError('Missing native endpoint identity')
    return hashlib.sha256(address.encode('utf-8')).hexdigest()


def binding(store, agent_id, send_id, client, *, conversation_id=None, for_dispatch=False,
            fresh_claim=False):
    row = store.outbox_get(send_id)
    if not row or row['agent_id'] != agent_id:
        raise LookupError('Native receipt not found')
    if conversation_id is not None and row['session_id'] != conversation_id:
        raise ValueError('Original conversation differs from saved intent')
    reference = row.get('transport_ref')
    if not reference:
        if for_dispatch and (not fresh_claim or row['state'] != 'sending' or row['attempts'] != 1):
            raise ValueError('Prior admission is uncertain; reconcile without dispatch')
        return None
    if not reference.startswith(PREFIX):
        raise ValueError('Unrecognized native receipt binding')
    saved = json.loads(reference[len(PREFIX):])
    if (not isinstance(saved, dict) or set(saved) != {'runId', 'gateway'}
            or not isinstance(saved['runId'], str) or not RUN_ID.fullmatch(saved['runId'])
            or saved['gateway'] != gateway_identity(client)):
        raise ValueError('Native receipt identity changed')
    return {'sendId': send_id, 'agentId': agent_id,
            'conversationId': row['session_id'], 'runId': saved['runId']}


def bind(store, agent_id, conversation_id, send_id, run_id, client):
    """Commit the exact admission before reading events; never replace another run."""
    if not isinstance(run_id, str) or not RUN_ID.fullmatch(run_id):
        raise ValueError('Malformed native run identity')
    reference = PREFIX + json.dumps({'runId': run_id, 'gateway': gateway_identity(client)},
                                    sort_keys=True, separators=(',', ':'))
    with store.lock, store.db:
        row = store.db.execute('SELECT * FROM outbox WHERE idem_key=?', (send_id,)).fetchone()
        if not row or row['agent_id'] != agent_id or row['session_id'] != conversation_id:
            raise ValueError('Native admission does not match saved intent')
        if row['transport_ref'] not in (None, '', reference):
            raise ValueError('A different native admission is already saved')
        changed = store.db.execute(
            "UPDATE outbox SET transport_ref=? WHERE id=? AND "
            "(transport_ref IS NULL OR transport_ref='' OR transport_ref=?)",
            (reference, row['id'], reference))
        if changed.rowcount != 1:
            raise ValueError('Native admission changed concurrently')


async def read(store, agent_id, send_id, client):
    """Exact saved-run GET only. Terminal is explicitly not writer quiescence."""
    row = store.outbox_get(send_id)
    if not row or row['agent_id'] != agent_id:
        raise LookupError('Native receipt not found')
    result = {'sendId': send_id, 'agentId': agent_id, 'conversationId': row['session_id'],
              'runId': None, 'nativeSessionId': None, 'status': 'unknown',
              'observation': 'unknown', 'terminal': False, 'writerQuiescence': False}
    try:
        saved = binding(store, agent_id, send_id, client)
    except (ValueError, TypeError, KeyError):
        return {**result, 'reason': 'binding_conflict'}
    if saved is None:
        return {**result, 'reason': 'binding_missing'}
    result['runId'] = saved['runId']
    try:
        status = await asyncio.wait_for(client.run_status(saved['runId']), timeout=5)
    except Exception:
        return {**result, 'reason': 'native_read_unavailable'}
    if (not isinstance(status, dict) or status.get('run_id') != saved['runId']
            or status.get('status') not in STATUSES):
        return {**result, 'reason': 'native_identity_or_status_unverified'}
    session = status.get('session_id')
    if not isinstance(session, str) or not session or len(session) > 256:
        return {**result, 'reason': 'native_session_unverified'}
    return {**result, 'nativeSessionId': session, 'status': status['status'],
            'observation': 'observed', 'terminal': status['status'] in TERMINAL}
