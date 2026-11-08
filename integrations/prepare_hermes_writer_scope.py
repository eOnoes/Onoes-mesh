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


if __name__ == '__main__':
    out, candidate, modules = prepare(Path(sys.argv[1]))
    report = {'state': 'candidate_only', 'baselineSha256': BASELINE,
              'nativeSourceBaselines': {'tools/process_registry.py': BASELINE, **LIFETIME_BASELINES,
                                        'tools/environments/local.py': FOREGROUND_BASELINE},
              'qualificationScope': 'patched native functions with fixture profiles/ledgers and real threads/processes',
              'files': {name: hashlib.sha256(text.encode()).hexdigest() for name, text in modules.items()},
              'liveInstallation': False, 'wholeWorkerReleaseQualified': False}
    try:
        report['checks'] = qualify(candidate) + qualify_lifetimes(modules) + qualify_foreground(modules) + qualify_enrollment(modules)
        report['qualification'] = 'PASS'
    except BaseException as error:
        report.update(qualification='FAIL', errorClass=type(error).__name__)
        (out / 'qualification.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
        raise
    (out / 'qualification.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps({'directory': str(out), **report}, indent=2))
