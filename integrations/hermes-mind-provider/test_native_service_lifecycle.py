"""Real native service-manager lifecycle in a disposable s6 supervision tree."""
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import time

import pytest

sys.path.insert(0,os.environ['HERMES_SOURCE'])
from hermes_constants import set_hermes_home_override,reset_hermes_home_override

pytestmark=pytest.mark.skipif(os.name!='posix',reason='Actual Linux s6 service lifecycle')


WORKER=r'''
import json,os,signal,sys,time
from pathlib import Path
sys.path.insert(0,'/opt/hermes')
from gateway.status import planned_stop_marker_targets_self
root=Path(sys.argv[1]);stopping=False
def stop(signum,frame):
 global stopping
 stopping=True
signal.signal(signal.SIGTERM,stop)
(root/'ready.json').write_text(json.dumps({'pid':os.getpid()}))
while not stopping:time.sleep(.01)
(root/'term-seen').write_text('yes')
while not (root/'allow-exit').exists():time.sleep(.01)
(root/'terminal.json').write_text(json.dumps({'pid':os.getpid(),'clean':True,'planned':planned_stop_marker_targets_self()}))
'''


def wait_for(predicate,seconds=8):
    deadline=time.monotonic()+seconds
    while time.monotonic()<deadline:
        if predicate():return
        time.sleep(.02)
    raise AssertionError('Owned synthetic service did not reach its expected state')


def document(path):
    try:return json.loads(path.read_bytes())
    except (FileNotFoundError,json.JSONDecodeError):return {}


def test_native_stop_is_request_until_exact_service_exits_and_other_profile_survives(tmp_path,monkeypatch):
    from hermes_cli.service_manager import S6ServiceManager
    from gateway.status import _get_planned_stop_marker_path
    home=tmp_path/'home';home.mkdir(mode=0o700)
    peerhome=home/'profiles/other';peerhome.mkdir(parents=True,mode=0o700)
    for folder in (home,peerhome):
        (folder/'gateway_state.json').write_text(json.dumps({'desired_state':'stopped','fixture_field':'keep'}))
    monkeypatch.setenv('HERMES_HOME',str(home))
    token=set_hermes_home_override(home)
    scanroot=tmp_path/'owned-scan';scanroot.mkdir(mode=0o700)
    worker=tmp_path/'worker.py';worker.write_text(WORKER)
    roots={}
    for name,profilehome in [('gateway-default',home),('gateway-other',peerhome)]:
        service=scanroot/name;service.mkdir(mode=0o700)
        root=tmp_path/name;root.mkdir(mode=0o700);roots[name]=root
        run=service/'run'
        run.write_text('#!/bin/sh\nexport HERMES_HOME='+shlex.quote(str(profilehome))+'\nexec '
            +shlex.quote(sys.executable)+' -I -B '+shlex.quote(str(worker))+' '+shlex.quote(str(root))
            +' >> '+shlex.quote(str(root/'worker.log'))+' 2>&1\n')
        run.chmod(0o700)
        (service/'down').touch()
    assert _get_planned_stop_marker_path().is_relative_to(home)
    manager=S6ServiceManager(scandir=scanroot)
    scannerlog=(tmp_path/'scanner.log').open('wb')
    scanner=subprocess.Popen(['/command/s6-svscan',str(scanroot)],stdout=scannerlog,stderr=subprocess.STDOUT)
    try:
        wait_for(lambda:(scanroot/'gateway-default/supervise/control').exists())
        for name in roots:manager.start(name)
        try:wait_for(lambda:all(document(root/'ready.json').get('pid') for root in roots.values()))
        except AssertionError:
            output={name:(root/'worker.log').read_text()[-1500:] if (root/'worker.log').exists() else 'worker did not open log' for name,root in roots.items()}
            output['scanner']=(tmp_path/'scanner.log').read_text()[-1500:]
            raise AssertionError(output)
        old_pid=manager._supervised_pid('gateway-default')
        peer_pid=manager._supervised_pid('gateway-other')
        assert old_pid==document(roots['gateway-default']/'ready.json')['pid']
        old_start=Path(f'/proc/{old_pid}/stat').read_text().rsplit(')',1)[1].split()[19]
        peer_state=(peerhome/'gateway_state.json').read_bytes()
        manager.stop('gateway-default')
        wait_for(lambda:(roots['gateway-default']/'term-seen').exists())
        # Native stop() is asynchronous: the exact old worker still exists until flush permits exit.
        assert manager.is_running('gateway-default')
        assert manager._supervised_pid('gateway-default')==old_pid
        assert document(home/'gateway_state.json')['desired_state']=='stopped'
        assert document(home/'gateway_state.json')['fixture_field']=='keep'
        assert manager.is_running('gateway-other') and manager._supervised_pid('gateway-other')==peer_pid
        assert (peerhome/'gateway_state.json').read_bytes()==peer_state
        marker=document(_get_planned_stop_marker_path())
        assert marker['target_pid']==old_pid and marker['target_start_time']
        (roots['gateway-default']/'allow-exit').touch()
        wait_for(lambda:not manager.is_running('gateway-default'))
        terminal=document(roots['gateway-default']/'terminal.json')
        assert terminal=={'pid':old_pid,'clean':True,'planned':True}
        old_proc=Path(f'/proc/{old_pid}/stat')
        wait_for(lambda:not old_proc.exists() or old_proc.read_text().rsplit(')',1)[1].split()[19]!=old_start)
        assert manager._supervised_pid('gateway-default') is None
        assert manager.is_running('gateway-other') and manager._supervised_pid('gateway-other')==peer_pid
        manager.start('gateway-default')
        wait_for(lambda:document(roots['gateway-default']/'ready.json').get('pid') not in (None,old_pid))
        assert manager.is_running('gateway-default')
        assert document(home/'gateway_state.json')['desired_state']=='running'
        assert (peerhome/'gateway_state.json').read_bytes()==peer_state
    finally:
        for root in roots.values():(root/'allow-exit').touch()
        try:
            for name in roots:
                if (scanroot/name/'supervise/control').exists():manager.stop(name)
            wait_for(lambda:all(not manager.is_running(name) for name in roots))
            subprocess.run(['/command/s6-svscanctl','-t',str(scanroot)],check=True,capture_output=True,timeout=5)
            assert scanner.wait(timeout=5)==0
        finally:
            scannerlog.close()
            reset_hermes_home_override(token)


def test_native_missing_service_cannot_change_an_existing_profile_intent(tmp_path,monkeypatch):
    from hermes_cli.service_manager import S6ServiceManager,GatewayNotRegisteredError
    home=tmp_path/'home';home.mkdir(mode=0o700)
    state=home/'gateway_state.json';original=b'{"desired_state":"running","fixture_field":"keep"}'
    state.write_bytes(original);monkeypatch.setenv('HERMES_HOME',str(home))
    scanroot=tmp_path/'empty-scan';scanroot.mkdir(mode=0o700)
    with pytest.raises(GatewayNotRegisteredError):S6ServiceManager(scandir=scanroot).stop('gateway-default')
    assert state.read_bytes()==original
