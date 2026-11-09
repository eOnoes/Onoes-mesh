import concurrent.futures
import asyncio
from contextvars import copy_context, ContextVar
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
import shutil
import sys
import tempfile
import threading
import types
import unittest
from unittest.mock import patch
from urllib.request import urlopen
from integrations import hermes_writer_scope as scope
from integrations.windows_writer_fence import WindowsWriterFence


class FakeFence:
    def __init__(self, name):
        self.name = name

    def popen(self, argv, **kwargs):
        return self.name, argv, kwargs


class HermesWriterScopeTests(unittest.TestCase):
    def test_overlapping_thread_contexts_cannot_swap_attempts_and_restore_on_error(self):
        barrier = threading.Barrier(2)
        def run(name):
            fence = FakeFence(name)
            with scope.bind_writer_fence(fence):
                barrier.wait(timeout=5)
                with self.assertRaises(RuntimeError):
                    with scope.bind_writer_fence(FakeFence('other')):
                        self.fail('Another attempt replaced this context')
                return scope.scoped_popen([sys.executable, '-c', 'pass'])[0]
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as workers:
            first = workers.submit(run, 'first')
            second = workers.submit(run, 'second')
            self.assertEqual(first.result(timeout=5), 'first')
            self.assertEqual(second.result(timeout=5), 'second')
        with self.assertRaises(ValueError):
            with scope.bind_writer_fence(FakeFence('temporary')):
                raise ValueError('fixture')
        scope.require_supported_writer_route(local=False)  # Parent context is restored.

    def test_fenced_failure_never_uses_unfenced_fallback_and_host_path_is_used(self):
        name = Path(sys.executable).name
        expected = str(Path(shutil.which(name)).resolve())
        with scope.bind_writer_fence(FakeFence('fixture')):
            result = scope.scoped_popen([name, '-c', 'pass'], env={'PATH': 'untrusted-child-path'})
            self.assertEqual(result[1][0], expected)
            self.assertEqual(result[2]['env']['PATH'], 'untrusted-child-path')
        fence = FakeFence('failed')
        with scope.bind_writer_fence(fence), patch.object(fence, 'popen', side_effect=RuntimeError('fixture')), \
                patch.object(scope.subprocess, 'Popen', side_effect=AssertionError('Unfenced fallback')):
            with self.assertRaises(RuntimeError):
                scope.scoped_popen([sys.executable, '-c', 'pass'])

    def test_unbound_legacy_call_keeps_original_arguments(self):
        argv = [sys.executable, '-c', 'pass']
        with patch.object(scope.subprocess, 'Popen', return_value='legacy') as launch:
            self.assertEqual(scope.scoped_popen(argv, stdout=-1), 'legacy')
            launch.assert_called_once_with(argv, stdout=-1)

    def test_unbound_submission_preserves_positional_and_keyword_arguments(self):
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = scope.submit_writer_work(pool, lambda value, *, suffix: value + suffix,
                                               None, 'legacy', suffix=' arguments')
            self.assertEqual(future.result(timeout=3), 'legacy arguments')

    def test_unbound_thread_keeps_original_target_and_identity(self):
        result=[]
        thread=threading.Thread(target=lambda:result.append('legacy'),name='legacy-title',daemon=True)
        scope.start_writer_observed_thread(thread);thread.join(timeout=3)
        self.assertEqual(result,['legacy']);self.assertEqual(thread.name,'legacy-title')


@unittest.skipUnless(sys.platform == 'win32', 'Real Windows job accounting required')
class ManagedWriterLifetimeTests(unittest.TestCase):
    def setUp(self):
        self.fence = WindowsWriterFence('lifetime-fixture', 'one')
        self.life = scope.WriterLifetime(self.fence)

    def tearDown(self):
        self.fence.terminate()
        self.fence.close()

    def test_cancelled_canonical_observer_cannot_settle_actual_thread(self):
        entered,release=threading.Event(),threading.Event()
        def worker():
            with scope.canonical_writer_foreground_scope():
                entered.set();release.wait(timeout=5)
        async def check():
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                with scope.bind_canonical_writer_claim(self.life):
                    context=copy_context()
                    future=pool.submit(context.run,worker)
                    observer=asyncio.wrap_future(future)
                    self.assertTrue(entered.wait(timeout=3))
                    observer.cancel()
                    await asyncio.sleep(0)
                # Leaving the asynchronous request context must not release root.
                held=self.life.snapshot()
                self.assertFalse(held['rootEnded']);self.assertFalse(held['managedWorkEnded'])
                release.set();future.result(timeout=3)
                self.assertTrue(self.life.wait()['managedWorkEnded'])
                self.assertFalse(self.life.snapshot()['writerQuiescence'])
        try:asyncio.run(check())
        finally:release.set()

    def test_unstarted_canonical_claim_and_duplicate_worker_remain_reserved(self):
        with scope.bind_canonical_writer_claim(self.life):
            with self.assertRaises(RuntimeError):
                with scope.bind_canonical_writer_claim(self.life):pass
        self.assertFalse(self.life.snapshot()['rootEnded'])
        with scope.bind_canonical_writer_claim(self.life):
            with scope.canonical_writer_foreground_scope():pass
            with self.assertRaises(RuntimeError):
                with scope.canonical_writer_foreground_scope():pass
        self.assertTrue(self.life.wait()['managedWorkEnded'])

    def test_http_acceptance_and_later_external_write_never_imply_effect_settlement(self):
        accepted, release, finished = threading.Event(), threading.Event(), threading.Event()
        with tempfile.TemporaryDirectory(prefix='mesh-external-effect-') as folder:
            marker = Path(folder) / 'synthetic-result.txt'
            class Handler(BaseHTTPRequestHandler):
                def do_POST(self):
                    self.send_response(202)
                    self.send_header('Content-Length', '0')
                    self.end_headers()
                    self.wfile.flush()
                    accepted.set()
                    if release.wait(timeout=5):
                        marker.write_text('synthetic external effect', encoding='utf-8')
                    finished.set()

                def log_message(self, *args):
                    pass

            server = HTTPServer(('127.0.0.1', 0), Handler)
            server.timeout = 3
            worker = threading.Thread(target=server.handle_request, daemon=True)
            worker.start()
            try:
                with scope.writer_foreground_scope(self.life):
                    with scope.writer_tool_effect():
                        with urlopen(f'http://127.0.0.1:{server.server_port}/', data=b'', timeout=3) as reply:
                            self.assertEqual(reply.status, 202)
                self.assertTrue(accepted.wait(timeout=3))
                self.assertFalse(marker.exists())
                before = self.life.wait(100)
                self.assertTrue(before['managedWorkEnded'])
                self.assertEqual(before['toolEffects']['activeCalls'], 0)
                self.assertEqual(before['toolEffects']['unverifiedCalls'], 1)
                self.assertFalse(before['toolEffects']['effectsSettled'])
                self.assertFalse(before['writerQuiescence'])
                release.set()
                self.assertTrue(finished.wait(timeout=3))
                worker.join(timeout=3)
                self.assertFalse(worker.is_alive())
                self.assertEqual(marker.read_text(encoding='utf-8'), 'synthetic external effect')
                # Even actual external completion is not a trusted adapter receipt.
                after = self.life.snapshot()
                self.assertFalse(after['toolEffects']['effectsSettled'])
                self.assertFalse(after['writerQuiescence'])
            finally:
                release.set()
                worker.join(timeout=6)
                server.server_close()

    def test_native_title_thread_holds_after_root_and_preserves_captured_profile(self):
        entered,release=threading.Event(),threading.Event();seen=[]
        profile=ContextVar('fixture_title_profile',default='wrong')
        def title():
            seen.append(profile.get());entered.set();release.wait(timeout=5)
        thread=None
        try:
            with scope.writer_foreground_scope(self.life):
                token=profile.set('original-profile');context=copy_context();profile.reset(token)
                thread=threading.Thread(target=lambda:context.run(title),name='native-title',daemon=True)
                scope.start_writer_observed_thread(thread)
                self.assertTrue(entered.wait(timeout=3))
            snapshot=self.life.wait(20)
            self.assertFalse(snapshot['managedWorkEnded']);self.assertFalse(self.fence.snapshot()['sealed'])
            self.assertEqual(snapshot['pendingWorkers'][0]['kind'],'background')
            release.set();thread.join(timeout=3)
            self.assertTrue(self.life.wait()['managedWorkEnded']);self.assertEqual(seen,['original-profile'])
            self.assertFalse(self.life.snapshot()['writerQuiescence'])
        finally:
            release.set()
            if thread is not None:thread.join(timeout=3)

    def test_uncertain_native_thread_start_stays_held_even_after_target_finishes(self):
        release=threading.Event();thread=threading.Thread(target=lambda:release.wait(timeout=5),daemon=True)
        original=thread.start
        def uncertain():
            original();raise RuntimeError('start failed after thread began')
        try:
            with scope.writer_foreground_scope(self.life),patch.object(thread,'start',side_effect=uncertain):
                with self.assertRaises(RuntimeError):scope.start_writer_observed_thread(thread)
            release.set();thread.join(timeout=3)
            snapshot=self.life.wait(20)
            self.assertFalse(snapshot['managedWorkEnded']);self.assertEqual(snapshot['pendingWorkers'][0]['state'],'unknown')
        finally:
            release.set()
            if thread.ident is not None:thread.join(timeout=3)

    def test_failed_thread_observer_cannot_release_a_running_native_callback(self):
        release=threading.Event();thread=threading.Thread(target=lambda:release.wait(timeout=5),name='native-title',daemon=True)
        original=threading.Thread.start
        def start(value):
            if value.name=='mesh-background-observer':raise RuntimeError('observer unavailable')
            return original(value)
        try:
            with scope.writer_foreground_scope(self.life),patch.object(threading.Thread,'start',start):
                with self.assertRaises(RuntimeError):scope.start_writer_observed_thread(thread)
            self.assertFalse(self.life.wait(20)['managedWorkEnded'])
            release.set();thread.join(timeout=3)
            self.assertEqual(self.life.snapshot()['pendingWorkers'][0]['state'],'unknown')
        finally:
            release.set()
            if thread.ident is not None:thread.join(timeout=3)

    def test_managed_submission_preserves_positional_and_keyword_arguments(self):
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            with scope.writer_foreground_scope(self.life):
                future = scope.submit_writer_work(pool, lambda value, *, suffix: value + suffix,
                                                   None, 'managed', suffix=' arguments')
                self.assertEqual(future.result(timeout=3), 'managed arguments')
            self.assertTrue(self.life.wait()['managedWorkEnded'])

    def test_tool_return_or_error_cannot_settle_unknown_external_effects(self):
        with scope.writer_foreground_scope(self.life):
            with scope.writer_tool_effect():
                self.assertEqual(self.life.snapshot()['toolEffects']['activeCalls'], 1)
            with self.assertRaises(ValueError):
                with scope.writer_tool_effect():
                    raise ValueError('External request outcome unknown')
        snapshot = self.life.wait()
        self.assertTrue(snapshot['managedWorkEnded'])
        self.assertEqual(snapshot['toolEffects']['unverifiedCalls'], 2)
        self.assertFalse(snapshot['toolEffects']['effectsSettled'])
        self.assertFalse(snapshot['writerQuiescence'])

    def test_tool_scope_rejects_stale_copied_context_before_body(self):
        with scope.writer_foreground_scope(self.life):
            copied = copy_context()
        def enter():
            with scope.writer_tool_effect():
                self.fail('Stale worker entered middleware')
        with self.assertRaises(RuntimeError):
            copied.run(enter)
        self.assertEqual(self.life.snapshot()['toolEffects']['observedCalls'], 0)

    def test_active_middleware_in_copied_context_keeps_root_from_sealing(self):
        entered, release = threading.Event(), threading.Event()
        def tool():
            with scope.writer_tool_effect():
                entered.set(); release.wait(timeout=5)
        worker = None
        try:
            with scope.writer_foreground_scope(self.life):
                context = copy_context()
                worker = threading.Thread(target=lambda: context.run(tool))
                worker.start()
                self.assertTrue(entered.wait(timeout=3))
            self.assertFalse(self.life.wait(20)['managedWorkEnded'])
            self.assertFalse(self.fence.snapshot()['sealed'])
            release.set(); worker.join(timeout=3)
            self.assertFalse(worker.is_alive())
            self.assertTrue(self.life.wait()['managedWorkEnded'])
            self.assertFalse(self.life.snapshot()['toolEffects']['effectsSettled'])
        finally:
            release.set()
            if worker is not None:
                worker.join(timeout=3)

    def test_parent_return_and_early_result_record_do_not_settle_running_delegate(self):
        started, delivery_recorded, release = threading.Event(), threading.Event(), threading.Event()
        def child():
            started.set()
            delivery_recorded.set()  # Native stale monitor can finalize a record early.
            release.wait(timeout=5)
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            try:
                with scope.writer_foreground_scope(self.life):
                    future = scope.submit_writer_work(pool, child)
                    self.assertTrue(started.wait(timeout=3))
                self.assertTrue(delivery_recorded.is_set())
                self.assertFalse(self.life.wait(20)['managedWorkEnded'])
                self.assertTrue(future.running())
                self.assertFalse(self.fence.snapshot()['sealed'])
                release.set(); future.result(timeout=3)
                self.assertTrue(self.life.wait()['managedWorkEnded'])
                self.assertFalse(self.life.snapshot()['writerQuiescence'])
            finally:
                release.set()

    def test_cancelled_queued_future_never_runs_and_does_not_leak_a_worker_ticket(self):
        occupied, release = threading.Event(), threading.Event()
        def occupy():
            occupied.set(); release.wait(timeout=5)
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            blocker = pool.submit(occupy)
            try:
                self.assertTrue(occupied.wait(timeout=3))
                with scope.writer_foreground_scope(self.life):
                    future = scope.submit_writer_work(pool, lambda: self.fail('Cancelled child ran'))
                    self.assertTrue(future.cancel())
                self.assertTrue(self.life.wait()['managedWorkEnded'])
            finally:
                release.set(); blocker.result(timeout=3)

    def test_submit_exception_after_start_stays_held_until_actual_callable_return(self):
        started, release = threading.Event(), threading.Event()
        def child():
            started.set(); release.wait(timeout=5)
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            class LostSubmit:
                def submit(_, fn):
                    pool.submit(fn)
                    if not started.wait(timeout=3):
                        raise AssertionError('Fixture worker did not start')
                    raise RuntimeError('Submission response lost')
            try:
                with scope.writer_foreground_scope(self.life):
                    with self.assertRaises(RuntimeError):
                        scope.submit_writer_work(LostSubmit(), child)
                self.assertFalse(self.life.wait(20)['managedWorkEnded'])
                release.set()
                self.assertTrue(self.life.wait()['managedWorkEnded'])
            finally:
                release.set()

    def test_unobserved_submit_failure_stays_unknown_instead_of_claiming_no_work(self):
        class UnknownSubmit:
            def submit(_, fn):
                raise RuntimeError('Unknown admission')
        with scope.writer_foreground_scope(self.life):
            with self.assertRaises(RuntimeError):
                scope.submit_writer_work(UnknownSubmit(), lambda: None)
        status = self.life.wait(20)
        self.assertFalse(status['managedWorkEnded'])
        self.assertEqual(status['pendingWorkers'][0]['state'], 'unknown')

    def test_copied_stale_context_cannot_start_another_writer_or_delegate(self):
        with scope.writer_foreground_scope(self.life):
            saved = copy_context()
        self.assertTrue(self.life.wait()['managedWorkEnded'])
        with patch.object(self.fence, 'popen', side_effect=AssertionError('Late process launched')):
            with self.assertRaises(RuntimeError):
                saved.run(scope.scoped_popen, [sys.executable, '-c', 'pass'])
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            with self.assertRaises(RuntimeError):
                saved.run(scope.submit_writer_work, pool, lambda: self.fail('Late delegate ran'))

    def test_wrong_native_run_or_generation_never_enters_the_worker(self):
        for run, generation in [('wrong-run', 'one'), ('lifetime-fixture', 'wrong-generation'), ('lifetime-fixture', '')]:
            with self.assertRaises(RuntimeError):
                with scope.writer_foreground_scope(self.life, expected_run_id=run, expected_generation=generation):
                    self.fail('Wrong attempt entered worker')
        self.assertFalse(self.life.snapshot()['rootEnded'])
        with scope.writer_foreground_scope(self.life, expected_run_id='lifetime-fixture', expected_generation='one'):
            pass
        self.assertTrue(self.life.wait()['managedWorkEnded'])

    def test_active_child_can_spawn_a_nested_worker_after_foreground_returns(self):
        enter, next_step, nested_started, release = [threading.Event() for _ in range(4)]
        results = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            def nested():
                nested_started.set(); release.wait(timeout=5)
                with scope.scoped_popen([sys.executable, '-c', 'print("nested output")'], text=True) as proc:
                    output, _ = proc.communicate(timeout=3)
                return output.strip()
            def child():
                enter.set(); next_step.wait(timeout=5)
                results.append(scope.submit_writer_work(pool, nested))
            try:
                with scope.writer_foreground_scope(self.life):
                    first = scope.submit_writer_work(pool, child)
                    self.assertTrue(enter.wait(timeout=3))
                next_step.set(); first.result(timeout=3)
                self.assertTrue(nested_started.wait(timeout=3))
                self.assertFalse(self.life.wait(20)['managedWorkEnded'])
                release.set()
                self.assertEqual(results[0].result(timeout=3), 'nested output')
                self.assertTrue(self.life.wait()['managedWorkEnded'])
                self.assertTrue(self.fence.snapshot()['processTreeEnded'])
            finally:
                next_step.set(); release.set()


class ManagedSessionOwnerTests(unittest.IsolatedAsyncioTestCase):
    def adapter(self, row):
        db=types.SimpleNamespace(get_session=lambda sid:row,db_path='fixture/state.db',get_compression_tip=lambda sid:'tip')
        async def database():return db
        return types.SimpleNamespace(_mesh_writer_runs=scope.WriterRunRegistry(lambda *args:None),
            _ensure_session_db_async=database,gateway_runner=None),db

    async def test_unconfigured_is_unchanged_and_invalid_registry_is_refused(self):
        await scope.require_managed_session_owner(types.SimpleNamespace(),'existing')
        with self.assertRaises(RuntimeError):
            await scope.require_managed_session_owner(types.SimpleNamespace(_mesh_writer_runs=object()),'existing')

    async def test_non_api_target_and_unavailable_database_are_refused(self):
        for source in ['bot_room','local','telegram','cli']:
            adapter,db=self.adapter({'source':source})
            with self.assertRaises(RuntimeError):await scope.require_managed_session_owner(adapter,'existing')
        adapter,db=self.adapter(None)
        async def missing():return None
        adapter._ensure_session_db_async=missing
        with self.assertRaises(RuntimeError):await scope.require_managed_session_owner(adapter,'existing')

    async def test_new_api_target_allowed_but_native_bot_identity_is_refused(self):
        adapter,db=self.adapter(None)
        await scope.require_managed_session_owner(adapter,'new')
        db.get_session=lambda sid:{'source':'api_server'}
        authorities=types.ModuleType('gateway.session_authorities');authorities.active_authority=lambda runner:object()
        bot=types.ModuleType('gateway.platforms.api_server_bot_chat');bot.bot_chat_tip=lambda *args:None
        with patch.dict(sys.modules,{'gateway.session_authorities':authorities,'gateway.platforms.api_server_bot_chat':bot}):
            await scope.require_managed_session_owner(adapter,'existing-api')
            bot.bot_chat_tip=lambda *args:{'session_id':'tip'}
            with self.assertRaises(RuntimeError):await scope.require_managed_session_owner(adapter,'existing-api')

    async def test_legacy_live_owner_refused_without_redirecting_another_api_chat(self):
        adapter,db=self.adapter({'source':'api_server'})
        authorities=types.ModuleType('gateway.session_authorities');authorities.active_authority=lambda runner:None
        live=types.ModuleType('tools.bot_live_delivery');live.find_canonical_live_owner=lambda home:{'session_id':'tip'}
        with patch.dict(sys.modules,{'gateway.session_authorities':authorities,'tools.bot_live_delivery':live}):
            with self.assertRaises(RuntimeError):await scope.require_managed_session_owner(adapter,'existing')
            db.get_compression_tip=lambda sid:'other-api-chat'
            await scope.require_managed_session_owner(adapter,'other')


class WriterRunEnrollmentTests(unittest.TestCase):
    def canonical_fixture(self):
        run_id='run_'+'a'*32
        row={'request_id':run_id,'admission_id':'admission-one','target_session_id':'session-one','principal_id':'api','owner_epoch':1,'generation':1,
             'status':'started','payload':{'api_turn_v1':{'run_owner_scope':'b'*64}}}
        stamp={'authority_epoch':1,'execution_generation':1,'admission_id':'admission-one'}
        live=types.SimpleNamespace(event_stream=types.SimpleNamespace(lock=threading.RLock(),execution=stamp))
        authority=types.SimpleNamespace(profile_id='profile-one',epoch=1,sessions={'session-one':live},executing={'session-one':1})
        ref=types.SimpleNamespace(profile_id='profile-one',session_id='session-one')
        fences=[]
        def factory(run_id,generation):
            fence=types.SimpleNamespace(run_id=run_id,generation=generation,popen=lambda *a,**k:None,
                seal=lambda:None,snapshot=lambda:{'state':'not_started','activeProcesses':0})
            fences.append(fence);return fence
        registry=scope.WriterRunRegistry(factory)
        adapter=types.SimpleNamespace(_mesh_writer_runs=registry)
        native=types.ModuleType('gateway.platforms.api_server_authority_runs')
        native.run_admission=lambda *args:(authority,dict(row))
        return authority,ref,row,adapter,native,fences

    def test_canonical_current_claim_enrolls_once_and_observer_exit_does_not_settle(self):
        authority,ref,row,adapter,native,fences=self.canonical_fixture()
        with patch.dict(sys.modules,{'gateway.platforms.api_server_authority_runs':native}):
            with scope.canonical_admission_writer_scope(authority,ref,row,adapter):
                held=adapter._mesh_writer_runs.snapshot(row['request_id'])
                self.assertFalse(held['lifetime']['rootEnded'])
                with scope.canonical_writer_foreground_scope():pass
            result=adapter._mesh_writer_runs.snapshot(row['request_id'])
            self.assertTrue(result['lifetime']['managedWorkEnded']);self.assertFalse(result['writerQuiescence'])
            with self.assertRaises(RuntimeError):
                with scope.canonical_admission_writer_scope(authority,ref,row,adapter):pass
        self.assertEqual(len(fences),1)

    def test_canonical_wrong_epoch_generation_profile_and_saved_row_create_no_worker(self):
        changes=[lambda a,r,row,n:setattr(a,'epoch','other'),
                 lambda a,r,row,n:setattr(r,'profile_id','other'),
                 lambda a,r,row,n:row.update(status='queued'),
                 lambda a,r,row,n:row.update(owner_epoch=2),
                 lambda a,r,row,n:row.update(principal_id='other'),
                 lambda a,r,row,n:row.update(generation=2),
                 lambda a,r,row,n:a.sessions[r.session_id].event_stream.execution.update(admission_id='other'),
                 lambda a,r,row,n:setattr(n,'run_admission',lambda *args:None),
                 lambda a,r,row,n:setattr(n,'run_admission',lambda *args:(a,{**row,'admission_id':'other'})),
                 lambda a,r,row,n:setattr(n,'run_admission',lambda *args:(object(),row))]
        for change in changes:
            authority,ref,row,adapter,native,fences=self.canonical_fixture();change(authority,ref,row,native)
            with patch.dict(sys.modules,{'gateway.platforms.api_server_authority_runs':native}):
                with self.assertRaises(RuntimeError):
                    with scope.canonical_admission_writer_scope(authority,ref,row,adapter):pass
            self.assertEqual(fences,[])

    def test_canonical_claim_scope_exit_keeps_continuing_worker_held(self):
        authority,ref,row,adapter,native,fences=self.canonical_fixture()
        entered,release=threading.Event(),threading.Event()
        def worker():
            with scope.canonical_writer_foreground_scope():
                entered.set();release.wait(timeout=5)
        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                with patch.dict(sys.modules,{'gateway.platforms.api_server_authority_runs':native}):
                    with scope.canonical_admission_writer_scope(authority,ref,row,adapter):
                        context=copy_context();future=pool.submit(context.run,worker)
                        self.assertTrue(entered.wait(timeout=3))
                    snapshot=adapter._mesh_writer_runs.snapshot(row['request_id'])
                    self.assertFalse(snapshot['lifetime']['rootEnded'])
                    self.assertFalse(snapshot['lifetime']['managedWorkEnded'])
                    release.set();future.result(timeout=3)
                    self.assertTrue(adapter._mesh_writer_runs.snapshot(row['request_id'])['lifetime']['managedWorkEnded'])
        finally:release.set()

    def test_canonical_unconfigured_and_non_run_admissions_keep_legacy_behavior(self):
        with scope.canonical_admission_writer_scope(None,None,{},None):pass
        with scope.canonical_admission_writer_scope(None,None,{'request_id':'chat-request'},types.SimpleNamespace(_mesh_writer_runs=object())):pass

    def test_observation_after_registry_restart_does_not_reuse_old_ownership(self):
        first = scope.WriterRunRegistry(lambda *args: None)
        second = scope.WriterRunRegistry(lambda *args: None)
        run_id = 'run_' + 'a' * 32
        old = scope.observe_writer_run(first, run_id)
        new = scope.observe_writer_run(second, run_id)
        self.assertNotEqual(old['ownerId'], new['ownerId'])
        self.assertEqual(new['state'], 'unknown')
        self.assertIsNone(new['enrollment'])
        self.assertFalse(new['writerQuiescence'])

    def test_failed_observation_does_not_publish_exception_contents_or_release(self):
        registry = scope.WriterRunRegistry(lambda *args: None)
        with patch.object(registry, 'snapshot', side_effect=OSError('private diagnostic fixture')):
            result = scope.observe_writer_run(registry, 'run_' + 'a' * 32)
        self.assertEqual(result['state'], 'unknown')
        self.assertNotIn('private diagnostic fixture', str(result))
        self.assertIsNone(result['enrollment'])
        self.assertFalse(result['writerQuiescence'])

    def test_unconfigured_or_wrong_registry_can_never_report_finished_ownership(self):
        for registry, state in [(None, 'not_configured'), (object(), 'unknown')]:
            result = scope.observe_writer_run(registry, 'run_' + 'a' * 32)
            self.assertEqual(result['state'], state)
            self.assertIsNone(result['enrollment'])
            self.assertTrue(result['observationOnly'])
            self.assertFalse(result['writerQuiescence'])

    def run_fixture(self, number=1, **kwargs):
        return types.SimpleNamespace(run_id=f'run_{number:032x}', admission=None,
                                     writer_lifetime=None, writer_generation='', **kwargs)

    def test_server_mints_generation_and_duplicate_admission_cannot_replace_it(self):
        created = []
        def factory(run_id, generation):
            fence = types.SimpleNamespace(run_id=run_id, generation=generation, popen=lambda *a, **k: None,
                                          snapshot=lambda: {'processTreeEnded': False})
            created.append(fence)
            return fence
        registry, run = scope.WriterRunRegistry(factory), self.run_fixture()
        lifetime = scope.enroll_direct_writer_run(registry, run)
        self.assertIs(run.writer_lifetime, lifetime)
        self.assertEqual(run.writer_generation, created[0].generation)
        with self.assertRaises(RuntimeError):
            scope.enroll_direct_writer_run(registry, self.run_fixture())
        self.assertEqual(len(created), 1)
        self.assertFalse(registry.snapshot(run.run_id)['writerQuiescence'])

    def test_unknown_creation_retains_reservation_and_capacity(self):
        def fail(*args):
            raise OSError('uncertain resource creation')
        registry, run = scope.WriterRunRegistry(fail, max_entries=1), self.run_fixture()
        with self.assertRaises(OSError):
            registry.enroll(run)
        self.assertEqual(registry.snapshot(run.run_id)['state'], 'unknown')
        with self.assertRaises(RuntimeError):
            registry.enroll(self.run_fixture())
        with self.assertRaises(RuntimeError):
            registry.enroll(self.run_fixture(2))

    def test_external_lifetime_and_canonical_owner_routes_are_refused_before_creation(self):
        calls = []
        registry = scope.WriterRunRegistry(lambda *args: calls.append(args))
        for field, value in [('writer_generation', 'request-generation'),
                             ('writer_lifetime', object()), ('admission', object())]:
            run = self.run_fixture()
            setattr(run, field, value)
            with self.assertRaises(RuntimeError):
                registry.enroll(run)
        with self.assertRaises(ValueError):
            registry.enroll(types.SimpleNamespace(run_id='client-picked'))
        self.assertEqual(calls, [])

    def test_unconfigured_registry_preserves_legacy_and_arbitrary_registry_is_refused(self):
        run = self.run_fixture()
        self.assertIsNone(scope.enroll_direct_writer_run(None, run))
        self.assertIsNone(run.writer_lifetime)
        with self.assertRaises(RuntimeError):
            scope.enroll_direct_writer_run(types.SimpleNamespace(enroll=lambda _: None), run)

    def test_concurrent_same_run_enrolls_only_once(self):
        created = []
        def factory(run_id, generation):
            created.append(run_id)
            return types.SimpleNamespace(run_id=run_id, generation=generation, popen=lambda *a, **k: None)
        registry, barrier = scope.WriterRunRegistry(factory), threading.Barrier(2)
        def attempt():
            barrier.wait(timeout=3)
            try:
                registry.enroll(self.run_fixture())
                return 'enrolled'
            except RuntimeError:
                return 'refused'
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: attempt(), range(2)))
        self.assertEqual(sorted(results), ['enrolled', 'refused'])
        self.assertEqual(len(created), 1)


if __name__ == '__main__':
    unittest.main()
