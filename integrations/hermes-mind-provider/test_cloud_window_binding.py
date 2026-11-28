"""Call-surface tests for run_phase('inspect-old') in cloud_windows_entry.

Pure fakes: no real SDK, subprocess, scheduled task, networking or private
files. sys.modules and sys.path are restored after every test because
run_phase prepends to sys.path and injects fake modules.
"""
import hashlib
import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ENTRY_PATH = Path(__file__).with_name('cloud_windows_entry.py')
_TMP = None
BASE = None
WORKSPACE = None
SDK = None
EVIDENCE = None
INTEGRATIONS = None
MIND = None


def _digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _write(path, text=''):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding='utf-8')
    return path


def _fake_module(name, **attrs):
    module = type(sys)(name)
    module.__dict__.update(attrs)
    if BASE is not None:
        module.__file__ = str(_write(BASE / 'fake-modules' / (name + '.py')))
    sys.modules[name] = module
    return module


class FakeWindow:
    """Context-tracked launcher window; enter/exit counts observable.

    MeshLauncherWindow-style context manager: __enter__ returns the window
    itself (run_phase does stack.enter_context(MeshLauncherWindow(...))).
    """

    instances = []

    def __init__(self, workspace, sha):
        self.workspace = workspace
        self.sha = sha
        self.entered = 0
        self.exited = 0
        self.abandoned = False
        FakeWindow.instances.append(self)

    def __enter__(self):
        self.entered += 1
        return self

    def __exit__(self, exc_type, exc, tb):
        self.exited += 1
        return False

    @property
    def held(self):
        return self.entered == 1 and self.exited == 0


class MindRolesKwargsError(TypeError):
    pass


class BrokenMindRoles:
    """Constructor REQUIRES keyword window and asserts it is the entered one."""

    def __init__(self, evidence, retained, window):
        if window is None:
            raise MindRolesKwargsError('MindRoles requires keyword window')
        if not isinstance(window, FakeWindow) or not window.held:
            raise MindRolesKwargsError('window must be the entered MeshLauncherWindow instance')
        # Caller-owned retained list; the adapter keeps its own state there.
        self.evidence = evidence
        self.retained = retained


class RecorderMindRoles(BrokenMindRoles):
    """Same guards; also records the construction call."""

    calls = []

    def __init__(self, evidence=None, retained=None, window=None):
        super().__init__(evidence=evidence, retained=retained, window=window)
        RecorderMindRoles.calls.append({'evidence': evidence,
                                        'retained': retained, 'window': window})


class ProcessObservation:
    """Fake recovery.ProcessObservation; tracks close, never kill."""

    def __init__(self, tag='observation'):
        self.tag = tag
        self.closed = 0
        self.kill_calls = 0

    def close(self):
        self.closed += 1

    def kill(self):
        self.kill_calls += 1


class UnrelatedRetained:
    """Retained object that must never be closed or killed."""

    def __init__(self):
        self.closed = 0
        self.kill_calls = 0

    def close(self):
        self.closed += 1

    def kill(self):
        self.kill_calls += 1


def install_fakes(mindroles=RecorderMindRoles):
    """Install fake SDK/native/launcher modules; caller restores sys.modules.

    The fake native MindRoles constructor requires keyword `window` and
    asserts it is exactly the entered FakeWindow instance, so the original
    production file (no window= argument) fails here with a missing-window
    error.
    """
    _init_workspace()
    RecorderMindRoles.calls = []
    FakeWindow.instances = []

    enrollment = _fake_module('onoes_mind.enrollment_store',
                              qualify_private_storage=lambda path, kind=None: Path(path))
    mind_root = _fake_module('onoes_mind')
    # Fake startup.ROOT equals the canonical workspace.
    mind_root.__path__ = [str(MIND)]
    mind_root.__file__ = str(MIND / '__init__.py')

    owner = {'live': True, 'mode': 'connected', 'receiptSha256': 'a' * 64,
             'record': {'pid': 123, 'creationTicks': 456}}
    _fake_module('mesh_startup_candidate', ROOT=WORKSPACE, owner_record=lambda *a: dict(owner))
    _fake_module('project_service_process_candidate')
    _fake_module('reader_service_process_candidate')
    _fake_module('recall_process_candidate')
    _fake_module('mesh_recovery_candidate', ProcessObservation=ProcessObservation)
    _fake_module('mesh_launcher_window', MeshLauncherWindow=FakeWindow)
    return enrollment


def install_cutover(selection):
    _fake_module('approved_cloud_windows_cutover', selection=selection)


def install_controls(mindroles):
    _fake_module('approved_cloud_native_mind_roles', MindRoles=mindroles)


# --- canonical TemporaryDirectory workspace (built once, at first use) ------

def _init_workspace():
    """Create the canonical root, fake onoes_mind package and pin sources."""
    global _TMP, BASE, WORKSPACE, SDK, EVIDENCE, INTEGRATIONS, MIND
    if _TMP is not None:
        return
    _TMP = tempfile.TemporaryDirectory(prefix='window-binding-062-')
    BASE = Path(_TMP.name).resolve()
    WORKSPACE = BASE / 'workspace'
    SDK = WORKSPACE / 'sdk'
    EVIDENCE = WORKSPACE / 'evidence'
    INTEGRATIONS = WORKSPACE / 'integrations'
    MIND = SDK / 'onoes_mind'
    # The selected mindSource is the fake onoes_mind package parent (SDK root).
    for rel in ('mesh_startup_candidate.py', 'mesh_launcher_window.py',
                'mesh_recovery_candidate.py',
                'mind-recovery-candidate/project_service_process_candidate.py',
                'mind-recovery-candidate/reader_service_process_candidate.py',
                'mind-recovery-candidate/recall_process_candidate.py'):
        _write(INTEGRATIONS / rel, '# fake source\n')
    for rel in ('__init__.py', 'enrollment_store.py', 'migrations/0001.sql'):
        _write(MIND / rel, '# fake onoes_mind source\n')
    _write(EVIDENCE / '.keep', '')


def _build_plan():
    required = []
    required += [INTEGRATIONS / n for n in ('mesh_startup_candidate.py',
                                            'mesh_launcher_window.py',
                                            'mesh_recovery_candidate.py')]
    required += [INTEGRATIONS / 'mind-recovery-candidate' / n for n in
                 ('project_service_process_candidate.py',
                  'reader_service_process_candidate.py',
                  'recall_process_candidate.py')]
    pins = {str(p): _digest(p) for p in required}
    for p in list(MIND.rglob('*.py')) + list((MIND / 'migrations').glob('*.sql')):
        pins[str(p)] = _digest(p)
    cutover_path = _write(BASE / 'cloud_windows_cutover.py', '# fake cutover\n')
    controls_path = _write(BASE / 'cloud_native_mind_roles.py', '# fake controls\n')
    return {
        'schema': 'onoes-cloud-windows-phases/v1',
        'agentId': 'cyony',
        'modelCalls': 0,
        'python': sys.executable,
        'workspace': str(WORKSPACE),
        'evidence': str(EVIDENCE),
        'entrySha256': _digest(ENTRY_PATH),
        'cutoverSha256': _digest(cutover_path),
        'nativeControlsPath': str(controls_path),
        'nativeControlsSha256': _digest(controls_path),
        'launcherSha256': 'b' * 64,
        'originalOwnerSha256': 'c' * 64,
        'maintenance': {'powershell': 'C:/Windows/System32/WindowsPowerShell/v1.0/powershell.exe',
                        'powershellSha256': 'd' * 64,
                        'disabledDefinitionSha256': 'e' * 64},
        'old': {'mindSource': str(SDK), 'sourcePins': pins,
                'startupPath': str(INTEGRATIONS / 'mesh_startup_candidate.py'),
                'startupSha256': _digest(INTEGRATIONS / 'mesh_startup_candidate.py')},
        'new': {'mindSource': str(SDK), 'sourcePins': pins,
                'startupPath': str(INTEGRATIONS / 'mesh_startup_candidate.py'),
                'startupSha256': _digest(INTEGRATIONS / 'mesh_startup_candidate.py')},
    }


def write_plan_and_authorization(plan):
    plan_path = _write(BASE / 'plan.json', json.dumps(plan, sort_keys=True))
    auth_path = _write(BASE / 'authorization.json', json.dumps(
        {'schema': 'onoes-cloud-windows-authorization/v1',
         'planSha256': _digest(plan_path), 'owner': 'Eddie',
         'decision': 'approve_scoped_cloud_mind_window'}, sort_keys=True))
    return plan_path, _digest(plan_path), auth_path


class WindowBindingTest(unittest.TestCase):
    """Exercises run_phase('inspect-old') against fakes only."""

    def setUp(self):
        self._modules = dict(sys.modules)
        self._path = list(sys.path)
        self._environ = dict(os.environ)

    def tearDown(self):
        sys.modules.clear()
        sys.modules.update(self._modules)
        sys.path[:] = self._path
        os.environ.clear()
        os.environ.update(self._environ)

    def _entry(self):
        spec = importlib.util.spec_from_file_location('cloud_windows_entry_under_test', ENTRY_PATH)
        entry = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(entry)
        return entry

    def _prepare(self, mindroles=RecorderMindRoles, selection=None, launcher=FakeWindow):
        entry = self._entry()
        install_fakes(mindroles)
        # plan/authorization files are still written and digested so mocked
        # approved_inputs returns the same canonical plan run_phase expects.
        plan = _build_plan()
        plan_path, pin, auth_path = write_plan_and_authorization(plan)
        # Mocked per task instructions: no real gates, powershell/task surface
        # or file loader; load returns the already-installed fake modules.
        entry.approved_inputs = lambda phase, path, pin, auth: (plan, plan['old'])
        entry.maintenance_paused = lambda plan: True
        entry.load = lambda path, name, pin: sys.modules[name]
        sys.modules['mesh_launcher_window'].MeshLauncherWindow = launcher
        if selection is None:
            def selection(**kwargs):
                selection.calls.append(kwargs)
                return 'handoff', 'profiles', None, None, None
            selection.calls = []
        install_cutover(selection)
        install_controls(mindroles)
        return entry, plan_path, pin, auth_path, selection

    def test_inspect_old_binds_entered_window_to_mindroles(self):
        entry, plan_path, pin, auth_path, selection = self._prepare()
        result = entry.run_phase('inspect-old', plan_path, pin, auth_path)
        self.assertEqual(result, {'verified': True, 'ownerSha256': 'a' * 64,
                                  'pid': 123, 'creationTicks': 456})
        self.assertEqual(len(RecorderMindRoles.calls), 1)
        window = RecorderMindRoles.calls[0]['window']
        self.assertIs(window, FakeWindow.instances[0])
        self.assertEqual(FakeWindow.instances[0].entered, 1)
        self.assertEqual(FakeWindow.instances[0].exited, 1)
        self.assertFalse(FakeWindow.instances[0].abandoned)
        self.assertIn('window', selection.calls[0])
        self.assertIs(selection.calls[0]['window'], FakeWindow.instances[0])

    def test_abandoned_window_refuses_before_adapter_construction(self):
        def abandoned_launcher(workspace, sha):
            window = FakeWindow(workspace, sha)
            window.abandoned = True
            return window

        entry, plan_path, pin, auth_path, selection = self._prepare(launcher=abandoned_launcher)
        with self.assertRaises(entry.PhaseHeld):
            entry.run_phase('inspect-old', plan_path, pin, auth_path)
        self.assertEqual(RecorderMindRoles.calls, [])
        self.assertEqual(selection.calls, [])
        self.assertEqual(FakeWindow.instances[0].entered, 1)
        self.assertEqual(FakeWindow.instances[0].exited, 1)

    def test_adapter_constructor_error_propagates_and_releases_window(self):
        def boom(evidence, retained, window):
            raise RuntimeError('adapter construction failed')

        entry, plan_path, pin, auth_path, selection = self._prepare(mindroles=boom)
        with self.assertRaises(RuntimeError):
            entry.run_phase('inspect-old', plan_path, pin, auth_path)
        self.assertEqual(selection.calls, [])
        self.assertEqual(FakeWindow.instances[0].entered, 1)
        self.assertEqual(FakeWindow.instances[0].exited, 1)

    def test_observations_added_by_constructor_closed_on_success(self):
        class CtorObservingRoles(RecorderMindRoles):
            """Adds observations to the caller-owned retained list."""

            def __init__(self, evidence=None, retained=None, window=None):
                super().__init__(evidence=evidence, retained=retained, window=window)
                CtorObservingRoles.obs = ProcessObservation('constructor-observation')
                retained.append(CtorObservingRoles.obs)
                CtorObservingRoles.unrelated = UnrelatedRetained()
                retained.append(CtorObservingRoles.unrelated)

        entry, plan_path, pin, auth_path, selection = self._prepare(mindroles=CtorObservingRoles)
        result = entry.run_phase('inspect-old', plan_path, pin, auth_path)
        self.assertTrue(result['verified'])
        self.assertEqual(CtorObservingRoles.obs.closed, 1)
        self.assertEqual(CtorObservingRoles.unrelated.closed, 0)
        self.assertEqual(CtorObservingRoles.unrelated.kill_calls, 0)
        self.assertEqual(FakeWindow.instances[0].exited, 1)

    def test_observations_closed_on_phase_error(self):
        class CtorObservingRoles(RecorderMindRoles):
            def __init__(self, evidence=None, retained=None, window=None):
                super().__init__(evidence=evidence, retained=retained, window=window)
                CtorObservingRoles.obs = ProcessObservation('constructor-observation')
                retained.append(CtorObservingRoles.obs)
                CtorObservingRoles.unrelated = UnrelatedRetained()
                retained.append(CtorObservingRoles.unrelated)

        def failing_selection(**kwargs):
            raise RuntimeError('selection failed')

        entry, plan_path, pin, auth_path, selection = self._prepare(mindroles=CtorObservingRoles,
                                                                   selection=failing_selection)
        with self.assertRaises(RuntimeError):
            entry.run_phase('inspect-old', plan_path, pin, auth_path)
        self.assertEqual(CtorObservingRoles.obs.closed, 1)
        self.assertEqual(CtorObservingRoles.unrelated.closed, 0)
        self.assertEqual(CtorObservingRoles.unrelated.kill_calls, 0)
        self.assertEqual(FakeWindow.instances[0].exited, 1)


if __name__ == '__main__':
    unittest.main()
