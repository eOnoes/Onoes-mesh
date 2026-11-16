"""Source-pinned long-lived project service; preview is the default.

No live profile, approval or startup entry is installed by this module. Client
exports retain peer identity and must not be stripped into an unattested HTTP
transport. The Mesh connection-level peer guard is a separate activation gate.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import uuid
from urllib.parse import urlsplit

HERE = Path(__file__).resolve().parent
SCHEMA = 'onoes-mind-project-service/v1'


class ServiceProcessError(RuntimeError):
    pass


class ServiceLaunchUnknown(ServiceProcessError):
    def __init__(self,child,stamp):
        super().__init__('Project service launch is uncertain; retain its handle and do not retry.')
        self.child,self.creation_ticks = child,stamp


def require(ok):
    if not ok: raise ServiceProcessError('Private project service refused; preserve existing state.')


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def unique(pairs):
    result={}
    for key,value in pairs: require(key not in result);result[key]=value
    return result


def checked_profile(path,expected_sha,approval_path=None):
    require(os.name=='nt')
    path=Path(path)
    with path.open('rb') as source: raw=source.read(65537)
    require(len(raw)<=65536 and hashlib.sha256(raw).hexdigest()==expected_sha)
    p=json.loads(raw,object_pairs_hook=unique)
    require(type(p) is dict and set(p)=={'schema','sourceHashes','operatorProfilePath','operatorProfileSha256',
        'attemptPath','readyPath','stopPath'} and p['schema']==SCHEMA)
    required={Path(__file__).resolve(),HERE/'project_operator_process_candidate.py'}
    require(type(p['sourceHashes']) is dict and {Path(n) for n in p['sourceHashes']}==required
        and all(type(h) is str and re.fullmatch('[0-9a-f]{64}',h) and digest(n)==h for n,h in p['sourceHashes'].items()))
    # Bootstrap only the verified operator validator, which verifies its complete
    # canonical/candidate dependency set before importing any participant.
    sys.path.insert(0,str(HERE))
    import project_operator_process_candidate as operator
    base,binding=operator.checked_profile(p['operatorProfilePath'],p['operatorProfileSha256'],approval_path)
    require(base['mode'] in ('first_setup','replace'))
    from onoes_mind.enrollment_store import qualify_private_storage
    from checkpoint_candidate import read_plain
    import recall_process_candidate as roles
    qualify_private_storage(path,kind='file');root=qualify_private_storage(path.parent)
    require(read_plain(path,65536)==raw and Path(p['operatorProfilePath']).parent==root)
    targets=[p[n] for n in ('attemptPath','readyPath','stopPath')]
    require(len(set(targets))==3)
    occupied={base[n] for n in ('attemptPath','terminalPath','outcomePath','credentialPath')}
    occupied.update((str(path),p['operatorProfilePath'],str(approval_path)))
    for value in targets:
        target=Path(value);require(target.is_absolute() and target.parent==root and '..' not in target.parts and value not in occupied)
    if approval_path is not None:
        approval=roles.plain_json(approval_path)
        require('run_service' in approval['actions'] and expected_sha in approval['profiles']
            and approval['storeId']==binding.store_id and approval['scopeId']==operator.SCOPE
            and approval['projects']==[v[0] for v in base['projects']] and approval['reviewRef']==base['reviewRef'])
    return p,base,binding


def terminal_proof(base,binding,operator_sha):
    import recall_process_candidate as roles
    from onoes_mind.enrollment_store import qualify_private_storage
    for name in ('terminalPath','outcomePath','attemptPath','credentialPath'):
        qualify_private_storage(Path(base[name]),kind='file')
    terminal=roles.plain_json(base['terminalPath']);attempt=roles.plain_json(base['attemptPath'])
    expected='provisioned_inactive' if base['mode']=='first_setup' else 'replaced_inactive'
    require(terminal.get('schema')=='onoes-mind-project-operator-terminal/v1'
        and terminal.get('profileSha256')==operator_sha and terminal.get('exitCode')==0
        and terminal.get('operationId')==base['operationId'] and terminal.get('mode')==base['mode']
        and terminal.get('storeId')==binding.store_id and terminal.get('environment')==binding.environment
        and attempt.get('profileSha256')==operator_sha and attempt.get('state')=='started'
        and attempt.get('pid')==terminal.get('pid') and attempt.get('creationTicks')==terminal.get('creationTicks'))
    require(not roles.same_process_alive(terminal['pid'],terminal['creationTicks']))
    require(digest(base['outcomePath'])==terminal['outcomeSha256'])
    outcome=roles.plain_json(base['outcomePath'])
    require(outcome.get('status')==expected and outcome.get('operationId')==base['operationId']
        and outcome.get('storeId')==binding.store_id and outcome.get('environment')==binding.environment
        and outcome.get('projects')==[v[0] for v in base['projects']]
        and outcome.get('principal')=='mesh-project-sync' and outcome.get('serviceStarted') is False
        and outcome.get('runtimeEnrollment') is False and outcome.get('credentialIssued') is True)
    require(digest(base['credentialPath'])==terminal['credentialFileSha256']==outcome['credentialStorage']['fileSha256'])


def stop_target(p,run_id):
    require(type(run_id) is str and re.fullmatch('[0-9a-f]{32}',run_id))
    path=Path(p['stopPath']);return path.with_name(path.name+'.'+run_id)


def _retire_previous(p,profile_sha):
    import recall_process_candidate as roles
    from onoes_mind.enrollment_store import qualify_private_storage
    attempt=Path(p['attemptPath']);ready=Path(p['readyPath']);root=attempt.parent.resolve(strict=True)
    if not os.path.lexists(attempt):
        require(not os.path.lexists(ready));return
    qualify_private_storage(attempt,kind='file');old=roles.plain_json(attempt)
    require(old.get('schema')=='onoes-mind-project-service-attempt/v1' and old.get('profileSha256')==profile_sha
        and old.get('state')=='started')
    stop=stop_target(p,old['runId'])
    require(not roles.same_process_alive(old['pid'],old['creationTicks']))
    paths=[attempt]
    if os.path.lexists(ready):
        qualify_private_storage(ready,kind='file');record=roles.plain_json(ready)
        require(record.get('profileSha256')==profile_sha and record.get('runId')==old['runId']
            and record.get('pid')==old['pid'] and record.get('creationTicks')==old['creationTicks']
            and record.get('state') in ('starting','running','stopped','failed'))
        paths.append(ready)
    if os.path.lexists(stop):
        qualify_private_storage(stop,kind='file')
        require(roles.plain_json(stop)==dict(profileSha256=profile_sha,runId=old['runId'],pid=old['pid'],creationTicks=old['creationTicks'],stop=True))
        paths.append(stop)
    moves=[]
    for source in paths:
        destination=source.with_name(source.name+'.retired-'+old['runId'])
        require(source.resolve(strict=True).parent==root and destination.parent.resolve(strict=True)==root
                and not os.path.lexists(destination))
        moves.append((source,destination))
    # Fixed private files only; no deletion/overwrite or recursive move. On
    # Windows rename refuses an existing destination. Partial archival is held.
    for source,destination in moves:os.rename(source,destination)


def launch_service(profile_path,profile_sha,approval_path):
    require(approval_path is not None)
    p,base,binding=checked_profile(profile_path,profile_sha,approval_path)
    terminal_proof(base,binding,p['operatorProfileSha256'])
    import recall_process_candidate as roles
    from native_project_sync_candidate import ProjectServiceLease
    lease=ProjectServiceLease(binding);child=stamp=None
    try:
        _retire_previous(p,profile_sha)
        run_id=uuid.uuid4().hex
        roles.new_role_file(p['readyPath']);roles.new_role_file(stop_target(p,run_id))
        record=dict(schema='onoes-mind-project-service-attempt/v1',profileSha256=profile_sha,runId=run_id,state='reserved')
        roles.private_new_json(p['attemptPath'],record)
        env={k:v for k,v in os.environ.items() if k.upper() not in ('PYTHONPATH','PYTHONHOME','PYTHONSTARTUP')}
        child=subprocess.Popen([sys.executable,'-I',str(Path(__file__).resolve()),'--profile',str(profile_path),
            '--sha256',profile_sha,'--approval',str(approval_path),'--run'],env=env,cwd=HERE,
            stdin=subprocess.PIPE,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=subprocess.CREATE_NO_WINDOW)
        def save():
            with Path(p['attemptPath']).open('w',encoding='utf-8') as output:
                json.dump(record,output);output.flush();os.fsync(output.fileno())
        record.update(pid=child.pid,creationTicks=None,state='identity_pending');save()
        stamp=roles.creation_ticks(child._handle);record.update(creationTicks=stamp,state='started');save()
        lease.close();lease=None
        child.stdin.write(b'START\n');child.stdin.flush();return child,stamp
    except Exception:
        if child is not None:raise ServiceLaunchUnknown(child,stamp) from None
        raise
    finally:
        if lease is not None:lease.close()
        if child is not None:
            try:child.stdin.close()
            except OSError:pass


def service_role(p,base,binding,profile_sha):
    require(sys.stdin.readline().strip()=='START')
    import recall_process_candidate as roles
    from onoes_mind.enrollment_store import qualify_private_storage
    qualify_private_storage(Path(p['attemptPath']),kind='file')
    attempt=roles.plain_json(p['attemptPath'])
    require(attempt.get('profileSha256')==profile_sha and attempt.get('pid')==os.getpid()
        and attempt.get('creationTicks')==roles.current_ticks() and attempt.get('state')=='started')
    terminal_proof(base,binding,p['operatorProfileSha256'])
    from onoes_mind.runtime_keys import unprotect_runtime_keys
    from persistent_authority import AuthorityBinding,PersistentAuthorityCandidate
    from native_project_sync_candidate import NativeProjectSyncHost
    stop=stop_target(p,attempt['runId'])
    record=dict(schema='onoes-mind-project-service-owner/v1',profileSha256=profile_sha,runId=attempt['runId'],
        pid=os.getpid(),creationTicks=attempt['creationTicks'],state='starting',storeId=binding.store_id,
        environment=binding.environment,projects=[v[0] for v in base['projects']],scopeId='project/onoes-mind/shared')
    host=keys=None
    with Path(p['readyPath']).open('x',encoding='utf-8') as output:
        qualify_private_storage(Path(p['readyPath']),kind='file')
        def save():
            output.seek(0);json.dump(record,output,indent=2);output.write('\n');output.truncate();output.flush();os.fsync(output.fileno())
        save()
        try:
            for name in ('keyEnrollmentPath','authorityBindingPath','historyPath'):qualify_private_storage(Path(base[name]),kind='file')
            package=roles.plain_json(base['keyEnrollmentPath'],16384)
            require(set(package)=={'schema','storeId','environment','recovery_envelope','runtime_envelope'}
                and package['schema']=='onoes-mind-key-enrollment/v1' and package['storeId']==binding.store_id
                and package['environment']==binding.environment)
            keys=unprotect_runtime_keys(package['runtime_envelope'],store_id=binding.store_id,environment_id=binding.environment)
            authority=PersistentAuthorityCandidate(AuthorityBinding(**roles.plain_json(base['authorityBindingPath'])))
            host=NativeProjectSyncHost(binding=binding,history_path=base['historyPath'],authority=authority,**keys,
                credential_path=base['credentialPath'],project_ids=tuple(v[0] for v in base['projects']),review_ref=base['reviewRef'])
            host.start();address,port=host.server.address
            require(address=='127.0.0.1');record.update(state='running',baseUrl=f'http://127.0.0.1:{port}/');save()
            while True:
                if os.path.lexists(stop):
                    qualify_private_storage(stop,kind='file')
                    require(roles.plain_json(stop)==dict(profileSha256=profile_sha,runId=attempt['runId'],pid=os.getpid(),creationTicks=attempt['creationTicks'],stop=True))
                    break
                require(host.status()['ready']);time.sleep(0.2)
            host.close();record['state']='stopped';save()
        except Exception:
            record['state']='failed'
            try:save()
            except Exception:pass
            raise
        finally:
            if host is not None:host.close()
            keys=None


def service_state(profile_path,profile_sha,approval_path):
    require(approval_path is not None)
    p,base,binding=checked_profile(profile_path,profile_sha,approval_path)
    import recall_process_candidate as roles
    from onoes_mind.enrollment_store import qualify_private_storage
    qualify_private_storage(Path(p['readyPath']),kind='file');record=roles.plain_json(p['readyPath'])
    qualify_private_storage(Path(p['attemptPath']),kind='file');attempt=roles.plain_json(p['attemptPath'])
    require(record.get('schema')=='onoes-mind-project-service-owner/v1' and record.get('profileSha256')==profile_sha
        and attempt.get('schema')=='onoes-mind-project-service-attempt/v1'
        and attempt.get('profileSha256')==profile_sha and attempt.get('state')=='started'
        and record.get('runId')==attempt.get('runId') and record.get('pid')==attempt.get('pid')
        and record.get('creationTicks')==attempt.get('creationTicks') and record.get('storeId')==binding.store_id
        and record.get('environment')==binding.environment and record.get('scopeId')=='project/onoes-mind/shared'
        and record.get('projects')==[v[0] for v in base['projects']])
    stop_target(p,record['runId'])
    live=roles.same_process_alive(record['pid'],record['creationTicks'])
    return {**record,'processLive':live,'ready':live and record.get('state')=='running'}


def native_options(profile_path,profile_sha,approval_path):
    """Secret input + mandatory peer metadata for an attested native transport."""
    p,base,binding=checked_profile(profile_path,profile_sha,approval_path)
    terminal_proof(base,binding,p['operatorProfileSha256'])
    state=service_state(profile_path,profile_sha,approval_path);require(state['ready'])
    url=urlsplit(state['baseUrl'])
    require(url.scheme=='http' and url.hostname=='127.0.0.1' and url.port and 1<=url.port<=65535
        and not url.username and not url.password and url.path=='/' and not url.query and not url.fragment)
    from native_project_sync_candidate import load_project_client_credential
    token=load_project_client_credential(base['credentialPath'],binding=binding,
        project_ids=tuple(v[0] for v in base['projects']),review_ref=base['reviewRef'])
    return dict(schema='onoes-mind-project-client-input/v1',destination=dict(baseUrl=state['baseUrl'],token=token,storeId=binding.store_id),
        peer=dict(pid=state['pid'],creationTicks=str(state['creationTicks']),runId=state['runId'],profileSha256=profile_sha))


def request_stop(profile_path,profile_sha,approval_path):
    p,_,_=checked_profile(profile_path,profile_sha,approval_path)
    state=service_state(profile_path,profile_sha,approval_path);require(state['processLive'])
    import recall_process_candidate as roles
    roles.private_new_json(stop_target(p,state['runId']),dict(profileSha256=profile_sha,runId=state['runId'],pid=state['pid'],creationTicks=state['creationTicks'],stop=True))


def main():
    parser=argparse.ArgumentParser(description='Project service profile: preview only by default.')
    parser.add_argument('--profile',required=True);parser.add_argument('--sha256',required=True)
    parser.add_argument('--approval');parser.add_argument('--run',action='store_true');args=parser.parse_args()
    try:
        require(not args.run or args.approval is not None)
        p,base,binding=checked_profile(args.profile,args.sha256,args.approval if args.run else None)
        if not args.run:
            print(json.dumps(dict(status='preview',createsNothing=True,needsOwnerApproval=True)));return 0
        service_role(p,base,binding,args.sha256);return 0
    except Exception:
        print(json.dumps(dict(status='refused',preserveState=True,automaticRetry=False)));return 1


if __name__=='__main__':sys.exit(main())
