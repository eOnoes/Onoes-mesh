"""Explicit native role processes; default CLI preview creates nothing.

No live profile/approval is supplied here. The native caller must record genuine
owner authorization for exact private profile hashes. This is a trusted local
operator boundary, not isolation from hostile same-login/admin processes.
"""
import argparse
import ctypes
from ctypes import wintypes
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time


SCHEMA='onoes-mind-native-role/v1'
DECISION='approve_exact_shared_readonly_mind_enrollment_and_reader'
REVOKE_DECISION='approve_exact_mesh_recall_credential_revocation'
HERE=Path(__file__).resolve().parent


class RoleError(RuntimeError):pass


class RoleLaunchUnknown(RoleError):
    def __init__(self,child,stamp):
        super().__init__('Owned native role launch is uncertain; retain this handle and do not retry.')
        self.child=child;self.creation_ticks=stamp


def require(ok):
    if not ok:raise RoleError('Private native Mind role refused; preserve state and do not retry automatically.')


def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def unique(pairs):
    result={}
    for key,value in pairs:require(key not in result);result[key]=value
    return result


def plain_json(path,limit=65536):
    from checkpoint_candidate import read_plain
    return json.loads(read_plain(Path(path),limit),object_pairs_hook=unique)


def source_paths(runtime):
    package=Path(importlib.util.find_spec('onoes_mind').origin).resolve().parent
    require(package==Path(runtime['mindSource']).resolve()/'onoes_mind')
    required={Path(__file__).resolve(),Path(runtime['python']).resolve(),Path(runtime['pwsh']).resolve()}
    required.update(HERE/name for name in ('native_recall_candidate.py','provision_recall_candidate.py',
        'checkpointed_ledger_candidate.py','checkpoint_candidate.py','persistent_authority.py'))
    for pattern in ('*.py','*.mjs','*.ps1','migrations/*.sql'):required.update(package.glob(pattern))
    return required


def creation_ticks(handle):
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.GetProcessTimes.argtypes=[wintypes.HANDLE]+[ctypes.POINTER(wintypes.FILETIME)]*4
    stamps=[wintypes.FILETIME() for _ in range(4)]
    require(kernel.GetProcessTimes(wintypes.HANDLE(int(handle)),*(ctypes.byref(t) for t in stamps)))
    return (stamps[0].dwHighDateTime<<32)|stamps[0].dwLowDateTime


def current_ticks():
    kernel=ctypes.WinDLL('kernel32',use_last_error=True);kernel.GetCurrentProcess.restype=wintypes.HANDLE
    return creation_ticks(kernel.GetCurrentProcess())


def same_process_alive(pid,started):
    require(type(pid) is int and pid>0 and type(started) is int and started>0)
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD];kernel.OpenProcess.restype=wintypes.HANDLE
    kernel.CloseHandle.argtypes=[wintypes.HANDLE]
    kernel.WaitForSingleObject.argtypes=[wintypes.HANDLE,wintypes.DWORD]
    handle=kernel.OpenProcess(0x1000|0x100000,False,pid)
    if not handle:
        require(ctypes.get_last_error()==87)  # Access-denied/observation failure is not retirement.
        return False
    try:
        if creation_ticks(handle)!=started:return False  # PID reused after the original retired.
        wait=kernel.WaitForSingleObject(handle,0);require(wait in (0,258))
        return wait==258
    finally:kernel.CloseHandle(handle)


def checked_profile(path,expected_sha,approval_path=None):
    require(os.name=='nt')
    path=Path(path)
    with path.open('rb') as input_file:raw=input_file.read(65537)
    require(len(raw)<=65536 and hashlib.sha256(raw).hexdigest()==expected_sha)
    value=json.loads(raw,object_pairs_hook=unique)
    common={'schema','role','ownerSid','runtime','sourceHashes','binding','credentialPath','outcomePath',
            'terminalPath','operationId','reviewRef'}
    extra={'operator':{'keyEnrollmentPath','authorityBindingPath','historyPath','attemptPath'},
           'revoker':{'keyEnrollmentPath','authorityBindingPath','historyPath','attemptPath'},
           'reader':{'operatorProfileSha256','readyPath','stopPath'}}
    require(type(value) is dict and value.get('schema')==SCHEMA and value.get('role') in extra)
    require(set(value)==common|extra[value['role']])
    runtime=value['runtime'];require(type(runtime) is dict and set(runtime)=={'python','pwsh','mindSource'})
    require(Path(runtime['python']).resolve()==Path(sys.executable).resolve())
    pins=value['sourceHashes'];require(type(pins) is dict)
    require({Path(p).resolve() for p in pins}==source_paths(runtime))
    for filename,sha in pins.items():require(type(sha) is str and digest(filename)==sha)
    # Import participant code only after the exact required source hashes pass.
    from onoes_mind.enrollment_store import qualify_private_storage
    from onoes_mind.recall_binding import RecallBinding
    from native_recall_candidate import context
    qualify_private_storage(path,kind='file');root=qualify_private_storage(path.parent)
    binding=RecallBinding(**value['binding']);context(binding)
    require(value['reviewRef']==binding.review_ref)
    require(type(value['operationId']) is str and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._:-]{0,127}',value['operationId']))
    database=qualify_private_storage(Path(binding.database_path),kind='file')
    info=database.stat();require((info.st_dev,info.st_ino)==(binding.file_device,binding.file_inode))
    data_root=database.parent
    require(not root.is_relative_to(data_root) and not data_root.is_relative_to(root))
    for name in ('credentialPath','outcomePath','terminalPath')+tuple(extra[value['role']]-{'operatorProfileSha256','keyEnrollmentPath','authorityBindingPath','historyPath'}):
        target=Path(value[name]);require(target.is_absolute() and target.parent==root and '..' not in target.parts)
    if value['role'] in ('operator','revoker'):
        require(Path(value['keyEnrollmentPath'])==data_root/'key-enrollment.json'
                and Path(value['authorityBindingPath'])==data_root/'checkpoint-authority-binding.json'
                and Path(value['historyPath'])==Path(str(database)+'.deletions.jsonl'))
    sid=subprocess.run([runtime['pwsh'],'-NoLogo','-NoProfile','-NonInteractive','-Command',
        '[Security.Principal.WindowsIdentity]::GetCurrent().User.Value'],capture_output=True,text=True,
        timeout=15,creationflags=subprocess.CREATE_NO_WINDOW)
    require(sid.returncode==0 and sid.stdout.strip()==value['ownerSid'])
    if approval_path is not None:
        qualify_private_storage(Path(approval_path),kind='file');approval=plain_json(approval_path)
        require(set(approval)=={'decision','ownerSid','profiles','scopeId','reviewRef'}
            and approval['decision']==(REVOKE_DECISION if value['role']=='revoker' else DECISION) and approval['ownerSid']==value['ownerSid']
            and type(approval['profiles']) is list and expected_sha in approval['profiles']
            and approval['scopeId']==binding.scope_id and approval['reviewRef']==binding.review_ref)
    return value,binding


def approved_profile(path,expected_sha,approval_path):
    require(approval_path is not None)
    return checked_profile(path,expected_sha,approval_path)


def private_new_json(path,value):
    from onoes_mind.enrollment_store import qualify_private_storage
    path=Path(path);qualify_private_storage(path.parent)
    with path.open('x',encoding='utf-8') as output:
        json.dump(value,output,indent=2);output.write('\n');output.flush();os.fsync(output.fileno())
    qualify_private_storage(path,kind='file')


def new_role_file(path):
    from provision_recall_candidate import new_private_file
    try:return new_private_file(path)
    except Exception:raise RoleError('Native role target already exists or private custody was refused.') from None


def operator_role(profile,binding,profile_sha):
    require(sys.stdin.readline().strip()=='START')
    from onoes_mind.enrollment_store import qualify_private_storage
    qualify_private_storage(Path(profile['attemptPath']),kind='file')
    attempt=plain_json(profile['attemptPath'])
    require(attempt.get('profileSha256')==profile_sha and attempt.get('pid')==os.getpid()
            and attempt.get('creationTicks')==current_ticks())
    from onoes_mind.runtime_keys import unprotect_runtime_keys
    from checkpointed_ledger_candidate import CheckpointedLedgerCandidate
    from persistent_authority import AuthorityBinding,PersistentAuthorityCandidate
    from provision_recall_candidate import provision_reader,revoke_reader
    writer=keys=None
    try:
        for name in ('keyEnrollmentPath','authorityBindingPath','historyPath'):
            qualify_private_storage(Path(profile[name]),kind='file')
        package=plain_json(profile['keyEnrollmentPath'],16384)
        require(set(package)=={'schema','storeId','environment','recovery_envelope','runtime_envelope'}
                and package['schema']=='onoes-mind-key-enrollment/v1'
                and package['storeId']==binding.store_id and package['environment']==binding.environment)
        keys=unprotect_runtime_keys(package['runtime_envelope'],store_id=binding.store_id,environment_id=binding.environment)
        authority=PersistentAuthorityCandidate(AuthorityBinding(**plain_json(profile['authorityBindingPath'])))
        writer=CheckpointedLedgerCandidate(Path(binding.database_path),Path(profile['historyPath']),authority,
            store_id=binding.store_id,environment=binding.environment,**keys)
        if profile['role']=='revoker':
            revoke_reader(writer,binding=binding,outcome_path=profile['outcomePath'],
                operation_id=profile['operationId'],approval_ref=profile['reviewRef'])
        else:
            provision_reader(writer,binding=binding,credential_path=profile['credentialPath'],
                outcome_path=profile['outcomePath'],operation_id=profile['operationId'],approval_ref=profile['reviewRef'])
    finally:
        if writer is not None:writer.close()
        keys=None


def terminal_proof(profile,binding):
    from onoes_mind.enrollment_store import qualify_private_storage
    qualify_private_storage(Path(profile['terminalPath']),kind='file')
    receipt=plain_json(profile['terminalPath'])
    require(set(receipt)=={'operatorProfileSha256','pid','creationTicks','exitCode','operationId','storeId','outcomeSha256'})
    require(receipt['operatorProfileSha256']==profile['operatorProfileSha256'] and receipt['exitCode']==0
            and receipt['operationId']==profile['operationId'] and receipt['storeId']==binding.store_id)
    require(not same_process_alive(receipt['pid'],receipt['creationTicks']))
    qualify_private_storage(Path(profile['outcomePath']),kind='file')
    require(digest(profile['outcomePath'])==receipt['outcomeSha256'])
    outcome=plain_json(profile['outcomePath'])
    require(outcome.get('status')=='provisioned_inactive' and outcome.get('operationId')==profile['operationId']
            and outcome.get('storeId')==binding.store_id and outcome.get('scopeId')==binding.scope_id)
    require(digest(profile['credentialPath'])==outcome['credentialStorage']['fileSha256'])


def reader_role(profile,binding,profile_sha):
    terminal_proof(profile,binding)
    from native_recall_candidate import NativeRecallHost
    from onoes_mind.enrollment_store import qualify_private_storage
    require(not os.path.lexists(profile['stopPath']))
    host=NativeRecallHost(binding=binding,credential_path=profile['credentialPath'])
    record=dict(schema='onoes-mind-reader-owner/v1',profileSha256=profile_sha,pid=os.getpid(),
        creationTicks=current_ticks(),state='starting',storeId=binding.store_id,scopeId=binding.scope_id)
    output=None
    try:
        output=Path(profile['readyPath']).open('x',encoding='utf-8')
        qualify_private_storage(Path(profile['readyPath']),kind='file')
        def save():
            output.seek(0);json.dump(record,output,indent=2);output.write('\n');output.truncate();output.flush();os.fsync(output.fileno())
        save();ready=host.start();require(ready['running'])
        record.update(state='running',baseUrl=ready['baseUrl'],readOnly=True);save()
        while True:
            if os.path.lexists(profile['stopPath']):
                qualify_private_storage(Path(profile['stopPath']),kind='file')
                stop=plain_json(profile['stopPath']);require(stop=={'profileSha256':profile_sha,'stop':True})
                break
            require(host.status()['running']);time.sleep(0.2)
        host.close();record['state']='stopped';save()
    finally:
        host.close()
        if output is not None:output.close()


def launch_operator(profile_path,profile_sha,approval_path):
    profile,binding=approved_profile(profile_path,profile_sha,approval_path);require(profile['role'] in ('operator','revoker'))
    names=('attemptPath','outcomePath','terminalPath') if profile['role']=='revoker' else ('attemptPath','credentialPath','outcomePath','terminalPath')
    for name in names:new_role_file(profile[name])
    # Reserve before creating a privileged process; never silently clear a prior attempt.
    private_new_json(profile['attemptPath'],dict(profileSha256=profile_sha,state='reserved'))
    child=subprocess.Popen([sys.executable,str(Path(__file__).resolve()),'--profile',str(profile_path),
        '--sha256',profile_sha,'--approval',str(approval_path),'--run'],stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=subprocess.CREATE_NO_WINDOW)
    stamp=None
    try:
        stamp=creation_ticks(child._handle)
        # This is only our freshly reserved marker, before START can reach the child.
        with Path(profile['attemptPath']).open('w',encoding='utf-8') as output:
            json.dump(dict(profileSha256=profile_sha,pid=child.pid,creationTicks=stamp,state='started'),output)
            output.flush();os.fsync(output.fileno())
        child.stdin.write(b'START\n');child.stdin.flush()
    except Exception:
        raise RoleLaunchUnknown(child,stamp) from None
    finally:
        try:child.stdin.close()
        except OSError:pass
    return child,stamp


def finish_operator(child,stamp,profile_path,profile_sha,approval_path):
    # Observation timeout must be handled by the caller retaining this same handle.
    # No wait timeout, kill, retry or replacement attempt is hidden here.
    require(child.poll()==0 and creation_ticks(child._handle)==stamp)
    profile,binding=approved_profile(profile_path,profile_sha,approval_path);require(profile['role'] in ('operator','revoker'))
    from onoes_mind.enrollment_store import qualify_private_storage
    qualify_private_storage(Path(profile['outcomePath']),kind='file')
    qualify_private_storage(Path(profile['attemptPath']),kind='file')
    attempt=plain_json(profile['attemptPath'])
    require(attempt.get('profileSha256')==profile_sha and attempt.get('pid')==child.pid
            and attempt.get('creationTicks')==stamp)
    outcome=plain_json(profile['outcomePath'])
    expected='revoked' if profile['role']=='revoker' else 'provisioned_inactive'
    require(outcome.get('status')==expected and outcome.get('operationId')==profile['operationId']
            and outcome.get('storeId')==binding.store_id)
    receipt=dict(operatorProfileSha256=profile_sha,pid=child.pid,creationTicks=stamp,exitCode=0,
        operationId=profile['operationId'],storeId=binding.store_id,outcomeSha256=digest(profile['outcomePath']))
    private_new_json(profile['terminalPath'],receipt)
    return receipt


def launch_reader(profile_path,profile_sha,approval_path):
    profile,binding=approved_profile(profile_path,profile_sha,approval_path);require(profile['role']=='reader')
    terminal_proof(profile,binding)
    new_role_file(profile['readyPath']);new_role_file(profile['stopPath'])
    child=subprocess.Popen([sys.executable,str(Path(__file__).resolve()),'--profile',str(profile_path),
        '--sha256',profile_sha,'--approval',str(approval_path),'--run'],stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=subprocess.CREATE_NO_WINDOW)
    try:return child,creation_ticks(child._handle)
    except Exception:raise RoleLaunchUnknown(child,None) from None


def reader_state(profile_path,profile_sha,approval_path):
    profile,binding=approved_profile(profile_path,profile_sha,approval_path);require(profile['role']=='reader')
    from onoes_mind.enrollment_store import qualify_private_storage
    qualify_private_storage(Path(profile['readyPath']),kind='file');record=plain_json(profile['readyPath'])
    require(record.get('profileSha256')==profile_sha and record.get('storeId')==binding.store_id
            and record.get('scopeId')==binding.scope_id)
    live=same_process_alive(record['pid'],record['creationTicks'])
    return {**record,'processLive':live,'ready':live and record.get('state')=='running'}


def native_options(profile_path,profile_sha,approval_path):
    """Secret result for inherited native IPC only; never print it."""
    profile,binding=approved_profile(profile_path,profile_sha,approval_path)
    state=reader_state(profile_path,profile_sha,approval_path);require(state['ready'])
    from native_recall_candidate import load_service_credential
    return dict(baseUrl=state['baseUrl'],token=load_service_credential(profile['credentialPath'],binding=binding),
        binding=dict(servicePrincipal='mesh-recall',storeId=binding.store_id,environment=binding.environment,
                     scopeId=binding.scope_id,reviewRef=binding.review_ref))


def request_stop(profile_path,profile_sha,approval_path):
    profile,_=approved_profile(profile_path,profile_sha,approval_path);require(profile['role']=='reader')
    state=reader_state(profile_path,profile_sha,approval_path);require(state['processLive'])
    private_new_json(profile['stopPath'],{'profileSha256':profile_sha,'stop':True})


def main():
    parser=argparse.ArgumentParser(description='Native Mind role candidate: default private-profile preview only.')
    parser.add_argument('--profile',required=True);parser.add_argument('--sha256',required=True)
    parser.add_argument('--approval');parser.add_argument('--run',action='store_true');args=parser.parse_args()
    try:
        require(not args.run or args.approval is not None)
        profile,binding=checked_profile(args.profile,args.sha256,args.approval if args.run else None)
        if not args.run:
            print(json.dumps(dict(status='preview',role=profile['role'],createsNothing=True,needsOwnerApproval=True)));return 0
        if profile['role'] in ('operator','revoker'):operator_role(profile,binding,args.sha256)
        else:reader_role(profile,binding,args.sha256)
        return 0
    except Exception:
        print(json.dumps(dict(status='refused',message='Native Mind role did not complete; preserve state. No automatic retry or cleanup.')))
        return 1


if __name__=='__main__':raise SystemExit(main())
