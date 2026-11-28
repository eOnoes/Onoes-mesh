"""Fakes-only unittest for the native mind-role adapter.

No real process, service or SDK operation happens here: the recovery SDK,
the roles module and the two native role modules are synthetic objects
installed into sys.modules only for the duration of one test and restored
afterwards. checked_profile and launch_service use the REAL tuple return
shapes and integer creation ticks. Invalid inputs are passed by direct
call, never through None-defaulting helpers.
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import ModuleType

sys.path.insert(0, str(Path(__file__).resolve().parent))

import cloud_native_mind_controls as adapter
from cloud_native_mind_controls import MindRoles, MindRolesHeld

SHA = 'a' * 64
HEX32 = 'ab12' + '0' * 28


class FakeWindow:
    def __init__(self, workspace):
        self.workspace = str(workspace)
        self.held = True
        self.assertHeldCalls = 0

    def assert_held(self):
        self.assertHeldCalls += 1
        if not self.held:
            raise AssertionError('window released')


class FakeObservation:
    """Kernel-retirement sentinel: poll() -> 0 means retired, never an exit code."""

    def __init__(self, window, roles, pid, creationTicks, argv, *, allow_terminate):
        self.window = window
        self.roles = roles
        self.pid = pid
        self.ticks = creationTicks
        self.argv = list(argv)
        self.allowTerminate = allow_terminate
        self.polls = 0
        self.retireAfter = 1
        self.closed = 0

    def poll(self):
        self.polls += 1
        if self.polls > self.retireAfter:
            return 0
        return None


def fake_roles_module():
    module = ModuleType('recall_process_candidate')

    def private_new_json(path, value):
        flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
        fd = os.open(str(path), flags, 0o600)
        with os.fdopen(fd, 'w') as handle:
            json.dump(value, handle)

    module.private_new_json = private_new_json
    return module


def _touch(path, text=''):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return str(path)


class Harness(unittest.TestCase):
    def setUp(self):
        self._stack = []
        for name in ('mesh_recovery_candidate', 'recall_process_candidate',
                     'onoes_mind', 'onoes_mind.enrollment_store'):
            self._stack.append((name, sys.modules.get(name)))
        roles = fake_roles_module()
        recovery = ModuleType('mesh_recovery_candidate')
        recovery.ProcessObservation = FakeObservation
        enrollment = ModuleType('onoes_mind.enrollment_store')
        enrollment.qualify_private_storage = lambda path, *, kind: None
        onoes = ModuleType('onoes_mind')
        onoes.enrollment_store = enrollment
        sys.modules['mesh_recovery_candidate'] = recovery
        sys.modules['recall_process_candidate'] = roles
        sys.modules['onoes_mind'] = onoes
        sys.modules['onoes_mind.enrollment_store'] = enrollment
        self.roles = roles
        self.recovery = recovery
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name).resolve(strict=True)
        self.root = root
        self.workspace = root / 'workspace'
        native = self.workspace / 'integrations' / 'mind-recovery-candidate'
        _touch(self.workspace / 'integrations' / 'mesh_recovery_candidate.py')
        self.writerPath = _touch(native / 'project_service_process_candidate.py')
        self.readerPath = _touch(native / 'reader_service_process_candidate.py')
        recovery.__file__ = str(self.workspace / 'integrations' / 'mesh_recovery_candidate.py')
        roles.__file__ = str(native / 'recall_process_candidate.py')
        self.evidence = root / 'evidence'
        self.evidence.mkdir()
        self.window = FakeWindow(self.workspace)
        self.retained = []
        self.writer = self._fake_module(self.writerPath, 'ServiceLaunchUnknown')
        self.reader = self._fake_module(self.readerPath, 'ReaderLaunchUnknown')
        self.profile = _touch(root / 'profile.json', '{}')
        self.approval = _touch(root / 'approval.json', '{}')
        self.descriptor = {'targetPath': self.profile, 'sha256': SHA}
        self.approvalDict = {'targetPath': self.approval}

    def tearDown(self):
        for name, previous in reversed(self._stack):
            if previous is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = previous
        self._tmp.cleanup()

    def _fake_module(self, file_path, unknown_name):
        module = ModuleType(file_path)
        module.__file__ = file_path
        state = {'calls': [], 'checked': None, 'states': [], 'stopResult': None,
                 'launchResult': None, 'launchError': None}
        module.state = state

        def checked_profile(profilePath, sha, approvalPath):
            state['calls'].append('checked_profile')
            return state['checked']

        def service_state(profilePath, sha, approvalPath):
            state['calls'].append('service_state')
            if not state['states']:
                raise AssertionError('service_state called with no scripted observation')
            if len(state['states']) > 1:
                return state['states'].pop(0)
            return state['states'][0]

        def request_stop(profilePath, sha, approvalPath):
            state['calls'].append('request_stop')
            if state['stopResult'] is not None:
                raise state['stopResult']

        def launch_service(profilePath, sha, approvalPath):
            state['calls'].append('launch_service')
            if state['launchError'] is not None:
                raise state['launchError']
            p, base, _ = state['checked']
            _touch(Path(p['attemptPath']), '{}')
            _touch(Path(p.get('readyPath') or base['readyPath']), '{}')
            return state['launchResult']

        module.checked_profile = checked_profile
        module.service_state = service_state
        module.request_stop = request_stop
        module.launch_service = launch_service
        setattr(module, unknown_name, type(unknown_name, (Exception,), {}))
        return module

    def _adapter(self):
        return MindRoles(evidence=str(self.evidence), retained=self.retained, window=self.window)

    def _files(self, runId=HEX32, ready='file', attempt='file', stop='absent'):
        base = self.root / 'state'
        readyPath = str(base / ('ready-%s.json' % runId))
        attemptPath = str(base / ('attempt-%s.json' % runId))
        stopPath = str(base / ('stop-%s.flag' % runId))
        if ready == 'file':
            _touch(Path(readyPath), '{}')
        if attempt == 'file':
            _touch(Path(attemptPath), '{}')
        if stop == 'file':
            _touch(Path(stopPath))
        return readyPath, attemptPath, stopPath

    def _checked(self, runId=HEX32, readyIn='profile', **footprint):
        readyPath, attemptPath, stopPath = self._files(runId=runId, **footprint)
        p = {'stopPath': stopPath, 'attemptPath': attemptPath, 'runId': runId}
        if readyIn == 'profile':
            p['readyPath'] = readyPath
        base = {}
        if readyIn == 'base':
            base['readyPath'] = readyPath
        return {'profile': p, 'base': base, 'readyPath': readyPath,
                'attemptPath': attemptPath, 'stopPath': stopPath}

    def _live(self, runId=HEX32, pid=1111, ticks=2222):
        return {'processLive': True, 'ready': True, 'state': 'running', 'pid': pid,
                'creationTicks': ticks, 'runId': runId}

    def _stopped(self, runId=HEX32, pid=1111, ticks=2222):
        return {'processLive': False, 'ready': False, 'state': 'stopped', 'pid': pid,
                'creationTicks': ticks, 'runId': runId}

    def _child(self, pid):
        class _C:
            pass
        instance = _C()
        instance.pid = pid
        return instance

    def _receipts(self):
        return sorted(p.name for p in self.evidence.iterdir())

    def _obs(self):
        return [o for o in self.retained if isinstance(o, FakeObservation)]

    # ---- state ----

    def test_state_healthy(self):
        checked = self._checked()
        self.writer.state['checked'] = (checked['profile'], checked['base'], 'binding')
        self.writer.state['states'] = [self._live()]
        value = self._adapter().state(self.writer, self.descriptor, self.approvalDict)
        self.assertEqual(value['state'], 'running')
        self.assertEqual(value['pid'], 1111)

    def test_state_unused_slot_returns_none(self):
        checked = self._checked(ready='absent', attempt='absent')
        self.writer.state['checked'] = (checked['profile'], checked['base'], 'binding')
        self.writer.state['states'] = [self._stopped()]
        value = self._adapter().state(self.writer, self.descriptor, self.approvalDict)
        self.assertIsNone(value)

    def test_state_orphan_stop_path_holds(self):
        checked = self._checked(ready='absent', attempt='absent', stop='file')
        self.writer.state['checked'] = (checked['profile'], checked['base'], 'binding')
        self.writer.state['states'] = [self._stopped()]
        with self.assertRaises(MindRolesHeld):
            self._adapter().state(self.writer, self.descriptor, self.approvalDict)

    def test_state_partial_footprint_holds(self):
        checked = self._checked(attempt='absent')
        self.writer.state['checked'] = (checked['profile'], checked['base'], 'binding')
        self.writer.state['states'] = [self._stopped()]
        with self.assertRaises(MindRolesHeld):
            self._adapter().state(self.writer, self.descriptor, self.approvalDict)

    def test_state_invalid_pid_holds(self):
        checked = self._checked()
        self.writer.state['checked'] = (checked['profile'], checked['base'], 'binding')
        broken = self._live()
        broken['pid'] = True
        self.writer.state['states'] = [broken]
        with self.assertRaises(MindRolesHeld):
            self._adapter().state(self.writer, self.descriptor, self.approvalDict)

    def test_state_invalid_ticks_holds(self):
        checked = self._checked()
        self.writer.state['checked'] = (checked['profile'], checked['base'], 'binding')
        broken = self._live()
        broken['creationTicks'] = 'uuid-not-a-real-tick'
        self.writer.state['states'] = [broken]
        with self.assertRaises(MindRolesHeld):
            self._adapter().state(self.writer, self.descriptor, self.approvalDict)

    def test_reader_ready_path_from_base(self):
        checked = self._checked(readyIn='base')
        self.reader.state['checked'] = (checked['profile'], checked['base'], 'binding')
        self.reader.state['states'] = [self._live()]
        value = self._adapter().state(self.reader, self.descriptor, self.approvalDict)
        self.assertEqual(value['state'], 'running')

    # ---- input refusals ----

    def test_invalid_retained_not_list(self):
        with self.assertRaises(MindRolesHeld):
            MindRoles(evidence=str(self.evidence), retained=(), window=self.window)

    def test_evidence_not_dir(self):
        with self.assertRaises(MindRolesHeld):
            MindRoles(evidence=str(self.root / 'nope'), retained=[], window=self.window)

    def test_unheld_window_refused(self):
        self.window.held = False
        with self.assertRaises(AssertionError):
            MindRoles(evidence=str(self.evidence), retained=[], window=self.window)

    def test_wrong_module_location(self):
        fake = self._fake_module(str(self.root / 'elsewhere.py'), 'ServiceLaunchUnknown')
        with self.assertRaises(MindRolesHeld):
            self._adapter().state(fake, self.descriptor, self.approvalDict)

    def test_descriptor_not_exact_dict(self):
        with self.assertRaises(MindRolesHeld):
            self._adapter().state(self.writer, {'targetPath': self.profile}, self.approvalDict)

    def test_bad_sha(self):
        with self.assertRaises(MindRolesHeld):
            self._adapter().state(self.writer,
                                  {'targetPath': self.profile, 'sha256': 'ABC'},
                                  self.approvalDict)

    def test_missing_profile_file(self):
        with self.assertRaises(MindRolesHeld):
            self._adapter().state(self.writer,
                                  {'targetPath': str(self.root / 'gone.json'), 'sha256': SHA},
                                  self.approvalDict)

    def test_wrong_label_for_stop(self):
        with self.assertRaises(MindRolesHeld):
            self._adapter().stop(self.writer, self.descriptor, self.approvalDict, 'new-reader-stop')

    # ---- stop ----

    def test_stop_graceful_proof(self):
        checked = self._checked()
        self.writer.state['checked'] = (checked['profile'], checked['base'], 'binding')
        self.writer.state['states'] = [self._live(), self._live(), self._stopped()]
        result = self._adapter().stop(self.writer, self.descriptor, self.approvalDict, 'old-writer-stop')
        self.assertEqual(result, {'verified': True, 'kernelRetired': True})
        calls = self.writer.state['calls']
        self.assertEqual(calls.count('request_stop'), 1)
        self.assertLess(calls.index('request_stop'), len(calls))
        observation = self._obs()[0]
        self.assertIs(observation.allowTerminate, False)
        self.assertEqual(observation.pid, 1111)
        self.assertEqual(observation.ticks, 2222)
        self.assertIn(self.writerPath, observation.argv)
        self.assertIn('--profile', observation.argv)
        self.assertIn(self.profile, observation.argv)
        self.assertIn('--sha256', observation.argv)
        self.assertIn(SHA, observation.argv)
        self.assertIn('--approval', observation.argv)
        self.assertIn(self.approval, observation.argv)
        self.assertIn('--run', observation.argv)
        names = self._receipts()
        self.assertEqual(len([n for n in names if 'stop' in n and 'RESULT' in n]), 1)
        receipt = json.loads((self.evidence / [n for n in names if 'RESULT' in n][0]).read_text())
        self.assertIs(receipt['verified'], True)
        self.assertIs(receipt['kernelRetired'], True)
        self.assertIs(receipt['nativeExitCodeClaimed'], False)
        profileText = ''.join((self.evidence / n).read_text() for n in names)
        self.assertNotIn(self.profile, profileText)

    def test_stop_unused_slot_refused(self):
        checked = self._checked(ready='absent', attempt='absent')
        self.writer.state['checked'] = (checked['profile'], checked['base'], 'binding')
        self.writer.state['states'] = [self._stopped()]
        with self.assertRaises(MindRolesHeld):
            self._adapter().stop(self.writer, self.descriptor, self.approvalDict, 'new-writer-stop')
        self.assertEqual(self._receipts(), [])
        self.assertEqual(self._obs(), [])

    def test_stop_identity_drift_before_request(self):
        checked = self._checked()
        self.writer.state['checked'] = (checked['profile'], checked['base'], 'binding')
        drifted = self._live()
        drifted['pid'] = 9999
        self.writer.state['states'] = [self._live(), drifted]
        with self.assertRaises(MindRolesHeld):
            self._adapter().stop(self.writer, self.descriptor, self.approvalDict, 'old-writer-stop')
        self.assertNotIn('request_stop', self.writer.state['calls'])
        names = self._receipts()
        self.assertEqual(len([n for n in names if 'RESULT' in n]), 0)
        self.assertEqual(len([n for n in names if 'ATTEMPT' in n]), 1)
        self.assertEqual(len(self._obs()), 1)

    def test_stop_timeout_no_kill_no_retry(self):
        class StillAlive(FakeObservation):
            def poll(self):
                return None
        self.recovery.ProcessObservation = StillAlive
        checked = self._checked()
        self.writer.state['checked'] = (checked['profile'], checked['base'], 'binding')
        self.writer.state['states'] = [self._live(), self._live()]
        adapter._TIMEOUT_SECONDS = 0.05
        self.addCleanup(setattr, adapter, '_TIMEOUT_SECONDS', 60.0)
        with self.assertRaises(MindRolesHeld):
            self._adapter().stop(self.writer, self.descriptor, self.approvalDict, 'restored-writer-stop')
        self.assertEqual(self.writer.state['calls'].count('request_stop'), 1)
        names = self._receipts()
        self.assertEqual(len([n for n in names if 'RESULT' in n]), 0)
        self.assertEqual(len([n for n in names if 'ATTEMPT' in n]), 1)
        observation = self._obs()[0]
        self.assertIs(observation.allowTerminate, False)
        self.assertEqual(observation.closed, 0)

    def test_stop_replay_refused_before_second_request(self):
        checked = self._checked()
        self.writer.state['checked'] = (checked['profile'], checked['base'], 'binding')
        self.writer.state['states'] = [self._live(), self._live(), self._stopped()]
        controls = self._adapter()
        controls.stop(self.writer, self.descriptor, self.approvalDict, 'old-writer-stop')
        self.writer.state['states'] = [self._live(), self._live(), self._stopped()]
        with self.assertRaises(MindRolesHeld):
            controls.stop(self.writer, self.descriptor, self.approvalDict, 'old-writer-stop')
        self.assertEqual(self.writer.state['calls'].count('request_stop'), 1)

    # ---- start ----

    def test_start_ready_bound_to_own_child(self):
        checked = self._checked(ready='absent', attempt='absent')
        self.writer.state['checked'] = (checked['profile'], checked['base'], 'binding')
        self.writer.state['states'] = [self._live(pid=3333, ticks=4444)]
        self.writer.state['launchResult'] = (self._child(3333), 4444)
        result = self._adapter().start(self.writer, self.descriptor, self.approvalDict, 'new-writer-start')
        self.assertEqual(result, {'verified': True, 'pid': 3333, 'creationTicks': 4444})
        self.assertEqual(self.writer.state['calls'].count('launch_service'), 1)
        observation = self._obs()[0]
        self.assertEqual(observation.pid, 3333)
        self.assertEqual(observation.ticks, 4444)
        self.assertIs(observation.allowTerminate, False)
        names = self._receipts()
        self.assertEqual(len([n for n in names if 'ATTEMPT' in n]), 1)
        self.assertEqual(len([n for n in names if 'RESULT' in n]), 1)
        attempt = [n for n in names if 'ATTEMPT' in n][0]
        result = [n for n in names if 'RESULT' in n][0]
        self.assertEqual(result.removesuffix('RESULT.json'), attempt.removesuffix('ATTEMPT.json'))
        self.assertEqual(self.writer.state['calls'].count('launch_service'), 1)

    def test_start_duplicate_attempt_blocks_second_launch(self):
        checked = self._checked(ready='absent', attempt='absent')
        self.writer.state['checked'] = (checked['profile'], checked['base'], 'binding')
        self.writer.state['states'] = [self._live(pid=3333, ticks=4444)]
        self.writer.state['launchResult'] = (self._child(3333), 4444)
        controls = self._adapter()
        controls.start(self.writer, self.descriptor, self.approvalDict, 'new-writer-start')
        before = list(self.writer.state['calls'])
        self.writer.state['states'] = [self._stopped(pid=3333, ticks=4444), self._live(pid=3333, ticks=4444)]
        with self.assertRaises(MindRolesHeld):
            controls.start(self.writer, self.descriptor, self.approvalDict, 'new-writer-start')
        self.assertNotIn('launch_service', self.writer.state['calls'][len(before):])
        self.assertEqual(len([n for n in self._receipts() if 'ATTEMPT' in n]), 1)

    def test_start_live_owner_refused(self):
        checked = self._checked()
        self.writer.state['checked'] = (checked['profile'], checked['base'], 'binding')
        self.writer.state['states'] = [self._live()]
        with self.assertRaises(MindRolesHeld):
            self._adapter().start(self.writer, self.descriptor, self.approvalDict, 'new-writer-start')
        self.assertNotIn('launch_service', self.writer.state['calls'])
        self.assertEqual(self._receipts(), [])

    def test_start_wrong_new_identity_refused(self):
        checked = self._checked(ready='absent', attempt='absent')
        self.writer.state['checked'] = (checked['profile'], checked['base'], 'binding')
        other = self._live(pid=7777, ticks=8888)
        self.writer.state['states'] = [other]
        self.writer.state['launchResult'] = (self._child(3333), 4444)
        with self.assertRaises(MindRolesHeld):
            self._adapter().start(self.writer, self.descriptor, self.approvalDict, 'new-writer-start')
        names = self._receipts()
        self.assertEqual(len([n for n in names if 'RESULT' in n]), 0)
        self.assertEqual(len(self._obs()), 1)

    def test_start_early_exit_preserves_handles(self):
        checked = self._checked(ready='absent', attempt='absent')
        self.writer.state['checked'] = (checked['profile'], checked['base'], 'binding')
        self.writer.state['states'] = []
        self.writer.state['launchResult'] = (self._child(3333), 4444)
        controls = self._adapter()
        realObservation = self.recovery.ProcessObservation

        class EarlyExit(FakeObservation):
            def poll(self):
                return 0

        self.recovery.ProcessObservation = EarlyExit
        self.addCleanup(setattr, self.recovery, 'ProcessObservation', realObservation)
        with self.assertRaises(MindRolesHeld):
            controls.start(self.writer, self.descriptor, self.approvalDict, 'restored-writer-start')
        names = self._receipts()
        self.assertEqual(len([n for n in names if 'ATTEMPT' in n]), 1)
        self.assertEqual(len([n for n in names if 'RESULT' in n]), 0)
        self.assertEqual(len(self._obs()), 1)
        self.assertNotIn('service_state', self.writer.state['calls'])

    def test_start_launch_unknown_retains_child(self):
        checked = self._checked(ready='absent', attempt='absent')
        self.writer.state['checked'] = (checked['profile'], checked['base'], 'binding')
        self.writer.state['states'] = []
        error = self.writer.ServiceLaunchUnknown('unknown launch')
        error.child = self._child(5555)
        error.creation_ticks = 6666
        self.writer.state['launchError'] = error
        with self.assertRaises(self.writer.ServiceLaunchUnknown):
            self._adapter().start(self.writer, self.descriptor, self.approvalDict, 'old-writer-start')
        self.assertIn(error, self.retained)
        self.assertIn(error.child, self.retained)
        self.assertEqual(self._obs(), [])
        self.assertEqual(len(self._receipts()), 1)

    def test_start_reader_uses_reader_error(self):
        checked = self._checked(readyIn='base', ready='absent', attempt='absent')
        self.reader.state['checked'] = (checked['profile'], checked['base'], 'binding')
        self.reader.state['states'] = []
        error = self.reader.ReaderLaunchUnknown('unknown')
        error.child = None
        error.creation_ticks = None
        self.reader.state['launchError'] = error
        with self.assertRaises(self.reader.ReaderLaunchUnknown):
            self._adapter().start(self.reader, self.descriptor, self.approvalDict, 'restored-reader-start')
        self.assertEqual(self._obs(), [])
        self.assertIn(error, self.retained)
        self.assertEqual(len(self._receipts()), 1)

    def test_start_timeout_preserves_handles(self):
        class StillAlive(FakeObservation):
            def poll(self):
                return None
        self.recovery.ProcessObservation = StillAlive
        checked = self._checked(ready='absent', attempt='absent')
        self.writer.state['checked'] = (checked['profile'], checked['base'], 'binding')
        starting = self._live(pid=3333, ticks=4444)
        starting.update({'ready': False, 'state': 'starting'})
        self.writer.state['states'] = [starting]
        self.writer.state['launchResult'] = (self._child(3333), 4444)
        adapter._TIMEOUT_SECONDS = 0.05
        self.addCleanup(setattr, adapter, '_TIMEOUT_SECONDS', 60.0)
        with self.assertRaises(MindRolesHeld):
            self._adapter().start(self.writer, self.descriptor, self.approvalDict, 'new-writer-start')
        self.assertEqual(self.writer.state['calls'].count('launch_service'), 1)
        names = self._receipts()
        self.assertEqual(len([n for n in names if 'ATTEMPT' in n]), 1)
        self.assertEqual(len([n for n in names if 'RESULT' in n]), 0)
        observation = self._obs()[0]
        self.assertIs(observation.allowTerminate, False)
        self.assertEqual(observation.closed, 0)


if __name__ == '__main__':
    unittest.main()
