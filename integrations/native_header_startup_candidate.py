"""Reproduce the reviewed header fix only inside a disposable native fixture."""
import hashlib
import json
from pathlib import Path
import subprocess

HEADER_BASELINES = {
    'hermes_cli/version_info.py': 'c9063a4a9b0ae7dd7027bf58955f3890b0ac671caa9be5fbd3f5bce02bcea0da',
    'agent/codex_headers.py': '54d165f64bb3988c16254f587a5dccac2efa988e57e86027714bf98f16bbbca9',
}


def header_startup_candidate(source):
    root = Path(__file__).resolve().parents[1]
    source = Path(source).resolve()
    if (source.name != 'source' or source.parent.parent != root / 'data'
            or not source.parent.name.startswith('hermes-local-session-')):
        raise RuntimeError('Header candidate requires an isolated local-session fixture')
    qualification = json.loads((root / 'integrations/native-header-startup-qualification.json').read_text())
    if set(qualification['files']) != set(HEADER_BASELINES):
        raise RuntimeError('Header qualification file set changed')
    originals, modules, patches = {}, {}, []
    for name, digest in HEADER_BASELINES.items():
        target = source / name
        if (not target.resolve().is_relative_to(source) or target.is_symlink()
                or hashlib.sha256(target.read_bytes()).hexdigest() != digest):
            raise RuntimeError('Header fixture baseline changed: ' + name)
        if qualification['files'][name]['beforeSha256'] != digest:
            raise RuntimeError('Header qualification baseline changed')
        originals[name] = target.read_bytes().decode('utf-8')
        patch = root / 'integrations' / ('native-' + Path(name).stem + '-startup.patch')
        headers = [line for line in patch.read_text().splitlines() if line.startswith(('--- ', '+++ '))]
        if headers != ['--- a/' + name, '+++ b/' + name]:
            raise RuntimeError('Header patch changes an unexpected file')
        patches.append(str(patch))
    command = ['git', 'apply', '--unidiff-zero', '--directory=' + source.relative_to(root).as_posix()]
    subprocess.run(command + ['--check'] + patches, cwd=root, check=True, capture_output=True, timeout=30)
    subprocess.run(command + patches, cwd=root, check=True, capture_output=True, timeout=30)
    for name in HEADER_BASELINES:
        target = source / name
        normalized = target.read_bytes().replace(b'\r\n', b'\n')
        expected = qualification['files'][name]['candidateSha256']
        matches = [data for data in (normalized, normalized.replace(b'\n', b'\r\n'))
                   if hashlib.sha256(data).hexdigest() == expected]
        if not matches:
            raise RuntimeError('Replayed header fix differs from qualified source: ' + name)
        target.write_bytes(matches[0])
        modules[name] = matches[0].decode('utf-8')
    return originals, modules
