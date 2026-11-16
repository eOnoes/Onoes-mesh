"""Explicit opt-in Ensure route. No enrollment, credential issuance or fallback.

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
    memory=value.get('decision')=='approve_exact_same_grant_memory_recovery'
    require(set(value)=={'schema','decision','ownerSid','workspace','profilePath','profileSha256',
                        'pythonSha256','sourceHashes'}|({'readerServiceProfile','readerServiceSha256'} if memory else set()))
    require(value['schema']=='onoes-mesh-native-recovery-approval/v1'
        and value['decision'] in ('approve_exact_same_grant_gateway_recovery','approve_exact_same_grant_memory_recovery')
        and value['workspace']==str(ROOT) and value['profilePath']==str(Path(profile))
        and value['profileSha256']==profile_sha and digest(sys.executable)==value['pythonSha256'])
    expected={str(ROOT/'integrations'/name) for name in FILES}
    if memory:
        expected.add(str(ROOT/'integrations/mind-recovery-candidate/reader_service_process_candidate.py'))
        require(type(value['readerServiceProfile']) is str and Path(value['readerServiceProfile']).is_absolute()
            and re.fullmatch('[a-f0-9]{64}',value['readerServiceSha256'] or ''))
    pins=value['sourceHashes'];require(type(pins) is dict and set(pins)==expected)
    require(all(digest(path)==sha for path,sha in pins.items()))
    return value


class ProcessObservation:
    """Retained exact native identity; query-only unless reconnect is authorized."""
    def __init__(self,window,roles,pid,ticks,args,*,allow_terminate=False):
        require(type(pid) is int and pid>0 and type(ticks) is int and ticks>0)
        self.window,self.roles,self.pid,self.args=window,roles,pid,args
        self.ticks,self.allow_terminate=ticks,allow_terminate
        self._handle=window.kernel.OpenProcess(0x100000|0x1000|(1 if allow_terminate else 0),False,pid)
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

    def terminate(self):
        self.window.assert_held()
        require(self.allow_terminate and self.roles.creation_ticks(self._handle)==self.ticks)
        if self.poll() is None:
            fn=self.window.kernel.TerminateProcess
            fn.argtypes=[wintypes.HANDLE,wintypes.UINT];fn.restype=wintypes.BOOL
            require(bool(fn(self._handle,1)))


def native_start(ticks):
    date=datetime(1601,1,1,tzinfo=timezone.utc)+timedelta(microseconds=ticks//10)
    return date.strftime('%Y-%m-%dT%H:%M:%S.')+f'{date.microsecond:06}{ticks%10}Z'


def gateway_binding(window,p,sha,roles):
    from mesh_native_recovery import identified_native_attempt
    window.assert_held()
    from onoes_mind.enrollment_store import qualify_private_storage
    for name in ('attemptPath','stdoutPath','stderrPath'):
        qualify_private_storage(Path(p[name]),kind='file')
    attempt=bounded_json(p['attemptPath'])
    require(identified_native_attempt(attempt))
    require(attempt.get('profileSha256')==sha
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
    return dict(attempt=attempt,args=args,receiptPath=receipt_path,previousSha=previous_sha,sameOwner=same_owner,alive=alive)


def ensure_gateway(window,*,launch,service,roles,profile,sha,approval,timeout=45):
    window.assert_held()
    p,checked_roles=launch.checked_launch(profile,sha,approval);require(checked_roles is roles)
    require(p['schema']=='onoes-mesh-native-launch/v2')
    # Authentication/current source binding must pass even for a no-op tick.
    frame=launch.native_frame(p,roles,approval,sha);frame=None
    project=p['projectSync']
    state=service.service_state(project['serviceProfile'],project['serviceProfileSha256'],project['approvalPath'])
    require(state['ready'])
    return _finish_gateway_preflight(window,launch=launch,service=service,roles=roles,p=p,
        profile=profile,sha=sha,approval=approval,state=state,timeout=timeout)


def _finish_gateway_preflight(window,*,launch,service,roles,p,profile,sha,approval,state,
                              timeout,reconcile_only=False,expected_peers=None):
    """Internal completion of the caller's full authorization under this window.

    No caller-supplied permission cache survives the operation. The handoff has
    already checked the same private profiles, scope and authenticated frame.
    """
    from mesh_native_pair import MeshNativePair
    from mesh_native_recovery import archive_retired_mesh_attempt,valid_memory_peers
    window.assert_held();require(state['ready'])
    project=p['projectSync']
    bound=gateway_binding(window,p,sha,roles)
    attempt,args=bound['attempt'],bound['args'];receipt_path=bound['receiptPath']
    previous_sha,same_owner,alive=bound['previousSha'],bound['sameOwner'],bound['alive']
    if reconcile_only:
        require(alive and valid_memory_peers(expected_peers) and attempt.get('peers')==expected_peers)
    observed=[]
    try:
        if reconcile_only:
            peer=expected_peers['reader']
            observed.append(ProcessObservation(window,roles,peer['pid'],peer['creationTicks'],[sys.executable]))
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
            require(not reconcile_only)
            archive_retired_mesh_attempt(window,launch_module=launch,mesh_profile=profile,
                mesh_sha256=sha,reader_approval=approval)
            pair.launch_mesh()
        until=time.monotonic()+timeout
        while pair.observe_mesh()['stage']!='mesh_ready':
            require(time.monotonic()<until);time.sleep(.2)
        with urlopen(pair.address,timeout=5) as response:require(response.status==200)
        require(all(reference.poll() is None for reference in observed))
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


def known_service_view(*,attempt_path,ready_path,profile_sha,kind,fetch,roles):
    """Wait on a known starting PID; never turn an unpublished failure into retry."""
    attempt=bounded_json(attempt_path)
    require(attempt.get('schema')==f'onoes-mind-{kind}-service-attempt/v1'
        and attempt.get('profileSha256')==profile_sha and attempt.get('state')=='started'
        and type(attempt.get('pid')) is int and attempt['pid']>0
        and type(attempt.get('creationTicks')) is int and attempt['creationTicks']>0
        and type(attempt.get('runId')) is str and re.fullmatch('[a-f0-9]{32}',attempt['runId']))
    live=roles.same_process_alive(attempt['pid'],attempt['creationTicks'])
    try:raw=bounded_json(ready_path)
    except (FileNotFoundError,json.JSONDecodeError):
        require(live)
        return dict(state='starting',pid=attempt['pid'],creationTicks=attempt['creationTicks'],processLive=True,ready=False)
    require(raw.get('pid')==attempt['pid'] and raw.get('creationTicks')==attempt['creationTicks'])
    value=fetch()
    require(value['pid']==attempt['pid'] and value['creationTicks']==attempt['creationTicks'])
    require(value['state'] in (('starting','running') if value['processLive'] else ('running','stopped')))
    return value


class MemoryRolesUnknown(RecoveryHold):
    """Retain all original starts if a later role/start observation is uncertain."""
    def __init__(self,children,cause):
        self.children,self.original_error=children,cause
        super().__init__('Memory role recovery is unresolved; preserve its original attempts.')


def restore_memory_roles(window,*,service,reader_service,roles,p,profile,approval,approved,timeout=90):
    """Caller must first prove its exact gateway ownership under this window."""
    window.assert_held();require(approved['decision']=='approve_exact_same_grant_memory_recovery')
    rp,rbase,rbinding=reader_service.checked_profile(approved['readerServiceProfile'],approved['readerServiceSha256'],approval)
    require(rp['readerProfilePath']==p['readerProfile'] and rp['readerProfileSha256']==p['readerProfileSha256']
            and Path(approved['readerServiceProfile']).parent==Path(profile).parent)
    project=p['projectSync'];sp,sbase,sbinding=service.checked_profile(
        project['serviceProfile'],project['serviceProfileSha256'],project['approvalPath'])
    service.terminal_proof(sbase,sbinding,sp['operatorProfileSha256'])
    require(all(getattr(rbinding,name)==getattr(sbinding,name) for name in
                ('database_path','store_id','environment','file_device','file_inode')))
    children=[]
    def reader_view():
        if os.path.lexists(rp['attemptPath']):
            return known_service_view(attempt_path=rp['attemptPath'],ready_path=rbase['readyPath'],
                profile_sha=approved['readerServiceSha256'],kind='reader',roles=roles,
                fetch=lambda:reader_service.service_state(approved['readerServiceProfile'],approved['readerServiceSha256'],approval))
        raw=bounded_json(rbase['readyPath'])
        require('managedBy' not in raw and raw.get('profileSha256')==p['readerProfileSha256'])
        value=roles.reader_state(p['readerProfile'],p['readerProfileSha256'],approval)
        require(value['state'] in (('starting','running') if value['processLive'] else ('running','stopped')))
        return value
    def writer_view():
        return known_service_view(attempt_path=sp['attemptPath'],ready_path=sp['readyPath'],
            profile_sha=project['serviceProfileSha256'],kind='project',roles=roles,
            fetch=lambda:service.service_state(project['serviceProfile'],project['serviceProfileSha256'],project['approvalPath']))
    # Validate both roles before starting either. An existing failed/unknown actor
    # is held; only a previously identified retired owner may be restarted here.
    reader,writer=reader_view(),writer_view()
    try:
        for state,start in (
            (reader,lambda:reader_service.launch_service(approved['readerServiceProfile'],approved['readerServiceSha256'],approval)),
            (writer,lambda:service.launch_service(project['serviceProfile'],project['serviceProfileSha256'],project['approvalPath']))):
            if not state['processLive']:
                child,ticks=start();children.append((child,ticks))
        until=time.monotonic()+timeout
        while True:
            for child,ticks in children:require(child.poll() is None and roles.creation_ticks(child._handle)==ticks)
            reader,writer=reader_view(),writer_view()
            if reader['ready'] and writer['ready']:break
            require(time.monotonic()<until);time.sleep(.2)
    except Exception as error:raise MemoryRolesUnknown(children,error) from None
    return reader,writer,children


def ensure_memory(window,*,launch,service,reader_service,roles,profile,sha,approval,approved,timeout=90):
    """Restore previously enrolled roles, then refresh only their exact gateway."""
    window.assert_held()
    require(approved['decision']=='approve_exact_same_grant_memory_recovery')
    p,checked_roles=launch.inspect_launch(profile,sha,approval);require(checked_roles is roles)
    require(p['schema']=='onoes-mesh-native-launch/v2')
    gateway_binding(window,p,sha,roles)  # Unknown gateway ownership blocks all actor changes.
    reader,writer,children=restore_memory_roles(window,service=service,reader_service=reader_service,roles=roles,
        p=p,profile=profile,approval=approval,approved=approved,timeout=timeout)
    frame=launch.native_frame(p,roles,approval,sha)
    peers=launch.native_peers(p,roles,approval,frame);frame=None
    bound=gateway_binding(window,p,sha,roles);attempt=bound['attempt']
    refreshed=False
    if bound['alive'] and attempt.get('peers')!=peers:
        # First reconcile a living unpublished attempt using its same identity.
        # This publishes process ownership only, not a claim of memory freshness.
        ensure_gateway(window,launch=launch,service=service,roles=roles,profile=profile,sha=sha,approval=approval)
        gateway=ProcessObservation(window,roles,attempt['pid'],attempt['creationTicks'],bound['args'],allow_terminate=True)
        try:
            gateway.terminate();deadline=time.monotonic()+30
            while gateway.poll() is None:require(time.monotonic()<deadline);time.sleep(.1)
        finally:gateway.close()
        refreshed=True
    result=ensure_gateway(window,launch=launch,service=service,roles=roles,profile=profile,sha=sha,approval=approval)
    final=bounded_json(p['attemptPath']);require(final.get('peers')==peers)
    return {**result,'readerPid':reader['pid'],'writerPid':writer['pid'],'gatewayRefreshedForPeers':refreshed,
            'memoryServicesRestarted':len(children)}


class CaptureHandoffUnknown(RecoveryHold):
    """Keep any original new-child handle while durable delivery is reconciled."""
    def __init__(self,pair):
        self.pair=pair
        super().__init__('Connected handoff is unresolved; retain the original pair and do not retry launch.')


def checked_handoff_approval(path,sha):
    require(os.name=='nt' and re.fullmatch('[a-f0-9]{64}',sha or '') and digest(path)==sha)
    value=bounded_json(path)
    require(set(value)=={'schema','decision','workspace','ownerSid','pythonSha256','sourceHashes','capture','connected'}
        and value['schema']=='onoes-mesh-capture-handoff-approval/v1'
        and value['decision']=='approve_exact_capture_to_connected_handoff'
        and value['workspace']==str(ROOT) and digest(sys.executable)==value['pythonSha256'])
    pins=value['sourceHashes'];require(type(pins) is dict and set(pins)=={str(ROOT/'integrations'/name) for name in FILES}
        and all(digest(filename)==expected for filename,expected in pins.items()))
    for role in ('capture','connected'):
        selected=value[role];keys={'profilePath','profileSha256','approvalPath','approvalSha256'}
        if role=='connected':keys|={'projectApprovalPath','projectApprovalSha256'}
        require(type(selected) is dict and set(selected)==keys)
        for prefix in ('profile','approval')+(('projectApproval',) if role=='connected' else ()):
            filename,expected=selected[prefix+'Path'],selected[prefix+'Sha256']
            require(type(filename) is str and Path(filename).is_absolute() and Path(filename).resolve(strict=True)==Path(filename)
                and type(expected) is str and re.fullmatch('[a-f0-9]{64}',expected) and digest(filename)==expected)
    return value


def handoff_capture_to_connected(window,*,launch,service,roles,approval_path,approval_sha,timeout=60):
    """Explicit owner transition; return state and the original new gateway child.

    A failed preflight leaves capture untouched. Once launch is attempted, only
    its durable IDs may be reconciled. No grant is provisioned or role restarted.
    The caller retains a CaptureHandoffUnknown exception and its pair on failure.
    """
    from mesh_native_pair import MeshNativePair
    from mesh_native_recovery import identified_native_attempt
    window.assert_held();require(window.workspace==ROOT)
    approved=checked_handoff_approval(approval_path,approval_sha)
    c,n=approved['capture'],approved['connected']
    cp,cr=launch.checked_launch(c['profilePath'],c['profileSha256'],c['approvalPath'])
    np,nr=launch.checked_launch(n['profilePath'],n['profileSha256'],n['approvalPath'])
    require(cr is roles and nr is roles and cp['schema']==launch.CAPTURE_SCHEMA
        and np['schema']=='onoes-mesh-native-launch/v2' and cp['ownerSid']==approved['ownerSid']
        and cp['settings']==np['settings'] and cp['nodeExecutable']==np['nodeExecutable']
        and cp['nodeSha256']==np['nodeSha256'] and cp['workspace']==np['workspace']==str(ROOT))
    from onoes_mind.enrollment_store import qualify_private_storage
    qualify_private_storage(Path(approval_path),kind='file')
    project=np['projectSync'];require(project['approvalPath']==n['projectApprovalPath'])
    local=launch.native_frame(cp,roles,c['approvalPath'],c['profileSha256'])['projectCaptureOptions']
    frame=launch.native_frame(np,roles,n['approvalPath'],n['profileSha256'])
    connected=frame['projectSyncOptions']
    require(local==dict(schema='onoes-mesh-native-project-capture/v1',source=connected['source'],
        storeId=connected['destination']['storeId'],links=connected['links']))
    peers=launch.native_peers(np,roles,n['approvalPath'],frame)
    frame=None;connected=None
    paths=[cp[name] for name in ('attemptPath','stdoutPath','stderrPath')]+[np[name] for name in ('attemptPath','stdoutPath','stderrPath')]
    require(len(set(paths))==6 and all(path not in paths for path in
        (str(approval_path),c['profilePath'],c['approvalPath'],n['profilePath'],n['approvalPath'],n['projectApprovalPath'])))
    qualify_private_storage(Path(cp['attemptPath']),kind='file')
    capture=bounded_json(cp['attemptPath'])
    require(identified_native_attempt(capture) and capture['schema']=='onoes-mesh-native-child/v3'
        and capture['mode']=='capture_only' and capture['profileSha256']==c['profileSha256']
        and capture['executable']==cp['nodeExecutable'] and capture['entryPoint']==str(ROOT/'serve.mjs'))
    if os.path.lexists(np['attemptPath']):
        # A new child already exists or is unresolved. Never replace it here.
        require(not roles.same_process_alive(capture['pid'],capture['creationTicks']))
        peer=peers['writer']
        result=_finish_gateway_preflight(window,launch=launch,service=service,roles=roles,p=np,
            profile=n['profilePath'],sha=n['profileSha256'],approval=n['approvalPath'],
            state=dict(ready=True,pid=peer['pid'],creationTicks=peer['creationTicks']),timeout=timeout,
            reconcile_only=True,expected_peers=peers)
        return {**result,'transition':'reconciled_capture_handoff'},None
    require(not any(os.path.lexists(np[name]) for name in ('stdoutPath','stderrPath')))
    bound=gateway_binding(window,cp,c['profileSha256'],roles);require(bound['sameOwner'])
    state=service.service_state(project['serviceProfile'],project['serviceProfileSha256'],project['approvalPath'])
    require(state['ready'])
    writer=ProcessObservation(window,roles,state['pid'],state['creationTicks'],[sys.executable])
    pair=None
    try:
        pair=MeshNativePair(window,service_module=service,launch_module=launch,roles_module=roles,
            service_profile=project['serviceProfile'],service_sha256=project['serviceProfileSha256'],
            project_approval=project['approvalPath'],mesh_profile=n['profilePath'],mesh_sha256=n['profileSha256'],reader_approval=n['approvalPath'])
        pair.adopt_started_writer(writer,state['creationTicks'])
        require(digest(bound['receiptPath'])==bound['previousSha'])
        if bound['alive']:
            window._owns_gateway(capture['pid'],int(cp['settings']['MESH_PREVIEW_PORT']))
            original=ProcessObservation(window,roles,capture['pid'],capture['creationTicks'],bound['args'],allow_terminate=True)
            try:
                original.terminate();until=time.monotonic()+30
                while original.poll() is None:require(time.monotonic()<until);time.sleep(.1)
            finally:original.close()
        require(not roles.same_process_alive(capture['pid'],capture['creationTicks']))
        require(digest(bound['receiptPath'])==bound['previousSha'])
        try:
            pair.launch_mesh();until=time.monotonic()+timeout
            while pair.observe_mesh()['stage']!='mesh_ready':require(time.monotonic()<until);time.sleep(.2)
            with urlopen(pair.address,timeout=5) as response:require(response.status==200)
            before=ROOT/'data'/f'capture-handoff-owner-before-{pair.mesh.pid}-{pair.mesh_ticks}-{uuid.uuid4().hex}.json'
            pair.publish_owner(previous_sha256=bound['previousSha'],beforeimage_path=before)
        except Exception:raise CaptureHandoffUnknown(pair) from None
        return dict(schema='onoes-mesh-capture-handoff-state/v1',state='connected',pid=pair.mesh.pid,
            creationTicks=pair.mesh_ticks,previousCapturePid=capture['pid'],writerPid=writer.pid,
            sameGrant=True,newCredentialCreated=False),pair.mesh
    finally:writer.close()


def handoff_main(argv):
    parser=argparse.ArgumentParser(description='Explicit approved offline capture to connected owner handoff.')
    parser.add_argument('--handoff-capture-to-connected',action='store_true',required=True)
    parser.add_argument('--handoff-approval',required=True)
    parser.add_argument('--handoff-sha256',required=True)
    args=parser.parse_args(argv)
    pending=None
    try:
        require(len(argv)==5 and all(argv.count(flag)==1 for flag in
            ('--handoff-capture-to-connected','--handoff-approval','--handoff-sha256')))
        approved=checked_handoff_approval(args.handoff_approval,args.handoff_sha256)
        sys.path.insert(0,str(ROOT/'integrations'))
        sys.path.insert(0,str(ROOT/'integrations/mind-recovery-candidate'))
        import mesh_launch_candidate as launch
        selected=approved['capture']
        _,roles=launch.checked_launch(selected['profilePath'],selected['profileSha256'],selected['approvalPath'])
        import project_service_process_candidate as service
        from mesh_launcher_window import MeshLauncherWindow
        with MeshLauncherWindow(ROOT,approved['sourceHashes'][str(ROOT/'integrations/restart-workroom-preview.ps1')]) as window:
            if (ROOT/'data/workroom-preview/recovery-paused').exists():
                result=dict(schema='onoes-mesh-capture-handoff-state/v1',state='paused')
            else:
                result,child=handoff_capture_to_connected(window,launch=launch,service=service,roles=roles,
                    approval_path=args.handoff_approval,approval_sha=args.handoff_sha256)
                # Retain the original launch handle through publication and the
                # launcher-window handoff. A normal process exit does not stop it.
                pending=child
        print(json.dumps(result));return 0
    except CaptureHandoffUnknown as error:
        pending=error.pair  # Preserve original child references until command exit.
        print(json.dumps(dict(schema='onoes-mesh-capture-handoff-state/v1',state='held',
            message='Preserve the original attempt. Reconcile its identity; do not relaunch.')))
        return 1
    except Exception:
        print(json.dumps(dict(schema='onoes-mesh-capture-handoff-state/v1',state='held',
            message='The handoff could not verify its approved binding. No fallback is authorized.')))
        return 1


def main():
    if '--handoff-capture-to-connected' in sys.argv[1:]:
        return handoff_main(sys.argv[1:])
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
        full=approved['decision']=='approve_exact_same_grant_memory_recovery'
        p,roles=(launch.inspect_launch if full else launch.checked_launch)(args.profile,args.sha256,args.approval)
        from onoes_mind.enrollment_store import qualify_private_storage
        qualify_private_storage(Path(args.recovery_approval),kind='file')
        reader=bounded_json(p['readerProfile']);require(approved['ownerSid']==reader['ownerSid'])
        import project_service_process_candidate as service
        from mesh_launcher_window import MeshLauncherWindow
        with MeshLauncherWindow(ROOT,approved['sourceHashes'][str(ROOT/'integrations/restart-workroom-preview.ps1')]) as window:
            if (ROOT/'data/workroom-preview/recovery-paused').exists():
                result=dict(schema='onoes-mesh-native-recovery-state/v1',state='paused')
            elif full:
                import reader_service_process_candidate as reader_service
                result=ensure_memory(window,launch=launch,service=service,reader_service=reader_service,roles=roles,
                    profile=args.profile,sha=args.sha256,approval=args.approval,approved=approved)
            else:result=ensure_gateway(window,launch=launch,service=service,roles=roles,
                    profile=args.profile,sha=args.sha256,approval=args.approval)
        print(json.dumps(result));return 0
    except Exception:
        print(json.dumps(dict(schema='onoes-mesh-native-recovery-state/v1',state='held',
            message='Native recovery could not qualify this binding. Preserve its attempt; no legacy fallback.')))
        return 1


if __name__=='__main__':raise SystemExit(main())
