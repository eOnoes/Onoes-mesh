"""Task-layer tests use synthetic backends and disposable files, no model or service."""
from pathlib import Path
import copy
import hashlib
import importlib.util
import json
import tempfile
import unittest
import os
import sys
import subprocess

source = Path(__file__).resolve().parents[1] / 'integrations/local_worker_candidate.py'
spec = importlib.util.spec_from_file_location('local_worker_under_test', source)
w = importlib.util.module_from_spec(spec)
spec.loader.exec_module(w)


class WorkerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='mesh-worker-test-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.source = self.root / 'source'
        self.runs = self.root / 'runs'
        self.home = self.root / 'dsh-home'
        for p in (self.source, self.runs, self.home):
            p.mkdir()
        (self.source / 'guide.md').write_bytes(b'old\r\nHISTORY\r\npreserve  me\r\n')
        (self.source / 'context.txt').write_bytes(b'Context stays unchanged.')
        stub = self.root / 'pinned.txt'
        stub.write_bytes(b'Owned synthetic pin; never executed.')
        pin = dict(path=str(stub), sha256=w.sha(stub.read_bytes()))
        helper = source.with_name('local_worker_checks.py')
        self.runtime = dict(schema='onoes-local-worker-runtime/v1', profile='mesh-qwen-worker',
                            provider='ustrata-flash', model='qwen3.8-flash-next-iq3-s',
                            node=pin, cli=pin, guard=pin, route_probe=pin, route_helper=pin, profile_patch=pin,
                            checks=dict(path=str(helper), sha256=w.sha(helper.read_bytes())),
                            source_root=str(self.source), run_root=str(self.runs), dsh_home=str(self.home))
        self.task = dict(schema='onoes-local-worker-task/v1', id='sample-task', instruction='Replace old with Ready.',
                         allowed_files=['guide.md'], context_files=['context.txt'], repairs=1,
                         checks=[dict(type='text_contains', path='guide.md', fragments=['Ready']),
                                 dict(type='preserve_suffix', path='guide.md', marker='HISTORY')])
        self.rp, self.tp = self.root / 'runtime.json', self.root / 'task.json'

    def prepare(self):
        self.rp.write_text(json.dumps(self.runtime), encoding='utf-8')
        self.tp.write_text(json.dumps(self.task), encoding='utf-8')
        return w.sha(self.rp.read_bytes())

    def run_case(self, backend, preflight=None):
        return w.run_task(self.tp, self.rp, self.prepare(), backend=backend,
                          preflight=preflight or (lambda r: dict(loaded=True, busy=False, model=r['model'], provider=r['provider'])))

    @staticmethod
    def answer():
        return dict(exitCode=0, tools=2, seconds=.01, timeout=False, stopReason=None)

    def success(self, runtime, workspace, evidence, prompt, attempt):
        self.assertIn('Fixed acceptance checks:', prompt)
        p = workspace / 'guide.md'
        p.write_bytes(p.read_bytes().replace(b'old', b'Ready'))
        return self.answer()

    def test_candidate_ready_without_changing_source(self):
        before = (self.source / 'guide.md').read_bytes()
        result = self.run_case(self.success)
        self.assertEqual(result['status'], 'READY_FOR_REVIEW')
        self.assertEqual(result['modelTasks'], 1)
        self.assertFalse(result['sourceApplied'])
        self.assertFalse(result['functionalCodeTestsRun'])
        self.assertEqual((self.source / 'guide.md').read_bytes(), before)
        self.assertIn('+Ready', (self.runs / 'sample-task/review.patch').read_text())
        self.assertFalse((self.runs / 'WORKER.lock').exists())

    def test_one_focused_repair_after_a_real_failed_check(self):
        calls = []
        def backend(r, workspace, evidence, prompt, n):
            calls.append(n)
            if n == 2:
                self.assertIn('One admitted focused repair', prompt)
                self.assertIn('required literal fragment missing', prompt)
                return self.success(r, workspace, evidence, prompt, n)
            return self.answer()
        result = self.run_case(backend)
        self.assertEqual(calls, [1, 2])
        self.assertEqual(result['status'], 'READY_FOR_REVIEW')
        self.assertFalse(json.loads((self.runs / 'sample-task/check-1.json').read_bytes())['passed'])

    def test_two_misses_are_terminal_no_third_attempt(self):
        calls = []
        def miss(*args):
            calls.append(args[-1])
            return self.answer()
        result = self.run_case(miss)
        self.assertEqual(result['status'], 'CHECKS_FAILED')
        self.assertEqual(calls, [1, 2])

    def test_no_repair_when_task_admits_zero(self):
        self.task['repairs'] = 0
        result = self.run_case(lambda *args: self.answer())
        self.assertEqual(result['modelTasks'], 1)
        self.assertEqual(result['status'], 'CHECKS_FAILED')

    def test_guard_stop_never_retries_and_keeps_lease(self):
        calls = []
        def stop(*args):
            calls.append(args[-1])
            return dict(exitCode=124, stopReason='tool-call limit reached', timeout=False)
        with self.assertRaises(w.WorkerHeld):
            self.run_case(stop)
        self.assertEqual(calls, [1])
        self.assertTrue((self.runs / 'WORKER.lock').exists())
        self.assertTrue((self.runs / 'sample-task/HELD.json').is_file())

    def test_context_write_is_held_without_source_mutation(self):
        def bad(r, workspace, evidence, prompt, n):
            (workspace / 'context.txt').write_bytes(b'bad')
            return self.answer()
        with self.assertRaisesRegex(w.WorkerHeld, 'context or unlisted'):
            self.run_case(bad)
        self.assertEqual((self.source / 'context.txt').read_bytes(), b'Context stays unchanged.')

    def test_extra_file_is_held(self):
        def bad(r, workspace, *args):
            (workspace / 'other.txt').write_bytes(b'bad')
            return self.answer()
        with self.assertRaises(w.WorkerHeld):
            self.run_case(bad)

    def test_used_task_id_does_not_replay_or_modify_evidence(self):
        self.run_case(self.success)
        original = (self.runs / 'sample-task/RESULT.json').read_bytes()
        with self.assertRaisesRegex(w.WorkerHeld, 'no replay'):
            self.run_case(lambda *args: self.fail('Replayed task'))
        self.assertEqual((self.runs / 'sample-task/RESULT.json').read_bytes(), original)
        self.assertFalse((self.runs / 'WORKER.lock').exists())

    def test_cli_preview_refuses_used_id_without_new_artifacts(self):
        self.run_case(self.success)
        original = (self.runs / 'sample-task/RESULT.json').read_bytes()
        result = subprocess.run([sys.executable, '-I', '-B', str(source), 'preview', '--task', str(self.tp),
                                 '--runtime', str(self.rp), '--runtime-sha256', w.sha(self.rp.read_bytes())],
                                capture_output=True, text=True, timeout=10,
                                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        self.assertEqual(result.returncode, 3)
        self.assertIn('no replay', json.loads(result.stdout)['reason'])
        self.assertEqual((self.runs / 'sample-task/RESULT.json').read_bytes(), original)
        self.assertFalse((self.runs / 'WORKER.lock').exists())

    def test_stale_lease_is_not_inferred_safe_to_remove(self):
        (self.runs / 'WORKER.lock').write_bytes(b'Unknown original actor')
        with self.assertRaisesRegex(w.WorkerHeld, 'lease exists'):
            self.run_case(lambda *args: self.fail('Replayed stale lease'))
        self.assertEqual((self.runs / 'WORKER.lock').read_bytes(), b'Unknown original actor')
        self.assertFalse((self.runs / 'sample-task').exists())

    def test_pinned_runtime_tamper_refuses_before_backend(self):
        expected = self.prepare()
        (self.root / 'pinned.txt').write_bytes(b'changed')
        with self.assertRaisesRegex(w.WorkerHeld, 'Pinned runtime'):
            w.run_task(self.tp, self.rp, expected, backend=lambda *args: self.fail('Ran changed runtime'))
        self.assertFalse((self.runs / 'WORKER.lock').exists())

    def test_offline_preflight_starts_nothing_and_leaves_no_lease(self):
        def offline(r):
            raise w.WorkerHeld('Offline')
        with self.assertRaisesRegex(w.WorkerHeld, 'Offline'):
            self.run_case(lambda *args: self.fail('Started offline model'), preflight=offline)
        self.assertFalse((self.runs / 'WORKER.lock').exists())
        self.assertFalse((self.runs / 'sample-task').exists())

    def test_source_change_during_task_holds_without_overwriting_it(self):
        def changed(r, workspace, evidence, prompt, n):
            self.success(r, workspace, evidence, prompt, n)
            (self.source / 'guide.md').write_bytes(b'Other editor changed source')
            return self.answer()
        with self.assertRaisesRegex(w.WorkerHeld, 'Source changed'):
            self.run_case(changed)
        self.assertEqual((self.source / 'guide.md').read_bytes(), b'Other editor changed source')

    def test_traversal_hidden_and_absolute_paths_refused(self):
        for name in ['../x', '/x', 'C:/x', 'a\\x', '.env', 'data/private.json', 'Data/private.json', 'NODE_MODULES/x', 'a/.git/config']:
            with self.subTest(name=name), self.assertRaises(w.WorkerHeld):
                w.relative(name)

    def test_task_cannot_add_command_checker_or_extra_retries(self):
        for changes in [dict(checks=[dict(type='command', path='guide.md')]), dict(repairs=2), dict(repairs=True)]:
            saved = copy.deepcopy(self.task)
            self.task.update(changes)
            with self.assertRaises(w.WorkerHeld):
                self.run_case(lambda *args: self.fail('Invalid task ran'))
            self.task = saved

    def test_duplicate_task_keys_and_nonfinite_numbers_refused(self):
        for raw in ['{"schema":1,"schema":2}', '{"n":NaN}']:
            p = self.root / 'invalid.json'
            p.write_text(raw)
            with self.assertRaises((w.WorkerHeld, ValueError)):
                w.read_json(p)

    def test_binary_source_refused_before_preflight_or_run(self):
        (self.source / 'context.txt').write_bytes(b'\xff\xfe')
        with self.assertRaisesRegex(w.WorkerHeld, 'UTF-8 text'):
            self.run_case(lambda *args: self.fail('Binary task ran'),
                          preflight=lambda *args: self.fail('Binary input reached preflight'))
        self.assertFalse((self.runs / 'WORKER.lock').exists())

    def fake_cli(self, body):
        p = self.root / 'fake-cli.py'
        p.write_text(body, encoding='utf-8')
        guard = Path(os.environ['MESH_LOCAL_WORKER_GUARD_SOURCE']).resolve(strict=True)
        runtime = {**self.runtime, 'task_allowed_files': ['guide.md'],
                   'task_selected_files': ['guide.md', 'context.txt'],
                   'node': dict(path=sys.executable, sha256=w.sha(Path(sys.executable).read_bytes())),
                   'cli': dict(path=str(p), sha256=w.sha(p.read_bytes())),
                   'guard': dict(path=str(guard), sha256=w.sha(guard.read_bytes()))}
        workspace, evidence = self.root / 'fake-workspace', self.root / 'fake-evidence'
        workspace.mkdir(); evidence.mkdir()
        return runtime, workspace, evidence

    @unittest.skipUnless(os.name == 'nt' and os.environ.get('MESH_LOCAL_WORKER_GUARD_SOURCE'), 'Supply existing Windows guard source for process integration')
    def test_actual_guard_stops_only_owned_fake_child_on_permission_error(self):
        body = '''import json,time
print(json.dumps({'type':'tool_call','callId':'one','tool':'edit','input':{'file_path':'guide.md'}}),flush=True)
print(json.dumps({'type':'tool_result','callId':'one','status':'failed','result':'EPERM permission denied'}),flush=True)
time.sleep(15)
'''
        runtime, workspace, evidence = self.fake_cli(body)
        answer = w.call_dsh(runtime, workspace, evidence, 'Synthetic guard fixture; no model', 1)
        self.assertEqual(answer['exitCode'], 124)
        self.assertEqual(answer['stopReason'], 'tool infrastructure or permission failure')
        self.assertLess(answer['seconds'], 10)

    @unittest.skipUnless(os.name == 'nt' and os.environ.get('MESH_LOCAL_WORKER_GUARD_SOURCE'), 'Supply existing Windows guard source for process integration')
    def test_terminal_tail_event_is_checked_after_fast_child_exit(self):
        body = "import json\nprint(json.dumps({'type':'tool_call','callId':'last','tool':'pwsh','input':{}}),flush=True)\n"
        runtime, workspace, evidence = self.fake_cli(body)
        answer = w.call_dsh(runtime, workspace, evidence, 'No model', 1)
        self.assertEqual(answer['stopReason'], 'unexpected tool in file-only worker')
        self.assertEqual(answer['tools'], 1)

    @unittest.skipUnless(os.name == 'nt' and os.environ.get('MESH_LOCAL_WORKER_GUARD_SOURCE'), 'Supply existing Windows guard source for process integration')
    def test_context_write_attempt_is_flagged_even_without_final_file_change(self):
        body = "import json\nprint(json.dumps({'type':'tool_call','callId':'bad','tool':'write','input':{'file_path':'context.txt'}}),flush=True)\n"
        runtime, workspace, evidence = self.fake_cli(body)
        answer = w.call_dsh(runtime, workspace, evidence, 'No model', 1)
        self.assertEqual(answer['stopReason'], 'file access outside admitted task files')


if __name__ == '__main__':
    unittest.main(verbosity=2)
