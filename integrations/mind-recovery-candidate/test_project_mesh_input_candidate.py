"""Disposable composed launcher; no live profiles, services or model calls."""
import copy
from contextlib import closing
import http.cookiejar
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import urllib.request
import uuid

import mesh_launch_candidate as launch
import project_mesh_input_candidate as composition
import project_service_process_candidate as service
import recall_process_candidate as roles
import test_project_service_process_candidate as fixtures


def admitted_http(base):
    cookies=http.cookiejar.CookieJar()
    opener=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cookies))
    def request(path,payload=None,csrf=None,method='POST'):
        headers={'Origin':base.rstrip('/'),'Content-Type':'application/json'}
        if csrf:headers['X-Trial-CSRF']=csrf
        req=urllib.request.Request(base.rstrip('/')+path,data=None if payload is None else json.dumps(payload).encode(),headers=headers,method=method)
        with opener.open(req,timeout=15) as response:
            body=response.read()
            if response.status==204:
                assert body==b''
                return None
            return json.loads(body)
    return request


def edited_card(card,title):
    # JavaScript omits undefined fields. The task API's owner is optional; do not
    # invent an owner or fail before actually exercising the card edit.
    return dict(title=title,revision=card['revision'],**{n:card[n] for n in ('description','label','status','owner') if n in card})


@unittest.skipUnless(sys.platform=='win32','Windows owned API fixture')
class CardHttpContractTests(unittest.TestCase):
    def test_python_admission_edit_and_readback_use_actual_task_shape(self):
        data=launch.ROOT/'data'/('mesh-card-http-'+uuid.uuid4().hex);data.mkdir()
        self.addCleanup(lambda:shutil.rmtree(data.resolve()) if data.resolve().parent==(launch.ROOT/'data').resolve() else None)
        script="""import {openTaskStore} from './lib/task-store.mjs';import {startApp} from './server.mjs';import path from 'node:path';
const dataDir=process.argv[1];const store=openTaskStore(path.join(dataDir,'tasks.sqlite'));
const card=store.create({title:'Synthetic HTTP contract',description:'Synthetic private fixture'});store.close();
const app=await startApp({dataDir,port:0,standalone:false});console.log(JSON.stringify({url:app.url,cardId:card.id}));
process.stdin.on('end',()=>process.exit(0));process.stdin.resume();"""
        env={k:v for k,v in os.environ.items() if not k.upper().startswith('MESH_') and k.upper() not in ('NODE_OPTIONS','NODE_PATH')}
        child=subprocess.Popen([shutil.which('node'),'--input-type=module','-e',script,data.relative_to(launch.ROOT).as_posix()],cwd=launch.ROOT,env=env,
            stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            # A bounded readiness observation, using only this newly owned child.
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                future=pool.submit(child.stdout.readline)
                try:line=future.result(timeout=20)
                except Exception:
                    child.terminate();child.wait(timeout=15);raise
            if not line:
                child.wait(timeout=5)
                self.fail('Owned HTTP fixture did not become ready: '+child.stderr.read())
            ready=json.loads(line);request=admitted_http(ready['url'])
            csrf=request('/api/trial-session/bootstrap',{})['csrfToken']
            card=request('/api/tasks/'+ready['cardId'],csrf=csrf,method='GET')['task']
            request('/api/tasks/'+ready['cardId'],edited_card(card,'HTTP contract saved'),csrf,method='PATCH')
            saved=request('/api/tasks/'+ready['cardId'],csrf=csrf,method='GET')['task']
            self.assertEqual(saved['title'],'HTTP contract saved')
            self.assertEqual(saved['description'],card['description'])
            request('/api/trial-session/logout',{},csrf)
        finally:
            if not child.stdin.closed:child.stdin.close()
            try:child.wait(timeout=15)
            except subprocess.TimeoutExpired:child.terminate();child.wait(timeout=15)
            child.stdout.close();child.stderr.close()


class NativeFrameTests(unittest.TestCase):
    def test_legacy_recall_frame_does_not_import_or_request_a_writer(self):
        reader = {'binding': {'storeId': 'read-only'}, 'token': 'synthetic-read'}
        p = dict(readerProfile='unused', readerProfileSha256='unused')
        with patch.object(composition, 'project_native_options', side_effect=AssertionError('No writer')):
            self.assertEqual(launch.native_frame(p, SimpleNamespace(native_options=lambda *a: reader), 'unused', 'unused'),
                dict(schema='onoes-mesh-native-recall-input/v1', mindRecallOptions=reader))

    def test_combined_frame_refuses_a_different_canonical_store(self):
        p = dict(schema='onoes-mesh-native-launch/v2',readerProfile='unused',readerProfileSha256='unused')
        reader = {'binding': {'storeId': 'store-A'}}
        with patch.object(composition, 'project_native_options', return_value={'destination': {'storeId': 'store-B'}}):
            with self.assertRaises(launch.LaunchError):
                launch.native_frame(p,SimpleNamespace(native_options=lambda *a: reader),'unused','unused')

    def test_shadowed_composer_refuses_before_import(self):
        p=dict(schema='onoes-mesh-native-launch/v2',readerProfile='unused',readerProfileSha256='unused')
        with patch.object(launch.importlib.util,'find_spec',return_value=SimpleNamespace(origin='unreviewed-helper.py')):
            with self.assertRaises(launch.LaunchError):
                launch.native_frame(p,SimpleNamespace(native_options=lambda *a:{}),'unused','unused')

    def test_node_identity_uses_the_real_runtime_and_ignores_ambient_preload(self):
        node=Path(shutil.which('node')).resolve()
        p=dict(nodeExecutable=str(node),nodeSha256=launch.digest(node),workspace=str(launch.ROOT))
        with tempfile.TemporaryDirectory(prefix='mesh-identity-probe-') as directory:
            database=Path(directory).resolve()/'synthetic-file';database.write_text('synthetic')
            with patch.dict(os.environ,{'NODE_OPTIONS':'--this-preload-option-must-not-be-inherited','NODE_PATH':directory}):
                identity=composition.node_source_identity(p,database)
            actual=subprocess.run([str(node),'--input-type=module','-e',
                "import {statSync} from 'node:fs';const s=statSync(process.argv[1],{bigint:true});console.log(JSON.stringify({fileDevice:String(s.dev),fileInode:String(s.ino)}));",str(database)],
                capture_output=True,text=True,timeout=10,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            self.assertEqual(actual.returncode,0,actual.stderr);self.assertEqual(identity,json.loads(actual.stdout))

    def test_changed_node_binary_pin_refuses_before_probe_execution(self):
        node=Path(shutil.which('node')).resolve()
        with patch.object(composition.subprocess,'run',side_effect=AssertionError('No probe may run')):
            with self.assertRaises(composition.ProjectMeshInputError):
                composition.node_source_identity(dict(nodeExecutable=str(node),nodeSha256='0'*64,workspace=str(launch.ROOT)),launch.ROOT/'package.json')


@unittest.skipUnless(sys.platform == 'win32', 'Windows owned service and Mesh child')
class ProjectMeshLauncherTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.ProjectServiceProcessTests(); self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.reader = self.fixture.base.base
        self.root = self.fixture.profile.parent
        self.data = launch.ROOT/'data'/('mesh-project-launch-'+uuid.uuid4().hex)
        self.data.mkdir()
        self.addCleanup(self.remove_data)
        self.mesh = None
        self.addCleanup(self.close_mesh)

    def remove_data(self):
        resolved = self.data.resolve()
        self.assertEqual(resolved.parent, (launch.ROOT/'data').resolve())
        shutil.rmtree(resolved)

    def close_mesh(self):
        # Retain password-free synthetic child diagnostics before fixture cleanup,
        # including failed startup. Never copy the credential or approval files.
        for name in ('mesh-out.log','mesh-err.log'):
            log=self.root/name
            if log.exists():
                target=launch.ROOT/'data'/('project-sync-composed-'+uuid.uuid4().hex+'-'+name)
                target.write_bytes(log.read_bytes())
                print('Synthetic child diagnostic: '+target.name,file=sys.stderr,flush=True)
        if self.mesh is not None and self.mesh.poll() is None:
            # Exact fresh test-owned child only. Its writer is a separate fixture
            # service which the fixture stops and observes through its own handle.
            self.mesh.terminate(); self.mesh.wait(timeout=30)

    def wait_for(self, action, child=None, timeout=100):
        deadline=time.monotonic()+timeout
        while time.monotonic()<deadline:
            if child is not None:
                status=child.poll()
                if status is not None:
                    error=self.root/'mesh-err.log'
                    self.fail('Owned fixture child exited before readiness: '+str(status)+'; '+
                        (error.read_text() if error.exists() else 'No Mesh child error log'))
            try:
                value=action()
                if value:return value
            except (OSError,ValueError,roles.RoleError): pass
            time.sleep(.2)
        self.fail('Owned fixture observation did not settle; no replacement launched')

    def test_exact_profiles_preflight_then_owned_gateway_delivers_only_approved_fields(self):
        self.exercise_gateway()

    def test_two_project_capture_then_service_only_gateway_delivers_both_linked_cards(self):
        self.exercise_gateway(with_pilot=True)

    def test_paused_rook_needs_a_new_exact_launch_approval_and_coexists_with_project_sync(self):
        self.exercise_gateway(with_rook=True)

    def exercise_gateway(self, with_pilot=False, with_rook=False):
        # Qualify the separate read-only identity first, with original-handle proof.
        child,stamp=roles.launch_operator(self.reader.operator,self.reader.operator_sha,self.reader.approval)
        self.reader.children.append(child); self.assertEqual(child.wait(timeout=120),0)
        roles.finish_operator(child,stamp,self.reader.operator,self.reader.operator_sha,self.reader.approval)
        if with_pilot:
            base=self.fixture.base
            base.value['projects']=[['onoes-mesh','Onoes-Mesh']]
            base.write()
            decision=json.loads(base.approval.read_bytes())
            decision['projects']=['onoes-mesh']
            base.approval.write_text(json.dumps(decision))
        self.fixture.write(actions=['first_setup','run_service','run_mesh_sync'])
        self.fixture.prepare()
        if with_pilot:
            self.fixture.configure_addition('3d-print-pilot','3D Print Pilot')
            self.fixture.write(actions=['add_project'])
            self.fixture.prepare()
            # The recurring launcher receives its own service-only decision.
            runtime_view=self.root/'pilot-service-runtime.json'
            roles.private_new_json(runtime_view,base.value)
            self.fixture.value.update(schema='onoes-mind-project-service/v2',serviceRuntimeProfilePath=str(runtime_view),
                                      serviceRuntimeProfileSha256=launch.digest(runtime_view))
            decision=json.loads(base.approval.read_bytes())
            base.approval=self.root/'pilot-service-only.json'
            self.fixture.profile.write_text(json.dumps(self.fixture.value))
            self.fixture.sha=launch.digest(self.fixture.profile)
            decision.update(actions=['run_service','run_mesh_sync'],profiles=[self.fixture.sha])
            roles.private_new_json(base.approval,decision)
        read_child,read_stamp=roles.launch_reader(self.reader.reader,self.reader.reader_sha,self.reader.approval)
        self.reader.children.append(read_child)
        self.wait_for(lambda:roles.reader_state(self.reader.reader,self.reader.reader_sha,self.reader.approval)['ready'],read_child)
        service_child,service_stamp=service.launch_service(self.fixture.profile,self.fixture.sha,self.fixture.base.approval)
        self.fixture.children.append((service_child,service_stamp));self.fixture.ready(service_child)

        database=self.data/'tasks.sqlite'
        source = """import {openTaskStore} from './lib/task-store.mjs';
import {statSync,realpathSync} from 'node:fs';
import path from 'node:path';import {createHash} from 'node:crypto';
import {projectSnapshot} from './integrations/workroom-project-sync-candidate.mjs';
import {canonicalProjectEvent} from './integrations/project-sync-outbox-candidate.mjs';
import {inspectProjectSource,prepareProjectSource} from './integrations/project-sync-source-setup-candidate.mjs';
const store=openTaskStore(process.argv[1]);
const card=store.create({title:'Synthetic composed launcher',description:'EXCLUDED-PRIVATE-PROSE',owner:'nims'});
const link={cardId:card.id,projectId:process.argv[3],approvalRef:'fixture:launch-sharing',fields:['title','stage']};
const snapshot=projectSnapshot(store.workroom.get(card.id),link.fields);
const links=[link];
let pilotPlan;
if(process.argv[3]==='onoes-mesh'){
  const pilot=store.create({title:'Pilot coupon draft',owner:'nims'});
  const task=store.workroom.get(pilot.id);
  store.workroom.saveProgress(pilot.id,{goal:'Coupon v1, 24 x 16 x 3 mm, coupon-v1.scad',checklist:[],
    result:'',evidence:'',reviewer:'',decision:'pending',revision:task.progress.revision,
    taskRevision:task.revision,briefRevision:task.workroom.revision});
  const pilotLink={cardId:pilot.id,projectId:'3d-print-pilot',approvalRef:'fixture:pilot',fields:['title','stage','goal']};
  const selected=projectSnapshot(store.workroom.get(pilot.id),pilotLink.fields);
  pilotPlan={...pilotLink,revisions:selected.revisions,projectionSha256:selected.evidence[0].content_hash.slice(7)};
  links.push(pilotLink);
}
store.close();
const s=statSync(process.argv[1],{bigint:true}),source={databasePath:realpathSync(process.argv[1]),fileDevice:String(s.dev),fileInode:String(s.ino)};
const projectionSha256=createHash('sha256').update(canonicalProjectEvent({revisions:snapshot.revisions,snapshot:snapshot.snapshot})).digest('hex');
const plan={schema:'onoes-mesh-project-source-setup/v1',workspace:realpathSync(process.cwd()),dataDir:path.relative(process.cwd(),path.dirname(process.argv[1])).split(path.sep).join('/'),source,storeId:process.argv[2],links:[{...link,revisions:snapshot.revisions,projectionSha256}]};
const preview=inspectProjectSource(plan);const receipt=prepareProjectSource(plan,{decision:'approve_exact_mesh_project_source_setup',planSha256:preview.planSha256});
if(receipt.baselines.length!==1||inspectProjectSource(plan).baselines[0].eventId!==receipt.baselines[0].eventId)throw Error('Source preparation readback failed');
if(pilotPlan){
  const {inspectProjectSourceAddition,prepareProjectSourceAddition}=await import('./integrations/project-sync-source-setup-candidate.mjs');
  plan.links.push(pilotPlan);
  const add=inspectProjectSourceAddition(plan,pilotPlan.cardId);
  prepareProjectSourceAddition(plan,{decision:'approve_exact_mesh_project_source_addition',addedCardId:pilotPlan.cardId,planSha256:add.planSha256});
}
const {databaseFileIdentity}=await import('./lib/database-identity.mjs');
console.log(JSON.stringify({link,links,source,boardIdentity:databaseFileIdentity(process.argv[1])}));"""
        initialized=subprocess.run([shutil.which('node'),'--input-type=module','-e',source,str(database),self.reader.reader_data['binding']['store_id'],
                                    'onoes-mesh' if with_pilot else 'project-A'],
            cwd=launch.ROOT,capture_output=True,text=True,timeout=30,creationflags=subprocess.CREATE_NO_WINDOW)
        self.assertEqual(initialized.returncode,0,initialized.stderr)
        initialized=json.loads(initialized.stdout);link=initialized['link']
        gate=self.root/'mesh-gate.txt';gate.write_text('synthetic-gate-key-for-owned-launcher-only',encoding='utf-8')
        settings={name:'0' for name in launch.SETTINGS}
        settings.update(MESH_PREVIEW_PORT='0',MESH_DATA_DIR=self.data.relative_to(launch.ROOT).as_posix(),MESH_RELAY_MODE='http',
            MESH_GATE_KEY_FILE=str(gate),MESH_TAILSCALE_HOST='synthetic.invalid')
        node=Path(shutil.which('node')).resolve()
        p=dict(schema='onoes-mesh-native-launch/v2',workspace=str(launch.ROOT),pythonExecutable=sys.executable,nodeExecutable=str(node),
            pythonSha256=launch.digest(sys.executable),nodeSha256=launch.digest(node),
            sourceHashes={str(n):launch.digest(n) for n in launch.source_paths(project=True)},
            readerProfile=str(self.reader.reader),readerProfileSha256=self.reader.reader_sha,settings=settings,
            attemptPath=str(self.root/'mesh-attempt.json'),stdoutPath=str(self.root/'mesh-out.log'),stderrPath=str(self.root/'mesh-err.log'),
            projectSync=dict(serviceProfile=str(self.fixture.profile),serviceProfileSha256=self.fixture.sha,approvalPath=str(self.fixture.base.approval),
                source=initialized['source'],links=initialized['links']))
        profile=self.root/'mesh-launch.json'
        def write(value):
            profile.write_text(json.dumps(value),encoding='utf-8');sha=launch.digest(profile)
            for approval_path in (self.reader.approval,self.fixture.base.approval):
                a=json.loads(approval_path.read_text());a['profiles']=list(dict.fromkeys(a['profiles']+[sha]));approval_path.write_text(json.dumps(a))
            return sha
        sha=write(p)
        if with_rook:
            p['rookEnrollment']=dict(id='rook',mode='paused',destination='mesh_relay_inbox',
                                     boardIdentity=initialized['boardIdentity'])
            profile.write_text(json.dumps(p),encoding='utf-8')
            with self.assertRaises(launch.LaunchError):
                launch.inspect_launch(profile,launch.digest(profile),self.reader.approval)
            self.assertFalse(Path(p['attemptPath']).exists())
            sha=write(p)
        if with_pilot:
            self.exercise_capture(p,initialized['links'][1]['cardId'])
        checked,read_roles=launch.checked_launch(profile,sha,self.reader.approval)
        frame=launch.native_frame(checked,read_roles,self.reader.approval,sha)
        self.assertEqual(frame['projectSyncOptions']['destination']['peer']['pid'],service_child.pid)
        # No Mesh child or launch records may exist for missing approval or drift.
        variants=[]
        bad=copy.deepcopy(p);bad['projectSync']['source']['fileInode']='0';variants.append(bad)
        bad=copy.deepcopy(p);bad['projectSync']['links'][0]['fields'].append('goal');variants.append(bad)
        bad=copy.deepcopy(p);bad['projectSync']['links'][0]['projectId']='not-granted';variants.append(bad)
        bad=copy.deepcopy(p);bad['projectSync']['serviceProfileSha256']='0'*64;variants.append(bad)
        for bad in variants:
            with self.subTest(changed=bad['projectSync']):
                with self.assertRaises((composition.ProjectMeshInputError,service.ServiceProcessError)):
                    launch.native_frame(bad,read_roles,self.reader.approval,sha)
        approval=json.loads(self.fixture.base.approval.read_text());held=copy.deepcopy(approval)
        held['actions'].remove('run_mesh_sync');self.fixture.base.approval.write_text(json.dumps(held))
        with self.assertRaises(composition.ProjectMeshInputError):launch.native_frame(p,read_roles,self.reader.approval,sha)
        self.fixture.base.approval.write_text(json.dumps(approval))
        missing_hash=copy.deepcopy(approval);missing_hash['profiles'].remove(sha)
        self.fixture.base.approval.write_text(json.dumps(missing_hash))
        with self.assertRaises(composition.ProjectMeshInputError):launch.native_frame(p,read_roles,self.reader.approval,sha)
        self.fixture.base.approval.write_text(json.dumps(approval))
        db=sqlite3.connect(database)
        try:
            old=db.execute('SELECT fields FROM mind_project_capture_policy WHERE cardId=?',(link['cardId'],)).fetchone()[0]
            db.execute('UPDATE mind_project_capture_policy SET fields=? WHERE cardId=?',(json.dumps(['title','stage','goal']),link['cardId']));db.commit()
            with self.assertRaises(composition.ProjectMeshInputError):launch.native_frame(p,read_roles,self.reader.approval,sha)
            db.execute('UPDATE mind_project_capture_policy SET fields=? WHERE cardId=?',(old,link['cardId']));db.commit()
        finally:db.close()
        self.assertFalse(Path(p['attemptPath']).exists())
        self.mesh,stamp,record=launch.launch_mesh(profile,sha,self.reader.approval)
        self.assertEqual(record['state'],'input_sent');self.assertEqual(record['pid'],self.mesh.pid)
        def listening():
            for line in Path(p['stdoutPath']).read_text().splitlines():
                try: row=json.loads(line)
                except ValueError:continue
                if row.get('event')=='mesh_listening':return row
        listening=self.wait_for(listening,self.mesh)
        request=admitted_http(listening['url'])
        admitted=request('/api/trial-session/bootstrap',{});csrf=admitted['csrfToken']
        if with_rook:
            status=request('/api/workroom/rook',csrf=csrf,method='GET')
            self.assertEqual((status['connection']['id'],status['connection']['source'],status['connection']['status']),
                             ('rook','native_mesh_profile','paused'))
            self.assertFalse(status['sweep']['schedulerInstalled'])
            self.assertIsNone(status['sweep']['lastScheduledAt'])
        card=request('/api/tasks/'+link['cardId'],csrf=csrf,method='GET')['task']
        request('/api/tasks/'+link['cardId'],edited_card(card,'Composed launcher saved title'),csrf,method='PATCH')
        def recorded():
            db=sqlite3.connect(self.reader.database)
            try:
                events=db.execute('SELECT * FROM project_sync_events').fetchall()
                memories=db.execute('SELECT * FROM memory_revisions WHERE is_current=1').fetchall()
                count=4 if with_pilot else 2
                return (events,memories) if len(events)==count and 'Composed launcher saved title' in str(memories) else None
            finally:db.close()
        events,memories=self.wait_for(recorded,self.mesh)
        self.assertEqual(len(events),4 if with_pilot else 2);self.assertNotIn('EXCLUDED-PRIVATE-PROSE',str(events)+str(memories))
        if with_pilot:
            self.assertIn('Offline pilot coupon',str(memories))
            self.assertIn('coupon-v1.scad',str(memories))
            with closing(sqlite3.connect(self.reader.database)) as ledger:
                actual=ledger.execute('SELECT event_id,receipt_id FROM project_sync_events ORDER BY event_id').fetchall()
            def saved_receipts():
                with closing(sqlite3.connect(database)) as board:
                    saved=board.execute("SELECT eventId,receipt FROM mind_project_outbox WHERE state='saved' ORDER BY eventId").fetchall()
                return saved if len(saved)==4 else None
            saved=self.wait_for(saved_receipts,self.mesh)
            self.assertEqual([(event_id,json.loads(receipt)['receiptId']) for event_id,receipt in saved],actual)
        request('/api/trial-session/logout',{},csrf)
        secret=frame['projectSyncOptions']['destination']['token']
        self.assertNotIn(secret,Path(p['attemptPath']).read_text()+Path(p['stdoutPath']).read_text()+Path(p['stderrPath']).read_text())

    def exercise_capture(self, connected, pilot_id):
        runtime=self.reader.reader_data['runtime']
        capture={key:connected[key] for key in ('workspace','settings','pythonExecutable','pythonSha256','nodeExecutable','nodeSha256')}
        capture.update(schema=launch.CAPTURE_SCHEMA,runtime=runtime,ownerSid=self.reader.reader_data['ownerSid'],
            pwshSha256=launch.digest(runtime['pwsh']),sourceHashes={str(f):launch.digest(f) for f in launch.capture_source_paths(runtime)},
            attemptPath=str(self.root/'capture-attempt.json'),stdoutPath=str(self.root/'capture-out.log'),stderrPath=str(self.root/'capture-err.log'),
            projectCapture=dict(schema='onoes-mesh-native-project-capture/v1',source=connected['projectSync']['source'],
                links=connected['projectSync']['links'],storeId=self.reader.reader_data['binding']['store_id']))
        profile=self.root/'capture-profile.json';roles.private_new_json(profile,capture)
        sha=launch.digest(profile);approval=self.root/'capture-decision.json'
        roles.private_new_json(approval,dict(schema='onoes-mesh-offline-capture-approval/v1',
            decision='approve_exact_workroom_offline_capture',profileSha256=sha,workspace=capture['workspace'],ownerSid=capture['ownerSid']))
        self.mesh,_,_=launch.launch_mesh(profile,sha,approval)
        def address():
            for line in Path(capture['stdoutPath']).read_text().splitlines():
                row=json.loads(line)
                if row.get('event')=='mesh_listening':return row['url']
        request=admitted_http(self.wait_for(address,self.mesh))
        csrf=request('/api/trial-session/bootstrap',{})['csrfToken']
        card=request('/api/tasks/'+pilot_id,csrf=csrf,method='GET')['task']
        request('/api/tasks/'+pilot_id,edited_card(card,'Offline pilot coupon'),csrf,method='PATCH')
        state=request('/api/workroom/'+pilot_id,csrf=csrf,method='GET')['memorySync']['state']
        self.assertEqual(state,'offline')
        with closing(sqlite3.connect(self.data/'tasks.sqlite')) as db:
            self.assertEqual(db.execute('SELECT state,COUNT(*) FROM mind_project_outbox GROUP BY state').fetchall(),[('pending',3)])
        self.mesh.terminate();self.mesh.wait(timeout=30);self.mesh=None


if __name__=='__main__':unittest.main()
