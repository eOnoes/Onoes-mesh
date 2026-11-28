"""Finite approved Windows canonical-owner operation for Cyony only.

Cold process, supported writer lease/authority/custody APIs, no service changes,
listeners, model calls or retries. Source-only imports are inert. The enclosing
installer supplies a separately approved, source-pinned private plan.
"""
from contextlib import closing
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import traceback


ACCESS={'agentId':'cyony','privateScope':'agent/cyony/private',
        'readerPrincipal':'context-cyony','sharedProject':'onoes-mesh','sharedReadOnly':True,
        'curatedSources':['MEMORY.md','USER.md']}


class OwnerHeld(RuntimeError):
    pass


def require(ok):
    if not ok:
        raise OwnerHeld('Canonical owner operation is unconfirmed; retain exact custody and evidence')


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _same_archive_path(reported,approved):
    # Pure comparison of the native reported archive spelling against the
    # reviewed approved archive. No filesystem access, no alias acceptance.
    try:
        for value in (reported,approved):
            if type(value) is not str or not value or '\x00' in value:
                return False
            if any(component in ('.','..') for component in re.split('[\\\\/]',value)):
                return False
        if not (Path(reported).is_absolute() and Path(approved).is_absolute()):
            return False
        return Path(reported)==Path(approved)
    except Exception:
        return False


def read(path):
    path=Path(path)
    require(path.is_absolute() and path.resolve(strict=True)==path and path.stat().st_size<=262144)
    def unique(pairs):
        result={}
        for key,value in pairs:
            require(key not in result);result[key]=value
        return result
    result=json.loads(path.read_bytes(),object_pairs_hook=unique)
    require(type(result) is dict)
    return result


def approved_inputs(action,plan_path,pin,authorization_path):
    require(os.name=='nt' and sys.flags.isolated==1 and sys.dont_write_bytecode
            and action in ('admit','revoke') and type(pin) is str and re.fullmatch('[a-f0-9]{64}',pin))
    require(digest(plan_path)==pin)
    plan=read(plan_path)
    require(plan['schema']=='onoes-cloud-owner-operation/v1' and plan['access']==ACCESS
            and read(authorization_path)=={'schema':'onoes-cloud-owner-operation-authorization/v1',
                'owner':'Eddie','decision':'approve_cyony_private_home_and_mesh_reader','planSha256':pin})
    require(Path(sys.executable).resolve()==Path(plan['python']).resolve(strict=True)
            and digest(__file__)==plan['executors']['cloud_owner_entry.py'])
    sdk=Path(plan['sdk']);workspace=Path(plan['workspace'])
    require(all(p.is_absolute() and p.resolve(strict=True)==p for p in (sdk,workspace)))
    native=workspace/'integrations/mind-recovery-candidate'
    required={native/name for name in ('project_service_process_candidate.py','project_operator_process_candidate.py',
        'native_project_sync_candidate.py','checkpointed_ledger_candidate.py','persistent_authority.py','recall_process_candidate.py')}
    required.update((sdk/'onoes_mind').rglob('*.py'))
    required.update((sdk/'onoes_mind/migrations').glob('*.sql'))
    require(sdk/'onoes_mind/__init__.py' in required and all(str(p) in plan['sourcePins'] for p in required))
    for name,expected in plan['sourcePins'].items():
        p=Path(name);require(p.is_absolute() and p.resolve(strict=True)==p and digest(p)==expected)
    for name in ('cloud_owner_phase.py','cloud_enrollment.py','cloud_curated_transfer.py'):
        require(digest(Path(__file__).with_name(name))==plan['executors'][name])
    for item in (plan['writer'],plan['writerApproval'],plan['operator']):
        require(digest(item['path'])==item['sha256'])
    before=read(plan['beforeBackupResult'])
    require(before['status']=='backup_complete_inactive' and before['archiveRehearsal']=='PASS')
    backup=plan['beforeBackup'];require(digest(backup['entryPath'])==backup['entrySha256']
            and digest(backup['profilePath'])==backup['profileSha256'])
    backup_profile=read(backup['profilePath'])
    require(backup_profile['resultPath']==plan['beforeBackupResult']
            and backup_profile['encryptedBackup']==plan['beforeArchive']
            and _same_archive_path(before['archive'],plan['beforeArchive'])
            and digest(plan['beforeArchive'])==before['archiveSha256'])
    require(before['profileSha256']==backup['profileSha256'])
    require(type(plan['attemptId']) is str and re.fullmatch('[a-z0-9][a-z0-9_-]{0,95}',plan['attemptId']))
    return plan


def run(action,plan_path,pin,authorization_path):
    plan=approved_inputs(action,plan_path,pin,authorization_path)
    # Verify the actual completed archive in its original frozen SDK process.
    # Importing that backup runtime into this owner process would violate the
    # native SDK/module-origin boundary during the server SDK transition.
    backup=plan['beforeBackup']
    verified=subprocess.run([sys.executable,'-I','-B',backup['entryPath'],
        '--profile',backup['profilePath'],'--sha',backup['profileSha256'],'--verify-archive'],
        stdin=subprocess.DEVNULL,capture_output=True,timeout=120,creationflags=subprocess.CREATE_NO_WINDOW)
    require(verified.returncode==0)
    verification=json.loads(verified.stdout)
    require(verification['status']=='archive_verified' and _same_archive_path(verification['archive'],plan['beforeArchive'])
            and verification['sourceLedgerOpened'] is False)
    sdk=Path(plan['sdk']);workspace=Path(plan['workspace'])
    sys.path[:0]=[str(Path(__file__).parent),str(workspace/'integrations/mind-recovery-candidate'),str(sdk)]
    import onoes_mind
    require(Path(onoes_mind.__file__).resolve().parents[1]==sdk)
    import project_service_process_candidate as service
    import recall_process_candidate as roles
    from native_project_sync_candidate import ProjectServiceLease
    from checkpointed_ledger_candidate import CheckpointedLedgerCandidate
    from persistent_authority import AuthorityBinding,PersistentAuthorityCandidate
    from onoes_mind.agent_home import WindowsAgentHomeCustody
    from onoes_mind.context_host import WindowsReaderCustody
    from onoes_mind.context_enrollment import WindowsOperatorCustody
    from onoes_mind.recall_binding import RecallBinding
    from onoes_mind.runtime_keys import unprotect_runtime_keys
    from onoes_mind.enrollment_store import qualify_private_storage
    import cloud_owner_phase as phase
    require(Path(phase.__file__).resolve()==Path(__file__).with_name('cloud_owner_phase.py').resolve())
    for path in (plan_path,authorization_path):qualify_private_storage(Path(path),kind='file')
    evidence=qualify_private_storage(Path(plan['evidence']))
    profile,base,binding=service.checked_profile(plan['writer']['path'],plan['writer']['sha256'],plan['writerApproval']['path'])
    backup_binding=read(backup['profilePath'])['binding']
    require(all(backup_binding[k]==getattr(binding,k) for k in (
        'database_path','store_id','environment','authority_ref','file_device','file_inode')))
    homes=service.profile_agent_homes(profile,binding)
    require([h.agent_id for h in homes]==['cyony','deep','echo'])
    home=homes[0]
    readers=service.profile_project_readers(profile,binding,base)
    require(len(readers)==1)
    shared,grant=readers[0]
    require(shared.principal_id=='context-cyony' and shared.project_id=='onoes-mesh' and home.store==shared.store)
    require(grant.path.read_bytes()==grant.document())
    private=WindowsAgentHomeCustody(qualify_private_storage(Path(plan['privateCustody'])),home)
    reader=WindowsReaderCustody(qualify_private_storage(Path(plan['sharedCustody'])),shared)
    operator=read(plan['operator']['path'])
    operator_store=RecallBinding(**operator['binding'])
    require(all(getattr(operator_store,k)==getattr(home.store,k) for k in (
        'database_path','store_id','environment','authority_ref','file_device','file_inode')))
    custodian=WindowsOperatorCustody(Path(plan['operator']['path']).parent,operator_store)
    # Retain fingerprints of existing protected files; never log their contents.
    existing={str(Path(p)):digest(p) for p in plan['preservedCustody']}
    require(str(custodian.path) in existing and str(Path(base['credentialPath'])) in existing)
    prepared=origin=None
    if action=='admit':
        from cloud_curated_transfer import decode,stage
        capture=read(plan['curatedCaptureReceipt'])
        require(capture['schema']=='onoes-cloud-curated-capture/v1' and capture['verified'] is True
                and capture['approvedSourceIdentities']==plan['curatedSourceIdentities'])
        transport=Path(plan['curatedTransport']);qualify_private_storage(transport,kind='file')
        snapshot=decode(transport.read_bytes(),expected_sha256=capture['transportSha256'])
        require({n:list(v['identity']) for n,v in snapshot.metadata.items()}==plan['curatedSourceIdentities'])
        prepared=stage(snapshot,Path(plan['curatedStage']),home);origin=snapshot.descriptor()
    writer=keys=token=None
    with closing(ProjectServiceLease(binding)):
        try:
            package=roles.plain_json(base['keyEnrollmentPath'],16384)
            keys=unprotect_runtime_keys(package['runtime_envelope'],store_id=binding.store_id,environment_id=binding.environment)
            authority=PersistentAuthorityCandidate(AuthorityBinding(**roles.plain_json(base['authorityBindingPath'])))
            writer=CheckpointedLedgerCandidate(binding.database_path,base['historyPath'],authority,
                store_id=binding.store_id,environment=binding.environment,**keys)
            token=custodian.read();require(writer.authenticate(token)=='operator')
            options=dict(operator_token=token,evidence=evidence,attempt_id=plan['attemptId'],review_sha256=pin)
            if action=='admit':
                result=phase.admit(writer,home,shared,private,reader,**options,prepared_curated=prepared,remote_origin=origin)
            else:
                result=phase.revoke(writer,home,shared,private,reader,**options)
            require(writer.integrity_report()['status']=='PASS'
                    and all(digest(p)==expected for p,expected in existing.items()))
        finally:
            if writer is not None:writer.close()
            keys=token=None
    return {'verified':True,'action':action,'state':result.get('state','new_access_revoked'),
            'existingCustodyUnchanged':True,'modelCalls':0}


if __name__=='__main__':
    try:
        require(len(sys.argv)==5)
        print(json.dumps(run(*sys.argv[1:]),sort_keys=True),flush=True)
    except Exception as error:
        print('Canonical owner operation held; preserve custody and receipts. Do not repeat.',file=sys.stderr)
        print(json.dumps({'errorType':type(error).__name__,'frames':[
            {'file':Path(f.filename).name,'function':f.name,'line':f.lineno}
            for f in traceback.extract_tb(error.__traceback__)[-12:]],'messagesAndLocalsExcluded':True}),file=sys.stderr)
        raise SystemExit(1)
