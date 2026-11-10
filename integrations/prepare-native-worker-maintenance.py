"""Prepare private rollback/candidate files; never install, launch or authenticate."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
HOME = Path('C:/Users/eMitchell109/AppData/Local/hermes')
TARGETS = ('gateway/session_controls.py', 'tui_gateway/contracts/canonical.py')


def digest(data):
    return hashlib.sha256(data).hexdigest()


def prepare_launcher(original):
    bom, encoding = (b'', 'utf-8')
    for marker, codec in ((b'\xff\xfe', 'utf-16-le'), (b'\xfe\xff', 'utf-16-be'), (b'\xef\xbb\xbf', 'utf-8')):
        if original.startswith(marker):
            bom, encoding = marker, codec
            break
    text = original[len(bom):].decode(encoding)
    if re.search(r'MESH_LOCAL_PROCESS_SCOPE|meshWorkerEnvironment', text, re.I):
        raise RuntimeError('Existing Mesh setting or variable requires separate review')
    shells = list(re.finditer(r'^([ \t]*Set[ \t]+(\w+)[ \t]*=[ \t]*CreateObject\("WScript\.Shell"\)[ \t]*)(\r?\n)', text, re.I | re.M))
    if len(shells) != 1:
        raise RuntimeError('Expected exactly one explicit WScript.Shell assignment')
    match = shells[0]
    newline = match.group(3)
    variable = match.group(2)
    addition = newline.join(['Dim meshWorkerEnvironment',
        f'Set meshWorkerEnvironment = {variable}.Environment("Process")',
        'meshWorkerEnvironment("MESH_LOCAL_PROCESS_SCOPE") = "1"']) + newline
    # Preserve every original byte including the encoding BOM and newline style.
    offset = len(text[:match.end()].encode(encoding)) + len(bom)
    return original[:offset] + addition.encode(encoding) + original[offset:]


def main():
    if sys.argv[1:]:
        raise RuntimeError('No alternate native root, launcher, installation or activation options accepted')
    metadata = json.loads((ROOT / 'data/native-process-capability-candidate.json').read_text())
    reviewed = json.loads((ROOT / 'integrations/native-process-capability-qualification.json').read_text())
    if any(metadata[key] != reviewed[key] for key in ('baselineHashes', 'candidateHashes')):
        raise RuntimeError('Candidate does not match the reviewed capability patch')
    source = Path(metadata['source']).resolve()
    if (source.parent.parent != (ROOT / 'data').resolve()
            or not source.parent.name.startswith('native-process-capability-')
            or source.name != 'source' or metadata.get('installed') is not False
            or metadata.get('enrollmentEnabled') is not False):
        raise RuntimeError('Reviewed offline native candidate required')
    launcher = HOME / 'gateway-service/Hermes_Gateway.vbs'
    originals, candidates = {}, {}
    for name in TARGETS:
        originals[name] = (HOME / 'hermes-agent' / name).read_bytes()
        candidates[name] = (source / name).read_bytes()
        if (digest(originals[name]) != metadata['baselineHashes'][name]
                or digest(candidates[name]) != metadata['candidateHashes'][name]):
            raise RuntimeError('Native source changed; do not prepare against stale evidence')
    name = 'gateway-service/Hermes_Gateway.vbs'
    originals[name] = launcher.read_bytes()
    candidates[name] = prepare_launcher(originals[name])
    directory = ROOT / 'data' / ('native-worker-maintenance-' + str(uuid4()))
    directory.mkdir()
    files = {}
    for name in originals:
        for label, data in [('rollback', originals[name]), ('candidate', candidates[name])]:
            path = directory / label / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        files[name] = {'before': digest(originals[name]), 'after': digest(candidates[name])}
    result = {'schema': 'mesh-native-worker-maintenance/v1',
        'preparedAt': datetime.now(timezone.utc).isoformat(), 'directory': str(directory),
        'status': 'PREPARED_NOT_INSTALLED', 'files': files,
        'topology': 'Existing single gateway owner; no second gateway or lock override',
        'setting': 'MESH_LOCAL_PROCESS_SCOPE=1 in existing launcher process environment',
        'credentialsCopied': False, 'restartPerformed': False, 'modelTasksSent': 0,
        'activationAuthorized': False,
        'remaining': ['Explicit shared-gateway maintenance approval',
            'Recheck all original hashes and active-work state before any installation',
            'Verify owner health and read-only capability after authorized restart',
            'Separate approval for a new disposable team trial; never replay the held trial']}
    (directory / 'maintenance.json').write_text(json.dumps(result, indent=2) + '\n')
    (ROOT / 'data/native-worker-maintenance-prepared.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
