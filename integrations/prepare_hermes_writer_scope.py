"""Prepare and qualify a pinned native-launcher patch; never edit the installed source.

Run with the exact installed tools/process_registry.py path as the sole argument.
The qualified functions use fixture registry/profile/ledger dependencies and real
threads/processes; this is not whole-Hermes, complete-tool-policy or live qualification.
"""
import ast
import asyncio
from contextlib import nullcontext, suppress
from contextvars import copy_context
from concurrent.futures import ThreadPoolExecutor
import difflib
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import threading
import time
import typing
import types
import uuid
from unittest.mock import patch
from integrations import hermes_writer_scope as scope
from integrations.windows_writer_fence import WindowsWriterFence

BASELINE = '6491641456b51eb78c36a50a8508f145da328f7c70a432bced84b3b329e0046e'
FOREGROUND_BASELINE = '723e8f0bc27c58c310f9530732c889e5f8480d74e12402656ed0033e08afc27c'
FILE_TOOLS_BASELINE = '1a23773abe410feb5dd99276d08b6c0837624309ea489c508d683c6965408f94'
TERMINAL_TOOL_BASELINE = 'a09910c7c61a93d89e8b9e83efd3abcb5eff4b58a3cb53e3bd0162d2ee59e909'
TITLE_BASELINE = 'e5beaa6185f91e887d27a35a5acdde613c0144c156e63ed053566127ff25ce0f'
CANONICAL_WORKER_BASELINE = 'efc702798fcb827b77ad485c7559643d5ecf407b06b5f115c8e3047752054c8a'
CANONICAL_INGRESS_BASELINE = '9b308b2ddf9cac9223361663c16eed1665feb4087fc0b58e0e3245e9708ce9a0'
TOOL_WORKER_BASELINES = {
    'agent/tool_executor.py': '3fb81cd7ec8946df1f6e50b0879b4be4499223b4236450da0581ac7c0a1727e6',
    'agent/terminal_approval_batch.py': '3ac8420c2cdbbaf8d6f8241be5154a75aff4da54fd090492e9ce9ce9396e71dc'}
LIFETIME_BASELINES = {
    'tools/async_delegation.py': '1bcff60c59c453f1e3d7d049bcf525b727df07c1d7e1eeb45ba0776598c3c2b6',
    'gateway/platforms/api_server_runs.py': '481b67c8cddd2dcca3a9b60d938d0cec5d621a4648784119873d60ffcd975138'}


def lifetime_candidates(native_root):
    originals, changed = {}, {}
    for path, expected in LIFETIME_BASELINES.items():
        raw = (native_root / path).read_bytes()
        if hashlib.sha256(raw).hexdigest() != expected:
            raise RuntimeError('Native lifetime source changed: ' + path)
        original = raw.decode('utf-8').replace('\r\n', '\n')
        originals[path] = original
        lines = original.splitlines(True)
        tree = ast.parse(original)
        if path.startswith('tools/'):
            fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == '_dispatch_admitted')
            body = ''.join(lines[fn.lineno - 1:fn.end_lineno])
            old = 'executor.submit(propagate_context_to_thread(_worker))'
            if body.count(old) != 1:
                raise RuntimeError('Unexpected native delegation submission shape')
            body = body.replace(old, 'submit_writer_work(executor, _worker, propagate_context_to_thread)')
            method = body.splitlines(True)
            method.insert(fn.body[0].end_lineno - fn.lineno + 1,
                          '    from tools.mesh_writer_scope import submit_writer_work\n')
            lines[fn.lineno - 1:fn.end_lineno] = [''.join(method)]
        else:
            fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == '_run_agent_sync')
            split = fn.body[0].end_lineno
            body = lines[split:fn.end_lineno]
            lines[split:fn.end_lineno] = [
                '    from tools.mesh_writer_scope import writer_foreground_scope\n',
                "    with writer_foreground_scope(getattr(run, 'writer_lifetime', None), expected_run_id=run.run_id, expected_generation=getattr(run, 'writer_generation', '')):\n",
                *['    ' + line if line.strip() else line for line in body]]
            current = ''.join(lines)
            launch = next(n for n in ast.parse(current).body if isinstance(n, ast.ClassDef) and n.name == '_RunLaunch')
            last = max(n.end_lineno for n in launch.body if isinstance(n, ast.AnnAssign))
            lines = current.splitlines(True)
            lines.insert(last, '    writer_lifetime: Any = None  # Trusted in-process factory only; never request JSON.\n')
            lines.insert(last + 1, "    writer_generation: str = ''\n")
            current = ''.join(lines)
            execute = next(n for n in ast.parse(current).body if isinstance(n, ast.AsyncFunctionDef) and n.name == '_execute_run')
            body = ''.join(current.splitlines(True)[execute.lineno - 1:execute.end_lineno])
            old = '        else:\n            with self._profile_scope(run.request_profile):\n'
            if body.count(old) != 1:
                raise RuntimeError('Unexpected native direct-executor admission shape')
            body = body.replace(old, '        else:\n'
                '            from tools.mesh_writer_scope import enroll_direct_writer_run\n'
                "            enroll_direct_writer_run(getattr(self, '_mesh_writer_runs', None), run)\n"
                '            with self._profile_scope(run.request_profile):\n')
            lines = current.splitlines(True)
            lines[execute.lineno - 1:execute.end_lineno] = [body]
            current = ''.join(lines)
            before = '    current.update(fields)\n'
            if current.count(before) != 1:
                raise RuntimeError('Unexpected native status update shape')
            current = current.replace(before, before
                + '    from tools.mesh_writer_scope import observe_writer_run\n'
                + "    current['writer_lifecycle'] = observe_writer_run(getattr(self, '_mesh_writer_runs', None), run_id)\n")
            before = ('    _, status, _, _, err = _load_owned_run(\n'
                      '        self, request, _api_server=_api_server, permission="status", active_fallback=True)\n'
                      '    return err or web.json_response(status)\n')
            after = ('    run_id, status, _, _, err = _load_owned_run(\n'
                     '        self, request, _api_server=_api_server, permission="status", active_fallback=True)\n'
                     '    if err is not None:\n'
                     '        return err\n'
                     '    from tools.mesh_writer_scope import observe_writer_run\n'
                     "    status = {**status, 'writer_lifecycle': observe_writer_run(getattr(self, '_mesh_writer_runs', None), run_id)}\n"
                     '    return web.json_response(status)\n')
            if current.count(before) != 1:
                raise RuntimeError('Unexpected owned native run-status handler shape')
            lines = current.replace(before, after).splitlines(True)
        changed[path] = ''.join(lines)
        ast.parse(changed[path])
    return originals, changed


def foreground_candidate(native_root):
    path = 'tools/environments/local.py'
    raw = (native_root / path).read_bytes()
    if hashlib.sha256(raw).hexdigest() != FOREGROUND_BASELINE:
        raise RuntimeError('Native foreground source changed: ' + path)
    original = raw.decode('utf-8').replace('\r\n', '\n')
    lines = original.splitlines(True)
    cls = next(n for n in ast.parse(original).body if isinstance(n, ast.ClassDef) and n.name == 'LocalEnvironment')
    fn = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == '_run_bash')
    body = ''.join(lines[fn.lineno - 1:fn.end_lineno])
    if body.count('proc = subprocess.Popen(') != 1:
        raise RuntimeError('Unexpected native foreground launch shape')
    body = body.replace('proc = subprocess.Popen(', 'proc = scoped_popen(')
    method = body.splitlines(True)
    method.insert(fn.body[0].lineno - fn.lineno,
                  '        from tools.mesh_writer_scope import scoped_popen\n')
    lines[fn.lineno - 1:fn.end_lineno] = [''.join(method)]
    candidate = ''.join(lines)
    ast.parse(candidate)
    return {path: original}, {path: candidate}


def tool_worker_candidates(native_root):
    originals, changed = {}, {}
    replacements = {
        'agent/tool_executor.py': [
            ('        future = executor.submit(propagate_context_to_thread(_run))',
             '        from tools.mesh_writer_scope import submit_writer_work\n'
             '        future = submit_writer_work(executor, _run, propagate_context_to_thread)'),
            ('                f = executor.submit(propagate_context_to_thread(self.run_worker), i, submit_index)',
             '                from tools.mesh_writer_scope import submit_writer_work\n'
             '                f = submit_writer_work(executor, self.run_worker, propagate_context_to_thread, i, submit_index)')],
        'agent/terminal_approval_batch.py': [
            ('            slot.future = self.executor.submit(propagate_context_to_thread(slot.run))',
             '            from tools.mesh_writer_scope import submit_writer_work\n'
             '            slot.future = submit_writer_work(self.executor, slot.run, propagate_context_to_thread)')]}
    for path, expected in TOOL_WORKER_BASELINES.items():
        raw = (native_root / path).read_bytes()
        if hashlib.sha256(raw).hexdigest() != expected:
            raise RuntimeError('Native tool-worker source changed: ' + path)
        original = raw.decode('utf-8').replace('\r\n', '\n')
        candidate = original
        for before, after in replacements[path]:
            if candidate.count(before) != 1:
                raise RuntimeError('Unexpected native tool-worker submission shape: ' + path)
            candidate = candidate.replace(before, after)
        if path == 'agent/tool_executor.py':
            lines = candidate.splitlines(True)
            fn = next(n for n in ast.parse(candidate).body if isinstance(n, ast.FunctionDef)
                      and n.name == '_run_agent_tool_execution_middleware')
            split = fn.body[0].end_lineno
            body = lines[split:fn.end_lineno]
            lines[split:fn.end_lineno] = [
                '    from tools.mesh_writer_scope import writer_tool_effect\n',
                '    with writer_tool_effect():\n',
                *['    ' + line if line.strip() else line for line in body]]
            candidate = ''.join(lines)
        ast.parse(candidate)
        originals[path], changed[path] = original, candidate
    return originals, changed


def file_tool_candidate(native_root):
    path = 'tools/file_tools.py'
    raw = (native_root / path).read_bytes()
    if hashlib.sha256(raw).hexdigest() != FILE_TOOLS_BASELINE:
        raise RuntimeError('Native file-tool source changed')
    original = raw.decode('utf-8').replace('\r\n', '\n')
    candidate = original
    replacements = [
        ('    env_type = config["env_type"]\n',
         '    env_type = config["env_type"]\n'
         '    from tools.mesh_writer_scope import require_supported_writer_route\n'
         '    require_supported_writer_route(local=env_type == "local")\n'),
        ('                return cached\n',
         '                from tools.mesh_writer_scope import require_writer_local_environment\n'
         '                require_writer_local_environment(cached.env, _active_environments[task_id])\n'
         '                return cached\n'),
        ('    file_ops = ShellFileOperations(terminal_env)\n',
         '    from tools.mesh_writer_scope import require_writer_local_environment\n'
         '    require_writer_local_environment(terminal_env)\n'
         '    file_ops = ShellFileOperations(terminal_env)\n')]
    for before, after in replacements:
        if candidate.count(before) != 1:
            raise RuntimeError('Unexpected file-tool backend selection shape')
        candidate = candidate.replace(before, after)
    ast.parse(candidate)
    return {path: original}, {path: candidate}


def terminal_route_candidate(native_root):
    path = 'tools/terminal_tool.py'
    raw = (native_root / path).read_bytes()
    if hashlib.sha256(raw).hexdigest() != TERMINAL_TOOL_BASELINE:
        raise RuntimeError('Native terminal-tool source changed')
    original = raw.decode('utf-8').replace('\r\n', '\n')
    lines = original.splitlines(True)
    fn = next(n for n in ast.parse(original).body if isinstance(n, ast.FunctionDef) and n.name == '_run_foreground')
    lines[fn.body[0].end_lineno:fn.body[0].end_lineno] = [
        '    from tools.mesh_writer_scope import require_supported_writer_route, require_writer_local_environment\n',
        '    require_supported_writer_route(local=plan.env_type == "local")\n',
        '    require_writer_local_environment(env)\n']
    candidate = ''.join(lines)
    before = '    env_type = "local" if _host_local else config["env_type"]\n'
    if candidate.count(before) != 1:
        raise RuntimeError('Unexpected pre-creation terminal plan shape')
    candidate = candidate.replace(before, before
        + '    from tools.mesh_writer_scope import require_supported_writer_route\n'
        + '    require_supported_writer_route(local=env_type == "local")\n')
    ast.parse(candidate)
    return {path: original}, {path: candidate}


def title_candidate(native_root):
    path = 'agent/title_generator.py'
    raw = (native_root / path).read_bytes()
    if hashlib.sha256(raw).hexdigest() != TITLE_BASELINE:
        raise RuntimeError('Native title source changed')
    original = raw.decode('utf-8').replace('\r\n', '\n')
    fn = next(n for n in ast.parse(original).body if isinstance(n, ast.FunctionDef) and n.name == 'start_title_upgrade')
    lines = original.splitlines(True)
    body = ''.join(lines[fn.lineno - 1:fn.end_lineno])
    if body.count('    upgrade.start()') != 1:
        raise RuntimeError('Unexpected native title-thread launch shape')
    body = body.replace('    upgrade.start()',
        '    from tools.mesh_writer_scope import start_writer_observed_thread\n'
        '    start_writer_observed_thread(upgrade)')
    lines[fn.lineno - 1:fn.end_lineno] = [body]
    candidate = ''.join(lines)
    ast.parse(candidate)
    return {path: original}, {path: candidate}


def canonical_worker_candidate(native_root):
    path = 'gateway/run_turn_runner.py'
    raw = (native_root / path).read_bytes()
    if hashlib.sha256(raw).hexdigest() != CANONICAL_WORKER_BASELINE:
        raise RuntimeError('Native canonical worker source changed')
    original = raw.decode('utf-8').replace('\r\n', '\n')
    tree = ast.parse(original)
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'TurnRunner')
    fn = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == 'run_sync')
    lines = original.splitlines(True)
    body = lines[fn.body[0].lineno - 1:fn.end_lineno]
    lines[fn.body[0].lineno - 1:fn.end_lineno] = [
        '        from tools.mesh_writer_scope import canonical_writer_foreground_scope\n',
        '        with canonical_writer_foreground_scope():\n',
        *['    ' + line if line.strip() else line for line in body]]
    candidate = ''.join(lines)
    ast.parse(candidate)
    return {path: original}, {path: candidate}


def canonical_ingress_candidate(native_root):
    path = 'gateway/session_ingress.py'
    raw = (native_root / path).read_bytes()
    if hashlib.sha256(raw).hexdigest() != CANONICAL_INGRESS_BASELINE:
        raise RuntimeError('Native canonical ingress source changed')
    original = raw.decode('utf-8').replace('\r\n', '\n')
    before = '            response = await authority.runner._handle_message(event)\n'
    if original.count(before) != 1:
        raise RuntimeError('Unexpected canonical ingress worker shape')
    candidate = original.replace(before,
        '            from tools.mesh_writer_scope import canonical_admission_writer_scope\n'
        "            with canonical_admission_writer_scope(authority, ref, row, prepared['adapter'] if is_api else None):\n"
        '                response = await authority.runner._handle_message(event)\n')
    ast.parse(candidate)
    return {path: original}, {path: candidate}


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
    lifetime_originals, lifetime_modules = lifetime_candidates(source_path.parent.parent)
    modules.update(lifetime_modules)
    foreground_originals, foreground_modules = foreground_candidate(source_path.parent.parent)
    lifetime_originals.update(foreground_originals)
    modules.update(foreground_modules)
    tool_originals, tool_modules = tool_worker_candidates(source_path.parent.parent)
    lifetime_originals.update(tool_originals)
    modules.update(tool_modules)
    file_originals, file_modules = file_tool_candidate(source_path.parent.parent)
    lifetime_originals.update(file_originals)
    modules.update(file_modules)
    terminal_originals, terminal_modules = terminal_route_candidate(source_path.parent.parent)
    lifetime_originals.update(terminal_originals)
    modules.update(terminal_modules)
    title_originals, title_modules = title_candidate(source_path.parent.parent)
    lifetime_originals.update(title_originals)
    modules.update(title_modules)
    canonical_originals, canonical_modules = canonical_worker_candidate(source_path.parent.parent)
    lifetime_originals.update(canonical_originals)
    modules.update(canonical_modules)
    ingress_originals, ingress_modules = canonical_ingress_candidate(source_path.parent.parent)
    lifetime_originals.update(ingress_originals)
    modules.update(ingress_modules)
    patch_text = ''.join(difflib.unified_diff(original.splitlines(True), candidate.splitlines(True),
                                           fromfile='a/tools/process_registry.py', tofile='b/tools/process_registry.py'))
    for path, text in modules.items():
        (out / path).parent.mkdir(parents=True, exist_ok=True)
        (out / path).write_bytes(text.encode('utf-8'))
        if path in lifetime_originals:
            patch_text += ''.join(difflib.unified_diff(lifetime_originals[path].splitlines(True), text.splitlines(True),
                                                      fromfile='a/' + path, tofile='b/' + path))
        elif path != 'tools/process_registry.py':
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


def qualify_lifetimes(modules):
    """Execute pinned native functions with fixture profiles/ledgers; no model or live DB."""
    def extract(path, names, namespace):
        nodes = [n for n in ast.parse(modules[path]).body if isinstance(n, ast.FunctionDef) and n.name in names]
        if {n.name for n in nodes} != set(names):
            raise RuntimeError('Native qualification functions missing')
        exec(compile(ast.Module(body=nodes, type_ignores=[]), '<pinned-native-lifetime-fixture>', 'exec'), namespace)
        return namespace
    tools = types.ModuleType('tools'); tools.__path__ = []
    acquire_count = [0]
    retirement = types.SimpleNamespace(acquire=lambda: acquire_count.__setitem__(0, acquire_count[0] + 1),
                                       release=lambda: acquire_count.__setitem__(0, acquire_count[0] - 1))
    retirement_module = types.ModuleType('hermes_cli.backend_retirement'); retirement_module.retirement = retirement
    def propagated(fn):
        context = copy_context()
        return lambda: context.run(fn)
    aliases = {'tools': tools, 'tools.mesh_writer_scope': scope,
               'hermes_cli.backend_retirement': retirement_module}
    checks = []
    with ThreadPoolExecutor(max_workers=2) as pool:
        namespace = {'Any': typing.Any, 'Optional': typing.Optional, 'Callable': typing.Callable,
                     'contextvars': __import__('contextvars'),
                     'time': time, '_records': {}, '_records_lock': threading.RLock(),
                     '_ACTIVE_STATES': ('running', 'stalling'), '_LIVE_STATES': ('running', 'stalling', 'finalizing'),
                     'worker_ledger': lambda: None, '_persist_dispatch': lambda _: None,
                     '_capture_routing_origin': lambda: {}, '_get_executor': lambda _: pool,
                     'propagate_context_to_thread': propagated, '_prune_completed_locked': lambda: None,
                     '_push_completion_event': lambda *args: None,
                     '_single_crash': lambda *args: {'status': 'error'}}
        extract('tools/async_delegation.py', ['_dispatch_admitted', '_finalize'], namespace)
        fence = WindowsWriterFence('native-delegate-fixture', 'one'); lifetime = scope.WriterLifetime(fence)
        started, release = threading.Event(), threading.Event()
        def runner():
            started.set(); release.wait(timeout=5)
            return {'status': 'completed'}
        try:
            with patch.dict(sys.modules, aliases):
                with scope.writer_foreground_scope(lifetime):
                    handle = namespace['_dispatch_admitted'](
                        delegation_id='native-child-fixture', goal='fixture', goals=None, context=None,
                        toolsets=None, role='fixture', model=None, session_key='fixture', parent_session_id=None,
                        runner=runner, origin_ui_session_id='', origin_session_id='', interrupt_fn=None,
                        max_async_children=2, progress_fn=None, capacity_error='fixture capacity')
                    if handle['status'] != 'dispatched' or not started.wait(timeout=3):
                        raise AssertionError('Native delegate did not start')
                    namespace['_finalize']('native-child-fixture', {'status': 'completed'}, 'completed')
                if lifetime.wait(20)['managedWorkEnded']:
                    raise AssertionError('Forced terminal delivery released a running native delegate')
                checks.append('native_forced_finalization_does_not_release_running_future')
                release.set()
                if not lifetime.wait()['managedWorkEnded'] or lifetime.snapshot()['writerQuiescence']:
                    raise AssertionError('Native delegate lifecycle failed to settle conservatively')
                checks.append('native_future_completion_settles_exact_attempt_only')
        finally:
            release.set(); pool.shutdown(wait=True); fence.terminate(); fence.close()
        if acquire_count[0] != 0:
            raise AssertionError('Native retirement reservation did not balance')
        checks.append('native_retirement_accounting_preserved')

    gateway_context = types.ModuleType('gateway.session_context'); gateway_context.clear_session_vars = lambda _: None
    policy = types.ModuleType('gateway.hosted_room_execution_policy')
    policy.RoomExecutionPolicy = object; policy.bind_room_execution_policy = lambda _: None; policy.reset_room_execution_policy = lambda _: None
    approval = types.ModuleType('tools.approval'); approval.register_gateway_notify = lambda *a: None; approval.unregister_gateway_notify = lambda *a: None
    approval_context = types.ModuleType('tools.approval_context'); approval_context.set_current_session_key = lambda _: None; approval_context.reset_current_session_key = lambda _: None
    aliases.update({'gateway.session_context': gateway_context, 'gateway.hosted_room_execution_policy': policy,
                    'tools.approval': approval, 'tools.approval_context': approval_context})
    fence = WindowsWriterFence('native-api-fixture', 'generation-one'); lifetime = scope.WriterLifetime(fence)
    observed = []
    def conversation(**kwargs):
        lifetime.assert_current_worker()
        with scope.scoped_popen([sys.executable, '-c', 'print("native API worker output")'], text=True) as proc:
            output, _ = proc.communicate(timeout=5)
        observed.append(output.strip())
        return {'output': output.strip()}
    host = types.SimpleNamespace(_profile_scope=lambda _: nullcontext(), _bind_api_server_session=lambda **kw: None,
                                _memory_sessions=types.SimpleNamespace(checkin=lambda _: lifetime.assert_current_worker()))
    run = types.SimpleNamespace(run_id='native-api-fixture', session_id='fixture', request_profile=None,
                                approval_session_key='fixture', browser_control_principal=None,
                                browser_control_transport_family=None, agent_kwargs={'room_dispatch': None},
                                session_history_delivery=False, declared_selected=False, turn_author=None,
                                user_message='fixture', conversation_history=[], writer_lifetime=lifetime,
                                writer_generation='generation-one')
    api = types.SimpleNamespace(_publish_turn_process_ownership=lambda *a: None, _clear_turn_process_ownership=lambda *a: None)
    namespace = {'Any': typing.Any, '_RunLaunch': object, 'suppress': suppress,
                 '_API_WORKER_LOCK': threading.Lock(), '_API_WORKER_LIVE': 0,
                 '_run_usage': lambda _: {}, '_served_runtime': lambda _: {}}
    extract('gateway/platforms/api_server_runs.py', ['_run_agent_sync', '_submit_api_worker'], namespace)
    try:
        with patch.dict(sys.modules, aliases):
            namespace['_run_agent_sync'](host, run, types.SimpleNamespace(run_conversation=conversation), None, _api_server=api)
        if observed != ['native API worker output'] or not lifetime.wait()['managedWorkEnded']:
            raise AssertionError('Native foreground lifetime did not encompass the whole callable')
        checks.append('native_api_callable_and_cleanup_bound_to_exact_lifetime')
        run.writer_generation = 'wrong-generation'
        with patch.dict(sys.modules, aliases):
            try:
                namespace['_run_agent_sync'](host, run, types.SimpleNamespace(run_conversation=conversation), None, _api_server=api)
            except RuntimeError:
                checks.append('native_api_wrong_generation_refused_before_agent')
            else:
                raise AssertionError('Wrong native API generation was allowed')
    finally:
        fence.terminate(); fence.close()

    async def cancel_handler_fixture():
        fence = WindowsWriterFence('native-api-cancel-fixture', 'generation-two')
        lifetime = scope.WriterLifetime(fence)
        started, release = threading.Event(), threading.Event()
        def conversation(**kwargs):
            lifetime.assert_current_worker(); started.set(); release.wait(timeout=5)
            return {'output': 'cancel fixture returned'}
        cancel_run = types.SimpleNamespace(**vars(run))
        cancel_run.run_id, cancel_run.writer_generation = fence.run_id, fence.generation
        cancel_run.writer_lifetime = lifetime
        cancel_host = types.SimpleNamespace(**vars(host))
        cancel_host._memory_sessions = types.SimpleNamespace(checkin=lambda _: lifetime.assert_current_worker())
        try:
            with patch.dict(sys.modules, aliases):
                future = namespace['_submit_api_worker'](asyncio.get_running_loop(), lambda:
                    namespace['_run_agent_sync'](cancel_host, cancel_run,
                        types.SimpleNamespace(run_conversation=conversation), None, _api_server=api))
                deadline = time.monotonic() + 3
                while not started.is_set() and time.monotonic() < deadline:
                    await asyncio.sleep(.01)
                if not started.is_set():
                    raise AssertionError('Native API worker never entered')
                future.cancel()
                try:
                    await future
                except asyncio.CancelledError:
                    pass
                if lifetime.snapshot()['rootEnded'] or namespace['_API_WORKER_LIVE'] != 1:
                    raise AssertionError('Handler cancellation released a running native API worker')
                release.set()
                deadline = time.monotonic() + 3
                while namespace['_API_WORKER_LIVE'] and time.monotonic() < deadline:
                    await asyncio.sleep(.01)
                if namespace['_API_WORKER_LIVE'] or not lifetime.wait()['managedWorkEnded']:
                    raise AssertionError('Native API worker did not settle after actual return')
                checks.append('native_handler_cancel_waits_for_actual_worker_return')
        finally:
            release.set(); fence.terminate(); fence.close()
    asyncio.run(cancel_handler_fixture())
    return checks


def qualify_foreground(modules):
    """Actual native launcher body, fixture shell selection, real Windows IO/tree."""
    cls = next(n for n in ast.parse(modules['tools/environments/local.py']).body
               if isinstance(n, ast.ClassDef) and n.name == 'LocalEnvironment')
    fn = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == '_run_bash')
    def pipe_stdin(proc, text):
        proc.stdin.write(text)
        proc.stdin.close()
        proc.stdin = None
    namespace = {'subprocess': subprocess, '_IS_WINDOWS': True,
                 '_find_bash': lambda: sys.executable, '_make_run_env': lambda env: env,
                 'windows_hide_flags': lambda: 0x08000000, '_pipe_stdin': pipe_stdin}
    exec(compile(ast.Module(body=[fn], type_ignores=[]), '<pinned-native-foreground-fixture>', 'exec'), namespace)
    fixture = types.SimpleNamespace(env=dict(__import__('os').environ), cwd=str(Path.cwd()), _recover_cwd=lambda: None)
    tools = types.ModuleType('tools'); tools.__path__ = []
    checks = []
    with patch.dict(sys.modules, {'tools': tools, 'tools.mesh_writer_scope': scope}):
        # Unbound legacy execution must remain usable without an enrolled lifetime.
        with namespace['_run_bash'](fixture, 'print("legacy foreground")') as proc:
            output, _ = proc.communicate(timeout=5)
        if output.strip() != 'legacy foreground':
            raise AssertionError('Legacy foreground IO changed')
        checks.append('native_foreground_legacy_output')
        fence = WindowsWriterFence('native-foreground-fixture', 'one')
        lifetime = scope.WriterLifetime(fence)
        try:
            with scope.writer_foreground_scope(lifetime):
                with namespace['_run_bash'](fixture, 'import sys; print(sys.stdin.read().upper())', stdin_data='fenced input') as proc:
                    output, _ = proc.communicate(timeout=5)
                if output.strip() != 'FENCED INPUT':
                    raise AssertionError('Fenced foreground stdin/output mismatch')
                checks.append('native_foreground_fenced_stdin_output')
                child = 'import time; time.sleep(1.5)'
                command = ('import subprocess,sys; subprocess.Popen([sys.executable,"-c",'
                           + repr(child) + '], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL); print("root returned")')
                with namespace['_run_bash'](fixture, command) as proc:
                    output, _ = proc.communicate(timeout=5)
                if output.strip() != 'root returned':
                    raise AssertionError('Foreground root output mismatch')
            if lifetime.wait(20)['managedWorkEnded']:
                raise AssertionError('Foreground root return released its live child')
            checks.append('native_foreground_child_holds_after_root_return')
            snapshot = lifetime.wait(5000)
            if not snapshot['managedWorkEnded'] or snapshot['writerQuiescence']:
                raise AssertionError('Foreground tree settlement or release boundary invalid')
            checks.append('native_foreground_actual_tree_completion_without_release_grant')
        finally:
            fence.terminate(); fence.close()
        bash = Path('C:/Program Files/Git/bin/bash.exe')
        if not bash.is_file():
            raise RuntimeError('Git Bash unavailable for foreground shell qualification')
        namespace['_find_bash'] = lambda: str(bash)
        fence = WindowsWriterFence('native-git-bash-fixture', 'one')
        try:
            with scope.bind_writer_fence(fence):
                with namespace['_run_bash'](fixture, 'read -r line; printf "shell:%s\\n" "$line"; exit 7',
                                            stdin_data='pipe input\n') as proc:
                    output, _ = proc.communicate(timeout=5)
                if output.strip() != 'shell:pipe input' or proc.returncode != 7:
                    raise AssertionError('Git Bash stdin/output/exit status changed')
            fence.seal()
            if not fence.wait(5000)['processTreeEnded']:
                raise AssertionError('Git Bash tree did not settle')
            checks.append('native_foreground_real_git_bash_stdin_output_exit_status')
        finally:
            fence.terminate(); fence.close()
    return checks


def qualify_enrollment(modules):
    """Execute the actual direct-branch enrollment prefix, not an entire API request."""
    tree = ast.parse(modules['gateway/platforms/api_server_runs.py'])
    execute = next(n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name == '_execute_run')
    branch = next(n for n in ast.walk(execute) if isinstance(n, ast.If)
                  and ast.unparse(n.test) == 'run.admission is not None')
    if (not isinstance(branch.orelse[0], ast.ImportFrom)
            or branch.orelse[0].module != 'tools.mesh_writer_scope'
            or not isinstance(branch.orelse[2], ast.With)
            or 'self._create_agent(' not in ast.unparse(branch.orelse[2])
            or 'enroll_direct_writer_run' in ast.unparse(ast.Module(body=branch.body, type_ignores=[]))):
        raise AssertionError('Enrollment must precede direct agent creation and avoid canonical-owner claims')
    prefix = compile(ast.Module(body=branch.orelse[:2], type_ignores=[]), '<native-direct-enrollment-prefix>', 'exec')
    registry = scope.WriterRunRegistry(WindowsWriterFence)
    run = types.SimpleNamespace(run_id='run_' + uuid.uuid4().hex, admission=None,
                                writer_lifetime=None, writer_generation='')
    host = types.SimpleNamespace(_mesh_writer_runs=registry)
    tools = types.ModuleType('tools'); tools.__path__ = []
    checks = []
    try:
        with patch.dict(sys.modules, {'tools': tools, 'tools.mesh_writer_scope': scope}):
            exec(prefix, {'self': host, 'run': run})
            lifetime = run.writer_lifetime
            with scope.writer_foreground_scope(lifetime, expected_run_id=run.run_id,
                                                expected_generation=run.writer_generation):
                with scope.scoped_popen([sys.executable, '-c', 'print("enrolled run")'],
                                        stdout=subprocess.PIPE, text=True) as proc:
                    output, _ = proc.communicate(timeout=5)
                if output.strip() != 'enrolled run':
                    raise AssertionError('Enrolled native run lost command output')
            if not lifetime.wait()['managedWorkEnded']:
                raise AssertionError('Actual enrolled run did not settle')
            checks.append('native_direct_enrollment_prefix_real_process_lifetime')
            try:
                exec(prefix, {'self': host, 'run': run})
            except RuntimeError:
                checks.append('native_direct_duplicate_enrollment_refused_before_agent_creation')
            else:
                raise AssertionError('Duplicate native admission was accepted')
            snapshot = registry.snapshot(run.run_id)
            if snapshot['writerQuiescence'] or snapshot['state'] != 'enrolled':
                raise AssertionError('Finished delivery removed enrollment or granted release')
            checks.append('native_completed_enrollment_retained_without_release_authority')
    finally:
        if run.writer_lifetime is not None:
            run.writer_lifetime.fence.terminate(); run.writer_lifetime.fence.close()
    return checks


def qualify_tool_worker_submissions(modules):
    """Actual three patched submission statements, real threads/processes, fixture bodies."""
    statements = []
    for path in TOOL_WORKER_BASELINES:
        for node in ast.walk(ast.parse(modules[path])):
            if (isinstance(node, ast.Assign) and isinstance(node.value, ast.Call)
                    and isinstance(node.value.func, ast.Name) and node.value.func.id == 'submit_writer_work'):
                statements.append((path, node))
    if len(statements) != 3:
        raise AssertionError('Expected sequential/concurrent/prepared tool submissions')
    checks = []
    tools = types.ModuleType('tools'); tools.__path__ = []
    for index, (path, statement) in enumerate(statements):
        fence = WindowsWriterFence('native-tool-worker-' + str(index), 'one')
        lifetime = scope.WriterLifetime(fence)
        entered, release = threading.Event(), threading.Event()
        outputs, arguments = [], []
        def worker(*args, **kwargs):
            lifetime.assert_current_worker()
            arguments.append((args, kwargs))
            entered.set()
            if not release.wait(timeout=5):
                raise RuntimeError('Tool fixture release timed out')
            with scope.scoped_popen([sys.executable, '-c', 'print("tool still owned")'],
                                    stdout=subprocess.PIPE, text=True) as proc:
                output, _ = proc.communicate(timeout=5)
            outputs.append(output.strip())
        with ThreadPoolExecutor(max_workers=1) as executor:
            try:
                slot = types.SimpleNamespace(run=worker)
                namespace = {'submit_writer_work': scope.submit_writer_work, 'executor': executor,
                             'self': types.SimpleNamespace(executor=executor, run_worker=worker),
                             'slot': slot, '_run': worker, 'i': 7, 'submit_index': 2}
                # The native propagator supports positional arguments, as does copy_context.run.
                def propagate(fn):
                    context = copy_context()
                    return lambda *args, **kwargs: context.run(fn, *args, **kwargs)
                namespace['propagate_context_to_thread'] = propagate
                code = compile(ast.Module(body=[statement], type_ignores=[]), '<native-tool-submission>', 'exec')
                with scope.writer_foreground_scope(lifetime):
                    exec(code, namespace)
                    future = getattr(slot, 'future', None) or namespace.get('future') or namespace.get('f')
                    if not entered.wait(timeout=3):
                        raise AssertionError('Native tool worker did not start')
                if future.cancel() or lifetime.wait(20)['managedWorkEnded']:
                    raise AssertionError('Abandoned tool future released its still-running callable')
                release.set(); future.result(timeout=5)
                if outputs != ['tool still owned'] or not lifetime.wait()['managedWorkEnded']:
                    raise AssertionError('Native tool worker lost owned context after parent return')
                expected_args = (7, 2) if ast.unparse(statement.targets[0]) == 'f' else ()
                if arguments != [(expected_args, {})]:
                    raise AssertionError('Native tool positional arguments changed')
                checks.append('native_' + ('prepared' if 'approval_batch' in path else
                              'concurrent' if expected_args else 'sequential') + '_tool_future_holds_actual_callable')
            finally:
                release.set()
                fence.terminate(); fence.close()
    return checks


def qualify_tool_effect_boundary(modules):
    """Full patched middleware function, fixture hooks; no live Relay/external calls."""
    tree = ast.parse(modules['agent/tool_executor.py'])
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef)
              and n.name == '_run_agent_tool_execution_middleware')
    namespace = {'Any': typing.Any, '_ManagedToolResult': types.SimpleNamespace,
                 '_ConcurrentToolAuthorizationGate': object, 'threading': threading,
                 '_ToolCallRef': lambda name, args, *rest: types.SimpleNamespace(name=name, args=args),
                 'tool_hook_ids': lambda *args: {}}
    namespace['_dispatch_authorized_once'] = lambda agent, state, ref, **kw: kw['execute'](ref.args)
    exec(compile(ast.Module(body=[fn], type_ignores=[]), '<native-tool-effect-boundary>', 'exec'), namespace)
    fence = WindowsWriterFence('native-tool-effect-fixture', 'one')
    lifetime, stages = scope.WriterLifetime(fence), []
    def observe(stage):
        if lifetime.snapshot()['toolEffects']['activeCalls'] != 1:
            raise AssertionError('Tool effects were not reserved before ' + stage)
        stages.append(stage)
    def relay_execute(name, args, pipeline, **kwargs):
        observe('relay'); return pipeline(args), args
    def request_middleware(name, args, **kwargs):
        observe('request_middleware'); return types.SimpleNamespace(payload=args, trace=[])
    def execution_middleware(name, args, dispatch, **kwargs):
        observe('execution_middleware'); return dispatch(args)
    def handler(args):
        observe('handler'); return 'fixture response'
    tools = types.ModuleType('tools'); tools.__path__ = []
    agent_module = types.ModuleType('agent'); agent_module.__path__ = []
    agent_module.relay_tools = types.SimpleNamespace(execute=relay_execute)
    cli = types.ModuleType('hermes_cli'); cli.__path__ = []
    middleware = types.ModuleType('hermes_cli.middleware')
    middleware.apply_tool_request_middleware = request_middleware
    middleware.run_tool_execution_middleware = execution_middleware
    prepared = types.ModuleType('agent.terminal_approval_batch'); prepared.bind_prepared_dispatch = lambda fn: fn
    aliases = {'tools': tools, 'tools.mesh_writer_scope': scope, 'agent': agent_module,
               'hermes_cli': cli, 'hermes_cli.middleware': middleware,
               'agent.terminal_approval_batch': prepared}
    checks = []
    try:
        with patch.dict(sys.modules, aliases), scope.writer_foreground_scope(lifetime):
            result = namespace[fn.name](types.SimpleNamespace(session_id='fixture'), function_name='fixture_tool',
                        function_args={}, effective_task_id='fixture', tool_call_id='fixture', execute=handler)
            if result.result != 'fixture response' or stages != ['relay', 'request_middleware', 'execution_middleware', 'handler']:
                raise AssertionError('Native middleware order/output changed')
            checks.append('native_tool_effect_reserved_before_all_middleware_and_handler')
            def fail(*args, **kwargs):
                observe('relay_error'); raise ValueError('uncertain external outcome')
            agent_module.relay_tools.execute = fail
            try:
                namespace[fn.name](types.SimpleNamespace(session_id='fixture'), function_name='fixture_tool',
                    function_args={}, effective_task_id='fixture', tool_call_id='second', execute=handler)
            except ValueError:
                checks.append('native_middleware_failure_retains_unverified_effect')
            else:
                raise AssertionError('Native middleware error was swallowed')
        snapshot = lifetime.wait()
        effects = snapshot['toolEffects']
        if (not snapshot['managedWorkEnded'] or effects['activeCalls'] or effects['unverifiedCalls'] != 2
                or effects['effectsSettled'] or snapshot['writerQuiescence']):
            raise AssertionError('Returned middleware manufactured settled external effects')
        checks.append('native_returned_tool_responses_cannot_settle_external_effects')
    finally:
        fence.terminate(); fence.close()
    return checks


def qualify_file_tool_routes(modules):
    """Actual file-backend selection functions with fixture environments/cache only."""
    tree = ast.parse(modules['tools/file_tools.py'])
    functions = [n for n in tree.body if isinstance(n, ast.FunctionDef)
                 and n.name in ('_create_terminal_env_for_file_ops', '_get_file_ops')]
    class LocalEnvironment:
        cwd = str(Path.cwd())
    class RemoteEnvironment:
        cwd = '/fixture'
        is_local = True  # A plugin flag cannot impersonate the native local type.
    constructors, created = [], []
    class FileOperations:
        def __init__(self, env):
            constructors.append(env); self.env, self.cwd = env, env.cwd
    config = {'env_type': 'local', 'cwd': str(Path.cwd()), 'timeout': 5}
    active, cache, activity = {}, {}, {}
    terminal = types.ModuleType('tools.terminal_tool')
    terminal._active_environments, terminal._last_activity = active, activity
    terminal._env_lock = threading.RLock()
    terminal._creation_locks, terminal._creation_locks_lock = {}, threading.RLock()
    terminal._resolve_container_task_id = lambda task: task
    terminal.get_session_cwd = lambda task: None
    terminal.record_session_cwd = lambda *args: None
    terminal._start_cleanup_thread = lambda: None
    terminal._get_env_config = lambda: dict(config)
    terminal.resolve_task_overrides = lambda task: {}
    terminal._resolve_task_host_cwd = lambda *args: None
    terminal._select_image = lambda *args: ''
    terminal._is_mounted_host_cwd = terminal._is_unusable_container_cwd = lambda *args, **kw: False
    def create(config, env_type, **kwargs):
        env = LocalEnvironment() if env_type == 'local' else RemoteEnvironment()
        created.append(env); return env
    terminal._create_configured_env = create
    configuration = types.ModuleType('tools.terminal_tool_config')
    configuration._is_container_backend = lambda name: False
    configuration.coerce_ssh_remote_cwd = lambda cwd, name: cwd
    local_module = types.ModuleType('tools.environments.local'); local_module.LocalEnvironment = LocalEnvironment
    tools = types.ModuleType('tools'); tools.__path__ = []
    environments = types.ModuleType('tools.environments'); environments.__path__ = []
    aliases = {'tools': tools, 'tools.mesh_writer_scope': scope, 'tools.terminal_tool': terminal,
               'tools.terminal_tool_config': configuration, 'tools.environments': environments,
               'tools.environments.local': local_module}
    namespace = {'ShellFileOperations': FileOperations, '_file_ops_lock': threading.RLock(),
                 '_file_ops_cache': cache, 'threading': threading, 'time': time,
                 'logger': types.SimpleNamespace(info=lambda *args: None)}
    exec(compile(ast.Module(body=functions, type_ignores=[]), '<native-file-route-fixture>', 'exec'), namespace)
    get = namespace['_get_file_ops']
    fence = WindowsWriterFence('native-file-route-fixture', 'one')
    checks = []
    try:
        with patch.dict(sys.modules, aliases):
            with scope.bind_writer_fence(fence):
                config['env_type'] = 'ssh'
                try:
                    get('remote-new')
                except RuntimeError:
                    if created or constructors:
                        raise AssertionError('Remote environment started before rejection')
                    checks.append('native_file_remote_creation_refused_before_factory')
                else:
                    raise AssertionError('Remote file environment created')
                config['env_type'] = 'local'
                first = get('local')
                if type(first.env) is not LocalEnvironment or len(created) != 1:
                    raise AssertionError('Native local file backend changed')
                checks.append('native_file_local_creation_preserved')
                if get('local') is not first or len(created) != 1:
                    raise AssertionError('Local cache reuse changed')
                checks.append('native_file_matching_local_cache_preserved')
                for label, cached_env, active_env in [
                    ('remote_cache', RemoteEnvironment(), LocalEnvironment()),
                    ('replaced_cache', LocalEnvironment(), LocalEnvironment()),
                    ('missing_active_identity', LocalEnvironment(), None)]:
                    cache[label] = types.SimpleNamespace(env=cached_env)
                    active[label] = active_env
                    try:
                        get(label)
                    except RuntimeError:
                        checks.append('native_file_' + label + '_refused')
                    else:
                        raise AssertionError('Invalid cached file backend returned')
                active['existing-remote'] = RemoteEnvironment()
                count = len(constructors)
                try:
                    get('existing-remote')
                except RuntimeError:
                    if len(constructors) != count:
                        raise AssertionError('Remote file adapter constructed before refusal')
                    checks.append('native_file_existing_remote_refused_before_adapter')
                else:
                    raise AssertionError('Existing remote backend was accepted')
            config['env_type'] = 'ssh'
            if type(get('legacy-remote').env) is not RemoteEnvironment:
                raise AssertionError('Unenrolled remote file behavior changed')
            checks.append('native_file_legacy_unenrolled_remote_preserved')
    finally:
        fence.terminate(); fence.close()
    return checks


def qualify_terminal_routes(modules):
    """Actual foreground function with fixture routing helpers and real local IO."""
    fn = next(n for n in ast.parse(modules['tools/terminal_tool.py']).body
              if isinstance(n, ast.FunctionDef) and n.name == '_run_foreground')
    calls = []
    class LocalEnvironment:
        def execute(self, command, **kwargs):
            calls.append('local')
            with scope.scoped_popen([sys.executable, '-c', 'print("foreground route output")'],
                                    stdout=subprocess.PIPE, text=True) as proc:
                output, _ = proc.communicate(timeout=5)
            return {'output': output.strip(), 'exit_code': proc.returncode}
    class RemoteEnvironment:
        is_local = True
        def execute(self, command, **kwargs):
            calls.append('remote'); return {'output': 'legacy remote fixture', 'exit_code': 0}
    namespace = {'Any': typing.Any, 'Optional': typing.Optional, '_ExecPlan': types.SimpleNamespace,
                 '_resolve_command_cwd': lambda **kwargs: str(Path.cwd()), '_yield_kwargs': lambda *a, **kw: {},
                 'finalize_foreground_result': lambda **kwargs: json.dumps(kwargs['result']), 'json': json,
                 'time': time, 'logger': types.SimpleNamespace(warning=lambda *a: None, error=lambda *a: None)}
    exec(compile(ast.Module(body=[fn], type_ignores=[]), '<native-foreground-route-fixture>', 'exec'), namespace)
    plan_fn = next(n for n in ast.parse(modules['tools/terminal_tool.py']).body
                   if isinstance(n, ast.FunctionDef) and n.name == '_plan_execution')
    config = {'env_type': 'local', 'cwd': str(Path.cwd()), 'timeout': 5}
    namespace.update(_get_env_config=lambda: dict(config), _resolve_container_task_id=lambda value: value,
        resolve_task_overrides=lambda task: {}, _select_image=lambda *args: '',
        coerce_ssh_remote_cwd=lambda cwd, env: cwd, get_session_cwd=lambda task: None,
        _resolve_task_host_cwd=lambda *args: None, _is_container_backend=lambda env: False,
        _foreground_background_guidance=lambda command: None, FOREGROUND_MAX_TIMEOUT=600,
        _Rejected=RuntimeError)
    exec(compile(ast.Module(body=[plan_fn], type_ignores=[]), '<native-terminal-plan-fixture>', 'exec'), namespace)
    tools = types.ModuleType('tools'); tools.__path__ = []
    environments = types.ModuleType('tools.environments'); environments.__path__ = []
    local = types.ModuleType('tools.environments.local'); local.LocalEnvironment = LocalEnvironment
    cli = types.ModuleType('hermes_cli'); cli.__path__ = []
    observability = types.ModuleType('hermes_cli.observability'); observability.__path__ = []
    metrics = types.ModuleType('hermes_cli.observability.shared_metrics_harness')
    metrics.record_terminal_outcome = lambda *args: None
    terminal_scope = types.ModuleType('tools.terminal_scope'); terminal_scope.enforce_no_refusal = lambda: None
    aliases = {'tools': tools, 'tools.mesh_writer_scope': scope, 'tools.environments': environments,
               'tools.environments.local': local, 'hermes_cli': cli, 'hermes_cli.observability': observability,
               'hermes_cli.observability.shared_metrics_harness': metrics, 'tools.terminal_scope': terminal_scope}
    def invoke(env, env_type):
        plan = types.SimpleNamespace(env_type=env_type, effective_task_id='fixture', effective_timeout=5,
                                     cwd=str(Path.cwd()), host_cwd=None)
        return namespace[fn.name]('fixture', env, plan, task_id='fixture', session_id='fixture',
                    session_key='fixture', workdir=None, approval_note=None, clear_interrupt=False)
    fence = WindowsWriterFence('native-foreground-route-fixture', 'one')
    lifetime, checks = scope.WriterLifetime(fence), []
    try:
        with patch.dict(sys.modules, aliases):
            with scope.writer_foreground_scope(lifetime):
                config['env_type'] = 'ssh'
                try:
                    namespace[plan_fn.name]('fixture', task_id='fixture', timeout=5, background=False, _host_local=False)
                except RuntimeError:
                    checks.append('native_terminal_plan_remote_refused_before_environment_acquisition')
                else:
                    raise AssertionError('Remote terminal plan reached environment acquisition')
                config['env_type'] = 'local'
                plan = namespace[plan_fn.name]('fixture', task_id='fixture', timeout=5, background=False, _host_local=False)
                if plan.env_type != 'local':
                    raise AssertionError('Local terminal planning changed')
                checks.append('native_terminal_local_plan_preserved')
                result = json.loads(invoke(LocalEnvironment(), 'local'))
                if result != {'output': 'foreground route output', 'exit_code': 0}:
                    raise AssertionError('Native local foreground output changed')
                checks.append('native_foreground_local_route_preserves_real_process_output')
                for env_type in ['ssh', 'local']:
                    before = len(calls)
                    try:
                        invoke(RemoteEnvironment(), env_type)
                    except RuntimeError:
                        if len(calls) != before:
                            raise AssertionError('Remote terminal executed before rejection')
                        checks.append('native_foreground_' + ('remote' if env_type == 'ssh' else 'impostor_local')
                                      + '_refused_before_execute')
                    else:
                        raise AssertionError('Untracked foreground backend accepted')
            if not lifetime.wait()['managedWorkEnded']:
                raise AssertionError('Local foreground process did not settle')
            if json.loads(invoke(RemoteEnvironment(), 'ssh'))['output'] != 'legacy remote fixture':
                raise AssertionError('Unenrolled remote terminal behavior changed')
            checks.append('native_foreground_unenrolled_remote_route_preserved')
            config['env_type'] = 'ssh'
            plan = namespace[plan_fn.name]('fixture', task_id='fixture', timeout=5, background=False, _host_local=False)
            if plan.env_type != 'ssh':
                raise AssertionError('Legacy remote terminal planning changed')
            checks.append('native_terminal_unenrolled_remote_plan_preserved')
    finally:
        fence.terminate(); fence.close()
    return checks


def qualify_status_observation(modules):
    """Actual status functions; fixture ownership gate/store, real worker lifetime."""
    functions = [n for n in ast.parse(modules['gateway/platforms/api_server_runs.py']).body
                 if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                 and n.name in ('_set_run_status', '_handle_get_run')]
    namespace = {'Any': typing.Any, 'web': types.SimpleNamespace(Request=object, Response=object,
                  json_response=lambda body: body), 'time': time, 'TERMINAL_STATUSES': {'completed', 'failed', 'cancelled'},
                 'logger': types.SimpleNamespace(exception=lambda *args: None)}
    exec(compile(ast.Module(body=functions, type_ignores=[]), '<native-run-status-fixture>', 'exec'), namespace)
    stored = []
    run_id = 'run_' + uuid.uuid4().hex
    registry = scope.WriterRunRegistry(WindowsWriterFence)
    run = types.SimpleNamespace(run_id=run_id, admission=None, writer_lifetime=None, writer_generation='')
    lifetime = registry.enroll(run)
    host = types.SimpleNamespace(_mesh_writer_runs=registry, _run_statuses={}, _run_idempotency_ids={run_id},
        _run_idempotency_store=types.SimpleNamespace(update_status=lambda key, body: stored.append(json.loads(json.dumps(body)))))
    tools = types.ModuleType('tools'); tools.__path__ = []
    aliases = {'tools': tools, 'tools.mesh_writer_scope': scope}
    checks = []
    try:
        with patch.dict(sys.modules, aliases):
            with scope.writer_foreground_scope(lifetime):
                status = namespace['_set_run_status'](host, run_id, 'completed', output='fixture response',
                            writer_lifecycle={'writerQuiescence': True, 'state': 'forged cached receipt'})
                observation = status['writer_lifecycle']
                if observation['writerQuiescence'] or observation['enrollment']['lifetime']['managedWorkEnded']:
                    raise AssertionError('Native completed response released its active foreground worker')
                if stored[-1]['writer_lifecycle'] != observation:
                    raise AssertionError('Existing native persistence callback lost its server observation')
                checks.append('native_completed_status_persists_active_worker_observation')
            namespace['_load_owned_run'] = lambda *args, **kwargs: (run_id, status, None, None, None)
            fresh = asyncio.run(namespace['_handle_get_run'](host, object(), _api_server=object()))
            if not fresh['writer_lifecycle']['enrollment']['lifetime']['managedWorkEnded']:
                raise AssertionError('Owned status poll did not refresh actual worker completion')
            if status['writer_lifecycle']['enrollment']['lifetime']['managedWorkEnded']:
                raise AssertionError('Read-only fresh poll mutated historical saved observation')
            checks.append('native_owned_poll_refreshes_lifetime_without_reusing_saved_completion')
            original_owner = fresh['writer_lifecycle']['ownerId']
            host._mesh_writer_runs = scope.WriterRunRegistry(WindowsWriterFence)
            restarted = asyncio.run(namespace['_handle_get_run'](host, object(), _api_server=object()))
            observation = restarted['writer_lifecycle']
            if (observation['ownerId'] == original_owner or observation['state'] != 'unknown'
                    or observation['enrollment'] is not None or observation['writerQuiescence']):
                raise AssertionError('Restart recovered false ownership from old run status')
            checks.append('native_owned_poll_restart_reports_unknown_new_owner')
            refusal = types.SimpleNamespace(status=403)
            namespace['_load_owned_run'] = lambda *args, **kwargs: (None, None, None, None, refusal)
            with patch.object(host._mesh_writer_runs, 'snapshot', side_effect=AssertionError('Unauthorized observation')):
                denied = asyncio.run(namespace['_handle_get_run'](host, object(), _api_server=object()))
            if denied is not refusal:
                raise AssertionError('Unauthorized status request reached worker observations')
            checks.append('native_owned_poll_refusal_precedes_writer_observation')
    finally:
        lifetime.fence.terminate(); lifetime.fence.close()
    return checks


def qualify_title_thread(modules):
    """Actual native title start function, real native Thread and weak tracking set."""
    import weakref
    fn = next(n for n in ast.parse(modules['agent/title_generator.py']).body
              if isinstance(n, ast.FunctionDef) and n.name == 'start_title_upgrade')
    tracked = weakref.WeakSet()
    namespace = {'Optional': typing.Optional, 'threading': threading, '_UPGRADE_THREADS': tracked}
    exec(compile(ast.Module(body=[fn], type_ignores=[]), '<native-title-start-fixture>', 'exec'), namespace)
    entered, release = threading.Event(), threading.Event()
    thread = threading.Thread(target=lambda: (entered.set(), release.wait(timeout=5)), daemon=True)
    fence = WindowsWriterFence('native-title-start-fixture', 'one')
    lifetime = scope.WriterLifetime(fence)
    tools = types.ModuleType('tools'); tools.__path__ = []
    try:
        with patch.dict(sys.modules, {'tools': tools, 'tools.mesh_writer_scope': scope}):
            with scope.writer_foreground_scope(lifetime):
                namespace[fn.name](None)
                namespace[fn.name](thread)
                if not entered.wait(timeout=3) or thread not in tracked:
                    raise AssertionError('Native title tracking/start changed')
                namespace[fn.name](thread)  # Native duplicate-start guard must remain intact.
            snapshot = lifetime.wait(20)
            if snapshot['managedWorkEnded'] or len(snapshot['pendingWorkers']) != 1:
                raise AssertionError('Native title thread was not retained after foreground return')
            release.set(); thread.join(timeout=3)
            if not lifetime.wait()['managedWorkEnded'] or lifetime.snapshot()['writerQuiescence']:
                raise AssertionError('Native title join did not settle locally without release')
        return ['native_title_thread_held_after_foreground_return',
                'native_title_weakset_duplicate_guard_and_actual_join_preserved']
    finally:
        release.set()
        if thread.ident is not None:
            thread.join(timeout=3)
        fence.terminate(); fence.close()


def qualify_canonical_worker_seam(modules):
    """Actual native run_sync method; fixture policy/context and reserved claim only."""
    from contextlib import contextmanager
    tree = ast.parse(modules['gateway/run_turn_runner.py'])
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'TurnRunner')
    fn = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == 'run_sync')
    namespace = {}
    exec(compile(ast.Module(body=[fn], type_ignores=[]), '<native-canonical-worker-seam>', 'exec'), namespace)
    captured, cleanup = {}, []
    fence = WindowsWriterFence('canonical-worker-seam', 'one')
    lifetime = scope.WriterLifetime(fence)
    @contextmanager
    def policy(*args, **kwargs):
        try:
            yield
        finally:
            if lifetime.snapshot()['rootEnded']:
                raise AssertionError('Canonical root ended before native policy cleanup')
            cleanup.append('policy-cleanup')
    replacements = {}
    for name in ['gateway.session_policy','gateway.session_api_turn','gateway.session_authorities','gateway.session_results']:
        replacements[name] = types.ModuleType(name)
    replacements['gateway.session_policy'].policy_for_source = lambda *args: None
    replacements['gateway.session_policy'].policy_scope = policy
    replacements['gateway.session_api_turn'].api_policy_scope = policy
    replacements['gateway.session_authorities'].active_authority = lambda *args: None
    replacements['gateway.session_results'].execution_result = types.SimpleNamespace(get=lambda: captured)
    replacements['tools.mesh_writer_scope'] = scope
    worker = types.SimpleNamespace(_runner=object(), _ctx=types.SimpleNamespace(source='fixture'),
                                   _cli_result_fields={'fixture': True})
    def run():
        if lifetime.snapshot()['rootEnded']:
            raise AssertionError('Canonical body ran outside the root lifetime')
        return {'final_response':'synthetic canonical result'}
    worker._run_sync_scoped = run
    try:
        with patch.dict(sys.modules, replacements), scope.bind_canonical_writer_claim(lifetime):
            result = namespace['run_sync'](worker)
        if (result['final_response'] != 'synthetic canonical result' or captured['result'].get('fixture') is not True
                or len(cleanup) != 2 or not lifetime.wait()['managedWorkEnded']):
            raise AssertionError('Native canonical result/cleanup/lifetime changed')
        return ['native_canonical_run_sync_result_capture_and_cleanup_inside_lifetime']
    finally:
        fence.terminate(); fence.close()


if __name__ == '__main__':
    out, candidate, modules = prepare(Path(sys.argv[1]))
    report = {'state': 'candidate_only', 'baselineSha256': BASELINE,
              'nativeSourceBaselines': {'tools/process_registry.py': BASELINE, **LIFETIME_BASELINES,
                                        'tools/environments/local.py': FOREGROUND_BASELINE, **TOOL_WORKER_BASELINES,
                                        'tools/file_tools.py': FILE_TOOLS_BASELINE,
                                        'tools/terminal_tool.py': TERMINAL_TOOL_BASELINE,
                                        'agent/title_generator.py': TITLE_BASELINE,
                                        'gateway/run_turn_runner.py': CANONICAL_WORKER_BASELINE,
                                        'gateway/session_ingress.py': CANONICAL_INGRESS_BASELINE},
              'qualificationScope': 'patched native functions with fixture profiles/ledgers and real threads/processes',
              'files': {name: hashlib.sha256(text.encode()).hexdigest() for name, text in modules.items()},
              'liveInstallation': False, 'wholeWorkerReleaseQualified': False}
    try:
        report['checks'] = (qualify(candidate) + qualify_lifetimes(modules) + qualify_foreground(modules)
                            + qualify_enrollment(modules) + qualify_tool_worker_submissions(modules)
                            + qualify_tool_effect_boundary(modules) + qualify_file_tool_routes(modules)
                            + qualify_terminal_routes(modules) + qualify_status_observation(modules)
                            + qualify_title_thread(modules) + qualify_canonical_worker_seam(modules))
        report['qualification'] = 'PASS'
    except BaseException as error:
        report.update(qualification='FAIL', errorClass=type(error).__name__)
        (out / 'qualification.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
        raise
    (out / 'qualification.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps({'directory': str(out), **report}, indent=2))
