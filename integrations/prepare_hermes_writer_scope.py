"""Prepare and qualify a pinned native-launcher patch; never edit the installed source.

Run with the exact installed tools/process_registry.py path as the sole argument.
The qualified method uses fixture registry/session dependencies and real Windows
processes; this is not whole-Hermes, tool-policy, delegation or live qualification.
"""
import ast
import difflib
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import types
import uuid
from unittest.mock import patch
from integrations import hermes_writer_scope as scope
from integrations.windows_writer_fence import WindowsWriterFence

BASELINE = '6491641456b51eb78c36a50a8508f145da328f7c70a432bced84b3b329e0046e'


def prepare(source_path):
    raw = source_path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != BASELINE:
        raise RuntimeError('Native source changed; review and pin its new baseline before patching')
    original = raw.decode('utf-8').replace('\r\n', '\n')
    lines = original.splitlines(keepends=True)
    registry = next(n for n in ast.parse(original).body if isinstance(n, ast.ClassDef) and n.name == 'ProcessRegistry')
    for name, local in [('spawn_via_env', False), ('spawn_local', True)]:
        fn = next(n for n in registry.body if isinstance(n, ast.FunctionDef) and n.name == name)
        body = ''.join(lines[fn.lineno - 1:fn.end_lineno])
        if local:
            if body.count('proc = subprocess.Popen(') != 1:
                raise RuntimeError('Unexpected native pipe-launch shape')
            body = body.replace('proc = subprocess.Popen(', 'proc = scoped_popen(')
        doc_end = fn.body[0].end_lineno - fn.lineno + 1
        method_lines = body.splitlines(keepends=True)
        method_lines[doc_end:doc_end] = [
            '        from tools.mesh_writer_scope import require_supported_writer_route, scoped_popen\n',
            f'        require_supported_writer_route(local={local}, '
            + ('use_pty=use_pty, ' if local else '') + 'persist_on_release=persist_on_release)\n']
        lines[fn.lineno - 1:fn.end_lineno] = [''.join(method_lines)]
        # Reparse positions after each edit; never apply a second edit at stale offsets.
        registry = next(n for n in ast.parse(''.join(lines)).body if isinstance(n, ast.ClassDef) and n.name == 'ProcessRegistry')
        lines = ''.join(lines).splitlines(keepends=True)
    candidate = ''.join(lines)
    ast.parse(candidate)
    root = Path(__file__).resolve().parents[1]
    out = root / 'data' / ('hermes-writer-scope-' + str(uuid.uuid4()))
    (out / 'tools').mkdir(parents=True)
    modules = {'tools/process_registry.py': candidate,
               'tools/mesh_writer_scope.py': (root / 'integrations/hermes_writer_scope.py').read_text(encoding='utf-8'),
               'tools/mesh_windows_writer_fence.py': (root / 'integrations/windows_writer_fence.py').read_text(encoding='utf-8')}
    patch_text = ''.join(difflib.unified_diff(original.splitlines(True), candidate.splitlines(True),
                                           fromfile='a/tools/process_registry.py', tofile='b/tools/process_registry.py'))
    for path, text in modules.items():
        (out / path).write_bytes(text.encode('utf-8'))
        if path != 'tools/process_registry.py':
            patch_text += ''.join(difflib.unified_diff([], text.splitlines(True), fromfile='/dev/null', tofile='b/' + path))
    (out / 'candidate.patch').write_bytes(patch_text.encode('utf-8'))
    return out, candidate, modules


def qualify(candidate):
    """Execute the actual edited launcher methods, with no native singleton/config import."""
    registry = next(n for n in ast.parse(candidate).body if isinstance(n, ast.ClassDef) and n.name == 'ProcessRegistry')
    functions = [n for n in registry.body if isinstance(n, ast.FunctionDef) and n.name in ('spawn_local', 'spawn_via_env')]
    namespace = {'os': __import__('os'), 'subprocess': subprocess, 'ProcessSession': types.SimpleNamespace,
                 'Any': object, '_IS_WINDOWS': True, 'windows_hide_flags': lambda: 0x08000000,
                 '_resolve_safe_cwd': lambda value: value, 'worker_output_log': lambda _: None}
    exec(compile(ast.Module(body=functions, type_ignores=[]), '<pinned-native-launcher-fixture>', 'exec'), namespace)
    fixture_type = type('RegistryFixture', (), {name: namespace[name] for name in ('spawn_local', 'spawn_via_env')})
    fixture = fixture_type()
    fixture._new_session = lambda *a, **k: types.SimpleNamespace(id='fixture', cwd=str(Path.cwd()), systemd_unit='')
    fixture._scope_argv = lambda *a: [sys.executable, '-c', 'print("native fenced output")']
    fixture._spawn_env = lambda _: None
    fixture._reader_loop = lambda *a: None
    fixture._track_started = lambda *a: None
    fixture._safe_host_start_time = lambda _: None
    tools = types.ModuleType('tools'); tools.__path__ = []
    rewrite = types.ModuleType('tools.terminal_tool_sudo'); rewrite._rewrite_compound_background = lambda value: value
    fence = WindowsWriterFence('native-launcher-fixture', 'one')
    checks = []
    try:
        with patch.dict(sys.modules, {'tools': tools, 'tools.mesh_writer_scope': scope, 'tools.terminal_tool_sudo': rewrite}):
            with scope.bind_writer_fence(fence):
                session = fixture.spawn_local('fixture', task_id='fixture')
                with session.process as proc:
                    output, _ = proc.communicate(timeout=5)
                    if output.strip() != 'native fenced output':
                        raise AssertionError('Native pipe output mismatch')
                checks.append('actual_native_pipe_launcher_output')
                for name, fn in [('pty_refused', lambda: fixture.spawn_local('fixture', use_pty=True)),
                                 ('retained_refused', lambda: fixture.spawn_local('fixture', persist_on_release=True)),
                                 ('remote_refused', lambda: fixture.spawn_via_env(None, 'fixture'))]:
                    try:
                        fn()
                    except RuntimeError:
                        checks.append(name)
                    else:
                        raise AssertionError(name + ' unexpectedly allowed')
            fence.seal()
            if not fence.wait()['processTreeEnded'] or fence.snapshot()['writerQuiescence']:
                raise AssertionError('Unexpected worker-release authority')
            checks.append('ended_tree_is_not_whole_worker_release')
    finally:
        fence.terminate(); fence.close()
    return checks


if __name__ == '__main__':
    out, candidate, modules = prepare(Path(sys.argv[1]))
    report = {'state': 'candidate_only', 'baselineSha256': BASELINE,
              'files': {name: hashlib.sha256(text.encode()).hexdigest() for name, text in modules.items()},
              'liveInstallation': False, 'wholeWorkerReleaseQualified': False}
    try:
        report['checks'] = qualify(candidate)
        report['qualification'] = 'PASS'
    except BaseException as error:
        report.update(qualification='FAIL', errorClass=type(error).__name__)
        (out / 'qualification.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
        raise
    (out / 'qualification.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps({'directory': str(out), **report}, indent=2))
