"""Recovery refusal checks plus actual Windows-owned process retirement.

Profile/authentication and private-storage boundaries are test doubles here;
actual deployed-profile recovery remains a separate composed qualification.
"""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace, ModuleType
import unittest
from unittest.mock import patch

import mesh_native_recovery as recovery


class NativeRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='mesh-retired-attempt-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.window = SimpleNamespace(workspace=self.root, assert_held=lambda:None)
        self.profile = self.root/'profile.json'
        self.paths = [self.root/name for name in ('attempt', 'out', 'err')]
        self.p = dict(zip(('attemptPath','stdoutPath','stderrPath'),map(str,self.paths)))
        self.p['nodeExecutable'] = sys.executable
        self.record = dict(schema='onoes-mesh-native-child/v1',profileSha256='approved',
            pid=123,creationTicks=456,executable=sys.executable,entryPoint=str(self.root/'serve.mjs'),
            state='input_sent',credentialsInRecord=False)
        self.roles = SimpleNamespace(plain_json=lambda p:json.loads(p.read_text()),
                                     same_process_alive=lambda pid,ticks:False)
        self.module = SimpleNamespace(__file__=str(self.root/'integrations/mind-recovery-candidate/mesh_launch_candidate.py'),
                                     checked_launch=lambda *args:(self.p,self.roles))
        fake = ModuleType('onoes_mind.enrollment_store')
        def qualify(path,kind='directory'):
            if kind=='file' and not path.is_file():raise ValueError('Missing private file')
            return path.resolve(strict=True)
        fake.qualify_private_storage=qualify
        self.enrollment = patch.dict(sys.modules,{'onoes_mind.enrollment_store':fake})
        self.enrollment.start();self.addCleanup(self.enrollment.stop)

    def seed(self):
        self.paths[0].write_text(json.dumps(self.record))
        self.paths[1].write_bytes(b'original stdout\n')
        self.paths[2].write_bytes(b'original stderr\n')

    def archive(self):
        return recovery.archive_retired_mesh_attempt(self.window,launch_module=self.module,
            mesh_profile=self.profile,mesh_sha256='approved',reader_approval='approved-reader')

    def test_unused_namespace_has_no_side_effects(self):
        before=list(self.root.iterdir())
        self.assertEqual(self.archive(),dict(state='absent',archived=False))
        self.assertEqual(list(self.root.iterdir()),before)

    def test_live_owner_and_failed_observation_preserve_every_byte(self):
        self.seed();before=[p.read_bytes() for p in self.paths]
        self.roles.same_process_alive=lambda *args:True
        with self.assertRaises(recovery.NativeRecoveryHold):self.archive()
        def denied(*args):raise PermissionError('Observation denied')
        self.roles.same_process_alive=denied
        with self.assertRaises(PermissionError):self.archive()
        self.assertEqual([p.read_bytes() for p in self.paths],before)

    def test_unresolved_or_mismatched_identity_never_retries(self):
        self.seed()
        for key,value in (('state','input_pending'),('state','identity_pending'),
                          ('profileSha256','other'),('creationTicks',None),
                          ('credentialsInRecord',True),('entryPoint','other'),('extra',True)):
            value_record=dict(self.record);value_record[key]=value
            self.paths[0].write_text(json.dumps(value_record));before=[p.read_bytes() for p in self.paths]
            with self.subTest(key=key,value=value):
                with self.assertRaises(recovery.NativeRecoveryHold):self.archive()
                self.assertEqual([p.read_bytes() for p in self.paths],before)

    def test_existing_destination_and_partial_namespace_are_held(self):
        self.seed();suffix='.retired-123-456'
        destination=self.paths[1].with_name(self.paths[1].name+suffix)
        destination.write_bytes(b'previous evidence')
        with self.assertRaises(recovery.NativeRecoveryHold):self.archive()
        self.assertTrue(all(p.exists() for p in self.paths))
        self.paths[0].unlink()
        with self.assertRaises(recovery.NativeRecoveryHold):self.archive()
        self.assertEqual(destination.read_bytes(),b'previous evidence')

    def test_authentication_window_or_module_failure_precedes_moves(self):
        self.seed();before=[p.read_bytes() for p in self.paths]
        with patch.object(self.module,'checked_launch',side_effect=PermissionError):
            with self.assertRaises(PermissionError):self.archive()
        with patch.object(self.window,'assert_held',side_effect=RuntimeError):
            with self.assertRaises(RuntimeError):self.archive()
        with patch.object(self.module,'__file__','elsewhere'):
            with self.assertRaises(recovery.NativeRecoveryHold):self.archive()
        self.assertEqual([p.read_bytes() for p in self.paths],before)

    def test_interrupted_rename_preserves_blocking_attempt_and_refuses_again(self):
        self.seed();actual=recovery.os.rename;calls=[]
        def interrupted(source,destination):
            calls.append(source)
            if len(calls)==2:raise OSError('Synthetic interruption')
            actual(source,destination)
        with patch.object(recovery.os,'rename',side_effect=interrupted):
            with self.assertRaises(OSError):self.archive()
        self.assertTrue(self.paths[0].exists())
        with self.assertRaises((ValueError,recovery.NativeRecoveryHold)):self.archive()

    @unittest.skipUnless(sys.platform=='win32','Actual Windows-owned process')
    def test_original_windows_child_must_exit_before_exact_evidence_archival(self):
        sys.path.insert(0,str(Path(__file__).parent/'mind-recovery-candidate'))
        import recall_process_candidate as roles
        child=subprocess.Popen([sys.executable,'-I','-c','import time;time.sleep(30)'],
                               creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            self.record.update(pid=child.pid,creationTicks=roles.creation_ticks(child._handle))
            self.roles.same_process_alive=roles.same_process_alive
            self.seed();before=[p.read_bytes() for p in self.paths]
            with self.assertRaises(recovery.NativeRecoveryHold):self.archive()
            child.terminate();child.wait(timeout=10)
            result=self.archive()
            self.assertTrue(result['archived']);self.assertEqual(result['pid'],child.pid)
            self.assertEqual([Path(p).read_bytes() for p in result['archives']],before)
            self.assertFalse(any(p.exists() for p in self.paths))
            self.assertEqual(self.archive()['state'],'absent')
        finally:
            if child.poll() is None:child.terminate();child.wait(timeout=10)


if __name__=='__main__':unittest.main()
