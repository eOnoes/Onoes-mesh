"""Native Hermes discovery + registry dispatch, synthetic home/store/TLS only."""
import importlib.metadata
import importlib.util
import json
import os
from pathlib import Path
import ssl
import subprocess
import sys
import venv

import pytest

MIND=Path(os.environ['MIND_SOURCE']).resolve()
sys.path[:0]=[str(MIND),str(MIND/'tests'),os.environ['HERMES_SOURCE']]
from test_agent_context import context_store
from test_remote_home_client import tls_home
from test_project_context_http import shared
from test_portable_provider import profile,scope,loaded,call,canonical,private
from portable_owner_switch import SERVER,TOOL,prepare_switch,install_switch,rollback_switch

pytestmark=pytest.mark.skipif(os.name!='posix',reason='Native POSIX MCP/custody rehearsal')


@pytest.fixture
def staged_native_reader(profile,shared):
    assert importlib.metadata.version('mcp')=='2.3.0'

    document={'author':'nims','revision':9,'marker':'handoffmarker',
              'next_action':'Read the current measured print specification'}
    shared['remember']('native-shared-handoff',json.dumps(document))
    home=profile['home'];review=home/'review';client=shared['client']()
    custody=home/'custody/context.json'
    private(custody,canonical({'schema':'onoes-mind/posix-context-credential/v1',
        'principal_id':client.principal_id,'binding_sha256':client.binding_sha256,
        'token':shared['tokens']['cyony']}))
    entry_path=MIND/'scripts/remote_project_stdio.py'
    spec=importlib.util.spec_from_file_location('reader_for_native_fixture',entry_path)
    entry=importlib.util.module_from_spec(spec);spec.loader.exec_module(entry)
    reader=review/'shared-reader.json'
    body={'schema':'onoes-mind/remote-project-mcp/v1','mind_source':str(MIND),
        'source_hashes':entry.source_pins(),'endpoint':client.base_url,
        'principal_id':client.principal_id,'project_id':client.project_id,
        'scope_id':client.scope_id,'binding_sha256':client.binding_sha256,
        'credential_file':str(custody),'review_ref':'fixture:native-shared-reader'}
    reader_bytes=canonical(body);private(reader,reader_bytes)
    from hashlib import sha256

    # Separate child runtime: keep the native gateway's MCP2.3 unchanged.
    runtime=home/'reader-runtime'
    venv.EnvBuilder(with_pip=False,symlinks=True).create(runtime)
    site=runtime/'lib'/f'python{sys.version_info.major}.{sys.version_info.minor}'/'site-packages'
    import sysconfig
    package_paths=['/reader-deps','/reader-extra',sysconfig.get_path('purelib')]
    # Trust only the synthetic CA in this disposable child, not a live config option.
    child_init='import sys; sys.path[0:0]='+repr(package_paths)+'\n'
    child_init+='import os; os.environ[\'SSL_CERT_FILE\']='+repr(str(review/'fixture-ca.pem'))+'\n'
    (site/'qualified-reader.pth').write_text(child_init,encoding='utf-8')
    python=runtime/'bin/python'
    version=subprocess.run([str(python),'-I','-B','-c',
        "import mcp,importlib.metadata,json;print(json.dumps([importlib.metadata.version('mcp'),mcp.__file__]))"],
        capture_output=True,text=True,timeout=15)
    assert version.returncode==0,version.stderr
    child_version,child_source=json.loads(version.stdout)
    assert child_version=='1.26.0' and Path(child_source).is_relative_to('/reader-deps')
    profile['body']['shared_project_tool']=TOOL
    profile['path'].write_bytes(canonical(profile['body']))
    original=b'''# Preserve the existing cloud profile and literal secret reference.
model: {default: existing-cloud-model}
memory:
  provider: ''
  memory_enabled: true
  user_profile_enabled: true
  custom_limit: 1500 # Keep this comment too.
mcp_servers:
  blender:
    command: existing-blender-server
    env: {EXISTING_SECRET: '${DO_NOT_EXPAND}'}
platforms: {telegram: {enabled: true}}
'''
    (home/'config.yaml').write_bytes(original)
    backup=home/'owner-backup';backup.mkdir(mode=0o700)
    native_files={'MEMORY.md':b'Existing selected native memory remains here.',
                  'USER.md':b'Existing native user profile remains here.'}
    for filename,raw in native_files.items():(home/filename).write_bytes(raw)
    arguments=dict(home=home,home_profile=profile['path'],home_sha256=sha256(profile['path'].read_bytes()).hexdigest(),
        reader_profile=reader,reader_sha256=sha256(reader_bytes).hexdigest(),reader_python=python,
        agent_id='cyony',project_id=client.project_id,principal_id=client.principal_id,
        expected_config_sha256=sha256(original).hexdigest())
    return dict(profile=profile,shared=shared,document=document,reader=reader,reader_bytes=reader_bytes,
        original=original,backup=backup,arguments=arguments,native_files=native_files)


def test_native_discovery_dispatch_shared_handoff_and_private_home_keep_separate_current_permissions(staged_native_reader):
    from tools.mcp_tool_discovery import discover_mcp_tools
    from tools.mcp_tool_lifecycle import shutdown_mcp_servers
    from tools.registry import registry
    import tools.mcp_tool as core
    fixture=staged_native_reader;profile=fixture['profile'];shared=fixture['shared'];home=profile['home']
    reader=fixture['reader'];reader_bytes=fixture['reader_bytes'];document=fixture['document']

    with scope(home):
        plan=prepare_switch(**fixture['arguments'])
        receipt=install_switch(plan,backup_directory=fixture['backup'],assert_quiescent=lambda:True)
        provider=None;manager=None
        try:
            provider,manager=loaded(profile)
            assert TOOL in provider.system_prompt_block()
            saved=call(manager,'remember',event_id='native-composed-private',text='Private azureharbor preference')
            assert saved['ok']
            names=discover_mcp_tools(allowed_mcp_names=[SERVER])
            name=TOOL
            assert name in names and registry.get_entry(name) is not None
            schema,=registry.get_definitions({name})
            assert schema['function']['name']==name
            assert set(schema['function']['parameters']['properties'])=={'query','limit','max_bytes'}
            def dispatch(arguments):
                result=json.loads(registry.dispatch(name,arguments))
                if 'error' in result:return result
                assert isinstance(result['result'],str)
                return json.loads(result['result'])
            result=dispatch({'query':'handoffmarker'})
            assert result['ok']
            record,=result['result']['records']
            assert json.loads(record['claim'])==document and record['provenance']
            assert result['result']['content_role']=='reference_data'
            requests=len(shared['proxy']['requests'])
            assert 'error' in dispatch({'query':'handoffmarker','project_id':'other'})
            assert len(shared['proxy']['requests'])==requests
            grant=shared['grants']['cyony'];grant.path.unlink()
            assert 'error' in dispatch({'query':'handoffmarker'})
            assert call(manager,'recall',query='azureharbor')['result']['records'][0]['record_id']==saved['receipt']['record_id']
            grant.path.write_bytes(grant.document())
            assert dispatch({'query':'handoffmarker'})['ok']
            reader.write_bytes(reader_bytes+b' ')
            requests=len(shared['proxy']['requests'])
            assert 'error' in dispatch({'query':'handoffmarker'})
            assert len(shared['proxy']['requests'])==requests
            assert call(manager,'recall',query='azureharbor')['ok']
        finally:
            shutdown_mcp_servers(scope=registry.current_scope_key(),names={SERVER},timeout=15)
            if manager is not None:manager.shutdown_all()
            rollback_switch(plan,receipt,assert_quiescent=lambda:True)
        assert not core._servers
        assert registry.get_entry(TOOL) is None
        from hermes_cli.config import require_readable_config_before_write
        assert require_readable_config_before_write(home/'config.yaml')==plan.original
        for filename,raw in fixture['native_files'].items():assert (home/filename).read_bytes()==raw
        text=(home/'config.yaml').read_text(encoding='utf-8')
        assert '# Keep this comment too.' in text and '${DO_NOT_EXPAND}' in text
