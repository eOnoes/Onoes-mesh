"""One-shot privileged preparation; no CLI, consent mechanism or service start.

The caller must establish exact owner approval and exclusive canonical ownership.
Replacement reissues only a freshly reviewed project set; it never infers approval
from a restored grant. This module does not prove prior runtime retirement.
"""
import hashlib
import json
import os

from onoes_mind.enrollment_store import qualify_private_storage
from checkpoint_candidate import history_view
from native_project_sync_candidate import context, seal_project_credential, ProjectServiceLease
from project_events_candidate import PRINCIPAL, identifier, text
from provision_recall_candidate import new_private_file


class ProjectProvisionError(RuntimeError):
    pass


def require(ok):
    if not ok:
        raise ProjectProvisionError('Protected project-service operation refused; preserve existing state.')


def prepare_project_service(events, *, mode, projects, credential_path, outcome_path, operation_id, review_ref):
    """Prepare once and return nonsecret evidence only; never activate access."""
    outcome = lease = None
    result = None
    token = None
    changed = False
    registered = False
    stage = 'preflight'
    try:
        require(mode in ('first_setup', 'replace', 'revoke') and identifier(operation_id))
        require(type(projects) is tuple and 1 <= len(projects) <= 8
                and all(type(p) is tuple and len(p) == 2 and identifier(p[0])
                        and text(p[1], 160) and p[1].strip() == p[1] and p[1] for p in projects))
        project_ids = tuple(p[0] for p in projects)
        entropy = context(events, project_ids, review_ref)
        require(mode != 'revoke' or credential_path is None)
        credential = new_private_file(credential_path) if mode != 'revoke' else None
        target = new_private_file(outcome_path)
        require(credential != target)
        request_hash = hashlib.sha256(json.dumps(dict(mode=mode, projects=projects,
            operationId=operation_id, contextSha256=hashlib.sha256(entropy).hexdigest(),
            credentialPath=str(credential), outcomePath=str(target)), sort_keys=True).encode()).hexdigest()
        ledger = events.ledger
        result = dict(schema='onoes-mind-project-service-outcome/v1', operationId=operation_id,
            requestHash=request_hash, mode=mode, storeId=events.binding.store_id,
            environment=events.binding.environment, principal=PRINCIPAL, projects=project_ids,
            status='attempt_reserved', serviceStarted=False, runtimeEnrollment=False,
            previousRuntimeRetirementQualified=False)

        def save():
            result.update(stage=stage, mayHaveChanged=changed)
            outcome.seek(0); json.dump(result, outcome, indent=2); outcome.write('\n')
            outcome.truncate(); outcome.flush(); os.fsync(outcome.fileno())

        def register():
            nonlocal registered
            with events.lock, events._history_guard(), ledger._transaction(immediate=True):
                events.db.execute('INSERT INTO project_sync_admin_operations VALUES(?,?,?,?)',
                    (operation_id, request_hash, mode, 'reserved'))
            registered = True

        with events.lock:
            require(ledger._checkpoint_thread is None)
            lease = ProjectServiceLease(events.binding)
            with events._history_guard():
                before, _ = history_view(ledger, ledger.deletion_ledger_path,
                    events.binding.store_id, events.binding.environment)
                require(ledger.integrity_report()['status'] == 'PASS')
                if mode == 'first_setup':
                    require(not events.db.execute("SELECT 1 FROM sqlite_schema WHERE name GLOB 'project_sync_*'").fetchone())
                    require(not events.db.execute('SELECT 1 FROM principals WHERE principal_id=?', (PRINCIPAL,)).fetchone())
                else:
                    events._format()
                    require(not events.db.execute('SELECT 1 FROM project_sync_admin_operations WHERE operation_id=?', (operation_id,)).fetchone())
                    if mode == 'replace':
                        for project, label in projects:
                            require(events.db.execute('SELECT 1 FROM project_sync_projects WHERE project_id=? AND label=? AND deleted=0', (project,label)).fetchone())
                    else:
                        require(events.db.execute("SELECT 1 FROM principals p JOIN project_sync_credentials c USING(principal_id) WHERE p.principal_id=? AND p.kind='service'", (PRINCIPAL,)).fetchone())
            # A partial marker or credential is never deleted to permit retry.
            if credential is not None: new_private_file(credential)
            new_private_file(target)
            outcome = target.open('x', encoding='utf-8'); save()
            qualify_private_storage(target, kind='file')
            stage = 'database_change_pending'; changed = True; save()
            if mode == 'first_setup':
                events.initialize(); register()
                for project, label in projects: events.register_project(project, label)
                token = events.enroll(list(project_ids))
            elif mode == 'replace':
                register()
                token = events.replace_credential(project_ids, operation_id)
            else:
                register()
                with events._history_guard(), ledger._transaction(immediate=True):
                    epoch_before = events.db.execute('SELECT credential_epoch FROM principals WHERE principal_id=?', (PRINCIPAL,)).fetchone()[0]
                    ledger.rotate_credentials(PRINCIPAL)
                    epoch_after = events.db.execute('SELECT credential_epoch FROM principals WHERE principal_id=?', (PRINCIPAL,)).fetchone()[0]
                    require(epoch_after == epoch_before + 1)
                    events.db.execute("UPDATE project_sync_admin_operations SET state='unknown' WHERE operation_id=?", (operation_id,))
                    result.update(epochBefore=epoch_before, epochAfter=epoch_after)
            storage = None
            if mode != 'revoke':
                stage = 'protected_storage'; save()
                storage = seal_project_credential(credential, token, events=events,
                    project_ids=project_ids, review_ref=review_ref)
            token = None
            stage = 'postconditions'; save()
            with events._history_guard(), ledger._transaction(immediate=True):
                after, _ = history_view(ledger, ledger.deletion_ledger_path,
                    events.binding.store_id, events.binding.environment)
                require(after == before and ledger.integrity_report()['status'] == 'PASS')
                events.db.execute("UPDATE project_sync_admin_operations SET state='complete' WHERE operation_id=? AND request_hash=?", (operation_id,request_hash))
                ledger._audit('project_service_revoked' if mode == 'revoke' else 'project_service_prepared', PRINCIPAL, operation_id)
            stage = 'complete'
            result.update(status={'first_setup':'provisioned_inactive','replace':'replaced_inactive','revoke':'revoked_inactive'}[mode],
                          credentialIssued=mode != 'revoke')
            if storage is not None: result['credentialStorage'] = storage
            save()
        return result
    except Exception:
        if registered:
            try:
                events.db.execute("UPDATE project_sync_admin_operations SET state='unknown' WHERE operation_id=?", (operation_id,))
            except Exception: pass
        if outcome is not None:
            result['status'] = 'outcome_unknown' if changed else 'refused'
            try: save()
            except Exception: pass
        raise ProjectProvisionError('Project-service preparation did not complete; preserve source and files. No automatic retry or cleanup.') from None
    finally:
        token = None
        if outcome is not None: outcome.close()
        if lease is not None: lease.close()


def revoke_project_service(events, *, projects, outcome_path, operation_id, review_ref):
    """One reviewed epoch invalidation after owned service retirement; no reissue."""
    return prepare_project_service(events, mode='revoke', projects=projects,
        credential_path=None, outcome_path=outcome_path, operation_id=operation_id, review_ref=review_ref)
