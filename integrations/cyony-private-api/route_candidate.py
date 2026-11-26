"""Pure preparation for one existing Hermes API route; no live apply entry point."""
from copy import deepcopy
from hashlib import sha256
import json
import re

import yaml

MOUNT = '/relay-native/'
SERVICE = 'hermes'


class RouteHold(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise RouteHold(message)


class UniqueLoader(yaml.SafeLoader):
    pass


def mapping(loader, node, deep=False):
    result = {}
    for key_node, value_node in node.value:
        require(key_node.tag != 'tag:yaml.org,2002:merge', 'YAML merge is outside this reviewed slice')
        key = loader.construct_object(key_node, deep=deep)
        require(isinstance(key, str) and key not in result, 'Duplicate or non-string YAML key')
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, mapping)


def document(raw):
    require(isinstance(raw, bytes) and 0 < len(raw) <= 262144, 'Compose input bound')
    text = raw.decode('utf-8')
    require('\r' not in text and '\t' not in text and text.endswith('\n'), 'Expected reviewed LF document')
    # Aliases could let an ostensibly local addition affect another service.
    require(not any(isinstance(event, yaml.AliasEvent) for event in yaml.parse(text)), 'YAML alias not allowed')
    data = yaml.load(text, Loader=UniqueLoader)
    require(isinstance(data, dict), 'Compose mapping required')
    return text, data


def member(node, key):
    require(isinstance(node, yaml.MappingNode), 'Expected mapping node')
    pairs = [(k, v) for k, v in node.value if k.value == key]
    require(len(pairs) == 1, 'Expected one reviewed field')
    return pairs[0]


def flow_addition(text, node, field):
    end = node.end_mark.index - 1
    require(text[node.start_mark.index] == '{' and text[end] == '}', 'Expected explicit flow map')
    prefix = ' ' if text[:end].rstrip().endswith(',') else ', '
    return end, prefix + field


def prepare_compose(raw, *, expected_sha256, expected_image, host_port=8642,
                    expected_api_enabled='true'):
    """Insert only host binding and loopback publication, preserving all original bytes."""
    require(sha256(raw).hexdigest() == expected_sha256, 'Compose changed since review')
    require(type(host_port) is int and 1024 <= host_port <= 65535, 'Invalid host port')
    require(isinstance(expected_image, str) and re.search(r'@sha256:[0-9a-f]{64}\Z', expected_image),
            'Immutable image reference required')
    text, before = document(raw)
    service = before.get('services', {}).get(SERVICE)
    require(isinstance(service, dict), 'Expected Hermes service')
    require(service.get('image') == expected_image, 'Image differs from reviewed runtime')
    require('ports' not in service and 'network_mode' not in service, 'Existing publication/network override')
    require(service.get('networks') == ['cyony_private'], 'Expected existing private network')
    require(service.get('restart') == 'unless-stopped', 'Unexpected restart policy')
    env = service.get('environment')
    require(isinstance(env, dict) and env.get('HERMES_HOME') == '/opt/data', 'Expected existing home')
    require('API_SERVER_HOST' not in env and 'API_SERVER_KEY' not in env, 'API binding/key already overridden')
    # A current gateway can serve its native API while retaining the legacy
    # false flag. Bind the exact reviewed value; do not enable/change it here.
    require(type(expected_api_enabled) is str and expected_api_enabled in ('true', 'false', '1', '0'),
            'Reviewed legacy API enable value required')
    require(env.get('API_SERVER_ENABLED') == expected_api_enabled, 'API enable value changed since review')
    nodes = yaml.compose(text)
    service_node = member(member(nodes, 'services')[1], SERVICE)[1]
    env_key, env_node = member(service_node, 'environment')
    require(isinstance(env_node, yaml.MappingNode) and env_node.value, 'Expected nonempty environment')
    indent = env_node.value[0][0].start_mark.column
    service_indent = env_key.start_mark.column
    lines = text.splitlines(keepends=True)
    if env_node.flow_style:
        env_addition = flow_addition(text, env_node, 'API_SERVER_HOST: 0.0.0.0')
    else:
        env_addition = (sum(map(len, lines[:env_node.end_mark.line])),
                        ' ' * indent + 'API_SERVER_HOST: 0.0.0.0\n')
    if service_node.flow_style:
        ports_addition = flow_addition(text, service_node, "ports: ['127.0.0.1:%d:8642']" % host_port)
    else:
        ports_addition = (sum(map(len, lines[:env_key.start_mark.line])), ' ' * service_indent + 'ports:\n' +
                          ' ' * (service_indent + 2) + "- '127.0.0.1:%d:8642'\n" % host_port)
    additions = [env_addition, ports_addition]
    modified = text
    for index, content in sorted(additions, reverse=True):
        modified = modified[:index] + content + modified[index:]
    proposed = modified.encode('utf-8')
    _, after = document(proposed)
    expected = deepcopy(before)
    expected['services'][SERVICE]['environment']['API_SERVER_HOST'] = '0.0.0.0'
    expected['services'][SERVICE]['ports'] = ['127.0.0.1:%d:8642' % host_port]
    require(after == expected, 'Unexpected Compose semantic change')
    # The inverse is byte-exact, not YAML reserialization.
    without = proposed.decode('utf-8')
    for _, content in additions:
        require(without.count(content) == 1, 'Ambiguous inverse')
        without = without.replace(content, '', 1)
    require(without.encode('utf-8') == raw, 'Original bytes not preserved')
    return proposed


def restore_compose(current, *, original, proposed):
    require(current == proposed, 'Concurrent Compose edit; preserve it and hold')
    return original


def prepare_serve(before, *, hostname, host_port=8642):
    """Propose one subpath on the existing private HTTPS listener; never reset Serve."""
    require(isinstance(before, dict) and type(host_port) is int and 1024 <= host_port <= 65535,
            'Invalid Serve input')
    require(isinstance(hostname, str) and re.fullmatch(r'[a-z0-9-]+\.[a-z0-9-]+\.ts\.net', hostname),
            'Expected reviewed tailnet hostname')
    require(not any(before.get('AllowFunnel', {}).values()), 'Funnel is outside this private route')
    key = hostname + ':443'
    require(before.get('TCP', {}).get('443') == {'HTTPS': True}, 'Expected existing HTTPS443 only')
    handlers = before.get('Web', {}).get(key, {}).get('Handlers')
    require(isinstance(handlers, dict) and handlers.get('/') == {'Proxy': 'http://127.0.0.1:3000'},
            'Keep route differs from reviewed source')
    require(not any(path.rstrip('/') == MOUNT.rstrip('/') or path.startswith(MOUNT)
                    for path in handlers), 'Relay mount already owned')
    after = deepcopy(before)
    after['Web'][key]['Handlers'][MOUNT] = {'Proxy': 'http://127.0.0.1:%d' % host_port}
    return after


def restore_serve(current, *, original, proposed, hostname):
    """Remove only this exact added mount; preserve independent newer routes."""
    key = hostname + ':443'
    require(MOUNT not in original['Web'][key]['Handlers'], 'Original mount ownership conflict')
    expected = proposed['Web'][key]['Handlers'][MOUNT]
    handlers = current.get('Web', {}).get(key, {}).get('Handlers', {})
    require(handlers.get(MOUNT) == expected, 'Mount changed; do not remove another owner route')
    after = deepcopy(current)
    del after['Web'][key]['Handlers'][MOUNT]
    return after


def serve_commands(host_port=8642):
    require(type(host_port) is int and 1024 <= host_port <= 65535, 'Invalid host port')
    return {
        'add': ['tailscale', 'serve', '--bg', '--https=443', '--set-path=' + MOUNT,
                'http://127.0.0.1:%d' % host_port],
        'remove': ['tailscale', 'serve', '--https=443', '--set-path=' + MOUNT, 'off'],
    }
