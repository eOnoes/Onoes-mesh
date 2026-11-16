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
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[2]
SETTINGS={'MESH_PREVIEW_PORT','MESH_DATA_DIR','MESH_RELAY','MESH_RELAY_MODE','MESH_NIMS',
          'MESH_MODEL_OBSERVATION','MESH_SIMPLE_FLOW','MESH_NEMOTRON_CONTROL',
          'MESH_TAILSCALE_LOGIN','MESH_TAILSCALE_HOST','MESH_GATE_KEY_FILE'}


class LaunchError(RuntimeError):pass


def require(ok):
    if not ok:raise LaunchError('Native Mesh launch refused; preserve state and do not retry automatically.')


def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def source_paths(*, project=False):
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
    return paths


def inspect_launch(path,expected_sha,approval_path):
    # Inspect the profile and pin our imports before loading the participant code.
    path=Path(path);raw=path.read_bytes();require(len(raw)<=65536 and digest(path)==expected_sha)
    def unique(pairs):
        result={}
        for k,v in pairs:require(k not in result);result[k]=v
        return result
    p=json.loads(raw,object_pairs_hook=unique)
    require(type(p) is dict)
    project=p.get('schema')=='onoes-mesh-native-launch/v2'
    require(set(p)=={'schema','workspace','pythonExecutable','nodeExecutable',
        'pythonSha256','nodeSha256','sourceHashes','readerProfile','readerProfileSha256',
        'settings','attemptPath','stdoutPath','stderrPath'} | ({'projectSync'} if project else set()))
    require(p['schema'] in ('onoes-mesh-native-launch/v1','onoes-mesh-native-launch/v2') and Path(p['workspace']).resolve()==ROOT)
    require(Path(p['pythonExecutable']).resolve()==Path(sys.executable).resolve()
        and digest(sys.executable)==p['pythonSha256'])
    node=Path(p['nodeExecutable']);require(node.is_absolute() and node.resolve()==node and digest(node)==p['nodeSha256'])
    pins=p['sourceHashes'];require(type(pins) is dict and {Path(n) for n in pins}==source_paths(project=project))
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
    settings=p['settings'];require(type(settings) is dict and set(settings)==SETTINGS
        and all(type(v) is str and len(v)<=256 and not re.search(r'[\x00-\x1f\x7f]',v) for v in settings.values()))
    require(settings['MESH_PREVIEW_PORT'].isdigit() and 0<=int(settings['MESH_PREVIEW_PORT'])<=65535
        and re.fullmatch(r'data/[A-Za-z0-9_-]+',settings['MESH_DATA_DIR'])
        and settings['MESH_RELAY'] in ('0','1') and settings['MESH_RELAY_MODE'] in ('http','child')
        and all(settings[n] in ('0','1') for n in ('MESH_NIMS','MESH_MODEL_OBSERVATION','MESH_NEMOTRON_CONTROL'))
        and settings['MESH_SIMPLE_FLOW']=='0')
    require(Path(settings['MESH_GATE_KEY_FILE']).is_absolute())
    require(Path(p['attemptPath']).is_absolute() and Path(p['attemptPath']).parent==root)
    for name in ('stdoutPath','stderrPath'):
        target=Path(p[name]);require(target.is_absolute() and target.parent==root)
    require(len({p[n] for n in ('attemptPath','stdoutPath','stderrPath')})==3)
    return p,roles


def checked_launch(path,expected_sha,approval_path):
    p,roles=inspect_launch(path,expected_sha,approval_path)
    # Ordinary launch still requires the live reader; inspection cannot launch.
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
            # Do not inherit a preload or ambient Mesh enrollment override.
            env={k:v for k,v in os.environ.items() if not k.upper().startswith('MESH_')
                 and k.upper() not in ('NODE_OPTIONS','NODE_PATH')}
            env.update(p['settings'])
            with open(p['stdoutPath'],'ab') as out,open(p['stderrPath'],'ab') as err:
                child=subprocess.Popen([p['nodeExecutable'],str(ROOT/'serve.mjs'),'--native-mind'],
                    cwd=ROOT,env=env,stdin=subprocess.PIPE,stdout=out,stderr=err,
                    creationflags=subprocess.CREATE_NO_WINDOW)
            stamp=None
            try:
                record=dict(schema='onoes-mesh-native-child/v1',profileSha256=expected_sha,pid=child.pid,
                    creationTicks=None,executable=p['nodeExecutable'],entryPoint=str(ROOT/'serve.mjs'),
                    state='identity_pending',credentialsInRecord=False)
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
