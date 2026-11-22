"""Disposable Windows code overlay and rollback; no real apps are stopped."""
import copy
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import mesh_runtime_overlay_candidate as overlay


@unittest.skipUnless(os.name=='nt','Windows exact-owner/port/file semantics')
class MeshOverlayTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='mesh-overlay-test-');self.root=Path(self.temp.name).resolve()
        self.addCleanup(self.cleanup)
        self.live=self.root/'live';self.payload=self.root/'payload';self.ops=self.root/'ops'
        for folder in (self.live,self.payload,self.ops):folder.mkdir()
        for folder in (self.live,self.payload):(folder/'lib').mkdir()
        (self.live/'lib/a.mjs').write_bytes(b'// exact original\r\n')
        (self.payload/'lib/a.mjs').write_bytes(b'// qualified replacement\n')
        (self.payload/'lib/new.mjs').write_bytes(b'// new installer-owned file\n')
        (self.live/'package.json').write_bytes(b'{}\r\n');(self.payload/'package.json').write_bytes(b'{}\r\n')
        (self.live/'UNRELATED.txt').write_text('Preserve user work',encoding='utf-8')
        observer=overlay.roles()
        child=subprocess.Popen([sys.executable,'-c','pass'],creationflags=subprocess.CREATE_NO_WINDOW)
        stamp=observer.creation_ticks(child._handle);self.assertEqual(child.wait(timeout=10),0)
        with socket.socket() as port:port.bind(('127.0.0.1',0));number=port.getsockname()[1]
        self.plan=dict(schema='onoes-mesh-runtime-overlay/v2',workspace=str(self.live),payloadRoot=str(self.payload),journalRoot=str(self.root/'journal'),
            toolSha256=overlay.digest(overlay.__file__),observerSha256=overlay.digest(overlay.observer_path()),runtime=dict(meshPid=child.pid,meshCreationTicks=stamp,gatewayPort=number,
                serviceAttemptPath=str(self.ops/'fixture-service-attempt.json'),serviceProfileSha256='a'*64,
                freshLaunchAttempts=[dict(kind='mesh',path=str(self.ops/'fresh-mesh-attempt.json'),profileSha256='c'*64),
                    dict(kind='service',path=str(self.ops/'fresh-service-attempt.json'),profileSha256='d'*64)]),files=[
                dict(relativePath='lib/a.mjs',beforeSha256=overlay.digest(self.live/'lib/a.mjs'),afterSha256=overlay.digest(self.payload/'lib/a.mjs')),
                dict(relativePath='lib/new.mjs',beforeSha256=None,afterSha256=overlay.digest(self.payload/'lib/new.mjs')),
                dict(relativePath='package.json',beforeSha256=overlay.digest(self.live/'package.json'),afterSha256=overlay.digest(self.payload/'package.json'))])

    def cleanup(self):
        self.assertEqual(self.root.parent,Path(tempfile.gettempdir()).resolve())
        self.assertTrue(self.root.name.startswith('mesh-overlay-test-'));self.temp.cleanup()

    def approve(self,rollback=False):
        return dict(decision='approve_exact_mesh_runtime_rollback' if rollback else 'approve_exact_mesh_runtime_overlay',planSha256=overlay.plan_hash(self.plan))

    def test_preview_and_exact_apply_rollback_preserve_all_original_bytes(self):
        self.assertTrue(overlay.inspect_overlay(self.plan)['createsNothing']);self.assertFalse((self.root/'journal').exists())
        self.assertEqual(overlay.apply_overlay(self.plan,self.approve())['state'],'installed')
        self.assertEqual((self.live/'lib/new.mjs').read_bytes(),(self.payload/'lib/new.mjs').read_bytes())
        self.assertRaises(RuntimeError,overlay.apply_overlay,self.plan,self.approve())
        self.assertEqual(overlay.rollback_overlay(self.plan,self.approve(True))['state'],'original')
        self.assertEqual((self.live/'lib/a.mjs').read_bytes(),b'// exact original\r\n');self.assertFalse((self.live/'lib/new.mjs').exists())
        self.assertEqual((self.live/'UNRELATED.txt').read_text(),'Preserve user work')
        self.assertEqual((self.root/'journal/before/lib/a.mjs').read_bytes(),b'// exact original\r\n')

    def test_missing_wrong_or_extra_approval_never_creates_a_journal(self):
        for approval in ({},dict(decision='wrong',planSha256=overlay.plan_hash(self.plan)),{**self.approve(),'notApproved':True}):
            self.assertRaises(RuntimeError,overlay.apply_overlay,self.plan,approval)
        self.assertFalse((self.root/'journal').exists());self.assertEqual((self.live/'lib/a.mjs').read_bytes(),b'// exact original\r\n')

    def test_existing_ui_files_replace_and_restore_only_exact_named_originals(self):
        for folder in (self.live, self.payload):
            (folder / 'public').mkdir()
        files = []
        for name in ('app.js', 'index.html', 'styles.css'):
            rel = 'public/' + name
            (self.live / rel).write_bytes(b'original ' + name.encode())
            (self.payload / rel).write_bytes(b'updated ' + name.encode())
            files.append(dict(relativePath=rel, beforeSha256=overlay.digest(self.live / rel),
                              afterSha256=overlay.digest(self.payload / rel)))
        self.plan['files'] = files
        for entry in files:
            missing_original = dict(entry, beforeSha256=None)
            with self.subTest(path=entry['relativePath']):
                self.assertRaises(RuntimeError, overlay.checked, dict(self.plan, files=[missing_original]))
        for rel in ('public/custom.js', 'public/help.html', 'public/theme.css'):
            (self.payload / rel).write_bytes(b'other')
            (self.live / rel).write_bytes(b'prior')
            other = dict(relativePath=rel, beforeSha256=overlay.digest(self.live / rel),
                         afterSha256=overlay.digest(self.payload / rel))
            with self.subTest(path=rel):
                self.assertRaises(RuntimeError, overlay.checked, dict(self.plan, files=[other]))
        self.assertEqual(overlay.apply_overlay(self.plan, self.approve())['state'], 'installed')
        for entry in files:
            self.assertEqual(overlay.digest(self.live / entry['relativePath']), entry['afterSha256'])
        self.assertEqual(overlay.rollback_overlay(self.plan, self.approve(True))['state'], 'original')
        for entry in files:
            self.assertEqual(overlay.digest(self.live / entry['relativePath']), entry['beforeSha256'])

    def test_after_backup_receipt_keeps_exact_identity_and_quiescence_guards(self):
        self.plan['runtime']['serviceAttemptPath']=str(self.ops/'fixture-service-attempt-after-backup.json')
        self.assertTrue(overlay.inspect_overlay(self.plan)['createsNothing'])
        observer=overlay.roles();attempt=Path(self.plan['runtime']['serviceAttemptPath'])
        record=dict(schema='onoes-mind-project-service-attempt/v1',profileSha256='a'*64,
            state='started',runId='fixture-after-backup',pid=os.getpid(),creationTicks=observer.current_ticks())
        attempt.write_text(json.dumps(record))
        self.assertRaises(RuntimeError,overlay.apply_overlay,self.plan,self.approve())
        self.assertFalse((self.root/'journal').exists())
        record.update(pid=self.plan['runtime']['meshPid'],creationTicks=self.plan['runtime']['meshCreationTicks'],profileSha256='b'*64)
        attempt.write_text(json.dumps(record));self.assertRaises(RuntimeError,overlay.apply_overlay,self.plan,self.approve())
        record['profileSha256']='a'*64;attempt.write_text(json.dumps(record))
        self.assertEqual(overlay.apply_overlay(self.plan,self.approve())['state'],'installed')
        self.assertEqual(overlay.rollback_overlay(self.plan,self.approve(True))['state'],'original')
        for name in ('fixture-service-attempt-after-backup.json.extra','fixture-attempt-after-backup.json'):
            p=copy.deepcopy(self.plan);p['runtime']['serviceAttemptPath']=str(self.ops/name)
            self.assertRaises(RuntimeError,overlay.checked,p)

    def test_managed_writer_requires_its_original_receipt_for_install_and_rollback(self):
        runtime=self.plan['runtime']
        attempt=self.ops/'mesh-runtime-recovery-20261121-writer-attemptPath.json'
        runtime['serviceAttemptPath']=str(attempt)
        self.assertRaises(RuntimeError,overlay.apply_overlay,self.plan,self.approve())
        observed=overlay.roles()
        record=dict(schema='onoes-mind-project-service-attempt/v1',state='started',runId='fixture',
            pid=os.getpid(),creationTicks=observed.current_ticks(),profileSha256=runtime['serviceProfileSha256'])
        attempt.write_text(json.dumps(record))
        self.assertRaises(RuntimeError,overlay.apply_overlay,self.plan,self.approve())
        record.update(pid=runtime['meshPid'],creationTicks=runtime['meshCreationTicks'],profileSha256='0'*64)
        attempt.write_text(json.dumps(record))
        self.assertRaises(RuntimeError,overlay.apply_overlay,self.plan,self.approve())
        self.assertFalse((self.root/'journal').exists())
        record['profileSha256']=runtime['serviceProfileSha256']
        attempt.write_text(json.dumps(record))
        self.assertEqual(overlay.apply_overlay(self.plan,self.approve())['state'],'installed')
        attempt.unlink()
        self.assertRaises(RuntimeError,overlay.rollback_overlay,self.plan,self.approve(True))
        attempt.write_text(json.dumps(record))
        self.assertEqual(overlay.rollback_overlay(self.plan,self.approve(True))['state'],'original')

    def test_exact_startup_helpers_install_and_rollback_without_allowing_other_python(self):
        expected={f'integrations/{name}.py' for name in (
            'mesh_startup_candidate','mesh_recovery_candidate','mesh_native_recovery',
            'mesh_native_pair','mesh_launcher_window')}
        self.assertEqual(overlay.STARTUP_HELPERS,expected)
        for rel in sorted(expected):
            for base in (self.live,self.payload):(base/rel).parent.mkdir(exist_ok=True)
            (self.payload/rel).write_bytes(b'# exact approved startup helper\n')
            before=None
            if rel.endswith('/mesh_native_pair.py'):
                (self.live/rel).write_bytes(b'# previous helper\r\n');before=overlay.digest(self.live/rel)
            self.plan['files'].append(dict(relativePath=rel,beforeSha256=before,afterSha256=overlay.digest(self.payload/rel)))
        self.assertTrue(overlay.inspect_overlay(self.plan)['createsNothing'])
        self.assertEqual(overlay.apply_overlay(self.plan,self.approve())['state'],'installed')
        for rel in expected:self.assertEqual((self.live/rel).read_bytes(),(self.payload/rel).read_bytes())
        self.assertEqual(overlay.rollback_overlay(self.plan,self.approve(True))['state'],'original')
        for rel in expected:
            if rel.endswith('/mesh_native_pair.py'):self.assertEqual((self.live/rel).read_bytes(),b'# previous helper\r\n')
            else:self.assertFalse((self.live/rel).exists())
        for rel in ('integrations/other.py','integrations/mesh_startup_candidate.py.extra','integrations/../mesh_startup_candidate.py'):
            p=copy.deepcopy(self.plan);p['files'][-1]['relativePath']=rel
            self.assertRaises(RuntimeError,overlay.inspect_overlay,p)

    def test_changed_payload_original_or_tool_hash_refuses_before_any_write(self):
        p=copy.deepcopy(self.plan);p['toolSha256']='0'*64;self.assertRaises(RuntimeError,overlay.inspect_overlay,p)
        p=copy.deepcopy(self.plan);p['observerSha256']='0'*64;self.assertRaises(RuntimeError,overlay.inspect_overlay,p)
        (self.payload/'lib/a.mjs').write_text('Unreviewed payload');self.assertRaises(RuntimeError,overlay.inspect_overlay,self.plan)
        (self.payload/'lib/a.mjs').write_bytes(b'// qualified replacement\n')
        (self.live/'lib/a.mjs').write_text('User edit');self.assertRaises(RuntimeError,overlay.apply_overlay,self.plan,self.approve())
        self.assertEqual((self.live/'lib/a.mjs').read_text(),'User edit');self.assertFalse((self.root/'journal').exists())

    def test_noncode_traversal_and_overlapping_roots_refuse(self):
        for rel in ('../outside.mjs','data/tasks.sqlite','integrations/private.json','lib/../a.mjs','lib\\a.mjs'):
            p=copy.deepcopy(self.plan);p['files'][0]['relativePath']=rel;self.assertRaises((RuntimeError,ValueError),overlay.inspect_overlay,p)
        p=copy.deepcopy(self.plan);p['journalRoot']=str(self.live/'journal');self.assertRaises(RuntimeError,overlay.inspect_overlay,p)
        self.assertFalse((self.root/'journal').exists())

    def test_live_mesh_or_occupied_gateway_or_uncertain_service_blocks_apply(self):
        original=copy.deepcopy(self.plan['runtime']);observer=overlay.roles()
        self.plan['runtime'].update(meshPid=os.getpid(),meshCreationTicks=observer.current_ticks())
        self.assertRaises(RuntimeError,overlay.apply_overlay,self.plan,self.approve());self.plan['runtime']=original
        with socket.socket() as listener:
            listener.setsockopt(socket.SOL_SOCKET,socket.SO_EXCLUSIVEADDRUSE,1);listener.bind(('127.0.0.1',original['gatewayPort']))
            self.assertRaises(OSError,overlay.apply_overlay,self.plan,self.approve())
        Path(original['serviceAttemptPath']).write_text(json.dumps(dict(schema='onoes-mind-project-service-attempt/v1',profileSha256='a'*64,state='identity_pending',pid=123,creationTicks=None)))
        self.assertRaises(RuntimeError,overlay.apply_overlay,self.plan,self.approve());self.assertFalse((self.root/'journal').exists())

    def test_lost_write_reply_uses_same_journal_and_rolls_back_a_known_partial_install(self):
        actual=overlay.write_atomic
        def lose_reply(path,body):
            actual(path,body)
            if path==self.live/'lib/a.mjs':raise OSError('Synthetic lost replacement reply')
        with patch.object(overlay,'write_atomic',side_effect=lose_reply):
            self.assertRaises(RuntimeError,overlay.apply_overlay,self.plan,self.approve())
        self.assertEqual(overlay.inspect_overlay(self.plan)['state'],'partial')
        self.assertRaises(RuntimeError,overlay.apply_overlay,self.plan,self.approve())
        self.assertEqual(overlay.rollback_overlay(self.plan,self.approve(True))['state'],'original')

    def test_live_known_service_and_changed_before_image_refuse(self):
        observer=overlay.roles();attempt=Path(self.plan['runtime']['serviceAttemptPath'])
        attempt.write_text(json.dumps(dict(schema='onoes-mind-project-service-attempt/v1',profileSha256='a'*64,
            state='started',runId='fixture-run',pid=os.getpid(),creationTicks=observer.current_ticks())))
        self.assertRaises(RuntimeError,overlay.apply_overlay,self.plan,self.approve());self.assertFalse((self.root/'journal').exists())
        attempt.unlink();overlay.apply_overlay(self.plan,self.approve())
        (self.root/'journal/before/lib/a.mjs').write_text('Changed recovery evidence')
        self.assertRaises(RuntimeError,overlay.rollback_overlay,self.plan,self.approve(True))
        self.assertEqual((self.live/'lib/a.mjs').read_bytes(),b'// qualified replacement\n')

    def test_later_user_edit_or_replaced_new_file_is_never_deleted_by_rollback(self):
        overlay.apply_overlay(self.plan,self.approve());(self.live/'lib/new.mjs').write_text('Later user work')
        self.assertRaises(RuntimeError,overlay.rollback_overlay,self.plan,self.approve(True))
        self.assertEqual((self.live/'lib/new.mjs').read_text(),'Later user work')
        (self.live/'lib/new.mjs').write_bytes((self.payload/'lib/new.mjs').read_bytes())
        replacement=self.root/'user-replacement';replacement.write_bytes((self.payload/'lib/new.mjs').read_bytes());os.replace(replacement,self.live/'lib/new.mjs')
        self.assertRaises(RuntimeError,overlay.rollback_overlay,self.plan,self.approve(True));self.assertTrue((self.live/'lib/new.mjs').exists())


    def fresh_record(self,entry,pid,ticks,state=None):
        mesh=entry['kind']=='mesh'
        record=dict(schema='onoes-mesh-native-child/v1' if mesh else 'onoes-mind-project-service-attempt/v1',
            profileSha256=entry['profileSha256'],state=state or ('input_sent' if mesh else 'started'),pid=pid,creationTicks=ticks)
        if mesh:record.update(entryPoint=str(self.live/'serve.mjs'),credentialsInRecord=False)
        else:record['runId']='fixture-fresh-run'
        Path(entry['path']).write_text(json.dumps(record),encoding='utf-8')

    def owned_waiting_child(self):
        child=subprocess.Popen([sys.executable,'-c','import sys;sys.stdin.buffer.read(1)'],stdin=subprocess.PIPE,
            creationflags=subprocess.CREATE_NO_WINDOW)
        ticks=overlay.roles().creation_ticks(child._handle)
        def close():
            if not child.stdin.closed:child.stdin.close()
            child.wait(timeout=10)
        self.addCleanup(close)
        return child,ticks

    def test_v1_or_omitted_duplicate_or_aliased_fresh_attempts_refuse(self):
        for kind in ('old','missing','empty','duplicate','inside','no-mesh'):
            p=copy.deepcopy(self.plan)
            if kind=='old':p['schema']='onoes-mesh-runtime-overlay/v1'
            elif kind=='missing':del p['runtime']['freshLaunchAttempts']
            elif kind=='empty':p['runtime']['freshLaunchAttempts']=[]
            elif kind=='duplicate':p['runtime']['freshLaunchAttempts'].append(p['runtime']['freshLaunchAttempts'][0])
            elif kind=='inside':p['runtime']['freshLaunchAttempts'][0]['path']=str(self.live/'attempt.json')
            else:p['runtime']['freshLaunchAttempts']=[p['runtime']['freshLaunchAttempts'][1]]
            with self.subTest(kind=kind):self.assertRaises(RuntimeError,overlay.inspect_overlay,p)
        self.assertFalse((self.root/'journal').exists())

    def test_live_prelistener_mesh_and_second_service_refuse_apply_and_rollback(self):
        child,ticks=self.owned_waiting_child();entries=self.plan['runtime']['freshLaunchAttempts']
        for entry in entries:
            self.fresh_record(entry,child.pid,ticks)
            with self.subTest(kind=entry['kind']):self.assertRaises(RuntimeError,overlay.apply_overlay,self.plan,self.approve())
            self.assertIsNone(child.poll());self.assertFalse((self.root/'journal').exists());Path(entry['path']).unlink()
        overlay.apply_overlay(self.plan,self.approve())
        for entry in entries:
            self.fresh_record(entry,child.pid,ticks)
            self.assertRaises(RuntimeError,overlay.rollback_overlay,self.plan,self.approve(True))
            self.assertEqual((self.live/'lib/a.mjs').read_bytes(),b'// qualified replacement\n')
            Path(entry['path']).unlink()
        child.stdin.close();self.assertEqual(child.wait(timeout=10),0)
        for entry in entries:self.fresh_record(entry,child.pid,ticks)
        self.assertEqual(overlay.rollback_overlay(self.plan,self.approve(True))['state'],'original')

    def test_pending_mismatched_or_malformed_fresh_receipt_refuses(self):
        entry=self.plan['runtime']['freshLaunchAttempts'][0];retired=self.plan['runtime']
        for change in ('pending','wrong-profile','no-birth','wrong-entry','credentials','malformed'):
            self.fresh_record(entry,retired['meshPid'],retired['meshCreationTicks'])
            path=Path(entry['path']);record=json.loads(path.read_text())
            if change=='pending':record['state']='input_pending'
            elif change=='wrong-profile':record['profileSha256']='0'*64
            elif change=='no-birth':record['creationTicks']=None
            elif change=='wrong-entry':record['entryPoint']=str(self.root/'some-other.mjs')
            elif change=='credentials':record['credentialsInRecord']=True
            if change=='malformed':path.write_text('{')
            else:path.write_text(json.dumps(record))
            with self.subTest(change=change):self.assertRaises((RuntimeError,ValueError),overlay.apply_overlay,self.plan,self.approve())
        self.assertFalse((self.root/'journal').exists())

    def test_fresh_owner_appearing_mid_apply_preserves_partial_and_requires_retirement(self):
        child,ticks=self.owned_waiting_child();entry=self.plan['runtime']['freshLaunchAttempts'][0]
        actual=overlay.write_atomic
        def start_during_write(path,body):
            actual(path,body)
            if path==self.live/'lib/a.mjs':self.fresh_record(entry,child.pid,ticks)
        with patch.object(overlay,'write_atomic',side_effect=start_during_write):
            self.assertRaises(RuntimeError,overlay.apply_overlay,self.plan,self.approve())
        self.assertEqual(overlay.inspect_overlay(self.plan)['state'],'partial')
        self.assertFalse((self.live/'lib/new.mjs').exists());self.assertIsNone(child.poll())
        self.assertRaises(RuntimeError,overlay.rollback_overlay,self.plan,self.approve(True))
        child.stdin.close();self.assertEqual(child.wait(timeout=10),0)
        self.assertEqual(overlay.rollback_overlay(self.plan,self.approve(True))['state'],'original')


if __name__=='__main__':unittest.main()
