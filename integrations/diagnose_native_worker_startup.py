"""Owned disposable fixture; startup diagnostics are installed before spawn."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import uuid

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
from integrations.qualify_native_local_session import prepare_local
from integrations.qualify_hermes_runtime import runtime_environment
from integrations.windows_writer_fence import WindowsWriterFence
from integrations.native_startup_markers import instrument_worker

native = 'C:/Users/eMitchell109/AppData/Local/hermes/hermes-agent'
executable = 'C:/Users/eMitchell109/AppData/Local/hermes/tools/python-3.14.9+20261021-win32-x64/python.exe'
fixture = prepare_local(native)
worker = fixture / 'source/agent/managed_worker.py'
original = worker.read_bytes()
marker = b'\nimport json\n'
if original.count(marker) != 1:
    raise RuntimeError('Unexpected worker import seam; fixture not started')
instrumentation = (
    '\nimport faulthandler as _mesh_fixture_faults\n'
    '_mesh_fixture_trace = open(' + repr(str(fixture / 'worker-startup-stacks.log')) + ', "a")\n'
    '_mesh_fixture_faults.dump_traceback_later(15, repeat=True, file=_mesh_fixture_trace)\n'
    'import json\n'
).encode()
worker.write_bytes(instrument_worker(original.replace(marker, instrumentation)))
report = {'schema': 'mesh-native-startup-diagnostic/v1', 'fixture': str(fixture),
          'sourceInstrumentation': 'fixed startup phase labels and faulthandler enabled in disposable worker before process start',
          'originalWorkerSha256': hashlib.sha256(original).hexdigest(),
          'instrumentedWorkerSha256': hashlib.sha256(worker.read_bytes()).hexdigest(),
          'liveGatewayChanged': False, 'liveInjection': False, 'realProvider': False,
          'qualification': 'DIAGNOSTIC_ONLY_NOT_RELEASE_ACCEPTANCE'}
(root / 'data/native-startup-diagnostic-current.json').write_text(json.dumps(report, indent=2))
print(json.dumps(report), flush=True)
environment = runtime_environment(fixture, native, executable, ('--safe-mode',))
fence = WindowsWriterFence('worker-startup-diagnostic', str(uuid.uuid4()))
try:
    with (fixture / 'startup-diagnostic-runtime.log').open('wb') as log:
        with fence.popen([executable, str(root / 'integrations/qualify_native_local_session.py'),
                          '--child', str(fixture)], cwd=str(fixture / 'source'),
                         env=environment, stdout=log, stderr=subprocess.STDOUT) as process:
            try:
                code = process.wait(timeout=180)
            except subprocess.TimeoutExpired:
                report['timedOut'] = True
                fence.terminate()  # Only this owned disposable fixture's job.
                code = process.wait(timeout=20)
    fence.seal()
    report.update(exitCode=code, ownedProcessObservation=fence.wait(5000))
    (root / 'data/native-startup-diagnostic-current.json').write_text(json.dumps(report, indent=2))
    print(json.dumps(report), flush=True)
finally:
    fence.terminate()
    fence.close()
