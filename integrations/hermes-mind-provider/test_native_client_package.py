"""Install the exact offline client layout and use native private/shared tools."""
import importlib.metadata
import json
import os
from pathlib import Path
import ssl
import subprocess
import sys
import sysconfig

import pytest

MIND=Path(os.environ['MIND_SOURCE']).resolve()
sys.path[:0]=[str(MIND),str(MIND/'tests'),os.environ['HERMES_SOURCE']]
from test_agent_context import context_store
from test_remote_home_client import tls_home
from test_project_context_http import shared
from cloud_client_package import PackageConflict,build_package,materialize,encoded,sha,write_bundle,load_bundle
from onoes_mind.agent_home_http import home_binding_sha256

pytestmark=pytest.mark.skipif(os.name!='posix',reason='Actual Linux client installation/loader')


def public_files(root):
    return {p.relative_to(root).as_posix():p.read_bytes() for p in root.rglob('*')
        if p.is_file() and '__pycache__' not in p.parts and p.suffix not in ('.pyc','.pyo')}


CHILD=r'''
import hashlib,json,sys
from pathlib import Path
request=json.load(sys.stdin);home=Path(request['home']);meta=request['package']
# Bootstrap only the independently verified copied SDK. The owner switch itself
# needs SDK custody helpers before loading the selected provider.
for name,pin in request['filePins'].items():
 assert hashlib.sha256((home/name).read_bytes()).hexdigest()==pin
sys.path[:0]=[meta['sdkRoot'],'/integration','/opt/hermes']
from hermes_constants import set_hermes_home_override,reset_hermes_home_override
from portable_owner_switch import prepare_switch,install_switch,rollback_switch,TOOL,SERVER
from plugins.memory import load_memory_provider
from agent.memory_manager import MemoryManager
from tools.mcp_tool_discovery import discover_mcp_tools
from tools.mcp_tool_lifecycle import shutdown_mcp_servers
from tools.registry import registry
token=set_hermes_home_override(home);manager=None;receipt=None
try:
 plan=prepare_switch(home=home,home_profile=meta['homeProfile'],home_sha256=meta['homeProfileSha256'],
  reader_profile=meta['readerProfile'],reader_sha256=meta['readerProfileSha256'],reader_python=meta['readerPython'],
  agent_id='cyony',project_id=request['project'],principal_id=request['principal'],expected_config_sha256=request['configSha256'])
 receipt=install_switch(plan,backup_directory=home/'owner-backup',assert_quiescent=lambda:True)
 provider=load_memory_provider('onoes_mind',register_skills=False)
 assert provider is not None and provider.is_available()
 manager=MemoryManager();manager.add_provider(provider)
 manager.initialize_all(session_id='synthetic-packaged-client',hermes_home=str(home),agent_context='primary')
 assert TOOL in provider.system_prompt_block()
 saved=json.loads(manager.handle_tool_call('onoes_memory',{'action':'remember','event_id':'packaged-private-write','text':'Packaged private harbor note'}))
 assert saved['ok']
 assert TOOL in discover_mcp_tools(allowed_mcp_names=[SERVER])
 definition,=registry.get_definitions({TOOL});assert definition['function']['name']==TOOL
 response=json.loads(registry.dispatch(TOOL,{'query':'clientpackagehandoff'}))
 assert 'result' in response,response
 result=json.loads(response['result']);assert result['ok']
 record,=result['result']['records']
 assert json.loads(record['claim'])==request['document'] and record['provenance']
 assert result['result']['content_role']=='reference_data'
 print(json.dumps({'privateSaved':True,'recordId':saved['receipt']['record_id'],'sharedDocument':json.loads(record['claim']),
  'correctNativeTool':True,'provenance':True}),flush=True)
finally:
 shutdown_mcp_servers(scope=registry.current_scope_key(),names={SERVER},timeout=15)
 if manager is not None:manager.shutdown_all()
 if receipt is not None:assert rollback_switch(plan,receipt,assert_quiescent=lambda:True)['restored']
 reset_hermes_home_override(token)
'''


def test_offline_package_native_install_private_write_shared_handoff_and_original_config_restore(tls_home,shared,tmp_path):
    assert importlib.metadata.version('mcp')=='2.3.0'
    _,server,_,home_client=tls_home
    reader=shared['client']();home=tmp_path/'packaged-home';home.mkdir(mode=0o700)
    assert reader.base_url==home_client().base_url
    sdk=public_files(Path('/staged-sdk'))
    sdk={name:raw for name,raw in sdk.items() if name.startswith('onoes_mind/') or name=='scripts/remote_project_stdio.py'}
    package=build_package(home=str(home),base_url=reader.base_url,
        home_binding_sha256=home_binding_sha256(server.homes['cyony'].binding),context_binding_sha256=reader.binding_sha256,
        principal_id=reader.principal_id,project_id=reader.project_id,python_resolved=str(Path(sys.executable).resolve()),
        python_sha256=sha(Path(sys.executable).resolve().read_bytes()),native_purelib=sysconfig.get_path('purelib'),
        sdk_files=sdk,plugin_files=public_files(Path(__file__).parent/'onoes_mind_provider'),
        mcp_files=public_files(Path('/reader-deps')),settings_files=public_files(Path('/reader-extra')))
    original=b'''# Existing profile, untouched by client materialization.
model: {default: existing-cloud-model}
memory: {memory_enabled: true, user_profile_enabled: true}
mcp_servers:
  blender: {command: existing-blender-server, env: {KEEP: '${DO_NOT_EXPAND}'}}
'''
    (home/'config.yaml').write_bytes(original)
    bundle=tmp_path/'offline-client.zip';stamp=write_bundle(package,bundle)
    package=load_bundle(bundle,stamp['sha256'])
    receipt=materialize(package)
    assert (home/'config.yaml').read_bytes()==original
    assert receipt['readerVersion']=='1.26.0' and receipt['credentialsCreated'] is False
    private=home/'onoes-mind/cyony/custody'
    def put(path,raw):
        path.write_bytes(raw);path.chmod(0o600)
    # Synthetic tokens/key only: production materialization deliberately supplies none.
    put(private/'home.json',encoded({'schema':'onoes-mind/posix-home-credential/v1','agent_id':'cyony',
        'binding_sha256':home_binding_sha256(server.homes['cyony'].binding),'token':home_client().credential_provider()}))
    put(private/'context.json',encoded({'schema':'onoes-mind/posix-context-credential/v1',
        'principal_id':reader.principal_id,'binding_sha256':reader.binding_sha256,'token':shared['tokens']['cyony']}))
    put(private/'intent.key',os.urandom(32));(home/'owner-backup').mkdir(mode=0o700)
    memories=home/'memories';memories.mkdir(mode=0o700)
    for name in ('MEMORY.md','USER.md'):put(memories/name,b'Existing native curated original.')
    doc={'author':'nims','revision':7,'marker':'clientpackagehandoff','next_action':'Read the current measured specification'}
    shared['remember']('packaged-shared-seed',json.dumps(doc))
    request={'home':str(home),'package':package.descriptor(),'project':reader.project_id,
        'principal':reader.principal_id,'configSha256':sha(original),'document':doc,
        'filePins':{name:sha(raw) for name,raw in package.files.items()}}
    env=dict(os.environ)
    # Trust the existing synthetic fixture CA only in this test child. Production
    # profiles and the reader bootstrap have no certificate override.
    trusted=home_client()._tls_context.get_ca_certs(binary_form=True);assert len(trusted)==1
    ca=tmp_path/'fixture-ca.pem';put(ca,ssl.DER_cert_to_PEM_cert(trusted[0]).encode())
    env['SSL_CERT_FILE']=str(ca)
    # Native MCP starts children with a reduced environment, so the fake CA
    # belongs in a separate test-only startup file for this disposable reader.
    # Leave the actual packaged dependency bootstrap and its receipt unchanged.
    site=Path(package.descriptor()['readerPython']).parents[1]/'lib'/f'python{sys.version_info.major}.{sys.version_info.minor}'/'site-packages'
    put(site/'synthetic-fixture-ca.pth',('import os; os.environ["SSL_CERT_FILE"]='+repr(str(ca))+'\n').encode())
    result=subprocess.run([sys.executable,'-I','-B','-c',CHILD],input=json.dumps(request),
        capture_output=True,text=True,env=env,timeout=70)
    assert result.returncode==0,result.stderr[-4000:]
    response=json.loads(result.stdout)
    record,=home_client().call('recall',{'query':'Packaged private harbor'})['records']
    assert response['recordId']==record['record_id'] and response['sharedDocument']==doc
    import hermes_yaml as yaml
    restored=yaml.safe_load((home/'config.yaml').read_text())
    assert restored==yaml.safe_load(original.decode())
    for name in ('MEMORY.md','USER.md'):assert (memories/name).read_bytes()==b'Existing native curated original.'
    assert importlib.metadata.version('mcp')=='2.3.0'
    snapshot=(home/'config.yaml').read_bytes()
    with pytest.raises(PackageConflict):materialize(package)
    assert (home/'config.yaml').read_bytes()==snapshot
