"""Pinned opt-in process ownership patch for a dedicated native LOCAL owner."""
import ast
import hashlib
from pathlib import Path
import textwrap


BASELINE = '4d51ca8d605ee3facc20e3ef6b8d9f3aeebe5ac14c849a7a4174937f9a5198f4'


def assignment_process_candidate(native_root):
    name = 'gateway/session_managed_worker.py'
    raw = (native_root/name).read_bytes()
    if hashlib.sha256(raw).hexdigest() != BASELINE:
        raise RuntimeError('Pinned native managed-worker source changed')
    original = raw.decode('utf-8').replace('\r\n', '\n')
    candidate = original
    replacements = [
        ('async def _spawn_registered_worker(authority, ref, row):',
         'async def _spawn_registered_worker(authority, ref, row, assignment_scope=None):'),
        ('acquire_process(subprocess.Popen,',
         'acquire_process(assignment_scope.popen if assignment_scope is not None else subprocess.Popen,'),
        ('spawned = await _spawn_registered_worker(authority, ref, row)',
         'spawned = await _spawn_registered_worker(authority, ref, row, assignment_scope=assignment_scope)'),
    ]
    for before, after in replacements:
        if candidate.count(before) != 1:
            raise RuntimeError('Pinned native worker launch shape changed')
        candidate = candidate.replace(before, after)
    function = next(n for n in ast.parse(candidate).body
                    if isinstance(n, ast.AsyncFunctionDef) and n.name == 'execute_managed')
    lines = candidate.splitlines(True)
    body = ''.join(lines[function.lineno:function.end_lineno])
    wrapped = (
        '    from gateway.mesh_assignment_process import make_assignment_scope\n'
        '    assignment_scope = make_assignment_scope(authority, ref, row, policy)\n'
        '    try:\n' + textwrap.indent(body, '    ') +
        '    finally:\n'
        '        if assignment_scope is not None:\n'
        '            await asyncio.to_thread(assignment_scope.retire)\n')
    lines[function.lineno:function.end_lineno] = [wrapped]
    candidate = ''.join(lines)
    ast.parse(candidate)
    directory = Path(__file__).resolve().parent
    helper = (directory/'native_assignment_process.py').read_text().replace(
        'from integrations.windows_writer_fence import WindowsWriterFence',
        'from gateway.mesh_windows_process import WindowsWriterFence')
    windows = (directory/'windows_writer_fence.py').read_text()
    helpers = {'gateway/mesh_assignment_process.py': helper,
               'gateway/mesh_windows_process.py': windows}
    if any((native_root/path).exists() for path in helpers):
        raise RuntimeError('Native assignment helper path already exists')
    for source in helpers.values():
        ast.parse(source)
    return {name: original, **{path: '' for path in helpers}}, {name: candidate, **helpers}
