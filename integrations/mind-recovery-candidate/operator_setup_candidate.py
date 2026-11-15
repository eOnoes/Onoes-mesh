"""INACTIVE operator journey. No CLI, live path defaults, service or agent enrollment.

Invocation on real data requires separate owner approval for key custody, three
private destinations, journal trust/updates and initialization. Text references are
records of review, never permission. The default canonical setup is unchanged.
"""
from dataclasses import asdict
from pathlib import Path
import json
import hashlib
import os

from onoes_mind import Ledger
from onoes_mind.enrollment_store import qualify_private_storage
from onoes_mind.operator_setup import initialize_private_store
from onoes_mind.runtime_keys import unprotect_runtime_keys
from checkpoint_candidate import (require, read_plain, publish_snapshot_candidate,
                                   restore_checkpoint_candidate)
from persistent_authority import PersistentAuthorityCandidate


class CheckpointedSetupError(RuntimeError):
    def __init__(self, stage):
        self.stage = stage
        super().__init__('Checkpointed setup did not complete at ' + stage +
                         '. Preserve attempted files; nothing was activated.')


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, 'Duplicate enrollment field.')
        result[key] = value
    return result


def save_new(path, value):
    with path.open('x', encoding='utf-8') as stream:
        stream.write(json.dumps(value, sort_keys=True, indent=2) + '\n')
        stream.flush()
        os.fsync(stream.fileno())
    qualify_private_storage(path, kind='file')


def save_new_bytes(path, value):
    with path.open('xb') as stream:
        stream.write(value);stream.flush();os.fsync(stream.fileno())
    qualify_private_storage(path, kind='file')


def initialize_checkpointed_candidate(*, directory, authority_directory, backup_directory,
                                      environment_id, owner_ref, authority_ref, review_ref):
    """Empty setup -> protected keys -> current journal -> backup -> actual restore.

    Requires explicitly selected EMPTY, disjoint, existing private directories.
    No ACL is changed. Failure preserves all attempted files and creates no success
    receipt. There is no automatic retry, cleanup, principal or live connection.
    """
    stage = 'preflight'
    ledger = restored = keys = rehearsal_keys = None
    try:
        roots = [qualify_private_storage(p) for p in
                 (directory, authority_directory, backup_directory)]
        for i, root in enumerate(roots):
            require(not any(root.iterdir()), 'All three destinations must be empty.')
            for other in roots[:i]:
                require(not root.is_relative_to(other) and not other.is_relative_to(root),
                        'Data, current authority and dated backup must be separate directories.')
        identities = [(p.stat().st_dev, p.stat().st_ino) for p in roots]

        def check_roots():
            for root, expected in zip(roots, identities):
                qualify_private_storage(root)
                info = root.stat()
                require((info.st_dev, info.st_ino) == expected, 'A reviewed directory changed.')

        root, journal_root, backup_root = roots
        stage = 'protected-enrollment'
        initial = initialize_private_store(directory=root, environment_id=environment_id,
            owner_ref=owner_ref, authority_ref=authority_ref, review_ref=review_ref)
        require(initial.get('activated') is False, 'Unexpected activation state.')
        if initial.get('cancelled') is True:
            require(initial.get('initialized') is False, 'Unexpected cancellation state.')
            return dict(schema='onoes-mind-checkpointed-setup-candidate/v1', cancelled=True,
                        initialized=False, recoveryQualified=False, activated=False)
        require(initial.get('initialized') is True and initial.get('principals') == 0
                and initial.get('environment') == environment_id, 'Unexpected initialization receipt.')
        check_roots()
        stage = 'runtime-key-reopen'
        key_path, database = root / 'key-enrollment.json', root / 'ledger.sqlite'
        require(initial.get('keyEnrollment') == str(key_path) and initial.get('database') == str(database),
                'Setup paths differ from the reviewed directory.')
        history = Path(initial['deletionHistory'])
        require(history == Path(str(database) + '.deletions.jsonl'), 'Unexpected deletion-history path.')
        qualify_private_storage(key_path, kind='file')
        key_bytes = read_plain(key_path, 16384)
        package = json.loads(key_bytes, object_pairs_hook=unique_object)
        require(set(package) == {'schema','storeId','environment','recovery_envelope','runtime_envelope'}
                and package['schema'] == 'onoes-mind-key-enrollment/v1'
                and package['storeId'] == initial['storeId'] and package['environment'] == environment_id,
                'Key package context mismatch.')
        keys = unprotect_runtime_keys(package['runtime_envelope'], store_id=initial['storeId'],
                                      environment_id=environment_id)
        ledger = Ledger(database, deletion_ledger_path=history, environment_id=environment_id, **keys)
        require(ledger.integrity_report()['status'] == 'PASS'
                and ledger.db.execute('SELECT COUNT(*) FROM principals').fetchone()[0] == 0
                and ledger.db.execute('SELECT COUNT(*) FROM memory_records').fetchone()[0] == 0,
                'First-time store must remain empty and intact.')
        stage = 'current-journal'
        check_roots()
        authority = PersistentAuthorityCandidate.create(journal_root, ledger,
            store_id=initial['storeId'], environment=environment_id, review_ref=review_ref)
        save_new(root / 'checkpoint-authority-binding.json', asdict(authority.binding))
        stage = 'first-backup'
        check_roots()
        snapshot = backup_root / 'first-empty-snapshot.sqlite'
        publication = publish_snapshot_candidate(ledger, snapshot, authority,
            store_id=initial['storeId'], environment=environment_id)
        for item in (snapshot, Path(str(snapshot) + '.meta')):
            qualify_private_storage(item, kind='file')
        exported_keys = backup_root / 'encrypted-key-enrollment.json'
        exported_history = backup_root / 'snapshot-deletion-history.jsonl'
        save_new_bytes(exported_keys, key_bytes)
        save_new_bytes(exported_history, read_plain(history, 16 * 1024 * 1024))
        require(read_plain(exported_keys, 16384) == key_bytes, 'Encrypted key export mismatch.')
        backup_package = json.loads(read_plain(exported_keys, 16384), object_pairs_hook=unique_object)
        rehearsal_keys = unprotect_runtime_keys(backup_package['runtime_envelope'],
            store_id=initial['storeId'], environment_id=environment_id)
        save_new_bytes(backup_root / 'RESTORE-NOTES.txt',
            b'INACTIVE CANDIDATE FIRST BACKUP\n\nSnapshot, metadata, encrypted key package and matching deletion history are included.\n'
            b'The key package includes portable password encryption and current-account runtime protection; no plaintext keys.\n'
            b'Use the reviewed recovery procedure into a separate private folder. Enter the recovery password locally, never in chat.\n'
            b'This snapshot history is not proof of latest history after later deletions. Independently retained CURRENT checkpoint and complete newer history are still required.\n'
            b'No service, agent access or runtime binding is activated by this backup.\n')
        stage = 'restore-rehearsal'
        rehearsal = backup_root / 'restore-rehearsal.sqlite'
        restored = restore_checkpoint_candidate(snapshot, rehearsal, exported_history, authority,
            store_id=initial['storeId'], environment=environment_id, review_ref=review_ref, **rehearsal_keys)
        require(restored.integrity_report()['status'] == 'PASS'
                and restored.db.execute('SELECT COUNT(*) FROM principals').fetchone()[0] == 0
                and restored.db.execute('SELECT COUNT(*) FROM memory_records').fetchone()[0] == 0,
                'Empty-store recovery rehearsal did not pass.')
        restored.close();restored = None
        qualify_private_storage(rehearsal, kind='file')
        stage = 'close-source'
        ledger.close();ledger = None
        check_roots()
        stage = 'final-receipt'
        result = dict(schema='onoes-mind-checkpointed-setup-candidate/v1',
            storeId=initial['storeId'], environment=environment_id, initialized=True,
            activated=False, cancelled=False, principals=0, records=0,
            authorityBinding=asdict(authority.binding), publication=asdict(publication),
            snapshot=str(snapshot), rehearsal=str(rehearsal),
            backupArtifacts={item.name:hashlib.sha256(item.read_bytes()).hexdigest() for item in
                (snapshot, Path(str(snapshot) + '.meta'), exported_keys, exported_history)},
            recoveryQualified=False, candidateRehearsal='PASS', runtimeEnrollment=False)
        save_new(root / 'checkpointed-initialization-receipt.json', result)
        return result
    except Exception:
        raise CheckpointedSetupError(stage) from None
    finally:
        if restored is not None:
            restored.close()
        if ledger is not None:
            ledger.close()
        keys = None  # Ref clearing only, not a promise of complete Python memory erasure.
        rehearsal_keys = None
