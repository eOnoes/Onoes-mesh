"""Actual capture-first command, held memory, catch-up and cheap healthy tick."""
from contextlib import closing,ExitStack
import copy
import importlib.util
import json
import os
from pathlib import Path
import pstats
import socket
import sqlite3
import subprocess
import sys
import time
import unittest
import xml.etree.ElementTree as ET
from unittest.mock import patch

import mesh_launch_candidate as launch
import recall_process_candidate as roles
import reader_service_process_candidate as reader_service
import test_project_mesh_input_candidate as fixtures
from test_native_ensure_candidate import OwnedTestGateway

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from mesh_launcher_window import MeshLauncherWindow
import mesh_recovery_candidate as recovery
import mesh_startup_candidate as startup
import mesh_startup_task_candidate as startup_task


@unittest.skipUnless(os.name=='nt' and os.environ.get('MESH_CAPTURE_FIRST_WORKSPACE'),
                     'Explicit isolated copied capture-first workspace required')
class CaptureFirstProcessTests(unittest.TestCase):
    def test_real_startup_keeps_local_board_when_memory_held_then_catches_up(self):
        ws=Path(os.environ['MESH_CAPTURE_FIRST_WORKSPACE']).resolve()
        self.assertEqual(ws,launch.ROOT);self.assertEqual(ws,startup.ROOT);self.assertEqual(ws,recovery.ROOT)
        self.assertTrue(ws.parent.name.startswith('mesh-capture-first-'))
        receipt=ws.parent/'workroom-ab-preview-process.json';self.assertFalse(receipt.exists())
        (ws/'data').mkdir(exist_ok=True)
        def phase(value):print('Synthetic capture-first: '+value,flush=True)
        phase('baseline_start')
        case=fixtures.ProjectMeshLauncherTests();self.addCleanup(case.doCleanups);case.setUp()
        install=None;old_launch=None;fallback_profile=None
        if os.environ.get('MESH_CAPTURE_FIRST_INSTALL_FIXTURE'):
            install=json.loads(Path(os.environ['MESH_CAPTURE_FIRST_INSTALL_FIXTURE']).read_text())
            self.assertEqual(install['workspace'],str(ws));self.assertTrue(install['syntheticOnly'])
            self.assertTrue(ws.parent.name.startswith('mesh-capture-first-install-'))
            import mesh_runtime_overlay_candidate as overlay
            self.assertEqual(overlay.digest(overlay.__file__),install['toolSha256'])
            case.fixture.value['attemptPath']=str(case.root/'fixture-service-attempt-after-backup.json');case.fixture.write()
            for f in install['files']:
                target=ws/f['relativePath'];self.assertTrue(target.resolve().is_relative_to(ws))
                self.assertEqual(overlay.digest(target),f['afterSha256'])
                if f['beforeSha256'] is None:target.unlink()
                else:
                    body=(Path(install['beforeRoot'])/f['relativePath']).read_bytes()
                    self.assertEqual(overlay.digest(Path(install['beforeRoot'])/f['relativePath']),f['beforeSha256'])
                    target.write_bytes(body)
            self.assertTrue(all(overlay.digest(ws/f['relativePath'])==f['beforeSha256'] for f in install['files']))
            managed_relative='integrations/mind-recovery-candidate/reader_service_process_candidate.py'
            managed_entry=next(f for f in install['files'] if f['relativePath']==managed_relative)
            self.assertIsNone(managed_entry['beforeSha256'])
            self.assertFalse((ws/managed_relative).exists())
            spec=importlib.util.spec_from_file_location('before_capture_launcher',ws/'integrations/mind-recovery-candidate/mesh_launch_candidate.py')
            old_launch=importlib.util.module_from_spec(spec);spec.loader.exec_module(old_launch)
        def code_digest(path):
            path=Path(path)
            if install and path.is_relative_to(ws):
                rel=path.relative_to(ws).as_posix()
                for f in install['files']:
                    if f['relativePath']==rel:return f['afterSha256']
            return launch.digest(path)
        original_launch=launch.launch_mesh
        baseline_launch=old_launch.launch_mesh if install else original_launch
        def fixed_gateway(profile,sha,approval):
            p=json.loads(Path(profile).read_text())
            with socket.socket() as sock:sock.bind(('127.0.0.1',0));p['settings']['MESH_PREVIEW_PORT']=str(sock.getsockname()[1])
            Path(profile).write_text(json.dumps(p));sha=launch.digest(profile)
            for path in (case.reader.approval,case.fixture.base.approval):
                value=json.loads(path.read_text());value['profiles'].append(sha);path.write_text(json.dumps(value))
            return baseline_launch(profile,sha,approval)
        with ExitStack() as stack:
            if install:
                aliases=[name for name,value in vars(fixtures).items() if value is launch]
                self.assertEqual(len(aliases),1)
                stack.enter_context(patch.object(fixtures,aliases[0],old_launch))
            stack.enter_context(patch.object(old_launch if install else launch,'launch_mesh',side_effect=fixed_gateway))
            case.test_exact_profiles_preflight_then_owned_gateway_delivers_only_approved_fields()
        phase('baseline_delivered')
        profile=case.root/'mesh-launch.json';sha=launch.digest(profile);p=json.loads(profile.read_text());root=case.root
        baseline_profile,baseline_sha,baseline_p=profile,sha,copy.deepcopy(p)
        if install:
            fallback=copy.deepcopy(p);fallback['schema']='onoes-mesh-native-launch/v1';fallback.pop('projectSync')
            fallback['sourceHashes']={str(path):old_launch.digest(path) for path in old_launch.source_paths()}
            for key,name in [('attemptPath','fallback-attempt.json'),('stdoutPath','fallback-out.log'),('stderrPath','fallback-err.log')]:fallback[key]=str(root/name)
            fallback_profile=root/'fallback-profile.json';roles.private_new_json(fallback_profile,fallback);fallback_sha=launch.digest(fallback_profile)
            p['sourceHashes']={str(path):code_digest(path) for path in launch.source_paths(project=True)}
            for key,name in [('attemptPath','connected-attempt.json'),('stdoutPath','connected-out.log'),('stderrPath','connected-err.log')]:p[key]=str(root/name)
            profile=root/'connected-profile.json';roles.private_new_json(profile,p);sha=launch.digest(profile)
            for path,hashes in [(case.reader.approval,[sha,fallback_sha]),(case.fixture.base.approval,[sha])]:
                value=json.loads(path.read_text());value['profiles'].extend(hashes);path.write_text(json.dumps(value))
        def events():
            with closing(sqlite3.connect((case.data/'tasks.sqlite').as_uri()+'?mode=ro',uri=True)) as db:
                return db.execute('SELECT eventId,payloadHash,state,receipt FROM mind_project_outbox ORDER BY sequence').fetchall()
        before=events();self.assertEqual(len(before),2)
        protected=[Path(case.reader.reader_data['credentialPath']),Path(case.fixture.base.value['credentialPath']),
            Path(case.reader.reader_data['terminalPath']),Path(case.fixture.base.value['terminalPath']),Path(case.fixture.base.value['keyEnrollmentPath'])]
        protected_hashes={str(path):launch.digest(path) for path in protected}
        runtime=case.reader.reader_data['runtime']
        cp=dict(schema=launch.CAPTURE_SCHEMA,workspace=str(ws),pythonExecutable=sys.executable,nodeExecutable=p['nodeExecutable'],
            pythonSha256=p['pythonSha256'],nodeSha256=p['nodeSha256'],runtime=runtime,ownerSid=case.reader.reader_data['ownerSid'],
            pwshSha256=launch.digest(runtime['pwsh']),sourceHashes={str(path):code_digest(path) for path in launch.capture_source_paths(runtime)},
            settings=p['settings'],attemptPath=str(root/'capture-attempt.json'),stdoutPath=str(root/'capture-out.log'),stderrPath=str(root/'capture-err.log'),
            projectCapture=dict(schema='onoes-mesh-native-project-capture/v1',source=p['projectSync']['source'],
                storeId=case.reader.reader_data['binding']['store_id'],links=p['projectSync']['links']))
        capture_profile=root/'capture-profile.json';roles.private_new_json(capture_profile,cp);capture_sha=launch.digest(capture_profile)
        capture_approval=root/'capture-approval.json';roles.private_new_json(capture_approval,dict(schema='onoes-mesh-offline-capture-approval/v1',
            decision='approve_exact_workroom_offline_capture',ownerSid=cp['ownerSid'],workspace=str(ws),profileSha256=capture_sha))
        managed=root/'managed-reader.json';managed_attempt=root/'managed-reader-attempt.json'
        roles.private_new_json(managed,dict(schema=reader_service.SCHEMA,
            sourceHashes={str(path):code_digest(path) for path in (Path(reader_service.__file__).resolve(),reader_service.HERE/'recall_process_candidate.py')},
            readerProfilePath=str(case.reader.reader),readerProfileSha256=case.reader.reader_sha,
            attemptPath=str(managed_attempt),stopPath=str(root/'managed-reader-stop')))
        managed_sha=launch.digest(managed);value=json.loads(case.reader.approval.read_text());value['profiles'].append(managed_sha);case.reader.approval.write_text(json.dumps(value))
        handoff=root/'handoff.json';roles.private_new_json(handoff,dict(schema='onoes-mesh-capture-handoff-approval/v1',
            decision='approve_exact_capture_to_connected_handoff',workspace=str(ws),ownerSid=cp['ownerSid'],pythonSha256=launch.digest(sys.executable),
            sourceHashes={str(ws/'integrations'/name):code_digest(ws/'integrations'/name) for name in recovery.FILES},
            capture=dict(profilePath=str(capture_profile),profileSha256=capture_sha,approvalPath=str(capture_approval),approvalSha256=launch.digest(capture_approval)),
            connected=dict(profilePath=str(profile),profileSha256=sha,approvalPath=str(case.reader.approval),approvalSha256=launch.digest(case.reader.approval),
                projectApprovalPath=str(case.fixture.base.approval),projectApprovalSha256=launch.digest(case.fixture.base.approval))))
        memory=root/'memory-recovery.json';roles.private_new_json(memory,dict(schema='onoes-mesh-native-recovery-approval/v1',
            decision='approve_exact_same_grant_memory_recovery',ownerSid=cp['ownerSid'],workspace=str(ws),profilePath=str(profile),profileSha256=sha,
            pythonSha256=launch.digest(sys.executable),readerServiceProfile=str(managed),readerServiceSha256=managed_sha,
            sourceHashes={**{str(ws/'integrations'/name):code_digest(ws/'integrations'/name) for name in recovery.FILES},
                str(Path(reader_service.__file__).resolve()):code_digest(reader_service.__file__)}))
        approval=root/'startup.json';approved=dict(schema='onoes-mesh-capture-first-approval/v1',decision='approve_exact_capture_first_recovery',
            workspace=str(ws),ownerSid=cp['ownerSid'],pythonSha256=launch.digest(sys.executable),
            sourceHashes={str(ws/'integrations'/name):code_digest(ws/'integrations'/name) for name in startup.SOURCES},
            handoffApprovalPath=str(handoff),handoffApprovalSha256=launch.digest(handoff),memoryApprovalPath=str(memory),memoryApprovalSha256=launch.digest(memory))
        roles.private_new_json(approval,approved);approval_sha=launch.digest(approval)
        hidden_mode=os.environ.get('MESH_CAPTURE_FIRST_HIDDEN')=='1'
        hidden_draft=None
        def prepare_hidden():
            # Adapt only the workspace action in a read-only exported task copy.
            # No scheduler API is called or task registered by this scenario.
            original_task=Path(os.environ['MESH_CAPTURE_FIRST_TASK_XML']).read_text(encoding='utf-8-sig')
            tree=ET.fromstring(original_task);tag='{'+startup_task.NS+'}'
            tree.find('.//'+tag+'Actions/'+tag+'Exec/'+tag+'Arguments').text='//B //Nologo "'+str(ws/'integrations/ensure-workroom-hidden.vbs')+'"'
            task_bytes=ET.tostring(tree,encoding='utf-8',xml_declaration=True)
            draft=startup_task.prepare_hidden_task(approval_path=str(approval),approval_sha=approval_sha,
                task_xml=task_bytes,task_sha=startup_task.sha(task_bytes),wrapper_path=str(root/startup_task.WRAPPER_NAME))
            Path(draft['wrapperPath']).write_bytes(draft['wrapperBytes'])
            from onoes_mind.enrollment_store import qualify_private_storage
            qualify_private_storage(Path(draft['wrapperPath']),kind='file')
            (root/'hidden-task-draft.xml').write_bytes(draft['taskBytes']);return draft
        if hidden_mode and not install:hidden_draft=prepare_hidden()
        with MeshLauncherWindow(ws,launch.digest(ws/'integrations/restart-workroom-preview.ps1')) as window:
            if install:
                # Seed the already-published before-state from the actual old
                # actor, not by asking the new project source policy to accept
                # an old profile. Production already has this owner receipt.
                args=[baseline_p['nodeExecutable'],str(ws/'serve.mjs'),'--native-mind']
                ticks=roles.creation_ticks(case.mesh._handle)
                observation=recovery.ProcessObservation(window,roles,case.mesh.pid,ticks,args)
                try:self.assertIsNone(observation.poll())
                finally:observation.close()
                receipt.write_text(json.dumps(dict(Schema='onoes-owned-process/v1',AppName="ONOe's Mesh - Workroom",
                    WorkingDirectory=str(ws),EntryPoint=args[1],Port=int(baseline_p['settings']['MESH_PREVIEW_PORT']),
                    Url='https://synthetic.invalid/#workroom',CommandLine=subprocess.list2cmdline(args),
                    Id=case.mesh.pid,StartTime=recovery.native_start(ticks),Path=args[0])))
            else:window.publish_native_owner(case.mesh,roles.creation_ticks(case.mesh._handle),baseline_profile,baseline_sha,previous_sha256=None)
            old_reader=roles.reader_state(case.reader.reader,case.reader.reader_sha,case.reader.approval)
            import project_service_process_candidate as service
            old_writer=service.service_state(case.fixture.profile,case.fixture.sha,case.fixture.base.approval)
            writer_child=next(child for child,ticks in case.fixture.children if child.pid==old_writer['pid'])
            mesh_pid,mesh_ticks=case.mesh.pid,roles.creation_ticks(case.mesh._handle)
            case.mesh.terminate();case.mesh.wait(timeout=30)
            if install:
                service.request_stop(case.fixture.profile,case.fixture.sha,case.fixture.base.approval)
                self.assertEqual(writer_child.wait(timeout=60),0)
                stopped=service.service_state(case.fixture.profile,case.fixture.sha,case.fixture.base.approval)
                self.assertEqual(stopped['state'],'stopped');self.assertFalse(stopped['processLive'])
                plan=dict(schema='onoes-mesh-runtime-overlay/v2',workspace=str(ws),payloadRoot=install['payloadRoot'],
                    journalRoot=str(ws.parent/'overlay-journal'),toolSha256=install['toolSha256'],observerSha256=overlay.digest(overlay.observer_path()),
                    runtime=dict(meshPid=mesh_pid,meshCreationTicks=mesh_ticks,gatewayPort=int(p['settings']['MESH_PREVIEW_PORT']),
                        serviceAttemptPath=case.fixture.value['attemptPath'],serviceProfileSha256=case.fixture.sha,
                        freshLaunchAttempts=[dict(kind='mesh',path=cp['attemptPath'],profileSha256=capture_sha),
                            dict(kind='mesh',path=p['attemptPath'],profileSha256=sha),
                            dict(kind='mesh',path=fallback['attemptPath'],profileSha256=fallback_sha)]),files=install['files'])
                roles.private_new_json(root/'bound-overlay-plan.json',plan)
                self.assertEqual(overlay.apply_overlay(plan,dict(decision='approve_exact_mesh_runtime_overlay',planSha256=overlay.plan_hash(plan)))['state'],'installed')
                window.assert_held();self.assertTrue(roles.reader_state(case.reader.reader,case.reader.reader_sha,case.reader.approval)['ready'])
                capture_child,capture_ticks,_=original_launch(capture_profile,capture_sha,capture_approval)
                case.reader.children.append(capture_child)
                until=time.monotonic()+60
                while True:
                    try:window._owns_gateway(capture_child.pid,int(cp['settings']['MESH_PREVIEW_PORT']));break
                    except Exception:
                        self.assertIsNone(capture_child.poll());self.assertLess(time.monotonic(),until);time.sleep(.2)
                previous=launch.digest(receipt)
                window.publish_native_owner(capture_child,capture_ticks,capture_profile,capture_sha,previous_sha256=previous,beforeimage_path=ws/'data/install-owner-before.json')
                self.assertEqual(events(),before);phase('exact_source_installed_reader_preserved_capture_owner_published')
            else:
                reader_child=next(child for child in case.reader.children if child.pid==old_reader['pid'])
                reader_child.terminate();reader_child.wait(timeout=30);writer_child.terminate();writer_child.wait(timeout=30)
            case.mesh=None
        if hidden_mode and install:hidden_draft=prepare_hidden()
        # Fault injection only: no actor was launched for this reserved record.
        # The startup command must preserve it and leave capture usable.
        roles.private_new_json(managed_attempt,dict(schema='onoes-mind-reader-service-attempt/v1',
            profileSha256=managed_sha,state='reserved'))
        reserved=managed_attempt.read_bytes();refs=[]
        def cleanup():
            for ref in reversed(refs):
                try:
                    if ref.poll() is None:ref.terminate();ref.wait(30)
                finally:ref.close()
        self.addCleanup(cleanup)
        def attach(path,expected):
            if not Path(path).is_file():return
            record=json.loads(Path(path).read_text())
            if record.get('profileSha256')==expected and record.get('state') in ('started','input_sent') and roles.same_process_alive(record['pid'],record['creationTicks']):
                if not any(ref.pid==record['pid'] for ref in refs):refs.append(OwnedTestGateway(record['pid'],record['creationTicks']))
        def command(label,profile_output=None):
            args=[sys.executable,'-I']
            if profile_output:args+=['-m','cProfile','-o',str(profile_output)]
            args += [str(ws/'integrations/mesh_startup_candidate.py'),'--approval',str(approval),'--sha256',approval_sha]
            hidden=hidden_mode and profile_output is None
            if hidden:args=[str(Path(os.environ['WINDIR'])/'System32/wscript.exe'),'//B','//Nologo',hidden_draft['wrapperPath']]
            start=time.monotonic();child=subprocess.Popen(args,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,creationflags=subprocess.CREATE_NO_WINDOW)
            try:
                while True:
                    try:out,err=child.communicate(timeout=30);break
                    except subprocess.TimeoutExpired:phase(label+'_same_command_'+str(int(time.monotonic()-start))+'s')
                result=dict(code=child.returncode,seconds=time.monotonic()-start,stdout=out,stderr=err,transport='hidden_wscript' if hidden else 'python_cli')
                (ws.parent/(label+'-RESULT.json')).write_text(json.dumps(result,indent=2))
                self.assertEqual(child.returncode,0,out+err)
                if hidden:
                    owner=json.loads(receipt.read_text());observed=None
                    for mode,selected,expected in [('capture',cp,capture_sha),('connected',p,sha)]:
                        path=Path(selected['attemptPath'])
                        if not path.is_file():continue
                        record=json.loads(path.read_text())
                        if record.get('profileSha256')==expected and record.get('pid')==owner['Id']:
                            self.assertEqual(record['creationTicks'],startup.receipt_ticks(owner))
                            self.assertTrue(roles.same_process_alive(record['pid'],record['creationTicks']))
                            observed=dict(state='capture_pending' if mode=='capture' else 'connected',
                                startupMode=mode,pid=record['pid'],evidence='exact_owner_receipt_and_attempt')
                    self.assertIsNotNone(observed);result['observed']=observed
                    (ws.parent/(label+'-RESULT.json')).write_text(json.dumps(result,indent=2));return observed
                return json.loads(out)
            finally:
                for path,expected in [(cp['attemptPath'],capture_sha),(p['attemptPath'],sha),
                    (managed_attempt,managed_sha),(case.fixture.value['attemptPath'],case.fixture.sha)]:attach(path,expected)
        first=command('HELD-MEMORY');self.assertEqual(first['state'],'capture_pending')
        self.assertEqual(managed_attempt.read_bytes(),reserved);self.assertEqual(events(),before)
        capture_record=json.loads(Path(cp['attemptPath']).read_text());self.assertEqual(json.loads(receipt.read_text())['Id'],capture_record['pid'])
        def backend(p,pid,required=True):
            for line in Path(p['stdoutPath']).read_text().splitlines():
                try:row=json.loads(line)
                except ValueError:continue
                if row.get('event')=='mesh_listening' and row.get('pid')==pid:return row['url']
            if required:self.fail('Exact backend was not logged')
        request=fixtures.admitted_http(backend(cp,capture_record['pid']));token=request('/api/trial-session/bootstrap',{})['csrfToken'];card=p['projectSync']['links'][0]['cardId']
        self.assertEqual(request('/api/workroom/'+card,csrf=token,method='GET')['memorySync']['state'],'offline')
        task=request('/api/tasks/'+card,csrf=token,method='GET')['task'];request('/api/tasks/'+card,fixtures.edited_card(task,'Bootproof offline edit saved'),token,method='PATCH')
        request('/api/trial-session/logout',{},token);pending=events();self.assertEqual(pending[:2],before);self.assertEqual(pending[-1][2],'pending')
        phase('local_board_usable_while_unresolved_memory_attempt_preserved')
        # Remove only the known never-launched injected stub from the test's
        # counterfactual state, preserving its bytes. Runtime does not do this.
        fault_archive=root/'injected-reserved-record-preserved.json';managed_attempt.rename(fault_archive)
        self.assertEqual(fault_archive.read_bytes(),reserved)
        second=command('RESTORE-MEMORY');self.assertEqual(second.get('startupMode'),'connected')
        connected=json.loads(Path(p['attemptPath']).read_text());self.assertEqual(second['pid'],connected['pid'])
        request=fixtures.admitted_http(backend(p,connected['pid']));token=request('/api/trial-session/bootstrap',{})['csrfToken']
        try:
            after=case.wait_for(lambda:events() if len(events())==3 and all(row[2]=='saved' for row in events()) else None)
            self.assertEqual(after[:2],before);self.assertEqual(after[-1][:2],pending[-1][:2])
            recall=request('/api/mind/recall',dict(query='bootproof',limit=8),token)
            self.assertIn('Bootproof offline edit saved',json.dumps(recall));self.assertNotIn('EXCLUDED-PRIVATE-PROSE',json.dumps(recall))
        finally:request('/api/trial-session/logout',{},token)
        receipt_before=receipt.read_bytes();warm_profile=ws.parent/'WARM.pstats';warm=command('WARM',warm_profile)
        self.assertEqual(warm['state'],'observed_running');self.assertEqual(warm['pid'],connected['pid']);self.assertEqual(warm['processChanges'],0)
        self.assertEqual(receipt.read_bytes(),receipt_before);self.assertEqual(events(),after)
        if hidden_mode:
            hidden_warm=command('HIDDEN-WARM');self.assertEqual(hidden_warm['pid'],connected['pid'])
            self.assertEqual(receipt.read_bytes(),receipt_before);self.assertEqual(events(),after)
        stats=pstats.Stats(str(warm_profile));private_calls=sum(value[1] for (file,line,name),value in stats.stats.items() if name=='qualify_private_storage')
        self.assertEqual(private_calls,0);self.assertEqual({str(path):launch.digest(path) for path in protected},protected_hashes)
        phase('automatic_same_grant_catch_up_and_observation_only_warm_tick_passed')
        proof=dict(schema='onoes-mesh-synthetic-capture-first-proof/v1',syntheticOnly=True,liveChanged=False,
            localBoardSurvivedMemoryHold=True,unresolvedAttemptPreserved=True,sameGrantRecoveryAndCatchUp=True,
            originalEventIdsAndReceiptsPreserved=True,warmTickNoProcessChanges=True,warmTickPrivateChecks=0,
            protectedCredentialTerminalKeyHashesUnchanged=True,privateFieldExcluded=True,sourceHashes=approved['sourceHashes'],
            captureSourceHashes=cp['sourceHashes'],connectedSourceHashes=p['sourceHashes'],
            managedReaderSourceHashes=json.loads(managed.read_text())['sourceHashes'],
            memoryRecoverySourceHashes=json.loads(memory.read_text())['sourceHashes'],
            handoffSourceHashes=json.loads(handoff.read_text())['sourceHashes'])
        if hidden_mode:
            proof.update(hiddenWscriptStartupAndRecovery=True,hiddenWarmTickPreservedOwnerAndEvents=True,
                taskRegistered=False,taskPropertiesPreserved=True,wrapperSha256=hidden_draft['wrapperSha256'],
                taskGeneratorSourceHashes={str(Path(startup_task.__file__).resolve()):launch.digest(startup_task.__file__)})
        if install:
            installed_hashes={f['relativePath']:overlay.digest(ws/f['relativePath']) for f in install['files']}
            self.assertEqual(installed_hashes,{f['relativePath']:f['afterSha256'] for f in install['files']})
            with MeshLauncherWindow(ws,launch.digest(ws/'integrations/restart-workroom-preview.ps1')) as window:
                self.assertTrue(roles.same_process_alive(old_reader['pid'],old_reader['creationTicks']))
                previous=launch.digest(receipt)
                native_ref=next(ref for ref in refs if ref.pid==connected['pid'])
                native_ref.terminate();native_ref.wait(30)
                writer_state=service.service_state(case.fixture.profile,case.fixture.sha,case.fixture.base.approval)
                writer_ref=next(ref for ref in refs if ref.pid==writer_state['pid'])
                service.request_stop(case.fixture.profile,case.fixture.sha,case.fixture.base.approval)
                self.assertEqual(writer_ref.wait(60),0)
                writer_state=service.service_state(case.fixture.profile,case.fixture.sha,case.fixture.base.approval)
                self.assertEqual(writer_state['state'],'stopped');self.assertFalse(writer_state['processLive'])
                self.assertEqual(overlay.rollback_overlay(plan,dict(decision='approve_exact_mesh_runtime_rollback',planSha256=overlay.plan_hash(plan)))['state'],'original')
                self.assertTrue(all(overlay.digest(ws/f['relativePath'])==f['beforeSha256'] for f in install['files']))
                window.assert_held();self.assertEqual(events(),after)
                spec=importlib.util.spec_from_file_location('restored_capture_launcher',ws/'integrations/mind-recovery-candidate/mesh_launch_candidate.py')
                restored=importlib.util.module_from_spec(spec);spec.loader.exec_module(restored)
                case.mesh,fallback_ticks,_=restored.launch_mesh(fallback_profile,fallback_sha,case.reader.approval)
                url=case.wait_for(lambda:backend(fallback,case.mesh.pid,False),case.mesh)
                request=fixtures.admitted_http(url);token=request('/api/trial-session/bootstrap',{})['csrfToken']
                try:
                    status=request('/api/mind/status',csrf=token,method='GET');self.assertTrue(status['configured'])
                    found=request('/api/mind/recall',dict(query='bootproof',limit=8),token)
                    self.assertIn('Bootproof offline edit saved',json.dumps(found));self.assertNotIn('EXCLUDED-PRIVATE-PROSE',json.dumps(found))
                finally:request('/api/trial-session/logout',{},token)
                window.publish_native_owner(case.mesh,fallback_ticks,fallback_profile,fallback_sha,previous_sha256=previous,beforeimage_path=ws/'data/rollback-owner-before.json')
                self.assertEqual(events(),after);self.assertEqual({str(path):launch.digest(path) for path in protected},protected_hashes)
                self.assertTrue(roles.same_process_alive(old_reader['pid'],old_reader['creationTicks']))
                proof.update(sourceInstalledAndRolledBack=True,allBeforeImagesRestored=True,originalReaderPidPreserved=True,
                    noGrantRevocationOrRotation=True,readOnlyFallbackCanonicalRecallPassed=True,sourceEventsAndReceiptsSurvivedRollback=True,
                    allFutureAttemptsBoundBeforeInstall=True,sourceFiles=len(install['files']),
                    changedSourceFiles=sum(f['beforeSha256']!=f['afterSha256'] for f in install['files']),
                    installedAfterSourceHashes=installed_hashes,boundOverlayPlanSha256=overlay.plan_hash(plan))
                phase('original_reader_preserved_all_code_restored_readonly_recall_passed')
        (ws.parent/'STARTUP-PROOF.json').write_text(json.dumps(proof,indent=2))


if __name__=='__main__':unittest.main()
