"""Owned copied Mesh startup/capture/connected flow with a new v7 host.

This test refuses the live workspace. All cards, ledgers, credentials, grants
and children belong to the existing native disposable fixtures.
"""
from contextlib import closing
from copy import deepcopy
from dataclasses import asdict
import hashlib
import importlib
import json
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
from types import SimpleNamespace
import sys
import traceback
import unittest
from unittest.mock import patch

WS=Path(os.environ['MESH_CLOUD_STARTUP_WORKSPACE']).resolve()
assert WS.name=='mesh-workroom-ab' and WS.parent.name.startswith('mesh-capture-first-cloud-')
assert WS!=Path('D:/App-Data/Onoes-Mesh/mesh-workroom-ab')
MIND=Path(os.environ['MIND_SOURCE']).resolve()
sys.path[:0]=[str(WS/'integrations/hermes-mind-provider'),str(WS/'integrations/mind-recovery-candidate'),
    str(WS/'integrations'),str(MIND),str(MIND/'tests'),str(Path(os.environ['MIND_TEST_SOURCE'])/'tests')]
import mesh_launch_candidate as launch
import mesh_recovery_candidate as recovery
import mesh_startup_candidate as startup
import native_project_sync_candidate as native
import project_service_process_candidate as service
import project_operator_process_candidate as operator
import reader_service_process_candidate as reader_service
import recall_process_candidate as roles
import test_project_mesh_input_candidate as fixtures
from mesh_launcher_window import MeshLauncherWindow
from cloud_host_profiles import prepare_host,encoded,digest,V6
from cloud_startup_profiles import prepare_aligned_startup
from onoes_mind.agent_home import AgentHomeBinding,enroll_agent_home
from onoes_mind.agent_home_http import AgentHomeClient,home_binding_sha256
from onoes_mind.agent_context import AgentContextBinding
from onoes_mind.context_enrollment import enroll_context_reader
from onoes_mind.handoff_channel import HandoffBinding
from onoes_mind.project_tool_grant import ReviewedProjectToolGrant
from onoes_mind.recall_binding import RecallBinding


def read(path):return json.loads(Path(path).read_bytes())
def put(path,body):
    from onoes_mind.enrollment_store import qualify_private_storage
    path=Path(path);qualify_private_storage(path.parent)
    with path.open('xb') as stream:stream.write(encoded(body));stream.flush();os.fsync(stream.fileno())
    qualify_private_storage(path,kind='file');return launch.digest(path)


@unittest.skipUnless(os.name=='nt','Actual owned Windows startup')
class CloudStartupComposedTests(unittest.TestCase):
    def test_native_startup_qualifies_new_host_current_handoff_and_existing_board(self):
        self.assertEqual(launch.ROOT,WS);self.assertEqual(startup.ROOT,WS)
        print('Cloud startup: disposable baseline',flush=True)
        case=fixtures.ProjectMeshLauncherTests();case.setUp();self.addCleanup(case.doCleanups)
        # The deployed older operator supports first enrollment, not the newer
        # fixture's add-project mode. Establish both synthetic project grants
        # initially; retain project-A's existing board while adding Mesh reads.
        case.fixture.base.value['projects']=sorted([['project-A','Synthetic existing project'],['onoes-mesh','Synthetic Mesh']])
        case.fixture.base.write()
        case.fixture.value['operatorProfileSha256']=case.fixture.base.sha
        actual_launch=launch.launch_mesh
        def fixed_port(profile,sha,approval):
            p=read(profile)
            with socket.socket() as sock:sock.bind(('127.0.0.1',0));p['settings']['MESH_PREVIEW_PORT']=str(sock.getsockname()[1])
            Path(profile).write_bytes(encoded(p));sha=launch.digest(profile)
            for path in (case.reader.approval,case.fixture.base.approval):
                v=read(path);v['profiles'].append(sha);Path(path).write_bytes(encoded(v))
            return actual_launch(profile,sha,approval)
        try:
            baseline_run=getattr(case,'exercise_gateway',case.test_exact_profiles_preflight_then_owned_gateway_delivers_only_approved_fields)
            with patch.object(launch,'launch_mesh',side_effect=fixed_port):baseline_run()
        except Exception:
            observation={'phase':'existing baseline','syntheticOnly':True}
            try:
                with closing(sqlite3.connect((case.data/'tasks.sqlite').as_uri()+'?mode=ro',uri=True)) as db:
                    columns={r[1] for r in db.execute('PRAGMA table_info(mind_project_outbox)')}
                    selected=[n for n in ('sequence','state','attempts','lastError','nextAttemptAt') if n in columns]
                    observation['outboxMetadata']=[dict(zip(selected,row)) for row in db.execute(
                        'SELECT '+','.join(selected)+' FROM mind_project_outbox ORDER BY sequence')]
                with closing(sqlite3.connect(Path(case.reader.database).as_uri()+'?mode=ro',uri=True)) as db:
                    observation['canonicalEventCount']=db.execute('SELECT count(*) FROM project_sync_events').fetchone()[0]
            except Exception as diagnostic:observation['diagnosticErrorType']=type(diagnostic).__name__
            (WS.parent/'BASELINE-OBSERVATION.json').write_text(json.dumps(observation,indent=2))
            print(json.dumps(observation),flush=True)
            raise
        p=read(case.root/'mesh-launch.json');root=case.root;owner=case.fixture.base
        # Retire only fixture-owned exact child handles. Never enumerate/kill a
        # live port's owner or infer exit from an observation timeout.
        if case.mesh.poll() is None:case.mesh.terminate()
        case.mesh.wait(30)
        for child,_ in case.fixture.children:
            if child.poll() is None:child.terminate();child.wait(30)
        # The SDK changes; retire the exact old fixture reader before its replacement.
        for child in case.reader.children:
            if child.poll() is None:child.terminate()
            child.wait(30)
        NATIVE=WS/'integrations/mind-recovery-candidate'
        keys=roles.plain_json(owner.value['keyEnrollmentPath'],16384)
        from onoes_mind.runtime_keys import unprotect_runtime_keys
        from persistent_authority import AuthorityBinding,PersistentAuthorityCandidate
        store_fields=owner.value['binding'];store=RecallBinding(store_fields['database_path'],store_fields['store_id'],
            store_fields['environment'],store_fields['authority_ref'],'project/onoes-mind/shared',
            store_fields['file_device'],store_fields['file_inode'],'fixture:custody','fixture:revoke','fixture:review')
        homes={a:AgentHomeBinding(store,a) for a in ('deep','echo','cyony')}
        reader=AgentContextBinding(store,'context-cyony','onoes-mesh')
        native_host=native.NativeProjectSyncHost(binding=operator.checked_profile(owner.profile,owner.sha)[1],
            history_path=owner.value['historyPath'],authority=PersistentAuthorityCandidate(
                AuthorityBinding(**roles.plain_json(owner.value['authorityBindingPath']))),
            credential_path=owner.value['credentialPath'],project_ids=tuple(v[0] for v in owner.value['projects']),
            review_ref=owner.value['reviewRef'],**unprotect_runtime_keys(keys['runtime_envelope'],
                store_id=store.store_id,environment_id=store.environment))
        tokens={};op='omop1_'+'X'*43;doc={'author':'nims','revision':1,'next_action':'Review the measured print plan','marker':'cloudstartupqualification'}
        native_host.start()
        try:
            with native_host.writer_lock:
                native_host.ledger.create_principal('operator');native_host.ledger.issue_credential('operator',op)
                for actor,binding in homes.items():
                    enroll_agent_home(native_host.ledger,binding,operator_token=op,
                        save_new_token=lambda t,a=actor:tokens.setdefault(a,t) is not None)
                enroll_context_reader(native_host.ledger,reader,operator_token=op,
                    save_new_token=lambda t:tokens.setdefault('context',t) is not None)
                admitted=native_host.ledger.remember(op,{'event_id':'cloud-startup-handoff','kind':'project_fact',
                    'project_id':'onoes-mesh','claim':json.dumps(doc),'requested_visibility':'shared',
                    'source_class':'agent_handoff','evidence_refs':[{'type':'fixture','ref':'nims:cloudstartup@1','content_hash':'a'*64}]})
        finally:native_host.close()
        handoff_binding=HandoffBinding(store,admitted['record_id'],'nims/onoes-mesh/cloudstartup','onoes-mesh','nims')
        view=root/'old-runtime-view.json';put(view,owner.value)
        with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
        baseline=deepcopy(case.fixture.value)
        baseline.update(schema=V6,serviceRuntimeProfilePath=str(view),serviceRuntimeProfileSha256=launch.digest(view),
            enrolledMeshSourceDirectory=str(NATIVE),agentHomeBindings=[asdict(homes[a]) for a in ('deep','echo')],
            agentHomePort=port,handoffBinding=asdict(handoff_binding))
        baseline.update(attemptPath=str(root/'old-v6-attempt.json'),readyPath=str(root/'old-v6-ready.json'),stopPath=str(root/'old-v6-stop.json'))
        baseline_path=root/'old-host.json';put(baseline_path,baseline)
        wa=read(owner.approval);wa.update(profiles=[launch.digest(baseline_path)],
            actions=['run_agent_homes','run_handoff_refresh','run_mesh_sync','run_service'],
            agentHomes=service.home_approval(baseline),handoffRefresh=service.handoff_approval(baseline))
        paths={n:root/('old-'+n+'.json') for n in ('capture','capture-approval','connected','connected-approval','writer-approval','handoff','memory','startup')}
        p['projectSync'].update(serviceProfile=str(baseline_path),serviceProfileSha256=launch.digest(baseline_path),approvalPath=str(paths['writer-approval']))
        for k in ('attemptPath','stdoutPath','stderrPath'):p[k]=str(root/('old-connected-'+k))
        p['sourceHashes']={str(n):launch.digest(n) for n in launch.source_paths(project=True)}
        put(paths['connected'],p);wa['profiles'].append(launch.digest(paths['connected']));put(paths['writer-approval'],wa)
        ca=read(case.reader.approval);ca['profiles'].append(launch.digest(paths['connected']))
        put(paths['connected-approval'],ca)
        runtime=case.reader.reader_data['runtime'];sid=case.reader.reader_data['ownerSid']
        cap=dict(schema=launch.CAPTURE_SCHEMA,workspace=str(WS),pythonExecutable=sys.executable,nodeExecutable=p['nodeExecutable'],
            pythonSha256=p['pythonSha256'],nodeSha256=p['nodeSha256'],runtime=runtime,ownerSid=sid,
            pwshSha256=launch.digest(runtime['pwsh']),sourceHashes={str(n):launch.digest(n) for n in launch.capture_source_paths(runtime)},
            settings=p['settings'],**{k:str(root/('old-capture-'+k)) for k in ('attemptPath','stdoutPath','stderrPath')},
            projectCapture=dict(schema='onoes-mesh-native-project-capture/v1',source=p['projectSync']['source'],
                storeId=store.store_id,links=p['projectSync']['links']))
        put(paths['capture'],cap);put(paths['capture-approval'],dict(schema='onoes-mesh-offline-capture-approval/v1',
            decision='approve_exact_workroom_offline_capture',ownerSid=sid,workspace=str(WS),profileSha256=launch.digest(paths['capture'])))
        managed=root/'managed-reader.json';put(managed,dict(schema=reader_service.SCHEMA,
            sourceHashes={str(n):launch.digest(n) for n in (Path(reader_service.__file__),reader_service.HERE/'recall_process_candidate.py')},
            readerProfilePath=str(case.reader.reader),readerProfileSha256=case.reader.reader_sha,
            attemptPath=str(root/'managed-reader-attempt.json'),stopPath=str(root/'managed-reader-stop')))
        ca['profiles'].append(launch.digest(managed));paths['connected-approval'].write_bytes(encoded(ca))
        hand=dict(schema='onoes-mesh-capture-handoff-approval/v1',decision='approve_exact_capture_to_connected_handoff',
            workspace=str(WS),ownerSid=sid,pythonSha256=launch.digest(sys.executable),
            sourceHashes={str(WS/'integrations'/n):launch.digest(WS/'integrations'/n) for n in recovery.FILES},
            capture=dict(profilePath=str(paths['capture']),profileSha256=launch.digest(paths['capture']),approvalPath=str(paths['capture-approval']),approvalSha256=launch.digest(paths['capture-approval'])),
            connected=dict(profilePath=str(paths['connected']),profileSha256=launch.digest(paths['connected']),approvalPath=str(paths['connected-approval']),approvalSha256=launch.digest(paths['connected-approval']),projectApprovalPath=str(paths['writer-approval']),projectApprovalSha256=launch.digest(paths['writer-approval'])))
        put(paths['handoff'],hand)
        put(paths['memory'],dict(schema='onoes-mesh-native-recovery-approval/v1',decision='approve_exact_same_grant_memory_recovery',
            ownerSid=sid,workspace=str(WS),profilePath=str(paths['connected']),profileSha256=launch.digest(paths['connected']),
            pythonSha256=launch.digest(sys.executable),readerServiceProfile=str(managed),readerServiceSha256=launch.digest(managed),
            sourceHashes={**hand['sourceHashes'],str(Path(reader_service.__file__)):launch.digest(reader_service.__file__)}))
        put(paths['startup'],dict(schema='onoes-mesh-capture-first-approval/v1',decision='approve_exact_capture_first_recovery',
            workspace=str(WS),ownerSid=sid,pythonSha256=launch.digest(sys.executable),
            sourceHashes={str(WS/'integrations'/n):launch.digest(WS/'integrations'/n) for n in startup.SOURCES},
            handoffApprovalPath=str(paths['handoff']),handoffApprovalSha256=launch.digest(paths['handoff']),
            memoryApprovalPath=str(paths['memory']),memoryApprovalSha256=launch.digest(paths['memory'])))
        old_raw={n:path.read_bytes() for n,path in paths.items()}

        packet=dict(root=str(root),paths={n:str(p) for n,p in paths.items()},baselinePath=str(baseline_path),
            view=str(view),ownerProfile=str(owner.profile),managed=str(managed),readerProfile=str(case.reader.reader),
            tokens=tokens,doc=doc,store=asdict(store),homes={n:asdict(v) for n,v in homes.items()},
            reader=asdict(reader),port=port,p=p,oldSdk=str(MIND))
        packet_path=root/'synthetic-sdk-transition.json';put(packet_path,packet)
        # This fresh copied workspace has no pre-existing public owner receipt.
        # A real installer must preserve/restore its own exact beforeimage.
        self.assertFalse((WS.parent/'workroom-ab-preview-process.json').exists())
        for direction,sdk in (('forward',os.environ['MIND_NEW_SOURCE']),('inverse',str(MIND))):
            if direction=='inverse':
                recipe=read(WS.parent/'SOURCE-UPGRADE.json')
                for row in recipe['files']:
                    target=WS/row['relative'];self.assertEqual(launch.digest(target),row['after'])
                    target.write_bytes((WS.parent/'original-native'/target.name).read_bytes())
                    self.assertEqual(launch.digest(target),row['before'])
            env=dict(os.environ);env['MIND_SOURCE']=sdk
            with (WS.parent/('SDK-'+direction+'.log')).open('xb') as phase_log:
                done=subprocess.run([sys.executable,'-B',str(Path(__file__)),direction,str(packet_path)],
                    env=env,cwd=WS,stdout=phase_log,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW)
            self.assertEqual(done.returncode,0,direction+' cold SDK process failed; do not retry')
        packet_path.unlink()  # Only synthetic tokens; never included in proof archives.
        self.assertTrue(all(path.read_bytes()==old_raw[n] for n,path in paths.items()))
        print('SDK transition: forward and inverse complete',flush=True)


def assert_sdk(expected):
    import onoes_mind
    assert Path(onoes_mind.__file__).resolve().parent.parent==expected


def child_phase(direction,packet_path):
    self=unittest.TestCase();packet=read(packet_path)
    root=Path(packet['root']);assert root.is_relative_to(Path(os.environ['TEMP']).resolve())
    assert_sdk(MIND)
    case=fixtures.ProjectMeshLauncherTests();case.root=root
    paths={n:Path(p) for n,p in packet['paths'].items()};old_raw={n:p.read_bytes() for n,p in paths.items()}
    baseline_path=Path(packet['baselinePath']);baseline=read(baseline_path);view=Path(packet['view'])
    owner=SimpleNamespace(profile=Path(packet['ownerProfile']),value=read(packet['ownerProfile']))
    managed=Path(packet['managed']);reader_profile=Path(packet['readerProfile'])
    store=RecallBinding(**packet['store'])
    homes={n:AgentHomeBinding(RecallBinding(**v['store']),v['agent_id']) for n,v in packet['homes'].items()}
    reader=AgentContextBinding(store,'context-cyony','onoes-mesh')
    port=packet['port'];tokens=packet['tokens'];doc=packet['doc'];p=packet['p']
    NATIVE=WS/'integrations/mind-recovery-candidate'
    try:
        if direction=='inverse':
            inverse(self,case,packet,paths,baseline_path,managed,reader_profile)
            return
        from onoes_mind.project_context_http import context_binding_sha256
        source_before=launch.digest(NATIVE/'project_service_process_candidate.py')
        # Upgrade only the copied files, then reload the same native module
        # objects referenced by the existing fixtures and startup implementation.
        recipe=read(WS.parent/'SOURCE-UPGRADE.json')
        for row in recipe['files']:
            target=WS/row['relative'];self.assertEqual(launch.digest(target),row['before'])
            target.write_bytes(Path(row['candidate']).read_bytes());self.assertEqual(launch.digest(target),row['after'])
        importlib.reload(native);importlib.reload(service)
        new_service=root/'new-host.json';new_view=root/'new-runtime.json'
        runtime={**owner.value['runtime'],'mindSource':str(MIND)}
        runtime_pins={str(n):operator.digest(n) for n in operator.source_paths(runtime)}
        plan=prepare_host(service_raw=baseline_path.read_bytes(),runtime_raw=view.read_bytes(),service_path=str(baseline_path),
            expected_service_sha256=launch.digest(baseline_path),expected_runtime_sha256=launch.digest(view),
            mind_source=str(MIND),runtime_source_hashes=runtime_pins,
            service_source_hashes={str(Path(m.__file__)):launch.digest(m.__file__) for m in (service,operator)},
            new_runtime_path=str(new_view),new_service_path=str(new_service),new_attempt_path=str(root/'new-service-attempt.json'),
            new_ready_path=str(root/'new-service-ready.json'),new_stop_path=str(root/'new-service-stop'),
            tool_grant_path=str(root/'new-tool-grant.json'),tool_review_ref='fixture:cloud-startup')
        proposed={n:str(root/('new-'+n+'.json')) for n in paths}
        graph=prepare_aligned_startup(originals=old_raw,original_paths={n:str(p) for n,p in paths.items()},
            original_sha256={n:launch.digest(p) for n,p in paths.items()},new_paths=proposed,
            service_path=str(new_service),service_raw=encoded(plan.service),expected_service_sha256=digest(encoded(plan.service)),
            home_descriptor=service.home_approval(plan.service),project_descriptor=service.project_read_approval(plan.service),
            source_replacements={str(NATIVE/'project_service_process_candidate.py'):{'before':source_before,'after':launch.digest(service.__file__)}},
            launch_paths={n:{k:str(root/('new-'+n+'-'+k)) for k in ('attemptPath','stdoutPath','stderrPath')} for n in ('capture','connected')},

        reader_originals={'reader-runtime':reader_profile.read_bytes(),'reader-service':managed.read_bytes()},
        reader_paths={'reader-runtime':str(reader_profile),'reader-service':str(managed)},
        reader_sha256={'reader-runtime':launch.digest(reader_profile),'reader-service':launch.digest(managed)},
        new_reader_paths={n:str(root/('new-'+n+'.json')) for n in ('reader-runtime','reader-service')},
        sdk_runtime=plan.runtime,capture_source_hashes={str(n):launch.digest(n) for n in launch.capture_source_paths(runtime)},
        reader_source_hashes={str(n):launch.digest(n) for n in roles.source_paths(runtime)},
        reader_launch_paths={n:{k:str(root/('new-'+n+'-'+k)) for k in fields} for n,fields in
            {'reader-runtime':('readyPath','stopPath'),'reader-service':('attemptPath','stopPath')}.items()})

        put(new_view,plan.runtime);put(new_service,plan.service)
        proposed=dict(graph.paths)
        for n,raw in graph.files.items():put(proposed[n],json.loads(raw))
        grant=ReviewedProjectToolGrant(root/'new-tool-grant.json',reader,'fixture:cloud-startup');grant.path.write_bytes(grant.document())
        print('Cloud startup: native graph and owned connected launch',flush=True)
        profile_evidence={'old':{n:json.loads(raw) for n,raw in old_raw.items()},
            'new':{n:json.loads(raw) for n,raw in graph.files.items()},
            'oldHost':baseline,'oldRuntime':read(view),'newHost':plan.service,'newRuntime':plan.runtime,
            'originalOperator':read(owner.profile),'liveWorkspaceChanged':False,'syntheticOnly':True}
        (WS.parent/'NATIVE-PROFILE-VIEWS.json').write_text(json.dumps(profile_evidence,indent=2))
        checked,*_=startup.checked_startup(proposed['startup'],launch.digest(proposed['startup']))
        held=[]
        def stop_new():
            for child in reversed(held):
                if hasattr(child,'poll') and hasattr(child,'terminate'):
                    if child.poll() is None:child.terminate()
                    child.wait(30)
        self.addCleanup(stop_new)
        # First activation belongs to the explicit owner installer. Recurring
        # recovery deliberately refuses a writer with no prior attempt receipt.
        reader_child,_=reader_service.launch_service(proposed['reader-service'],launch.digest(proposed['reader-service']),proposed['connected-approval'])
        held.append(reader_child)
        case.wait_for(lambda: reader_service.service_state(proposed['reader-service'],launch.digest(proposed['reader-service']),proposed['connected-approval'])['ready'],reader_child)
        writer_child,_=service.launch_service(new_service,launch.digest(new_service),proposed['writer-approval'])
        held.append(writer_child)
        case.wait_for(lambda: service.service_state(new_service,launch.digest(new_service),
            proposed['writer-approval'])['ready'],writer_child)
        with MeshLauncherWindow(WS,launch.digest(WS/'integrations/restart-workroom-preview.ps1')) as window:
            result,children=startup.ensure_capture_first(window,approval_path=proposed['startup'],approval_sha=launch.digest(proposed['startup']))
            held.extend(children)
            if result.get('startupMode')!='connected':
                problems=[{'type':type(e).__name__,'frames':[{'file':Path(f.filename).name,'function':f.name,'line':f.lineno}
                    for f in traceback.extract_tb(e.__traceback__)[-12:]]} for e in children if isinstance(e,BaseException)]
                details={'result':result,'failures':problems,'messagesAndLocalsExcluded':True}
                (WS.parent/'STARTUP-HOLD.json').write_text(json.dumps(details,indent=2))
                print(json.dumps(details),flush=True)
            self.assertEqual(result.get('startupMode'),'connected',result)
        client=AgentHomeClient(f'http://127.0.0.1:{port}',agent_id='cyony',binding_sha256=home_binding_sha256(homes['cyony']),credential_provider=lambda:tokens['cyony'],timeout=10)
        self.assertEqual(client.call('recall',{})['records'],[])
        import http.client
        connection=http.client.HTTPConnection('127.0.0.1',port,timeout=10)
        try:
            connection.request('POST','/v1/project/read',body=encoded({'query':'cloudstartupqualification'}),headers={
                'Authorization':'Bearer '+tokens['context'],'X-Onoes-Context-Principal':'context-cyony',
                'X-Onoes-Context-Binding':context_binding_sha256(reader),'Content-Type':'application/json'})
            response=connection.getresponse();body=json.loads(response.read());self.assertEqual(response.status,200)
            row,=body['result']['records'];self.assertEqual(json.loads(row['claim']),doc);self.assertTrue(row['provenance'])
        finally:connection.close()
        # Verify the actual new Mesh HTTP path, not just the writer's listener:
        # the existing saved card must open from the reconnected same board.
        new_connected=read(proposed['connected'])
        def listening():
            for line in Path(new_connected['stdoutPath']).read_text().splitlines():
                try:event=json.loads(line)
                except ValueError:continue
                if event.get('event')=='mesh_listening':return event
        observed=case.wait_for(listening,next(c for c in held if getattr(c,'pid',None)==result['pid']))
        request=fixtures.admitted_http(observed['url']);session=request('/api/trial-session/bootstrap',{})
        card=request('/api/tasks/'+p['projectSync']['links'][0]['cardId'],csrf=session['csrfToken'],method='GET')['task']
        self.assertEqual(card['title'],'Composed launcher saved title')
        request('/api/trial-session/logout',{},session['csrfToken'])
        self.assertTrue(all(path.read_bytes()==old_raw[n] for n,path in paths.items()))
        assert_sdk(MIND)
        (WS.parent/'SDK-FORWARD.json').write_text(json.dumps({'passed':True,'sdk':str(MIND),'sameCredential':True,'sameBinding':True,'syntheticOnly':True}))
        print('Cloud startup: connected, same board and current handoff verified',flush=True)

    finally:
        if not self.doCleanups():raise AssertionError('Owned phase cleanup failed')
    if direction=='forward':retire_forward_owner()


def retire_forward_owner():
    """Restore the copy's originally absent slot after exact owned retirement.

    Profile switching cannot discard an unknown owner. Use the unchanged native
    ownership/attempt validators, preserve its evidence, and hold the existing
    launcher window through the metadata-only restoration.
    """
    proposal=read(WS.parent/'NATIVE-PROFILE-VIEWS.json')
    root=Path(proposal['newHost']['attemptPath']).parent
    profile=root/'new-startup.json'
    with MeshLauncherWindow(WS,launch.digest(WS/'integrations/restart-workroom-preview.ps1')) as window:
        _,handoff,_,_=startup.checked_startup(profile,launch.digest(profile))
        selected=startup.profiles(handoff)
        owner=startup.owner_record(window,handoff,selected,roles)
        assert owner and owner['mode']=='connected' and owner['live'] is False
        receipt=WS.parent/'workroom-ab-preview-process.json';before=receipt.read_bytes()
        assert digest(before)==owner['receiptSha256']
        startup.retire_mode(window,selected['connected'],{**handoff['connected'],'mode':'connected'},roles)
        assert not roles.same_process_alive(owner['record']['pid'],owner['record']['creationTicks'])
        destination=WS.parent/'SDK-retired-forward-owner.json'
        assert not destination.exists() and receipt.read_bytes()==before
        receipt.rename(destination)
        assert destination.read_bytes()==before and not receipt.exists()
        (WS.parent/'SDK-OWNER-RETIREMENT.json').write_text(json.dumps({
            'state':'exact_owned_process_retired','pid':owner['record']['pid'],
            'creationTicks':owner['record']['creationTicks'],'receiptSha256':digest(before),
            'originalSlot':'absent','receiptArchived':True,'launcherWindowHeld':True,'syntheticOnly':True}))


def inverse(self,case,packet,paths,baseline_path,managed,reader_profile):
    held=[]
    try:
        child,_=reader_service.launch_service(managed,launch.digest(managed),paths['connected-approval']);held.append(child)
        case.wait_for(lambda: reader_service.service_state(managed,launch.digest(managed),paths['connected-approval'])['ready'],child)
        child,_=service.launch_service(baseline_path,launch.digest(baseline_path),paths['writer-approval']);held.append(child)
        case.wait_for(lambda: service.service_state(baseline_path,launch.digest(baseline_path),paths['writer-approval'])['ready'],child)
        with MeshLauncherWindow(WS,launch.digest(WS/'integrations/restart-workroom-preview.ps1')) as window:
            result,children=startup.ensure_capture_first(window,approval_path=paths['startup'],approval_sha=launch.digest(paths['startup']))
            held.extend(children);self.assertEqual(result.get('startupMode'),'connected',result)
        connected=read(paths['connected'])
        def listening():
            for line in Path(connected['stdoutPath']).read_text().splitlines():
                try:event=json.loads(line)
                except ValueError:continue
                if event.get('event')=='mesh_listening':return event
        event=case.wait_for(listening,next(c for c in held if getattr(c,'pid',None)==result['pid']))
        request=fixtures.admitted_http(event['url']);session=request('/api/trial-session/bootstrap',{})
        card=request('/api/tasks/'+packet['p']['projectSync']['links'][0]['cardId'],csrf=session['csrfToken'],method='GET')['task']
        self.assertEqual(card['title'],'Composed launcher saved title')
        recalled=request('/api/mind/recall',{'query':'cloudstartupqualification','limit':8},session['csrfToken'])
        row,=recalled['records'];self.assertEqual(json.loads(row['claim']),packet['doc'])
        self.assertTrue(row['provenance'])
        request('/api/trial-session/logout',{},session['csrfToken'])
        state=roles.reader_state(reader_profile,launch.digest(reader_profile),paths['connected-approval'])
        self.assertTrue(state['ready']);assert_sdk(MIND)
        (WS.parent/'SDK-INVERSE.json').write_text(json.dumps({'passed':True,'sdk':str(MIND),
            'sameBoard':True,'sameReaderEnrollment':True,'sameSharedHandoff':True,'syntheticOnly':True}))
        print('SDK inverse: original reader, host and saved card verified',flush=True)
    finally:
        for child in reversed(held):
            if hasattr(child,'poll'):
                if child.poll() is None:child.terminate()
                child.wait(30)


if __name__=='__main__':
    try:child_phase(sys.argv[1],Path(sys.argv[2]))
    except BaseException as error:
        observation={'type':type(error).__name__,'direction':sys.argv[1],
            'frames':[{'file':Path(f.filename).name,'function':f.name,'line':f.lineno}
                for f in traceback.extract_tb(error.__traceback__)],
            'messagesAndLocalsExcluded':True,'syntheticOnly':True}
        (WS.parent/('SDK-FAILURE-'+sys.argv[1]+'.json')).write_text(json.dumps(observation,indent=2))
        print(json.dumps(observation),flush=True)
        raise SystemExit(1)
