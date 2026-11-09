"""Source-only bridge installation; never stop/start services or handle credentials.

Production apply/rollback require operator permission AND a stopped native runtime.
The default command only verifies the prepared files. Source changes by somebody
else are refused, including during rollback.
"""
import argparse
import ast
import hashlib
import json
import os
from pathlib import Path
import tempfile

FILES = frozenset((
    'gateway/session_controls.py', 'tui_gateway/contracts/canonical.py',
    'gateway/session_managed_worker.py', 'gateway/mesh_assignment_process.py',
    'gateway/mesh_windows_process.py', 'tools/file_tools_read_tracking.py',
    'tools/file_tools.py',
))
NEW_FILES = frozenset(('gateway/mesh_assignment_process.py', 'gateway/mesh_windows_process.py'))


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None


def checked_files(package, target, *, rollback=False):
    package, target = Path(package).resolve(), Path(target).resolve()
    manifest = json.loads((package / 'manifest.json').read_text())
    entries = manifest['files']
    if len(entries) != 7 or {e['relativePath'] for e in entries} != FILES:
        raise RuntimeError('Unexpected bridge manifest file set')
    for entry in entries:
        rel = entry['relativePath']
        if (entry['before'] is None) != (rel in NEW_FILES):
            raise RuntimeError('Only the two introduced helpers may have no original source')
        paths = [package / 'candidate' / rel, package / 'baseline' / rel, target / rel]
        if any(not p.resolve().is_relative_to(root) for p, root in
               zip(paths, [package, package, target])):
            raise RuntimeError('Bridge path leaves its declared root')
        candidate, baseline, installed = paths
        if digest(candidate) != entry['after'] or digest(baseline) != entry['before']:
            raise RuntimeError('Prepared bridge or rollback source changed')
        ast.parse(candidate.read_bytes(), filename=rel)
        allowed = (entry['before'], entry['after']) if rollback else (entry['before'],)
        if digest(installed) not in allowed:
            raise RuntimeError('Installed source changed; preserve it for review: ' + rel)
    return entries


def stopped_runtime():
    import psutil
    if any(c.status == psutil.CONN_LISTEN and c.laddr.port == 8642
           for c in psutil.net_connections(kind='tcp') if c.laddr):
        raise RuntimeError('Native listener is still running; source untouched')
    for process in psutil.process_iter(['name']):
        if 'python' not in (process.info['name'] or '').lower():
            continue
        try:
            cmd = ' '.join(process.cmdline())
        except psutil.NoSuchProcess:
            continue
        except psutil.AccessDenied as exc:
            raise RuntimeError('Cannot establish native writer quiescence') from exc
        if ('hermes_cli.main' in cmd and 'gateway' in cmd and 'run' in cmd
                or 'gateway.session_managed_worker' in cmd
                or 'gateway.session_worker_spawn' in cmd):
            raise RuntimeError('Native gateway/worker is still present; source untouched')


def replace_bytes(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, staged = tempfile.mkstemp(prefix='.mesh-bridge-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(staged, path)
    finally:
        if os.path.exists(staged):
            os.unlink(staged)  # Only this invocation's uniquely created staging file.


def change_sources(package, target, *, assert_stopped, rollback=False):
    package, target = Path(package).resolve(), Path(target).resolve()
    entries = checked_files(package, target, rollback=rollback)
    assert_stopped()
    for entry in entries:
        assert_stopped()
        path = target / entry['relativePath']
        allowed = (entry['before'], entry['after']) if rollback else (entry['before'],)
        if digest(path) not in allowed:
            raise RuntimeError('Concurrent source edit; stop and reconcile')
        expected = entry['before'] if rollback else entry['after']
        if digest(path) == expected:
            continue
        if expected is None:
            # Only a new helper whose exact candidate hash was verified above.
            path.unlink()
        else:
            selected = package / ('baseline' if rollback else 'candidate') / entry['relativePath']
            content = selected.read_bytes()
            if hashlib.sha256(content).hexdigest() != expected:
                raise RuntimeError('Prepared source changed during maintenance')
            replace_bytes(path, content)
        if digest(path) != expected:
            raise RuntimeError('Bridge source verification failed')
    assert_stopped()
    return {'files': len(entries), 'action': 'rollback' if rollback else 'apply',
            'servicesStarted': False, 'credentialsChanged': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['dry-run', 'apply', 'rollback'], default='dry-run', nargs='?')
    parser.add_argument('--maintenance-approved', action='store_true')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    package = root / 'data/native-bridge-rollout-fb4d589d-0904-4282-bd67-5be857252ebe'
    target = Path('C:/Users/eMitchell109/AppData/Local/hermes/hermes-agent')
    if args.action == 'dry-run':
        print(json.dumps({'action': 'dry-run', 'files': len(checked_files(package, target)),
                          'sourceChanged': False, 'servicesChanged': False}))
    else:
        if not args.maintenance_approved:
            parser.error('Explicit maintenance permission is required; nothing changed')
        print(json.dumps(change_sources(package, target, assert_stopped=stopped_runtime,
                                         rollback=args.action == 'rollback')))


if __name__ == '__main__':
    main()
