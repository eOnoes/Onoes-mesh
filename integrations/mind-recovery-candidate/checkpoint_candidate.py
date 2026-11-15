"""INACTIVE experiment. No CLI, production authority, enrollment or default-path hook.

The supplied authority is a TRUST BOUNDARY: it must independently retain the latest
acknowledged head, fence producers during hold(), and durably block recovery before
purge. Merely implementing this interface, signing a file, or passing a review string
does not establish freshness. The original authority is a disposable fixture; the
persistent authority candidate is also inactive and needs a reviewed live binding.
"""
from dataclasses import dataclass
from pathlib import Path
import hashlib
import json
import os
import stat
import uuid

from onoes_mind import Ledger
from onoes_mind.ledger import LedgerError
from onoes_mind.store_init import _validate_integrity_keys


class CheckpointRecoveryError(RuntimeError):
    pass


def require(value, message):
    if not value:
        raise CheckpointRecoveryError(message)


def sha(value):
    return hashlib.sha256(value).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':')).encode()


def read_plain(path, limit):
    selected = Path(path)
    require(selected.is_absolute() and selected.resolve(strict=True) == selected,
            'Canonical explicit input required.')
    with selected.open('rb') as stream:
        info = os.fstat(stream.fileno())
        require(stat.S_ISREG(info.st_mode) and info.st_size <= limit, 'Input exceeds bound.')
        value = stream.read(limit + 1)
        require(len(value) <= limit, 'Input exceeds bound.')
    return value


@dataclass(frozen=True)
class Head:
    store_id: str
    environment: str
    sequence: int
    history_sha256: str


@dataclass(frozen=True)
class SnapshotReceipt:
    store_id: str
    environment: str
    database_sha256: str
    metadata_sha256: str
    sequence: int
    history_prefix_sha256: str


@dataclass(frozen=True)
class CapturedHistory:
    data: bytes

    def exists(self):
        return True

    def read_text(self, encoding='utf-8'):
        return self.data.decode(encoding)


def context(store_id, environment):
    require(str(uuid.UUID(store_id)) == store_id and isinstance(environment, str)
            and 0 < len(environment) <= 160 and environment != 'onoes-mind-local',
            'Explicit store/environment required.')


def history_view(ledger, path, store_id, environment):
    """Verify the captured bytes using the unchanged canonical HMAC-chain verifier."""
    context(store_id, environment)
    identity = ledger.db.execute('SELECT store_id,environment FROM recall_store_identity').fetchall()
    require(ledger.environment_id == environment and len(identity) == 1
            and tuple(identity[0]) == (store_id, environment), 'Producer/history store identity mismatch.')
    raw = path.data if type(path) is CapturedHistory else read_plain(path, 16 * 1024 * 1024)
    require(type(raw) is bytes and len(raw) <= 16 * 1024 * 1024, 'Input exceeds bound.')
    old_path = ledger.deletion_ledger_path
    try:
        # Canonical verification must authenticate THESE immutable bytes, rather
        # than reopening a pathname which could temporarily point at other bytes.
        ledger.deletion_ledger_path = CapturedHistory(raw)
        require(ledger.verify_deletion_ledger(), 'Deletion chain is invalid.')
        if type(path) is not CapturedHistory:
            require(read_plain(path, 16 * 1024 * 1024) == raw, 'Deletion history changed.')
    finally:
        ledger.deletion_ledger_path = old_path
    lines = raw.splitlines(keepends=True)
    require(bool(lines) and raw.endswith(b'\n'), 'Complete deletion history required.')
    return Head(store_id, environment, len(lines) - 1, sha(raw)), lines


def snapshot_ram(snapshot, audit_key, deletion_key, store_id, environment):
    """Use captured immutable bytes; no plaintext staging file or source DB mutation."""
    data = read_plain(snapshot, 64 * 1024 * 1024)
    metadata = read_plain(Path(str(snapshot) + '.meta'), 1024 * 1024)
    manifest = json.loads(metadata)
    require(manifest.get('format') == 2 and manifest.get('environment_id') == environment
            and manifest.get('database_sha256') == sha(data)
            and isinstance(manifest.get('integrity_manifest'), dict), 'Snapshot binding is invalid.')
    sequence = manifest.get('deletion_sequence')
    require(type(sequence) is int and sequence >= 0, 'Snapshot deletion sequence is invalid.')
    probe = Ledger(':memory:', audit_key=audit_key, deletion_key=deletion_key,
                   environment_id=environment)
    try:
        # SQLite documents this two-byte RAM-only normalization for WAL snapshots:
        # https://www.sqlite.org/c3ref/deserialize.html . Original hashes stay bound.
        require(data[:16] == b'SQLite format 3\x00' and len(data) >= 100,
                'SQLite snapshot header required.')
        memory_image = bytearray(data)
        memory_image[18:20] = b'\x01\x01'
        probe.db.deserialize(memory_image)
        require(probe.db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok',
                'Snapshot integrity failed.')
        require(probe.db.execute('SELECT MAX(version) FROM schema_migrations').fetchone()[0]
                == manifest.get('schema_version'), 'Snapshot schema mismatch.')
        identity = probe.db.execute('SELECT store_id,environment FROM recall_store_identity').fetchall()
        require(len(identity) == 1 and tuple(identity[0]) == (store_id, environment),
                'Snapshot store identity mismatch.')
        require(probe.verify_audit_chain(), 'Snapshot audit key or chain is invalid.')
        return probe, sequence, sha(data), sha(metadata)
    except Exception:
        probe.close()
        raise


def publish_snapshot_candidate(ledger, snapshot, authority, *, store_id, environment):
    """Trusted PRODUCER path only. Snapshot cannot attest to its own freshness."""
    context(store_id, environment)
    with authority.hold(store_id, environment) as lease:
        current = lease.current()
        actual, lines = history_view(ledger, ledger.deletion_ledger_path, store_id, environment)
        require(current == actual, 'Producer is not at the acknowledged current head.')
        require(not Path(snapshot).exists() and not Path(str(snapshot) + '.meta').exists(),
                'Existing snapshot is preserved.')
        ledger.backup(snapshot)
        probe, sequence, database_hash, metadata_hash = snapshot_ram(
            snapshot, ledger.audit_key, ledger.deletion_key, store_id, environment)
        probe.close()
        require(sequence == current.sequence, 'Producer changed while snapshotting.')
        again, _ = history_view(ledger, ledger.deletion_ledger_path, store_id, environment)
        require(again == current, 'Producer history changed.')
        receipt = SnapshotReceipt(store_id, environment, database_hash, metadata_hash,
                                  sequence, sha(b''.join(lines[:sequence + 1])))
        lease.register_snapshot(receipt)  # Must be durably committed before hold exits.
        lease.assert_current(current)
    return receipt


def purge_checkpoint_candidate(ledger, token, record_id, confirmation, authority, *,
                               operation_id, store_id, environment):
    """No deletion success before durable acknowledgement. Uncertain intent stays blocked."""
    context(store_id, environment)
    require(isinstance(operation_id, str) and 0 < len(operation_id) <= 128,
            'Stable bounded purge operation ID required.')
    require(ledger.authenticate(token) == 'operator' and confirmation == 'PURGE:' + record_id,
            'Operator confirmation is required before checkpoint admission.')
    actual, _ = history_view(ledger, ledger.deletion_ledger_path, store_id, environment)
    payload_hash = sha(canonical([store_id, environment, record_id]))
    admission = authority.begin_purge(operation_id, payload_hash, actual)
    def acknowledged(receipt):
        require(isinstance(receipt, dict) and receipt.get('operationId') == operation_id
                and receipt.get('checkpointAcknowledged') is True
                and type(receipt.get('sequence')) is int and receipt['sequence'] > 0,
                'Exact durable purge acknowledgement required.')
        return receipt
    if admission.get('completed') is True:
        return acknowledged(admission['receipt'])
    require(admission.get('completed') is False and isinstance(admission.get('ticket'), str)
            and str(uuid.UUID(admission['ticket'])) == admission['ticket'],
            'Explicit fenced purge admission required before mutation.')
    # begin_purge must durably fence restoration BEFORE the canonical writer runs.
    ledger.purge(token, record_id, confirmation)
    head, lines = history_view(ledger, ledger.deletion_ledger_path, store_id, environment)
    receipt = acknowledged(authority.ack_purge(operation_id, payload_hash, admission['ticket'], head,
                                              b''.join(lines)))
    require(receipt['sequence'] == head.sequence, 'Purge acknowledgement head mismatch.')
    return receipt


def restore_checkpoint_candidate(snapshot, destination, deletion_history, authority, *,
                                 audit_key, deletion_key, store_id, environment, review_ref):
    """Return an unopened-to-agents Ledger only after checkpoint/chain verification.

    The default canonical restore is untouched. All inputs are captured in RAM before
    writing; a later failed target is preserved, closed and never returned as success.
    This candidate is NOT approved for real/private data or production authority use.
    """
    context(store_id, environment)
    _validate_integrity_keys(audit_key, deletion_key, environment)
    require(isinstance(review_ref, str) and 0 < len(review_ref) <= 256,
            'Review reference required; it does not grant authority.')
    target = Path(destination)
    require(target.is_absolute() and target.parent.is_dir() and target.parent.resolve() == target.parent,
            'Canonical existing destination parent required.')
    for suffix in ('', '-wal', '-shm', '-journal', '.deletions.jsonl', '.deletions.jsonl.lock'):
        require(not os.path.lexists(str(target) + suffix), 'Existing restore state is preserved.')
    probe = restored = None
    try:
        with authority.hold(store_id, environment) as lease:
            current = lease.current()
            require(isinstance(current, Head) and (current.store_id, current.environment)
                    == (store_id, environment), 'Checkpoint identity mismatch.')
            probe, sequence, database_hash, metadata_hash = snapshot_ram(
                snapshot, audit_key, deletion_key, store_id, environment)
            recovered_history = deletion_history is None
            selected_history = CapturedHistory(lease.history()) if recovered_history else deletion_history
            actual, lines = history_view(probe, selected_history, store_id, environment)
            require(current == actual, 'Current checkpoint and deletion history disagree.')
            receipt = lease.snapshot_receipt(database_hash, metadata_hash)
            expected = SnapshotReceipt(store_id, environment, database_hash, metadata_hash,
                                       sequence, sha(b''.join(lines[:sequence + 1])))
            require(receipt == expected and sequence <= current.sequence,
                    'Snapshot has no matching independently registered checkpoint.')
            # Replay the complete authenticated chain in RAM, as canonical restore does.
            with probe.db:
                for raw in lines[1:]:
                    entry = json.loads(raw)
                    for row in probe.db.execute("SELECT record_id FROM memory_records WHERE state!='purged'").fetchall():
                        if sha(row[0].encode()) == entry['record_fingerprint']:
                            probe.db.execute("UPDATE memory_records SET state='purged' WHERE record_id=?", (row[0],))
                            probe.db.execute('DELETE FROM memory_fts WHERE record_id=?', (row[0],))
                            probe.db.execute('INSERT OR IGNORE INTO deletion_tombstones VALUES (?,?,?,?)',
                                             (entry['tombstone_id'], row[0], entry['record_fingerprint'], entry['purged_at']))
            require(probe.integrity_report()['status'] == 'PASS', 'Replayed snapshot failed integrity.')
            lease.assert_current(current)
            if recovered_history:
                # A new recovery-local copy; never overwrite or depend on the lost
                # source history. Keep it on a later failure for inspection.
                deletion_history = Path(str(target) + '.deletions.jsonl')
                descriptor = os.open(deletion_history, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                with os.fdopen(descriptor, 'wb') as stream:
                    stream.write(b''.join(lines))
                    stream.flush()
                    os.fsync(stream.fileno())
            # Reserve once, without replacing a target created after preflight.
            descriptor = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            os.close(descriptor)
            import sqlite3
            connection = sqlite3.connect(target)
            try:
                probe.db.backup(connection)
            finally:
                connection.close()
            restored = Ledger(target, audit_key=audit_key, deletion_key=deletion_key,
                              environment_id=environment, deletion_ledger_path=deletion_history)
            require(restored.integrity_report()['status'] == 'PASS', 'Restored integrity failed.')
            after, _ = history_view(restored, deletion_history, store_id, environment)
            require(after == current, 'Deletion history changed during restore.')
            lease.assert_current(current)
        result, restored = restored, None  # A failed authority COMMIT cannot return a ledger.
        return result
    finally:
        if probe is not None:
            probe.close()
        if restored is not None:
            restored.close()
