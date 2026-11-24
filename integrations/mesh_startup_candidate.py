"""Explicit capture-first owner recovery. Inactive until separately approved.

Existing attempts, retired archives and the owner receipt are the only process
records. This never enrolls memory, dispatches work or installs a scheduler.
"""
import argparse
from datetime import datetime,timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import time
import traceback
import uuid

ROOT=Path(__file__).resolve().parents[1]
SOURCES=('mesh_startup_candidate.py','mesh_recovery_candidate.py','mesh_native_recovery.py',
         'mesh_native_pair.py','mesh_launcher_window.py','restart-workroom-preview.ps1',
         'mind-recovery-candidate/mesh_launch_candidate.py')


class StartupHold(RuntimeError):pass


class StartupUnknown(StartupHold):
    def __init__(self,handles,cause):
        self.handles,self.original_error=handles,cause
        super().__init__('Startup launch/publication is unresolved; preserve original attempts.')


def require(ok):
    if not ok:raise StartupHold('Startup ownership is held; preserve original attempts.')


def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path,expected_sha=None):
    path=Path(path);require(path.is_absolute() and path.resolve(strict=True)==path and path.stat().st_size<=65536)
    def unique(pairs):
        result={}
        for key,value in pairs:require(key not in result);result[key]=value
        return result
    with path.open('rb') as source:raw=source.read(65537)
    require(len(raw)<=65536 and (expected_sha is None or hashlib.sha256(raw).hexdigest()==expected_sha))
    value=json.loads(raw,object_pairs_hook=unique);require(type(value) is dict);return value


def checked_startup(path,sha):
    require(os.name=='nt' and re.fullmatch('[a-f0-9]{64}',sha or '') and digest(path)==sha)
    value=read(path,sha)
    require(set(value)=={'schema','decision','workspace','ownerSid','pythonSha256','sourceHashes',
        'handoffApprovalPath','handoffApprovalSha256','memoryApprovalPath','memoryApprovalSha256'}
        and value['schema']=='onoes-mesh-capture-first-approval/v1'
        and value['decision']=='approve_exact_capture_first_recovery' and value['workspace']==str(ROOT)
        and value['pythonSha256']==digest(sys.executable))
    pins=value['sourceHashes'];require(type(pins) is dict and set(pins)=={str(ROOT/'integrations'/name) for name in SOURCES}
        and all(digest(filename)==expected for filename,expected in pins.items()))
    for prefix in ('handoffApproval','memoryApproval'):
        require(type(value[prefix+'Sha256']) is str and re.fullmatch('[a-f0-9]{64}',value[prefix+'Sha256'])
            and digest(value[prefix+'Path'])==value[prefix+'Sha256'])
    sys.path.insert(0,str(ROOT/'integrations'));sys.path.insert(0,str(ROOT/'integrations/mind-recovery-candidate'))
    import mesh_recovery_candidate as recovery
    require(Path(recovery.__file__).resolve()==ROOT/'integrations/mesh_recovery_candidate.py')
    handoff=recovery.checked_handoff_approval(value['handoffApprovalPath'],value['handoffApprovalSha256'])
    n=handoff['connected']
    memory=recovery.checked_recovery_approval(value['memoryApprovalPath'],value['memoryApprovalSha256'],
        n['profilePath'],n['profileSha256'])
    require(value['ownerSid']==handoff['ownerSid']==memory['ownerSid']
        and memory['decision']=='approve_exact_same_grant_memory_recovery')
    return value,handoff,memory,recovery


def profiles(handoff):
    from mesh_native_recovery import connected_settings_match
    result={mode:read(handoff[mode]['profilePath'],handoff[mode]['profileSha256']) for mode in ('capture','connected')}
    c,n=result['capture'],result['connected']
    require(c['schema']=='onoes-mesh-native-capture-launch/v1' and n['schema']=='onoes-mesh-native-launch/v2'
        and c['workspace']==n['workspace']==str(ROOT) and connected_settings_match(c['settings'],n['settings'])
        and c['nodeExecutable']==n['nodeExecutable'] and c['nodeSha256']==n['nodeSha256']
        and c['projectCapture']['source']==n['projectSync']['source'] and c['projectCapture']['links']==n['projectSync']['links'])
    port=int(c['settings']['MESH_PREVIEW_PORT']);require(0<port<65536)
    protected={str(ROOT.parent/'workroom-ab-preview-process.json')}
    for mode,p in result.items():
        protected.update(p['sourceHashes']);protected.update(handoff[mode][name] for name in handoff[mode] if name.endswith('Path'))
        protected.add(p['settings']['MESH_GATE_KEY_FILE'])
    protected.update((n['readerProfile'],n['projectSync']['serviceProfile'],n['projectSync']['approvalPath']))
    if 'MESH_NATIVE_WORKER_RECORD' in n['settings']:
        protected.add(n['settings']['MESH_NATIVE_WORKER_RECORD'])
    for mode,p in result.items():
        root=Path(handoff[mode]['profilePath']).parent
        require(not root.is_relative_to(ROOT) and not ROOT.is_relative_to(root))
        paths=[Path(p[key]) for key in ('attemptPath','stdoutPath','stderrPath')]
        require(len(set(paths))==3 and all(path.is_absolute() and path.parent==root and str(path) not in protected for path in paths))
    return result


def load_roles(capture):
    # Observation imports only a fixed hash-checked standard-library role helper.
    # It neither opens a role profile nor reads a memory credential/database.
    path=ROOT/'integrations/mind-recovery-candidate/recall_process_candidate.py'
    require(capture['sourceHashes'].get(str(path))==digest(path))
    import recall_process_candidate as roles
    require(Path(roles.__file__).resolve()==path)
    return roles


def attempt(p,selection,path=None):
    from mesh_native_recovery import identified_native_attempt
    path=Path(path or p['attemptPath']);record=read(path)
    require(identified_native_attempt(record) and record['profileSha256']==selection['profileSha256']
        and record['executable']==p['nodeExecutable'] and record['entryPoint']==str(ROOT/'serve.mjs'))
    require(record['schema']==('onoes-mesh-native-child/v3' if selection.get('mode')=='capture' else 'onoes-mesh-native-child/v2'))
    return record


def receipt_ticks(value):
    stamp=value['StartTime'];require(type(stamp) is str and re.fullmatch(r'\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{7}Z',stamp))
    date=datetime.strptime(stamp[:19],'%Y-%m-%dT%H:%M:%S').replace(tzinfo=timezone.utc)
    delta=date-datetime(1601,1,1,tzinfo=timezone.utc)
    return (delta.days*86400+delta.seconds)*10000000+int(stamp[20:27])


def owner_record(window,handoff,selected,roles):
    path=ROOT.parent/'workroom-ab-preview-process.json'
    if not os.path.lexists(path):return None
    owner=read(path);ticks=receipt_ticks(owner)
    require(owner.get('Schema')=='onoes-owned-process/v1' and owner.get('WorkingDirectory')==str(ROOT)
        and type(owner.get('Id')) is int and owner['Id']>0)
    for mode,p in selected.items():
        args=[p['nodeExecutable'],str(ROOT/'serve.mjs'),'--native-mind']
        require(owner.get('EntryPoint')==args[1] and owner.get('Path')==args[0]
            and owner.get('CommandLine')==subprocess.list2cmdline(args) and owner.get('Port')==int(p['settings']['MESH_PREVIEW_PORT']))
        candidates=[Path(p['attemptPath']),Path(p['attemptPath']+f".retired-{owner['Id']}-{ticks}")]
        for candidate in candidates:
            if not os.path.lexists(candidate):continue
            record=attempt(p,{**handoff[mode],'mode':mode},candidate)
            if (record['pid'],record['creationTicks'])!=(owner['Id'],ticks):continue
            live=roles.same_process_alive(record['pid'],record['creationTicks'])
            require(not live or candidate==Path(p['attemptPath']))
            if candidate!=Path(p['attemptPath']):
                suffix=f".retired-{owner['Id']}-{ticks}"
                require(all(Path(p[key]+suffix).is_file() for key in ('stdoutPath','stderrPath')))
            if live:window._owns_gateway(record['pid'],int(p['settings']['MESH_PREVIEW_PORT']))
            return dict(mode=mode,record=record,live=live,receiptSha256=digest(path),archived=candidate!=Path(p['attemptPath']))
    raise StartupHold('Owner receipt does not identify a configured attempt.')


def retire_mode(window,p,selection,roles):
    """Explicit startup authorization, metadata-only; never authenticate memory."""
    window.assert_held();paths=[Path(p[key]) for key in ('attemptPath','stdoutPath','stderrPath')]
    if not os.path.lexists(paths[0]):
        require(not any(os.path.lexists(path) for path in paths[1:]));return
    record=attempt(p,selection);require(not roles.same_process_alive(record['pid'],record['creationTicks']))
    from onoes_mind.enrollment_store import qualify_private_storage
    root=qualify_private_storage(paths[0].parent)
    destinations=[]
    for path in paths:
        qualify_private_storage(path,kind='file');require(path.parent==root)
        target=Path(str(path)+f".retired-{record['pid']}-{record['creationTicks']}")
        require(not os.path.lexists(target));destinations.append(target)
    for index in (1,2,0):os.rename(paths[index],destinations[index])


def publish_capture(window,launch,roles,p,selection,child,ticks,previous):
    until=time.monotonic()+60
    while True:
        require(child.poll() is None)
        try:window._owns_gateway(child.pid,int(p['settings']['MESH_PREVIEW_PORT']));break
        except Exception:
            require(time.monotonic()<until);time.sleep(.1)
    before=ROOT/'data'/f'capture-startup-owner-before-{child.pid}-{ticks}-{uuid.uuid4().hex}.json'
    window.publish_native_owner(child,ticks,selection['profilePath'],selection['profileSha256'],
        previous_sha256=previous,beforeimage_path=before if previous is not None else None)


def require_unoccupied_port(port):
    # Windows can take more than one second to refuse a closed loopback port.
    # Only explicit refusal proves this probe found no listener; timeout holds.
    with socket.socket() as probe:
        probe.settimeout(5)
        try:probe.connect(('127.0.0.1',int(port)))
        except ConnectionRefusedError:return
        raise StartupHold('The configured gateway port is occupied.')


def ensure_capture_first(window,*,approval_path,approval_sha):
    """Return public state and retained original handles; no hidden fallback."""
    window.assert_held();require(window.workspace==ROOT)
    approved,handoff,memory,recovery=checked_startup(approval_path,approval_sha)
    if (ROOT/'data/workroom-preview/recovery-paused').exists():
        return dict(schema='onoes-mesh-startup-state/v1',state='paused'),[]
    selected=profiles(handoff);roles=load_roles(selected['capture']);held=[]
    owner=owner_record(window,handoff,selected,roles)
    n,c=selected['connected'],selected['capture']
    # A healthy tick is observation only, not a new grant/receipt assertion.
    if owner and owner['mode']=='connected' and owner['live']:
        from mesh_native_recovery import valid_memory_peers
        peers=owner['record'].get('peers');require(valid_memory_peers(peers))
        require(peers['reader']['profileSha256']==n['readerProfileSha256']
            and peers['writer']['profileSha256']==n['projectSync']['serviceProfileSha256'])
        if all(roles.same_process_alive(peer['pid'],peer['creationTicks']) for peer in peers.values()):
            return dict(schema='onoes-mesh-startup-state/v1',state='observed_running',pid=owner['record']['pid'],
                memoryAuthorization='not_revalidated',processChanges=0),held
    import mesh_launch_candidate as launch
    cp,qualified_roles=launch.checked_launch(handoff['capture']['profilePath'],handoff['capture']['profileSha256'],handoff['capture']['approvalPath'])
    require(qualified_roles is roles and cp['ownerSid']==approved['ownerSid'])
    from onoes_mind.enrollment_store import qualify_private_storage
    qualify_private_storage(Path(approval_path),kind='file')
    if (ROOT/'data/workroom-preview/recovery-paused').exists():
        return dict(schema='onoes-mesh-startup-state/v1',state='paused'),held
    # A living connected child may be unpublished after an interrupted handoff.
    if os.path.lexists(n['attemptPath']):
        record=attempt(n,{**handoff['connected'],'mode':'connected'})
        if roles.same_process_alive(record['pid'],record['creationTicks']):
            require(owner is not None and (not owner['live'] or (owner['mode']=='connected'
                and owner['record']['pid']==record['pid'] and owner['record']['creationTicks']==record['creationTicks'])))
            import project_service_process_candidate as service
            import reader_service_process_candidate as reader_service
            try:
                result=recovery.ensure_memory(window,launch=launch,service=service,reader_service=reader_service,
                    roles=roles,profile=handoff['connected']['profilePath'],sha=handoff['connected']['profileSha256'],
                    approval=handoff['connected']['approvalPath'],approved=memory)
                return {**result,'startupMode':'connected'},held
            except Exception as error:
                held.append(error);return dict(schema='onoes-mesh-startup-state/v1',state='memory_held',pid=record['pid']),held
        # Never turn a dead unpublished connected send into a new attempt.
        require(owner and owner['mode']=='connected' and not owner['live']
            and owner['record']['pid']==record['pid'] and owner['record']['creationTicks']==record['creationTicks'])
    if not owner:
        require(not os.path.lexists(n['attemptPath']))
        if os.path.lexists(c['attemptPath']):
            unpublished=attempt(c,{**handoff['capture'],'mode':'capture'})
            require(roles.same_process_alive(unpublished['pid'],unpublished['creationTicks']))
    if owner and owner['live']:require(owner['mode']=='capture')
    if os.path.lexists(c['attemptPath']):
        current=attempt(c,{**handoff['capture'],'mode':'capture'})
        live=roles.same_process_alive(current['pid'],current['creationTicks'])
        if live:
            child=recovery.ProcessObservation(window,roles,current['pid'],current['creationTicks'],
                [c['nodeExecutable'],str(ROOT/'serve.mjs'),'--native-mind'])
            held.append(child)
            if not (owner and owner['mode']=='capture' and owner['live']):
                try:publish_capture(window,launch,roles,c,handoff['capture'],child,current['creationTicks'],owner['receiptSha256'] if owner else None)
                except Exception as error:raise StartupUnknown(held,error) from None
        else:
            require(owner is not None);retire_mode(window,c,{**handoff['capture'],'mode':'capture'},roles)
            child=None
    else:child=None
    if not child:
        require(not owner or not owner['live'])
        # Retire the last published connected owner before capture starts. Its
        # exact archived attempt remains discoverable from the unchanged receipt.
        retire_mode(window,n,{**handoff['connected'],'mode':'connected'},roles)
        require_unoccupied_port(c['settings']['MESH_PREVIEW_PORT'])
        try:
            child,ticks,record=launch.launch_mesh(handoff['capture']['profilePath'],handoff['capture']['profileSha256'],handoff['capture']['approvalPath'])
            held.append(child);publish_capture(window,launch,roles,c,handoff['capture'],child,ticks,owner['receiptSha256'] if owner else None)
        except Exception as error:raise StartupUnknown(held,error) from None
    # Capture is now published and usable before canonical memory is inspected.
    import project_service_process_candidate as service
    import reader_service_process_candidate as reader_service
    try:
        np,checked_roles=launch.inspect_launch(handoff['connected']['profilePath'],handoff['connected']['profileSha256'],handoff['connected']['approvalPath'])
        require(checked_roles is roles)
        reader,writer,children=recovery.restore_memory_roles(window,service=service,reader_service=reader_service,
            roles=roles,p=np,profile=handoff['connected']['profilePath'],approval=handoff['connected']['approvalPath'],approved=memory)
        held.extend(item[0] for item in children)
        result,new_child=recovery.handoff_capture_to_connected(window,launch=launch,service=service,roles=roles,
            approval_path=approved['handoffApprovalPath'],approval_sha=approved['handoffApprovalSha256'])
        if new_child:held.append(new_child)
        return {**result,'startupMode':'connected'},held
    except Exception as error:
        held.append(error)
        if isinstance(error,recovery.CaptureHandoffUnknown):
            actor=error.pair.mesh
            return dict(schema='onoes-mesh-startup-state/v1',state='handoff_held',pid=actor.pid if actor is not None else None,
                message='Preserve the original handoff attempt; do not relaunch.'),held
        require(child.poll() is None)
        return dict(schema='onoes-mesh-startup-state/v1',state='capture_pending',pid=child.pid,
            memoryAuthorization='not_available',message='Local board ready; memory recovery is held.'),held


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--approval',required=True);parser.add_argument('--sha256',required=True)
    args=parser.parse_args();held=[]
    try:
        approved,handoff,memory,recovery=checked_startup(args.approval,args.sha256)
        from mesh_launcher_window import MeshLauncherWindow
        with MeshLauncherWindow(ROOT,approved['sourceHashes'][str(ROOT/'integrations/restart-workroom-preview.ps1')]) as window:
            result,held=ensure_capture_first(window,approval_path=args.approval,approval_sha=args.sha256)
        print(json.dumps(result));return 0
    except StartupUnknown as error:
        held=[error]
        print(json.dumps(dict(schema='onoes-mesh-startup-state/v1',state='held',message='Preserve the original capture launch; do not relaunch.')));return 1
    except Exception as error:
        # Report code location only: exception messages/locals can contain secrets.
        frames=traceback.extract_tb(error.__traceback__)
        frame=next((item for item in reversed(frames) if item.name!='require'),frames[-1])
        print(json.dumps(dict(schema='onoes-mesh-startup-state/v1',state='held',
            failureType=type(error).__name__,failureAt=f'{Path(frame.filename).name}:{frame.lineno}',
            message='Preserve the existing startup attempts.')));return 1


if __name__=='__main__':raise SystemExit(main())
