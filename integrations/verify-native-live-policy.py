"""Create/reconcile one unsubmitted local session and inspect only its frozen policy.

Uses the existing owner's native client, not a Rook identity. Never submits a prompt,
installs code, changes settings, or reads another session's policy/conversation.
"""
import asyncio
import json
import re
import sqlite3
import sys
import uuid
from pathlib import Path
from urllib.parse import urlsplit


async def main():
    root = Path(__file__).resolve().parents[1]
    home = Path('C:/Users/eMitchell109/AppData/Local/hermes')
    source = home / 'hermes-agent'
    sys.path.insert(0, str(source))
    from aiohttp import ClientSession
    from hermes_cli.gateway_client import _session_ticket, gateway_ws_target
    from hermes_cli.gateway_runtime import discover_gateway_endpoint
    from hermes_state_local import POLICY_PREFIX
    from gateway.session_policy import restore_policy

    record = root / 'data/native-live-explicit-policy.json'
    if record.exists():
        result = json.loads(record.read_text(encoding='utf-8'))
    else:
        workspace = root / 'data' / ('native-live-policy-' + uuid.uuid4().hex)
        workspace.mkdir()
        result = {
            'schema': 'mesh-native-live-policy/v1',
            'requestId': 'mesh-live-policy-' + uuid.uuid4().hex,
            'workspace': str(workspace), 'model': 'gpt-6-luna',
            'provider': 'openai-codex', 'tools': ['file', 'terminal'],
            'promptsSubmitted': 0, 'productionBuilderEnabled': False,
            'servicesRestarted': False, 'credentialsCopied': False,
            'state': 'prepared',
        }
        record.write_text(json.dumps(result, indent=2), encoding='utf-8')

    # Reopening uses the exact saved intent; it cannot silently create a fresh attempt.
    workspace = Path(result['workspace']).resolve()
    if (result.get('schema') != 'mesh-native-live-policy/v1'
            or not re.fullmatch(r'mesh-live-policy-[a-f0-9]{32}', result['requestId'])
            or workspace.parent != (root / 'data').resolve()
            or not workspace.name.startswith('native-live-policy-')
            or result['model'] != 'gpt-6-luna'
            or result['provider'] != 'openai-codex'
            or result['tools'] != ['file', 'terminal']):
        raise RuntimeError('Saved probe intent does not match the fixed policy')

    def save():
        record.write_text(json.dumps(result, indent=2), encoding='utf-8')

    if not result.get('sessionId'):
        discovery = await asyncio.to_thread(discover_gateway_endpoint, home, timeout=5)
        if discovery.state != 'ready':
            raise RuntimeError('Native gateway is not ready')
        ticket = await asyncio.to_thread(_session_ticket, home, discovery.endpoint,
                                        purpose='interactive')
        url, protocols = gateway_ws_target(discovery.endpoint, ticket)
        parsed = urlsplit(url)
        if parsed.scheme != 'ws' or parsed.hostname != '127.0.0.1':
            raise RuntimeError('Expected the existing loopback gateway')
        result['state'] = 'create_pending'
        save()
        async with ClientSession() as client:
            async with client.ws_connect(url, protocols=protocols) as ws:
                await ws.send_json({'jsonrpc': '2.0', 'id': 1,
                                    'method': 'session.create', 'params': {
                    'request_id': result['requestId'], 'source': 'tool',
                    'model': result['model'], 'provider': result['provider'],
                    'toolsets': result['tools'], 'safe_mode': True,
                    'ignore_rules': True, 'cwd': str(workspace), 'max_turns': 50,
                }})
                while True:
                    reply = await ws.receive_json(timeout=30)
                    if reply.get('id') != 1:
                        continue
                    if 'error' in reply:
                        result['state'] = 'create_refused'
                        save()
                        raise RuntimeError('Native session creation refused')
                    result['sessionId'] = reply['result']['session_id']
                    result['state'] = 'created_unsubmitted'
                    save()
                    break

    sid = result['sessionId']
    if not isinstance(sid, str) or not re.fullmatch(r'local-[a-f0-9]{64}', sid):
        raise RuntimeError('Unexpected local session identity')
    with sqlite3.connect((home / 'state.db').as_uri() + '?mode=ro', uri=True) as db:
        db.execute('PRAGMA query_only=ON')
        row = db.execute('SELECT value FROM state_meta WHERE key=?',
                         (POLICY_PREFIX + sid,)).fetchone()
        if row is None:
            raise RuntimeError('Exact session policy is unavailable')
        receipt = json.loads(row[0])
        if receipt.get('request_id') != result['requestId'] or receipt.get('session_id') != sid:
            raise RuntimeError('Native receipt does not belong to the saved probe intent')
        policy = restore_policy(receipt['policy'])
        # Export only public allowlisted policy metadata, never raw receipt/config.
        def public(name):
            value = getattr(policy, name)
            return value() if callable(value) else value
        result['policy'] = {key: public(key) for key in (
            'model', 'provider', 'base_url', 'cwd', 'toolsets', 'safe_mode',
            'ignore_user_config', 'source', 'max_turns')}
        result['policy']['follow_profile'] = public('follows_profile')
        columns = {row[1] for row in db.execute('PRAGMA table_info(session_admissions)')}
        if 'target_session_id' not in columns:
            raise RuntimeError('Cannot independently verify absence of admissions')
        result['admissionCount'] = db.execute(
            'SELECT count(*) FROM session_admissions WHERE target_session_id=?', (sid,)).fetchone()[0]
    p = result['policy']
    result['policyMatches'] = (
        p['model'] == result['model'] and p['provider'] == result['provider']
        and p['base_url'] in (None, '') and Path(p['cwd']).resolve() == workspace
        and sorted(p['toolsets']) == result['tools'] and p['safe_mode'] is True
        and p['ignore_user_config'] is True and p['follow_profile'] is False
        and p['source'] == 'tool' and p['max_turns'] == 50
        and result['admissionCount'] == 0)
    result['credentialAbsenceQualified'] = False
    result['credentialBoundary'] = 'Private provider credential presence requires the native closed-profile bridge; this public-policy probe cannot qualify it.'
    result['state'] = 'policy_verified_no_prompt' if result['policyMatches'] else 'policy_mismatch_no_prompt'
    save()
    print(json.dumps({'state': result['state'], 'record': str(record),
                      'sessionId': sid, 'policy': result['policy'],
                      'promptsSubmitted': 0}))
    if not result['policyMatches']:
        raise RuntimeError('Exact requested policy was not established; no prompt submitted')


if __name__ == '__main__':
    asyncio.run(main())
