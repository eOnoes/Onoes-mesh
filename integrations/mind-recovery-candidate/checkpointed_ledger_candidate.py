"""Inactive opt-in host adapter; no factory enrollment, CLI or live defaults.

This is a trusted application API, not a sandbox for arbitrary Python/SQL access.
Every real host must explicitly adopt it before a binding can be qualified.
Canonical Mind source and its legacy Ledger behavior remain unchanged.
"""
from pathlib import Path
import sqlite3
import threading

from onoes_mind import Ledger
from onoes_mind.enrollment_store import qualify_private_storage
from checkpoint_candidate import (context, history_view, purge_checkpoint_candidate,
                                  require, read_plain, restore_checkpoint_candidate)
from persistent_authority import PersistentAuthorityCandidate


class CheckpointedLedgerCandidate(Ledger):
    def __init__(self, database, history, authority, *, store_id, environment,
                 audit_key, deletion_key):
        context(store_id, environment)
        require(type(authority) is PersistentAuthorityCandidate,
                'Explicit separately bound persistent authority required.')
        # This adapter opens an existing enrolled store only; no missing-file
        # initialization or automatic authority/source adoption.
        for path in (database, history):
            read_plain(path, 64 * 1024 * 1024)
            qualify_private_storage(Path(path).parent)
            qualify_private_storage(path, kind='file')
        probe = sqlite3.connect(Path(database).as_uri() + '?mode=ro', uri=True)
        try:
            rows = probe.execute('SELECT store_id,environment FROM recall_store_identity').fetchall()
            require(rows == [(store_id, environment)], 'Existing source identity mismatch.')
        finally:
            probe.close()
        self._checkpoint_lock = threading.RLock()
        self._checkpoint_thread = None
        self._checkpoint_authority = authority
        self._checkpoint_store_id = store_id
        self._checkpoint_environment = environment
        try:
            with authority.hold(store_id, environment) as lease:
                super().__init__(database, deletion_ledger_path=history,
                    environment_id=environment, audit_key=audit_key, deletion_key=deletion_key)
                actual, _ = history_view(self, self.deletion_ledger_path, store_id, environment)
                lease.assert_current(actual)
                require(self.integrity_report()['status'] == 'PASS', 'Existing source integrity failed.')
        except Exception:
            if getattr(self, 'db', None) is not None:
                self.close()
            raise

    def purge(self, token, record_id, confirmation, *, operation_id=None):
        require(isinstance(operation_id, str) and 0 < len(operation_id) <= 128,
                'A stable purge operation ID is required; legacy direct purge is disabled.')
        with self._checkpoint_lock:
            require(self._checkpoint_thread is None, 'A managed purge is already active.')
            self._checkpoint_thread = threading.get_ident()
            try:
                return purge_checkpoint_candidate(self, token, record_id, confirmation,
                    self._checkpoint_authority, operation_id=operation_id,
                    store_id=self._checkpoint_store_id, environment=self._checkpoint_environment,
                    canonical_purge=super().purge)
            finally:
                self._checkpoint_thread = None

    def _append_deletion(self, record_id, tombstone_id, purge_time):
        require(self._checkpoint_thread == threading.get_ident(),
                'Deletion requires the managed checkpoint path.')
        return super()._append_deletion(record_id, tombstone_id, purge_time)


def restore_checkpointed_candidate(snapshot, destination, deletion_history, authority, *,
                                   audit_key, deletion_key, store_id, environment, review_ref):
    """Offline candidate handoff; never return an unprotected restored writer.

    The caller must separately establish exclusive/offline source selection before
    any runtime use. This helper neither retires other writers nor enrolls a
    service. Failures preserve recovery artifacts for deliberate inspection.
    Canonical strict restore and the ordinary bootstrap API are unchanged.
    """
    require(type(authority) is PersistentAuthorityCandidate,
            'Explicit separately bound persistent authority required.')
    require(deletion_history is None,
            'Protected restore requires retained history into a new recovery-local file.')
    restored = restore_checkpoint_candidate(snapshot, destination, deletion_history, authority,
        audit_key=audit_key, deletion_key=deletion_key, store_id=store_id,
        environment=environment, review_ref=review_ref)
    try:
        history = restored.deletion_ledger_path
    finally:
        restored.close()
    # Revalidate current authority/history/identity through the existing opener
    # after closing the plain handle. If it refuses, there is no plain fallback.
    return CheckpointedLedgerCandidate(destination, history, authority,
        audit_key=audit_key, deletion_key=deletion_key, store_id=store_id,
        environment=environment)
