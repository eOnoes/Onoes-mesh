"""Real gateway/S6 driver in an isolated no-network, unmounted container.

No chat/agent endpoint is called. All credentials, profiles and peer workers are
synthetic. The image's normal gateway, locks, status and service manager run.
"""
import hashlib,json,os,secrets,shlex,subprocess,sys,tempfile,time,traceback
from pathlib import Path

ROOT=None


def wait(predicate,seconds=120):
    end=time.monotonic()+seconds
    while time.monotonic()<end:
        try:
            value=predicate()
            if value:return value
        except (OSError,RuntimeError,ValueError):pass
        time.sleep(.1)
    raise AssertionError('Owned native fixture observation did not settle')


def json_read(path):
    try:return json.loads(path.read_bytes())
    except (FileNotFoundError,json.JSONDecodeError):return {}


def main(driver=None):
    global ROOT
    ROOT=Path(tempfile.mkdtemp(prefix='mesh-native-gateway-'))
    HOME=ROOT/'home';HOME.mkdir(mode=0o700)
    os.environ.update(HERMES_HOME=str(HOME),HOME=str(HOME),API_SERVER_KEY=secrets.token_hex(24),
        OPENAI_API_KEY='sk-'+secrets.token_hex(24),OPENAI_BASE_URL='http://127.0.0.1:1/v1',
        API_SERVER_PORT='8642',CI='1',NO_COLOR='1',PYTHONDONTWRITEBYTECODE='1')
    os.environ['PATH']='/command:/package/admin/s6/command:'+os.environ['PATH']
    sys.path[:0]=['/opt/hermes','/tmp/fixture']
    from hermes_constants import set_hermes_home_override
    set_hermes_home_override(HOME)
    from hermes_cli.service_manager import S6ServiceManager
    from gateway import status,drain_control
    from cloud_native_gateway import NativeGateway,GatewayHeld,digest
    (HOME/'config.yaml').write_text(json.dumps({'model':'openai/gpt-4o-mini','toolsets':[],
        'platforms':{'api_server':{'enabled':True,'extra':{'port':8642,'host':'127.0.0.1'}}},
        'agent':{'max_turns':1}}))
    (HOME/'gateway_state.json').write_text(json.dumps({'desired_state':'stopped'}))
    peerhome=HOME/'profiles/other';peerhome.mkdir(parents=True,mode=0o700)
    (peerhome/'gateway_state.json').write_text(json.dumps({'desired_state':'stopped','fixture':'preserve'}))
    tree=ROOT/'owned-scan';tree.mkdir(mode=0o700)
    for name in ('gateway-default','gateway-other'):
        directory=tree/name;directory.mkdir(mode=0o700)
        if name=='gateway-default':
            command='exec /opt/hermes/.venv/bin/python3 -B -m hermes_cli.main gateway run'
            command+=' >> '+shlex.quote(str(ROOT/'gateway.log'))+' 2>&1'
        else:command='exec /bin/sleep 10000'
        script='#!/bin/sh\nexport HERMES_S6_SUPERVISED_CHILD=1 HERMES_SUPERVISED_CHILD=1\n'
        if name=='gateway-default':
            observation="import json;from pathlib import Path;p=Path("+repr(str(HOME/'gateway_state.json'))+");v=json.loads(p.read_text());f=Path("+repr(str(ROOT/'boot-intents.jsonl'))+").open('a');f.write(json.dumps({'desired_state':v.get('desired_state')})+'\\n');f.close()"
            script+='/opt/hermes/.venv/bin/python3 -I -B -c '+shlex.quote(observation)+'\n'
        script+='cd '+shlex.quote(str(HOME))+'\n'+command+'\n'
        (directory/'run').write_text(script);(directory/'run').chmod(0o700)
        (directory/'finish').write_text('#!/bin/sh\n[ "$1" = 0 ] && exit 125\nexit 0\n')
        (directory/'finish').chmod(0o700);(directory/'down').touch()
    manager=S6ServiceManager(scandir=tree)
    scanner=subprocess.Popen(['/command/s6-svscan',str(tree)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    gate=None
    try:
        wait(lambda:all((tree/name/'supervise/control').exists() for name in ('gateway-default','gateway-other')))
        for name in ('gateway-default','gateway-other'):manager.start(name)
        def ready():
            identity=status.get_running_pid_identity_strict(HOME/'gateway.pid')
            state=status.read_runtime_status(HOME/'gateway_state.json')
            return identity if identity and state and state.get('gateway_state') in ('running','degraded') else None
        initial=wait(ready)
        peer_pid=manager._supervised_pid('gateway-other');peer_state=(peerhome/'gateway_state.json').read_bytes()
        evidence=HOME/'cloud-window-evidence';evidence.mkdir(mode=0o700)
        (evidence/'rollback').mkdir(mode=0o700)
        pins={name:digest(Path('/opt/hermes')/name) for name in (
            'gateway/status.py','gateway/drain_control.py','hermes_cli/service_manager.py',
            'gateway/run.py','gateway/run_shutdown.py','gateway/run_bootstrap.py','gateway/run_inbound.py')}
        slot_pins={name:digest(tree/'gateway-default'/name) for name in ('run','finish')}
        if driver is not None:
            # Optional composed client driver shares only this owned fixture.
            # The normal source-bound native lifecycle case remains unchanged.
            driver(root=ROOT,home=HOME,evidence=evidence,tree=tree,manager=manager,
                initial=initial,peer_pid=peer_pid,peerhome=peerhome,peer_state=peer_state,
                source_pins=pins,slot_pins=slot_pins)
            return
        gate=NativeGateway(home=HOME,evidence=evidence,window_id='synthetic-window',plan_sha256='a'*64,native_source='/opt/hermes',
            source_pins=pins,slot_pins=slot_pins,manager=manager,api_port=8642)
        # Foreign maintenance is never overwritten or cleared by this driver.
        drain_control.write_drain_request(principal='synthetic-other-owner',home=HOME,suppress_notification=True)
        marker=drain_control.drain_request_path(HOME);before=marker.read_bytes()
        try:gate.quiesce_and_stop(seconds=60)
        except GatewayHeld:pass
        else:raise AssertionError('Foreign marker accepted')
        assert marker.read_bytes()==before and manager._supervised_pid('gateway-default')==initial[0]
        assert not (evidence/'GATEWAY-STOP-ATTEMPT.json').exists()
        drain_control.clear_drain_request(home=HOME)
        wait(lambda:json_read(HOME/'gateway_state.json').get('gateway_state') in ('running','degraded'))
        # Changed service bytes cannot authorize a stop.
        run=tree/'gateway-default/run';original=run.read_bytes();run.write_bytes(original+b'#changed\n')
        try:
            try:gate.quiesce_and_stop(seconds=60)
            except GatewayHeld:pass
            else:raise AssertionError('Changed service source accepted')
            assert not marker.exists() and not (evidence/'GATEWAY-STOP-ATTEMPT.json').exists()
        finally:run.write_bytes(original)
        # Exercise the actual separate-process installer entry, not just the
        # in-process control object. This fixture tests lifecycle only; the full
        # Mind/client qualification belongs to the enclosing installer proof.
        gate.close();gate=None
        entry=Path('/tmp/fixture/cloud_gateway_entry.py')
        release_files=[HOME/'config.yaml',HOME/'fixture-home-profile.json',HOME/'fixture-reader-profile.json']
        original_config=(HOME/'config.yaml').read_bytes()
        proposed_config=json.dumps({**json.loads(original_config),'mesh_fixture_revision':1}).encode()
        for p in release_files[1:]:p.write_text('{}');p.chmod(0o600)
        pins['hermes_constants.py']=digest(Path('/opt/hermes/hermes_constants.py'))
        plan={'schema':'onoes-cloud-native-window/v1','agentId':'cyony','service':'gateway-default',
            'windowId':'synthetic-window','home':str(HOME),'evidence':str(evidence),
            'nativeSource':'/opt/hermes','scandir':str(tree),'python':str(Path(sys.executable).resolve()),
            'modelCalls':0,'sourcePins':pins,'slotPins':slot_pins,'apiPort':8642,
            'stopSeconds':30,'startSeconds':120,
            'entryPins':{p.name:digest(p) for p in (entry,Path('/tmp/fixture/cloud_native_gateway.py'))},
            'releasePins':{str(p):(hashlib.sha256(proposed_config).hexdigest() if p==HOME/'config.yaml' else digest(p)) for p in release_files},
            'originalReleasePins':{str(HOME/'config.yaml'):hashlib.sha256(original_config).hexdigest()}}
        plan_path=evidence/'PLAN.json';plan_path.write_text(json.dumps(plan));plan_path.chmod(0o600)
        pin=digest(plan_path)
        authorization=evidence/'AUTHORIZATION.json'
        auth={'schema':'onoes-cloud-native-window-authorization/v1','planSha256':pin,
            'decision':'approve_scoped_cloud_mind_window','owner':'Eddie'}
        authorization.write_text(json.dumps({**auth,'decision':'NOT_APPROVED'}));authorization.chmod(0o600)
        def phase(name,expected=0):
            done=subprocess.run([sys.executable,'-I','-B',str(entry),name,str(plan_path),pin,str(authorization)],
                capture_output=True,text=True,timeout=155)
            if done.returncode!=expected:raise AssertionError('Cloud entry failed: '+done.stderr[-1000:])
            return json.loads(done.stdout) if not done.returncode else None
        phase('stop',1)
        assert not (evidence/'GATEWAY-STOP-ATTEMPT.json').exists()
        assert manager._supervised_pid('gateway-default')==initial[0]
        authorization.write_text(json.dumps(auth))
        stopped=phase('stop')
        assert stopped['kernelRetirementConfirmed'] and phase('verify-stopped')['verified']
        (HOME/'config.yaml').write_bytes(proposed_config)
        assert marker.exists() and manager._supervised_pid('gateway-other')==peer_pid
        assert (peerhome/'gateway_state.json').read_bytes()==peer_state
        phase('release',1)
        assert not (evidence/'GATEWAY-START-ATTEMPT.json').exists() and marker.exists()
        qualification=evidence/'HELD-QUALIFICATION.json'
        qualification.write_text(json.dumps({'schema':'onoes-cloud-held-qualification/v1',
            'planSha256':pin,'verified':True,'hostReadback':True,'clientReadback':True,
            'sharedMcpReadback':True,'modelCalls':0}));qualification.chmod(0o600)
        changed=release_files[1];original=changed.read_bytes();changed.write_bytes(b'{"changed":true}')
        phase('release',1)
        assert not (evidence/'GATEWAY-START-ATTEMPT.json').exists() and marker.exists()
        changed.write_bytes(original)
        started=phase('release')
        assert phase('verify-running')['verified']
        assert started['pid']!=initial[0] and not marker.exists()
        held=phase('rehold')
        assert held['pid']==started['pid'] and phase('verify-rollback-stopped')['verified']
        phase('release-original',1)
        assert marker.exists() and not (evidence/'rollback/GATEWAY-START-ATTEMPT.json').exists()
        (HOME/'config.yaml').write_bytes(original_config)
        original_qualification=evidence/'ORIGINAL-HELD-QUALIFICATION.json'
        original_qualification.write_text(json.dumps({'schema':'onoes-cloud-original-held-qualification/v1',
            'planSha256':pin,'verified':True,'originalConfigurationReadback':True,
            'originalReleaseFilesReadback':True,'nativeGatewayRetired':True,'modelCalls':0}));original_qualification.chmod(0o600)
        restored=phase('release-original')
        assert restored['pid']!=started['pid'] and phase('verify-original-running')['verified']
        assert (HOME/'config.yaml').read_bytes()==original_config and not marker.exists()
        assert manager._supervised_pid('gateway-other')==peer_pid
        assert (peerhome/'gateway_state.json').read_bytes()==peer_state
        print(json.dumps({'nativeGateway':True,'nativeS6':True,'kernelRetirement':True,
            'foreignMarkerRefused':True,'changedSourceRefused':True,'peerUnchanged':True,
            'normalReleaseRestart':True,'coldReceiptResume':True,'ownerEntry':True,
            'unapprovedPlanRefused':True,'unqualifiedReleaseRefused':True,'changedReleaseFileRefused':True,
            'exactReleasedOwnerReheld':True,'coldOriginalRelease':True,'originalConfigRestored':True,
            'mindQualification':'SYNTHETIC_LIFECYCLE_FIXTURE_ONLY','modelCalls':0,'liveChanges':False}),flush=True)
    finally:
        if gate:gate.close()
        for name in ('gateway-default','gateway-other'):
            try:manager.stop(name)
            except Exception:pass
        try:wait(lambda:all(manager._svstat_fields(name,'up')==['false'] for name in ('gateway-default','gateway-other')),20)
        except Exception:pass
        scanner.terminate()
        try:scanner.wait(10)
        except subprocess.TimeoutExpired:scanner.kill();scanner.wait(10)


if __name__=='__main__':
    try:main()
    except BaseException as error:
        log=(ROOT/'gateway.log').read_text(errors='replace') if ROOT is not None and (ROOT/'gateway.log').exists() else 'No gateway log'
        for name in ('API_SERVER_KEY','OPENAI_API_KEY'):
            if os.environ.get(name):log=log.replace(os.environ[name],'<synthetic-key>')
        observation=json_read(ROOT/'home/cloud-window-evidence/GATEWAY-STOP-HELD.json') if ROOT is not None else {}
        print(json.dumps({'type':type(error).__name__,'frames':[{'file':Path(f.filename).name,'function':f.name,'line':f.lineno}
            for f in traceback.extract_tb(error.__traceback__)],'stopObservation':observation,'ownedGatewayLog':log[-5000:]}),flush=True)
        raise SystemExit(1)
