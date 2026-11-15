"""Inactive, local operator entry. Default is read-only preview, never setup.

Use the reviewed canonical Mind package on PYTHONPATH. No password/key CLI flags,
automatic directory creation, permission changes, service setup or retries.
"""
import argparse
import json
from pathlib import Path
import re
import sys
import uuid


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
           ('directory','authority_directory','backup_directory')}
    selected=[]
    identities={}
    for name,root in roots.items():
        require(root.resolve(strict=True)==root, 'An existing canonical location is required.')
        require(not any(root.iterdir()), 'All three private destinations must be empty.')
        require(not any(root.is_relative_to(other) or other.is_relative_to(root) for other in selected),
                'Select three separate, disjoint private directories.')
        selected.append(root)
        info=root.stat()
        identities[name]=[info.st_dev,info.st_ino]
    return dict(schema='onoes-mind-setup-preview/v1', action='preview', ready=True,
                directories={name:str(root) for name,root in roots.items()},
                directoryIdentities=identities, environment=arguments.environment_id,
                references=refs, ownerApprovalRequired=True, activated=False,
                runtimeEnrollment=False, createsNothing=True)


def initialize(arguments):
    # Lazy import: --help and module import cannot start enrollment or require GUI.
    from operator_setup_candidate import initialize_checkpointed_candidate
    return initialize_checkpointed_candidate(**{
        name:getattr(arguments,name) for name in
        ('directory','authority_directory','backup_directory','environment_id',
         'owner_ref','authority_ref','review_ref')})


def parser():
    result=argparse.ArgumentParser(description='Onoes-Mind inactive setup candidate. Preview is read-only. '
        'Real initialization requires separate owner approval; this command does not activate memory.')
    for flag in ('directory','authority-directory','backup-directory','environment-id',
                 'owner-ref','authority-ref','review-ref'):
        result.add_argument('--'+flag,required=True)
    result.add_argument('--initialize',action='store_true',help='Separately approved, interactive empty setup only.')
    result.add_argument('--approval-ref',help='Reference to the exact owner approval, never a password or key.')
    return result


def main(argv=None, *, input_stream=None, output=None):
    arguments=parser().parse_args(argv)
    incoming=sys.stdin if input_stream is None else input_stream
    outgoing=sys.stdout if output is None else output
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
        require(preview_setup(arguments)==plan, 'A selected directory changed; stop for review.')
        result=initialize(arguments)
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
        store_id=str(uuid.UUID(result['storeId']))
        # Print a fixed public projection, never the key package or arbitrary result fields.
        print(json.dumps(dict(status='setup_complete_inactive',storeId=store_id,
            receipt=str(Path(arguments.directory)/'checkpointed-initialization-receipt.json'),
            candidateRehearsal='PASS',activated=False,runtimeEnrollment=False,
            recoveryQualified=False,principals=0,records=0),indent=2),file=outgoing)
        return 0
    except KeyboardInterrupt:
        print('Stopped. Preserve any attempted files for review; do not retry automatically.',file=outgoing)
        return 130
    except Exception:
        # Native exceptions can contain sensitive values. Do not echo them or a traceback.
        print('Setup or preview refused. Preserve any attempted files for review. '
              'No automatic retry, cleanup or activation was performed.',file=outgoing)
        return 1


if __name__=='__main__':
    raise SystemExit(main())
