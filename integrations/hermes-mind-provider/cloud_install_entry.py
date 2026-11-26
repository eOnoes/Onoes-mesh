"""Owner-approved finite cloud enrollment, using the existing native controls.

Inactive on import. No agent/model calls, scheduler, PC restart, retry or direct
database writes. Source/runtime swaps happen only after authoritative retirement;
unknown transport or partial actor startup holds before revocation/restoration.
"""
from copy import deepcopy
import base64,hashlib,importlib.util,json,os,re,secrets,subprocess,sys,traceback
from pathlib import Path

DECISION='approve_cyony_private_home_and_mesh_reader'
TASK='ONOes Mesh Workroom Recovery'


class InstallHeld(RuntimeError):pass


def require(ok):
    if not ok:raise InstallHeld('Cloud installation held; retain the exact owner window and native receipts')


def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    path=Path(path);require(path.is_absolute() and path.resolve(strict=True)==path and path.stat().st_size<=1048576)
    def unique(pairs):
        result={}
        for key,value in pairs:require(key not in result);result[key]=value
        return result
    value=json.loads(path.read_bytes(),object_pairs_hook=unique);require(type(value) is dict)
    return value


def save(path,value,*,raw=False):
    from onoes_mind.enrollment_store import qualify_private_storage
    path=Path(path);qualify_private_storage(path.parent)
    body=value if raw else json.dumps(value,sort_keys=True,allow_nan=False).encode()
    with path.open('xb') as stream:stream.write(body);stream.flush();os.fsync(stream.fileno())
    qualify_private_storage(path,kind='file')


def load(path,name,pin):
    path=Path(path);require(path.resolve(strict=True)==path and digest(path)==pin)
    spec=importlib.util.spec_from_file_location(name,path)
    module=importlib.util.module_from_spec(spec);sys.modules[name]=module;spec.loader.exec_module(module)
    return module


def approved_inputs(path,pin,authorization):
    """Validate the complete source and owner contract before SDK or helper imports."""
    require(os.name=='nt' and sys.flags.isolated==1 and sys.dont_write_bytecode
        and type(pin) is str and re.fullmatch('[a-f0-9]{64}',pin) and digest(path)==pin)
    plan=read(path)
    require(read(authorization)=={'schema':'onoes-cloud-install-authorization/v1','owner':'Eddie',
        'decision':DECISION,'planSha256':pin})
    require(plan['schema']=='onoes-cloud-install-window/v1' and plan['agentId']=='cyony'
        and plan['readerPrincipal']=='context-cyony' and plan['sharedProject']=='onoes-mesh'
        and type(plan['modelCalls']) is int and plan['modelCalls']==0
        and plan['maintenanceTask']==TASK)
    sdk=Path(plan['sdk']);workspace=Path(plan['workspace']);python=Path(plan['python'])
    require(all(p.is_absolute() and p.resolve(strict=True)==p for p in (sdk,workspace,python))
        and Path(sys.executable).resolve()==python and digest(python)==plan['pythonSha256'])
    required={Path(__file__).with_name(n) for n in ('cloud_install_entry.py','cloud_install_window.py',
        'cloud_phase_runner.py','cloud_windows_task.py','cloud_source_selection.py','private_mind_route.py')}
    required.update((sdk/'onoes_mind').rglob('*.py'));required.update((sdk/'onoes_mind/migrations').glob('*.sql'))
    core=workspace/'integrations'
    require(plan['core']['rolesPath']==str(core/'mind-recovery-candidate/recall_process_candidate.py')
        and plan['core']['launcherModulePath']==str(core/'mesh_launcher_window.py'))
    required.update(Path(plan['core'][k]) for k in ('rolesPath','launcherModulePath','atomicModulePath'))
    require(sdk/'onoes_mind/__init__.py' in required and all(str(p) in plan['sourcePins'] for p in required))
    for filename,expected in plan['sourcePins'].items():
        p=Path(filename);require(p.is_absolute() and p.resolve(strict=True)==p and digest(p)==expected)
    sys.path[:0]=[str(Path(__file__).parent),str(sdk)]
    import onoes_mind
    require(Path(onoes_mind.__file__).resolve().parents[1]==sdk)
    from onoes_mind.enrollment_store import qualify_private_storage
    for item in (path,authorization):qualify_private_storage(Path(item),kind='file')
    require(set(plan['evidence'])=={'journal','transport','task','source','windows','owner','private'})
    for item in plan['evidence'].values():qualify_private_storage(Path(item))
    locations=list(map(Path,plan['evidence'].values()))
    require(len(set(locations))==len(locations) and all(not list(p.iterdir()) for p in locations
        if p!=Path(plan['evidence']['private'])))
    # A stopped earlier test is not inferred from an absent local SSH process.
    retirement=plan['remoteTestRetirement']
    require(digest(retirement['path'])==retirement['sha256'])
    known=read(retirement['path']);require(known.get('remaining')==0 and known.get('verified') is True)
    return plan


class CombinedWindow:
    def __init__(self,plan,pin,authorization):
        from cloud_phase_runner import NativePhases
        from cloud_windows_task import Binding,TaskWindow
        import cloud_source_selection as selection
        import private_mind_route as routes
        self.plan=plan;self.pin=pin;self.execution=deepcopy(plan)
        self.root={k:Path(v) for k,v in plan['evidence'].items()}
        self.phase=NativePhases(self.execution,pin,authorization,self.root['transport'])
        self.task=TaskWindow(Binding(**plan['taskBinding']),self.root['task'])
        self.selection=selection;self.routes=routes
        core=plan['core'];pins=plan['sourcePins']
        self.roles=load(core['rolesPath'],'cloud_window_unchanged_roles',pins[core['rolesPath']])
        self.launcher=load(core['launcherModulePath'],'cloud_window_unchanged_launcher',pins[core['launcherModulePath']])
        self.atomic=load(core['atomicModulePath'],'cloud_window_original_atomic',pins[core['atomicModulePath']])
        self.windows_body=read(plan['windows']['templatePath'])
        self.owner_body=read(plan['owner']['planPath'])
        self.before_route=read(plan['route']['beforePath'])
        self.proposed_route=routes.prepare(self.before_route,hostname=plan['route']['hostname'],
            expected_sha256=plan['route']['beforeSha256'])
        source=plan['sourceSelection'];replacements={}
        for target,item in source['replacements'].items():
            raw=Path(item['afterPath']).read_bytes();require(hashlib.sha256(raw).hexdigest()==item['afterSha256'])
            replacements[target]={**item,'after':raw}
        self.changes=selection.prepare(workspace=plan['workspace'],wrapper=source['wrapper'],replacements=replacements,
            original_startup=source['originalStartup'],original_sha256=source['originalStartupSha256'],
            new_startup=source['newStartup'],new_sha256=source['newStartupSha256'],
            expected_wrapper_sha256=source['wrapperSha256'])

    def preflight(self,pin,evidence):
        require(pin==self.pin and Path(evidence)==self.root['journal'])
        b=self.task.binding;state=self.task.status()
        require(b.task_name==TASK and b.task_path=='\\' and state['definitionSha256']==b.original_sha256
            and state['otherDefinitionSha256']==b.other_sha256 and state['enabled']==b.original_enabled)
        w=self.plan['windows'];require(digest(w['templatePath'])==w['templateSha256']
            and not os.path.lexists(w['planPath']) and not os.path.lexists(w['authorizationPath']))
        require(self.windows_body['schema']=='onoes-cloud-windows-phases/v1'
            and self.windows_body['workspace']==self.plan['workspace'] and self.windows_body['agentId']=='cyony'
            and self.windows_body['evidence']==str(self.root['windows'])
            and self.windows_body['maintenance']['powershell']==b.powershell
            and self.windows_body['maintenance']['powershellSha256']==b.powershell_sha256)
        require(digest(self.plan['owner']['planPath'])==self.plan['owner']['planSha256']
            and self.owner_body['evidence']==str(self.root['owner']))
        for value in (self.plan['windows'],self.plan['owner']):
            require(digest(value['entryPath'])==value['entrySha256'])
        owner_auth=read(self.plan['owner']['authorizationPath'])
        require(owner_auth=={'schema':'onoes-cloud-owner-operation-authorization/v1','owner':'Eddie',
            'decision':DECISION,'planSha256':self.plan['owner']['planSha256']})
        for which in ('before','after'):
            value=self.plan['backups'][which]
            require(digest(value['entryPath'])==value['entrySha256']
                and digest(value['profilePath'])==value['profileSha256']
                and digest(value['approvalPath'])==value['approvalSha256'])
            profile=read(value['profilePath'])
            require(profile['archiveCredentialMode']=='windows-local'
                and profile['resultPath']==value['resultPath']
                and not os.path.lexists(profile['resultPath']) and not os.path.lexists(profile['attemptPath']))
        operator=read(self.owner_body['operator']['path'])['binding']
        require(all(self.plan['canonicalBinding'][k]==operator[k] for k in (
            'database_path','store_id','environment','authority_ref','file_device','file_inode')))
        writer=self.owner_body['writer']
        require(digest(writer['path'])==writer['sha256'])
        service=read(writer['path'])
        homes=[r for r in service['agentHomeBindings'] if r['agent_id']=='cyony']
        readers=[r['binding'] for r in service['projectReaderBindings']
            if r['binding']['principal_id']=='context-cyony' and r['binding']['project_id']=='onoes-mesh']
        require(len(homes)==len(readers)==1 and homes[0]['store']==readers[0]['store'])
        require(all(homes[0]['store'][k]==operator[k] for k in (
            'database_path','store_id','environment','authority_ref','file_device','file_inode')))
        for target,item in self.plan['sourceSelection']['replacements'].items():
            require(self.windows_body['old']['sourcePins'][target]==item['beforeSha256']
                and self.windows_body['new']['sourcePins'][target]==item['afterSha256']
                and self.owner_body['sourcePins'][target]==item['afterSha256'])
        require(not any(os.path.lexists(self.root['private']/name) for name in (
            'WINDOWS-PLAN-DERIVATION.json','NEW-CLIENT-INTENT.dpapi','ROUTE-ADD-ATTEMPT.json','WINDOW-FINALIZED.json')))
        require(not os.path.lexists(self.owner_body['curatedTransport'])
            and not os.path.lexists(self.owner_body['curatedCaptureReceipt']))
        # The known old public receipt is retained by the native cutover, never
        # replaced on the strength of an HTTP response or local PID alone.
        require(digest(Path(self.plan['workspace']).parent/'workroom-ab-preview-process.json')
            ==self.windows_body['originalOwnerSha256'])
        require(self.routes.fingerprint(self.route_status())==self.routes.fingerprint(self.before_route))
        return True

    def windows(self,phase,label):return self.phase.local('windows',phase,label=label)
    def gateway(self,phase,label):return self.phase.remote('gateway',phase,label=label)
    def client(self,phase,label,stdin=None):return self.phase.remote('client',phase,label=label,stdin=stdin)

    def quiesce_gateway(self):
        require(self.gateway('stop','gateway-initial-stop')['verified'] is True)
        result=self.task.pause();require(result['readyForCutover'] is True)
        body=deepcopy(self.windows_body)
        body['maintenance']['disabledDefinitionSha256']=result['definitionSha256']
        # The sole dynamic child-plan change is the exact post-pause task XML
        # hash, derived from the reviewed original + unchanged-other-settings.
        value=self.execution['windows'];save(value['planPath'],body);child_pin=digest(value['planPath'])
        save(value['authorizationPath'],{'schema':'onoes-cloud-windows-authorization/v1','owner':'Eddie',
            'decision':'approve_scoped_cloud_mind_window','planSha256':child_pin})
        value['planSha256']=child_pin
        save(self.root['private']/'WINDOWS-PLAN-DERIVATION.json',{'masterPlanSha256':self.pin,
            'templateSha256':value['templateSha256'],'disabledDefinitionSha256':result['definitionSha256'],
            'childPlanSha256':child_pin,'onlyChangedField':'maintenance.disabledDefinitionSha256'})
        require(self.windows('inspect-old','windows-inspect-old')['ownerSha256']==body['originalOwnerSha256'])
        return {'verified':True}

    def retire_windows(self):return self.windows('retire-old','windows-retire-old')

    def backup_before(self):
        result=self.phase.backup('before',label='backup-before');require(result['archiveRehearsal']=='PASS')
        return {'verified':True}

    def materialize_client(self):return self.client('materialize','client-public-materialize')

    def capture_curated(self):
        receipt=self.client('capture','client-curated-capture')
        raw=self.client('export-curated','client-curated-export');require(type(raw) is bytes
            and hashlib.sha256(raw).hexdigest()==receipt['transportSha256'])
        require(receipt['approvedSourceIdentities']==self.owner_body['curatedSourceIdentities'])
        save(self.owner_body['curatedTransport'],raw,raw=True)
        save(self.owner_body['curatedCaptureReceipt'],receipt)
        return {'verified':True}

    def assert_retired(self,window):
        window.assert_held();require(not window.abandoned);self.task.assert_paused()
        workspace=Path(self.plan['workspace']);require(not os.path.lexists(workspace.parent/'workroom-ab-preview-process.json'))
        for label in ('old','new'):
            attempt=self.root['windows']/(label+'-retire-ATTEMPT.json')
            if label=='new' and not (self.root['windows']/'new-start-ATTEMPT.json').exists():continue
            value=read(attempt);result=read(self.root['windows']/(label+'-retire-RESULT.json'))
            require(result['verified'] is True and result['ownerSha256']==value['ownerSha256']
                and digest(self.root['windows']/(label+'-owner.json'))==value['ownerSha256'])
            actors=[value,*value['peers'].values()]
            require(all(not self.roles.same_process_alive(a['pid'],a['creationTicks']) for a in actors))
        return True

    def install_source(self):
        with self.launcher.MeshLauncherWindow(self.plan['workspace'],self.plan['launcherSha256']) as window:
            return self.selection.install(self.changes,evidence=self.root['source'],atomic_replace=self.atomic.atomic_replace,
                assert_quiescent=lambda:self.assert_retired(window))

    def admit_cyony(self):return self.phase.local('owner','admit',label='owner-admit')

    def backup_after(self):
        result=self.phase.backup('after',label='backup-after');require(result['archiveRehearsal']=='PASS')
        return {'verified':True}

    def route_status(self):
        value=self.plan['route'];exe=Path(value['executable'])
        require(exe.is_absolute() and exe.resolve(strict=True)==exe and digest(exe)==value['executableSha256'])
        done=subprocess.run([str(exe),'serve','status','--json'],stdin=subprocess.DEVNULL,capture_output=True,
            timeout=25,creationflags=subprocess.CREATE_NO_WINDOW)
        require(done.returncode==0 and len(done.stdout)<=262144)
        result=json.loads(done.stdout);require(type(result) is dict);return result

    def route_command(self,which):
        exe=Path(self.plan['route']['executable'])
        require(exe.resolve(strict=True)==exe and digest(exe)==self.plan['route']['executableSha256'])
        args=self.routes.commands()[which]
        done=subprocess.run([self.plan['route']['executable'],*args[1:]],stdin=subprocess.DEVNULL,
            capture_output=True,timeout=30,creationflags=subprocess.CREATE_NO_WINDOW)
        require(done.returncode==0)

    def start_windows(self):
        result=self.windows('start-new','windows-start-new');require(result['verified'] is True)
        require(self.routes.fingerprint(self.route_status())==self.routes.fingerprint(self.before_route))
        save(self.root['private']/'ROUTE-ADD-ATTEMPT.json',{'masterPlanSha256':self.pin,'automaticRetry':False})
        self.route_command('add')
        require(self.routes.fingerprint(self.route_status())==self.routes.fingerprint(self.proposed_route))
        save(self.root['private']/'ROUTE-ADDED.json',{'verified':True,'privateOnly':True})
        return {'verified':True}

    def deliver_client(self):
        from onoes_mind.recall_binding import RecallBinding
        from onoes_mind.agent_home import AgentHomeBinding,WindowsAgentHomeCustody
        from onoes_mind.agent_context import AgentContextBinding
        from onoes_mind.context_host import WindowsReaderCustody
        from onoes_mind.runtime_keys import _crypt
        require(read(self.root['owner']/'ADMITTED.json')['state']=='admitted')
        # Custody entropy includes the complete enrolled binding, not just the
        # database identity. Reuse the exact native service rows; operator
        # metadata can refer to the same DB with a different review reference.
        writer=self.owner_body['writer'];require(digest(writer['path'])==writer['sha256'])
        profile=read(writer['path'])
        homes=[r for r in profile['agentHomeBindings'] if r['agent_id']=='cyony']
        readers=[r['binding'] for r in profile['projectReaderBindings']
            if r['binding']['principal_id']=='context-cyony' and r['binding']['project_id']=='onoes-mesh']
        require(len(homes)==len(readers)==1 and homes[0]['store']==readers[0]['store'])
        store=RecallBinding(**homes[0]['store'])
        private=WindowsAgentHomeCustody(Path(self.owner_body['privateCustody']),AgentHomeBinding(store,'cyony'))
        shared=WindowsReaderCustody(Path(self.owner_body['sharedCustody']),AgentContextBinding(store,'context-cyony','onoes-mesh'))
        key=secrets.token_bytes(32);entropy=hashlib.sha256(('onoes-cloud-intent-key/v1\0'+self.pin).encode()).digest()
        sealed=_crypt(key,entropy,protect=True)
        save(self.root['private']/'NEW-CLIENT-INTENT.dpapi',sealed,raw=True)
        require(_crypt((self.root['private']/'NEW-CLIENT-INTENT.dpapi').read_bytes(),entropy,protect=False)==key)
        payload=json.dumps({'homeToken':private.read(),'readerToken':shared.read(),
            'intentKeyBase64':base64.b64encode(key).decode()}).encode()
        try:return self.client('deliver','client-credential-delivery',payload)
        finally:key=payload=sealed=None

    def select_configuration(self):return self.client('select','client-configuration-select')

    def qualify_held(self):
        require(self.windows('inspect-new','windows-inspect-new-held')['verified'] is True)
        return self.client('qualify-held','client-qualify-held')

    def release_gateway(self):return self.gateway('release','gateway-new-release')

    def qualify_running(self):
        require(self.windows('inspect-new','windows-inspect-new-running')['verified'] is True)
        return self.gateway('verify-running','gateway-new-running')

    def hold_for_rollback(self):
        # A lost command acknowledgement must be reconciled, not compensated
        # by acting over a possibly still active source/credential writer.
        require(not list(self.root['transport'].glob('*-TRANSPORT-UNKNOWN.json')))
        require(self.gateway('rehold','gateway-rollback-hold')['verified'] is True)
        self.task.assert_paused()
        started=self.root['windows']/'new-start-ATTEMPT.json'
        if started.exists():
            require((self.root['windows']/'new-start-RESULT.json').exists())
            require(not (self.root['windows']/'new-retire-ATTEMPT.json').exists())
            require(self.windows('retire-new','windows-retire-new')['verified'] is True)
        if (self.root['windows']/'old-retire-ATTEMPT.json').exists():
            with self.launcher.MeshLauncherWindow(self.plan['workspace'],self.plan['launcherSha256']) as window:
                self.assert_retired(window)
        else:
            require(not (self.root['source']/'SOURCE-SELECTION-ATTEMPT.json').exists())
            require(self.windows('inspect-old','windows-inspect-never-retired')['verified'] is True)
        return {'verified':True}

    def revoke_new_access(self):
        if (self.root['owner']/'ADMIT-ATTEMPT.json').exists():
            return self.phase.local('owner','revoke',label='owner-new-access-revoke')
        require(not (self.root['owner']/'ADMITTED.json').exists())
        require(not (Path(self.owner_body['privateCustody'])/'agent-home.dpapi').exists()
            and not (Path(self.owner_body['sharedCustody'])/'context-reader.dpapi').exists())
        return {'verified':True,'newAccessNeverAttempted':True}

    def restore_configuration(self):return self.client('restore','client-original-configuration')

    def restore_windows(self):
        route_attempt=self.root['private']/'ROUTE-ADD-ATTEMPT.json'
        current=self.route_status()
        host=self.routes.target(self.plan['route']['hostname'])
        require(current.get('AllowFunnel',{}).get(host,False) is False
            and current.get('TCP',{}).get('8453')=={'HTTPS':True}
            and current.get('Web',{}).get(host,{}).get('Handlers',{}).get('/')=={'Proxy':self.routes.MESH_PROXY})
        if route_attempt.exists() and self.routes.fingerprint(current)!=self.routes.fingerprint(self.before_route):
            expected=self.routes.rollback(current,original=self.before_route,proposed=self.proposed_route,
                hostname=self.plan['route']['hostname'])
            save(self.root['private']/'ROUTE-REMOVE-ATTEMPT.json',{'automaticRetry':False})
            self.route_command('remove');require(self.route_status()==expected)
        if not (self.root['windows']/'old-retire-ATTEMPT.json').exists():
            return {'verified':True,'windowsNeverRetired':True}
        with self.launcher.MeshLauncherWindow(self.plan['workspace'],self.plan['launcherSha256']) as window:
            self.selection.restore(evidence=self.root['source'],atomic_replace=self.atomic.atomic_replace,
                assert_quiescent=lambda:self.assert_retired(window))
        require(self.windows('restore-original','windows-original-owner-beforeimage')['verified'] is True)
        return self.windows('start-original','windows-original-start')

    def qualify_original_held(self):
        require(self.windows('inspect-old','windows-original-inspect-held')['verified'] is True)
        return self.client('qualify-original-held','client-original-qualify-held')

    def release_original_gateway(self):return self.gateway('release-original','gateway-original-release')

    def qualify_original_running(self):
        require(self.windows('inspect-old','windows-original-inspect-running')['verified'] is True)
        return self.gateway('verify-original-running','gateway-original-running')


def main():
    require(len(sys.argv)==4)
    path,pin,auth=sys.argv[1:];plan=approved_inputs(path,pin,auth)
    from cloud_install_window import install_once
    adapter=CombinedWindow(plan,pin,read(auth))
    result=install_once(adapter,plan['evidence']['journal'],pin)
    # Re-enable the original recovery trigger only after either complete new
    # health or complete original health. A failure here holds this final stage
    # instead of launching a second source/credential rollback over healthy apps.
    adapter.task.restore()
    save(Path(plan['evidence']['private'])/'WINDOW-FINALIZED.json',{'verified':True,
        'originalRecoveryTaskSettingRestored':True,'installed':result['installed'],'restored':result['restored']})
    print(json.dumps(result),flush=True)


if __name__=='__main__':
    try:main()
    except Exception as error:
        print('Cloud installation held; preserve private custody, native receipts and the original window. Do not rerun.',file=sys.stderr)
        print(json.dumps({'errorType':type(error).__name__,'frames':[
            {'file':Path(f.filename).name,'function':f.name,'line':f.lineno}
            for f in traceback.extract_tb(error.__traceback__)[-12:]],'messagesAndLocalsExcluded':True}),file=sys.stderr)
        raise SystemExit(1)
