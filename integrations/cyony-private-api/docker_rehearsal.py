"""One explicitly named disposable project; never use live configs or model services."""
from datetime import datetime, timezone
import argparse
from hashlib import sha256
import json
from pathlib import Path
import socket
import subprocess
import time
from urllib.error import HTTPError, URLError
from urllib.request import build_opener, ProxyHandler, Request

import yaml

from route_candidate import prepare_compose, restore_compose

PROJECT = 'mesh-cyony-private-route-check'
OUT = None
HERE = Path(__file__).resolve().parent


def command(*args, timeout=40):
    result = subprocess.run(list(args), capture_output=True, text=True, timeout=timeout,
                            creationflags=subprocess.CREATE_NO_WINDOW)
    if result.returncode:
        raise RuntimeError('Owned fixture command failed: ' + ' '.join(args[:3]) + ': ' + result.stderr[-1500:])
    return result.stdout


def compose(path, *args):
    return command('docker', 'compose', '-p', PROJECT, '-f', str(path), *args)


def current_container():
    ids = command('docker', 'ps', '-aq', '--filter', 'label=com.docker.compose.project=' + PROJECT).split()
    assert len(ids) == 1
    value, = json.loads(command('docker', 'inspect', ids[0]))
    assert value['Config']['Labels']['onoes.mesh.test'] == 'cyony-private-route'
    return value


def inside_ready():
    container = current_container()
    # Wait on this exact owned process, never restart it on a readiness timeout.
    deadline = time.monotonic() + 10
    while 'FIXTURE_READY' not in command('docker', 'logs', container['Id']):
        assert time.monotonic() < deadline, 'Owned fixture readiness timeout; no retry'
        assert current_container()['Id'] == container['Id']
        time.sleep(.2)
    return container


def read_inside():
    code = "const h=require('node:http'); h.get({host:'127.0.0.1',port:8642,path:'/v1/capabilities',headers:{Authorization:'Bearer fixture-key-only'}},r=>{let b='';r.on('data',c=>b+=c);r.on('end',()=>{console.log(b);process.exit(r.statusCode===200?0:1)})}).on('error',()=>process.exit(1));"
    return json.loads(command('docker', 'exec', current_container()['Id'], 'node', '-e', code))


def main(output_directory, project, flow_style):
    global OUT, PROJECT
    import re
    assert re.fullmatch(r'mesh-cyony-private-route-check(?:-[a-z0-9-]+)?', project) and len(project) <= 63
    OUT, PROJECT = Path(output_directory).resolve(), project
    assert not OUT.exists(), 'Retain prior fixture evidence; do not blindly repeat'
    assert not command('docker', 'ps', '-aq', '--filter', 'label=com.docker.compose.project=' + PROJECT).strip()
    image, = json.loads(command('docker', 'image', 'inspect', 'node:22-alpine'))
    image_ref, = [name for name in image['RepoDigests'] if name.startswith('node@sha256:')]
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0)); host_port = probe.getsockname()[1]
    OUT.mkdir(parents=True)
    data = OUT / 'data'; data.mkdir()
    fixture = OUT / 'fixture.js'; fixture.write_bytes((HERE / 'fixture.js').read_bytes())
    original = {'services': {'hermes': {'image': image_ref,
        'entrypoint': ['node', '/probe/fixture.js'], 'restart': 'unless-stopped',
        'environment': {'HERMES_HOME': '/opt/data', 'API_SERVER_ENABLED': 'false' if flow_style else 'true'},
        'volumes': [str(fixture).replace('\\', '/') + ':/probe/fixture.js:ro',
                    str(data).replace('\\', '/') + ':/opt/data'],
        'networks': ['cyony_private'], 'labels': {'onoes.mesh.test': 'cyony-private-route'}}},
        'networks': {'cyony_private': {'driver': 'bridge'}}}
    raw = yaml.safe_dump(original, sort_keys=False, default_flow_style=flow_style).encode()
    proposed = prepare_compose(raw, expected_sha256=sha256(raw).hexdigest(),
                               expected_image=image_ref, host_port=host_port,
                               expected_api_enabled='false' if flow_style else 'true')
    baseline = OUT / 'baseline.yaml'; baseline.write_bytes(raw)
    candidate = OUT / 'candidate.yaml'; candidate.write_bytes(proposed)
    result = {'startedAt': datetime.now(timezone.utc).isoformat(), 'project': PROJECT,
        'fixtureOnly': True, 'modelCalls': 0, 'liveTailscaleChanged': False,
        'remoteCyonyChanged': False, 'image': image_ref, 'hostPort': host_port,
        'flowStyle': flow_style, 'legacyApiEnableValuePreserved': 'false' if flow_style else 'true'}
    (OUT / 'ATTEMPT.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    try:
        compose(baseline, 'up', '-d', '--no-deps', '--pull', 'never', 'hermes')
        first = inside_ready()
        assert read_inside()['marker'] == 'fixture-state-must-survive'
        assert not first['HostConfig'].get('PortBindings')
        compose(candidate, 'config', '--quiet')
        compose(candidate, 'up', '-d', '--no-deps', '--pull', 'never', 'hermes')
        second = inside_ready()
        assert second['Id'] != first['Id']
        binding = second['NetworkSettings']['Ports']['8642/tcp']
        assert binding == [{'HostIp': '127.0.0.1', 'HostPort': str(host_port)}]
        opener = build_opener(ProxyHandler({}))
        base = 'http://127.0.0.1:' + str(host_port)
        try:
            opener.open(base + '/v1/capabilities', timeout=5)
            raise AssertionError('Unauthenticated fixture unexpectedly accepted')
        except HTTPError as error:
            assert error.code == 401
        headers = {'Authorization': 'Bearer fixture-key-only'}
        with opener.open(Request(base + '/v1/capabilities', headers=headers), timeout=5) as response:
            assert json.loads(response.read())['marker'] == 'fixture-state-must-survive'
        with opener.open(Request(base + '/v1/runs/fixture/events', headers=headers), timeout=5) as response:
            frames = response.read().decode()
            assert frames.index('message.delta') < frames.index('run.completed')
        restored = restore_compose(proposed, original=raw, proposed=proposed)
        assert restored == raw
        baseline.write_bytes(restored)
        compose(baseline, 'up', '-d', '--no-deps', '--pull', 'never', 'hermes')
        third = inside_ready()
        assert not third['HostConfig'].get('PortBindings')
        assert read_inside()['marker'] == 'fixture-state-must-survive'
        result.update(verified=True, publishedOnlyToLoopback=True,
            unauthenticatedReadRejected=True, authenticatedReadPassed=True,
            orderedSsePassed=True, stateSurvivedBothRecreates=True,
            exactOriginalRestored=True, realHermesModelTest=False,
            realTailscaleTlsTest=False)
    finally:
        # Only the exact predeclared test project; no volume/image/global prune.
        ids = command('docker', 'ps', '-aq', '--filter', 'label=com.docker.compose.project=' + PROJECT).split()
        if ids:
            assert current_container()['Config']['Labels']['onoes.mesh.test'] == 'cyony-private-route'
            compose(baseline, 'down')
        result['ownedContainersRemaining'] = command('docker', 'ps', '-aq', '--filter',
            'label=com.docker.compose.project=' + PROJECT).split()
        assert not result['ownedContainersRemaining']
        (OUT / 'RESULT.json').write_text(json.dumps(result, indent=2, sort_keys=True), encoding='utf-8')
    print(json.dumps(result))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-directory', required=True)
    parser.add_argument('--project', default=PROJECT)
    parser.add_argument('--flow-style', action='store_true')
    options = parser.parse_args()
    main(options.output_directory, options.project, options.flow_style)
