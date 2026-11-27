"""Actual TLS home/provider + dedicated MCP under the owned native gateway hold.

The canonical API fixture is an actual SDK Ledger/AgentHomeServer on loopback.
It is synthetic POSIX storage, not the Windows checkpoint authority. The latter
is qualified independently by the owned cold owner-entry test.
"""
import base64,hashlib,importlib.util,json,os,secrets,ssl,subprocess,sys,sysconfig,traceback
from datetime import datetime,timedelta,timezone
from pathlib import Path
from types import SimpleNamespace


def read(p):return json.loads(Path(p).read_bytes())
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def put(p,value):
    Path(p).write_text(json.dumps(value,sort_keys=True));Path(p).chmod(0o600)


def driver(*,root,home,evidence,tree,manager,initial,peer_pid,peerhome,peer_state,source_pins,slot_pins):
    from cloud_client_package import load_bundle,build_package,write_bundle,SDK,PLUGIN,CLIENT
    fixture=Path('/tmp/fixture')
    seed=load_bundle(fixture/'seed-client.zip',sha(fixture/'seed-client.zip'))
    bootstrap=root/'bootstrap-sdk';bootstrap.mkdir(mode=0o700)
    for name,raw in seed.files.items():
        if name.startswith(SDK+'/'):
            p=bootstrap/name.removeprefix(SDK+'/');p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(raw)
    sys.path.insert(0,str(bootstrap))
    from onoes_mind import Ledger
    from onoes_mind.agent_home import AgentHome,AgentHomeBinding,enroll_agent_home
    from onoes_mind.agent_context import AgentContextBinding,ProjectContextReader
    from onoes_mind.agent_home_http import AgentHomeServer,home_binding_sha256
    from onoes_mind.context_enrollment import enroll_context_reader
    from onoes_mind.project_context_http import ProjectReadEndpoint,context_binding_sha256
    from onoes_mind.project_tool_grant import ReviewedProjectToolGrant
    from onoes_mind.recall_binding import RecallBinding,prepare_store_identity,prepare_mesh_principal
    realm=root/'canonical-api-fixture';realm.mkdir(mode=0o700)
    ledger=Ledger(realm/'ledger.sqlite',environment_id='synthetic-cloud-client',
        audit_key=secrets.token_bytes(32),deletion_key=secrets.token_bytes(32))
    context=api=None
    try:
        store_id=prepare_store_identity(ledger,environment='synthetic-cloud-client',authority_ref='fixture:owner')
        prepare_mesh_principal(ledger,scope_id='project/onoes-mind/shared')
        info=(realm/'ledger.sqlite').stat()
        store=RecallBinding(str(realm/'ledger.sqlite'),store_id,'synthetic-cloud-client','fixture:owner',
            'project/onoes-mind/shared',info.st_dev,info.st_ino,'fixture:custodian','fixture:revoke','fixture:review')
        home_binding=AgentHomeBinding(store,'cyony');reader_binding=AgentContextBinding(store,'context-cyony','onoes-mesh')
        operator='omop1_'+secrets.token_urlsafe(32);ledger.create_principal('operator');ledger.issue_credential('operator',operator)
        context=ProjectContextReader(store.database_path,binding=reader_binding)
        grant=ReviewedProjectToolGrant(realm/'tool-grant.json',reader_binding,'fixture:cloud-client');grant.path.write_bytes(grant.document())
        api=AgentHomeServer([AgentHome(ledger,home_binding)],project_readers=[ProjectReadEndpoint(context,grant)])
        api.start();port=api._server.server_port
        # Native urllib/OpenSSL verifies a real self-signed test CA for the
        # synthetic hostname injected only into this --network=none container.
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes,serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.x509.oid import NameOID
        key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
        subject=x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,'echo.synthetic.ts.net')]);now=datetime.now(timezone.utc)
        cert=(x509.CertificateBuilder().subject_name(subject).issuer_name(subject).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now-timedelta(minutes=1)).not_valid_after(now+timedelta(hours=1))
            .add_extension(x509.BasicConstraints(ca=True,path_length=None),critical=True)
            .add_extension(x509.SubjectAlternativeName([x509.DNSName('echo.synthetic.ts.net')]),critical=False).sign(key,hashes.SHA256()))
        cert_path=realm/'test-ca.pem';key_path=realm/'test-ca-key.pem'
        cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM));cert_path.chmod(0o600)
        key_path.write_bytes(key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()));key_path.chmod(0o600)
        tls=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);tls.load_cert_chain(cert_path,key_path)
        api._server.socket=tls.wrap_socket(api._server.socket,server_side=True)
        # MCP intentionally inherits a small safe environment that excludes
        # SSL_CERT_FILE. Use this container's ephemeral STANDARD trust store,
        # keeping production TLS verification unchanged for every subprocess.
        trust=Path(ssl.get_default_verify_paths().openssl_cafile).resolve()
        assert trust==Path('/etc/ssl/cert.pem')
        trust.write_bytes(cert.public_bytes(serialization.Encoding.PEM));trust.chmod(0o600)
        os.environ.pop('SSL_CERT_FILE',None)
        os.environ['NO_PROXY']='echo.synthetic.ts.net,127.0.0.1,localhost'
        endpoint='https://echo.synthetic.ts.net:'+str(port)
        def subset(prefix):return {n.removeprefix(prefix+'/'):v for n,v in seed.files.items() if n.startswith(prefix+'/')}
        package=build_package(home=str(home),base_url=endpoint,home_binding_sha256=home_binding_sha256(home_binding),
            context_binding_sha256=context_binding_sha256(reader_binding),principal_id='context-cyony',project_id='onoes-mesh',
            python_resolved=str(Path(sys.executable).resolve()),python_sha256=sha(Path(sys.executable).resolve()),
            native_purelib=sysconfig.get_path('purelib'),sdk_files=subset(SDK),plugin_files=subset(PLUGIN),
            mcp_files=subset(CLIENT+'/vendor/mcp-1.26.0'),settings_files=subset(CLIENT+'/vendor/pydantic-settings-2.13.1'))
        bundle=evidence/'client.zip';bundle_receipt=write_bundle(package,bundle);bundle.chmod(0o600)
        original_config=(home/'config.yaml').read_bytes()
        from portable_owner_switch import proposed_settings
        import hermes_yaml as yaml
        from hermes_cli.config import atomic_config_write
        meta=package.descriptor()
        preview=root/'preview.yaml';preview.write_bytes(original_config)
        proposed=proposed_settings(SimpleNamespace(original=yaml.safe_load(original_config),
            home_profile=Path(meta['homeProfile']),home_sha256=meta['homeProfileSha256'],
            reader_profile=Path(meta['readerProfile']),reader_sha256=meta['readerProfileSha256'],
            reader_python=Path(meta['readerPython']),reader_entry=Path(meta['readerEntry'])))
        atomic_config_write(preview,proposed);selected_sha=sha(preview)
        source_pins={**source_pins,**{n:sha(Path('/opt/hermes')/n) for n in (
            'hermes_constants.py','hermes_cli/config.py','hermes_cli/config_backend.py')}}
        gate_plan={'schema':'onoes-cloud-native-window/v1','agentId':'cyony','service':'gateway-default',
            'windowId':'synthetic-client-window','home':str(home),'evidence':str(evidence),'nativeSource':'/opt/hermes',
            'scandir':str(tree),'python':str(Path(sys.executable).resolve()),'modelCalls':0,'sourcePins':source_pins,
            'slotPins':slot_pins,'apiPort':8642,'stopSeconds':30,'startSeconds':120,
            'entryPins':{n:sha(fixture/n) for n in ('cloud_gateway_entry.py','cloud_native_gateway.py')},
            'releasePins':{str(home/'config.yaml'):selected_sha,meta['homeProfile']:meta['homeProfileSha256'],meta['readerProfile']:meta['readerProfileSha256']},
            'originalReleasePins':{str(home/'config.yaml'):hashlib.sha256(original_config).hexdigest()}}
        gate_path=evidence/'GATEWAY-PLAN.json';put(gate_path,gate_plan);gate_pin=sha(gate_path)
        gate_auth=evidence/'GATEWAY-AUTHORIZATION.json';put(gate_auth,{'schema':'onoes-cloud-native-window-authorization/v1',
            'planSha256':gate_pin,'decision':'approve_scoped_cloud_mind_window','owner':'Eddie'})
        def gateway(phase,expected=0):
            done=subprocess.run([sys.executable,'-I','-B',str(fixture/'cloud_gateway_entry.py'),phase,str(gate_path),gate_pin,str(gate_auth)],
                capture_output=True,timeout=160)
            if done.returncode!=expected:
                from gateway import status
                value=status.read_runtime_status(home/'gateway_state.json') or {}
                observation={k:value.get(k) for k in ('pid','desired_state','gateway_state','active_agents','updated_at')}
                observation['supervisor']=manager._svstat_fields('gateway-default','up','pid','wantedup','exitcode','signum')
                print(json.dumps({'nativeGatewayObservation':observation,'phase':phase}),flush=True)
                raise AssertionError('Owned gateway entry held: '+done.stderr.decode()[-1800:])
            return json.loads(done.stdout) if not expected else None
        # Saved native files are synthetic; contents never leave the container.
        notes=home/'memories';notes.mkdir(mode=0o700,exist_ok=True)
        assert notes.resolve()==notes and {p.name for p in notes.iterdir()}<={'MEMORY.md','USER.md'}
        for name,text in [('MEMORY.md','Synthetic measured print design version seven.'),('USER.md','Prefer short progress updates.')]:
            p=notes/name;p.write_text(text);p.chmod(0o600)
        def identity(s):return [s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns]
        identities={p.name:identity(p.stat()) for p in notes.iterdir()}
        originals={p.name:p.read_bytes() for p in notes.iterdir()}
        document={'author':'nims','revision':24,'handoff_id':'nims/onoes-mesh/cloudclienthandoff',
            'next_action':'Review synthetic printer dimensions'}
        handoff=ledger.remember(operator,{'event_id':'cloudclienthandoff','kind':'project_fact','project_id':'onoes-mesh',
            'requested_visibility':'shared','claim':json.dumps(document),'source_class':'agent_handoff',
            'evidence_refs':[{'type':'fixture','ref':'nims:cloudclienthandoff@24','content_hash':'a'*64}]})
        executors={n:sha(fixture/n) for n in ('cloud_client_entry.py','cloud_gateway_entry.py','cloud_native_gateway.py',
            'cloud_client_package.py','cloud_curated_transfer.py','cloud_custody_delivery.py','portable_owner_switch.py','owner_profile_switch.py')}
        client_plan={'schema':'onoes-cloud-client-operation/v1','agentId':'cyony','readerPrincipal':'context-cyony','sharedProject':'onoes-mesh',
            'home':str(home),'evidence':str(evidence),'endpoint':endpoint,'executors':executors,
            'gateway':{'planPath':str(gate_path),'sha256':gate_pin,'authorizationPath':str(gate_auth)},
            'bundlePath':str(bundle),'bundleSha256':bundle_receipt['sha256'],'curatedSourceIdentities':identities,
            'configurationBeforeSha256':hashlib.sha256(original_config).hexdigest(),'selectedConfigurationSha256':selected_sha,
            'handoffQuery':'cloudclienthandoff','handoffRecordId':handoff['record_id'],'minimumHandoffRevision':24}
        client_path=evidence/'CLIENT-PLAN.json';put(client_path,client_plan);client_pin=sha(client_path)
        client_auth=evidence/'CLIENT-AUTHORIZATION.json';put(client_auth,{'schema':'onoes-cloud-client-operation-authorization/v1',
            'owner':'Eddie','decision':'approve_cyony_private_home_and_mesh_reader','planSha256':client_pin})
        def client(phase,stdin=None,expected=0,backend=None):
            environment=None if backend is None else {**os.environ,'HERMES_CONFIG_BACKEND':backend}
            done=subprocess.run([sys.executable,'-I','-B',str(fixture/'cloud_client_entry.py'),phase,str(client_path),client_pin,str(client_auth)],
                input=stdin,capture_output=True,timeout=80,env=environment)
            if done.returncode!=expected:raise AssertionError('Owned client entry held: '+done.stderr.decode()[-1800:])
            if expected:return None
            return done.stdout if phase=='export-curated' else json.loads(done.stdout)
        print('Cloud client fixture: native stop and public materialization',flush=True)
        assert gateway('stop')['verified']
        import fcntl
        lock=os.open(evidence/'WINDOW-OPERATION.lock',os.O_RDWR)
        try:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            client('materialize',expected=1);gateway('rehold',expected=1)
            assert not (evidence/'MATERIALIZE-ATTEMPT.json').exists()
        finally:fcntl.flock(lock,fcntl.LOCK_UN);os.close(lock)
        assert client('restore')['configurationUntouched']
        assert not (evidence/'MATERIALIZED.json').exists()
        assert client('materialize')['publicCodeOnly']
        assert not ledger.db.execute("SELECT 1 FROM principals WHERE principal_id='cyony'").fetchone()
        captured=client('capture');transport=client('export-curated')
        assert hashlib.sha256(transport).hexdigest()==captured['transportSha256']
        assert (home/'config.yaml').read_bytes()==original_config
        # Same supported SDK enrollment as the Windows owner operation; plain
        # synthetic custody here qualifies delivery, not Windows DPAPI custody.
        tokens={}
        enroll_agent_home(ledger,home_binding,operator_token=operator,save_new_token=lambda t:tokens.setdefault('home',t) is not None)
        enroll_context_reader(ledger,reader_binding,operator_token=operator,save_new_token=lambda t:tokens.setdefault('reader',t) is not None)
        payload=json.dumps({'homeToken':tokens['home'],'readerToken':tokens['reader'],
            'intentKeyBase64':base64.b64encode(secrets.token_bytes(32)).decode()}).encode()
        assert client('deliver',payload)['custodyReadback']
        client('select',expected=1,backend='sqlite')
        assert not (evidence/'CONFIG-ATTEMPT.json').exists() and (home/'config.yaml').read_bytes()==original_config
        assert client('select')['verified']
        print('Cloud client fixture: native provider TLS and dedicated MCP qualification',flush=True)
        assert client('qualify-held')['sharedMcpReadback'];assert gateway('release')['verified']
        assert gateway('verify-running')['verified']
        assert json.loads((root/'boot-intents.jsonl').read_text().splitlines()[-1])['desired_state']=='running'
        # The scoped rollback reholds exactly that started actor. Restore is a
        # real portable configuration rollback; no new entry/custody is deleted.
        assert gateway('rehold')['verified'];assert client('restore')['originalConfigurationRestored']
        assert (home/'config.yaml').read_bytes()==original_config
        qualification={'schema':'onoes-cloud-held-qualification/v1','planSha256':gate_pin,'verified':True,
            'hostReadback':True,'clientReadback':True,'sharedMcpReadback':True,'modelCalls':0}
        # New-connection proof is not proof of the original native selection.
        put(evidence/'ORIGINAL-HELD-QUALIFICATION.json',qualification)
        gateway('release-original',expected=1)
        assert not (evidence/'rollback/GATEWAY-START-ATTEMPT.json').exists()
        (evidence/'ORIGINAL-HELD-QUALIFICATION.json').rename(evidence/'REJECTED-NEW-PROOF-AS-ORIGINAL.json')
        assert client('qualify-original-held')['originalConfigurationReadback']
        assert 'sharedMcpReadback' not in read(evidence/'ORIGINAL-HELD-QUALIFICATION.json')
        assert gateway('release-original')['verified'];assert gateway('verify-original-running')['verified']
        assert json.loads((root/'boot-intents.jsonl').read_text().splitlines()[-1])['desired_state']=='running'
        assert manager._supervised_pid('gateway-other')==peer_pid and (peerhome/'gateway_state.json').read_bytes()==peer_state
        assert all((notes/n).read_bytes()==raw for n,raw in originals.items())
        print(json.dumps({'passed':True,'actualTlsSdkApi':True,'actualPortableProvider':True,'actualDedicatedMcp':True,
            'publicCodeBeforeCredentials':True,'curatedOnlyTransfer':True,'nativeGatewayReleaseAndRollback':True,
            'originalConfigurationRestored':True,'peerUnchanged':True,'modelCalls':0,'liveChanges':False,
            'concurrentWindowActorRefused':True,'defaultTlsTrustVerified':True,
            'nonFileBackendRefusedBeforeSelection':True,
            'runningIntentObservedBeforeBothBoots':True,
            'originalQualificationHasNoNewMindClaim':True,
            'hostStorage':'SYNTHETIC_POSIX_LEDGER_NOT_WINDOWS_CHECKPOINT_HOST'}),flush=True)
    finally:
        if api is not None:api.close()
        if context is not None:context.close()
        ledger.close()


if __name__=='__main__':
    try:
        sys.path[:0]=['/tmp/fixture','/opt/hermes']
        import native_cloud_gateway_fixture as native
        native.main(driver=driver)
    except Exception as error:
        print(json.dumps({'errorType':type(error).__name__,'frames':[
            {'file':Path(f.filename).name,'function':f.name,'line':f.lineno}
            for f in traceback.extract_tb(error.__traceback__)],'messagesAndLocalsExcluded':True}),flush=True)
        # Assertion text is limited to child credential-free lifecycle reports.
        if isinstance(error,AssertionError):print(str(error),flush=True)
        raise SystemExit(1)
