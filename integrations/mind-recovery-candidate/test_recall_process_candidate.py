"""Real Windows child roles and actual Mesh client; all profiles/data are TEMP."""
from dataclasses import asdict
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
import time
import unittest
import urllib.request
import urllib.error
import uuid
import hashlib
import mesh_launch_candidate as mesh_launch
from unittest.mock import patch

from onoes_mind.ledger import Ledger
from onoes_mind.recall_binding import RecallBinding, prepare_store_identity
from onoes_mind.runtime_keys import protect_runtime_keys
from persistent_authority import PersistentAuthorityCandidate
import recall_process_candidate as roles
import test_operator_setup_candidate as fixtures
from test_native_recall_candidate import NODE


@unittest.skipUnless(sys.platform=='win32','Actual Windows owned-process identity')
class NativeRoleProcessTests(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.OperatorSetupCandidateTests();self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.database=(self.fixture.data/'ledger.sqlite').resolve()
        self.history=Path(str(self.database)+'.deletions.jsonl')
        self.environment='synthetic-process-handoff'
        keys=dict(audit_key=secrets.token_bytes(32),deletion_key=secrets.token_bytes(32))
        source=Ledger(self.database,deletion_ledger_path=self.history,environment_id=self.environment,**keys)
        try:
            store=prepare_store_identity(source,environment=self.environment,authority_ref='fixture:owner')
            authority=PersistentAuthorityCandidate.create(self.fixture.authority,source,
                store_id=store,environment=self.environment,review_ref='fixture:authority')
        finally:source.close()
        self.key_package=self.fixture.data/'key-enrollment.json'
        self.key_package.write_text(json.dumps(dict(schema='onoes-mind-key-enrollment/v1',storeId=store,
            environment=self.environment,recovery_envelope={'fixture':'not-used'},
            runtime_envelope=protect_runtime_keys(store_id=store,environment_id=self.environment,**keys))))
        authority_path=self.fixture.data/'checkpoint-authority-binding.json'
        authority_path.write_text(json.dumps(asdict(authority.binding)))
        stat=self.database.stat()
        binding=RecallBinding(str(self.database),store,self.environment,'fixture:owner','project/onoes-mind/shared',
            stat.st_dev,stat.st_ino,'fixture:custodian','fixture:revoke','fixture:process-review')
        package=Path(__import__('onoes_mind').__file__).resolve().parent
        runtime=dict(python=sys.executable,pwsh=shutil.which('pwsh'),mindSource=str(package.parent))
        sid=subprocess.run([runtime['pwsh'],'-NoProfile','-Command',
            '[Security.Principal.WindowsIdentity]::GetCurrent().User.Value'],capture_output=True,text=True,
            check=True,creationflags=subprocess.CREATE_NO_WINDOW).stdout.strip()
        root=self.fixture.backup
        common=dict(schema=roles.SCHEMA,ownerSid=sid,runtime=runtime,
            sourceHashes={str(p):roles.digest(p) for p in roles.source_paths(runtime)},binding=asdict(binding),
            credentialPath=str(root/'service.json'),outcomePath=str(root/'outcome.json'),
            terminalPath=str(root/'terminal.json'),operationId='fixture:process-operation',reviewRef=binding.review_ref)
        self.operator=root/'operator.json';self.reader=root/'reader.json';self.approval=root/'approval.json'
        self.operator_data=dict(common,role='operator',keyEnrollmentPath=str(self.key_package),
            authorityBindingPath=str(authority_path),historyPath=str(self.history),attemptPath=str(root/'attempt.json'))
        self.operator.write_text(json.dumps(self.operator_data,indent=2));self.operator_sha=roles.digest(self.operator)
        self.reader_data=dict(common,role='reader',operatorProfileSha256=self.operator_sha,
            readyPath=str(root/'reader-owner.json'),stopPath=str(root/'reader-stop.json'))
        self.reader.write_text(json.dumps(self.reader_data,indent=2));self.reader_sha=roles.digest(self.reader)
        self.approval_data=dict(decision=roles.DECISION,ownerSid=sid,profiles=[self.operator_sha,self.reader_sha],
            scopeId=binding.scope_id,reviewRef=binding.review_ref)
        self.approval.write_text(json.dumps(self.approval_data))
        self.children=[];self.addCleanup(self.close_owned_children)

    def close_owned_children(self):
        # Test-owned handles only. All production data paths are excluded.
        for child in self.children:
            if child.poll() is None:
                child.terminate();child.wait(timeout=15)

    def cli(self,path,sha,*,run=False,approval=True,input_text=None):
        args=[sys.executable,str(Path(roles.__file__)),'--profile',str(path),'--sha256',sha]
        if run:args+=['--run']
        if approval:args+=['--approval',str(self.approval)]
        return subprocess.run(args,input=input_text,capture_output=True,text=True,timeout=30,
                              creationflags=subprocess.CREATE_NO_WINDOW)

    def test_preview_and_missing_approval_never_create_an_attempt_or_grant(self):
        for path,sha in ((self.operator,self.operator_sha),(self.reader,self.reader_sha)):
            preview=self.cli(path,sha,approval=False)
            self.assertEqual(preview.returncode,0,preview.stdout+preview.stderr)
            self.assertTrue(json.loads(preview.stdout)['createsNothing'])
        refused=self.cli(self.operator,self.operator_sha,run=True,approval=False)
        self.assertEqual(refused.returncode,1)
        self.assertFalse(Path(self.operator_data['attemptPath']).exists())
        self.assertFalse(Path(self.operator_data['outcomePath']).exists())
        self.assertFalse(Path(self.operator_data['credentialPath']).exists())

    def test_terminal_operator_then_fresh_reader_without_key_package_feeds_actual_mesh_client(self):
        operator,stamp=roles.launch_operator(self.operator,self.operator_sha,self.approval);self.children.append(operator)
        self.assertEqual(operator.wait(timeout=60),0)
        unrelated=subprocess.Popen([sys.executable,'-c','pass'],creationflags=subprocess.CREATE_NO_WINDOW)
        self.children.append(unrelated);unrelated_stamp=roles.creation_ticks(unrelated._handle);unrelated.wait(timeout=15)
        with self.assertRaises(roles.RoleError):
            roles.finish_operator(unrelated,unrelated_stamp,self.operator,self.operator_sha,self.approval)
        self.assertFalse(Path(self.operator_data['terminalPath']).exists())
        receipt=roles.finish_operator(operator,stamp,self.operator,self.operator_sha,self.approval)
        self.assertEqual(receipt['pid'],operator.pid);self.assertFalse(roles.same_process_alive(operator.pid,stamp))
        with self.assertRaises(roles.RoleError):roles.launch_operator(self.operator,self.operator_sha,self.approval)
        # A genuine separate Windows process cannot inherit the test heap. Removing
        # the encrypted integrity-key package also proves no reader fallback opens it.
        parked=self.key_package.with_name('key-enrollment.fixture-unavailable')
        for path in (self.key_package,parked):self.assertTrue(path.resolve().is_relative_to(self.fixture.root))
        self.key_package.rename(parked)
        reader,reader_stamp=roles.launch_reader(self.reader,self.reader_sha,self.approval);self.children.append(reader)
        ready_path=Path(self.reader_data['readyPath']);deadline=time.monotonic()+30
        while time.monotonic()<deadline:
            self.assertIsNone(reader.poll(),'Reader exited before ready')
            try:ready=json.loads(ready_path.read_text())
            except (FileNotFoundError,json.JSONDecodeError):ready={}
            if ready.get('state')=='running':break
            time.sleep(0.1)
        state=roles.reader_state(self.reader,self.reader_sha,self.approval)
        self.assertTrue(state['ready']);self.assertEqual(state['pid'],reader.pid)
        self.assertEqual(state['creationTicks'],reader_stamp);self.assertNotEqual(reader.pid,operator.pid)
        self.assertNotIn('keyEnrollmentPath',self.reader_data)
        self.assertNotIn('runtime_envelope',ready_path.read_text())
        options=roles.native_options(self.reader,self.reader_sha,self.approval)
        self.assertNotIn(options['token'],ready_path.read_text())
        result=subprocess.run([shutil.which('node'),'--input-type=module','-e',NODE,
            str(Path(__file__).resolve().parents[2]/'lib/mind-recall.mjs')],input=json.dumps(options),
            capture_output=True,text=True,timeout=15,creationflags=subprocess.CREATE_NO_WINDOW)
        self.assertEqual(result.returncode,0,result.stderr);response=json.loads(result.stdout)
        self.assertTrue(response['ok']);self.assertEqual(response['result']['records'],[])
        # Launch the real application through the fixed inherited-input entry.
        # No secret argument/environment/file; the writer keys remain parked.
        root=self.fixture.backup;gate_key=root/'gate.key';gate_key.write_text('synthetic-gateway-token')
        settings=dict(MESH_DATA_DIR='data/native-process-'+uuid.uuid4().hex,MESH_RELAY='0',
            MESH_RELAY_MODE='child',MESH_MODEL_OBSERVATION='0',MESH_NEMOTRON_CONTROL='0',
            MESH_SIMPLE_FLOW='0',MESH_NIMS='0',MESH_PREVIEW_PORT='0',
            MESH_TAILSCALE_LOGIN='',MESH_TAILSCALE_HOST='',MESH_GATE_KEY_FILE=str(gate_key))
        launch=root/'mesh-launch.json'
        launch_data=dict(schema='onoes-mesh-native-launch/v1',workspace=str(mesh_launch.ROOT),
            pythonExecutable=sys.executable,nodeExecutable=str(Path(shutil.which('node')).resolve()),
            pythonSha256=roles.digest(sys.executable),nodeSha256=roles.digest(shutil.which('node')),
            sourceHashes={str(p):roles.digest(p) for p in mesh_launch.source_paths()},
            readerProfile=str(self.reader),readerProfileSha256=self.reader_sha,settings=settings,
            attemptPath=str(root/'mesh-attempt.json'),stdoutPath=str(root/'mesh.out'),stderrPath=str(root/'mesh.err'))
        launch.write_text(json.dumps(launch_data));launch_sha=roles.digest(launch)
        # A previously approved reader alone does not authorize launching Mesh.
        with self.assertRaises(mesh_launch.LaunchError):mesh_launch.checked_launch(launch,launch_sha,self.approval)
        self.approval_data['profiles'].append(launch_sha);self.approval.write_text(json.dumps(self.approval_data))
        preview=subprocess.run([sys.executable,str(Path(mesh_launch.__file__)),'--profile',str(launch),
            '--sha256',launch_sha,'--approval',str(self.approval)],capture_output=True,text=True,
            timeout=45,creationflags=subprocess.CREATE_NO_WINDOW)
        self.assertEqual(preview.returncode,0,preview.stdout);self.assertTrue(json.loads(preview.stdout)['createsNothing'])
        self.assertFalse(Path(launch_data['attemptPath']).exists())
        with patch.dict(os.environ,{'NODE_OPTIONS':'--require=not-a-real-preload','MESH_NATIVE_WORKER_RECORD':'not-a-real-worker'}):
            app,app_stamp,app_receipt=mesh_launch.launch_mesh(launch,launch_sha,self.approval)
        self.children.append(app)
        self.assertEqual(app_receipt['creationTicks'],app_stamp);self.assertEqual(app_receipt['pid'],app.pid)
        with self.assertRaises(roles.RoleError):mesh_launch.launch_mesh(launch,launch_sha,self.approval)
        deadline=time.monotonic()+20;line=''
        while time.monotonic()<deadline:
            self.assertIsNone(app.poll(),'Native Mesh exited before ready')
            lines=Path(launch_data['stdoutPath']).read_text().splitlines()
            if lines:line=lines[0];break
            time.sleep(0.1)
        self.assertNotIn(options['token'],Path(launch_data['attemptPath']).read_text())
        self.assertNotIn(options['token'],line)
        app_state=json.loads(line);self.assertEqual(app_state['event'],'mesh_listening')
        self.assertEqual(app_state['pid'],app.pid)
        url=app_state['previewUrl']
        gate_cookie='mesh_session='+hashlib.sha256(b'mesh-cookie:synthetic-gateway-token').hexdigest()
        bootstrap=urllib.request.Request(url+'/api/trial-session/bootstrap',data=b'{}',
            headers={'Origin':url,'Content-Type':'application/json','Cookie':gate_cookie},method='POST')
        with urllib.request.urlopen(bootstrap,timeout=10) as boot:
            cookie=gate_cookie+'; '+boot.headers['Set-Cookie'].split(';')[0];csrf=json.load(boot)['csrfToken']
        def request(path,body=None):
            return urllib.request.urlopen(urllib.request.Request(url+path,
                data=json.dumps(body).encode() if body is not None else None,
                headers={'Origin':url,'Content-Type':'application/json','Cookie':cookie,'X-Trial-CSRF':csrf}),timeout=10)
        with request('/api/mind/recall',dict(query='fixture',limit=8)) as response:
            self.assertEqual(json.load(response)['records'],[])
        with self.assertRaises(roles.RoleError):roles.launch_reader(self.reader,self.reader_sha,self.approval)
        roles.request_stop(self.reader,self.reader_sha,self.approval)
        self.assertEqual(reader.wait(timeout=15),0)
        state=roles.reader_state(self.reader,self.reader_sha,self.approval)
        self.assertFalse(state['processLive']);self.assertEqual(state['state'],'stopped')
        with self.assertRaises(urllib.error.HTTPError) as denied:request('/api/mind/recall',dict(query='fixture',limit=8))
        self.assertEqual(denied.exception.code,503)
        self.assertNotIn(options['token'],denied.exception.read().decode());denied.exception.close()
        with request('/api/tasks') as tasks:self.assertIsInstance(json.load(tasks)['tasks'],list)
        self.assertIsNone(app.poll(),'Reader shutdown must not stop Mesh')
        app.terminate();app.wait(timeout=15)
        self.assertFalse(self.key_package.exists());self.assertTrue(parked.exists())

    def test_reader_refuses_fake_terminal_receipt_for_a_still_live_process(self):
        roles.private_new_json(self.reader_data['terminalPath'],dict(operatorProfileSha256=self.operator_sha,
            pid=os.getpid(),creationTicks=roles.current_ticks(),exitCode=0,
            operationId=self.reader_data['operationId'],storeId=self.reader_data['binding']['store_id'],outcomeSha256='0'*64))
        actual=roles.subprocess.Popen;reader_starts=[]
        def track(*args,**kwargs):
            child=actual(*args,**kwargs)
            if str(Path(roles.__file__)) in args[0] and str(self.reader) in args[0]:
                reader_starts.append(child.pid);self.children.append(child)
            return child
        with patch.object(roles.subprocess,'Popen',side_effect=track):
            with self.assertRaises(roles.RoleError):roles.launch_reader(self.reader,self.reader_sha,self.approval)
            self.assertEqual(reader_starts,[])
        refused=self.cli(self.reader,self.reader_sha,run=True)
        self.assertEqual(refused.returncode,1)
        self.assertFalse(Path(self.reader_data['readyPath']).exists())

    def test_changed_profile_source_pin_and_reader_key_input_refuse(self):
        original=self.operator.read_bytes();self.operator.write_bytes(original+b' ')
        self.assertEqual(self.cli(self.operator,self.operator_sha,run=True,input_text='START\n').returncode,1)
        self.operator.write_bytes(original)
        broken=dict(self.operator_data);broken['sourceHashes']=dict(broken['sourceHashes'])
        first=next(iter(broken['sourceHashes']));broken['sourceHashes'][first]='0'*64
        self.operator.write_text(json.dumps(broken));changed_sha=roles.digest(self.operator)
        self.approval_data['profiles'].append(changed_sha);self.approval.write_text(json.dumps(self.approval_data))
        self.assertEqual(self.cli(self.operator,changed_sha,run=True,input_text='START\n').returncode,1)
        reader=dict(self.reader_data,keyEnrollmentPath=str(self.key_package))
        self.reader.write_text(json.dumps(reader));reader_sha=roles.digest(self.reader)
        self.approval_data['profiles'].append(reader_sha);self.approval.write_text(json.dumps(self.approval_data))
        self.assertEqual(self.cli(self.reader,reader_sha,run=True).returncode,1)
        self.assertFalse(Path(self.operator_data['outcomePath']).exists())
        self.assertFalse(Path(self.reader_data['readyPath']).exists())

    def test_an_approved_operator_profile_without_parent_start_handshake_cannot_apply(self):
        refused=self.cli(self.operator,self.operator_sha,run=True,input_text='')
        self.assertEqual(refused.returncode,1)
        self.assertFalse(Path(self.operator_data['outcomePath']).exists())
        self.assertFalse(Path(self.operator_data['credentialPath']).exists())

    def test_uncertain_launch_retains_the_same_owned_handle_and_does_not_retry(self):
        with patch.object(roles,'creation_ticks',side_effect=roles.RoleError('fixture observation failure')):
            with self.assertRaises(roles.RoleLaunchUnknown) as error:
                roles.launch_operator(self.operator,self.operator_sha,self.approval)
        child=error.exception.child;self.children.append(child)
        self.assertIsNone(error.exception.creation_ticks)
        self.assertEqual(child.wait(timeout=30),1)  # EOF before START; no privileged action.
        self.assertTrue(Path(self.operator_data['attemptPath']).exists())
        self.assertFalse(Path(self.operator_data['outcomePath']).exists())
        self.assertFalse(Path(self.operator_data['credentialPath']).exists())


if __name__=='__main__':unittest.main()
