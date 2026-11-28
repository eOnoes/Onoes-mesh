import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import mesh_launch_candidate as launch


class RoleLaunchUnknown(Exception):
    def __init__(self, child, creation_ticks):
        self.child = child
        self.creation_ticks = creation_ticks
        super().__init__('native launch outcome unknown')


class FakeStdin:
    def __init__(self, fail_write=False):
        self.writes = []
        self.closed = False
        self._fail = fail_write

    def write(self, data):
        if self._fail:
            raise BrokenPipeError('stdin closed')
        self.writes.append(bytes(data))

    def close(self):
        self.closed = True


class FakeChild:
    def __init__(self, fail_write=False):
        self.pid = 4321
        self._handle = object()
        self.stdin = FakeStdin(fail_write)

    def terminate(self):
        raise AssertionError('terminate must never be called')


class FakeRoles:
    def __init__(self, creation_ticks_value=123456, creation_ticks_error=None):
        self.creation_ticks_value = creation_ticks_value
        self.creation_ticks_error = creation_ticks_error
        self.RoleLaunchUnknown = RoleLaunchUnknown

    def new_role_file(self, path):
        return Path(path)

    def creation_ticks(self, handle):
        if self.creation_ticks_error is not None:
            raise self.creation_ticks_error
        return self.creation_ticks_value


def fresh_fixture(test):
    """TemporaryDirectory + canonical attempt.json holding old valid bytes."""
    stack = tempfile.TemporaryDirectory(prefix='mesh-attempt-')
    test.addCleanup(stack.cleanup)
    root = Path(stack.name).resolve(strict=True)
    target = root / 'attempt.json'
    old = b'{"state":"reserved"}'
    target.write_bytes(old)
    return root, target, old


def helper_call(target, new_record, previous_bytes, roles=None):
    return launch._atomic_attempt(target, new_record, roles or FakeRoles(), previous_bytes)


def temp_siblings(root, target):
    return sorted(p for p in root.iterdir() if p.name.startswith(target.name + '.') and p.suffix == '.tmp')


def canonical(test, target):
    return json.loads(target.read_bytes())


class AtomicAttemptTests(unittest.TestCase):
    def test_success_byte_identity_and_temp_gone(self):
        root, target, old = fresh_fixture(self)
        record = {'state': 'launch_reserved', 'pid': 7}
        payload = helper_call(target, record, old)
        self.assertEqual(target.read_bytes(), json.dumps(record).encode('utf-8'))
        self.assertEqual(payload, target.read_bytes())
        self.assertEqual(canonical(self, target), record)
        self.assertEqual(temp_siblings(root, target), [])
        self.assertNotEqual(target.read_bytes(), b'')

    def test_wrong_previous_bytes_refuses_unchanged(self):
        root, target, old = fresh_fixture(self)
        with self.assertRaises(launch.LaunchError):
            helper_call(target, {'state': 'new'}, b'{"state":"other"}')
        self.assertEqual(target.read_bytes(), old)
        self.assertEqual(temp_siblings(root, target), [])

    def test_replace_failure_keeps_old_and_exactly_one_temp(self):
        root, target, old = fresh_fixture(self)
        with mock.patch.object(launch.os, 'replace', side_effect=OSError('replace denied')):
            with self.assertRaises(OSError):
                helper_call(target, {'state': 'new'}, old)
        self.assertEqual(target.read_bytes(), old)
        canonical(self, target)
        temps = temp_siblings(root, target)
        self.assertEqual(len(temps), 1)
        self.assertEqual(temps[0].read_bytes(), json.dumps({'state': 'new'}).encode('utf-8'))

    def test_fsync_failure_keeps_old_and_temp(self):
        root, target, old = fresh_fixture(self)
        with mock.patch.object(launch.os, 'fsync', side_effect=OSError('fsync denied')):
            with self.assertRaises(OSError):
                helper_call(target, {'state': 'new'}, old)
        self.assertEqual(target.read_bytes(), old)
        self.assertEqual(len(temp_siblings(root, target)), 1)

    def test_target_content_changed_in_callback_refuses(self):
        root, target, old = fresh_fixture(self)
        changed = b'{"state":"tampered"}'

        def mutate(path):
            if not any(p.name.startswith(target.name + '.') for p in root.iterdir()):
                target.write_bytes(changed)
            return Path(path)

        with self.assertRaises(launch.LaunchError):
            helper_call(target, {'state': 'new'}, old, _roles_with(mutate))
        self.assertEqual(target.read_bytes(), changed)
        self.assertEqual(len(temp_siblings(root, target)), 1)

    def test_inode_changed_same_bytes_in_callback_refuses(self):
        root, target, old = fresh_fixture(self)

        def swap_inode(path):
            if not any(p.name.startswith(target.name + '.') for p in root.iterdir()):
                alias = target.parent / (target.name + '.swapped')
                alias.write_bytes(old)
                original_inode = target.lstat().st_ino
                # Replace while the original is still allocated so the id cannot
                # be trivially reused; on platforms without st_ino fall back to
                # the file id used by the helper check.
                try:
                    os.replace(alias, target)
                    changed_inode = target.lstat().st_ino != original_inode
                except (AttributeError, NotImplementedError):
                    identity = os.stat(target).st_file_id
                    os.replace(alias, target)
                    changed_inode = os.stat(target).st_file_id != identity
                self.assertTrue(changed_inode)
            return Path(path)

        with self.assertRaises(launch.LaunchError):
            helper_call(target, {'state': 'new'}, old, _roles_with(swap_inode))
        self.assertEqual(target.read_bytes(), old)
        self.assertEqual(len(temp_siblings(root, target)), 1)

    def test_temp_content_changed_before_check_refuses(self):
        root, target, old = fresh_fixture(self)
        seen = []
        real_fsync = os.fsync

        def tampering_fsync(fd):
            real_fsync(fd)
            # Tamper the first temp while it is still open, before the helper
            # re-reads it just before os.replace.
            for p in temp_siblings(root, target):
                if p not in seen:
                    seen.append(p)
                    try:
                        with p.open('ab') as handle:
                            handle.write(b'x')
                    except OSError:
                        # Windows denies reopening a file that is still open
                        # exclusively; tamper through the fd being fsynced.
                        os.write(fd, b'x')

        with mock.patch.object(launch.os, 'fsync', side_effect=tampering_fsync):
            with self.assertRaises(launch.LaunchError):
                helper_call(target, {'state': 'new'}, old)
        self.assertEqual(target.read_bytes(), old)
        self.assertEqual(len(temp_siblings(root, target)), 1)


def _roles_with(new_role_file):
    roles = FakeRoles()
    roles.new_role_file = new_role_file
    return roles


class MeshLaunchTests(unittest.TestCase):
    def setUp(self):
        self.stack = tempfile.TemporaryDirectory(prefix='mesh-launch-')
        self.addCleanup(self.stack.cleanup)
        self.root = Path(self.stack.name).resolve(strict=True)
        self.profile = {
            'attemptPath': str(self.root / 'attempt.json'),
            'stdoutPath': str(self.root / 'stdout.log'),
            'stderrPath': str(self.root / 'stderr.log'),
            'schema': 'onoes-mesh-native-launch/v1',
            'nodeExecutable': 'synthetic-node',
            'settings': {'MESH_PREVIEW_PORT': '0'},
        }
        self.spawned = []
        self.stdin_fail = False
        self.profile_count = 0

    def fake_popen(self, *args, **kwargs):
        raw = Path(self.profile['attemptPath']).read_bytes()
        record = json.loads(raw)
        self.profile_count += 1
        self.assertEqual(self.profile_count, 1, 'Popen spawned more than once')
        self.assertEqual(record['schema'], 'onoes-mesh-native-reservation/v1')
        self.assertEqual(record['state'], 'launch_reserved')
        for key in ('pid', 'creationTicks', 'peers'):
            self.assertNotIn(key, record)
        self.assertNotIn('marker', raw.decode('utf-8'))
        for name in ('stdoutPath', 'stderrPath'):
            self.assertTrue(Path(self.profile[name]).is_file())
        child = FakeChild(self.stdin_fail)
        self.spawned.append(child)
        return child

    def synthetic_peers(self):
        return {
            'reader': {'pid': 1111, 'creationTicks': 222222, 'profileSha256': 'a' * 64},
            'writer': {'creationTicks': 333333, 'profileSha256': 'b' * 64},
        }

    def launch(self, *, frame=None, roles=None, peers=None):
        if frame is None:
            frame = {'marker': 'harmless-options-not-in-record'}
        if peers is None and self.profile['schema'] == 'onoes-mesh-native-launch/v2':
            peers = self.synthetic_peers()
        popen = mock.Mock(side_effect=self.fake_popen)
        with mock.patch.object(launch, 'checked_launch', return_value=(self.profile, roles or FakeRoles())), \
             mock.patch.object(launch, 'native_frame', return_value=frame), \
             mock.patch.object(launch, 'native_peers', return_value=peers), \
             mock.patch.object(launch, 'approved_environment', return_value={}), \
             mock.patch.object(launch.subprocess, 'Popen', popen):
            child, stamp, record = launch.launch_mesh('profile.json', 'sha', 'approval.json')
        return child, stamp, record

    def test_preflight_frame_failure_creates_nothing(self):
        with mock.patch.object(launch, 'checked_launch', return_value=(self.profile, FakeRoles())), \
             mock.patch.object(launch, 'native_frame', side_effect=launch.LaunchError('frame refused')), \
             mock.patch.object(launch, 'approved_environment', return_value={}), \
             mock.patch.object(launch.subprocess, 'Popen') as popen:
            with self.assertRaises(launch.LaunchError):
                launch.launch_mesh('profile.json', 'sha', 'approval.json')
        popen.assert_not_called()
        for name in ('attemptPath', 'stdoutPath', 'stderrPath'):
            self.assertFalse(Path(self.profile[name]).exists())

    def test_existing_attempt_blocks_second_spawn(self):
        self.launch()
        self.assertEqual(len(self.spawned), 1)
        with mock.patch.object(launch, 'checked_launch', return_value=(self.profile, FakeRoles())), \
             mock.patch.object(launch, 'native_frame', return_value={'marker': 'harmless'}), \
             mock.patch.object(launch, 'native_peers', return_value=None), \
             mock.patch.object(launch, 'approved_environment', return_value={}), \
             mock.patch.object(launch.subprocess, 'Popen') as popen:
            with self.assertRaises(FileExistsError):
                launch.launch_mesh('profile.json', 'sha', 'approval.json')
        popen.assert_not_called()
        self.assertEqual(len(self.spawned), 1)

    def test_successful_launch_input_sent(self):
        for schema in ('onoes-mesh-native-launch/v1', 'onoes-mesh-native-capture-launch/v1',
                       'onoes-mesh-native-launch/v2'):
            stack = tempfile.TemporaryDirectory(prefix='mesh-launch-mode-')
            self.addCleanup(stack.cleanup)
            root = Path(stack.name).resolve(strict=True)
            self.root = root
            self.profile = dict(self.profile,
                attemptPath=str(root / 'attempt.json'),
                stdoutPath=str(root / 'stdout.log'),
                stderrPath=str(root / 'stderr.log'),
                schema=schema)
            self.profile_count = 0
            self.spawned = []
            child, stamp, record = self.launch()
            self.assertEqual(stamp, 123456)
            self.assertEqual(len(child.stdin.writes), 1)
            self.assertTrue(child.stdin.closed)
            written = canonical(self, Path(self.profile['attemptPath']))
            self.assertEqual(written['state'], 'input_sent')
            self.assertEqual(written['creationTicks'], 123456)
            self.assertEqual(written['pid'], child.pid)
            self.assertEqual(record['state'], 'input_sent')
            if schema.endswith('capture-launch/v1'):
                self.assertEqual(written['schema'], 'onoes-mesh-native-child/v3')
                self.assertEqual(written['mode'], 'capture_only')
            elif schema.endswith('launch/v2'):
                self.assertEqual(written['schema'], 'onoes-mesh-native-child/v2')
                self.assertEqual(written['peers'], self.synthetic_peers())

    def test_creation_ticks_failure_identity_pending(self):
        roles = FakeRoles(creation_ticks_error=RuntimeError('ticks unavailable'))
        with self.assertRaises(RoleLaunchUnknown) as caught:
            self.launch(roles=roles)
        child = caught.exception.child
        self.assertIs(child, self.spawned[0])
        self.assertIsNone(caught.exception.creation_ticks)
        self.assertEqual(len(self.spawned), 1)
        written = canonical(self, Path(self.profile['attemptPath']))
        self.assertEqual(written['schema'], 'onoes-mesh-native-child/v1')
        self.assertEqual(written['state'], 'identity_pending')
        self.assertEqual(written['pid'], child.pid)
        self.assertIsNone(written['creationTicks'])
        self.assertEqual(child.stdin.writes, [])
        self.assertTrue(child.stdin.closed)

    def test_stdin_write_failure_input_pending(self):
        self.stdin_fail = True
        roles = FakeRoles()
        with mock.patch.object(launch, 'checked_launch', return_value=(self.profile, roles)), \
             mock.patch.object(launch, 'native_frame', return_value={'marker': 'harmless'}), \
             mock.patch.object(launch, 'approved_environment', return_value={}), \
             mock.patch.object(launch.subprocess, 'Popen', side_effect=self.fake_popen):
            with self.assertRaises(RoleLaunchUnknown) as caught:
                launch.launch_mesh('profile.json', 'sha', 'approval.json')
        self.assertEqual(caught.exception.creation_ticks, 123456)
        self.assertIs(caught.exception.child, self.spawned[0])
        written = canonical(self, Path(self.profile['attemptPath']))
        self.assertEqual(written['state'], 'input_pending')
        self.assertEqual(written['creationTicks'], 123456)
        self.assertEqual(temp_siblings(self.root, Path(self.profile['attemptPath'])), [])

    def test_third_replace_failure_keeps_input_pending(self):
        target = Path(self.profile['attemptPath'])
        calls = {'n': 0}
        real_replace = os.replace

        def third_fails(src, dst):
            calls['n'] += 1
            if calls['n'] == 3:
                raise OSError('replace denied')
            real_replace(src, dst)

        with mock.patch.object(launch, 'checked_launch', return_value=(self.profile, FakeRoles())), \
             mock.patch.object(launch, 'native_frame', return_value={'marker': 'harmless'}), \
             mock.patch.object(launch, 'approved_environment', return_value={}), \
             mock.patch.object(launch.subprocess, 'Popen', side_effect=self.fake_popen), \
             mock.patch.object(launch.os, 'replace', side_effect=third_fails):
            with self.assertRaises(RoleLaunchUnknown) as caught:
                launch.launch_mesh('profile.json', 'sha', 'approval.json')
        self.assertIs(caught.exception.child, self.spawned[0])
        self.assertEqual(caught.exception.creation_ticks, 123456)
        written = canonical(self, target)
        self.assertEqual(written['state'], 'input_pending')
        self.assertEqual(written['creationTicks'], 123456)
        self.assertEqual(len(self.spawned[0].stdin.writes), 1)
        self.assertTrue(self.spawned[0].stdin.closed)
        self.assertEqual(calls['n'], 3)
        temps = temp_siblings(self.root, target)
        self.assertEqual(len(temps), 1)
        self.assertEqual(json.loads(temps[0].read_bytes())['state'], 'input_sent')


if __name__ == '__main__':
    unittest.main()
