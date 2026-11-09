"""Isolated native HTTP/agent/tool/store qualification; never install or use live models."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import shutil
import sys
import tarfile
import uuid

NATIVE_HEAD = 'acc3cada0da86c81efc8aa6c5a291989549ca900'


def terminal_proof_seen(results):
    for raw in results:
        try:
            value = json.loads(raw)
        except (ValueError, TypeError):
            continue
        if (isinstance(value, dict) and isinstance(value.get('output'), str)
                and value['output'].strip() == 'mesh-runtime-proof'
                and type(value.get('exit_code')) is int and value['exit_code'] == 0
                and value.get('error') is None):
            return True
    return False


def verify_evidence(root):
    manifest = json.loads((root / 'manifest.json').read_text(encoding='utf-8'))
    report = json.loads((root / 'runtime-qualification.json').read_text(encoding='utf-8'))
    provider = json.loads((root / 'provider-evidence.json').read_text(encoding='utf-8'))
    restart = json.loads((root / 'restart-evidence.json').read_text(encoding='utf-8'))
    if report['qualification'] != 'PASS' or not terminal_proof_seen(provider['toolResults']):
        raise RuntimeError('Exact successful tool output is not proven')
    for name, digest in manifest['files'].items():
        if hashlib.sha256((Path(manifest['source']) / name).read_bytes()).hexdigest() != digest:
            raise RuntimeError('Native candidate source changed since qualification')
    if (restart['agentsBeforeRestart'] != restart['agentsAfterRestart']
            or restart['fencesBeforeRestart'] != restart['fencesAfterRestart']
            or restart['restored']['writer_lifecycle']['state'] != 'unknown'
            or restart['restored']['writer_lifecycle']['writerQuiescence']):
        raise RuntimeError('Restart identity evidence is incomplete')
    result = {'qualification': 'PASS', 'checks': ['exact_exit_zero_tool_output_without_error',
              'all_candidate_source_hashes', 'restart_without_new_agent_or_fence', 'no_writer_release'],
              'wholeWorkerReleaseQualified': False}
    if 'actual_native_title_callback_keeps_completed_reply_worker_held' in report['checks']:
        pending = json.loads((root / 'title-pending-status.json').read_text(encoding='utf-8'))
        finished = json.loads((root / 'final-status.json').read_text(encoding='utf-8'))
        before = pending['writer_lifecycle']['enrollment']['lifetime']
        after = finished['writer_lifecycle']['enrollment']['lifetime']
        if (not before['rootEnded'] or before['managedWorkEnded']
                or not any(item['kind'] == 'background' for item in before['pendingWorkers'])
                or not after['managedWorkEnded'] or after['pendingWorkers']):
            raise RuntimeError('Native title callback lifetime evidence is incomplete')
        result['checks'].append('native_title_pending_then_actual_thread_exit')
    if 'native_SQLite_canonical_claim_lookup_and_worker_binding' in report['checks']:
        claim = json.loads((root / 'canonical-claim-evidence.json').read_text(encoding='utf-8'))
        if (not claim['durableClaimMatched'] or not claim['duplicateRefused']
                or not claim['lifetime']['managedWorkEnded'] or claim['lifetime']['writerQuiescence']):
            raise RuntimeError('Canonical claim binding evidence is incomplete')
        result['checks'].append('native_SQLite_canonical_claim_binding_without_release')
    if 'actual_canonical_HTTP_FIFO_observer_cancellation_and_exact_replay' in report['checks']:
        fifo = json.loads((root/'canonical-fifo-evidence.json').read_text(encoding='utf-8'))
        held = fifo['heldAfterObserverCancellation']['lifetime']
        if (not fifo['realRunnerAndAuthority'] or not fifo['successorWaitedQueued']
                or not fifo['replayCreatedNoWork'] or held['rootEnded'] or held['managedWorkEnded']
                or fifo['generations'][0] >= fifo['generations'][1]
                or fifo['terminalStatuses'] != ['terminal','terminal']
                or fifo.get('verifiedOutputs') != ['mesh fixture completed','mesh fixture completed']
                or any(not worker['lifetime']['managedWorkEnded'] or worker['writerQuiescence'] for worker in fifo['finalWorkers'])):
            raise RuntimeError('Actual canonical FIFO execution evidence is incomplete')
        result['checks'].append('actual_canonical_FIFO_results_cancellation_ordering_and_replay')
    if 'actual_canonical_retirement_timeout_drain_and_successor_queue_recovery' in report['checks']:
        retired=json.loads((root/'canonical-retirement-evidence.json').read_text(encoding='utf-8'))
        held=retired['heldWorker']['lifetime'];unknown=retired['newOwnerObservation']
        if (not retired['fullNativeRetirementAndRecovery'] or not retired['timeoutRetainedOwnership']
                or not retired['queuedAdmissionPreserved'] or held['rootEnded'] or held['managedWorkEnded']
                or retired['newEpoch']<=retired['oldEpoch'] or unknown['state']!='unknown'
                or unknown['enrollment'] is not None or unknown['writerQuiescence']
                or not retired['recoveredExactlyOnce'] or not retired['replayCreatedNoWorker']
                or retired['verifiedOutput']!='mesh fixture completed'
                or not retired['recoveredWorker']['lifetime']['managedWorkEnded']
                or retired['recoveredWorker']['writerQuiescence']):
            raise RuntimeError('Actual canonical owner retirement/recovery evidence is incomplete')
        result['checks'].append('actual_retirement_keeps_ownership_then_recovers_queue_once')
    if 'actual_abrupt_owner_process_loss_blocks_replay_and_preserves_queue' in report['checks']:
        before=json.loads((root/'abrupt-owner-before.json').read_text(encoding='utf-8'))
        lost=json.loads((root/'abrupt-owner-recovery.json').read_text(encoding='utf-8'))
        writer=lost['writerObservation'];held=before['heldWorker']['lifetime']
        if (not lost['realSeparateProcesses'] or lost['processExitCodes']!=[73,0]
                or lost['newEpoch']<=lost['oldEpoch'] or held['rootEnded'] or held['managedWorkEnded']
                or lost['activeStatus']!='unknown' or lost['queuedStatus']!='queued'
                or not lost['queuedAdmissionPreserved'] or not lost['claimBlockedByUnknown']
                or not lost['retryCreatedNoWorker'] or lost['savedAdmissionCount']!=2
                or writer['state']!='unknown' or writer['enrollment'] is not None
                or writer['ownerId']==before['ownerId'] or writer['writerQuiescence']):
            raise RuntimeError('Abrupt process-loss recovery evidence is incomplete')
        result['checks'].append('separate_process_loss_preserves_unknown_and_blocks_duplicate_work')
    if 'actual_native_HTTP_unmanaged_owner_refused_before_reservation' in report['checks']:
        guard=json.loads((root/'owner-guard-evidence.json').read_text(encoding='utf-8'))
        if (guard['statuses']!=[409,409] or guard['codes']!=['unsupported_writer_owner']*2
                or not guard['noHandoff'] or not guard['noReservation'] or not guard['noWorker']):
            raise RuntimeError('Unmanaged owner refusal evidence is incomplete')
        result['checks'].append('unmanaged_owner_refused_without_handoff_or_reservation')
    if 'actual_native_tool_pipeline_stages_observed_without_clearance' in report['checks']:
        effects=json.loads((root/'tool-pipeline-evidence.json').read_text(encoding='utf-8'))
        pipeline=effects['pipeline']
        if (effects['observedCalls']<1 or pipeline['fullyObservedCalls']!=effects['observedCalls']
                or pipeline['lateStages'] or pipeline['completionQualified'] or effects['effectsSettled']
                or effects['unverifiedCalls']!=effects['observedCalls']):
            raise RuntimeError('Tool pipeline observations lost stages or granted clearance')
        result['checks'].append('actual_native_pipeline_stages_remain_observation_only')
    if 'actual_native_HTTP_agent_file_write_exact_bytes_without_release' in report['checks']:
        file_evidence=json.loads((root/'file-worker-evidence.json').read_text(encoding='utf-8'))
        proof=(root/'workspace'/'mesh-file-proof.md').read_bytes()
        status=file_evidence['status'];life=status['writer_lifecycle']['enrollment']['lifetime']
        if (proof!=b'Mesh native file proof.\n' or hashlib.sha256(proof).hexdigest()!=file_evidence['sha256']
                or status['status']!='completed' or not life['managedWorkEnded']
                or status['writer_lifecycle']['writerQuiescence'] or life['toolEffects']['effectsSettled']):
            raise RuntimeError('Native file worker evidence is incomplete or incorrectly releases ownership')
        result['checks'].append('actual_native_file_write_bytes_and_held_ownership')
    if 'actual_file_bytes_do_not_settle_held_native_bookkeeping' in report['checks']:
        file_evidence=json.loads((root/'file-worker-evidence.json').read_text(encoding='utf-8'))
        held=file_evidence['heldAfterBytes']['writer_lifecycle'];final=file_evidence['status']['writer_lifecycle']
        life=held['enrollment']['lifetime']
        if (held['runId']!=final['runId'] or held['ownerId']!=final['ownerId']
                or held['enrollment']['generation']!=final['enrollment']['generation'] or life['rootEnded'] or life['managedWorkEnded']
                or life['toolEffects']['activeCalls']!=1 or held['writerQuiescence']):
            raise RuntimeError('Held file bookkeeping evidence is incomplete or misbound')
        result['checks'].append('file_bytes_precede_handler_completion_without_ownership_release')
    if report.get('nativeSafeMode'):
        if 'native_safe_mode_plain_terminal_and_file_pipeline' not in report['checks']:
            raise RuntimeError('Safe mode has no native pipeline acceptance')
        terminal=json.loads((root/'tool-pipeline-evidence.json').read_text(encoding='utf-8'))
        file_effects=json.loads((root/'file-worker-evidence.json').read_text(encoding='utf-8'))['status']['writer_lifecycle']['enrollment']['lifetime']['toolEffects']
        for effects in [terminal,file_effects]:
            pipeline=effects['pipeline']
            if (not effects['observedCalls'] or pipeline['plainNativeCalls']!=effects['observedCalls']
                    or pipeline['blockerCalls'] or pipeline['otherOrMissingCalls'] or pipeline['lateStages']):
                raise RuntimeError('Safe-mode pipeline evidence is incomplete')
        result['checks'].append('native_safe_mode_has_plain_terminal_and_file_pipeline')
    (root / 'verified-evidence.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    return result


def prepare(native_root):
    native_root = Path(native_root).resolve()
    head = subprocess.check_output(['git', '-C', str(native_root), 'rev-parse', 'HEAD'], text=True).strip()
    if head != NATIVE_HEAD:
        raise RuntimeError('Native HEAD changed; review before runtime qualification')
    from integrations.prepare_hermes_writer_scope import prepare as candidate
    generated, _, modules = candidate(native_root / 'tools/process_registry.py')
    root = Path(__file__).resolve().parents[1] / 'data' / ('hermes-runtime-' + str(uuid.uuid4()))
    source = root / 'source'; source.mkdir(parents=True)
    archive = root / 'source.tar'
    subprocess.run(['git', '-C', str(native_root), 'archive', '--format=tar', '--output=' + str(archive), head], check=True)
    with tarfile.open(archive) as tar:
        members = []
        for member in tar.getmembers():
            if member.issym() or member.islnk():
                raise RuntimeError('Source archive links require separate review')
            if member.name == '.github/workflows' or member.name.startswith('.github/workflows/'):
                continue
            members.append(member)
        tar.extractall(source, members=members, filter='data')
    subprocess.run(['git', 'apply', str(generated / 'candidate.patch')], cwd=source, check=True)
    for name, content in modules.items():
        if (source / name).read_bytes() != content.encode('utf-8'):
            raise RuntimeError('Applied candidate differs from generated bytes: ' + name)
    home = root / 'fixture-home'; home.mkdir()
    for name in ['appdata', 'localappdata', 'temp', 'workspace']:
        (root / name).mkdir()
    (home / 'config.yaml').write_text('model:\n  provider: custom\n  default: mesh-runtime-fixture\nterminal:\n  backend: local\n', encoding='utf-8')
    report = {'state': 'isolated_candidate', 'nativeHead': head, 'candidate': str(generated),
              'source': str(source), 'home': str(home), 'liveInstallation': False,
              'wholeWorkerReleaseQualified': False,
              'files': {name: hashlib.sha256((source / name).read_bytes()).hexdigest() for name in modules}}
    (root / 'manifest.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    return root


async def qualify_canonical_retirement(root, adapter, origin, key, runner, endpoint, factory, fences):
    """Real owner drain/recovery, held at fixture runtime selection in the actual worker."""
    import asyncio
    import threading
    import time
    from uuid import uuid4
    from aiohttp import ClientSession
    from gateway.config import GatewayConfig, Platform
    from gateway.run import GatewayRunner
    from gateway.run_runtime import _retire_profile_authority, initialize_gateway_runtime
    from gateway.runtime_ownership import process_ownership
    from gateway.session_api_turn import recover_api_turns, _settled_api_result
    from gateway.platforms.api_server_authority_runs import run_admission
    from tools.mesh_writer_scope import WriterRunRegistry, observe_writer_run
    entered,release = threading.Event(),threading.Event()
    route = ('mesh-runtime-fixture',{'base_url':endpoint,'api_key':'synthetic-local-provider',
             'provider':'custom','api_mode':'chat_completions'})
    def held_route(**kwargs):
        entered.set()
        if not release.wait(timeout=30):
            raise RuntimeError('Synthetic runtime selection gate timed out')
        return route[0],dict(route[1])
    runner._resolve_session_agent_runtime = held_route
    old_registry = adapter._mesh_writer_runs
    authority = runner.session_authorities.launch
    home = root/'fixture-home'
    try:
        async with ClientSession() as client:
            headers={'Authorization':'Bearer '+key,'Idempotency-Key':'mesh-retirement-active'}
            body={'input':'Synthetic owner retirement active request.','session_id':uuid4().hex}
            async with client.post(origin+'/v1/runs',headers=headers,json=body) as response:
                active=await response.json()
                if response.status not in (200,201,202):raise RuntimeError('Retirement active admission failed')
            active_id=active['run_id'];deadline=time.monotonic()+20
            while not entered.is_set():
                if time.monotonic()>deadline:raise RuntimeError('Actual retirement worker did not enter fixture gate')
                await asyncio.sleep(.02)
            queued_headers={**headers,'Idempotency-Key':'mesh-retirement-queued'}
            queued_body={**body,'input':'Synthetic preserved queued request.'}
            async with client.post(origin+'/v1/runs',headers=queued_headers,json=queued_body) as response:
                waiting=await response.json()
                if response.status not in (200,201,202):raise RuntimeError('Retirement queued admission failed')
            waiting_id=waiting['run_id'];before=run_admission(adapter,waiting_id)[1]
            if before['status']!='queued' or old_registry.snapshot(waiting_id) is not None:
                raise RuntimeError('Retirement successor was not queued without a worker')
            first_retirement=await _retire_profile_authority(authority,timeout=.02)
            held=old_registry.snapshot(active_id)
            if first_retirement is not False or not process_ownership.owns(home) or authority.retired:
                raise RuntimeError('Timed-out owner retirement released ownership')
            if not held or held['lifetime']['rootEnded'] or held['lifetime']['managedWorkEnded']:
                raise RuntimeError('Retirement timeout lost its still-running worker')
            if run_admission(adapter,waiting_id)[1]['status']!='queued' or old_registry.snapshot(waiting_id) is not None:
                raise RuntimeError('Retiring owner started its queued successor')
            release.set()
            if not await _retire_profile_authority(authority,timeout=15):
                raise RuntimeError('Actual owner did not drain after worker gate release')
            tasks=list(adapter._active_run_tasks.values())
            if tasks:await asyncio.wait_for(asyncio.gather(*tasks,return_exceptions=True),timeout=5)
            if run_admission(adapter,waiting_id)[1]['status']!='queued' or old_registry.snapshot(waiting_id) is not None:
                raise RuntimeError('Retired owner consumed the waiting request')
            deadline=time.monotonic()+10
            while not old_registry.snapshot(active_id)['lifetime']['managedWorkEnded']:
                if time.monotonic()>deadline:raise RuntimeError('Retired worker background work remained active')
                await asyncio.sleep(.02)
            old_epoch=authority.epoch
            process_ownership.release(home)
            process_ownership.reserve([home])
            successor=GatewayRunner(GatewayConfig(multiplex_profiles=False))
            successor._resolve_session_agent_runtime=lambda **kwargs:(route[0],dict(route[1]))
            successor._resolve_turn_toolsets=lambda *args,**kwargs:(['terminal'],[])
            await initialize_gateway_runtime(successor)
            successor.adapters[Platform.API_SERVER]=adapter;adapter.gateway_runner=successor
            adapter._mesh_writer_runs=WriterRunRegistry(factory)
            unknown=observe_writer_run(adapter._mesh_writer_runs,active_id)
            if unknown['state']!='unknown' or unknown['ownerId']==old_registry.owner_id:
                raise RuntimeError('Successor reused old worker ownership')
            recover_api_turns(adapter)
            deadline=time.monotonic()+30
            while True:
                owner,row=run_admission(adapter,waiting_id)
                state=adapter._mesh_writer_runs.snapshot(waiting_id)
                if row['status']=='terminal' and state and state['lifetime']['managedWorkEnded']:break
                if time.monotonic()>deadline:raise RuntimeError('Successor failed to recover queued work')
                await asyncio.sleep(.02)
            result,_usage=_settled_api_result(owner,row['admission_id'])
            if (row['admission_id']!=before['admission_id'] or owner.epoch<=old_epoch
                    or result.get('failed') or result.get('final_response')!='mesh fixture completed'
                    or sum(fence.run_id==waiting_id for fence in fences)!=1 or state['writerQuiescence']):
                raise RuntimeError('Recovered work identity/result/single execution is unproven')
            fence_count=len(fences)
            async with client.post(origin+'/v1/runs',headers=queued_headers,json=queued_body) as response:
                replay=await response.json()
            if replay.get('run_id')!=waiting_id or len(fences)!=fence_count:
                raise RuntimeError('Recovered exact retry duplicated work')
            evidence={'timeoutRetainedOwnership':True,'heldWorker':held,'queuedAdmissionPreserved':True,
                'oldEpoch':old_epoch,'newEpoch':owner.epoch,'newOwnerObservation':unknown,
                'recoveredWorker':state,'recoveredExactlyOnce':True,'replayCreatedNoWorker':True,
                'verifiedOutput':result['final_response'],'fullNativeRetirementAndRecovery':True}
            (root/'canonical-retirement-evidence.json').write_text(json.dumps(evidence,indent=2),encoding='utf-8')
    finally:
        release.set()


async def abrupt_owner_process(root, recovering):
    """Dedicated synthetic owner process; the first intentionally skips all cleanup."""
    import asyncio
    import socket
    import threading
    import time
    from uuid import uuid4
    from aiohttp import ClientSession
    sys.path.insert(0,str(root/'source'));os.chdir(root/'source')
    from hermes_constants import get_hermes_home
    from gateway.config import GatewayConfig, Platform, PlatformConfig
    from gateway.run import GatewayRunner
    from gateway.run_runtime import initialize_gateway_runtime
    from gateway.runtime_ownership import process_ownership
    from gateway.session_api_turn import recover_api_turns
    from gateway.platforms.api_server import APIServerAdapter
    from gateway.platforms.api_server_authority_runs import run_admission
    from hermes_state_runtime import claim_session_input, list_session_admissions, RuntimeStoreError
    from tools.mesh_writer_scope import WriterRunRegistry
    from tools.mesh_windows_writer_fence import WindowsWriterFence
    home=root/'crash-home'
    if Path(get_hermes_home()).resolve()!=home.resolve():raise RuntimeError('Abrupt-loss profile is not isolated')
    process_ownership.reserve([home]);fences=[];adapter=None;entered=threading.Event()
    def factory(run_id,generation):
        fence=WindowsWriterFence(run_id,generation);fences.append(fence);return fence
    def route(**kwargs):
        if not recovering:
            entered.set()
            if not threading.Event().wait(timeout=30):raise RuntimeError('Abrupt-loss gate expired without intentional exit')
        raise RuntimeError('Unexpected model request in crash-recovery fixture')
    try:
        runner=GatewayRunner(GatewayConfig(multiplex_profiles=False))
        runner._resolve_session_agent_runtime=route
        runner._resolve_turn_toolsets=lambda *args,**kwargs:(['terminal'],[])
        await initialize_gateway_runtime(runner)
        with socket.socket() as free:free.bind(('127.0.0.1',0));port=free.getsockname()[1]
        # Fixed synthetic key for the two isolated processes, never a live key.
        key=hashlib.sha256(b'mesh-abrupt-owner-fixture-only').hexdigest()
        adapter=APIServerAdapter(PlatformConfig(enabled=True,extra={'host':'127.0.0.1','port':port,
            'key':key,'model_name':'mesh-runtime-fixture'}))
        adapter._mesh_writer_runs=WriterRunRegistry(factory)
        adapter.gateway_runner=runner;runner.adapters[Platform.API_SERVER]=adapter
        if not await adapter.connect():raise RuntimeError('Crash fixture API did not start')
        origin='http://127.0.0.1:'+str(port);headers={'Authorization':'Bearer '+key}
        authority=runner.session_authorities.launch
        async with ClientSession() as client:
            if not recovering:
                body={'input':'Synthetic abrupt loss active.','session_id':uuid4().hex}
                queued_body={**body,'input':'Synthetic abrupt loss queued.'}
                async with client.post(origin+'/v1/runs',headers={**headers,'Idempotency-Key':'mesh-crash-active'},json=body) as response:
                    active=await response.json()
                    if response.status not in (200,201,202):raise RuntimeError('Crash active admission refused')
                deadline=time.monotonic()+20
                while not entered.is_set():
                    if time.monotonic()>deadline:raise RuntimeError('Crash worker did not enter real synchronous body')
                    await asyncio.sleep(.02)
                async with client.post(origin+'/v1/runs',headers={**headers,'Idempotency-Key':'mesh-crash-queued'},json=queued_body) as response:
                    queued=await response.json()
                    if response.status not in (200,201,202):raise RuntimeError('Crash queued admission refused')
                row=run_admission(adapter,queued['run_id'])[1]
                held=adapter._mesh_writer_runs.snapshot(active['run_id'])
                if row['status']!='queued' or held['lifetime']['rootEnded'] or adapter._mesh_writer_runs.snapshot(queued['run_id']) is not None:
                    raise RuntimeError('Crash fixture was not active-plus-queued')
                evidence={'pid':os.getpid(),'epoch':authority.epoch,'ownerId':adapter._mesh_writer_runs.owner_id,
                    'activeRunId':active['run_id'],'queuedRunId':queued['run_id'],'queuedAdmissionId':row['admission_id'],
                    'sessionId':body['session_id'],'activeBody':body,'heldWorker':held}
                with (root/'abrupt-owner-before.json').open('w',encoding='utf-8') as output:
                    json.dump(evidence,output,indent=2);output.flush();os.fsync(output.fileno())
                os._exit(73)  # This fixture process only: genuinely bypass finally/owner drain.
            before=json.loads((root/'abrupt-owner-before.json').read_text(encoding='utf-8'))
            recover_api_turns(adapter)
            await asyncio.sleep(0)
            active_row=run_admission(adapter,before['activeRunId'])[1]
            queued_row=run_admission(adapter,before['queuedRunId'])[1]
            if (authority.epoch<=before['epoch'] or active_row['status']!='unknown'
                    or queued_row['status']!='queued' or queued_row['admission_id']!=before['queuedAdmissionId']):
                raise RuntimeError('Abrupt loss did not preserve unknown-plus-queued input')
            blocked=False
            try:claim_session_input(authority.db,epoch=authority.epoch,session_id=before['sessionId'])
            except RuntimeStoreError as error:
                if error.reason!='unknown_execution':raise
                blocked=True
            async with client.get(origin+'/v1/runs/'+before['activeRunId'],headers=headers) as response:
                observed=await response.json()
                if response.status!=200:raise RuntimeError('Crash native status lookup failed')
            writer=observed['writer_lifecycle']
            if writer['state']!='unknown' or writer['enrollment'] is not None or writer['ownerId']==before['ownerId'] or writer['writerQuiescence']:
                raise RuntimeError('New process reused stale writer proof')
            async with client.post(origin+'/v1/runs',headers={**headers,'Idempotency-Key':'mesh-crash-active'},json=before['activeBody']) as response:
                retry=await response.json();retry_status=response.status
            if retry_status not in (200,201,202,409) or retry_status!=409 and retry.get('run_id')!=before['activeRunId']:
                raise RuntimeError('Unknown execution retry did not preserve its identity')
            rows=list_session_admissions(authority.db,session_id=before['sessionId'],pending_only=False)
            if not blocked or len(rows)!=2 or fences or authority.executing:
                raise RuntimeError('New owner dispatched or duplicated unresolved work')
            evidence={'oldPid':before['pid'],'newPid':os.getpid(),'oldEpoch':before['epoch'],'newEpoch':authority.epoch,
                'activeStatus':active_row['status'],'queuedStatus':queued_row['status'],'queuedAdmissionPreserved':True,
                'claimBlockedByUnknown':blocked,'writerObservation':writer,'retryStatus':retry_status,
                'retryCreatedNoWorker':True,'savedAdmissionCount':len(rows),'realSeparateProcesses':True}
            (root/'abrupt-owner-recovery.json').write_text(json.dumps(evidence,indent=2),encoding='utf-8')
    finally:
        if adapter is not None:await adapter.disconnect()
        for fence in fences:fence.terminate();fence.close()
        process_ownership.close()


async def qualify_abrupt_owner_loss(root):
    import asyncio
    home=root/'crash-home';home.mkdir()
    (home/'config.yaml').write_text('model:\n  provider: custom\n  default: mesh-runtime-fixture\nterminal:\n  backend: local\n',encoding='utf-8')
    environment={name:value for name,value in os.environ.items() if name.upper() in {
        'SYSTEMROOT','WINDIR','COMSPEC','PATH','PATHEXT','PROGRAMFILES','PROGRAMFILES(X86)','PYTHONPATH'}}
    environment.update(HERMES_HOME=str(home),HOME=str(home),USERPROFILE=str(home),APPDATA=str(root/'appdata'),
        LOCALAPPDATA=str(root/'localappdata'),TEMP=str(root/'temp'),TMP=str(root/'temp'),
        PYTHONIOENCODING='utf-8',TERMINAL_ENV='local',TERMINAL_CWD=str(root/'workspace'))
    exits=[]
    for mode,expected in [('--crash-owner',73),('--recover-owner',0)]:
        with (root/(mode[2:]+'.log')).open('wb') as log:
            result=await asyncio.to_thread(subprocess.run,[sys.executable,str(Path(__file__).resolve()),mode,str(root)],
                cwd=root/'source',env=environment,stdout=log,stderr=subprocess.STDOUT,
                creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0),timeout=90)
        exits.append(result.returncode)
        if result.returncode!=expected:raise RuntimeError('Isolated '+mode+' exited unexpectedly: '+str(result.returncode))
    evidence=json.loads((root/'abrupt-owner-recovery.json').read_text(encoding='utf-8'))
    evidence['processExitCodes']=exits
    (root/'abrupt-owner-recovery.json').write_text(json.dumps(evidence,indent=2),encoding='utf-8')


async def child(root):
    import asyncio
    import secrets
    import socket
    import time
    from aiohttp import web, ClientSession
    source = root / 'source'
    sys.path.insert(0, str(source))
    os.chdir(source)
    from gateway.config import PlatformConfig
    from gateway.platforms.api_server import APIServerAdapter
    from tools.mesh_writer_scope import WriterRunRegistry
    from tools.mesh_windows_writer_fence import WindowsWriterFence
    from run_agent import AIAgent
    from hermes_constants import get_hermes_home
    if Path(get_hermes_home()).resolve() != (root / 'fixture-home').resolve():
        raise RuntimeError('Native home is not isolated')
    requests, tools_seen, fences, agents_created = [], [], [], []
    title_started, title_release = asyncio.Event(), asyncio.Event()
    canonical_started, canonical_release = asyncio.Event(), asyncio.Event()
    canonical_mode = False
    file_mode = False
    async def provider(request):
        body = await request.json()
        requests.append({'path': request.path, 'tools': [item.get('function', {}).get('name') or item.get('name')
                         for item in body.get('tools', [])], 'roles': [item.get('role') for item in body.get('messages', [])]})
        for message in body.get('messages', []):
            if message.get('role') == 'tool':
                tools_seen.append(str(message.get('content', '')))
        terminal_allowed = any(item.get('function', {}).get('name') == 'terminal' for item in body.get('tools', []))
        file_allowed = any(item.get('function', {}).get('name') == 'write_file' for item in body.get('tools', []))
        worker_allowed = terminal_allowed or file_allowed
        if canonical_mode and terminal_allowed:
            canonical_started.set()
            await asyncio.wait_for(canonical_release.wait(), timeout=30)
        if not worker_allowed:
            title_started.set()
            await asyncio.wait_for(title_release.wait(), timeout=30)
        tool = worker_allowed and not any(message.get('role') == 'tool' for message in body.get('messages', []))
        tool_name = 'write_file' if file_mode and file_allowed else 'terminal'
        tool_args = ({'path': str(root / 'workspace' / 'mesh-file-proof.md'), 'content': 'Mesh native file proof.\n'}
                     if tool_name == 'write_file' else {'command': "printf 'mesh-runtime-proof'", 'timeout': 5})
        message = ({'role': 'assistant', 'content': None, 'tool_calls': [{'id': 'call_mesh_fixture', 'type': 'function',
                    'function': {'name': tool_name, 'arguments': json.dumps(tool_args)}}]}
                   if tool else {'role': 'assistant', 'content': 'mesh fixture completed' if worker_allowed
                                 else json.dumps({'title': 'Mesh runtime fixture'})})
        finish = 'tool_calls' if tool else 'stop'
        if body.get('stream'):
            delta = dict(message); delta.pop('role', None)
            if tool:
                delta['tool_calls'][0]['index'] = 0
            chunks = [{'id': 'fixture', 'object': 'chat.completion.chunk', 'created': 1, 'model': 'mesh-runtime-fixture',
                       'choices': [{'index': 0, 'delta': delta, 'finish_reason': None}]},
                      {'id': 'fixture', 'object': 'chat.completion.chunk', 'created': 1, 'model': 'mesh-runtime-fixture',
                       'choices': [{'index': 0, 'delta': {}, 'finish_reason': finish}]}]
            return web.Response(text=''.join('data: ' + json.dumps(chunk) + '\n\n' for chunk in chunks) + 'data: [DONE]\n\n',
                                content_type='text/event-stream')
        return web.json_response({'id': 'fixture', 'object': 'chat.completion', 'created': 1, 'model': 'mesh-runtime-fixture',
             'choices': [{'index': 0, 'message': message, 'finish_reason': finish}],
             'usage': {'prompt_tokens': 1, 'completion_tokens': 1, 'total_tokens': 2}})
    provider_app = web.Application(); provider_app.router.add_post('/v1/chat/completions', provider)
    provider_runner = web.AppRunner(provider_app); await provider_runner.setup()
    site = web.TCPSite(provider_runner, '127.0.0.1', 0); await site.start()
    endpoint = 'http://127.0.0.1:' + str(site._server.sockets[0].getsockname()[1]) + '/v1'
    key = secrets.token_hex(32)  # Ephemeral test authentication only; never saved or printed.
    def factory(run_id, generation):
        fence = WindowsWriterFence(run_id, generation); fences.append(fence); return fence
    def make_adapter():
        with socket.socket() as free:
            free.bind(('127.0.0.1', 0)); port = free.getsockname()[1]
        adapter = APIServerAdapter(PlatformConfig(enabled=True, extra={'host': '127.0.0.1', 'port': port,
                                                                      'key': key, 'model_name': 'mesh-runtime-fixture'}))
        adapter._mesh_writer_runs = WriterRunRegistry(factory)
        # Only provider selection is a fixture. The actual agent, tools, API
        # admission/executor, ownership checks and persistence run unchanged.
        def create_agent(**kwargs):
            agents_created.append(True)
            callbacks = {name: value for name, value in kwargs.items() if name.endswith('_callback')
                         or name in ('session_id', 'gateway_session_key', 'ephemeral_system_prompt')}
            return AIAgent(base_url=endpoint, api_key='synthetic-local-provider', provider='custom',
                api_mode='chat_completions', model='mesh-runtime-fixture', max_iterations=4, max_tokens=256,
                enabled_toolsets=['file'] if file_mode else ['terminal'], skip_memory=True, skip_background_review=True,
                skip_context_files=True, load_soul_identity=False, quiet_mode=True,
                session_db=adapter._ensure_session_db(), cwd=str(root / 'workspace'), **callbacks)
        adapter._create_agent = create_agent
        return adapter, 'http://127.0.0.1:' + str(port)
    adapter = None
    checks = []
    try:
        adapter, origin = make_adapter()
        if not await adapter.connect():
            raise RuntimeError('Isolated native server did not start')
        async with ClientSession() as client:
            headers = {'Authorization': 'Bearer ' + key, 'Idempotency-Key': 'mesh-runtime-fixture-one'}
            unmanaged_sid='fixture-unmanaged-chat'
            adapter._ensure_session_db().create_session(unmanaged_sid,'bot_room')
            from unittest.mock import patch
            rejected_statuses,rejected_codes=[],[]
            with patch.object(adapter,'_admit_to_live_bot_chat',side_effect=AssertionError('Unmanaged handoff reached')) as handoff, \
                    patch.object(adapter._run_idempotency_store,'reserve',wraps=adapter._run_idempotency_store.reserve) as reservation:
                for _ in range(2):
                    async with client.post(origin+'/v1/runs',headers={**headers,'Idempotency-Key':'mesh-unmanaged-refusal'},
                            json={'input':'Synthetic unmanaged target refusal.','session_id':unmanaged_sid}) as response:
                        rejected=await response.json();rejected_statuses.append(response.status)
                        rejected_codes.append(rejected.get('error',{}).get('code'))
                if rejected_statuses!=[409,409] or rejected_codes!=['unsupported_writer_owner']*2:
                    raise RuntimeError('Unmanaged owner was not explicitly refused before admission')
                handoff.assert_not_called();reservation.assert_not_called()
            if agents_created or fences or adapter._run_statuses or adapter._run_owners or adapter._run_streams:
                raise RuntimeError('Refused owner retained a worker/run reservation')
            (root/'owner-guard-evidence.json').write_text(json.dumps({'statuses':rejected_statuses,'codes':rejected_codes,
                'noHandoff':True,'noReservation':True,'noWorker':True},indent=2),encoding='utf-8')
            checks.append('actual_native_HTTP_unmanaged_owner_refused_before_reservation')
            body = {'input': 'Synthetic fixture: run the provided terminal proof, then finish.'}
            async with client.post(origin + '/v1/runs', headers=headers, json=body) as response:
                admitted = await response.json()
                if response.status not in (200, 201, 202):
                    raise RuntimeError('Native admission failed: ' + str(response.status))
            run_id = admitted['run_id']
            deadline = time.monotonic() + 45
            while True:
                async with client.get(origin + '/v1/runs/' + run_id, headers={'Authorization': 'Bearer ' + key}) as response:
                    status = await response.json()
                    if response.status != 200:
                        raise RuntimeError('Owned status failed: ' + str(response.status))
                if status['status'] in ('completed', 'failed', 'cancelled', 'interrupted'):
                    break
                if time.monotonic() >= deadline:
                    raise RuntimeError('Bounded native run did not finish')
                await asyncio.sleep(.05)
            (root / 'final-status.json').write_text(json.dumps(status, indent=2), encoding='utf-8')
            (root / 'provider-evidence.json').write_text(json.dumps({'requests': requests, 'toolResults': tools_seen}, indent=2), encoding='utf-8')
            if status['status'] != 'completed' or not terminal_proof_seen(tools_seen):
                raise RuntimeError('Real agent/tool proof did not complete')
            checks.append('actual_native_HTTP_agent_tool_roundtrip')
            await asyncio.wait_for(title_started.wait(), timeout=10)
            async with client.get(origin + '/v1/runs/' + run_id, headers={'Authorization': 'Bearer ' + key}) as response:
                pending_title = await response.json()
            (root / 'title-pending-status.json').write_text(json.dumps(pending_title, indent=2), encoding='utf-8')
            pending_life = pending_title['writer_lifecycle']['enrollment']['lifetime']
            if (not pending_life['rootEnded'] or pending_life['managedWorkEnded']
                    or not any(item['kind'] == 'background' for item in pending_life['pendingWorkers'])):
                raise RuntimeError('Native reply completion lost its running title callback')
            checks.append('actual_native_title_callback_keeps_completed_reply_worker_held')
            title_release.set()
            deadline = time.monotonic() + 10
            while True:
                async with client.get(origin + '/v1/runs/' + run_id, headers={'Authorization': 'Bearer ' + key}) as response:
                    status = await response.json()
                if status['writer_lifecycle']['enrollment']['lifetime']['managedWorkEnded']:
                    break
                if time.monotonic() >= deadline:
                    raise RuntimeError('Native title callback did not settle after actual completion')
                await asyncio.sleep(.02)
            (root / 'final-status.json').write_text(json.dumps(status, indent=2), encoding='utf-8')
            (root / 'provider-evidence.json').write_text(json.dumps({'requests': requests, 'toolResults': tools_seen}, indent=2), encoding='utf-8')
            checks.append('actual_native_title_thread_exit_observed_before_local_settlement')
            observation = status['writer_lifecycle']
            life = observation['enrollment']['lifetime']
            effects=life['toolEffects'];pipeline=effects['pipeline']
            if (effects['observedCalls']<1 or pipeline['fullyObservedCalls']!=effects['observedCalls']
                    or pipeline['lateStages'] or pipeline['completionQualified'] or effects['effectsSettled']
                    or effects['unverifiedCalls']!=effects['observedCalls']):
                raise RuntimeError('Native tool pipeline stages were not completely observed without release')
            (root/'tool-pipeline-evidence.json').write_text(json.dumps(effects,indent=2),encoding='utf-8')
            checks.append('actual_native_tool_pipeline_stages_observed_without_clearance')
            if not life['managedWorkEnded'] or not life['processTree']['processTreeEnded']:
                raise RuntimeError('Actual native process lifetime did not settle')
            if observation['writerQuiescence'] or life['toolEffects']['unverifiedCalls'] < 1:
                raise RuntimeError('Unqualified effects manufactured writer release')
            checks.append('actual_native_tool_thread_and_Windows_job_observed_without_release')
            async with client.get(origin + '/v1/runs/' + run_id) as response:
                if response.status not in (401, 403):
                    raise RuntimeError('Unauthenticated native status was exposed')
            checks.append('actual_native_HTTP_authentication_enforced')
            file_mode = True
            import threading
            import tools.file_tools as native_file_tools
            file_write_started, file_write_release = threading.Event(), threading.Event()
            original_note_edited = native_file_tools._note_edited
            def held_note_edited(*args, **kwargs):
                file_write_started.set()
                if not file_write_release.wait(timeout=30):
                    raise RuntimeError('Fixture file bookkeeping release timed out')
                return original_note_edited(*args, **kwargs)
            with patch.object(native_file_tools, '_note_edited', side_effect=held_note_edited):
                try:
                    file_headers = {**headers, 'Idempotency-Key': 'mesh-native-file-proof'}
                    async with client.post(origin+'/v1/runs', headers=file_headers,
                            json={'input': 'Create the synthetic Mesh file proof, then finish.'}) as response:
                        file_admitted = await response.json()
                        if response.status not in (200,201,202):
                            raise RuntimeError('Native file run admission failed')
                    file_id = file_admitted['run_id']
                    deadline = time.monotonic()+45
                    while not file_write_started.is_set():
                        if time.monotonic()>deadline:
                            raise RuntimeError('Native file write did not reach post-write bookkeeping')
                        await asyncio.sleep(.02)
                    async with client.get(origin+'/v1/runs/'+file_id,
                            headers={'Authorization':'Bearer '+key}) as response:
                        file_held = await response.json()
                    held_life=file_held['writer_lifecycle']['enrollment']['lifetime']
                    held_path=root/'workspace'/'mesh-file-proof.md'
                    if (held_path.read_bytes()!=b'Mesh native file proof.\n' or held_life['rootEnded']
                            or held_life['managedWorkEnded'] or held_life['toolEffects']['activeCalls']!=1
                            or file_held['writer_lifecycle']['writerQuiescence']):
                        raise RuntimeError('File bytes incorrectly implied native handler completion')
                    file_write_release.set()
                    deadline = time.monotonic()+45
                    while True:
                        async with client.get(origin+'/v1/runs/'+file_id,
                                headers={'Authorization':'Bearer '+key}) as response:
                            file_status = await response.json()
                        file_life = file_status.get('writer_lifecycle',{}).get('enrollment',{}).get('lifetime',{})
                        if file_status['status'] in ('completed','failed','cancelled','interrupted') and file_life.get('managedWorkEnded'):
                            break
                        if time.monotonic()>deadline:
                            raise RuntimeError('Native file worker did not settle')
                        await asyncio.sleep(.05)
                    proof_path = root/'workspace'/'mesh-file-proof.md'
                    proof = proof_path.read_bytes() if proof_path.is_file() else b''
                    if file_status['status']!='completed' or proof!=b'Mesh native file proof.\n':
                        raise RuntimeError('Native file worker did not produce exact expected bytes')
                    if file_status['writer_lifecycle']['writerQuiescence'] or file_life['toolEffects']['effectsSettled']:
                        raise RuntimeError('File success incorrectly granted unqualified writer release')
                    (root/'file-worker-evidence.json').write_text(json.dumps({
                        'relativePath':'workspace/mesh-file-proof.md','sha256':hashlib.sha256(proof).hexdigest(),
                        'status':file_status,'heldAfterBytes':file_held,'exactContentVerified':True},indent=2),encoding='utf-8')
                    checks.append('actual_native_HTTP_agent_file_write_exact_bytes_without_release')
                    checks.append('actual_file_bytes_do_not_settle_held_native_bookkeeping')
                finally:
                    file_write_release.set()
            file_mode = False
            count = len(requests)
            worker_calls = sum('terminal' in item['tools'] for item in requests)
            creations, fence_count = len(agents_created), len(fences)
            old_owner = observation['ownerId']
            await adapter.disconnect(); adapter = None
            adapter, origin = make_adapter()
            if not await adapter.connect():
                raise RuntimeError('Isolated native restart failed')
            async with client.post(origin + '/v1/runs', headers=headers, json=body) as response:
                replay = await response.json()
                if response.status not in (200, 201, 202) or replay.get('run_id') != run_id:
                    raise RuntimeError('Durable native idempotency replay changed run identity')
            async with client.get(origin + '/v1/runs/' + run_id, headers={'Authorization': 'Bearer ' + key}) as response:
                restored = await response.json()
            evidence = {'providerRequestsBeforeRestart': count, 'providerRequestsAfterRestart': len(requests),
                        'oldOwner': old_owner, 'replay': replay, 'restored': restored, 'checksBeforeRestart': checks,
                        'pythonVersion': sys.version, 'pythonExecutable': sys.executable,
                        'providerRequests': requests, 'agentsBeforeRestart': creations, 'agentsAfterRestart': len(agents_created),
                        'fencesBeforeRestart': fence_count, 'fencesAfterRestart': len(fences)}
            (root / 'restart-evidence.json').write_text(json.dumps(evidence, indent=2), encoding='utf-8')
            if (len(requests) != count or len(agents_created) != creations or len(fences) != fence_count
                    or sum('terminal' in item['tools'] for item in requests) != worker_calls
                    or adapter._active_run_tasks or adapter._active_run_agents):
                raise RuntimeError('Durable replay resubmitted a worker')
            if restored.get('status') != 'completed':
                raise RuntimeError('Durable replay lost completed status')
            if restored['writer_lifecycle']['state'] != 'unknown':
                raise RuntimeError('Restart did not report unknown ownership')
            if restored['writer_lifecycle']['ownerId'] == old_owner or restored['writer_lifecycle']['writerQuiescence']:
                raise RuntimeError('Restart reused old owner or granted release')
            checks.append('actual_native_SQLite_restart_replay_without_new_worker_or_old_owner')
        # Native SQLite admission/claim and lookup, with a synthetic authority
        # stamp. This is NOT full FIFO/HTTP canonical execution qualification.
        import types
        from uuid import uuid4
        from hermes_state_runtime import begin_runtime_epoch, admit_session_input, claim_session_input
        from tools.mesh_writer_scope import canonical_admission_writer_scope, canonical_writer_foreground_scope
        db = adapter._ensure_session_db()
        sid, canonical_run = uuid4().hex, 'run_' + uuid4().hex
        db.create_session(sid, 'api_server')
        epoch = begin_runtime_epoch(db, instance_id='mesh-isolated-canonical-' + uuid4().hex)
        admitted = admit_session_input(db, epoch=epoch, principal_id='api', session_id=sid,
            request_id=canonical_run, payload={'text':'synthetic canonical claim',
                'api_turn_v1':{'run_owner_scope':'a'*64}})
        claimed = claim_session_input(db, epoch=epoch, session_id=sid, head=admitted['admission_id'])
        import threading
        stamp = {'authority_epoch':epoch,'execution_generation':claimed['generation'],'admission_id':claimed['admission_id']}
        authority = types.SimpleNamespace(db=db, profile_id='fixture', epoch=epoch,
            sessions={sid:types.SimpleNamespace(event_stream=types.SimpleNamespace(lock=threading.RLock(),execution=stamp))},
            executing={sid:claimed['generation']})
        canonical_adapter = types.SimpleNamespace(_mesh_writer_runs=WriterRunRegistry(factory),
            gateway_runner=types.SimpleNamespace(session_authority=authority))
        ref = types.SimpleNamespace(profile_id='fixture',session_id=sid)
        def canonical_body():
            with canonical_writer_foreground_scope():
                return 'synthetic worker returned'
        with canonical_admission_writer_scope(authority,ref,claimed,canonical_adapter):
            if await asyncio.to_thread(canonical_body) != 'synthetic worker returned':
                raise RuntimeError('Canonical bound worker did not return')
        duplicate_refused = False
        try:
            with canonical_admission_writer_scope(authority,ref,claimed,canonical_adapter):
                raise AssertionError('Duplicate canonical claim ran')
        except RuntimeError:
            duplicate_refused = True
        lifetime = canonical_adapter._mesh_writer_runs.snapshot(canonical_run)['lifetime']
        if not duplicate_refused or not lifetime['managedWorkEnded'] or lifetime['writerQuiescence']:
            raise RuntimeError('Canonical claim binding did not remain bounded')
        (root / 'canonical-claim-evidence.json').write_text(json.dumps({'durableClaimMatched':True,
            'duplicateRefused':duplicate_refused,'lifetime':lifetime,
            'scope':'native SQLite claim/lookup and actual thread; synthetic authority stamp; no full FIFO qualification'},indent=2),encoding='utf-8')
        checks.append('native_SQLite_canonical_claim_lookup_and_worker_binding')
        # Full native runner and authority pump. Only runtime/provider selection
        # is a fixture; no synthetic execution stamps or replaced queue methods.
        from gateway.config import GatewayConfig, Platform
        from gateway.run import GatewayRunner
        from gateway.run_runtime import initialize_gateway_runtime
        from gateway.runtime_ownership import process_ownership
        from gateway.platforms.api_server_authority_runs import run_admission
        home = root / 'fixture-home'
        process_ownership.reserve([home])
        try:
            runner = GatewayRunner(GatewayConfig(multiplex_profiles=False))
            runner._resolve_session_agent_runtime = lambda **kwargs: ('mesh-runtime-fixture', {
                'base_url':endpoint,'api_key':'synthetic-local-provider','provider':'custom','api_mode':'chat_completions'})
            runner._resolve_turn_toolsets = lambda *args, **kwargs: (['terminal'], [])
            await initialize_gateway_runtime(runner)
            runner.adapters[Platform.API_SERVER] = adapter
            adapter.gateway_runner = runner
            canonical_mode = True
            sid = uuid4().hex
            async with ClientSession() as client:
                headers = {'Authorization':'Bearer '+key,'Idempotency-Key':'mesh-canonical-one'}
                body = {'input':'Synthetic canonical queue proof one.','session_id':sid}
                async with client.post(origin+'/v1/runs',headers=headers,json=body) as response:
                    first = await response.json()
                    if response.status not in (200,201,202):
                        raise RuntimeError('Canonical first admission failed: '+str(response.status))
                first_id = first['run_id']
                await asyncio.wait_for(canonical_started.wait(),timeout=20)
                async with client.post(origin+'/v1/runs',headers={**headers,'Idempotency-Key':'mesh-canonical-two'},
                        json={**body,'input':'Synthetic canonical queue proof two.'}) as response:
                    second = await response.json()
                    if response.status not in (200,201,202):
                        raise RuntimeError('Canonical second admission failed: '+str(response.status))
                second_id = second['run_id']
                queued = run_admission(adapter,second_id)
                if queued is None or queued[1]['status'] != 'queued' or adapter._mesh_writer_runs.snapshot(second_id) is not None:
                    raise RuntimeError('Canonical successor did not wait unstarted in FIFO')
                observer = adapter._active_run_tasks[first_id]
                observer.cancel()
                try:
                    await observer
                except asyncio.CancelledError:
                    pass
                held = adapter._mesh_writer_runs.snapshot(first_id)
                if held is None or held['lifetime']['rootEnded'] or held['lifetime']['managedWorkEnded']:
                    raise RuntimeError('Cancelled native observer lost its continuing canonical worker')
                canonical_release.set()
                deadline = time.monotonic()+30
                while True:
                    rows = [run_admission(adapter,ident)[1] for ident in [first_id,second_id]]
                    states = [adapter._mesh_writer_runs.snapshot(ident) for ident in [first_id,second_id]]
                    if all(row['status']=='terminal' for row in rows) and all(state and state['lifetime']['managedWorkEnded'] for state in states):
                        break
                    if time.monotonic()>deadline:
                        raise RuntimeError('Canonical FIFO did not settle both actual workers')
                    await asyncio.sleep(.02)
                if rows[0]['generation'] >= rows[1]['generation'] or any(state['writerQuiescence'] for state in states):
                    raise RuntimeError('Canonical generation ordering/release changed')
                from gateway.session_api_turn import _settled_api_result
                outputs = []
                for ident,row in zip([first_id,second_id],rows):
                    result,_usage = _settled_api_result(run_admission(adapter,ident)[0],row['admission_id'])
                    if result.get('failed') or result.get('interrupted') or result.get('final_response') != 'mesh fixture completed':
                        raise RuntimeError('Canonical terminal row did not contain the successful result')
                    outputs.append(result['final_response'])
                fence_count, request_count = len(fences),len(requests)
                async with client.post(origin+'/v1/runs',headers=headers,json=body) as response:
                    replay = await response.json()
                if replay.get('run_id') != first_id or len(fences)!=fence_count or len(requests)!=request_count:
                    raise RuntimeError('Canonical exact replay created new work')
                (root/'canonical-fifo-evidence.json').write_text(json.dumps({
                    'firstRunId':first_id,'secondRunId':second_id,'successorWaitedQueued':True,
                    'heldAfterObserverCancellation':held,'generations':[row['generation'] for row in rows],
                    'terminalStatuses':[row['status'] for row in rows],'finalWorkers':states,'verifiedOutputs':outputs,
                    'replayCreatedNoWork':True,'realRunnerAndAuthority':True},indent=2),encoding='utf-8')
                checks.append('actual_canonical_HTTP_FIFO_observer_cancellation_and_exact_replay')
            await qualify_canonical_retirement(root,adapter,origin,key,runner,endpoint,factory,fences)
            checks.append('actual_canonical_retirement_timeout_drain_and_successor_queue_recovery')
            await qualify_abrupt_owner_loss(root)
            checks.append('actual_abrupt_owner_process_loss_blocks_replay_and_preserves_queue')
        finally:
            canonical_release.set()
            process_ownership.close()
        if os.environ.get('HERMES_SAFE_MODE')=='1':
            for tool_effects in [effects,file_life['toolEffects']]:
                pipeline=tool_effects['pipeline']
                if (pipeline['plainNativeCalls']!=tool_effects['observedCalls'] or pipeline['blockerCalls']
                        or pipeline['otherOrMissingCalls'] or pipeline['lateStages']):
                    raise RuntimeError('Native safe-mode profile retained an unqualified pipeline')
            checks.append('native_safe_mode_plain_terminal_and_file_pipeline')
        return {'qualification': 'PASS', 'checks': checks, 'providerRequests': len(requests),
                'nonToolProviderRequests': sum('terminal' not in item['tools'] for item in requests),
                'agentsCreated': len(agents_created), 'pythonVersion': sys.version.split()[0],
                'nativeSafeMode': os.environ.get('HERMES_SAFE_MODE')=='1',
                'liveInstallation': False, 'wholeWorkerReleaseQualified': False}
    finally:
        title_release.set()
        canonical_release.set()
        if adapter is not None:
            await adapter.disconnect()
        await provider_runner.cleanup()
        for fence in fences:
            fence.terminate(); fence.close()


if __name__ == '__main__':
    if len(sys.argv) == 3 and sys.argv[1] == '--verify':
        print(json.dumps(verify_evidence(Path(sys.argv[2]).resolve())))
    elif len(sys.argv) == 3 and sys.argv[1] in ('--crash-owner','--recover-owner'):
        import asyncio
        asyncio.run(abrupt_owner_process(Path(sys.argv[2]).resolve(),sys.argv[1]=='--recover-owner'))
    elif len(sys.argv) == 3 and sys.argv[1] == '--child':
        import asyncio
        root = Path(sys.argv[2]).resolve()
        try:
            result = asyncio.run(child(root))
        except BaseException as error:
            (root / 'runtime-qualification.json').write_text(json.dumps({'qualification': 'FAIL', 'errorClass': type(error).__name__,
                'liveInstallation': False, 'wholeWorkerReleaseQualified': False}, indent=2), encoding='utf-8')
            raise
        (root / 'runtime-qualification.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
        print(json.dumps(result))
    else:
        if len(sys.argv) not in (3,4) or (len(sys.argv)==4 and sys.argv[3]!='--safe-mode'):
            raise SystemExit('Usage: native_root python_executable [--safe-mode]')
        native, executable = sys.argv[1:3]
        root = prepare(native)
        environment = {name: value for name, value in os.environ.items() if name.upper() in
                       {'SYSTEMROOT', 'WINDIR', 'COMSPEC', 'PATH', 'PATHEXT', 'PROGRAMFILES', 'PROGRAMFILES(X86)'}}
        environment.update(HERMES_HOME=str(root / 'fixture-home'), HOME=str(root / 'fixture-home'),
            USERPROFILE=str(root / 'fixture-home'), APPDATA=str(root / 'appdata'), LOCALAPPDATA=str(root / 'localappdata'),
            TEMP=str(root / 'temp'), TMP=str(root / 'temp'), PYTHONIOENCODING='utf-8',
            TERMINAL_ENV='local', TERMINAL_CWD=str(root / 'workspace'))
        if len(sys.argv)==4:
            environment['HERMES_SAFE_MODE']='1'  # Supported native no-plugin discovery mode.
        # Keep profile/data roots isolated while resolving the installed runtime's
        # existing libraries explicitly. Never inherit provider keys or real HOME.
        libraries = subprocess.check_output([executable, '-c', 'import site;print(site.getusersitepackages())'], text=True).strip()
        if Path(libraries).is_dir():
            environment['PYTHONPATH'] = libraries
        # The live 3.14 library set lacks this pure-Python dependency. Reuse its
        # existing source in this fixture only; never mix 3.11 compiled extensions.
        snowball = Path(native) / 'venv/Lib/site-packages/snowballstemmer'
        if snowball.is_dir():
            for item in snowball.rglob('*'):
                if item.is_symlink() or item.suffix.lower() in {'.pyd', '.so', '.dll', '.exe'}:
                    raise RuntimeError('Dependency fixture must contain pure Python only')
            dependency_root = root / 'test-dependencies'
            shutil.copytree(snowball, dependency_root / 'snowballstemmer', ignore=shutil.ignore_patterns('__pycache__', '*.pyc', '*.pyo'))
            environment['PYTHONPATH'] = str(dependency_root) + os.pathsep + environment.get('PYTHONPATH', '')
            (root / 'dependency-fixture.json').write_text(json.dumps({'scope': 'isolated pure-Python snowballstemmer source',
                'files': {str(path.relative_to(dependency_root)): hashlib.sha256(path.read_bytes()).hexdigest()
                          for path in dependency_root.rglob('*') if path.is_file()}}, indent=2), encoding='utf-8')
        print(json.dumps({'directory': str(root), 'state': 'running_isolated_native_runtime'}), flush=True)
        with (root / 'runtime.log').open('wb') as log:
            try:
                result = subprocess.run([executable, str(Path(__file__).resolve()), '--child', str(root)],
                    env=environment, cwd=root / 'source', stdout=log, stderr=subprocess.STDOUT,
                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0), timeout=360)
            except subprocess.TimeoutExpired:
                (root / 'runtime-qualification.json').write_text(json.dumps({'qualification': 'FAIL',
                    'errorClass': 'TimeoutExpired', 'liveInstallation': False, 'wholeWorkerReleaseQualified': False}, indent=2), encoding='utf-8')
                raise
        print(json.dumps({'directory': str(root), 'exitCode': result.returncode}), flush=True)
        if result.returncode == 0:
            print(json.dumps(verify_evidence(root)), flush=True)
        sys.exit(result.returncode)
