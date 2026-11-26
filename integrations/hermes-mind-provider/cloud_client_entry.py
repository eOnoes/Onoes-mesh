"""Finite cloud client/capture/configuration operations under the native hold.

No model, enrollment, gateway start, service registration or automatic retry.
Credential stdin and curated stdout are private transports, never journal text.
The caller installs public code before capture and delivers credentials later.
"""
from dataclasses import replace
import base64,hashlib,importlib.util,json,os,stat,subprocess,sys,traceback
from pathlib import Path


class ClientHeld(RuntimeError):pass


def require(ok):
    if not ok:raise ClientHeld('Cloud client operation is unconfirmed; preserve the original window')


def sha(raw):return hashlib.sha256(raw).hexdigest()
def digest(path):return sha(Path(path).read_bytes())


def private_read(path,limit=262144):
    p=Path(path);require(p.is_absolute() and p.resolve(strict=True)==p)
    s=p.stat();require(stat.S_ISREG(s.st_mode) and s.st_uid==os.geteuid()
        and not stat.S_IMODE(s.st_mode)&0o077 and s.st_nlink==1 and s.st_size<=limit)
    return p.read_bytes()


def read(path):
    def unique(pairs):
        result={}
        for k,v in pairs:require(k not in result);result[k]=v
        return result
    result=json.loads(private_read(path),object_pairs_hook=unique);require(type(result) is dict);return result


def save(path,value,*,raw=False):
    data=value if raw else json.dumps(value,sort_keys=True,allow_nan=False).encode()
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'wb') as stream:stream.write(data);stream.flush();os.fsync(stream.fileno())


def load(name,pin):
    path=Path(__file__).with_name(name)
    require(path.resolve(strict=True)==path and digest(path)==pin)
    spec=importlib.util.spec_from_file_location(name.removesuffix('.py'),path)
    module=importlib.util.module_from_spec(spec);sys.modules[spec.name]=module;spec.loader.exec_module(module)
    return module


def approved(phase,plan_path,pin,auth_path):
    require(os.name=='posix' and sys.flags.isolated==1 and sys.dont_write_bytecode
        and phase in ('materialize','capture','export-curated','deliver','select','restore','qualify-held')
        and digest(plan_path)==pin)
    plan=read(plan_path)
    require(plan['schema']=='onoes-cloud-client-operation/v1' and plan['agentId']=='cyony'
        and plan['readerPrincipal']=='context-cyony' and plan['sharedProject']=='onoes-mesh'
        and read(auth_path)=={'schema':'onoes-cloud-client-operation-authorization/v1','owner':'Eddie',
            'decision':'approve_cyony_private_home_and_mesh_reader','planSha256':pin}
        and digest(__file__)==plan['executors']['cloud_client_entry.py'])
    for name in ('cloud_gateway_entry.py','cloud_native_gateway.py','cloud_client_package.py',
                 'cloud_curated_transfer.py','cloud_custody_delivery.py','portable_owner_switch.py','owner_profile_switch.py'):
        require(digest(Path(__file__).with_name(name))==plan['executors'][name])
    gateway=load('cloud_gateway_entry.py',plan['executors']['cloud_gateway_entry.py'])
    g=plan['gateway'];gate_plan=gateway.approved_inputs(g['planPath'],g['sha256'],g['authorizationPath'])
    require(plan['home']==gate_plan['home'] and plan['evidence']==gate_plan['evidence'])
    stopped='verify-rollback-stopped' if phase=='restore' and (Path(plan['evidence'])/'rollback/GATEWAY-STOPPED.json').exists() else 'verify-stopped'
    def held():
        require(gateway.run_phase(stopped,g['planPath'],g['sha256'],g['authorizationPath'])['verified'] is True)
        return True
    held()
    package_api=load('cloud_client_package.py',plan['executors']['cloud_client_package.py'])
    package=package_api.load_bundle(plan['bundlePath'],plan['bundleSha256'])
    require(package.home==plan['home'] and package.descriptor()['endpoint']==plan['endpoint'])
    # -I deliberately omits the script directory. Add only the just-verified
    # owner operation directory so the switch's sibling helper resolves there.
    sys.path.insert(0,str(Path(__file__).parent))
    return plan,gate_plan,held,package_api,package,gateway


def installed(plan,package):
    home=Path(plan['home'])
    for name,raw in package.files.items():require(private_read(home/name,len(raw)+1)==raw)
    receipt=read(Path(plan['evidence'])/'MATERIALIZED.json')
    require(receipt['manifestSha256']==package.manifest_sha256 and receipt['codeInstalled'] is True)
    pth=home/'onoes-mind/cyony/reader-runtime/lib'/('python'+str(sys.version_info.major)+'.'+str(sys.version_info.minor))/'site-packages/onoes-reader-dependencies.pth'
    require(digest(pth)==receipt['bootstrapPthSha256'])
    sdk=home/'onoes-mind/sdk-4a7c3e3';sys.path.insert(0,str(sdk))
    import onoes_mind
    require(Path(onoes_mind.__file__).resolve().parent.parent==sdk)
    # The offline bundle installs the plugin at Hermes' native plugin path;
    # the existing switch helper imports its source package name. Bind that
    # name to the same already-pinned package, never a second copy/identity.
    plugin=home/'plugins/onoes_mind';name='onoes_mind_provider'
    if name in sys.modules:
        require(Path(sys.modules[name].__file__).resolve()==plugin/'__init__.py')
    else:
        spec=importlib.util.spec_from_file_location(name,plugin/'__init__.py',submodule_search_locations=[str(plugin)])
        module=importlib.util.module_from_spec(spec);sys.modules[name]=module;spec.loader.exec_module(module)
    return sdk


def switch_plan(plan,package,*,restore=False):
    api=load('portable_owner_switch.py',plan['executors']['portable_owner_switch.py'])
    meta=package.descriptor();home=Path(plan['home'])
    args=dict(home=home,home_profile=meta['homeProfile'],home_sha256=meta['homeProfileSha256'],
        reader_profile=meta['readerProfile'],reader_sha256=meta['readerProfileSha256'],reader_python=meta['readerPython'],
        agent_id='cyony',project_id='onoes-mesh',principal_id='context-cyony',
        expected_config_sha256=plan['configurationBeforeSha256'])
    if not restore:return api,api.prepare_switch(**args)
    import hermes_yaml as yaml
    raw=private_read(Path(plan['evidence'])/'config-before/hermes-config-before-mind.yaml',1024*1024)
    require(sha(raw)==plan['configurationBeforeSha256'])
    original=yaml.safe_load(raw.decode('utf-8-sig'));require(type(original) is dict)
    prepared=api.PortableSwitch(home,Path(args['home_profile']),args['home_sha256'],Path(args['reader_profile']),
        args['reader_sha256'],Path(args['reader_python']),Path(meta['readerEntry']),'cyony','onoes-mesh','context-cyony',
        plan['configurationBeforeSha256'],raw,original,{})
    return api,replace(prepared,proposed=api.proposed_settings(prepared))


MCP_CHECK=r'''
import asyncio,json,sys,traceback
from mcp import ClientSession,StdioServerParameters
from mcp.client.stdio import stdio_client
phase='initialize';observed_records=None
async def main():
    global phase,observed_records
    p=json.loads(sys.argv[1]);command=StdioServerParameters(command=sys.executable,
        args=['-I','-B',p['entry'],'--profile',p['profile'],'--sha256',p['sha256']])
    async with stdio_client(command) as (reader,writer):
        async with ClientSession(reader,writer) as session:
            await session.initialize();phase='list-tools';tools=await session.list_tools()
            assert [t.name for t in tools.tools]==['read_project_context']
            phase='read-project'
            reply=await session.call_tool('read_project_context',{'query':p['query']})
            assert not reply.isError
            result=json.loads(reply.content[0].text);assert result['ok'] is True
            phase='match-handoff';observed_records=len(result['result']['records'])
            matches=[r for r in result['result']['records'] if r['record_id']==p['recordId']]
            assert len(matches)==1 and matches[0]['provenance']
            doc=json.loads(matches[0]['claim']);assert doc['author']=='nims' and doc['revision']>=p['minimumRevision']
            print(json.dumps({'verified':True,'author':'nims','documentRevision':doc['revision'],'recordId':p['recordId']}))
try:asyncio.run(asyncio.wait_for(main(),40))
except BaseException as error:
    print(json.dumps({'errorType':type(error).__name__,'phase':phase,'observedRecords':observed_records,
        'frames':[{'function':f.name,'line':f.lineno} for f in traceback.extract_tb(error.__traceback__)[-8:]],
        'messagesAndLocalsExcluded':True}));raise SystemExit(1)
'''


def _run_checked(phase,pin,context):
    plan,gate,held,package_api,package,gateway=context
    held()
    evidence=Path(plan['evidence']);home=Path(plan['home'])
    if phase=='materialize':
        save(evidence/'MATERIALIZE-ATTEMPT.json',{'planSha256':pin,'automaticRetry':False})
        result=package_api.materialize(package);held();save(evidence/'MATERIALIZED.json',result)
        return {'verified':True,'publicCodeOnly':True,'credentialsCreated':False,'configChanged':False}
    installed(plan,package)
    if phase=='capture':
        transfer=load('cloud_curated_transfer.py',plan['executors']['cloud_curated_transfer.py'])
        snapshot=transfer.capture(home,origin='srv1693050/cyony-hermes',expected_identities=plan['curatedSourceIdentities'])
        raw=transfer.encode(snapshot);held();save(evidence/'CURATED-TRANSPORT.json',raw,raw=True)
        receipt={'schema':'onoes-cloud-curated-capture/v1','verified':True,
            'approvedSourceIdentities':plan['curatedSourceIdentities'],'transportSha256':sha(raw)}
        save(evidence/'CURATED-CAPTURE.json',receipt);return receipt
    if phase=='export-curated':
        raw=private_read(evidence/'CURATED-TRANSPORT.json',16000)
        require(sha(raw)==read(evidence/'CURATED-CAPTURE.json')['transportSha256']);held();return raw
    if phase=='deliver':
        delivery=load('cloud_custody_delivery.py',plan['executors']['cloud_custody_delivery.py'])
        save(evidence/'DELIVERY-ATTEMPT.json',{'planSha256':pin,'automaticRetry':False})
        raw=sys.stdin.buffer.read(8193);require(len(raw)<=8192)
        data=json.loads(raw);require(set(data)=={'homeToken','readerToken','intentKeyBase64'})
        result=delivery.provision(package,home_token=data['homeToken'],reader_token=data['readerToken'],
            intent_key=base64.b64decode(data['intentKeyBase64'],validate=True));data=raw=None
        held();save(evidence/'DELIVERED.json',result);return {'verified':True,'custodyReadback':True}
    if phase=='select':
        api,prepared=switch_plan(plan,package)
        require(gate['releasePins'][str(home/'config.yaml')]==plan['selectedConfigurationSha256'])
        save(evidence/'CONFIG-ATTEMPT.json',{'planSha256':pin,'automaticRetry':False})
        folder=evidence/'config-before';require(not os.path.lexists(folder));folder.mkdir(mode=0o700)
        receipt=api.install_switch(prepared,backup_directory=folder,assert_quiescent=held)
        require(digest(home/'config.yaml')==plan['selectedConfigurationSha256'])
        save(evidence/'CONFIG-SELECTED.json',receipt);return {'verified':True,'gatewayReleased':False}
    if phase=='restore':
        if not (evidence/'CONFIG-ATTEMPT.json').exists():return {'verified':True,'configurationUntouched':True}
        if digest(home/'config.yaml')==plan['configurationBeforeSha256']:
            return {'verified':True,'originalConfigurationAlreadySelected':True}
        # A missing selection acknowledgement remains held; do not invent an
        # installed receipt or derive one from the current configuration.
        receipt=read(evidence/'CONFIG-SELECTED.json');api,prepared=switch_plan(plan,package,restore=True)
        result=api.rollback_switch(prepared,receipt,assert_quiescent=held)
        save(evidence/'CONFIG-RESTORED.json',result);return {'verified':True,'originalConfigurationRestored':True}
    # Qualify the actual configured provider and dedicated stdio MCP connection.
    require(digest(home/'config.yaml')==plan['selectedConfigurationSha256'])
    module=sys.modules['onoes_mind_provider']
    providers=[]
    class Context:
        def register_memory_provider(self,provider):providers.append(provider)
    module.register(Context());require(len(providers)==1 and providers[0].is_available())
    provider=providers[0];provider.initialize('owner-cloud-readonly-qualification',hermes_home=home)
    recalled=json.loads(provider.handle_tool_call('onoes_memory',{'action':'recall','kind':'profile'}))
    require(recalled.get('ok') is True)
    meta=package.descriptor();query=dict(entry=meta['readerEntry'],profile=meta['readerProfile'],sha256=meta['readerProfileSha256'],
        query=plan['handoffQuery'],recordId=plan['handoffRecordId'],minimumRevision=plan['minimumHandoffRevision'])
    child=subprocess.run([meta['readerPython'],'-I','-B','-c',MCP_CHECK,json.dumps(query)],
        capture_output=True,timeout=50)
    if child.returncode:
        try:observation=json.loads(child.stdout)
        except (ValueError,UnicodeError):observation={'diagnostic':'unavailable'}
        if observation.get('messagesAndLocalsExcluded') is True:
            print(json.dumps({'mcpQualification':observation}),file=sys.stderr)
    require(child.returncode==0 and json.loads(child.stdout)['verified'] is True)
    held();receipt={'schema':'onoes-cloud-held-qualification/v1','planSha256':plan['gateway']['sha256'],
        'verified':True,'hostReadback':True,'clientReadback':True,'sharedMcpReadback':True,'modelCalls':0}
    save(evidence/'HELD-QUALIFICATION.json',receipt)
    return {'verified':True,'privateProviderReadback':True,'sharedMcpReadback':True,'modelCalls':0}


def run(phase,plan_path,pin,auth_path):
    context=approved(phase,plan_path,pin,auth_path)
    plan,_,_,_,_,gateway=context
    with gateway.operation_scope(plan['evidence'],plan['gateway']['sha256']):
        return _run_checked(phase,pin,context)


if __name__=='__main__':
    try:
        require(len(sys.argv)==5);result=run(*sys.argv[1:])
        if type(result) is bytes:sys.stdout.buffer.write(result);sys.stdout.buffer.flush()
        else:print(json.dumps(result,sort_keys=True),flush=True)
    except Exception as error:
        print('Cloud client operation held; preserve private custody and receipts. Do not repeat.',file=sys.stderr)
        print(json.dumps({'errorType':type(error).__name__,'frames':[
            {'file':Path(f.filename).name,'function':f.name,'line':f.lineno}
            for f in traceback.extract_tb(error.__traceback__)[-12:]],'messagesAndLocalsExcluded':True}),file=sys.stderr)
        raise SystemExit(1)
