"""Diagnostics-focused tests for the existing worker: malformed file-tool calls,
admitted path decisions and the actual per-attempt tool-budget prompt. No model,
node, subprocess, registry or network is ever invoked."""
from pathlib import Path
import importlib.util
import json
import tempfile
import unittest

source = Path(__file__).resolve().parents[1] / 'integrations/local_worker_candidate.py'
spec = importlib.util.spec_from_file_location('local_worker_diagnostics_under_test', source)
w = importlib.util.module_from_spec(spec)
spec.loader.exec_module(w)

MALFORMED = 'malformed file tool arguments'
OUTSIDE = 'file access outside admitted task files'


class DiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='mesh-worker-diag-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.workspace = self.root / 'workspace'
        self.workspace.mkdir()
        (self.workspace / 'guide.md').write_bytes(b'old\n')
        (self.workspace / 'context.txt').write_bytes(b'Context stays unchanged.')
        self.allowed = {'guide.md'}
        self.readable = {'guide.md', 'context.txt'}

    def call(self, tool, file_path=None, input_value='sentinel'):
        if input_value == 'sentinel':
            payload = {'file_path': file_path}
        else:
            payload = input_value
        return dict(type='tool_call', callId='one', tool=tool, input=payload)

    def reason(self, row):
        return w.file_tool_stop_reason(row, self.workspace, self.allowed, self.readable)

    def test_malformed_file_tool_arguments(self):
        cases = [
            self.call('edit', input_value={}),                    # observed run007 empty input
            self.call('edit', input_value=None),                  # absent input
            self.call('write', input_value=['guide.md']),         # non-dict input
            self.call('read', input_value='guide.md'),            # non-dict input
            dict(type='tool_call', callId='one', tool='edit'),    # no input key at all
            self.call('edit', file_path=None),                    # missing file_path value
            self.call('write', file_path=7),                      # numeric path
            self.call('edit', file_path='   '),                   # blank path
            self.call('edit', file_path=''),                      # empty path
        ]
        for row in cases:
            self.assertEqual(self.reason(row), MALFORMED, row)

    def test_valid_admitted_relative_and_absolute_paths(self):
        self.assertIsNone(self.reason(self.call('edit', 'guide.md')))
        self.assertIsNone(self.reason(self.call('write', 'guide.md')))
        self.assertIsNone(self.reason(self.call('read', 'guide.md')))
        self.assertIsNone(self.reason(self.call('read', str(self.workspace / 'guide.md'))))
        self.assertIsNone(self.reason(self.call('read', str(self.workspace / 'context.txt'))))
        # Admission intentionally casefolds, so GUIDE.MD resolves onto the admitted guide.md.
        self.assertIsNone(self.reason(self.call('read', 'GUIDE.MD')))

    def test_unlisted_parent_and_context_edits_stay_stopped(self):
        self.assertEqual(self.reason(self.call('read', 'unlisted.txt')), OUTSIDE)
        self.assertEqual(self.reason(self.call('edit', '../outside.txt')), OUTSIDE)
        self.assertEqual(self.reason(self.call('read', 'missing/../context.txt/../unlisted.txt')), OUTSIDE)
        self.assertEqual(self.reason(self.call('edit', str(self.root / 'pinned-outside.txt'))), OUTSIDE)
        self.assertEqual(self.reason(self.call('edit', 'context.txt')), OUTSIDE)
        self.assertEqual(self.reason(self.call('write', 'context.txt')), OUTSIDE)

    def test_admitted_context_reads_allowed(self):
        self.assertIsNone(self.reason(self.call('read', 'context.txt')))

    def test_unrelated_events_defer_to_run_guard(self):
        self.assertIsNone(self.reason(dict(type='tool_call', callId='one', tool='pwsh', input={})))
        self.assertIsNone(self.reason(dict(type='tool_result', callId='one', tool='edit',
                                           input={'file_path': 'nope'})))
        self.assertIsNone(self.reason(dict(type='assistant', text='hi')))
        # A file-tool call with input=None is malformed under the contract, not unrelated.
        self.assertEqual(self.reason(dict(type='tool_call', callId='one', tool='read', input=None)), MALFORMED)

    def pinned(self, path):
        return dict(path=str(path), sha256=w.sha(path.read_bytes()))

    def test_call_dsh_prompt_carries_actual_tool_budget(self):
        pin = self.root / 'pinned.txt'
        pin.write_bytes(b'Owned synthetic pin; never executed.')
        runtime = dict(schema='onoes-local-worker-runtime/v1', profile='mesh-qwen-worker',
                       provider='ustrata-flash', model='qwen3.8-flash-next-iq3-s',
                       node=self.pinned(pin), cli=self.pinned(pin), guard=self.pinned(pin),
                       route_probe=self.pinned(pin), route_helper=self.pinned(pin),
                       profile_patch=self.pinned(pin), checks=self.pinned(pin),
                       source_root=str(self.root / 'source'), run_root=str(self.root / 'runs'),
                       dsh_home=str(self.root / 'dsh-home'),
                       task_allowed_files=['guide.md'], task_selected_files=['guide.md', 'context.txt'])

        class FakeGuard:
            def __init__(self, max_tools, edit_only):
                self.calls = {}

            def observe(self, row):
                return None

        class FakeJob:
            def __init__(self, child):
                pass

            def close(self):
                pass

            def terminate(self):
                pass

        class FakeChild:
            pid = 4242
            returncode = 0

            def poll(self):
                return 0

            def wait(self, timeout=None):
                return 0

        class FakePopen:
            captured = []

            def __init__(self, argv, **kwargs):
                FakePopen.captured.append(argv)
                self.pid = FakeChild.pid
                self.returncode = 0

            def poll(self):
                return 0

            def wait(self, timeout=None):
                return 0

        def fake_pinned(item):
            # Recording no-op: accepts a pin and returns the synthetic pin path without executing anything.
            fake_pinned.seen.append(item)
            return pin

        fake_pinned.seen = []
        fake_guard_module = type('FakeGuardModule', (), dict(RunGuard=FakeGuard, OwnedWindowsJob=FakeJob))
        evidence = self.root / 'evidence'
        evidence.mkdir()
        original = dict(node=w.pinned_file, module=w.module, popen=w.subprocess.Popen)
        w.pinned_file = fake_pinned
        w.module = lambda path, name: fake_guard_module
        w.subprocess.Popen = FakePopen
        try:
            answers = {}
            for attempt, (tools, seconds) in ((1, (12, 180)), (2, (8, 120))):
                answer = w.call_dsh(runtime, self.workspace, evidence, 'Base task prompt.\n', attempt)
                sent = FakePopen.captured[-1][-1]
                self.assertIn('Actual tool budget:', sent)
                self.assertIn(str(tools), sent)
                self.assertIn(str(seconds), sent)
                self.assertIn('read, write and edit', sent)
                self.assertTrue(sent.startswith('Base task prompt.'))
                receipt = json.loads((evidence / ('attempt-' + str(attempt) + '-owner.json')).read_bytes())
                self.assertEqual(receipt['maxTools'], tools)
                self.assertEqual(receipt['timeoutSeconds'], seconds)
                self.assertEqual(answer['stopReason'], None)
                answers[attempt] = answer
        finally:
            w.pinned_file = original['node']
            w.module = original['module']
            w.subprocess.Popen = original['popen']
        self.assertEqual(FakePopen.captured[0][:2], [str(pin), str(pin)])
        self.assertEqual(len(fake_pinned.seen), 14)  # 7 pinned runtime items re-verified per attempt x 2 attempts
        self.assertTrue(all(item['path'] == str(pin) for item in fake_pinned.seen))


if __name__ == '__main__':
    unittest.main(verbosity=2)
