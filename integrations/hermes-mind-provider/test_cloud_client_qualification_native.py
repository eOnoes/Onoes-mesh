# QFN080 real client qualification, synthetic Linux fixture only.
"""Execute the actual cloud_client_entry._run_checked('qualify-held', ...) code
against the real package plus the synthetic TLS fixture.

This is synthetic qualification evidence only: it is not live activation and it
is not proof of the old R9 cause. Linux only.
"""
import importlib.metadata
import json
import os
import ssl
import subprocess
import sys
import sysconfig
from pathlib import Path

import pytest

from test_native_client_package import (
    build_package,
    context_store,
    public_files,
    shared,
    tls_home,
)

from cloud_client_package import load_bundle, materialize, write_bundle
from cloud_client_package import PackageConflict, encoded, sha

from onoes_mind.agent_home_http import home_binding_sha256

# The child script must not interpolate parent pytest objects: it receives the
# request as JSON on stdin and performs the real switch/qualification itself.
# No mocks: the real portable_owner_switch, cloud_client_package, SDK, provider,
# subprocess and MCP_CHECK paths all execute.
CHILD = r'''
import hashlib
import json
import sys
from pathlib import Path

request = json.loads(sys.stdin.read())
home = request['home']
meta = request['meta']

# The parent already exported HERMES_HOME=str(home) before this import, so the
# real Hermes home override comes from the environment, never from an in-process
# patch.

# Verify every package file BEFORE importing any SDK/switch module: the pins
# are relative to the Hermes HOME, not the SDK root, and no package module is
# importable yet under -I.
for name, expected in request['filePins'].items():
    candidate = Path(home) / name
    assert candidate.is_file(), name
    assert hashlib.sha256(candidate.read_bytes()).hexdigest() == expected, name

sys.path[:0] = [meta['sdkRoot'], '/integration', '/opt/hermes']

from cloud_client_package import load_bundle
from cloud_client_package import sha
import cloud_client_entry as entry

package = load_bundle(request['packagePath'], request['bundleSha256'])
assert package.descriptor() == meta

# Match real select/qualify phases: bind the installed plugin before switch validation.
evidence = Path(request['evidence'])
entry.installed({'home': home, 'evidence': str(evidence)}, package)
from portable_owner_switch import install_switch, prepare_switch, rollback_switch

switch_plan = prepare_switch(
    home=home,
    home_profile=meta['homeProfile'],
    home_sha256=meta['homeProfileSha256'],
    reader_profile=meta['readerProfile'],
    reader_sha256=meta['readerProfileSha256'],
    reader_python=meta['readerPython'],
    agent_id='cyony',
    project_id=request['project'],
    principal_id=request['principal'],
    expected_config_sha256=request['configSha256'],
)

installed_config = Path(home) / 'config.yaml'

switch_receipt = None
try:
    switch_receipt = install_switch(
        switch_plan,
        backup_directory=Path(home) / 'owner-backup',
        assert_quiescent=lambda: True,
    )

    plan = {
        'home': home,
        'evidence': str(evidence),
        'selectedConfigurationSha256': sha(installed_config.read_bytes()),
        'gateway': {'sha256': '1' * 64},
        'handoffQuery': 'clientpackagehandoff',
        'handoffRecordId': request['recordId'],
        'minimumHandoffRevision': 7,
    }

    held_calls = []

    def held():
        held_calls.append(1)
        return True

    result = entry._run_checked(
        'qualify-held', '2' * 64, (plan, None, held, None, package, None)
    )

    assert result == {
        'verified': True,
        'privateProviderReadback': True,
        'sharedMcpReadback': True,
        'modelCalls': 0,
    }

    qualification = json.loads((evidence / 'HELD-QUALIFICATION.json').read_bytes())
    assert qualification['schema'] == 'onoes-cloud-held-qualification/v1'
    assert qualification['clientReadback'] is True
    assert qualification['sharedMcpReadback'] is True
    assert qualification['modelCalls'] == 0
    assert len(held_calls) >= 2

    print(json.dumps({
        'verified': True,
        'heldCalls': len(held_calls),
        'readOnlyQualification': True,
    }))
finally:
    if switch_receipt is not None:
        assert rollback_switch(
            switch_plan, switch_receipt, assert_quiescent=lambda: True
        )['restored']
'''


@pytest.mark.skipif(sys.platform != 'linux', reason='native client package is Linux-only')
def test_qualify_held_real_entry_synthetic_tls(tls_home, shared, tmp_path):
    assert importlib.metadata.version('mcp') == '2.3.0'
    _, server, _, home_client = tls_home
    reader = shared['client']()
    home = tmp_path / 'qualification-home'
    home.mkdir(mode=0o700)
    assert reader.base_url == home_client().base_url

    sdk = public_files(Path('/staged-sdk'))
    sdk = {
        name: raw
        for name, raw in sdk.items()
        if name.startswith('onoes_mind/') or name == 'scripts/remote_project_stdio.py'
    }
    package = build_package(
        home=str(home),
        base_url=reader.base_url,
        home_binding_sha256=home_binding_sha256(server.homes['cyony'].binding),
        context_binding_sha256=reader.binding_sha256,
        principal_id=reader.principal_id,
        project_id=reader.project_id,
        python_resolved=str(Path(sys.executable).resolve()),
        python_sha256=sha(Path(sys.executable).resolve().read_bytes()),
        native_purelib=sysconfig.get_path('purelib'),
        sdk_files=sdk,
        plugin_files=public_files(Path(__file__).parent / 'onoes_mind_provider'),
        mcp_files=public_files(Path('/reader-deps')),
        settings_files=public_files(Path('/reader-extra')),
    )
    original = b'''# Existing profile, untouched by client materialization.
model: {default: existing-cloud-model}
memory: {memory_enabled: true, user_profile_enabled: true}
mcp_servers:
  blender: {command: existing-blender-server, env: {KEEP: '${DO_NOT_EXPAND}'}}
'''
    (home / 'config.yaml').write_bytes(original)
    bundle = tmp_path / 'qualification-client.zip'
    stamp = write_bundle(package, bundle)
    package = load_bundle(bundle, stamp['sha256'])
    receipt = materialize(package)
    assert (home / 'config.yaml').read_bytes() == original
    assert receipt['readerVersion'] == '1.26.0'
    assert receipt['credentialsCreated'] is False

    private = home / 'onoes-mind' / 'cyony' / 'custody'

    def put(path, raw):
        path.write_bytes(raw)
        path.chmod(0o600)

    # Synthetic tokens/key only: production materialization deliberately supplies none.
    put(private / 'home.json', encoded({
        'schema': 'onoes-mind/posix-home-credential/v1',
        'agent_id': 'cyony',
        'binding_sha256': home_binding_sha256(server.homes['cyony'].binding),
        'token': home_client().credential_provider(),
    }))
    put(private / 'context.json', encoded({
        'schema': 'onoes-mind/posix-context-credential/v1',
        'principal_id': reader.principal_id,
        'binding_sha256': reader.binding_sha256,
        'token': shared['tokens']['cyony'],
    }))
    put(private / 'intent.key', os.urandom(32))
    (home / 'owner-backup').mkdir(mode=0o700)
    memories = home / 'memories'
    memories.mkdir(mode=0o700)
    for name in ('MEMORY.md', 'USER.md'):
        put(memories / name, b'Existing native curated original.')

    doc = {
        'author': 'nims',
        'revision': 7,
        'marker': 'clientpackagehandoff',
        'next_action': 'Read the current measured specification',
    }
    shared['remember']('qualification-shared-seed', json.dumps(doc))

    records = shared['client']().read({'query': 'clientpackagehandoff'})['records']
    record, = records
    record_id = record['record_id']

    # Evidence lives outside the package home and never inside the bundle tree.
    evidence = tmp_path / 'qualification-evidence'
    evidence.mkdir(mode=0o700)
    (evidence / 'MATERIALIZED.json').write_bytes(json.dumps(receipt, sort_keys=True).encode())
    (evidence / 'MATERIALIZED.json').chmod(0o600)

    meta = package.descriptor()
    request = {
        'home': str(home),
        'package': meta,
        'packagePath': str(bundle),
        'bundleSha256': stamp['sha256'],
        'project': reader.project_id,
        'principal': reader.principal_id,
        'configSha256': sha(original),
        'recordId': record_id,
        'evidence': str(evidence),
        'meta': meta,
        'filePins': {name: sha(raw) for name, raw in package.files.items()},
    }

    env = dict(os.environ)
    # Trust the existing synthetic fixture CA only in this test child. Production
    # profiles and the reader bootstrap have no certificate override.
    trusted = home_client()._tls_context.get_ca_certs(binary_form=True)
    assert len(trusted) == 1
    ca = tmp_path / 'fixture-ca.pem'
    put(ca, ssl.DER_cert_to_PEM_cert(trusted[0]).encode())
    env['SSL_CERT_FILE'] = str(ca)
    # Native MCP starts children with a reduced environment, so the fake CA
    # belongs in a separate test-only startup file for this disposable reader.
    # Leave the actual packaged dependency bootstrap and its receipt unchanged.
    site = (
        Path(meta['readerPython']).parents[1]
        / 'lib'
        / f'python{sys.version_info.major}.{sys.version_info.minor}'
        / 'site-packages'
    )
    put(
        site / 'synthetic-fixture-ca.pth',
        ('import os; os.environ["SSL_CERT_FILE"]=' + repr(str(ca)) + '\n').encode(),
    )

    env['HERMES_HOME'] = str(home)
    result = subprocess.run(
        [sys.executable, '-I', '-B', '-c', CHILD],
        input=json.dumps(request),
        capture_output=True,
        text=True,
        env=env,
        timeout=70,
    )
    assert result.returncode == 0, result.stderr[-4000:]
    response = json.loads(result.stdout)
    assert sorted(response) == ['heldCalls', 'readOnlyQualification', 'verified']
    assert response['verified'] is True
    assert response['readOnlyQualification'] is True
    assert response['heldCalls'] >= 2

    qualification = json.loads((evidence / 'HELD-QUALIFICATION.json').read_bytes())
    assert qualification['schema'] == 'onoes-cloud-held-qualification/v1'
    assert qualification['clientReadback'] is True
    assert qualification['sharedMcpReadback'] is True
    assert qualification['modelCalls'] == 0

    import hermes_yaml as yaml

    restored_config = yaml.safe_load((home / 'config.yaml').read_text())
    assert restored_config == yaml.safe_load(original.decode())
    for name in ('MEMORY.md', 'USER.md'):
        assert (memories / name).read_bytes() == b'Existing native curated original.'

    snapshot = (home / 'config.yaml').read_bytes()
    with pytest.raises(PackageConflict):
        materialize(package)
    assert (home / 'config.yaml').read_bytes() == snapshot
