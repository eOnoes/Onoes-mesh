"""Pure, owner-reviewed migration of one existing Relay peer; never reads a key."""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import PureWindowsPath
import re
from urllib.parse import urlsplit


class RelayConfigHold(ValueError):
    pass


def require(ok, message):
    if not ok:
        raise RelayConfigHold(message)


def unique(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, 'Duplicate Relay configuration field')
        result[key] = value
    return result


def invalid_constant(value):
    raise RelayConfigHold('Non-JSON constant refused')


def parse(raw):
    require(isinstance(raw, bytes) and 0 < len(raw) <= 262144, 'Relay configuration bound')
    value = json.loads(raw, object_pairs_hook=unique, parse_constant=invalid_constant)
    require(isinstance(value, dict), 'Relay configuration object required')
    return value


def prepare_relay_config(raw, *, expected_sha256, hostname, credential_directory, credential_file):
    require(sha256(raw).hexdigest() == expected_sha256, 'Relay configuration changed since review')
    require(isinstance(hostname, str) and re.fullmatch(r'[a-z0-9-]+\.[a-z0-9-]+\.ts\.net', hostname),
            'Reviewed tailnet hostname required')
    directory, key = PureWindowsPath(credential_directory), PureWindowsPath(credential_file)
    require(directory.is_absolute() and key.is_absolute() and len(directory.drive) == 2
            and len(key.drive) == 2 and '..' not in directory.parts and '..' not in key.parts
            and directory.name == '.private' and key.parent == directory and key.suffix == '.key',
            'New key reference must be directly inside the reviewed local private directory')
    before = parse(raw)
    agents = before.get('agents')
    require(isinstance(agents, dict) and isinstance(agents.get('cyony'), dict), 'Existing Cyony peer required')
    old = agents['cyony']
    require(old.get('backend') == 'a2a' and old.get('device') == 'cloud'
            and old.get('demo_fallback') is False, 'Unexpected existing Cyony route')
    require('api_key' not in old and 'api_key_env' not in old, 'Unexpected alternate credential source')
    require(isinstance(old.get('api_key_file'), str) and old['api_key_file'].strip(),
            'Existing credential reference required for reviewed migration')
    # Reject reusing the old A2A credential even when relative spelling differs.
    old_key = PureWindowsPath(old['api_key_file'])
    if not old_key.is_absolute():
        old_key = directory.parent / old_key
    require(old_key != key, 'Old A2A credential must not be reused for Hermes')
    after = deepcopy(before)
    after['agents']['cyony'].update(backend='hermes', url='https://' + hostname + '/relay-native',
                                    api_key_file=str(key))
    proposed = (json.dumps(after, indent=2, ensure_ascii=False, allow_nan=False) + '\n').encode('utf-8')
    # Only the declared route fields may change; preserve all other peer/budget settings.
    restored = deepcopy(after)
    restored['agents']['cyony'] = old
    require(restored == before, 'Unrelated Relay configuration changed')
    require(parse(proposed) == after, 'Proposed Relay configuration does not round-trip')
    return proposed


def restore_relay_config(current, *, original, proposed):
    require(current == proposed, 'Concurrent Relay configuration edit; preserve it and hold')
    return original
