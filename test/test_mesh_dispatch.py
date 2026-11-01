"""Native dispatcher regressions; every runner/Hermes subprocess is mocked."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import unittest
from unittest import mock

from tools import mesh_dispatch as dispatch


BUSY = ('Triggered job: Mesh manager (f46e2ca656b9)\n'
        '  Job is already being fired by the scheduler; not run again.\n')
RUNNING = ('Job is already running (a scheduler tick or another manual run is '
           'executing it); not started again.')
SUCCESS = 'Triggered job: Mesh manager (f46e2ca656b9)\n  Ran now: succeeded.\n'


class MeshDispatchTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='mesh-dispatch-test-')
        self.addCleanup(temporary.cleanup)
        self.repo = Path(temporary.name)
        self.folder = self.repo / '.runner' / 'fixture'
        self.folder.mkdir(parents=True)
        self.target = self.folder / 'DISPATCH.json'
        self.record = {'job': 'fixture', 'ended': 123, 'runnerExit': 5}
        self.env = {'PYTHONDONTWRITEBYTECODE': '1'}
        self.flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
        self.now = 0
        self.calls = []
        self.responses = []
        self.patch('REPO', self.repo)
        self.patch('FIRE_MAX_ATTEMPTS', 3)
        self.patch('FIRE_RETRY_SECONDS', 15)
        self.patch('FIRE_BUDGET_SECONDS', 100)
        self.run = self.patch('subprocess.run', side_effect=self.fake_cli)
        self.sleep = self.patch('time.sleep', side_effect=self.advance)
        self.patch('time.monotonic', side_effect=lambda: self.now)
        self.patch('time.time', side_effect=lambda: 1000 + self.now)

    def patch(self, name, *args, **kwargs):
        patcher = mock.patch('tools.mesh_dispatch.' + name, *args, **kwargs)
        self.addCleanup(patcher.stop)
        return patcher.start()

    def advance(self, seconds):
        self.now += seconds

    def receipt(self):
        return json.loads(self.target.read_text(encoding='utf-8'))

    def fake_cli(self, argv, **kwargs):
        self.assertEqual(argv, [str(dispatch.HERMES), 'cron', 'run', dispatch.MANAGER])
        self.assertEqual(kwargs['cwd'], self.repo)
        self.assertEqual(kwargs['env'], self.env)
        self.assertEqual(kwargs['stdin'], subprocess.DEVNULL)
        self.assertEqual(kwargs['creationflags'], self.flags)
        self.assertGreater(kwargs['timeout'], 0)
        event = self.receipt()['managerFire']
        self.assertTrue(event['pending'])
        self.assertEqual(event['status'], 'firing')
        self.assertEqual(event['attempts'][-1]['status'], 'firing')
        self.assertFalse((self.folder / 'dispatch.lock').exists())
        self.calls.append(event)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        code, stdout, stderr = response
        kwargs['stdout'].write(stdout.encode('utf-8'))
        kwargs['stderr'].write(stderr.encode('utf-8'))
        return subprocess.CompletedProcess(argv, code)

    def fire(self, responses):
        self.responses = list(responses)
        return dispatch.fire_completion(self.folder, self.target, self.record,
                                        self.env, self.flags)

    def test_success_is_durable_and_not_repeated(self):
        self.assertTrue(self.fire([(0, SUCCESS, '')]))
        record = self.receipt()
        self.assertEqual(record['managerFire']['status'], 'succeeded')
        self.assertFalse(record['managerFire']['pending'])
        self.assertEqual(record['managerFireExit'], 0)
        self.assertEqual(record['runnerExit'], 5)
        self.sleep.assert_not_called()
        self.run.assert_called_once()
        self.assertEqual((self.folder / 'manager-fire.stdout.log').read_text(), SUCCESS)
        self.assertFalse(self.target.with_suffix('.json.tmp').exists())

    def test_busy_manager_ends_then_followup_fire_succeeds(self):
        self.assertTrue(self.fire([(0, BUSY, ''), (0, BUSY, ''), (0, SUCCESS, '')]))
        event = self.receipt()['managerFire']
        self.assertEqual([a['status'] for a in event['attempts']],
                         ['busy', 'busy', 'succeeded'])
        self.assertFalse(event['pending'])
        self.assertEqual(self.sleep.call_args_list, [mock.call(15), mock.call(15)])
        # Before each follow-up, prior busy states remain in the durable receipt.
        self.assertEqual(self.calls[1]['attempts'][0]['status'], 'busy')
        self.assertEqual((self.folder / 'manager-fire.stdout.log').read_text(),
                         BUSY + BUSY + SUCCESS)

    def test_running_manager_on_stderr_is_retryable_even_with_nonzero_exit(self):
        self.assertTrue(self.fire([(1, '', '\x1b[33m' + RUNNING + '\x1b[0m'),
                                   (0, SUCCESS, '')]))
        self.assertEqual(self.receipt()['managerFire']['attempts'][0]['exit'], 1)

    def test_background_dispatch_is_success(self):
        self.assertTrue(self.fire([(0, 'Running in background (delegation fixture).', '')]))
        self.sleep.assert_not_called()

    def test_busy_budget_exhaustion_keeps_completion_pending(self):
        self.assertFalse(self.fire([(0, BUSY, '')] * 3))
        event = self.receipt()['managerFire']
        self.assertEqual(event['status'], 'exhausted')
        self.assertTrue(event['pending'])
        self.assertEqual(len(event['attempts']), 3)
        self.assertEqual(self.sleep.call_count, 2)

    def test_wall_budget_limits_wait_and_prevents_another_fire(self):
        self.patch('FIRE_BUDGET_SECONDS', 5)
        self.assertFalse(self.fire([(0, BUSY, '')]))
        self.sleep.assert_called_once_with(5)
        self.run.assert_called_once()
        self.assertEqual(self.run.call_args.kwargs['timeout'], 5)
        self.assertEqual(self.receipt()['managerFire']['status'], 'exhausted')

    def test_terminal_cli_failures_are_not_retried(self):
        cases = [(7, SUCCESS, 'fixture CLI failed'),
                 (0, 'Triggered job: Mesh\n  Ran now: failed.', ''),
                 (0, 'Job is paused/disabled; resume it before running.', ''),
                 (0, 'It will run on the next scheduler tick.', ''),
                 (0, '', '')]
        for response in cases:
            with self.subTest(response=response):
                self.run.reset_mock()
                self.assertFalse(self.fire([response]))
                event = self.receipt()['managerFire']
                self.assertEqual(event['status'], 'failed')
                self.assertTrue(event['pending'])
                self.run.assert_called_once()
        self.sleep.assert_not_called()

    def test_old_log_success_does_not_hide_new_failure(self):
        (self.folder / 'manager-fire.stdout.log').write_text(SUCCESS)
        self.assertFalse(self.fire([(0, 'Ran now: failed.', '')]))
        self.assertEqual(self.receipt()['managerFire']['status'], 'failed')

    def test_terminal_exceptions_are_recorded_and_not_retried(self):
        for error in (FileNotFoundError('fixture missing CLI'),
                      subprocess.TimeoutExpired('fixture Hermes', 100)):
            with self.subTest(error=error):
                self.run.reset_mock()
                self.assertFalse(self.fire([error]))
                event = self.receipt()['managerFire']
                self.assertEqual(event['status'], 'exception')
                self.assertTrue(event['pending'])
                self.assertIn(type(error).__name__, event['attempts'][0]['error'])
                self.run.assert_called_once()
        self.sleep.assert_not_called()

    def run_main(self, runner_result, fire_responses):
        self.responses = list(fire_responses)
        self.patch('sys.argv', ['mesh_dispatch.py', '--job', 'fixture',
                                '--idle', '60', '--wall', '900'])
        self.patch('psutil.Process', return_value=mock.Mock(create_time=lambda: 123))
        self.patch('os.environ', {'PYTHONPATH': 'fixture-remove', 'FIXTURE': 'keep'})
        self.env = {'FIXTURE': 'keep', 'PYTHONDONTWRITEBYTECODE': '1'}

        def runner_then_cli(argv, **kwargs):
            if argv[0] == str(dispatch.HERMES):
                return self.fake_cli(argv, **kwargs)
            self.assertEqual(argv, [dispatch.PYTHON, str(self.repo / 'tools/mesh_runner.py'),
                                   '--repo', str(self.repo), '--job', 'fixture',
                                   '--prompt-file', str(self.repo / 'jobs/fixture.md'),
                                   '--idle', '60', '--wall', '900', '--model', 'gpt-6.1-sol',
                                   '--effort', 'high', '--codex', str(dispatch.CODEX)])
            self.assertTrue((self.folder / 'dispatch.lock').exists())
            self.assertEqual(kwargs['creationflags'], self.flags)
            self.assertEqual(kwargs['stdin'], subprocess.DEVNULL)
            self.assertEqual(kwargs['cwd'], self.repo)
            self.assertEqual(kwargs['env'], self.env)
            self.assertNotIn('timeout', kwargs)  # Runner owns its existing clock.
            if isinstance(runner_result, Exception):
                raise runner_result
            return subprocess.CompletedProcess(argv, runner_result)

        self.run.side_effect = runner_then_cli
        dispatch.main()

    def test_main_preserves_runner_clock_worktree_lock_and_nonzero_completion(self):
        with self.assertRaises(SystemExit) as exited:
            self.run_main(5, [(0, BUSY, ''), (0, SUCCESS, '')])
        self.assertEqual(exited.exception.code, 5)
        record = self.receipt()
        self.assertEqual(record['runnerExit'], 5)
        self.assertIn('ended', record)
        self.assertEqual(record['managerFire']['status'], 'succeeded')
        self.assertFalse((self.folder / 'dispatch.lock').exists())

    def test_runner_exception_still_emits_completion_and_is_raised(self):
        with self.assertRaisesRegex(OSError, 'fixture runner failure'):
            self.run_main(OSError('fixture runner failure'), [(0, SUCCESS, '')])
        record = self.receipt()
        self.assertIn('OSError: fixture runner failure', record['runnerError'])
        self.assertIn('ended', record)
        self.assertEqual(record['managerFire']['status'], 'succeeded')
        self.assertFalse((self.folder / 'dispatch.lock').exists())

    def test_main_reports_undelivered_completion_as_nonzero(self):
        for code in (0, 5):
            with self.subTest(runner_exit=code):
                with self.assertRaisesRegex(SystemExit, 'Completion event remains pending'):
                    self.run_main(code, [(2, '', 'fixture failure')])
                self.assertTrue(self.receipt()['managerFire']['pending'])
                self.assertEqual(self.receipt()['managerFire']['status'], 'failed')

    def test_existing_single_job_lock_prevents_all_launches(self):
        lock = self.folder / 'dispatch.lock'
        lock.write_text('fixture')
        with self.assertRaisesRegex(SystemExit, 'already recorded'):
            self.run_main(0, [])
        self.run.assert_not_called()
        self.assertEqual(lock.read_text(), 'fixture')


class MeshDispatchProcessTests(unittest.TestCase):
    def run_process(self, runner_exit, notification='success', runner_error=False):
        # Execute the unchanged dispatcher source and its __main__ guard in a real
        # native Python process. Only runner/Hermes launches and retry sleep are mocked.
        with tempfile.TemporaryDirectory(prefix='mesh-dispatch-process-') as temporary:
            repo = Path(temporary)
            source = repo / 'tools' / 'mesh_dispatch.py'
            source.parent.mkdir()
            source.write_bytes(Path(dispatch.__file__).read_bytes())
            config = {'runnerExit': runner_exit, 'notification': notification,
                      'runnerError': runner_error, 'hermes': str(dispatch.HERMES),
                      'codex': str(dispatch.CODEX), 'manager': dispatch.MANAGER,
                      'busy': BUSY, 'success': SUCCESS}
            bootstrap = textwrap.dedent('''
                import json
                import os
                from pathlib import Path
                import runpy
                import subprocess
                import sys
                from unittest import mock
                import psutil

                source = Path(sys.argv[1]).resolve()
                config = json.loads(sys.argv[2])
                repo = source.parents[1]
                folder = repo / '.runner' / 'fixture'
                target = folder / 'DISPATCH.json'
                runner_seen = False
                fire_count = 0
                flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0

                def fake_boundary(argv, **kwargs):
                    global runner_seen, fire_count
                    record = json.loads(target.read_text(encoding='utf-8'))
                    assert record['pid'] == os.getpid()
                    assert record['created'] == psutil.Process().create_time()
                    assert kwargs['cwd'] == repo
                    assert kwargs['stdin'] == subprocess.DEVNULL
                    assert kwargs['creationflags'] == flags
                    assert 'PYTHONPATH' not in kwargs['env']
                    assert kwargs['env']['PYTHONDONTWRITEBYTECODE'] == '1'
                    if argv == [config['hermes'], 'cron', 'run', config['manager']]:
                        assert runner_seen
                        assert not (folder / 'dispatch.lock').exists()
                        assert 'ended' in record
                        if config['runnerError']:
                            assert 'OSError: fixture runner failure' in record['runnerError']
                        else:
                            assert record['runnerExit'] == config['runnerExit']
                        event = record['managerFire']
                        assert event['pending'] is True
                        assert event['status'] == 'firing'
                        assert event['attempts'][-1]['status'] == 'firing'
                        assert event['attempts'][-1]['number'] == fire_count + 1
                        assert 0 < kwargs['timeout'] <= 1800
                        fire_count += 1
                        if config['notification'] == 'failure':
                            code, output = 2, 'fixture notification failure'
                        elif fire_count == 1:
                            code, output = 0, config['busy']
                        else:
                            assert fire_count == 2
                            assert event['attempts'][0]['status'] == 'busy'
                            code, output = 0, config['success']
                        kwargs['stdout'].write(output.encode('utf-8'))
                        return subprocess.CompletedProcess(argv, code)
                    assert not runner_seen
                    assert argv == [sys.executable, str(repo / 'tools/mesh_runner.py'),
                                    '--repo', str(repo), '--job', 'fixture',
                                    '--prompt-file', str(repo / 'jobs/fixture.md'),
                                    '--idle', '60', '--wall', '900', '--model', 'gpt-6.1-sol',
                                    '--effort', 'high', '--codex', config['codex']]
                    assert record['argv'] == argv
                    assert record['manager'] == config['manager']
                    assert (folder / 'dispatch.lock').exists()
                    assert 'runnerExit' not in record
                    assert 'timeout' not in kwargs
                    runner_seen = True
                    if config['runnerError']:
                        raise OSError('fixture runner failure')
                    return subprocess.CompletedProcess(argv, config['runnerExit'])

                sys.argv = [str(source), '--job', 'fixture', '--idle', '60', '--wall', '900']
                with mock.patch('subprocess.run', side_effect=fake_boundary), \\
                        mock.patch('time.sleep'):
                    runpy.run_path(str(source), run_name='__main__')
            ''')
            process = subprocess.run(
                [sys.executable, '-c', bootstrap, str(source), json.dumps(config)],
                cwd=dispatch.REPO, env=os.environ.copy(), stdin=subprocess.DEVNULL,
                capture_output=True, text=True, timeout=30,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
            folder = repo / '.runner' / 'fixture'
            target = folder / 'DISPATCH.json'
            self.assertTrue(target.exists(), process.stderr)
            record = json.loads(target.read_text(encoding='utf-8'))
            self.assertFalse((folder / 'dispatch.lock').exists())
            self.assertFalse(target.with_suffix('.json.tmp').exists())
            self.assertIn('ended', record)
            return process, record, (folder / 'manager-fire.stdout.log').read_text()

    def assert_runner_exit(self, code):
        process, record, log = self.run_process(code)
        self.assertEqual(process.returncode, code, process.stderr)
        self.assertEqual(process.stderr, '')
        self.assertEqual(record['runnerExit'], code)
        self.assertEqual(record['managerFireExit'], 0)
        self.assertEqual(record['managerFire']['status'], 'succeeded')
        self.assertFalse(record['managerFire']['pending'])
        self.assertEqual([a['status'] for a in record['managerFire']['attempts']],
                         ['busy', 'succeeded'])
        self.assertEqual(log, BUSY + SUCCESS)

    def test_native_process_exit_0_after_durable_completion(self):
        self.assert_runner_exit(0)

    def test_native_process_exit_2_after_durable_completion(self):
        self.assert_runner_exit(2)

    def test_native_process_exit_3_after_durable_completion(self):
        self.assert_runner_exit(3)

    def test_native_process_exit_4_after_durable_completion(self):
        self.assert_runner_exit(4)

    def test_native_process_exit_5_after_durable_completion(self):
        self.assert_runner_exit(5)

    def test_native_notification_failure_remains_visible_and_pending(self):
        for code in (0, 5):
            with self.subTest(runner_exit=code):
                process, record, log = self.run_process(code, notification='failure')
                self.assertEqual(process.returncode, 1, process.stderr)
                self.assertIn('Completion event remains pending', process.stderr)
                self.assertEqual(record['runnerExit'], code)
                self.assertEqual(record['managerFire']['status'], 'failed')
                self.assertTrue(record['managerFire']['pending'])
                self.assertEqual(len(record['managerFire']['attempts']), 1)
                self.assertEqual(log, 'fixture notification failure')

    def test_native_runner_exception_delivers_then_remains_visible(self):
        process, record, log = self.run_process(0, runner_error=True)
        self.assertEqual(process.returncode, 1, process.stderr)
        self.assertIn('OSError: fixture runner failure', process.stderr)
        self.assertIn('OSError: fixture runner failure', record['runnerError'])
        self.assertNotIn('runnerExit', record)
        self.assertEqual(record['managerFire']['status'], 'succeeded')
        self.assertFalse(record['managerFire']['pending'])
        self.assertEqual(log, BUSY + SUCCESS)


if __name__ == '__main__':
    unittest.main()
