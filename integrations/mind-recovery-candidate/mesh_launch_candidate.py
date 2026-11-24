"""Explicit Mind-enabled launch for the existing named Mesh owner launcher.

No profiles or approvals are installed. Preview never starts or stops anything.
The approval must come from Eddie; a file/reference alone is not consent.
"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[2]
SETTINGS={'MESH_PREVIEW_PORT','MESH_DATA_DIR','MESH_RELAY','MESH_RELAY_MODE','MESH_NIMS',
          'MESH_MODEL_OBSERVATION','MESH_SIMPLE_FLOW','MESH_NEMOTRON_CONTROL',
          'MESH_TAILSCALE_LOGIN','MESH_TAILSCALE_HOST','MESH_GATE_KEY_FILE'}
NATIVE_WORKER_SETTINGS={'MESH_NATIVE_WORKER_RECORD','MESH_NATIVE_WORKER_RECORD_SHA256'}


class LaunchError(RuntimeError):pass


def require(ok):
    if not ok:raise LaunchError('Native Mesh launch refused; preserve state and do not retry automatically.')


def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def check_settings(settings, *, allow_native_worker=False):
    allowed=SETTINGS | {'MESH_TRIPP_HARDWARE','MESH_AI_BOX_WINDOWS_SENSOR_HOST'}
    if allow_native_worker:
        allowed |= NATIVE_WORKER_SETTINGS
    require(type(settings) is dict and SETTINGS <= set(settings) <= allowed)
    require(all(type(v) is str and len(v)<=256 and not re.search(r'[\x00-\x1f\x7f]',v) for v in settings.values()))
    require(settings['MESH_PREVIEW_PORT'].isdigit() and 0<=int(settings['MESH_PREVIEW_PORT'])<=65535
        and re.fullmatch(r'data/[A-Za-z0-9_-]+',settings['MESH_DATA_DIR'])
        and settings['MESH_RELAY'] in ('0','1') and settings['MESH_RELAY_MODE'] in ('http','child')
        and all(settings[n] in ('0','1') for n in ('MESH_NIMS','MESH_MODEL_OBSERVATION','MESH_NEMOTRON_CONTROL'))
        and settings.get('MESH_TRIPP_HARDWARE','0') in ('0','1')
        and ('MESH_AI_BOX_WINDOWS_SENSOR_HOST' not in settings or
             re.fullmatch('[A-Za-z0-9][A-Za-z0-9-]{0,14}',settings['MESH_AI_BOX_WINDOWS_SENSOR_HOST']))
        and settings['MESH_SIMPLE_FLOW']=='0' and Path(settings['MESH_GATE_KEY_FILE']).is_absolute())
    if set(settings) & NATIVE_WORKER_SETTINGS:
        require(NATIVE_WORKER_SETTINGS <= set(settings)
            and settings['MESH_RELAY']=='1' and settings['MESH_RELAY_MODE']=='http'
            and settings['MESH_NIMS']=='1' and Path(settings['MESH_NATIVE_WORKER_RECORD']).is_absolute()
            and re.fullmatch('[0-9a-f]{64}',settings['MESH_NATIVE_WORKER_RECORD_SHA256']))


def source_paths(*, project=False, settings=None):
    paths={Path(__file__).resolve(),ROOT/'package.json',ROOT/'server.mjs',ROOT/'serve.mjs',
           ROOT/'integrations/native-mind-mesh-entry.mjs',
           ROOT/'integrations/mind-recovery-candidate/recall_process_candidate.py',
           ROOT/'integrations/restart-workroom-preview.ps1'}
    paths.update(ROOT/'integrations'/name for name in (
        'project-sync-native-candidate.mjs','project-sync-http-client-candidate.mjs',
        'project-sync-outbox-candidate.mjs','project-sync-runner-candidate.mjs',
        'workroom-project-sync-candidate.mjs'))
    for name in ('lib','public'):paths.update((ROOT/name).rglob('*.mjs'))
    if project:paths.update(Path(__file__).resolve().parent/name for name in (
        'project_mesh_input_candidate.py','project_service_process_candidate.py','project_operator_process_candidate.py'))
    if project:paths.update((ROOT/'integrations/project-sync-source-setup-candidate.mjs',ROOT/'integrations/mesh_native_recovery.py'))
    if settings and 'MESH_AI_BOX_WINDOWS_SENSOR_HOST' in settings:
        paths.update((ROOT/'config/nodes.json',ROOT/'integrations/tripp-hardware.ps1'))
    if settings and NATIVE_WORKER_SETTINGS <= set(settings):
        paths.add(ROOT/'integrations/native_gateway_transport.py')
    return paths


CAPTURE_SCHEMA='onoes-mesh-native-capture-launch/v1'

def rook_frame_fields(profile, profile_sha):
    if 'rookEnrollment' not in profile:
        return {}
    record = profile['rookEnrollment']
    require(type(record) is dict and set(record) == {'id', 'destination', 'mode', 'boardIdentity'}
            and record['id'] == 'rook' and record['destination'] == 'mesh_relay_inbox'
            and record['mode'] == 'paused' and type(record['boardIdentity']) is str
            and re.fullmatch('[0-9a-f]{64}', record['boardIdentity']) and re.fullmatch('[0-9a-f]{64}', profile_sha))
    board = ROOT / profile['settings']['MESH_DATA_DIR'] / 'tasks.sqlite'
    require(board.is_file() and board.resolve(strict=True) == board)
    node = Path(profile['nodeExecutable'])
    module = ROOT / 'lib' / 'database-identity.mjs'
    require(node.is_absolute() and node.resolve(strict=True) == node and digest(node) == profile['nodeSha256']
            and module.resolve(strict=True) == module and digest(module) == profile['sourceHashes'].get(str(module)))
    check = "import {databaseFileIdentity} from './lib/database-identity.mjs'; console.log(databaseFileIdentity(process.argv[1]));"
    env = {k:v for k,v in os.environ.items() if k.upper() not in ('NODE_OPTIONS','NODE_PATH')}
    result = subprocess.run([str(node), '--input-type=module', '-e', check, str(board)],
                            env=env, cwd=ROOT, capture_output=True, text=True, timeout=10,
                            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    require(result.returncode == 0 and result.stdout.strip() == record['boardIdentity'])
    return {'rookEnrollment': {**record, 'boardPath': str(board), 'approvalRef': profile_sha}}


def capture_source_paths(runtime,settings=None):
    # The role helpers supply file permissions/process identity only. No role
    # profile, credential, terminal proof or canonical database is opened.
    import recall_process_candidate as roles
    require(Path(roles.__file__).resolve()==Path(__file__).resolve().parent/'recall_process_candidate.py')
    return source_paths(project=True,settings=settings)|roles.source_paths(runtime)|{ROOT/'integrations/mesh_launcher_window.py'}


def capture_frame(p):
    value=p['projectCapture']
    require(type(value) is dict and set(value)=={'schema','source','storeId','links'}
        and value['schema']=='onoes-mesh-native-project-capture/v1'
        and type(value['storeId']) is str and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._:-]{0,127}',value['storeId']))
    require(len(json.dumps(value).encode('utf-8'))<=12288)
    source=value['source'];require(type(source) is dict and set(source)=={'databasePath','fileDevice','fileInode'})
    database=Path(source['databasePath']);expected=ROOT/p['settings']['MESH_DATA_DIR']/'tasks.sqlite'
    require(database.is_absolute() and database.resolve(strict=True)==database==expected
        and all(type(source[k]) is str and re.fullmatch(r'(0|[1-9][0-9]{0,19})',source[k]) for k in ('fileDevice','fileInode')))
    spec=importlib.util.find_spec('project_mesh_input_candidate')
    require(spec is not None and Path(spec.origin).resolve()==Path(__file__).resolve().parent/'project_mesh_input_candidate.py')
    from project_mesh_input_candidate import node_source_identity
    require(node_source_identity(p,database)=={k:source[k] for k in ('fileDevice','fileInode')})
    links=value['links'];require(type(links) is list and 1<=len(links)<=32)
    seen=set()
    for link in links:
        require(type(link) is dict and set(link)=={'cardId','projectId','approvalRef','fields'}
            and all(type(link[k]) is str and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._:-]{0,127}',link[k]) for k in ('cardId','projectId'))
            and link['cardId'] not in seen)
        seen.add(link['cardId']);fields=link['fields'];ref=link['approvalRef']
        require(type(ref) is str and ref.strip()==ref and 1<=len(ref)<=300 and not re.search(r'[\x00-\x1f\x7f]',ref)
            and type(fields) is list and all(type(f) is str for f in fields) and len(fields)==len(set(fields))
            and {'title','stage'}.issubset(fields) and set(fields).issubset({'title','goal','owner','stage','result','blocker'}))
    before=database.stat();db=sqlite3.connect(database.as_uri()+'?mode=ro',uri=True)
    try:
        db.execute('PRAGMA query_only=ON');db.execute('BEGIN')
        rows=db.execute('SELECT cardId,projectId,storeId,approvalRef FROM mind_project_links').fetchall()
        policies=db.execute('SELECT cardId,fields FROM mind_project_capture_policy').fetchall()
        require(len(rows)==len(links)==len(policies));by_card={link['cardId']:link for link in links};policy=dict(policies)
        for card,project,store,ref in rows:
            link=by_card.get(card);require(link is not None and project==link['projectId'] and store==value['storeId']
                and ref==link['approvalRef'] and card in policy)
            actual=json.loads(policy[card]);require(type(actual) is list and all(type(f) is str for f in actual)
                and len(actual)==len(set(actual))==len(link['fields']) and set(actual)==set(link['fields']))
        db.execute('COMMIT');require(db.total_changes==0)
    finally:db.close()
    after=database.stat();require(database.resolve(strict=True)==database and (before.st_dev,before.st_ino)==(after.st_dev,after.st_ino))
    return dict(schema='onoes-mesh-native-capture-input/v1',projectCaptureOptions=value)


def approved_environment(settings):
    # All Mesh settings come from the approved profile. Drop inherited preloads.
    env={k:v for k,v in os.environ.items() if not k.upper().startswith('MESH_')
         and k.upper() not in ('NODE_OPTIONS','NODE_PATH')}
    env.update(settings)
    return env


def check_native_worker(profile, qualify_private_storage):
    settings=profile['settings']
    if not NATIVE_WORKER_SETTINGS <= set(settings):
        return
    qualify_private_storage(Path(settings['MESH_NATIVE_WORKER_RECORD']),kind='file')
    # Reuse the actual Node binding and workspace checks. The transport is lazy
    # and no bridge runs until the server receives an authorized request.
    check="""
import {mainboardNativeConnection} from './lib/native-mainboard.mjs';
import {confinedPath, ROOT} from './server.mjs';
const native = mainboardNativeConnection({root: ROOT});
if (native.state !== 'configured') process.exit(1);
await confinedPath(native.options.profile.workspace);
"""
    result=subprocess.run([profile['nodeExecutable'],'--input-type=module','-e',check],
        cwd=ROOT,env=approved_environment(settings),capture_output=True,timeout=15,
        creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    require(result.returncode==0)


def inspect_capture(p,path,expected_sha,approval_path):
    require(os.name=='nt' and set(p)-{'rookEnrollment'}=={'schema','workspace','pythonExecutable','nodeExecutable','pythonSha256','nodeSha256',
        'sourceHashes','settings','attemptPath','stdoutPath','stderrPath','runtime','ownerSid','pwshSha256','projectCapture'})
    require(Path(p['workspace']).resolve()==ROOT and Path(p['pythonExecutable']).resolve()==Path(sys.executable).resolve()
        and digest(sys.executable)==p['pythonSha256'])
    node=Path(p['nodeExecutable']);require(node.is_absolute() and node.resolve()==node and digest(node)==p['nodeSha256'])
    runtime=p['runtime'];require(type(runtime) is dict and set(runtime)=={'python','pwsh','mindSource'}
        and Path(runtime['python']).resolve()==Path(sys.executable).resolve())
    pwsh=Path(runtime['pwsh']);require(pwsh.is_absolute() and pwsh.resolve()==pwsh and digest(pwsh)==p['pwshSha256'])
    pins=p['sourceHashes'];require(type(pins) is dict and source_paths(project=True).issubset({Path(n) for n in pins})
        and all(digest(n)==sha for n,sha in pins.items()))
    sys.path.insert(0,str(Path(runtime['mindSource'])));sys.path.insert(0,str(ROOT/'integrations'))
    require({Path(n) for n in pins}==capture_source_paths(runtime,p['settings']))
    spec=importlib.util.find_spec('onoes_mind');require(spec is not None
        and Path(spec.origin).resolve()==Path(runtime['mindSource'])/'onoes_mind/__init__.py')
    from onoes_mind.enrollment_store import qualify_private_storage
    import recall_process_candidate as roles
    qualify_private_storage(path,kind='file');root=qualify_private_storage(path.parent)
    approval_path=Path(approval_path);require(approval_path.parent==root and approval_path!=path)
    qualify_private_storage(approval_path,kind='file');approval=roles.plain_json(approval_path)
    require(approval==dict(schema='onoes-mesh-offline-capture-approval/v1',decision='approve_exact_workroom_offline_capture',
        ownerSid=p['ownerSid'],workspace=str(ROOT),profileSha256=expected_sha))
    sid=subprocess.run([str(pwsh),'-NoLogo','-NoProfile','-NonInteractive','-Command',
        '[Security.Principal.WindowsIdentity]::GetCurrent().User.Value'],capture_output=True,text=True,
        timeout=15,creationflags=subprocess.CREATE_NO_WINDOW)
    require(sid.returncode==0 and sid.stdout.strip()==p['ownerSid'])
    settings=p['settings']
    check_settings(settings)
    targets=[Path(p[n]) for n in ('attemptPath','stdoutPath','stderrPath')]
    require(len(set(targets))==3 and all(target.is_absolute() and target.parent==root
        and target not in (path,approval_path,Path(settings['MESH_GATE_KEY_FILE'])) for target in targets))
    capture_frame(p)
    rook_frame_fields(p, expected_sha)
    return p,roles


def inspect_launch(path,expected_sha,approval_path):
    # Inspect the profile and pin our imports before loading the participant code.
    path=Path(path);raw=path.read_bytes();require(len(raw)<=65536 and digest(path)==expected_sha)
    def unique(pairs):
        result={}
        for k,v in pairs:require(k not in result);result[k]=v
        return result
    p=json.loads(raw,object_pairs_hook=unique)
    require(type(p) is dict)
    if p.get('schema')==CAPTURE_SCHEMA:return inspect_capture(p,path,expected_sha,approval_path)
    project=p.get('schema')=='onoes-mesh-native-launch/v2'
    require(set(p)-{'rookEnrollment'}=={'schema','workspace','pythonExecutable','nodeExecutable',
        'pythonSha256','nodeSha256','sourceHashes','readerProfile','readerProfileSha256',
        'settings','attemptPath','stdoutPath','stderrPath'} | ({'projectSync'} if project else set()))
    require(p['schema'] in ('onoes-mesh-native-launch/v1','onoes-mesh-native-launch/v2') and Path(p['workspace']).resolve()==ROOT)
    require(Path(p['pythonExecutable']).resolve()==Path(sys.executable).resolve()
        and digest(sys.executable)==p['pythonSha256'])
    node=Path(p['nodeExecutable']);require(node.is_absolute() and node.resolve()==node and digest(node)==p['nodeSha256'])
    settings=p['settings']
    check_settings(settings,allow_native_worker=project)
    pins=p['sourceHashes'];require(type(pins) is dict and {Path(n) for n in pins}==source_paths(project=project,settings=p['settings']))
    require(all(digest(n)==s for n,s in pins.items()))
    if project:sys.path.insert(0,str(ROOT/'integrations'))
    reader_path=Path(p['readerProfile']);reader_raw=reader_path.read_bytes()
    require(len(reader_raw)<=65536 and hashlib.sha256(reader_raw).hexdigest()==p['readerProfileSha256'])
    reader_value=json.loads(reader_raw,object_pairs_hook=unique);reader_pins=reader_value['sourceHashes']
    require(type(reader_pins) is dict and all(digest(n)==s for n,s in reader_pins.items()))
    sys.path.insert(0,reader_value['runtime']['mindSource'])
    from onoes_mind.enrollment_store import qualify_private_storage
    import recall_process_candidate as roles
    qualify_private_storage(path,kind='file');root=qualify_private_storage(path.parent)
    reader,binding=roles.approved_profile(p['readerProfile'],p['readerProfileSha256'],approval_path)
    require(reader['role']=='reader' and Path(p['readerProfile']).parent==root)
    approval=roles.plain_json(approval_path);require(expected_sha in approval['profiles'])
    check_native_worker(p,qualify_private_storage)
    if 'MESH_NATIVE_WORKER_RECORD' in settings:
        require(settings['MESH_NATIVE_WORKER_RECORD'] not in
                (p['attemptPath'],p['stdoutPath'],p['stderrPath'],settings['MESH_GATE_KEY_FILE']))
    require(Path(p['attemptPath']).is_absolute() and Path(p['attemptPath']).parent==root)
    for name in ('stdoutPath','stderrPath'):
        target=Path(p[name]);require(target.is_absolute() and target.parent==root)
    require(len({p[n] for n in ('attemptPath','stdoutPath','stderrPath')})==3)
    rook_frame_fields(p, expected_sha)
    return p,roles


def checked_launch(path,expected_sha,approval_path):
    p,roles=inspect_launch(path,expected_sha,approval_path)
    # Ordinary launch still requires the live reader; inspection cannot launch.
    if p['schema']!=CAPTURE_SCHEMA:
        require(roles.reader_state(p['readerProfile'],p['readerProfileSha256'],approval_path)['ready'])
    return p,roles


def native_peers(p,roles,approval_path,options):
    from mesh_native_recovery import valid_memory_peers
    reader=roles.reader_state(p['readerProfile'],p['readerProfileSha256'],approval_path)
    require(reader['ready'] and reader['baseUrl']==options['mindRecallOptions']['baseUrl'])
    peer=options['projectSyncOptions']['destination']['peer']
    require(type(peer.get('creationTicks')) is str and peer['creationTicks'].isdecimal())
    value=dict(reader=dict(pid=reader['pid'],creationTicks=reader['creationTicks'],profileSha256=p['readerProfileSha256']),
        writer={**peer,'creationTicks':int(peer['creationTicks'])})
    require(valid_memory_peers(value) and value['writer']['profileSha256']==p['projectSync']['serviceProfileSha256'])
    return value


def native_frame(p,roles,approval_path,profile_sha):
    options = _mind_frame(p,roles,approval_path,profile_sha)
    options.update(rook_frame_fields(p, profile_sha))
    require(len(json.dumps(options).encode('utf-8')) <= 16384)
    return options


def _mind_frame(p,roles,approval_path,profile_sha):
    if p.get('schema')==CAPTURE_SCHEMA:return capture_frame(p)
    options=roles.native_options(p['readerProfile'],p['readerProfileSha256'],approval_path)
    if p.get('schema')!='onoes-mesh-native-launch/v2':
        return dict(schema='onoes-mesh-native-recall-input/v1',mindRecallOptions=options)
    spec=importlib.util.find_spec('project_mesh_input_candidate')
    require(spec is not None and spec.origin is not None and Path(spec.origin).resolve()==
        Path(__file__).resolve().parent/'project_mesh_input_candidate.py')
    from project_mesh_input_candidate import project_native_options
    project=project_native_options(p,profile_sha)
    require(options['binding']['storeId']==project['destination']['storeId'])
    return dict(schema='onoes-mesh-native-input/v2',mindRecallOptions=options,projectSyncOptions=project)


def launch_mesh(path,expected_sha,approval_path):
    p,roles=checked_launch(path,expected_sha,approval_path)
    # Reserve all owned records before a child exists; leftovers block a retry.
    attempt_path=roles.new_role_file(p['attemptPath'])
    try:
        with attempt_path.open('xb') as attempt:
            for name in ('stdoutPath','stderrPath'):
                with roles.new_role_file(p[name]).open('xb'):pass
            options=native_frame(p,roles,approval_path,expected_sha)
            peers=None
            if p.get('schema')=='onoes-mesh-native-launch/v2':
                peers=native_peers(p,roles,approval_path,options)
            env=approved_environment(p['settings'])
            with open(p['stdoutPath'],'ab') as out,open(p['stderrPath'],'ab') as err:
                child=subprocess.Popen([p['nodeExecutable'],str(ROOT/'serve.mjs'),'--native-mind'],
                    cwd=ROOT,env=env,stdin=subprocess.PIPE,stdout=out,stderr=err,
                    creationflags=subprocess.CREATE_NO_WINDOW)
            stamp=None
            try:
                record=dict(schema='onoes-mesh-native-child/v1',profileSha256=expected_sha,pid=child.pid,
                    creationTicks=None,executable=p['nodeExecutable'],entryPoint=str(ROOT/'serve.mjs'),
                    state='identity_pending',credentialsInRecord=False)
                if p.get('schema')==CAPTURE_SCHEMA:record.update(schema='onoes-mesh-native-child/v3',mode='capture_only')
                if peers is not None:record.update(schema='onoes-mesh-native-child/v2',peers=peers)
                attempt.write(json.dumps(record).encode());attempt.flush();os.fsync(attempt.fileno())
                stamp=roles.creation_ticks(child._handle)
                record.update(creationTicks=stamp,state='input_pending');attempt.seek(0);attempt.truncate()
                attempt.write(json.dumps(record).encode());attempt.flush();os.fsync(attempt.fileno())
                child.stdin.write(json.dumps(options).encode())
                child.stdin.close();options=None
                record['state']='input_sent';attempt.seek(0);attempt.truncate()
                attempt.write(json.dumps(record).encode());attempt.flush();os.fsync(attempt.fileno())
            except Exception:
                try:child.stdin.close()
                except Exception:pass
                # Keep the original handle and durable attempt. Never kill/retry.
                raise roles.RoleLaunchUnknown(child,stamp) from None
            return child,stamp,record
    except Exception:raise


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--profile',required=True)
    parser.add_argument('--sha256',required=True);parser.add_argument('--approval',required=True)
    parser.add_argument('--launch',action='store_true');args=parser.parse_args()
    try:
        if args.launch:
            child,stamp,record=launch_mesh(args.profile,args.sha256,args.approval)
            print(json.dumps(record))
        else:
            p,roles=checked_launch(args.profile,args.sha256,args.approval)
            require(not Path(p['attemptPath']).exists() and not Path(p['stdoutPath']).exists()
                    and not Path(p['stderrPath']).exists())
            # Check current token/grant revocation before the owner launcher can
            # stop Mesh. The secret result stays in this short-lived process.
            native_frame(p,roles,args.approval,args.sha256)
            print(json.dumps(dict(ready=True,createsNothing=True,settings=p['settings'],nodeExecutable=p['nodeExecutable'])))
    except Exception:
        print(json.dumps(dict(ready=False,error='Native Mesh launch refused; preserve the private attempt and do not retry.')))
        return 1
    return 0


if __name__=='__main__':raise SystemExit(main())
