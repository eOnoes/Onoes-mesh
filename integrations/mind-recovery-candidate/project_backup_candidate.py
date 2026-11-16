"""Explicit prepared-snapshot archive/rehearsal for an initialized Mind store.

No CLI, startup, enrollment, source-ledger opener or live recovery apply. The
caller must separately approve and publish a snapshot through the trusted producer.
"""
import hashlib
import json
from pathlib import Path
import sqlite3


def require(ok):
    if not ok:
        raise ValueError('Prepared Mind backup validation failed; retain artifacts and do not retry blindly.')


def prompt_archive_password():
    from operator_setup_entry import archive_password
    from encrypted_backup_candidate import password_bytes
    password = confirmation = None
    try:
        password = archive_password()
        confirmation = archive_password(confirm=True)
        require(password == confirmation)
        password_bytes(password)
        return password
    finally:
        confirmation = None


def project_receipts(database):
    """Hash receipt rows locally; never return record text or a credential."""
    exists = database.execute("SELECT count(*) FROM sqlite_master WHERE type='table' AND name='project_sync_events'").fetchone()[0]
    rows = [] if not exists else database.execute('SELECT * FROM project_sync_events').fetchall()
    encoded = sorted(json.dumps(list(row), ensure_ascii=False, separators=(',', ':')) for row in rows)
    return dict(count=len(rows), sha256=hashlib.sha256(json.dumps(encoded, separators=(',', ':')).encode()).hexdigest())


def archive_prepared_project_backup(source_directory, staging_directory, rehearsal_directory,
                                    destination, tool, password, *, publication, authority,
                                    review_ref, source_snapshot='project-snapshot.sqlite'):
    """Export one already-published snapshot and verify an offline archive restore.

    Uses the retained independent current authority, never the archive as its own
    freshness authority. A successful rehearsal does not qualify credential recovery.
    Failed artifacts are intentionally retained, and every destination must be new.
    """
    from onoes_mind.enrollment_store import qualify_private_storage
    from onoes_mind.runtime_keys import unprotect_runtime_keys
    from checkpoint_candidate import read_plain
    from checkpointed_ledger_candidate import restore_checkpointed_candidate
    from encrypted_backup_candidate import (
        export_encrypted_backup_candidate, unpack_encrypted_backup_candidate, password_bytes, save_new)
    password_bytes(password)
    require(type(review_ref) is str and 1 <= len(review_ref) <= 240 and not any(ord(c) < 32 for c in review_ref))
    roots = [qualify_private_storage(p) for p in (source_directory, staging_directory, rehearsal_directory)]
    require(all(not a.is_relative_to(b) and not b.is_relative_to(a)
                for i,a in enumerate(roots) for b in roots[i+1:]))
    source, stage, recovered = roots
    require(not any(stage.iterdir()) and not any(recovered.iterdir()))
    # Existing exporter enforces its snapshot basename, package context, publication
    # hashes, pinned archive binary, bounded files and no-overwrite destination.
    exported = export_encrypted_backup_candidate(source, stage, destination, tool, password,
        publication=publication, source_snapshot=source_snapshot)
    unpack_encrypted_backup_candidate(destination, recovered, tool, password,
        expected_archive_sha256=exported['archiveSha256'], publication=publication)
    package = json.loads(read_plain(recovered/'encrypted-key-enrollment.json',16384))
    require(package['storeId'] == publication.store_id and package['environment'] == publication.environment)
    keys = restored = snapshot = None
    try:
        keys = unprotect_runtime_keys(package['runtime_envelope'], store_id=publication.store_id,
                                      environment_id=publication.environment)
        # Snapshot bytes came from the verified archive. Open strictly read-only;
        # the protected restorer independently verifies signatures and current head.
        snapshot = sqlite3.connect((recovered/'snapshot.sqlite').as_uri()+'?mode=ro',uri=True)
        snapshot.execute('PRAGMA query_only=ON')
        expected = project_receipts(snapshot)
        restored = restore_checkpointed_candidate(recovered/'snapshot.sqlite', recovered/'verified-restored.sqlite',
            None, authority, **keys, store_id=publication.store_id, environment=publication.environment,
            review_ref=review_ref)
        require(restored.integrity_report()['status'] == 'PASS' and project_receipts(restored.db) == expected)
        result = dict(schema='onoes-mind-existing-project-backup/v1',storeId=publication.store_id,
            environment=publication.environment,archive=exported['archive'],archiveSha256=exported['archiveSha256'],
            archiveRehearsal='PASS',projectReceiptReadback='PASS',projectReceiptCount=expected['count'],
            projectReceiptSha256=expected['sha256'],credentialRecoveryQualified=False,
            independentCurrentAuthorityRetained=True,activated=False,sourceLedgerOpened=False)
        save_new(stage/'initialized-backup-rehearsal-receipt.json',(json.dumps(result,indent=2)+'\n').encode())
        return result
    finally:
        if restored is not None: restored.close()
        if snapshot is not None: snapshot.close()
        keys = None
