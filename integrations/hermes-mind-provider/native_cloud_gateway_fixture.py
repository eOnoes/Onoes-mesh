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


def main():
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
        evidence=ROOT/'evidence';evidence.mkdir(mode=0o700)
        pins={name:digest(Path('/opt/hermes')/name) for name in (
            'gateway/status.py','gateway/drain_control.py','hermes_cli/service_manager.py',
            'gateway/run.py','gateway/run_shutdown.py','gateway/run_bootstrap.py','gateway/run_inbound.py')}
        slot_pins={name:digest(tree/'gateway-default'/name) for name in ('run','finish')}
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
        stopped=gate.quiesce_and_stop(seconds=30)
        assert stopped['kernelRetirementConfirmed'] and gate.assert_stopped()
        assert marker.exists() and manager._supervised_pid('gateway-other')==peer_pid
        assert (peerhome/'gateway_state.json').read_bytes()==peer_state
        gate.close();gate=None
        binding={'home':str(HOME),'evidence':str(evidence),'window_id':'synthetic-window','plan_sha256':'a'*64,
            'native_source':'/opt/hermes','source_pins':pins,'slot_pins':slot_pins,'api_port':8642,'scandir':str(tree)}
        binding_path=ROOT/'resume-binding.json';binding_path.write_text(json.dumps(binding))
        resume=r'''
import json,sys
from pathlib import Path
sys.path[:0]=['/opt/hermes','/tmp/fixture']
data=json.loads(Path(sys.argv[1]).read_bytes());scan=data.pop('scandir')
from hermes_constants import set_hermes_home_override
set_hermes_home_override(Path(data['home']))
from hermes_cli.service_manager import S6ServiceManager
from cloud_native_gateway import NativeGateway
gate=NativeGateway.resume_stopped(manager=S6ServiceManager(scandir=Path(scan)),**data)
try:result=gate.release_and_start(seconds=120)
finally:gate.close()
Path(sys.argv[2]).write_text(json.dumps(result))
'''
        done=subprocess.run([sys.executable,'-I','-B','-c',resume,str(binding_path),str(ROOT/'RESUMED.json')],
            capture_output=True,text=True,timeout=150)
        if done.returncode:
            raise AssertionError('Cold release failed: '+done.stderr[-2000:])
        started=json_read(ROOT/'RESUMED.json')
        assert started['pid']!=initial[0] and not marker.exists()
        assert manager._supervised_pid('gateway-other')==peer_pid
        assert (peerhome/'gateway_state.json').read_bytes()==peer_state
        print(json.dumps({'nativeGateway':True,'nativeS6':True,'kernelRetirement':True,
            'foreignMarkerRefused':True,'changedSourceRefused':True,'peerUnchanged':True,
            'normalReleaseRestart':True,'coldReceiptResume':True,'modelCalls':0,'liveChanges':False}),flush=True)
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
        observation=json_read(ROOT/'evidence/GATEWAY-STOP-HELD.json') if ROOT is not None else {}
        print(json.dumps({'type':type(error).__name__,'frames':[{'file':Path(f.filename).name,'function':f.name,'line':f.lineno}
            for f in traceback.extract_tb(error.__traceback__)],'stopObservation':observation,'ownedGatewayLog':log[-5000:]}),flush=True)
        raise SystemExit(1)
