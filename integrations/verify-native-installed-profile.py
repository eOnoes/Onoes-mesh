"""Read one existing unsubmitted session's installed closed-profile contract.

No session creation, prompt submission, credential export or enrollment.
"""
import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sqlite3
import sys
from urllib.parse import urlsplit

PUBLIC_FIELDS = ('model', 'provider', 'base_url', 'workspace', 'toolsets', 'safe_mode',
                 'ignore_user_config', 'follow_profile', 'source', 'max_turns',
                 'terminal_backend', 'closed', 'api_key_configured')


def validate(snapshot, intent):
    profile = snapshot.get('profile_contract') or {}
    if (not isinstance(profile, dict) or not set(PUBLIC_FIELDS).issubset(profile)
            or snapshot.get('found') is not False
            or snapshot.get('session_id') != intent['sessionId']
            or snapshot.get('submission_id') != 'codex-never-submitted'
            or snapshot.get('outcome') is not None
            or profile.get('model') != intent['model']
            or profile.get('provider') != 'openai-codex'
            or profile.get('base_url') not in (None, '')
            or profile.get('workspace') != intent['workspace']
            or profile.get('toolsets') != ['file', 'terminal']
            or profile.get('safe_mode') is not True
            or profile.get('ignore_user_config') is not True
            or profile.get('follow_profile') is not False
            or profile.get('source') != 'tool'
            or profile.get('max_turns') != 50
            or profile.get('terminal_backend') != 'local'
            or profile.get('closed') is not True
            or profile.get('api_key_configured') is not False):
        raise RuntimeError('Installed closed profile is missing or mismatched; no prompt submitted')
    # Export only the known public contract, never arbitrary RPC fields.
    return {key: profile[key] for key in PUBLIC_FIELDS}


def readiness(snapshot):
    # A truthy string or a terminal reply cannot prove native process tracking.
    supported = snapshot.get('process_scope_supported') is True
    return {'processScopeSupported': supported,
            'status': 'CAPABILITY_CONFIRMED' if supported else 'HELD',
            'workerRetirementVerified': False,
            'productionEnrollment': False}


async def read_gateway(home, intent):
    from aiohttp import ClientSession
    from hermes_cli.gateway_client import _session_ticket, gateway_ws_target
    from hermes_cli.gateway_runtime import discover_gateway_endpoint
    discovery = await asyncio.to_thread(discover_gateway_endpoint, home, timeout=5)
    if discovery.state != 'ready':
        raise RuntimeError('Existing gateway unavailable')
    origin = urlsplit(discovery.endpoint.api_origin)
    if (origin.scheme != 'http' or origin.hostname not in ('127.0.0.1', '::1', 'localhost')
            or origin.username is not None or origin.password is not None):
        raise RuntimeError('Expected existing loopback gateway before authentication')
    ticket = await asyncio.to_thread(_session_ticket, home, discovery.endpoint,
                                    purpose='interactive')
    url, protocols = gateway_ws_target(discovery.endpoint, ticket)
    parsed = urlsplit(url)
    if (parsed.scheme != 'ws' or parsed.hostname not in ('127.0.0.1', '::1', 'localhost')
            or parsed.username is not None or parsed.password is not None):
        raise RuntimeError('Expected existing loopback gateway')
    async with asyncio.timeout(20):
        async with ClientSession() as client:
            async with client.ws_connect(url, protocols=protocols, max_msg_size=65536) as ws:
                await ws.send_json({'jsonrpc': '2.0', 'id': 1, 'method': 'prompt.lookup',
                                    'params': {'session_id': intent['sessionId'],
                                               'submission_id': 'codex-never-submitted'}})
                while True:
                    reply = await ws.receive_json()
                    if reply.get('id') != 1:
                        continue
                    if 'error' in reply:
                        raise RuntimeError('Installed profile lookup refused; no prompt submitted')
                    snapshot = reply['result']
                    return snapshot, validate(snapshot, intent)


async def main(require_process_scope=False):
    root = Path(__file__).resolve().parents[1]
    intent = json.loads((root / 'data/native-live-explicit-policy.json').read_text())
    workspace = Path(intent['workspace']).resolve()
    if (intent.get('schema') != 'mesh-native-live-policy/v1'
            or not re.fullmatch(r'local-[a-f0-9]{64}', intent.get('sessionId', ''))
            or not re.fullmatch(r'mesh-live-policy-[a-f0-9]{32}', intent.get('requestId', ''))
            or workspace.parent != (root / 'data').resolve()
            or not workspace.name.startswith('native-live-policy-')
            or intent.get('model') != 'gpt-6-luna'
            or intent.get('provider') != 'openai-codex'
            or intent.get('tools') != ['file', 'terminal']):
        raise RuntimeError('Existing fixed probe intent required; no replacement session created')
    home = Path('C:/Users/eMitchell109/AppData/Local/hermes')
    sys.path.insert(0, str(home / 'hermes-agent'))
    from hermes_state_local import POLICY_PREFIX
    with sqlite3.connect((home / 'state.db').as_uri() + '?mode=ro', uri=True) as db:
        db.execute('PRAGMA query_only=ON')
        row = db.execute('SELECT value FROM state_meta WHERE key=?',
                         (POLICY_PREFIX + intent['sessionId'],)).fetchone()
        receipt = json.loads(row[0]) if row else {}
        if (receipt.get('request_id') != intent['requestId']
                or receipt.get('session_id') != intent['sessionId']):
            raise RuntimeError('Native receipt does not bind this exact saved probe intent')
    snapshot, profile = await read_gateway(home, intent)
    with sqlite3.connect((home / 'state.db').as_uri() + '?mode=ro', uri=True) as db:
        db.execute('PRAGMA query_only=ON')
        admissions = db.execute('SELECT count(*) FROM session_admissions WHERE target_session_id=?',
                               (intent['sessionId'],)).fetchone()[0]
    if admissions != 0:
        raise RuntimeError('Probe unexpectedly has admissions; do not submit or replay')
    state = readiness(snapshot)
    result = {'schema': 'mesh-installed-native-profile/v1',
              'observedAt': datetime.now(timezone.utc).isoformat(),
              'qualification': 'HELD' if require_process_scope and state['status'] == 'HELD' else 'PASS',
              'sessionId': intent['sessionId'], 'profile': profile,
              'admissionCount': admissions, 'promptsSubmitted': 0,
              'workerReadiness': state,
              'productionEnrollment': False, 'credentialsExported': False}
    filename = 'native-worker-readiness.json' if require_process_scope else 'native-installed-profile.json'
    (root / 'data' / filename).write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result))
    return 2 if result['qualification'] == 'HELD' else 0


if __name__ == '__main__':
    if sys.argv[1:] not in ([], ['--require-process-scope']):
        raise SystemExit('Only --require-process-scope is supported; no alternate session or endpoint accepted')
    raise SystemExit(asyncio.run(main('--require-process-scope' in sys.argv)))
