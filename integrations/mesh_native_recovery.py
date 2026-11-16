"""Inactive recovery primitive: preserve a proven-retired native Mesh attempt.

This does not launch anything, enroll access, or enable automatic recovery.
The caller must retain the named launcher window through its eventual handoff.
Uncertain launch records deliberately remain held for reconciliation.
"""
import os
from pathlib import Path


class NativeRecoveryHold(RuntimeError):
    pass


def archive_retired_mesh_attempt(window, *, launch_module, mesh_profile,
                                mesh_sha256, reader_approval):
    window.assert_held()
    expected = window.workspace / 'integrations/mind-recovery-candidate/mesh_launch_candidate.py'
    if Path(launch_module.__file__).resolve() != expected:
        raise NativeRecoveryHold('Recovery helper is outside the installed workspace.')
    # Reuse the existing exact-source, private-profile and live-reader checks.
    # No token or grant is issued by this preflight.
    p, roles = launch_module.checked_launch(mesh_profile, mesh_sha256, reader_approval)
    from onoes_mind.enrollment_store import qualify_private_storage
    root = qualify_private_storage(Path(mesh_profile).parent)
    paths = [Path(p[n]) for n in ('attemptPath', 'stdoutPath', 'stderrPath')]
    if len(set(paths)) != 3 or any(path.parent != root for path in paths):
        raise NativeRecoveryHold('Recovery paths do not match the private profile.')
    attempt, out, err = paths
    if not os.path.lexists(attempt):
        if any(os.path.lexists(path) for path in (out, err)):
            raise NativeRecoveryHold('Partial launch evidence remains; preserve it.')
        return dict(state='absent', archived=False)
    for path in paths:
        qualify_private_storage(path, kind='file')
    record = roles.plain_json(attempt)
    keys = {'schema', 'profileSha256', 'pid', 'creationTicks', 'executable',
            'entryPoint', 'state', 'credentialsInRecord'}
    if (type(record) is not dict or set(record) != keys
            or record['schema'] != 'onoes-mesh-native-child/v1'
            or record['profileSha256'] != mesh_sha256
            or record['state'] != 'input_sent'
            or record['credentialsInRecord'] is not False
            or type(record['pid']) is not int or record['pid'] <= 0
            or type(record['creationTicks']) is not int or record['creationTicks'] <= 0
            or record['executable'] != p['nodeExecutable']
            or record['entryPoint'] != str(window.workspace / 'serve.mjs')):
        raise NativeRecoveryHold('Native launch identity or delivery is unresolved.')
    # Access denial and observation errors propagate. Only authoritative absence,
    # a different creation identity, or a signaled original handle proves retired.
    if roles.same_process_alive(record['pid'], record['creationTicks']):
        raise NativeRecoveryHold('The original native Mesh owner is still running.')
    suffix = f".retired-{record['pid']}-{record['creationTicks']}"
    destinations = [path.with_name(path.name + suffix) for path in paths]
    if any(os.path.lexists(path) for path in destinations):
        raise NativeRecoveryHold('Retirement destination already exists; preserve evidence.')
    # Validate every source and destination before any move. Keep the attempt
    # until last: interruption leaves a blocking record, never a clean retry.
    for source, destination in zip(paths, destinations):
        if source.resolve(strict=True).parent != root or destination.parent != root:
            raise NativeRecoveryHold('Retirement path changed.')
    for index in (1, 2, 0):
        os.rename(paths[index], destinations[index])
    return dict(state='retired', archived=True, pid=record['pid'],
                creationTicks=record['creationTicks'],
                archives=[str(path) for path in destinations])
