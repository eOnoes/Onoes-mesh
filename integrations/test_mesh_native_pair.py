"""Focused lifecycle faults; real Windows/runtime qualification is separate."""
import hashlib
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

from mesh_native_pair import MeshNativePair, NativePairHold


class Process:
    def __init__(self, pid): self.pid=pid;self._handle=pid;self.returncode=None;self.terminated=0
    def poll(self): return self.returncode
    def terminate(self): self.terminated+=1;self.returncode=1


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name).resolve();helpers=self.root/'integrations/mind-recovery-candidate'
        self.ready=self.root/'owner.json';self.log=self.root/'startup.log';self.log.write_text('')
        self.writer=Process(101);self.mesh=Process(202)
        self.starts=self.launches=self.stops=self.reads=0
        self.running=False;self.stop_failure=False;self.launch_unknown=False
        self.window=SimpleNamespace(workspace=self.root,assert_held=lambda:None,_owns_gateway=lambda *a:None)
        def start(*args):
            self.starts+=1
            if self.launch_unknown:
                error=RuntimeError('simulated uncertain startup');error.child=self.writer;raise error
            return self.writer,1010
        def state(*args):
            self.reads+=1
            return dict(pid=101,creationTicks=1010,ready=self.running and self.writer.poll() is None,
                        state='stopped' if self.writer.poll() is not None else 'running' if self.running else 'starting',
                        processLive=self.writer.poll() is None)
        def stop(*args):
            self.stops+=1
            if self.stop_failure: raise OSError('simulated uncertain stop receipt')
            self.writer.returncode=0
        def mesh(*args): self.launches+=1;return self.mesh,2020,dict(state='input_sent')
        self.service=SimpleNamespace(__file__=str(helpers/'project_service_process_candidate.py'),
            launch_service=start,service_state=state,request_stop=stop)
        self.launch=SimpleNamespace(__file__=str(helpers/'mesh_launch_candidate.py'),launch_mesh=mesh)
        self.roles=SimpleNamespace(__file__=str(helpers/'recall_process_candidate.py'),creation_ticks=lambda h:h*10)
        sp=self.root/'service.json';sp.write_text(json.dumps(dict(readyPath=str(self.ready))))
        mp=self.root/'mesh.json';mp.write_text(json.dumps(dict(stdoutPath=str(self.log),settings=dict(MESH_PREVIEW_PORT='42001'))))
        self.pair=MeshNativePair(self.window,service_module=self.service,launch_module=self.launch,roles_module=self.roles,
            service_profile=sp,service_sha256=hashlib.sha256(sp.read_bytes()).hexdigest(),project_approval=self.root/'approval.json',
            mesh_profile=mp,mesh_sha256=hashlib.sha256(mp.read_bytes()).hexdigest(),reader_approval=self.root/'reader.json')

    def make_running(self):
        self.pair.start_writer();self.running=True;self.ready.write_text('{"state":"running"}')
        self.assertEqual(self.pair.observe_writer()['stage'],'writer_ready');self.pair.launch_mesh()

    def test_unpublished_partial_and_starting_owner_never_imply_readiness(self):
        self.pair.start_writer()
        self.assertEqual(self.pair.observe_writer()['stage'],'writer_starting')
        self.ready.write_text('{"state":')
        self.assertEqual(self.pair.observe_writer()['stage'],'writer_starting')
        self.assertEqual(self.reads,0)
        self.ready.write_text('{"state":"starting"}')
        self.assertEqual(self.pair.observe_writer()['stage'],'writer_starting')
        self.assertEqual(self.pair.observe_writer()['stage'],'writer_starting')
        self.assertEqual(self.reads,1);self.assertEqual(self.launches,0)
        self.running=True;self.ready.write_text('{"state":"running"}')
        self.assertEqual(self.pair.observe_writer()['stage'],'writer_ready')
        self.pair.launch_mesh();self.assertEqual(self.launches,1);self.assertEqual(self.starts,1)
        with self.assertRaises(NativePairHold):self.pair.start_writer()
        self.assertIs(self.pair.writer,self.writer);self.assertIs(self.pair.mesh,self.mesh)
        self.assertEqual(self.starts,1)

    def test_uncertain_writer_launch_retains_original_handle_and_cannot_restart(self):
        self.launch_unknown=True
        with self.assertRaises(NativePairHold):self.pair.start_writer()
        self.assertIs(self.pair.writer,self.writer);self.assertEqual(self.pair.writer_ticks,1010)
        with self.assertRaises(NativePairHold):self.pair.start_writer()
        self.assertEqual(self.starts,1);self.assertEqual(self.writer.terminated,0)

    def test_uncertain_stop_is_not_resent_and_handles_are_preserved(self):
        self.make_running();self.stop_failure=True;self.pair.request_stop()
        with self.assertRaises(NativePairHold):self.pair.observe_stop()
        self.assertEqual(self.pair.stage,'held');self.assertEqual(self.stops,1)
        with self.assertRaises(NativePairHold):self.pair.observe_stop()
        self.assertEqual(self.stops,1);self.assertEqual(self.mesh.terminated,1)
        self.assertIs(self.pair.writer,self.writer);self.assertIs(self.pair.mesh,self.mesh)

    def test_owned_shutdown_requires_exact_clean_writer_readback(self):
        self.make_running();self.pair.request_stop()
        self.assertEqual(self.pair.observe_stop()['stage'],'stopped')
        self.assertEqual(self.stops,1);self.assertEqual(self.mesh.terminated,1)
        self.assertEqual(self.pair.observe_stop()['stage'],'stopped')
        self.assertEqual(self.stops,1)
        self.assertIs(self.pair.writer,self.writer);self.assertIs(self.pair.mesh,self.mesh)

    def test_terminal_writer_does_not_start_another_worker(self):
        self.pair.start_writer();self.writer.returncode=2
        with self.assertRaises(NativePairHold):self.pair.observe_writer()
        self.assertEqual(self.pair.stage,'held');self.assertEqual(self.starts,1);self.assertEqual(self.launches,0)

    def test_readiness_distinguishes_browser_gateway_from_internal_backend(self):
        self.make_running();observed=[]
        self.window._owns_gateway=lambda pid,port:observed.append((pid,port))
        self.log.write_text(json.dumps(dict(event='mesh_listening',pid=202,
            url='http://127.0.0.1:42002',previewUrl='http://127.0.0.1:42001')))
        self.assertEqual(self.pair.observe_mesh()['stage'],'mesh_ready')
        self.assertEqual(self.pair.address,'http://127.0.0.1:42001')
        self.assertEqual(observed,[(202,42001),(202,42002)])

    def test_backend_cannot_substitute_for_wrong_browser_gateway(self):
        self.make_running()
        self.log.write_text(json.dumps(dict(event='mesh_listening',pid=202,
            url='http://127.0.0.1:42001',previewUrl='http://127.0.0.1:42002')))
        with self.assertRaisesRegex(NativePairHold,'Unexpected native readiness address'):
            self.pair.observe_mesh()
        self.assertEqual(self.pair.stage,'held');self.assertEqual(self.mesh.terminated,0)

    def prepare_adoption(self):
        self.running=True;self.pair.adopt_started_writer(self.writer,1010)
        self.attempt=self.root/'attempt.json'
        self.pair.mesh_settings.update(attemptPath=str(self.attempt),nodeExecutable='fixed-node.exe')
        self.record=dict(schema='onoes-mesh-native-child/v1',profileSha256=self.pair.mesh_sha,
            pid=202,creationTicks=2020,state='input_sent',credentialsInRecord=False,
            executable='fixed-node.exe',entryPoint=str(self.root/'serve.mjs'))

    def test_existing_exact_gateway_is_observed_without_another_launch(self):
        self.prepare_adoption();self.attempt.write_text(json.dumps(self.record))
        self.log.write_text(json.dumps(dict(event='mesh_listening',pid=202,
            url='http://127.0.0.1:42002',previewUrl='http://127.0.0.1:42001')))
        self.assertEqual(self.pair.adopt_started_mesh(self.mesh,2020)['stage'],'mesh_ready')
        self.assertEqual((self.starts,self.launches),(0,0))
        with self.assertRaises(NativePairHold):self.pair.adopt_started_mesh(self.mesh,2020)

    def test_unresolved_existing_gateway_is_held_without_launch_or_stop(self):
        self.prepare_adoption();self.record['state']='input_pending'
        self.attempt.write_text(json.dumps(self.record))
        with self.assertRaises(NativePairHold):self.pair.adopt_started_mesh(self.mesh,2020)
        self.assertEqual((self.starts,self.launches,self.mesh.terminated),(0,0,0))


if __name__=='__main__':unittest.main()
