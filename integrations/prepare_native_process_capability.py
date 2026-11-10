"""Prepare (never install) the read-only native process-enrollment capability."""
import ast
import difflib
import hashlib
import json
from pathlib import Path
import subprocess
import uuid

ROOT = Path(__file__).resolve().parents[1]
FILES = ('gateway/session_controls.py', 'tui_gateway/contracts/canonical.py')


def candidate_sources(sources):
    result = dict(sources)
    needle = "        out = {'found': saved is not None,"
    text = sources[FILES[0]]
    if text.count(needle) != 1:
        raise ValueError('Expected one original lookup result')
    result[FILES[0]] = text.replace(needle,
        "        import os\n"
        "        out = {'process_scope_supported': os.name == 'nt' and os.environ.get('MESH_LOCAL_PROCESS_SCOPE') == '1',\n"
        "               'found': saved is not None,", 1)
    needle = '    process_scope: AssignmentProcessObservation | None = None'
    if sources[FILES[1]].count(needle) != 1:
        raise ValueError('Expected one original lookup contract')
    result[FILES[1]] = sources[FILES[1]].replace(needle,
        needle + '\n    process_scope_supported: bool | None = None', 1)
    for text in result.values():
        ast.parse(text)
    return result


def prepare(native):
    native = Path(native)
    baseline = json.loads((ROOT / 'integrations/native-header-fixture-qualification.json').read_text())['candidateFiles']
    raw = {name: (native / name).read_bytes() for name in FILES}
    for name, value in raw.items():
        if hashlib.sha256(value).hexdigest() != baseline[name]:
            raise ValueError('Installed baseline changed: ' + name)
    before = {name: value.decode('utf-8').replace('\r\n', '\n') for name, value in raw.items()}
    after = candidate_sources(before)
    patch = ''.join(''.join(difflib.unified_diff(before[name].splitlines(True), after[name].splitlines(True),
        fromfile='a/' + name, tofile='b/' + name, n=0)) for name in FILES)
    patch_path = ROOT / 'integrations/native-process-scope-capability.patch'
    if patch_path.exists() and patch_path.read_bytes() != patch.encode():
        raise ValueError('A different capability patch already exists; inspect it first')
    patch_path.write_bytes(patch.encode())
    source = ROOT / 'data' / ('native-process-capability-' + str(uuid.uuid4())) / 'source'
    for name in FILES:
        target = source / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw[name])
    # A separate empty Git root prevents apply from silently filtering paths
    # against the parent Mesh worktree when running inside its data directory.
    subprocess.run(['git', 'init', '--quiet'], cwd=source, check=True, capture_output=True, timeout=20)
    for args in (['--check'], []):
        subprocess.run(['git', 'apply', '--unidiff-zero', *args, str(patch_path)], cwd=source,
                       check=True, capture_output=True, timeout=20)
    hashes = {}
    for name in FILES:
        target = source / name
        normalized = target.read_bytes().decode('utf-8').replace('\r\n', '\n')
        if normalized != after[name]:
            raise ValueError('Applied candidate differs: ' + name)
        expected = after[name].replace('\n', '\r\n' if b'\r\n' in raw[name] else '\n').encode()
        target.write_bytes(expected)
        hashes[name] = hashlib.sha256(expected).hexdigest()
    return {'source': str(source), 'baselineHashes': {name: baseline[name] for name in FILES},
            'candidateHashes': hashes, 'installed': False, 'enrollmentEnabled': False}


if __name__ == '__main__':
    import sys
    print(json.dumps(prepare(sys.argv[1]), indent=2))
