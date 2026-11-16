"""Approval and interruption boundaries for the explicit native reconnect."""
import copy
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import mesh_recovery_candidate as recovery


class ApprovalTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name).resolve();self.addCleanup(patch.stopall)
        patch.object(recovery,'ROOT',self.root).start();(self.root/'integrations').mkdir()
        pins={}
        for name in recovery.FILES:
            p=self.root/'integrations'/name;p.write_text('synthetic code pin');pins[str(p)]=recovery.digest(p)
        self.value=dict(schema='onoes-mesh-capture-handoff-approval/v1',decision='approve_exact_capture_to_connected_handoff',
            workspace=str(self.root),ownerSid='S-1-synthetic',pythonSha256=recovery.digest(sys.executable),sourceHashes=pins)
        for role in ('capture','connected'):
            selected={}
            for prefix in ('profile','approval')+(('projectApproval',) if role=='connected' else ()):
                p=self.root/(role+'-'+prefix+'.json');p.write_text('{}')
                selected[prefix+'Path']=str(p);selected[prefix+'Sha256']=recovery.digest(p)
            self.value[role]=selected
        self.path=self.root/'handoff.json'

    def write(self,value):
        self.path.write_text(json.dumps(value));return recovery.digest(self.path)

    def test_exact_approval_pins_both_modes_and_all_grants(self):
        sha=self.write(self.value)
        self.assertEqual(recovery.checked_handoff_approval(self.path,sha),self.value)
        for role,prefix in [('capture','profile'),('capture','approval'),('connected','profile'),
                            ('connected','approval'),('connected','projectApproval')]:
            target=Path(self.value[role][prefix+'Path']);target.write_text('changed')
            with self.assertRaises(recovery.RecoveryHold):recovery.checked_handoff_approval(self.path,sha)
            target.write_text('{}')

    def test_other_decision_source_drift_and_extra_fields_are_refused(self):
        for change in [dict(decision='approve_exact_same_grant_memory_recovery'),dict(extra=True)]:
            sha=self.write({**self.value,**change})
            with self.assertRaises(recovery.RecoveryHold):recovery.checked_handoff_approval(self.path,sha)
        sha=self.write(self.value);next((self.root/'integrations').iterdir()).write_text('drift')
        with self.assertRaises(recovery.RecoveryHold):recovery.checked_handoff_approval(self.path,sha)


class BoundaryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name).resolve();self.addCleanup(patch.stopall)
        patch.object(recovery,'ROOT',self.root).start()
        self.window=SimpleNamespace(workspace=self.root,assert_held=Mock(),_owns_gateway=Mock())
        self.c={key:str(self.root/key) for key in ('profilePath','approvalPath')};self.c.update(profileSha256='c'*64,approvalSha256='a'*64)
        self.n={key:str(self.root/('new-'+key)) for key in ('profilePath','approvalPath','projectApprovalPath')}
        self.n.update(profileSha256='d'*64,approvalSha256='e'*64,projectApprovalSha256='f'*64)
        self.approved=dict(ownerSid='S-1-test',capture=self.c,connected=self.n)
        common=dict(workspace=str(self.root),nodeExecutable='fixed-node',nodeSha256='a'*64,settings={'MESH_PREVIEW_PORT':'12345'})
        self.cp={**common,'schema':'capture-schema','ownerSid':'S-1-test',**{name:str(self.root/('capture-'+name)) for name in ('attemptPath','stdoutPath','stderrPath')}}
        self.np={**common,'schema':'onoes-mesh-native-launch/v2',**{name:str(self.root/('new-'+name)) for name in ('attemptPath','stdoutPath','stderrPath')},
            'projectSync':dict(approvalPath=self.n['projectApprovalPath'],serviceProfile='service',serviceProfileSha256='s'*64)}
        self.local=dict(schema='onoes-mesh-native-project-capture/v1',source={'databasePath':'approved-source'},storeId='store',links=[{'fields':['title','stage']}])
        self.frame=dict(projectSyncOptions=dict(source=self.local['source'],links=self.local['links'],destination={'storeId':'store','token':'never-print'}))
        self.roles=SimpleNamespace(same_process_alive=Mock(return_value=False))
        self.launch=SimpleNamespace(CAPTURE_SCHEMA='capture-schema',checked_launch=Mock(side_effect=lambda path,*a:(self.cp if path==self.c['profilePath'] else self.np,self.roles)),
            native_frame=Mock(side_effect=lambda p,*a:dict(projectCaptureOptions=self.local) if p is self.cp else self.frame))
        self.launch.native_peers=Mock(return_value=dict(reader=dict(pid=101,creationTicks=1001,profileSha256='b'*64),
            writer=dict(pid=200,creationTicks=2000,profileSha256='d'*64,runId='e'*32)))
        self.service=SimpleNamespace(service_state=Mock(return_value=dict(ready=True,pid=200,creationTicks=2000)))
        patch.object(recovery,'checked_handoff_approval',return_value=self.approved).start()
        self.capture=dict(schema='onoes-mesh-native-child/v3',profileSha256='c'*64,pid=100,creationTicks=1000,
            executable='fixed-node',entryPoint=str(self.root/'serve.mjs'),state='input_sent',credentialsInRecord=False,mode='capture_only')
        Path(self.cp['attemptPath']).write_text(json.dumps(self.capture))
        self.owner=self.root/'owner.json';self.owner.write_text('{}')
        patch.object(recovery,'gateway_binding',return_value=dict(sameOwner=True,alive=False,args=['fixed-node'],
            receiptPath=self.owner,previousSha=recovery.digest(self.owner))).start()
        # Only private-file custody is doubled; no live profiles or services exist.
        import onoes_mind.enrollment_store as storage
        patch.object(storage,'qualify_private_storage',side_effect=lambda path,**kw:path).start()
        self.observe=patch.object(recovery,'ProcessObservation').start()
        self.observe.return_value.pid=200

    def call(self):
        return recovery.handoff_capture_to_connected(self.window,launch=self.launch,service=self.service,roles=self.roles,
            approval_path=self.root/'handoff.json',approval_sha='a'*64)

    def test_failed_connected_preflight_does_not_touch_capture(self):
        self.launch.checked_launch.side_effect=RuntimeError('unavailable')
        with self.assertRaises(RuntimeError):self.call()
        self.observe.assert_not_called();self.assertEqual(json.loads(Path(self.cp['attemptPath']).read_text()),self.capture)

    def test_broader_connected_scope_refuses_before_any_stop(self):
        self.frame=copy.deepcopy(self.frame);self.frame['projectSyncOptions']['links'][0]['fields'].append('goal')
        with self.assertRaises(recovery.RecoveryHold):self.call()
        self.observe.assert_not_called();self.service.service_state.assert_not_called()

    def test_existing_attempt_and_live_capture_cannot_dispatch_again(self):
        Path(self.np['attemptPath']).write_text('unresolved');self.roles.same_process_alive.return_value=True
        with patch.object(recovery,'_finish_gateway_preflight') as ensure:
            with self.assertRaises(recovery.RecoveryHold):self.call()
            ensure.assert_not_called()
        self.observe.assert_not_called()

    def test_existing_connected_attempt_is_reconciled_not_replaced(self):
        Path(self.np['attemptPath']).write_text('existing exact evidence')
        with patch.object(recovery,'_finish_gateway_preflight',return_value={'state':'reconciled','pid':300}) as ensure:
            result,child=self.call();self.assertEqual(result['pid'],300);self.assertIsNone(child);ensure.assert_called_once()
        self.observe.assert_not_called()

    def completion(self):
        return recovery._finish_gateway_preflight(self.window,launch=self.launch,service=self.service,roles=self.roles,
            p=self.np,profile=self.n['profilePath'],sha=self.n['profileSha256'],approval=self.n['approvalPath'],
            state=dict(ready=True,pid=200,creationTicks=2000),timeout=1,reconcile_only=True,
            expected_peers=self.launch.native_peers.return_value)

    def bound(self,alive=True):
        return dict(attempt=dict(pid=300,creationTicks=3000,peers=copy.deepcopy(self.launch.native_peers.return_value)),
            args=['fixed-node'],receiptPath=self.owner,previousSha=recovery.digest(self.owner),sameOwner=False,alive=alive)

    def test_dead_connected_attempt_cannot_be_replaced_even_if_old_owner_was_published(self):
        import mesh_native_pair
        bound=self.bound(False);bound['sameOwner']=True
        with patch.object(recovery,'gateway_binding',return_value=bound),patch.object(mesh_native_pair,'MeshNativePair') as pair:
            with self.assertRaises(recovery.RecoveryHold):self.completion()
            pair.assert_not_called()
        self.observe.assert_not_called()

    def test_changed_memory_peer_refuses_before_opening_or_launching_processes(self):
        import mesh_native_pair
        bound=self.bound();bound['attempt']['peers']['writer']['pid']=201
        with patch.object(recovery,'gateway_binding',return_value=bound),patch.object(mesh_native_pair,'MeshNativePair') as pair:
            with self.assertRaises(recovery.RecoveryHold):self.completion()
            pair.assert_not_called()
        self.observe.assert_not_called()

    def test_reader_retiring_during_observation_cannot_publish_as_connected(self):
        import mesh_native_pair
        references={pid:Mock(pid=pid) for pid in (101,200,300)}
        for ref in references.values():ref.poll.return_value=None
        references[101].poll.return_value=0
        self.observe.side_effect=lambda window,roles,pid,*args,**kw:references[pid]
        pair=Mock();pair.observe_mesh.return_value={'stage':'mesh_ready'}
        response=Mock();response.__enter__=Mock(return_value=SimpleNamespace(status=200));response.__exit__=Mock(return_value=False)
        with patch.object(recovery,'gateway_binding',return_value=self.bound()),patch.object(mesh_native_pair,'MeshNativePair',return_value=pair),patch.object(recovery,'urlopen',return_value=response):
            with self.assertRaises(recovery.RecoveryHold):self.completion()
        pair.publish_owner.assert_not_called();pair.launch_mesh.assert_not_called()
        for ref in references.values():ref.close.assert_called_once()

    def test_uncertain_new_launch_retains_its_original_pair(self):
        import mesh_native_pair
        pair=Mock();pair.launch_mesh.side_effect=RuntimeError('original launch uncertainty')
        original=object();pair.mesh=original
        with patch.object(mesh_native_pair,'MeshNativePair',return_value=pair):
            with self.assertRaises(recovery.CaptureHandoffUnknown) as result:self.call()
        self.assertIs(result.exception.pair,pair);self.assertIs(result.exception.pair.mesh,original)
        pair.launch_mesh.assert_called_once();self.observe.return_value.terminate.assert_not_called()
        self.observe.return_value.close.assert_called_once()


if __name__=='__main__':unittest.main()
