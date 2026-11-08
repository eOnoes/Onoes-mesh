"""Build a pinned, isolated Relay receipt patch. Does not edit/start installed Relay."""
import ast
import difflib
import hashlib
from pathlib import Path
import uuid

BASELINE = 'ad0444ac043dcdb5aa6baa008c4b58b47144f56925b39759a44dbbeafac2fafd'


def prepare(source_path):
    raw = Path(source_path).read_bytes()
    if hashlib.sha256(raw).hexdigest() != BASELINE:
        raise RuntimeError('Relay receipt source changed; review its baseline first')
    original = raw.decode('utf-8').replace('\r\n', '\n')
    before = "            'observation': 'observed', 'terminal': status['status'] in TERMINAL}"
    if original.count(before) != 1:
        raise RuntimeError('Unexpected Relay receipt projection shape')
    candidate = original.replace(before, before[:-1]
        + ", 'writerLifecycle': project_writer_observation(status.get('writer_lifecycle'), saved['runId'])}")
    candidate = candidate.replace('import re\n', 'import re\nfrom relay_writer_observation import project as project_writer_observation\n', 1)
    root = Path(__file__).resolve().parents[1]
    helper = (root / 'integrations/relay_writer_observation.py').read_text(encoding='utf-8')
    ast.parse(candidate); ast.parse(helper)
    out = root / 'data' / ('relay-writer-observation-' + str(uuid.uuid4()))
    out.mkdir(parents=True)
    (out / 'relay_native_receipts.py').write_bytes(candidate.encode('utf-8'))
    (out / 'relay_writer_observation.py').write_bytes(helper.encode('utf-8'))
    patch = ''.join(difflib.unified_diff(original.splitlines(True), candidate.splitlines(True),
                    fromfile='a/relay_native_receipts.py', tofile='b/relay_native_receipts.py'))
    patch += ''.join(difflib.unified_diff([], helper.splitlines(True),
                    fromfile='/dev/null', tofile='b/relay_writer_observation.py'))
    (out / 'candidate.patch').write_bytes(patch.encode('utf-8'))
    return out


if __name__ == '__main__':
    import sys
    print(prepare(sys.argv[1]))
