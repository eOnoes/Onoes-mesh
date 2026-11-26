"""Real Windows task/mutex/process/source guard on one owned copied workspace.

Three sleeping test actors stand in for retired-role records. This does not
qualify real service retirement, the hard-bound production task or cloud access.
"""
import hashlib,importlib.util,json,os,subprocess,sys,uuid
from pathlib import Path
import pytest

MIND=Path(os.environ['MIND_SOURCE']);PROVIDER=Path(os.environ['MESH_PROVIDER_SOURCE'])
REPO=Path(os.environ['MESH_MAINTAINED_SOURCE'])
sys.path[:0]=[str(MIND),str(Path(os.environ['MIND_TEST_SOURCE'])/'tests'),str(PROVIDER)]
from test_cloud_curated_transfer import private_dir
from test_cloud_windows_task import task_admin,PS
from cloud_windows_task import Binding,TaskWindow,invoke,digest
from cloud_install_entry import CombinedWindow,InstallHeld
import cloud_source_selection as selection

pytestmark=pytest.mark.skipif(os.name!='nt',reason='Real owned Windows scheduler/mutex/process checks')


def load(path,name):
    spec=importlib.util.spec_from_file_location(name,path)
    value=importlib.util.module_from_spec(spec);sys.modules[name]=value;spec.loader.exec_module(value)
    return value


def put(path,value):path.write_text(json.dumps(value))


def test_actual_kernel_gate_refuses_main_and_peer_writers_then_selects_and_restores(tmp_path):
    workspace=tmp_path/'copied-mesh';native=workspace/'integrations/mind-recovery-candidate';native.mkdir(parents=True)
    launcher=workspace/'integrations/restart-workroom-preview.ps1';launcher.write_text('# Owned never-executed launcher witness\n')
    wrapper=tmp_path/'mesh-capture-first-hidden.vbs'
    old,new=tmp_path/'old.json',tmp_path/'new.json'
    wrapper.write_text('Run --approval '+str(old)+' --sha256 '+'a'*64+'\n')
    replacements={}
    for name in ('project_service_process_candidate.py','native_project_sync_candidate.py'):
        p=native/name;p.write_bytes(b'# owned original\n');after=b'# owned selected\n'
        replacements[str(p)]={'beforeSha256':digest(p),'afterSha256':hashlib.sha256(after).hexdigest(),'after':after}
    roots={n:private_dir(tmp_path/n) for n in ('task','source','windows')}
    roles=load(REPO/'integrations/mind-recovery-candidate/recall_process_candidate.py','owned_source_gate_roles')
    launcher_api=load(REPO/'integrations/mesh_launcher_window.py','owned_source_gate_launcher')
    atomic=load(REPO/'data/deep-enrollment-candidate-20261125/operations/deep-configuration-switch.py','owned_source_gate_atomic')
    task_name='Onoes-Mesh-Isolated-Test-'+uuid.uuid4().hex+'0000';actors=[];task=None
    task_admin(task_name,'create',True)
    try:
        before=invoke(powershell=PS,powershell_sha256=digest(PS),task_name=task_name)
        task=TaskWindow(Binding(task_name,'\\',str(PS),digest(PS),before['definitionSha256'],
            before['otherDefinitionSha256'],True),roots['task'])
        assert task.pause()['readyForCutover']
        for _ in range(3):actors.append(subprocess.Popen([sys.executable,'-I','-B','-c','import time;time.sleep(90)'],
            stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=subprocess.CREATE_NO_WINDOW))
        identities=[{'pid':p.pid,'creationTicks':roles.creation_ticks(p._handle)} for p in actors]
        archive=roots['windows']/'old-owner.json';archive.write_bytes(b'Owned synthetic retirement lineage witness')
        pin=digest(archive)
        put(roots['windows']/'old-retire-ATTEMPT.json',{'ownerSha256':pin,**identities[0],
            'peers':{'writer':identities[1],'reader':identities[2]}})
        put(roots['windows']/'old-retire-RESULT.json',{'verified':True,'ownerSha256':pin})
        window=CombinedWindow.__new__(CombinedWindow)
        window.plan={'workspace':str(workspace),'launcherSha256':digest(launcher)};window.root=roots
        window.task=task;window.roles=roles;window.launcher=launcher_api;window.atomic=atomic;window.selection=selection
        window.changes=selection.prepare(workspace=workspace,wrapper=wrapper,replacements=replacements,
            original_startup=old,original_sha256='a'*64,new_startup=new,new_sha256='b'*64,expected_wrapper_sha256=digest(wrapper))
        with launcher_api.MeshLauncherWindow(workspace,digest(launcher)) as held:
            with pytest.raises(InstallHeld):window.assert_retired(held)
        actors[0].terminate();actors[0].wait(timeout=5)
        with launcher_api.MeshLauncherWindow(workspace,digest(launcher)) as held:
            with pytest.raises(InstallHeld):window.assert_retired(held) # Peers remain authoritative live actors.
        for p in actors[1:]:p.terminate();p.wait(timeout=5)
        assert window.install_source()['filesSelected']==3
        assert all(p.read_bytes()==after for p,_,after in window.changes)
        with launcher_api.MeshLauncherWindow(workspace,digest(launcher)) as held:
            assert selection.restore(evidence=roots['source'],atomic_replace=atomic.atomic_replace,
                assert_quiescent=lambda:window.assert_retired(held))['filesRestored']==3
        assert all(p.read_bytes()==before for p,before,_ in window.changes)
        assert task.restore()['originalEnabledRestored']
        put(tmp_path/'OWNED-SOURCE-GATE.json',{'passed':True,'actualTaskPauseRestore':True,'actualLauncherMutex':True,
            'mainAndPeerLiveRefusal':True,'actualProcessBirthRetirement':True,'actualThreeFileSelectRestore':True,
            'testTaskHadTriggers':False,'testActionStarted':False,'liveChanges':False,'modelCalls':0,
            'retirementRecords':'SYNTHETIC_OWNED_ACTORS_NOT_REAL_MESH_SERVICES'})
    finally:
        for p in actors:
            if p.poll() is None:p.terminate();p.wait(timeout=5)
        task_admin(task_name,'remove')
