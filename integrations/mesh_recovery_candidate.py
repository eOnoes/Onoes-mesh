"""Explicit opt-in Ensure route. No enrollment, writer startup, or fallback.

Live activation requires a private exact recovery approval in addition to the
existing native reader/project approvals. Unknown attempts stay held. A later
tick reconciles a living input_sent attempt rather than launching a duplicate.
"""
import argparse
import ctypes
from ctypes import wintypes
from datetime import datetime, timezone, timedelta
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import uuid
from urllib.request import urlopen

ROOT=Path(__file__).resolve().parents[1]
FILES=('mesh_recovery_candidate.py','mesh_native_recovery.py','mesh_native_pair.py',
       'mesh_launcher_window.py','restart-workroom-preview.ps1')


class RecoveryHold(RuntimeError):
    pass


def require(ok):
    if not ok:raise RecoveryHold('Native recovery is held; preserve the existing attempt.')


def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def bounded_json(path):
    path=Path(path)
    require(path.is_absolute() and path.resolve(strict=True)==path and path.stat().st_size<=65536)
    def unique(pairs):
        result={}
        for key,value in pairs:
            require(key not in result);result[key]=value
        return result
    value=json.loads(path.read_bytes(),object_pairs_hook=unique)
    require(type(value) is dict)
    return value


def checked_recovery_approval(path,sha,profile,profile_sha):
    require(os.name=='nt' and re.fullmatch('[0-9a-f]{64}',sha or '') and digest(path)==sha)
    value=bounded_json(path)
    require(set(value)=={'schema','decision','ownerSid','workspace','profilePath','profileSha256',
                        'pythonSha256','sourceHashes'})
    require(value['schema']=='onoes-mesh-native-recovery-approval/v1'
        and value['decision']=='approve_exact_same_grant_gateway_recovery'
        and value['workspace']==str(ROOT) and value['profilePath']==str(Path(profile))
        and value['profileSha256']==profile_sha and digest(sys.executable)==value['pythonSha256'])
    expected={str(ROOT/'integrations'/name) for name in FILES}
    pins=value['sourceHashes'];require(type(pins) is dict and set(pins)==expected)
    require(all(digest(path)==sha for path,sha in pins.items()))
    return value


class ProcessObservation:
    """A retained query-only native handle; never grants process termination."""
    def __init__(self,window,roles,pid,ticks,args):
        require(type(pid) is int and pid>0 and type(ticks) is int and ticks>0)
        self.window,self.roles,self.pid,self.args=window,roles,pid,args
        self._handle=window.kernel.OpenProcess(0x100000|0x1000,False,pid)
        require(bool(self._handle))
        try:
            require(roles.creation_ticks(self._handle)==ticks and self.poll() is None)
            image=ctypes.create_unicode_buffer(32768);size=wintypes.DWORD(len(image))
            require(window.kernel.QueryFullProcessImageNameW(self._handle,0,image,ctypes.byref(size))
                    and Path(image.value)==Path(args[0]))
        except Exception:self.close();raise

    def poll(self):
        self.window.assert_held()
        value=self.window.kernel.WaitForSingleObject(self._handle,0)
        require(value in (0,258))
        return None if value==258 else 0

    def close(self):
        if self._handle:
            self.window.kernel.CloseHandle(self._handle);self._handle=None


def native_start(ticks):
    date=datetime(1601,1,1,tzinfo=timezone.utc)+timedelta(microseconds=ticks//10)
    return date.strftime('%Y-%m-%dT%H:%M:%S.')+f'{date.microsecond:06}{ticks%10}Z'


def ensure_gateway(window,*,launch,service,roles,profile,sha,approval,timeout=45):
    from mesh_native_pair import MeshNativePair
    from mesh_native_recovery import archive_retired_mesh_attempt
    window.assert_held()
    p,checked_roles=launch.checked_launch(profile,sha,approval);require(checked_roles is roles)
    require(p['schema']=='onoes-mesh-native-launch/v2')
    from onoes_mind.enrollment_store import qualify_private_storage
    for name in ('attemptPath','stdoutPath','stderrPath'):
        qualify_private_storage(Path(p[name]),kind='file')
    # Authentication/current source binding must pass even for a no-op tick.
    frame=launch.native_frame(p,roles,approval,sha);frame=None
    project=p['projectSync']
    state=service.service_state(project['serviceProfile'],project['serviceProfileSha256'],project['approvalPath'])
    require(state['ready'])  # Writer/reader restart is a separately qualified slice.
    attempt=bounded_json(p['attemptPath'])
    require(set(attempt)=={'schema','profileSha256','pid','creationTicks','state',
        'credentialsInRecord','executable','entryPoint'})
    require(attempt.get('schema')=='onoes-mesh-native-child/v1' and attempt.get('profileSha256')==sha
        and attempt.get('state')=='input_sent' and attempt.get('credentialsInRecord') is False
        and type(attempt.get('pid')) is int and attempt['pid']>0
        and type(attempt.get('creationTicks')) is int and attempt['creationTicks']>0
        and attempt.get('executable')==p['nodeExecutable']
        and attempt.get('entryPoint')==str(window.workspace/'serve.mjs'))
    receipt_path=window.workspace.parent/'workroom-ab-preview-process.json'
    previous_sha=digest(receipt_path);owner=bounded_json(receipt_path)
    args=[p['nodeExecutable'],str(window.workspace/'serve.mjs'),'--native-mind']
    require(owner.get('Schema')=='onoes-owned-process/v1' and owner.get('WorkingDirectory')==str(window.workspace)
        and type(owner.get('Id')) is int and owner['Id']>0
        and type(owner.get('StartTime')) is str
        and owner.get('EntryPoint')==args[1] and owner.get('Path')==args[0]
        and type(owner.get('Port')) is int and owner['Port']==int(p['settings']['MESH_PREVIEW_PORT'])
        and owner.get('CommandLine')==subprocess.list2cmdline(args))
    same_owner=owner.get('Id')==attempt['pid'] and owner.get('StartTime')==native_start(attempt['creationTicks'])
    alive=roles.same_process_alive(attempt['pid'],attempt['creationTicks'])
    # A failed/unpublished new launch is not permission to start another one.
    require(alive or same_owner)
    observed=[]
    try:
        writer=ProcessObservation(window,roles,state['pid'],state['creationTicks'],[sys.executable])
        observed.append(writer)
        pair=MeshNativePair(window,service_module=service,launch_module=launch,roles_module=roles,
            service_profile=project['serviceProfile'],service_sha256=project['serviceProfileSha256'],
            project_approval=project['approvalPath'],mesh_profile=profile,mesh_sha256=sha,reader_approval=approval)
        pair.adopt_started_writer(writer,state['creationTicks'])
        if alive:
            gateway=ProcessObservation(window,roles,attempt['pid'],attempt['creationTicks'],args)
            observed.append(gateway)
            pair.adopt_started_mesh(gateway,attempt['creationTicks'])
        else:
            archive_retired_mesh_attempt(window,launch_module=launch,mesh_profile=profile,
                mesh_sha256=sha,reader_approval=approval)
            pair.launch_mesh()
        until=time.monotonic()+timeout
        while pair.observe_mesh()['stage']!='mesh_ready':
            require(time.monotonic()<until);time.sleep(.2)
        with urlopen(pair.address,timeout=5) as response:require(response.status==200)
        if not (alive and same_owner):
            before=window.workspace/'data'/f'native-recovery-owner-before-{pair.mesh.pid}-{pair.mesh_ticks}-{uuid.uuid4().hex}.json'
            pair.publish_owner(previous_sha256=previous_sha,beforeimage_path=before)
        else:require(digest(receipt_path)==previous_sha)
        return dict(schema='onoes-mesh-native-recovery-state/v1',
            state='running' if alive and same_owner else 'reconciled' if alive else 'recovered',
            pid=pair.mesh.pid,creationTicks=pair.mesh_ticks,writerPid=writer.pid,
            sameGrant=True,newCredentialCreated=False)
    finally:
        for reference in observed:reference.close()


def main():
    parser=argparse.ArgumentParser()
    for name in ('profile','sha256','approval','recovery-approval','recovery-sha256'):
        parser.add_argument('--'+name,required=True)
    parser.add_argument('--ensure',action='store_true',required=True)
    args=parser.parse_args()
    try:
        approved=checked_recovery_approval(args.recovery_approval,args.recovery_sha256,args.profile,args.sha256)
        sys.path.insert(0,str(ROOT/'integrations'))
        sys.path.insert(0,str(ROOT/'integrations/mind-recovery-candidate'))
        import mesh_launch_candidate as launch
        # Authenticate the pinned reader before importing canonical storage code.
        p,roles=launch.checked_launch(args.profile,args.sha256,args.approval)
        from onoes_mind.enrollment_store import qualify_private_storage
        qualify_private_storage(Path(args.recovery_approval),kind='file')
        reader=bounded_json(p['readerProfile']);require(approved['ownerSid']==reader['ownerSid'])
        import project_service_process_candidate as service
        from mesh_launcher_window import MeshLauncherWindow
        with MeshLauncherWindow(ROOT,approved['sourceHashes'][str(ROOT/'integrations/restart-workroom-preview.ps1')]) as window:
            if (ROOT/'data/workroom-preview/recovery-paused').exists():
                result=dict(schema='onoes-mesh-native-recovery-state/v1',state='paused')
            else:result=ensure_gateway(window,launch=launch,service=service,roles=roles,
                profile=args.profile,sha=args.sha256,approval=args.approval)
        print(json.dumps(result));return 0
    except Exception:
        print(json.dumps(dict(schema='onoes-mesh-native-recovery-state/v1',state='held',
            message='Native recovery could not qualify this binding. Preserve its attempt; no legacy fallback.')))
        return 1


if __name__=='__main__':raise SystemExit(main())
