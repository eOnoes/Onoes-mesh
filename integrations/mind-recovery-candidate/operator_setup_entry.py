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


def archive_password(*, confirm=False):
    # Fail closed if getpass would fall back to echoed input. Never accept a
    # password from command arguments, environment, browser or an agent channel.
    with warnings.catch_warnings():
        warnings.simplefilter('error',getpass.GetPassWarning)
        return getpass.getpass(('Confirm' if confirm else 'Enter')+
                               ' saved BACKUP ARCHIVE password (hidden): ')


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
    result.add_argument('--outcome-file',help='New local file for a fixed, nonsecret setup result; never a transcript.')
    return result


def main(argv=None, *, input_stream=None, output=None):
    arguments=parser().parse_args(argv)
    incoming=sys.stdin if input_stream is None else input_stream
    outgoing=sys.stdout if output is None else output
    password=confirmation=None
    initialized=False
    stage='preflight'
    outcome=None
    status='setup_failed'
    reason='PREFLIGHT_REFUSED'
    messages={
        'PREFLIGHT_REFUSED':'The local approval, locations or tool checks did not pass.',
        'OUTCOME_DESTINATION_UNAVAILABLE':'The new local result file could not be reserved. Preserve existing files.',
        'CONFIRMATION_CANCELLED':'The creation phrase was not confirmed; initialization was not started.',
        'HIDDEN_PASSWORD_INPUT_UNAVAILABLE':'Hidden password input was unavailable. No echoed input is allowed.',
        'BACKUP_PASSWORD_MISMATCH':'The two BACKUP ARCHIVE password entries did not match.',
        'BACKUP_PASSWORD_RULES':'Use a saved backup password of 16-256 UTF-8 bytes, without tabs or other control characters.',
        'LOCATIONS_CHANGED':'A reviewed location or archive tool changed during confirmation.',
        'NATIVE_INITIALIZATION_FAILED':'The protected key/store setup did not finish. Preserve any attempted files.',
        'NATIVE_CANCELLED':'The recovery-key window was cancelled; no completed store was reported.',
        'RECEIPT_INVALID':'The store setup did not return the required inactive result.',
        'ARCHIVE_REHEARSAL_FAILED':'The encrypted backup or its recovery rehearsal did not finish.',
        'INTERRUPTED':'The operator interrupted setup. Preserve any attempted files.',
        'COMPLETE':'The empty store, encrypted backup and archive recovery rehearsal completed; access remains off.'}
    try:
        if arguments.initialize:
            reference(arguments.approval_ref)
            require(incoming.isatty(), 'Initialization requires the local interactive operator.')
        plan=preview_setup(arguments)
        print(json.dumps(plan,indent=2),file=outgoing)
        if not arguments.initialize:
            return 0
        if arguments.outcome_file:
            reason='OUTCOME_DESTINATION_UNAVAILABLE'
            target=Path(arguments.outcome_file)
            require(target.is_absolute() and target.parent.resolve(strict=True)==target.parent
                    and not any(target.is_relative_to(Path(root)) for root in plan['directories'].values()),
                    'Select a separate local result file.')
            # Exclusive creation refuses an existing file, including a symlink.
            # Only fixed codes are stored; never exception text, input or keys.
            outcome=target.open('x',encoding='utf-8')
        stage='confirmation';reason='CONFIRMATION_CANCELLED'
        print('Continue only with Eddie\'s separate approval for these exact locations.\n'
              'Type CREATE EMPTY MIND STORE to continue, or press Enter to cancel.\n'
              'The recovery password belongs only in the native secure prompt.',file=outgoing,flush=True)
        if incoming.readline().rstrip('\r\n')!='CREATE EMPTY MIND STORE':
            status='cancelled'
            print('Cancelled. No initialization was started.',file=outgoing)
            return 2
        print('Create and save a NEW backup archive password in your password manager before entering it.\n'
              'Use at least 16 characters (20 or more recommended). Enter the SAME password twice.\n'
              'The separate recovery-key window will use a different saved password.',
              file=outgoing,flush=True)
        stage='archive-password-input';reason='HIDDEN_PASSWORD_INPUT_UNAVAILABLE'
        password=archive_password();confirmation=archive_password(confirm=True)
        from encrypted_backup_candidate import password_bytes
        stage='archive-password-match';reason='BACKUP_PASSWORD_MISMATCH'
        require(password==confirmation,'Backup passwords do not match.')
        stage='archive-password-rules';reason='BACKUP_PASSWORD_RULES'
        password_bytes(password);confirmation=None
        stage='location-recheck';reason='LOCATIONS_CHANGED'
        require(preview_setup(arguments)==plan, 'A selected directory or tool changed; stop for review.')
        stage='native-initialization';reason='NATIVE_INITIALIZATION_FAILED'
        print('Backup password accepted. Opening the separate RECOVERY KEYS window next.',file=outgoing,flush=True)
        result=initialize(arguments)
        initialized=result.get('initialized') is True
        if result.get('cancelled') is True:
            require(result.get('initialized') is False and result.get('activated') is False,
                    'Invalid cancellation result.')
            print('Cancelled at the secure prompt. No store was initialized.',file=outgoing)
            status='cancelled';reason='NATIVE_CANCELLED'
            return 2
        stage='initialization-receipt';reason='RECEIPT_INVALID'
        require(result.get('schema')=='onoes-mind-checkpointed-setup-candidate/v1'
                and result.get('initialized') is True and result.get('activated') is False
                and result.get('runtimeEnrollment') is False and result.get('recoveryQualified') is False
                and result.get('candidateRehearsal')=='PASS'
                and type(result.get('principals')) is int and result['principals']==0
                and type(result.get('records')) is int and result['records']==0,
                'Setup did not return a complete inactive receipt.')
        # Completion belongs to the actual E:-archive readback and protected
        # restore, not just the earlier private NTFS bootstrap receipt.
        stage='archive-rehearsal';reason='ARCHIVE_REHEARSAL_FAILED'
        summary=finish_encrypted_backup(arguments,result,password)
        print(json.dumps(summary,indent=2),file=outgoing)
        status='setup_complete_inactive';reason='COMPLETE';stage='complete'
        return 0
    except KeyboardInterrupt:
        status='interrupted';reason='INTERRUPTED'
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
        if arguments.initialize:
            print('Setup result: '+reason+' - '+messages[reason],file=outgoing,flush=True)
        if outcome is not None:
            try:
                json.dump(dict(schema='onoes-mind-operator-outcome/v1',status=status,
                    stage=stage,reason=reason,message=messages[reason],
                    initializationConfirmed=initialized,activated=False,runtimeEnrollment=False),outcome,indent=2)
                outcome.write('\n');outcome.flush();os.fsync(outcome.fileno())
            except OSError:
                print('Local result file could not be saved. Preserve files and the final screen; do not retry.',
                      file=outgoing,flush=True)
            finally:
                outcome.close()


if __name__=='__main__':
    raise SystemExit(main())
