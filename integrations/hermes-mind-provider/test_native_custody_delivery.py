"""Private remote delivery/readback in cached Linux image; synthetic tokens only."""
import os
from pathlib import Path
import sys
import sysconfig

import pytest

MIND=Path(os.environ['MIND_SOURCE']);sys.path[:0]=[str(MIND),str(MIND/'tests')]
from cloud_client_package import build_package,materialize,sha,PackageConflict,CLIENT
from cloud_custody_delivery import provision

pytestmark=pytest.mark.skipif(os.name!='posix',reason='Real POSIX private custody')


def public(root):
    return {p.relative_to(root).as_posix():p.read_bytes() for p in root.rglob('*')
        if p.is_file() and '__pycache__' not in p.parts and p.suffix not in ('.pyc','.pyo')}


@pytest.fixture
def installed(tmp_path):
    home=tmp_path/'delivery-home';home.mkdir(mode=0o700)
    sdk={n:b for n,b in public(Path('/staged-sdk')).items()
        if n.startswith('onoes_mind/') or n=='scripts/remote_project_stdio.py'}
    package=build_package(home=str(home),base_url='https://fixture.synthetic.ts.net/mind-agents',
        home_binding_sha256='a'*64,context_binding_sha256='b'*64,principal_id='context-cyony',project_id='onoes-mesh',
        python_resolved=str(Path(sys.executable).resolve()),python_sha256=sha(Path(sys.executable).resolve().read_bytes()),
        native_purelib=sysconfig.get_path('purelib'),sdk_files=sdk,
        plugin_files=public(Path(__file__).parent/'onoes_mind_provider'),mcp_files=public(Path('/reader-deps')),
        settings_files=public(Path('/reader-extra')))
    materialize(package)
    return package,dict(home_token='omh1_'+'a'*43,reader_token='ctx2_'+'b'*43,intent_key=b'x'*32)


def test_actual_sdk_private_custody_readback_and_repeat_refusal_preserve_files(installed):
    package,args=installed;receipt=provision(package,**args)
    assert receipt['sdkReadbackVerified'] and receipt['credentialsPrinted'] is False
    assert args['home_token'] not in str(receipt) and args['reader_token'] not in str(receipt)
    custody=Path(package.home)/CLIENT/'custody'
    originals={p.name:p.read_bytes() for p in custody.iterdir()}
    assert set(originals)=={'home.json','context.json','intent.key'}
    with pytest.raises(PackageConflict):provision(package,**args)
    assert {p.name:p.read_bytes() for p in custody.iterdir()}==originals


@pytest.mark.parametrize('case',['changed-code','invalid-token','pending-intent'])
def test_no_credential_file_written_when_public_code_input_or_intent_state_is_wrong(installed,case):
    package,args=installed;home=Path(package.home)
    if case=='changed-code':
        path=home/next(iter(package.files));path.write_bytes(path.read_bytes()+b'changed')
    elif case=='invalid-token':args['home_token']='not-an-issued-token'
    else:(home/CLIENT/'intents/pending-state').write_bytes(b'Existing unresolved intent')
    with pytest.raises(PackageConflict):provision(package,**args)
    assert not any((home/CLIENT/'custody').iterdir())
