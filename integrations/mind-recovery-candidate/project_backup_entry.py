"""Owner-invoked backup window for an existing Mind store; inactive by default."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys

HERE=Path(__file__).resolve().parent
SCHEMA='onoes-mind-existing-backup-window/v1'
DECISION='approve_exact_mind_existing_backup'
WINDOWS_LOCAL='windows-local'


def require(ok):
    if not ok: raise ValueError('Mind backup window validation failed; preserve existing files.')


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def unique(pairs):
    out={}
    for k,v in pairs:
        require(k not in out);out[k]=v
    return out


def source_paths(runtime):
    require(type(runtime) is dict and set(runtime)=={'python','pwsh','mindSource'})
    base=Path(runtime['mindSource'])
    require(base.is_absolute() and base.resolve()==base and (base/'onoes_mind/__init__.py').is_file())
    paths={Path(runtime['python']).resolve(),Path(runtime['pwsh']).resolve()}
    paths.update(p for p in HERE.glob('*.py') if not p.name.startswith('test'))
    paths.update(HERE.glob('*.ps1'))
    for pattern in ('*.py','*.mjs','*.ps1','migrations/*.sql'):
        paths.update((base/'onoes_mind').glob(pattern))
    return paths


def checked_profile(path,expected_sha,approval_path=None):
    require(os.name=='nt');path=Path(path)
    require(path.is_absolute() and path.resolve()==path)
    with path.open('rb') as stream:raw=stream.read(65537)
    require(len(raw)<=65536 and hashlib.sha256(raw).hexdigest()==expected_sha)
    p=json.loads(raw,object_pairs_hook=unique)
    require(type(p) is dict and set(p)-{'archiveCredentialMode'}=={'schema','ownerSid','runtime','sourceHashes','binding',
        'keyEnrollmentPath','authorityBindingPath','historyPath','sourceDirectory','stagingDirectory',
        'rehearsalDirectory','encryptedBackup','archiveTool','attemptPath','resultPath','reviewRef','writerGate'}
        and p['schema']==SCHEMA and p.get('archiveCredentialMode','operator') in ('operator',WINDOWS_LOCAL))
    pins=p['sourceHashes'];require(type(pins) is dict and {Path(n) for n in pins}==source_paths(p['runtime'])
        and all(type(h) is str and re.fullmatch('[a-f0-9]{64}',h) and digest(n)==h for n,h in pins.items())
        and Path(p['runtime']['python']).resolve()==Path(sys.executable).resolve())
    sys.path.insert(0,str(HERE));sys.path.insert(0,p['runtime']['mindSource'])
    for name,expected in [('onoes_mind',Path(p['runtime']['mindSource'])/'onoes_mind/__init__.py'),
        *[(n,HERE/(n+'.py')) for n in ('recall_process_candidate','project_backup_candidate',
            'checkpointed_ledger_candidate','checkpoint_candidate','persistent_authority','operator_setup_entry','encrypted_backup_candidate')]]:
        spec=importlib.util.find_spec(name);require(spec is not None and Path(spec.origin).resolve()==expected)
    from onoes_mind.enrollment_store import qualify_private_storage
    from checkpoint_candidate import read_plain
    from project_events_candidate import EventBinding,identifier
    qualify_private_storage(path,kind='file');root=qualify_private_storage(path.parent)
    require(read_plain(path,65536)==raw)
    b=EventBinding(**p['binding']);require(identifier(b.store_id) and identifier(b.environment)
        and type(b.authority_ref) is str and 1<=len(b.authority_ref)<=300)
    database=qualify_private_storage(Path(b.database_path),kind='file')
    require(database.resolve()==database);s=database.stat();require((s.st_dev,s.st_ino)==(b.file_device,b.file_inode))
    require(Path(p['keyEnrollmentPath'])==database.parent/'key-enrollment.json'
        and Path(p['authorityBindingPath'])==database.parent/'checkpoint-authority-binding.json'
        and Path(p['historyPath'])==Path(str(database)+'.deletions.jsonl'))
    for name in ('keyEnrollmentPath','authorityBindingPath','historyPath'):qualify_private_storage(Path(p[name]),kind='file')
    folders=[qualify_private_storage(Path(p[n])) for n in ('sourceDirectory','stagingDirectory','rehearsalDirectory')]
    require(all(not any(f.iterdir()) and f.is_absolute() and f.resolve()==f
        and not f.is_relative_to(database.parent) and not database.parent.is_relative_to(f) for f in folders)
        and all(not a.is_relative_to(b) and not b.is_relative_to(a) for i,a in enumerate(folders) for b in folders[i+1:]))
    outputs=[Path(p[n]) for n in ('attemptPath','resultPath')]
    if p.get('archiveCredentialMode')==WINDOWS_LOCAL:
        outputs.append(Path(p['resultPath']).with_suffix('.archive.dpapi'))
    require(len(set(outputs))==len(outputs) and all(n.is_absolute() and n.parent==root and n.resolve()==n and not os.path.lexists(n) for n in outputs))
    archive=Path(p['encryptedBackup']);require(archive.is_absolute() and archive.suffix.lower()=='.7z'
        and archive.parent.is_dir() and archive.resolve()==archive and not os.path.lexists(archive)
        and all(not archive.is_relative_to(f) for f in [database.parent,*folders]))
    from encrypted_backup_candidate import TOOL_SHA256
    require(digest(p['archiveTool'])==TOOL_SHA256 and Path(p['archiveTool']).resolve()==Path(p['archiveTool']))
    require(type(p['reviewRef']) is str and 1<=len(p['reviewRef'])<=240 and not re.search(r'[\x00-\x1f\x7f]',p['reviewRef']))
    sid=subprocess.run([p['runtime']['pwsh'],'-NoLogo','-NoProfile','-NonInteractive','-Command',
        '[Security.Principal.WindowsIdentity]::GetCurrent().User.Value'],capture_output=True,text=True,
        timeout=15,creationflags=subprocess.CREATE_NO_WINDOW)
    require(sid.returncode==0 and sid.stdout.strip()==p['ownerSid'])
    writer_gate(p,b)
    if approval_path is not None:
        a=json.loads(read_plain(qualify_private_storage(Path(approval_path),kind='file'),65536),object_pairs_hook=unique)
        require(a==dict(decision=DECISION,ownerSid=p['ownerSid'],profileSha256=expected_sha,
            storeId=b.store_id,environment=b.environment,reviewRef=p['reviewRef']))
    return p,b


def writer_gate(p,b):
    import recall_process_candidate as roles
    from onoes_mind.enrollment_store import qualify_private_storage
    gate=p['writerGate'];require(type(gate) is dict and set(gate)=={'kind','attemptPath','readyPath','profileSha256'}
        and gate['kind'] in ('not_started','stopped') and type(gate['profileSha256']) is str
        and re.fullmatch('[a-f0-9]{64}',gate['profileSha256']))
    a,r=Path(gate['attemptPath']),Path(gate['readyPath'])
    require(a!=r and all(n.is_absolute() and n.resolve()==n and n.parent.is_dir() for n in (a,r)))
    if gate['kind']=='not_started':require(not os.path.lexists(a) and not os.path.lexists(r));return
    for n in (a,r):qualify_private_storage(n,kind='file')
    attempt=roles.plain_json(a);ready=roles.plain_json(r)
    require(attempt.get('schema')=='onoes-mind-project-service-attempt/v1' and attempt.get('state')=='started'
        and ready.get('schema')=='onoes-mind-project-service-owner/v1' and ready.get('state')=='stopped'
        and ready.get('storeId')==b.store_id and ready.get('environment')==b.environment
        and all(attempt.get(n)==ready.get(n) for n in ('profileSha256','runId','pid','creationTicks'))
        and attempt.get('profileSha256')==gate['profileSha256']
        and type(attempt.get('runId')) is str and re.fullmatch('[A-Za-z0-9:_-]{1,100}',attempt['runId'])
        and ready.get('scopeId')=='project/onoes-mind/shared'
        and type(attempt.get('pid')) is int and attempt['pid']>0
        and type(attempt.get('creationTicks')) is int and attempt['creationTicks']>0
        and not roles.same_process_alive(attempt['pid'],attempt['creationTicks']))


def preview(path,sha):
    p,b=checked_profile(path,sha)
    return dict(schema=SCHEMA,ready=True,storeId=b.store_id,environment=b.environment,
        encryptedBackup=p['encryptedBackup'],createsNothing=True,keysRead=False,sourceLedgerOpened=False,
        sourcePins=len(p['sourceHashes']),writerGate=p['writerGate']['kind'],
        archiveCredentialMode=p.get('archiveCredentialMode','operator'))


def windows_backup_password(path,profile_sha,*,create=False):
    """Use a sealed per-archive secret on the same Windows account."""
    from checkpoint_candidate import read_plain
    from encrypted_backup_candidate import save_new
    from onoes_mind.enrollment_store import qualify_private_storage
    from onoes_mind.runtime_keys import _crypt

    require(type(profile_sha) is str and re.fullmatch('[a-f0-9]{64}',profile_sha))
    destination=Path(path)
    entropy=hashlib.sha256(b'onoes-mind/local-archive/v1\0'+bytes.fromhex(profile_sha)).digest()
    if create:
        qualify_private_storage(destination.parent)
        password=secrets.token_hex(32)
        save_new(destination,_crypt(password.encode('ascii'),entropy,protect=True))
    data=read_plain(qualify_private_storage(destination,kind='file'),2048)
    recovered=_crypt(data,entropy,protect=False).decode('ascii')
    require(re.fullmatch('[a-f0-9]{64}',recovered) and (not create or recovered==password))
    return recovered


def run_backup(path,sha,approval_path,password=None):
    p,b=checked_profile(path,sha,approval_path)
    import recall_process_candidate as roles
    from checkpoint_candidate import publish_snapshot_candidate,read_plain
    from checkpointed_ledger_candidate import CheckpointedLedgerCandidate
    from persistent_authority import AuthorityBinding,PersistentAuthorityCandidate
    from onoes_mind.runtime_keys import unprotect_runtime_keys
    from project_backup_candidate import archive_prepared_project_backup
    from encrypted_backup_candidate import password_bytes,save_new
    local=p.get('archiveCredentialMode')==WINDOWS_LOCAL
    if local:require(password is None)
    else:password_bytes(password)
    record=dict(schema=SCHEMA,profileSha256=sha,pid=os.getpid(),
        creationTicks=roles.current_ticks(),state='started',phase='keys')
    roles.private_new_json(p['attemptPath'],record)
    def phase(name,state='started'):
        # Retain only a password-free phase on the exact exclusive owned attempt.
        from onoes_mind.enrollment_store import qualify_private_storage
        target=qualify_private_storage(Path(p['attemptPath']),kind='file')
        with target.open('r+',encoding='utf-8') as marker:
            require(json.load(marker)==record)
            record.update(phase=name,state=state);marker.seek(0);json.dump(record,marker)
            marker.truncate();marker.flush();os.fsync(marker.fileno())
    ledger=keys=None
    try:
        writer_gate(p,b)
        if local:
            phase('archive_custody')
            custody=Path(p['resultPath']).with_suffix('.archive.dpapi')
            password=windows_backup_password(custody,sha,create=True)
        package=json.loads(read_plain(Path(p['keyEnrollmentPath']),16384),object_pairs_hook=unique)
        require(set(package)=={'schema','storeId','environment','recovery_envelope','runtime_envelope'}
            and package['schema']=='onoes-mind-key-enrollment/v1' and package['storeId']==b.store_id
            and package['environment']==b.environment)
        authority=PersistentAuthorityCandidate(AuthorityBinding(**roles.plain_json(p['authorityBindingPath'])))
        keys=unprotect_runtime_keys(package['runtime_envelope'],store_id=b.store_id,environment_id=b.environment)
        ledger=CheckpointedLedgerCandidate(b.database_path,p['historyPath'],authority,store_id=b.store_id,
            environment=b.environment,**keys)
        source=Path(p['sourceDirectory'])
        phase('snapshot')
        publication=publish_snapshot_candidate(ledger,source/'project-snapshot.sqlite',authority,
            store_id=b.store_id,environment=b.environment)
        ledger.close();ledger=None;keys=None
        save_new(source/'encrypted-key-enrollment.json',(json.dumps(package)+'\n').encode());package=None
        save_new(source/'snapshot-deletion-history.jsonl',read_plain(Path(p['historyPath']),4*1024*1024))
        phase('archive')
        result=archive_prepared_project_backup(source,p['stagingDirectory'],p['rehearsalDirectory'],
            p['encryptedBackup'],p['archiveTool'],password,publication=publication,authority=authority,
            review_ref=p['reviewRef'])
        writer_gate(p,b)
        require(digest(path)==sha and all(digest(n)==h for n,h in p['sourceHashes'].items()))
        stat=Path(b.database_path).stat();require((stat.st_dev,stat.st_ino)==(b.file_device,b.file_inode))
        result.update(windowSchema=SCHEMA,profileSha256=sha,status='backup_complete_inactive',
            sourceLedgerOpened=True,newKeysCreated=False,newCredentialsCreated=False,serviceStarted=False)
        if local:
            result.update(archiveCredentialMode=WINDOWS_LOCAL,archiveCredentialPath=str(custody))
        phase('result')
        roles.private_new_json(p['resultPath'],result)
        phase('complete','complete')
        return result
    except Exception:
        # No guessed cleanup, retry, secret-bearing exception text or false success.
        try:phase(record['phase'],'failed_outcome_unknown')
        except Exception:pass
        raise RuntimeError('Backup did not complete. Preserve this attempt and its artifacts for review; do not rerun.') from None
    finally:
        if ledger is not None:ledger.close()
        keys=password=None


def main(argv=None):
    parser=argparse.ArgumentParser(description='Preview or explicitly back up an existing Mind store; never initializes one.')
    parser.add_argument('--profile',required=True);parser.add_argument('--sha',required=True)
    parser.add_argument('--approval');parser.add_argument('--run',action='store_true')
    a=parser.parse_args(argv)
    if not a.run:print(json.dumps(preview(a.profile,a.sha),indent=2));return 0
    require(a.approval is not None)
    profile,_=checked_profile(a.profile,a.sha,a.approval)
    from project_backup_candidate import prompt_archive_password
    password=None
    try:
        if profile.get('archiveCredentialMode')==WINDOWS_LOCAL:
            print('Backing up Mind with Windows account protection. No password entry is needed.',flush=True)
        else:
            print('Backing up the existing Mind store. Enter your saved archive password locally. Access remains unchanged.',flush=True)
            password=prompt_archive_password()
        result=run_backup(a.profile,a.sha,a.approval,password)
        print('Backup COMPLETE. Encrypted backup and recovery readback passed.')
        print('Encrypted backup: '+result['archive'])
        return 0
    finally:password=None


if __name__=='__main__':
    try:raise SystemExit(main())
    except Exception:
        print('Backup did not complete. Keep this window and its artifacts for Nims. Do not rerun or share a password.',file=sys.stderr)
        raise SystemExit(1)
