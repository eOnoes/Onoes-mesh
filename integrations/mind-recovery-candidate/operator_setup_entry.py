"""Inactive, local operator entry. Default is read-only preview, never setup.

Use the reviewed canonical Mind package on PYTHONPATH. No password/key CLI flags,
automatic directory creation, permission changes, service setup or retries.
"""
import argparse
import getpass
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import uuid
import warnings


class SetupEntryError(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise SetupEntryError(message)


def reference(value):
    require(isinstance(value, str) and 0 < len(value) <= 256 and value.strip() == value
            and not any(ord(c) < 32 for c in value), 'An explicit review reference is required.')
    return value


def preview_setup(arguments):
    """Read metadata/ACLs only; do not create directories, keys or a database."""
    from onoes_mind.enrollment_store import qualify_private_storage
    require(re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,127}', arguments.environment_id),
            'An explicit environment identifier is required.')
    refs={name:reference(getattr(arguments,name)) for name in ('owner_ref','authority_ref','review_ref')}
    roots={name:qualify_private_storage(Path(getattr(arguments,name))) for name in
           ('directory','authority_directory','backup_directory','archive_staging_directory','archive_rehearsal_directory')}
    selected=[]
    identities={}
    for name,root in roots.items():
        require(root.resolve(strict=True)==root, 'An existing canonical location is required.')
        require(not any(root.iterdir()), 'All five private destinations must be empty.')
        require(not any(root.is_relative_to(other) or other.is_relative_to(root) for other in selected),
                'Select separate, disjoint private directories.')
        selected.append(root)
        info=root.stat()
        identities[name]=[info.st_dev,info.st_ino]
    from encrypted_backup_candidate import TOOL_SHA256
    from checkpoint_candidate import read_plain
    tool=Path(arguments.archive_tool)
    require(tool.is_absolute() and not tool.is_symlink() and not (tool.stat().st_file_attributes&0x400)
            and hashlib.sha256(read_plain(tool,16*1024*1024)).hexdigest()==TOOL_SHA256,
            'Reviewed portable archive tool required.')
    archive=Path(arguments.encrypted_backup)
    require(archive.is_absolute() and '..' not in archive.parts and archive.suffix.lower()=='.7z'
            and archive.parent.is_dir() and archive.parent.resolve()==archive.parent
            and not os.path.lexists(archive) and not any(archive.is_relative_to(root) for root in roots.values()),
            'Separate absent encrypted archive destination required.')
    parent_info=archive.parent.stat();tool_info=tool.stat()
    return dict(schema='onoes-mind-setup-preview/v1', action='preview', ready=True,
                directories={name:str(root) for name,root in roots.items()},
                directoryIdentities=identities, environment=arguments.environment_id,
                references=refs, ownerApprovalRequired=True, activated=False,
                runtimeEnrollment=False, createsNothing=True,encryptedBackup=str(archive),
                archiveParentIdentity=[parent_info.st_dev,parent_info.st_ino],
                archiveToolIdentity=[tool_info.st_dev,tool_info.st_ino],archiveToolSha256=TOOL_SHA256)


def initialize(arguments):
    # Lazy import: --help and module import cannot start enrollment or require GUI.
    from operator_setup_candidate import initialize_checkpointed_candidate
    return initialize_checkpointed_candidate(**{
        name:getattr(arguments,name) for name in
        ('directory','authority_directory','backup_directory','environment_id',
         'owner_ref','authority_ref','review_ref')})


def archive_password():
    # Fail closed if getpass would fall back to echoed input. Never accept a
    # password from command arguments, environment, browser or an agent channel.
    with warnings.catch_warnings():
        warnings.simplefilter('error',getpass.GetPassWarning)
        return getpass.getpass('Saved encrypted-backup password (hidden): ')


def finish_encrypted_backup(arguments, result, password):
    from onoes_mind.enrollment_store import qualify_private_storage
    from onoes_mind.runtime_keys import unprotect_runtime_keys
    from checkpoint_candidate import SnapshotReceipt,read_plain
    from checkpointed_ledger_candidate import restore_checkpointed_candidate
    from persistent_authority import AuthorityBinding,PersistentAuthorityCandidate
    from encrypted_backup_candidate import export_encrypted_backup_candidate,unpack_encrypted_backup_candidate,save_new
    publication=SnapshotReceipt(**result['publication'])
    export=export_encrypted_backup_candidate(arguments.backup_directory,arguments.archive_staging_directory,
        arguments.encrypted_backup,arguments.archive_tool,password,publication=publication)
    unpack_encrypted_backup_candidate(arguments.encrypted_backup,arguments.archive_rehearsal_directory,
        arguments.archive_tool,password,expected_archive_sha256=export['archiveSha256'],publication=publication)
    recovered=Path(arguments.archive_rehearsal_directory)
    package=json.loads(read_plain(recovered/'encrypted-key-enrollment.json',16384))
    require(package['storeId']==result['storeId'] and package['environment']==arguments.environment_id,
            'Archive key context mismatch.')
    keys=unprotect_runtime_keys(package['runtime_envelope'],store_id=result['storeId'],
                               environment_id=arguments.environment_id)
    restored=None
    try:
        authority=PersistentAuthorityCandidate(AuthorityBinding(**result['authorityBinding']))
        restored=restore_checkpointed_candidate(recovered/'snapshot.sqlite',recovered/'verified-restored.sqlite',
            None,authority,**keys,store_id=result['storeId'],environment=arguments.environment_id,
            review_ref=arguments.review_ref)
        require(restored.integrity_report()['status']=='PASS'
                and restored.db.execute('SELECT COUNT(*) FROM principals').fetchone()[0]==0
                and restored.db.execute('SELECT COUNT(*) FROM memory_records').fetchone()[0]==0,
                'Archive-sourced empty-store rehearsal failed.')
    finally:
        if restored is not None:restored.close()
        keys=None
    summary=dict(status='setup_complete_inactive',storeId=str(uuid.UUID(result['storeId'])),
        receipt=str(Path(arguments.directory)/'setup-with-encrypted-backup-receipt.json'),
        encryptedBackup=export['archive'],archiveSha256=export['archiveSha256'],archiveRehearsal='PASS',
        candidateRehearsal='PASS',activated=False,runtimeEnrollment=False,recoveryQualified=False,principals=0,records=0)
    qualify_private_storage(Path(arguments.directory))
    save_new(Path(summary['receipt']),(json.dumps(summary,indent=2)+'\n').encode())
    return summary


def parser():
    result=argparse.ArgumentParser(description='Onoes-Mind inactive setup candidate. Preview is read-only. '
        'Real initialization requires separate owner approval; this command does not activate memory.')
    for flag in ('directory','authority-directory','backup-directory','environment-id',
                 'owner-ref','authority-ref','review-ref','archive-staging-directory',
                 'archive-rehearsal-directory','encrypted-backup','archive-tool'):
        result.add_argument('--'+flag,required=True)
    result.add_argument('--initialize',action='store_true',help='Separately approved, interactive empty setup only.')
    result.add_argument('--approval-ref',help='Reference to the exact owner approval, never a password or key.')
    return result


def main(argv=None, *, input_stream=None, output=None):
    arguments=parser().parse_args(argv)
    incoming=sys.stdin if input_stream is None else input_stream
    outgoing=sys.stdout if output is None else output
    password=confirmation=None
    initialized=False
    try:
        if arguments.initialize:
            reference(arguments.approval_ref)
            require(incoming.isatty(), 'Initialization requires the local interactive operator.')
        plan=preview_setup(arguments)
        print(json.dumps(plan,indent=2),file=outgoing)
        if not arguments.initialize:
            return 0
        print('Continue only with Eddie\'s separate approval for these exact locations.\n'
              'Type CREATE EMPTY MIND STORE to continue, or press Enter to cancel.\n'
              'The recovery password belongs only in the native secure prompt.',file=outgoing,flush=True)
        if incoming.readline().rstrip('\r\n')!='CREATE EMPTY MIND STORE':
            print('Cancelled. No initialization was started.',file=outgoing)
            return 2
        print('Save the encrypted-backup password in your password manager. It is required to open backups.',
              file=outgoing,flush=True)
        password=archive_password();confirmation=archive_password()
        from encrypted_backup_candidate import password_bytes
        require(password==confirmation,'Backup passwords do not match.')
        password_bytes(password);confirmation=None
        require(preview_setup(arguments)==plan, 'A selected directory or tool changed; stop for review.')
        result=initialize(arguments)
        initialized=result.get('initialized') is True
        if result.get('cancelled') is True:
            require(result.get('initialized') is False and result.get('activated') is False,
                    'Invalid cancellation result.')
            print('Cancelled at the secure prompt. No store was initialized.',file=outgoing)
            return 2
        require(result.get('schema')=='onoes-mind-checkpointed-setup-candidate/v1'
                and result.get('initialized') is True and result.get('activated') is False
                and result.get('runtimeEnrollment') is False and result.get('recoveryQualified') is False
                and result.get('candidateRehearsal')=='PASS'
                and type(result.get('principals')) is int and result['principals']==0
                and type(result.get('records')) is int and result['records']==0,
                'Setup did not return a complete inactive receipt.')
        # Completion belongs to the actual E:-archive readback and protected
        # restore, not just the earlier private NTFS bootstrap receipt.
        summary=finish_encrypted_backup(arguments,result,password)
        print(json.dumps(summary,indent=2),file=outgoing)
        return 0
    except KeyboardInterrupt:
        print(('Empty store exists; setup stopped. Memory access is off. ' if initialized else 'Stopped. ')
              +'Preserve any attempted files for review; do not retry automatically.',file=outgoing)
        return 130
    except Exception:
        # Native exceptions can contain sensitive values. Do not echo them or a traceback.
        if initialized:
            print('Empty store exists; encrypted-backup setup did not finish. Memory access is off. '
                  'Preserve all files for review; do not retry automatically.',file=outgoing)
            return 1
        print('Setup or preview refused. Preserve any attempted files for review. '
              'No automatic retry, cleanup or activation was performed.',file=outgoing)
        return 1
    finally:
        password=confirmation=None  # Reference clearing, not complete memory erasure.


if __name__=='__main__':
    raise SystemExit(main())
