"""Credential-free portable client assembly; no filesystem or model operations."""
from dataclasses import replace
import json

import pytest

from cloud_client_package import PackageConflict,build_package,verify_package,write_bundle,load_bundle


@pytest.fixture
def inputs():
    return dict(home='/opt/data',base_url='https://echo.synthetic.ts.net:8453/mind-agents',
        home_binding_sha256='a'*64,context_binding_sha256='b'*64,
        principal_id='context-cyony',project_id='onoes-mesh',
        python_resolved='/opt/python/bin/python3.14',python_sha256='c'*64,native_purelib='/opt/hermes/lib/python3.14/site-packages',
        sdk_files={'onoes_mind/__init__.py':b'','scripts/remote_project_stdio.py':b'# synthetic entry\n'},
        plugin_files={n:b'# synthetic public code\n' for n in ('__init__.py','portable.py','config.py','portable_profile.py','journal.py')},
        mcp_files={'mcp/__init__.py':b'','mcp-1.26.0.dist-info/METADATA':b'Name: mcp\nVersion: 1.26.0\n'},
        settings_files={'pydantic_settings/__init__.py':b'','pydantic_settings-2.13.1.dist-info/METADATA':b'Name: pydantic-settings\nVersion: 2.13.1\n'})


def test_package_has_only_public_code_and_fixed_profiles_not_credentials_or_config(inputs):
    package=build_package(**inputs);verify_package(package)
    meta=package.descriptor()
    assert meta['agentId']=='cyony' and meta['readerPrincipal']=='context-cyony'
    assert meta['activated'] is False and meta['credentialsCreated'] is False and meta['configChanged'] is False
    home=json.loads(package.files['onoes-mind/cyony/review/home-profile.json'])
    reader=json.loads(package.files['onoes-mind/cyony/review/shared-reader.json'])
    assert home['home_endpoint']==reader['endpoint']==inputs['base_url']
    assert home['shared_project_tool']=='mcp__onoes_mind_mesh__read_project_context'
    assert reader['project_id']=='onoes-mesh' and reader['scope_id']=='project/onoes-mind/shared'
    assert inputs['python_resolved'] in reader['source_hashes']
    assert 'config.yaml' not in package.files
    assert not any('/custody/' in name or name.endswith('.key') for name in package.files)
    with pytest.raises(TypeError):package.files['config.yaml']=b'bad'
    with pytest.raises(TypeError):package.metadata['home']='/another/home'


@pytest.mark.parametrize('case',['http','public-host','actor','parent-path','compiled-code','wrong-reader-version','home-escape'])
def test_unreviewed_transport_identity_and_payloads_are_refused(inputs,case):
    if case=='http':inputs['base_url']='http://echo.synthetic.ts.net:8453/mind-agents'
    elif case=='public-host':inputs['base_url']='https://example.com/mind-agents'
    elif case=='actor':inputs['principal_id']='context-echo'
    elif case=='parent-path':inputs['sdk_files']['../outside.py']=b'bad'
    elif case=='compiled-code':inputs['mcp_files']['mcp/old.pyd']=b'bad'
    elif case=='wrong-reader-version':inputs['mcp_files']['mcp-1.26.0.dist-info/METADATA']=b'Name: mcp\nVersion: 2.3.0\n'
    else:inputs['home']='/opt/data/../another-home'
    with pytest.raises(PackageConflict):build_package(**inputs)


def test_modified_payload_or_changed_destination_cannot_pass_the_original_manifest(inputs):
    package=build_package(**inputs);changed=dict(package.files)
    changed['plugins/onoes_mind/__init__.py']=b'changed'
    with pytest.raises(PackageConflict):verify_package(replace(package,files=changed))
    with pytest.raises(PackageConflict):verify_package(replace(package,home='/another-home'))


def test_offline_bundle_roundtrip_keeps_exact_public_payload_and_refuses_wrong_outer_fingerprint(inputs,tmp_path):
    package=build_package(**inputs);path=tmp_path/'public-code.zip'
    receipt=write_bundle(package,path);restored=load_bundle(path,receipt['sha256'])
    assert dict(restored.files)==dict(package.files) and restored.descriptor()==package.descriptor()
    assert receipt['credentialsIncluded'] is False
    with pytest.raises(PackageConflict):load_bundle(path,'0'*64)


def test_bundle_cannot_be_repacked_with_a_custody_file(inputs,tmp_path):
    package=build_package(**inputs);files=dict(package.files)
    files['onoes-mind/cyony/custody/home.json']=b'not-public-code'
    with pytest.raises(PackageConflict):write_bundle(replace(package,files=files),tmp_path/'refused.zip')
