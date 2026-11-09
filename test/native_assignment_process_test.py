import unittest
import threading
import sqlite3
from contextlib import contextmanager
from unittest.mock import patch
from types import SimpleNamespace
from integrations.native_assignment_process import AssignmentProcessScope, make_assignment_scope, observe_retirement, execution_is_closed, describe_profile


class FakeFence:
    def __init__(self, run, generation):
        self.run, self.generation = run, generation
        self.active = 0
        self.sealed = self.closed = False
        self.launches = 0
        self.terminated = False

    def popen(self, argv, **kwargs):
        self.launches += 1
        self.active = 1
        return SimpleNamespace(pid=123)

    def seal(self):
        self.sealed = True

    def snapshot(self):
        return dict(state='ended' if self.sealed and not self.active else 'held',
                    processTreeEnded=self.sealed and not self.active,
                    activeProcesses=self.active, terminationRequested=self.terminated,
                    writerQuiescence=False, runId=self.run, generation=self.generation)

    def close(self):
        if self.active:
            raise RuntimeError('live process')
        self.closed = True

    def terminate(self):
        self.active = 0
        self.terminated = True
        return self.snapshot()


class AssignmentProcessTests(unittest.TestCase):
    def scope(self, **changes):
        return AssignmentProcessScope(SimpleNamespace(profile_id='fixture',epoch=1),
            SimpleNamespace(session_id='local-fixture'),
            dict(admission_id='a'*32, generation=1, principal_id='fixture', **changes),
            fence_factory=FakeFence)

    def test_child_keeps_assignment_held_after_retirement_then_natural_end_is_cached(self):
        scope = self.scope()
        scope.popen(['synthetic'])
        held = scope.retire()
        self.assertFalse(held['processTreeEnded'])
        self.assertEqual(held['activeProcesses'], 1)
        self.assertFalse(scope.fence.closed)
        scope.fence.active = 0
        ended = scope.observe()
        self.assertTrue(ended['processTreeEnded'])
        self.assertTrue(scope.fence.closed)
        self.assertFalse(ended['writerQuiescence'])
        self.assertEqual(scope.observe(), ended)
        self.assertEqual(ended['admissionId'], 'a'*32)

    def test_duplicate_and_post_retirement_launches_never_create_another_root(self):
        scope = self.scope()
        scope.popen(['synthetic'])
        with self.assertRaises(RuntimeError):
            scope.popen(['duplicate'])
        scope.retire()
        with self.assertRaises(RuntimeError):
            scope.popen(['late'])
        self.assertEqual(scope.fence.launches, 1)
        scope.dispose()

    def test_retirement_before_delayed_factory_blocks_launch(self):
        scope = self.scope()
        scope.retire()
        with self.assertRaises(RuntimeError):
            scope.popen(['late-factory'])
        self.assertEqual(scope.fence.launches, 0)

    def test_failed_launch_does_not_become_positive_empty_job_evidence(self):
        scope = self.scope()
        def fail(*args, **kwargs):
            raise OSError('fixture launch failure')
        scope.fence.popen = fail
        with self.assertRaises(OSError):
            scope.popen(['synthetic'])
        self.assertEqual(scope.retire()['state'], 'unknown')
        self.assertFalse(scope.observe()['processTreeEnded'])
        scope.dispose()

    def test_retirement_serializes_with_factory_already_launching(self):
        scope = self.scope()
        entered, release, retired = threading.Event(), threading.Event(), threading.Event()
        original = scope.fence.popen
        def delayed(*args, **kwargs):
            entered.set()
            if not release.wait(2):
                raise RuntimeError('fixture release missing')
            return original(*args, **kwargs)
        scope.fence.popen = delayed
        launch = threading.Thread(target=lambda: scope.popen(['synthetic']))
        launch.start()
        self.assertTrue(entered.wait(2))
        retirement = threading.Thread(target=lambda: (scope.retire(), retired.set()))
        retirement.start()
        self.assertFalse(retired.is_set())
        release.set()
        launch.join(2)
        retirement.join(2)
        self.assertTrue(retired.is_set())
        self.assertTrue(scope.observe()['assignmentLaunchSealed'])
        self.assertFalse(scope.observe()['processTreeEnded'])
        with self.assertRaises(RuntimeError):
            scope.popen(['late'])
        scope.dispose()

    def test_unenrolled_owner_does_not_create_a_scope(self):
        authority = SimpleNamespace()
        with patch.dict('os.environ', {}, clear=True):
            self.assertIsNone(make_assignment_scope(authority, None, {}))
        self.assertFalse(hasattr(authority, '_mesh_assignment_processes'))

    def test_explicit_shutdown_retains_termination_and_never_clears_writer(self):
        scope = self.scope()
        scope.popen(['synthetic'])
        ended = scope.dispose()
        self.assertTrue(ended['terminationRequested'])
        self.assertFalse(ended['writerQuiescence'])


class RetirementObservationTests(unittest.IsolatedAsyncioTestCase):
    async def test_pending_write_is_passive_and_does_not_read_or_interrupt(self):
        called = []
        scope = SimpleNamespace(identity={'authorityEpoch':1})
        result = await observe_retirement(None, scope,
            runtime_status=lambda _:dict(authority_writes_drained=False,worker_resources_idle=True),
            read_closed=lambda *_:called.append('read'))
        self.assertFalse(result['authority_writes_drained'])
        self.assertFalse(result['execution_closed'])
        self.assertEqual(called, [])

    async def test_runtime_is_sampled_again_after_closed_execution_read(self):
        samples = iter([dict(authority_writes_drained=True,worker_resources_idle=True),
                        dict(authority_writes_drained=False,worker_resources_idle=True)])
        result = await observe_retirement(None,SimpleNamespace(identity={'authorityEpoch':1}),
            runtime_status=lambda _:next(samples),read_closed=lambda *_:True)
        self.assertTrue(result['execution_closed'])
        self.assertFalse(result['authority_writes_drained'])

    async def test_exact_terminal_execution_and_children_are_required(self):
        conn = sqlite3.connect(':memory:')
        conn.executescript('CREATE TABLE session_admissions(admission_id,status,owner_epoch,generation,target_session_id,principal_id);'
            'CREATE TABLE worker_executions(execution_id,status,owner_epoch,generation);')
        admission = 'a'*32
        conn.execute('INSERT INTO session_admissions VALUES(?,?,?,?,?,?)',(admission,'terminal',1,1,'local-fixture','fixture'))
        execution = 'admission-worker:'+admission
        conn.execute('INSERT INTO worker_executions VALUES(?,?,?,?)',(execution,'terminal',1,1))
        @contextmanager
        def read():
            yield conn
        authority = SimpleNamespace(epoch=1,db=SimpleNamespace(_read_ctx=read))
        identity = dict(authorityEpoch=1,admissionId=admission,sessionId='local-fixture',principalId='fixture',executionGeneration=1)
        self.assertTrue(execution_is_closed(authority,identity))
        conn.execute('INSERT INTO worker_executions VALUES(?,?,?,?)',(execution+'/child:one','active',1,1))
        self.assertFalse(execution_is_closed(authority,identity))
        conn.execute("UPDATE worker_executions SET status='terminal'")
        self.assertTrue(execution_is_closed(authority,identity))
        self.assertFalse(execution_is_closed(authority,{**identity,'authorityEpoch':2}))
        conn.close()


class FrozenProfileTests(unittest.TestCase):
    def test_public_contract_is_closed_and_never_exports_keys(self):
        policy=SimpleNamespace(model='synthetic',provider='custom',base_url='http://127.0.0.1:9/v1',cwd='D:/fixture',
            toolsets=('file','terminal'),terminal_json='{"backend":"local","api_key":"DO_NOT_EXPORT"}',
            safe_mode=True,ignore_user_config=True,follows_profile=False,source='tool',max_turns=50,
            editor_mcp_json=None,kanban_json=None,client_env_remote=False,skills_prompt=None)
        contract=describe_profile(policy)
        self.assertTrue(contract['closed'])
        self.assertNotIn('DO_NOT_EXPORT',str(contract))
        policy.follows_profile=True
        self.assertFalse(describe_profile(policy)['closed'])
        policy.base_url='http://user:secret@127.0.0.1:9/v1'
        self.assertIsNone(describe_profile(policy))


if __name__ == '__main__':
    unittest.main()
