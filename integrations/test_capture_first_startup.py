"""Metadata continuity and modular startup boundaries; no live processes."""
from datetime import datetime,timezone
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch

import mesh_startup_candidate as startup
import mesh_recovery_candidate as recovery


class StartupTests(unittest.TestCase):
    def test_port_probe_requires_explicit_refusal_and_never_treats_timeout_as_free(self):
        for outcome in (ConnectionRefusedError(),TimeoutError(),None):
            probe=Mock();probe.connect.side_effect=outcome
            context=Mock();context.__enter__=Mock(return_value=probe);context.__exit__=Mock(return_value=False)
            with patch.object(startup.socket,'socket',return_value=context):
                if isinstance(outcome,ConnectionRefusedError):startup.require_unoccupied_port('12345')
                else:
                    with self.assertRaises(TimeoutError if isinstance(outcome,TimeoutError) else startup.StartupHold):
                        startup.require_unoccupied_port('12345')
            probe.settimeout.assert_called_once_with(5)
            probe.connect.assert_called_once_with(('127.0.0.1',12345))

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        base=Path(self.temp.name).resolve();self.root=base/'workspace';self.root.mkdir();self.private=base/'private';self.private.mkdir()
        self.addCleanup(patch.stopall);patch.object(startup,'ROOT',self.root).start()
        settings=dict(MESH_PREVIEW_PORT='12345',MESH_GATE_KEY_FILE=str(self.private/'gate'))
        self.handoff={};self.selected={}
        for mode,schema in [('capture','onoes-mesh-native-capture-launch/v1'),('connected','onoes-mesh-native-launch/v2')]:
            p=dict(schema=schema,workspace=str(self.root),nodeExecutable=str(self.root/'node.exe'),nodeSha256='a'*64,
                sourceHashes={},ownerSid='S-1-test',settings=settings.copy(),
                **{key:str(self.private/(mode+'-'+key)) for key in ('attemptPath','stdoutPath','stderrPath')})
            if mode=='capture':p['projectCapture']=dict(source={'databasePath':'approved'},links=['approved-link'])
            else:
                p['readerProfileSha256']='b'*64;p['readerProfile']=str(self.private/'reader')
                p['projectSync']=dict(source={'databasePath':'approved'},links=['approved-link'],
                    serviceProfile=str(self.private/'writer'),serviceProfileSha256='c'*64,approvalPath=str(self.private/'writer-approval'))
            path=self.private/(mode+'-profile.json');path.write_text(json.dumps(p));self.selected[mode]=p
            self.handoff[mode]=dict(profilePath=str(path),profileSha256=startup.digest(path),approvalPath=str(self.private/(mode+'-approval')))
        self.cp,self.np=self.selected['capture'],self.selected['connected']
        self.peers=dict(reader=dict(pid=201,creationTicks=2001,profileSha256='b'*64),
            writer=dict(pid=202,creationTicks=2002,profileSha256='c'*64,runId='d'*32))
        self.live=set();self.roles=SimpleNamespace(same_process_alive=lambda pid,ticks:pid in self.live)
        self.window=SimpleNamespace(workspace=self.root,assert_held=Mock(),_owns_gateway=Mock())
        self.approved=dict(ownerSid='S-1-test',handoffApprovalPath=str(self.private/'handoff'),handoffApprovalSha256='a'*64)

    def record(self,mode,pid=100,ticks=1000):
        value=dict(schema='onoes-mesh-native-child/v3' if mode=='capture' else 'onoes-mesh-native-child/v2',
            profileSha256=self.handoff[mode]['profileSha256'],pid=pid,creationTicks=ticks,
            executable=self.selected[mode]['nodeExecutable'],entryPoint=str(self.root/'serve.mjs'),state='input_sent',credentialsInRecord=False)
        if mode=='capture':value['mode']='capture_only'
        else:value['peers']=self.peers
        return value

    def files(self,mode,record):
        p=self.selected[mode];Path(p['attemptPath']).write_text(json.dumps(record))
        for key in ('stdoutPath','stderrPath'):Path(p[key]).write_bytes(b'original log')

    def receipt(self,mode,record):
        p=self.selected[mode]
        value=dict(Schema='onoes-owned-process/v1',WorkingDirectory=str(self.root),Id=record['pid'],
            StartTime=recovery.native_start(record['creationTicks']),EntryPoint=str(self.root/'serve.mjs'),
            Path=p['nodeExecutable'],Port=12345,CommandLine=subprocess.list2cmdline([p['nodeExecutable'],str(self.root/'serve.mjs'),'--native-mind']))
        target=self.root.parent/'workroom-ab-preview-process.json';target.write_text(json.dumps(value));return target

    def storage(self):
        import onoes_mind.enrollment_store as storage
        patch.object(storage,'qualify_private_storage',side_effect=lambda path,**kw:path).start()

    def configure_controller(self,owner):
        self.storage();self.fake_recovery=SimpleNamespace(restore_memory_roles=Mock(side_effect=RuntimeError('memory unavailable')),
            handoff_capture_to_connected=Mock(),ensure_memory=Mock(),CaptureHandoffUnknown=recovery.CaptureHandoffUnknown)
        patch.object(startup,'checked_startup',return_value=(self.approved,self.handoff,{},self.fake_recovery)).start()
        patch.object(startup,'profiles',return_value=self.selected).start();patch.object(startup,'load_roles',return_value=self.roles).start()
        patch.object(startup,'owner_record',return_value=owner).start()
        self.launch=SimpleNamespace(checked_launch=Mock(return_value=(self.cp,self.roles)),
            inspect_launch=Mock(return_value=(self.np,self.roles)),launch_mesh=Mock())
        patch.dict(sys.modules,{'mesh_launch_candidate':self.launch,'project_service_process_candidate':SimpleNamespace(),
            'reader_service_process_candidate':SimpleNamespace()}).start()

    def call(self):
        return startup.ensure_capture_first(self.window,approval_path=self.private/'startup.json',approval_sha='f'*64)

    def test_native_chat_binding_cannot_change_across_capture_and_connected_modes(self):
        def save(mode,profile):
            path=Path(self.handoff[mode]['profilePath']);path.write_text(json.dumps(profile))
            self.handoff[mode]['profileSha256']=startup.digest(path)
        value={'source':'native_codex_desktop_readonly','projectDirectory':'C:/Owned/Project'}
        self.cp['codexDesktopOptions']=value.copy();save('capture',self.cp)
        with self.assertRaises(startup.StartupHold):startup.profiles(self.handoff)
        self.np['codexDesktopOptions']=value.copy();save('connected',self.np)
        startup.profiles(self.handoff)
        self.np['codexDesktopOptions']['projectDirectory']='C:/Other';save('connected',self.np)
        with self.assertRaises(startup.StartupHold):startup.profiles(self.handoff)

    def test_profile_substitution_or_record_paths_inside_code_repo_are_refused(self):
        startup.profiles(self.handoff)
        bad=self.private/'capture-profile.json';bad.write_text('{}')
        with self.assertRaises(startup.StartupHold):startup.profiles(self.handoff)
        bad.write_text(json.dumps(self.cp));self.cp['attemptPath']=str(self.root/'misplaced-attempt')
        bad.write_text(json.dumps(self.cp));self.handoff['capture']['profileSha256']=startup.digest(bad)
        with self.assertRaises(startup.StartupHold):startup.profiles(self.handoff)

    def test_only_connected_mode_can_add_the_two_worker_fields(self):
        record_key='MESH_NATIVE_WORKER_RECORD'
        sha_key='MESH_NATIVE_WORKER_RECORD_SHA256'
        record=str(self.private/'worker-record')
        connected={**self.np['settings'],record_key:record,sha_key:'e'*64}

        def change(mode, **fields):
            profile={**self.selected[mode],**fields}
            path=Path(self.handoff[mode]['profilePath'])
            path.write_text(json.dumps(profile))
            self.handoff[mode]['profileSha256']=startup.digest(path)

        change('connected',settings=connected)
        self.assertEqual(startup.profiles(self.handoff)['connected']['settings'],connected)
        for drift in ({key:value for key,value in connected.items() if key!=sha_key},
                      {**connected,'MESH_PREVIEW_PORT':'23456'}, {**connected,record_key:'relative'}):
            change('connected',settings=drift)
            with self.assertRaises(startup.StartupHold):startup.profiles(self.handoff)
        change('connected',settings=connected,stdoutPath=record)
        with self.assertRaises(startup.StartupHold):startup.profiles(self.handoff)
        change('connected',settings=connected)
        change('capture',settings=connected)
        with self.assertRaises(startup.StartupHold):startup.profiles(self.handoff)

    def test_exact_retired_attempt_and_logs_are_preserved_without_memory_access(self):
        self.storage();record=self.record('connected');self.files('connected',record);receipt=self.receipt('connected',record)
        observed=startup.owner_record(self.window,self.handoff,self.selected,self.roles);self.assertFalse(observed['live'])
        original=receipt.read_bytes();startup.retire_mode(self.window,self.np,{**self.handoff['connected'],'mode':'connected'},self.roles)
        self.assertFalse(Path(self.np['attemptPath']).exists());self.assertEqual(receipt.read_bytes(),original)
        archived=startup.owner_record(self.window,self.handoff,self.selected,self.roles)
        self.assertTrue(archived['archived']);self.assertEqual(archived['record'],record)

    def test_partial_archive_or_live_actor_never_moves_original_evidence(self):
        self.storage();record=self.record('capture');self.files('capture',record);self.live.add(100)
        original=Path(self.cp['attemptPath']).read_bytes()
        with self.assertRaises(startup.StartupHold):startup.retire_mode(self.window,self.cp,{**self.handoff['capture'],'mode':'capture'},self.roles)
        self.live.clear();Path(self.cp['stdoutPath']+'.retired-100-1000').write_text('existing destination')
        with self.assertRaises(startup.StartupHold):startup.retire_mode(self.window,self.cp,{**self.handoff['capture'],'mode':'capture'},self.roles)
        self.assertEqual(Path(self.cp['attemptPath']).read_bytes(),original)

    def test_healthy_tick_observes_only_and_never_revalidates_memory_or_restarts(self):
        record=self.record('connected');self.live.update((100,201,202))
        self.configure_controller(dict(mode='connected',record=record,live=True,archived=False))
        state,held=self.call();self.assertEqual(state['state'],'observed_running');self.assertEqual(held,[])
        self.assertEqual(state['memoryAuthorization'],'not_revalidated');self.launch.checked_launch.assert_not_called()
        self.fake_recovery.restore_memory_roles.assert_not_called();self.fake_recovery.ensure_memory.assert_not_called()

    def test_memory_failure_keeps_published_capture_alive_and_its_attempt_unchanged(self):
        record=self.record('capture');self.files('capture',record);self.live.add(100)
        self.configure_controller(dict(mode='capture',record=record,live=True,receiptSha256='a'*64,archived=False))
        child=Mock(pid=100);child.poll.return_value=None
        self.fake_recovery.ProcessObservation=Mock(return_value=child)
        original=Path(self.cp['attemptPath']).read_bytes();state,held=self.call()
        self.assertEqual(state['state'],'capture_pending');self.assertIn(child,held)
        self.assertEqual(original,Path(self.cp['attemptPath']).read_bytes());self.launch.launch_mesh.assert_not_called()
        self.fake_recovery.handoff_capture_to_connected.assert_not_called();child.terminate.assert_not_called()

    def test_unpublished_dead_capture_and_live_split_owner_are_held(self):
        record=self.record('capture');self.files('capture',record);self.configure_controller(None)
        with self.assertRaises(startup.StartupHold):self.call()
        self.launch.launch_mesh.assert_not_called()
        self.files('connected',self.record('connected',300,3000));self.live.add(300)
        with patch.object(startup,'owner_record',return_value=dict(mode='capture',record=record,live=True)):
            with self.assertRaises(startup.StartupHold):self.call()
        self.fake_recovery.ensure_memory.assert_not_called()

    def test_pause_prevents_role_import_and_capture_launch(self):
        self.configure_controller(None);sentinel=self.root/'data/workroom-preview/recovery-paused';sentinel.parent.mkdir(parents=True);sentinel.touch()
        state,held=self.call();self.assertEqual(state['state'],'paused');self.assertEqual(held,[])
        self.launch.checked_launch.assert_not_called();self.launch.launch_mesh.assert_not_called()

    def test_real_command_missing_approval_fails_without_creating_state(self):
        result=subprocess.run([sys.executable,'-I',str(Path(startup.__file__).resolve()),'--approval',str(self.private/'missing'),
            '--sha256','0'*64],capture_output=True,text=True,timeout=15,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        self.assertEqual(result.returncode,1);self.assertEqual(json.loads(result.stdout)['state'],'held')
        self.assertFalse((self.private/'missing').exists());self.assertNotIn('Traceback',result.stderr)


class ApprovalChainTests(unittest.TestCase):
    def test_startup_binds_exact_handoff_and_memory_recovery_without_opening_store(self):
        with tempfile.TemporaryDirectory() as name:
            root=Path(name).resolve();bindings={}
            for role in ('capture','connected'):
                selected={}
                for prefix in ('profile','approval')+(('projectApproval',) if role=='connected' else ()):
                    p=root/(role+prefix+'.json');p.write_text('{}')
                    selected[prefix+'Path']=str(p);selected[prefix+'Sha256']=startup.digest(p)
                bindings[role]=selected
            hashes={str(startup.ROOT/'integrations'/name):startup.digest(startup.ROOT/'integrations'/name) for name in recovery.FILES}
            handoff=root/'handoff.json';handoff.write_text(json.dumps(dict(schema='onoes-mesh-capture-handoff-approval/v1',
                decision='approve_exact_capture_to_connected_handoff',workspace=str(startup.ROOT),ownerSid='S-1-test',
                pythonSha256=startup.digest(sys.executable),sourceHashes=hashes,**bindings)))
            wrapper=startup.ROOT/'integrations/mind-recovery-candidate/reader_service_process_candidate.py'
            memory=root/'memory.json';memory.write_text(json.dumps(dict(schema='onoes-mesh-native-recovery-approval/v1',
                decision='approve_exact_same_grant_memory_recovery',workspace=str(startup.ROOT),ownerSid='S-1-test',
                profilePath=bindings['connected']['profilePath'],profileSha256=bindings['connected']['profileSha256'],
                pythonSha256=startup.digest(sys.executable),sourceHashes={**hashes,str(wrapper):startup.digest(wrapper)},
                readerServiceProfile=str(root/'not-opened-reader-profile'),readerServiceSha256='b'*64)))
            value=dict(schema='onoes-mesh-capture-first-approval/v1',decision='approve_exact_capture_first_recovery',
                workspace=str(startup.ROOT),ownerSid='S-1-test',pythonSha256=startup.digest(sys.executable),
                sourceHashes={str(startup.ROOT/'integrations'/name):startup.digest(startup.ROOT/'integrations'/name) for name in startup.SOURCES},
                handoffApprovalPath=str(handoff),handoffApprovalSha256=startup.digest(handoff),
                memoryApprovalPath=str(memory),memoryApprovalSha256=startup.digest(memory))
            path=root/'startup.json';path.write_text(json.dumps(value))
            approved,_,_,_=startup.checked_startup(path,startup.digest(path));self.assertEqual(approved,value)
            self.assertFalse((root/'not-opened-reader-profile').exists())
            for mutation in [dict(ownerSid='S-1-another'),dict(decision='approve_exact_capture_to_connected_handoff'),
                             dict(sourceHashes={**value['sourceHashes'],str(startup.ROOT/'integrations/mesh_startup_candidate.py'):'0'*64})]:
                path.write_text(json.dumps({**value,**mutation}))
                with self.assertRaises(startup.StartupHold):startup.checked_startup(path,startup.digest(path))


if __name__=='__main__':unittest.main()
