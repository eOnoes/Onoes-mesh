"""Inactive privileged native operation; no CLI, approval mechanism or startup.

The caller must establish exact owner approval and exclusive writer ownership,
open the reviewed protected writer, then close it before starting a reader.
This creates a real read-only grant/token only when explicitly called. Never
call it merely to preview, discover a store or check whether setup is needed.
"""
import json
import os
from pathlib import Path
import re

from onoes_mind.enrollment_store import qualify_private_storage
from onoes_mind.recall_binding import prepare_mesh_principal, issue_mesh_recall_credential
from checkpointed_ledger_candidate import CheckpointedLedgerCandidate
from checkpoint_candidate import history_view
from native_recall_candidate import context, seal_service_credential


class RecallProvisionError(RuntimeError):
    pass


def require(ok):
    if not ok:raise RecallProvisionError('Protected recall provisioning refused; preserve existing state.')


def new_private_file(value):
    target=Path(value)
    require(target.is_absolute() and '..' not in target.parts and not os.path.lexists(target))
    parent=qualify_private_storage(target.parent)
    require(parent.resolve(strict=True)==parent)
    return target


def provision_reader(writer,*,binding,credential_path,outcome_path,operation_id,approval_ref):
    """One attempt. Returns only nonsecret metadata; no ordinary writer token."""
    outcome=None;token=None;stage='preflight';changed=False
    result=None
    try:
        require(type(writer) is CheckpointedLedgerCandidate)
        context(binding)
        require(type(operation_id) is str and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._:-]{0,127}',operation_id)
                and type(approval_ref) is str and approval_ref==binding.review_ref)
        require((writer._checkpoint_store_id,writer._checkpoint_environment)==(binding.store_id,binding.environment))
        database=qualify_private_storage(Path(binding.database_path),kind='file')
        require(database.resolve(strict=True)==database)
        stat=database.stat();require((stat.st_dev,stat.st_ino)==(binding.file_device,binding.file_inode))
        databases=writer.db.execute('PRAGMA database_list').fetchall()
        require([Path(row[2]).resolve(strict=True) for row in databases if row[1]=='main']==[database])
        identities=[tuple(row) for row in writer.db.execute('SELECT store_id,environment,authority_ref FROM recall_store_identity')]
        require(identities==[(binding.store_id,binding.environment,binding.authority_ref)])
        credential=new_private_file(credential_path);target=new_private_file(outcome_path)
        require(credential!=target)
        result=dict(schema='onoes-mind-recall-provision-outcome/v1',operationId=operation_id,
            reviewRef=approval_ref,storeId=binding.store_id,environment=binding.environment,
            principal='mesh-recall',scopeId=binding.scope_id,readerStarted=False,
            status='attempt_reserved',mayHaveChanged=False,stage=stage)

        def save():
            result.update(stage=stage,mayHaveChanged=changed)
            outcome.seek(0);json.dump(result,outcome,indent=2);outcome.write('\n')
            outcome.truncate();outcome.flush();os.fsync(outcome.fileno())

        with writer._checkpoint_lock:
            require(writer._checkpoint_thread is None)
            with writer._checkpoint_authority.hold(binding.store_id,binding.environment) as lease:
                head,_=history_view(writer,writer.deletion_ledger_path,binding.store_id,binding.environment)
                lease.assert_current(head)
                require(writer.integrity_report()['status']=='PASS')
                require(writer.db.execute('SELECT 1 FROM principals WHERE principal_id=?',('mesh-recall',)).fetchone() is None)
                new_private_file(credential);new_private_file(target)
                # Reserve and sync before any credential/grant mutation. A crash
                # leaves an existing marker, never implicit permission to retry.
                outcome=target.open('x',encoding='utf-8');save()
                qualify_private_storage(target,kind='file')
                stage='principal';changed=True;save()
                prepare_mesh_principal(writer,scope_id=binding.scope_id)
                stage='credential';save()
                token=issue_mesh_recall_credential(writer)
                stage='protected-storage';save()
                storage=seal_service_credential(credential,token,binding=binding)
                token=None
                stage='postconditions';save()
                head,_=history_view(writer,writer.deletion_ledger_path,binding.store_id,binding.environment)
                lease.assert_current(head)
                require(writer.integrity_report()['status']=='PASS')
                require([tuple(row) for row in writer.db.execute('SELECT scope_id,can_read,can_write FROM scope_grants WHERE principal_id=?',('mesh-recall',))]==[(binding.scope_id,1,0)])
                require(writer.db.execute('SELECT 1 FROM credentials WHERE principal_id=?',('mesh-recall',)).fetchone() is None)
                stage='complete';result.update(status='provisioned_inactive',credentialStorage=storage,grantProvisioned=True)
                save()
        return result
    except Exception:
        if outcome is not None:
            result.update(status='outcome_unknown' if changed else 'refused',stage=stage,mayHaveChanged=changed)
            try:
                outcome.seek(0);json.dump(result,outcome,indent=2);outcome.write('\n')
                outcome.truncate();outcome.flush();os.fsync(outcome.fileno())
            except OSError:
                pass  # Existing/partial marker still prevents an automatic repeat.
        raise RecallProvisionError('Recall provisioning did not complete; preserve source and files. No automatic retry or cleanup.') from None
    finally:
        token=None  # Reference clearing, not full Python memory erasure.
        if outcome is not None:outcome.close()
