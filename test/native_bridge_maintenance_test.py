import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from integrations.native_bridge_maintenance import FILES, NEW_FILES, change_sources, checked_files


class NativeBridgeMaintenanceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.package = Path(self.temp.name) / 'package'
        self.target = Path(self.temp.name) / 'installed'
        self.before = {}
        entries = []
        for i, rel in enumerate(sorted(FILES)):
            before = None if rel in NEW_FILES else f'value = {i}\n'.encode()
            after = f'value = {i + 10}\n'.encode()
            for base, content in [(self.package / 'candidate', after),
                                  (self.package / 'baseline', before), (self.target, before)]:
                if content is not None:
                    path = base / rel
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(content)
            self.before[rel] = before
            sha = lambda value: hashlib.sha256(value).hexdigest() if value is not None else None
            entries.append({'relativePath': rel, 'before': sha(before), 'after': sha(after)})
        (self.package / 'manifest.json').write_text(json.dumps({'files': entries}))

    def snapshot(self):
        return {rel: (self.target / rel).read_bytes() if (self.target / rel).exists() else None
                for rel in FILES}

    def test_live_runtime_refusal_changes_no_source(self):
        def busy():
            raise RuntimeError('busy')
        with self.assertRaisesRegex(RuntimeError, 'busy'):
            change_sources(self.package, self.target, assert_stopped=busy)
        self.assertEqual(self.snapshot(), self.before)

    def test_apply_and_exact_rollback_preserve_original_bytes_and_absent_helpers(self):
        self.assertEqual(change_sources(self.package, self.target, assert_stopped=lambda: None)['files'], 7)
        self.assertNotEqual(self.snapshot(), self.before)
        change_sources(self.package, self.target, assert_stopped=lambda: None, rollback=True)
        self.assertEqual(self.snapshot(), self.before)

    def test_changed_package_refused_before_any_mutation(self):
        (self.package / 'candidate' / sorted(FILES)[-1]).write_text('value = 999\n')
        with self.assertRaisesRegex(RuntimeError, 'Prepared bridge'):
            change_sources(self.package, self.target, assert_stopped=lambda: None)
        self.assertEqual(self.snapshot(), self.before)

    def test_rollback_preserves_unexpected_edits_to_any_file(self):
        change_sources(self.package, self.target, assert_stopped=lambda: None)
        (self.target / sorted(FILES)[-1]).write_text('user_work = True\n')
        expected = self.snapshot()
        with self.assertRaisesRegex(RuntimeError, 'Installed source changed'):
            change_sources(self.package, self.target, assert_stopped=lambda: None, rollback=True)
        self.assertEqual(self.snapshot(), expected)

    def test_path_escape_manifest_refused(self):
        p = self.package / 'manifest.json'
        value = json.loads(p.read_text())
        value['files'][0]['relativePath'] = '../outside.py'
        p.write_text(json.dumps(value))
        with self.assertRaisesRegex(RuntimeError, 'Unexpected bridge manifest'):
            checked_files(self.package, self.target)

    def test_runtime_return_mid_install_stops_and_allows_later_stopped_rollback(self):
        calls = 0
        def becomes_busy():
            nonlocal calls
            calls += 1
            if calls == 3:
                raise RuntimeError('runtime returned')
        with self.assertRaisesRegex(RuntimeError, 'runtime returned'):
            change_sources(self.package, self.target, assert_stopped=becomes_busy)
        self.assertNotEqual(self.snapshot(), self.before)
        change_sources(self.package, self.target, assert_stopped=lambda: None, rollback=True)
        self.assertEqual(self.snapshot(), self.before)

    def test_manifest_cannot_treat_an_original_file_as_removable_helper(self):
        p = self.package / 'manifest.json'
        value = json.loads(p.read_text())
        next(e for e in value['files'] if e['relativePath'] not in NEW_FILES)['before'] = None
        p.write_text(json.dumps(value))
        with self.assertRaisesRegex(RuntimeError, 'Only the two introduced helpers'):
            change_sources(self.package, self.target, assert_stopped=lambda: None, rollback=True)
        self.assertEqual(self.snapshot(), self.before)


if __name__ == '__main__':
    unittest.main()
