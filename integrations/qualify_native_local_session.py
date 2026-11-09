"""Disposable real local-session/RPC/process qualification; never enroll live access."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid


LOCAL_NATIVE_HEAD='2bd378ed1b8d6bf2192cb26e0a55ff3091e6bd19'
LOCAL_BASELINES={
    'gateway/session_controls.py':'3e6797de16ee375f21221a5da1c589756c6d0c31f21cd342a16a020eba891b71',
    'tui_gateway/contracts/canonical.py':'ecccf8d09673b5d5401a3ecd30adb70cb7a9be1ee7d221dec23cd34a3feaa853',
    'tools/file_tools_read_tracking.py':'fb839642d9e8de715ef7beb85a9d971e07fc16ae4a5b07fd05cc3da9238644fb',
    'tools/file_tools.py':'925ebccc2a70b5a1b55541242cb19ed6614a18e82df1d6bc29474dc22c4f0dee'}


def prepare_local(native):
    import difflib,tarfile
    from integrations.prepare_hermes_writer_scope import read_tracking_candidate
    from integrations.prepare_native_local_lookup import local_receipt_candidate
    from integrations.prepare_native_assignment_process import assignment_process_candidate
    native=Path(native).resolve()
    if subprocess.check_output(['git','-C',str(native),'rev-parse','HEAD'],text=True).strip()!=LOCAL_NATIVE_HEAD:
        raise RuntimeError('Native local-session source revision changed; review before qualification')
    root=Path(__file__).resolve().parents[1]/'data'/('hermes-local-session-'+str(uuid.uuid4()))
    source=root/'source';source.mkdir(parents=True);archive=root/'source.tar'
    subprocess.run(['git','-C',str(native),'archive','--format=tar','--output='+str(archive),LOCAL_NATIVE_HEAD],check=True)
    with tarfile.open(archive) as tar:
        members=[]
        for member in tar.getmembers():
            if member.issym() or member.islnk():raise RuntimeError('Native archive link needs review: '+member.name)
            if member.name=='.github/workflows' or member.name.startswith('.github/workflows/'):continue
            members.append(member)
        tar.extractall(source,members=members,filter='data')
    originals,modules=local_receipt_candidate(source,baselines=LOCAL_BASELINES)
    assignment_originals,assignment_modules=assignment_process_candidate(source)
    originals.update(assignment_originals);modules.update(assignment_modules)
    read_originals,read_modules=read_tracking_candidate(source)
    originals.update(read_originals);modules.update(read_modules)
    file_path='tools/file_tools.py';raw=(source/file_path).read_bytes()
    if hashlib.sha256(raw).hexdigest()!=LOCAL_BASELINES[file_path]:raise RuntimeError('Current native file source changed')
    original=raw.decode('utf-8').replace('\r\n','\n')
    before='    stable = version is not None and version[:-1] == version_before == _file_metadata(resolved_str)\n'
    if original.count(before)!=1:raise RuntimeError('Current native full-read stability shape changed')
    modules[file_path]=original.replace(before,
        '    stable = (version is not None and version[:-1] == version_before == _file_metadata(resolved_str)\n'
        '              and version == _file_version(resolved_str))\n')
    originals[file_path]=original
    patch=''
    for name,text in modules.items():
        patch+=''.join(difflib.unified_diff(originals[name].splitlines(True),text.splitlines(True),fromfile='a/'+name if originals[name] else '/dev/null',tofile='b/'+name))
        (source/name).write_bytes(text.encode('utf-8'))
    (root/'candidate.patch').write_bytes(patch.encode('utf-8'))
    for name in ['fixture-home','appdata','localappdata','temp','workspace']:(root/name).mkdir()
    (root/'manifest.json').write_text(json.dumps({'state':'isolated_local_session_candidate','nativeHead':LOCAL_NATIVE_HEAD,
        'source':str(source),'home':str(root/'fixture-home'),'files':{n:hashlib.sha256(t.encode()).hexdigest() for n,t in modules.items()},
        'baselines':LOCAL_BASELINES,'liveInstallation':False,'wholeWorkerReleaseQualified':False},indent=2))
    return root


def verify(root):
    report = json.loads((root/'local-session-evidence.json').read_text())
    manifest = json.loads((root/'manifest.json').read_text())
    if report['qualification'] != 'PASS' or report['wholeWorkerReleaseQualified'] is not True:
        raise RuntimeError('Local session qualification did not pass its stated boundary')
    if (root/'workspace'/'local-session-proof.md').read_bytes() != b'Mesh local session proof.\n':
        raise RuntimeError('Native local file effect is missing')
    for name, digest in manifest['files'].items():
        if hashlib.sha256((Path(manifest['source'])/name).read_bytes()).hexdigest() != digest:
            raise RuntimeError('Candidate changed since native session run')
    if (report['sessionId'] != report['replayedSessionId']
            or report['admissionId'] != report['replayedAdmissionId']
            or report['finalResponse'] != 'mesh local fixture completed'
            or not report['distinctVerifiedWorker'] or not report['workerHandleExited']
            or not report['replayCreatedNoProviderWork'] or report.get('ownerSettled') is not True
            or report.get('unauthenticatedRefused') is not True or report.get('creationConflictRefused') is not True
            or report.get('submissionConflictRefused') is not True
            or report.get('creationRefusalReason')!='invalid_params'
            or report.get('submissionRefusalReason')!='admission_conflict'
            or report.get('workerPid')==report.get('ownerPid')
            or not all(report.get(key) is True for key in ('requestLookupVerified','missingRequestDoesNotCreate','crossSessionLookupRefused'))):
        raise RuntimeError('Native local receipt/replay/process evidence is incomplete')
    binding=json.loads((root/'mesh-local-binding-evidence.json').read_text())
    if (report.get('meshBindingVerified') is not True or report.get('meshBindingDroppedReply') is not True
            or binding['qualification']!='PASS' or binding['rpcCounts'].get('prompt.submit')!=1
            or binding['rpcCounts'].get('session.create')!=1 or binding['rpcCounts'].get('prompt.lookup',0)<1
            or not binding['restartedBeforeReadback'] or binding['workspaceStillHeld'] is not (not manifest.get('realNimsReview',False)) or binding['writerQuiescence'] is not True):
        raise RuntimeError('Mesh task/native dispatch binding evidence is incomplete')
    import sqlite3
    with sqlite3.connect('file:'+(root/'mesh-local-binding.sqlite').as_posix()+'?mode=ro',uri=True) as saved:
        saved.row_factory=sqlite3.Row
        saved.execute('PRAGMA query_only=ON')
        row=saved.execute('SELECT * FROM workroom_local_sessions WHERE taskId=? AND sendId=?',
            (binding['taskId'],binding['sendId'])).fetchone()
        replies=saved.execute('SELECT * FROM workroom_replies WHERE taskId=? AND sendId=?',
            (binding['taskId'],binding['sendId'])).fetchall()
        team=saved.execute('SELECT * FROM workroom_automation WHERE taskId=?',(binding['taskId'],)).fetchone()
        if (binding.get('terminalResultImported') is not True or binding.get('automaticTeamDispatch') is not True
                or row is None or row['resultHash']!=binding['resultHash'] or row['teamBound']!=1
                or row['sessionId']!=binding['sessionId'] or row['admissionId']!=binding['admissionId']
                or len(replies)!=1 or replies[0]['messageId']!=row['resultMessageId']
                or replies[0]['agentId']!='echo' or team['workerSendId']!=binding['sendId']
                or team['phase']!='reviewer' or team['state']!=('needs_review' if manifest.get('realNimsReview') else 'active')
                or not row['retiredAt'] or row['retirementHash']!=binding['retirementHash']
                or binding.get('reviewSentToNims') is not True or binding.get('reviewTransportSynthetic') is not (not manifest.get('realNimsReview',False))):
            raise RuntimeError('Native result/card provenance or paused review boundary is incomplete')
        if manifest.get('realNimsReview'):
            review=json.loads((root/'nims-review-evidence.json').read_text())
            run=saved.execute('SELECT * FROM nims_runs WHERE sendId=?',(team['reviewerSendId'],)).fetchone()
            review_reply=saved.execute('SELECT * FROM workroom_replies WHERE taskId=? AND sendId=?',(binding['taskId'],team['reviewerSendId'])).fetchall()
            if (run is None or run['state']!='completed' or run['threadId']!=review['threadId'] or run['turnId']!=review['turnId']
                    or review['sendId']!=team['reviewerSendId'] or review['taskId']!=binding['taskId']
                    or review['status']!='completed' or review['before']!=review['after'] or review['realNimsTransport'] is not True
                    or len(review_reply)!=1 or review_reply[0]['agentId']!='nims' or '```workroom-review' not in review_reply[0]['text']
                    or binding.get('realNimsReviewCompleted') is not True
                    or not any(item.get('sourceReadInOutput') is True and item.get('exitCode')==0 for item in review.get('commands',[]))
                    or any('mcp' in kind.lower() or kind=='fileChange' for kind in review['itemTypes'])):
                raise RuntimeError('Actual Nims review identity, saved report or unchanged files not established')
        text=replies[0]['text']
        if not text.startswith('```workroom-update\n') or not text.endswith('\n```'):
            raise RuntimeError('Native result is not the expected structured update')
        update=json.loads(text[len('```workroom-update\n'):-len('\n```')])
        if update['taskId']!=binding['taskId'] or update['sendId']!=binding['sendId']:
            raise RuntimeError('Native structured update belongs to another task or dispatch')
    build=json.loads((root/'workspace'/'local-build-check.json').read_text())
    tool=json.loads(json.loads((root/'build-terminal-receipt.json').read_text())['raw'])
    if (binding.get('buildCheckVerified') is not True or build.get('syntaxExitCode')!=0
            or not isinstance(build.get('invalidSyntaxExitCode'),int) or build['invalidSyntaxExitCode']==0
            or tool.get('exit_code')!=0 or 'tests 3' not in tool.get('output','')
            or (root/'workspace'/'local-build-proof.mjs').read_bytes()!=b'export const localProof = true;\n'):
        raise RuntimeError('Real native terminal build-check evidence is incomplete')
    assignment=json.loads((root/'assignment-process-evidence.json').read_text())
    held,ended,other=(assignment[key] for key in ('heldAfterRootExit','naturallyEnded','differentAssignment'))
    for snapshot in (held,ended):
        if (snapshot['admissionId']!=binding['admissionId'] or snapshot['sessionId']!=binding['sessionId']
                or snapshot['profileId']!=binding['nativeProfileId']
                or snapshot['executionGeneration']!=binding['nativeGeneration']
                or not snapshot['assignmentLaunchSealed'] or not snapshot['sealed']
                or snapshot['terminationRequested'] or snapshot['writerQuiescence']):
            raise RuntimeError('Assignment process identity or observation boundary changed')
    if (held['processTreeEnded'] or not held['allRootsEnded'] or held['activeProcesses']<1
            or not ended['processTreeEnded'] or ended['activeProcesses']!=0
            or not other['processTreeEnded'] or other['admissionId']==held['admissionId']
            or assignment['lateRootRefused'] is not True or assignment['wholeWorkerReleaseQualified']):
        raise RuntimeError('Assignment Job did not retain its late child independently')
    persisted=json.loads(row['processObservation'] or 'null')
    authenticated_held,authenticated_ended=(assignment[key] for key in ('authenticatedHeld','authenticatedEnded'))
    if (binding.get('processReadbackPersisted') is not True or persisted!=authenticated_ended
            or authenticated_held['process_tree_ended'] is not False or authenticated_held['active_processes']<1
            or authenticated_ended['process_tree_ended'] is not True
            or authenticated_ended['admission_id']!=binding['admissionId']
            or authenticated_ended['session_id']!=binding['sessionId']
            or authenticated_ended['profile_id']!=binding['nativeProfileId']
            or authenticated_ended['execution_generation']!=binding['nativeGeneration']
            or authenticated_ended['writer_quiescence'] or authenticated_ended['termination_requested']
            or any(key in authenticated_ended for key in ('principalId','principal_id'))):
        raise RuntimeError('Authenticated assignment observation did not persist on the exact Mesh binding')
    if (binding.get('authorityDrainObserved') is not True or binding.get('executionClosedObserved') is not True
            or assignment.get('writeCommitted') is not True or assignment.get('closedMutationRefused') is not True
            or assignment['blockedWrite']['authority_writes_drained'] is not False
            or assignment['blockedWrite']['process_tree_ended'] is not True
            or assignment['blockedLookupSeconds']>=2
            or not all(authenticated_ended[key] is True for key in
                ('execution_closed','authority_writes_drained','worker_resources_idle'))
            or authenticated_ended['authority_epoch']!=binding['nativeEpoch']):
        raise RuntimeError('Passive retirement/write barrier or terminal mutation refusal was not established')
    contract=json.loads(row['profileContract'] or 'null')
    if (row['nativeOutcome']!='completed' or not contract or contract['closed'] is not True
            or not contract['safe_mode'] or not contract['ignore_user_config'] or contract['follow_profile']
            or contract['max_turns']!=50 or sorted(contract['toolsets'])!=['file','terminal']):
        raise RuntimeError('Qualified frozen profile or native outcome is absent')
    with sqlite3.connect('file:'+(root/'mesh-local-binding.sqlite').as_posix()+'?mode=ro',uri=True) as final_db:
        reviews=final_db.execute("SELECT id,agentId,phase,state,payload FROM workroom_sends WHERE taskId=? AND phase='review'",(binding['taskId'],)).fetchall()
        if (len(reviews)!=1 or reviews[0][0]!=team['reviewerSendId'] or reviews[0][1:4]!=('nims','review','accepted')
                or 'Read-only tools only' not in reviews[0][4]):
            raise RuntimeError('The original saved Nims review was not sent exactly once')
    retirement=json.loads(row['retirementEvidence'] or 'null')
    if not retirement or retirement[:5]!=[row['admissionId'],row['nativeEpoch'],row['nativeGeneration'],row['resultHash'],row['profileHash']]:
        raise RuntimeError('Original consumed retirement evidence is missing or rebound')
    digest=hashlib.sha256(json.dumps(retirement,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()
    if digest!=row['retirementHash']:
        raise RuntimeError('Consumed native retirement proof hash does not match saved evidence')
    processes=json.loads((root/'local-session-fixture-processes.json').read_text())
    if not processes['processTreeEnded'] or processes['activeProcesses'] or processes['terminationRequested']:
        raise RuntimeError('Disposable owner/process tree did not end naturally')
    result = {'qualification':'PASS','checks':['pinned_candidate_hashes','actual_file_bytes',
        'native_session_and_submission_identity_replay','verified_separate_worker_and_observed_exit',
        'private_auth_and_conflict_refusals','owner_settled_and_fixture_tree_ended_naturally',
        'exact_read_only_submission_lookup_without_cross_session_access_or_dispatch',
        'actual_mesh_saved_dispatch_restarts_and_reconciles_lost_native_reply_without_resubmit',
        'native_result_applies_only_after_qualified_retirement',
        'native_terminal_node_tests_pass_with_valid_and_invalid_syntax_and_built_export',
        'exact_assignment_job_remains_held_after_root_exit_until_late_child_ends',
        'authenticated_process_observation_persists_before_explicit_retirement_consumption',
        'passive_retirement_stays_held_during_write_and_terminal_execution_refuses_new_mutation',
        'frozen_profile_and_native_outcome_feed_one_saved_nims_read_only_review'],
        'wholeWorkerReleaseQualified':True,'liveInstallation':False}
    if manifest.get('realNimsReview'):
        result['checks'].append('real_nims_review_saved_under_original_dispatch_without_source_changes')
        result['realNimsReviewCompleted']=True
    if (root/'codex-preflight-evidence.json').is_file():
        codex=json.loads((root/'codex-preflight-evidence.json').read_text())
        expected_cases={'native-signin','explicit-key','endpoint-override'}|({'profile-key-ignored'} if codex.get('schema')=='mesh-codex-preflight/v2' else set())
        if codex.get('qualification')!='PASS' or codex.get('providerRequestsAdded')!=0 or codex.get('promptsSubmitted')!=0 or set(codex.get('cases',{}))!=expected_cases:
            raise RuntimeError('Codex preflight created work or has incomplete cases')
        ids=set()
        for case,snapshot in codex['cases'].items():
            c=snapshot.get('profile_contract') or {};ids.add(snapshot.get('session_id'))
            if (snapshot.get('found') is not False or snapshot.get('submission_id')!='codex-never-submitted'
                    or c.get('provider')!='openai-codex' or c.get('model')!='synthetic-codex-no-generation'
                    or c.get('closed') is not True or c.get('follow_profile') is not False
                    or c.get('safe_mode') is not True or c.get('ignore_user_config') is not True
                    or c.get('source')!='tool' or c.get('max_turns')!=50 or c.get('toolsets')!=['file']
                    or c.get('api_key_configured') is not (case=='explicit-key')
                    or c.get('base_url')!=('http://127.0.0.1:9/v1' if case=='endpoint-override' else None)):
                raise RuntimeError('Codex preflight provider/key/endpoint evidence mismatch')
        if len(ids)!=len(expected_cases) or None in ids or any(marker in json.dumps(codex) for marker in ('MESH_POISON_NOT_EXPORT','MESH_INHERITED_POISON')):
            raise RuntimeError('Codex preflight session identity or key privacy failed')
        result['checks'].append('native_codex_policy_preflight_without_key_export_or_provider_work')
        if 'profile-key-ignored' in expected_cases:result['checks'].append('native_codex_safe_policy_excludes_owner_config_keys_before_provider_work')
        result['codexGenerationQualified']=False
    (root/'local-session-verified.json').write_text(json.dumps(result,indent=2))
    return result


async def child(root):
    import asyncio
    import time
    from aiohttp import web, ClientSession, WSServerHandshakeError
    source=root/'source';sys.path.insert(0,str(source));os.chdir(source)
    from hermes_constants import get_hermes_home
    from gateway.config import GatewayConfig
    from gateway.run import GatewayRunner
    from gateway.run_runtime import (initialize_gateway_runtime,start_gateway_runtime_api,
        publish_gateway_runtime_ready,drain_gateway_runtime,settle_gateway_runtime,_authority_tasks)
    from gateway.run_bootstrap import _start_gateway_start_control_socket
    from gateway.runtime_ownership import process_ownership
    from hermes_cli.gateway_runtime import discover_gateway_endpoint
    from hermes_cli.gateway_client import _session_ticket,gateway_ws_target
    os.environ['MESH_LOCAL_PROCESS_SCOPE']='1'
    home=root/'fixture-home'
    if Path(get_hermes_home()).resolve()!=home.resolve():raise RuntimeError('Non-isolated native home')
    proof=root/'workspace'/'local-session-proof.md';proof.write_bytes(b'Before local session edit.\n')
    import shutil
    node_executable=shutil.which('node')
    if not node_executable:raise RuntimeError('Existing Node is required for build qualification')
    code=root/'workspace'/'local-build-proof.mjs';check=root/'workspace'/'verify-local-build.mjs'
    check.write_text('\n'.join([
        "import {spawnSync} from 'node:child_process';",
        "import {writeFileSync} from 'node:fs';",
        "import {pathToFileURL} from 'node:url';",
        "import {test} from 'node:test';",
        "import assert from 'node:assert/strict';",
        "const code="+json.dumps(str(code))+";",
        "const valid=spawnSync(process.execPath,['--check',code],{encoding:'utf8'});",
        "const invalid=spawnSync(process.execPath,['--input-type=module','--check'],{input:'export const =;',encoding:'utf8'});",
        "const evidence={syntaxExitCode:valid.status,invalidSyntaxExitCode:invalid.status,checkerPid:process.pid,checkerParentPid:process.ppid};",
        "writeFileSync("+json.dumps(str(root/'workspace'/'local-build-check.json'))+",JSON.stringify(evidence));",
        "console.log(JSON.stringify(evidence));",
        "test('valid fixture syntax passes',()=>assert.equal(valid.status,0));",
        "test('invalid syntax is rejected',()=>{assert.notEqual(invalid.status,null);assert.notEqual(invalid.status,0);});",
        "test('built module exports the expected value',async()=>assert.equal((await import(pathToFileURL(code))).localProof,true));",
    ])+'\n')
    child_ready=root/'workspace'/'assignment-child-ready.json'
    child_release=root/'workspace'/'assignment-child-release'
    child_code=("const fs=require('node:fs');fs.writeFileSync("+json.dumps(str(child_ready))+
        ",JSON.stringify({pid:process.pid,parent:process.ppid}));const timer=setInterval(()=>{if(fs.existsSync("+
        json.dumps(str(child_release))+")){clearInterval(timer);process.exit(0);}},25);")
    with check.open('a') as checker:
        checker.write("\nimport {spawn} from 'node:child_process';\nspawn(process.execPath,['-e',"+
            json.dumps(child_code)+"],{detached:true,stdio:'ignore',windowsHide:true}).unref();\n")
    build_command=subprocess.list2cmdline([node_executable,'--test',str(check)])
    import threading
    write_entered=threading.Event();write_release=threading.Event();pending_write=None
    requests=[];worker_started=asyncio.Event();worker_release=asyncio.Event()
    async def provider(request):
        body=await request.json();requests.append({'tools':[t.get('function',{}).get('name') for t in body.get('tools',[])],
            'roles':[m.get('role') for m in body.get('messages',[])]})
        tools=requests[-1]['tools'];is_worker='write_file' in tools
        if is_worker and not worker_started.is_set():
            worker_started.set();await asyncio.wait_for(worker_release.wait(),30)
        previous=[m for m in body.get('messages',[]) if m.get('role')=='tool']
        build_worker='terminal' in tools
        call=is_worker and len(previous)<(4 if build_worker else 2)
        name='read_file' if not previous else 'write_file';args={'path':str(proof)}
        if name=='write_file':args['content']='Mesh local session proof.\n'
        if build_worker and len(previous)==2:
            name='write_file';args={'path':str(code),'content':'export const localProof = true;\n'}
        if build_worker and len(previous)==3:
            name='terminal';args={'command':build_command,'workdir':str(root/'workspace'),'timeout':30}
        if build_worker and len(previous)>=4:
            check_result=previous[-1].get('content','')
            (root/'build-terminal-receipt.json').write_text(json.dumps({'raw':check_result}))
            parsed=json.loads(check_result)
            if parsed.get('exit_code')!=0:raise RuntimeError('Native terminal build tests did not exit successfully')
            if 'syntaxExitCode' not in check_result or not (root/'workspace'/'local-build-check.json').exists():
                raise RuntimeError('Native terminal did not run the named Node build check')
        final='mesh local fixture completed'
        if is_worker:
            import re
            frozen='\n'.join(m.get('content','') for m in body.get('messages',[]) if m.get('role')=='user' and isinstance(m.get('content'),str))
            task_match=re.search(r'Workroom task ([a-f0-9-]+):',frozen)
            send_match=re.search(r'Workroom message ([a-f0-9-]+)',frozen)
            if task_match and send_match:
                update={'schema':'workroom-update/v1','taskId':task_match.group(1),'sendId':send_match.group(1),
                    'goal':'Build and verify the declared synthetic proof artifacts against exact acceptance criteria','checklist':[{'id':'proof','text':'Edit and verify the proof','status':'done'}],
                    'result':'Updated local-session-proof.md','evidence':'Native terminal ran node --test: valid syntax, invalid syntax rejection and built export all passed; external qualifier checks bytes and native exit status.'}
                final='```workroom-update\n'+json.dumps(update)+'\n```'
        message=({'role':'assistant','content':None,'tool_calls':[{'id':'local-proof-'+str(len(previous)),
            'type':'function','function':{'name':name,'arguments':json.dumps(args)}}]} if call else
            {'role':'assistant','content':final if is_worker else '{"title":"Local worker proof"}'})
        finish='tool_calls' if call else 'stop'
        if body.get('stream'):
            delta=dict(message);delta.pop('role',None)
            if call:delta['tool_calls'][0]['index']=0
            chunks=[{'id':'fixture','object':'chat.completion.chunk','created':1,'model':'mesh-local-fixture',
                'choices':[{'index':0,'delta':delta,'finish_reason':None}]},
                {'id':'fixture','object':'chat.completion.chunk','created':1,'model':'mesh-local-fixture',
                'choices':[{'index':0,'delta':{},'finish_reason':finish}]}]
            return web.Response(text=''.join('data: '+json.dumps(c)+'\n\n' for c in chunks)+'data: [DONE]\n\n',content_type='text/event-stream')
        return web.json_response({'id':'fixture','object':'chat.completion','created':1,'model':'mesh-local-fixture',
            'choices':[{'index':0,'message':message,'finish_reason':finish}],
            'usage':{'prompt_tokens':1,'completion_tokens':1,'total_tokens':2}})
    app=web.Application();app.router.add_post('/v1/chat/completions',provider)
    service=web.AppRunner(app);await service.setup();site=web.TCPSite(service,'127.0.0.1',0);await site.start()
    endpoint='http://127.0.0.1:'+str(site._server.sockets[0].getsockname()[1])+'/v1'
    runner=None;control=None;report=None;stage='initialization'
    process_ownership.reserve([home])
    try:
        runner=GatewayRunner(GatewayConfig(multiplex_profiles=False))
        runner._running=True;runner._draining=False
        await initialize_gateway_runtime(runner)
        stage='control_listener';control=await _start_gateway_start_control_socket(runner)
        if control is None:raise RuntimeError('Disposable owner control listener unavailable')
        await start_gateway_runtime_api(runner);publish_gateway_runtime_ready(runner)
        stage='discovery';discovery=await asyncio.to_thread(discover_gateway_endpoint,home,timeout=5)
        if discovery.state!='ready':raise RuntimeError('Disposable owner discovery state: '+discovery.state)
        ticket=await asyncio.to_thread(_session_ticket,home,discovery.endpoint,purpose='interactive')
        url,protocols=gateway_ws_target(discovery.endpoint,ticket)
        if not url.startswith('ws://127.0.0.1:'):raise RuntimeError('Non-loopback fixture target')
        async with ClientSession() as client:
            try:
                unexpected=await client.ws_connect(url)
            except WSServerHandshakeError as error:
                if error.status not in (401,403):raise RuntimeError('Unexpected unauthenticated RPC status')
            else:
                await unexpected.close();raise RuntimeError('Native private RPC accepted missing ticket')
            async with client.ws_connect(url,protocols=protocols) as ws:
                serial=0
                async def rpc(method,params,expect_error=False):
                    nonlocal serial
                    serial+=1;ident=serial
                    await ws.send_json({'jsonrpc':'2.0','id':ident,'method':method,'params':params})
                    while True:
                        response=await ws.receive_json(timeout=45)
                        if response.get('id')!=ident:continue
                        if 'error' in response:
                            if expect_error:return response['error']
                            error=response['error'];raise RuntimeError('Fixture RPC '+method+' refused: '+str(error.get('message')))
                        if expect_error:raise RuntimeError('Native RPC accepted conflicting request ID')
                        return response['result']
                stage='codex_preflight'
                codex_checks={};before_codex=len(requests)
                for case,extra in [('native-signin',{}),('explicit-key',{'api_key':'MESH_POISON_NOT_EXPORT'}),('endpoint-override',{'base_url':'http://127.0.0.1:9/v1'})]:
                    selected={'request_id':'mesh-codex-preflight-'+case,'source':'tool','model':'synthetic-codex-no-generation',
                        'provider':'openai-codex','toolsets':['file'],'safe_mode':True,'ignore_rules':True,
                        'cwd':str(root/'workspace'),'max_turns':50,**extra}
                    created_codex=await rpc('session.create',selected)
                    observed_codex=await rpc('prompt.lookup',{'session_id':created_codex['session_id'],'submission_id':'codex-never-submitted'})
                    contract=observed_codex.get('profile_contract')
                    if (observed_codex.get('found') is not False or not contract or contract['provider']!='openai-codex'
                            or contract['model']!='synthetic-codex-no-generation' or contract['closed'] is not True
                            or contract.get('api_key_configured') is not (case=='explicit-key')
                            or (case!='endpoint-override' and contract['base_url'] not in (None,''))
                            or (case=='endpoint-override' and contract['base_url']!='http://127.0.0.1:9/v1')):
                        raise RuntimeError('Explicit Codex preflight policy was not preserved: '+case)
                    codex_checks[case]=observed_codex
                config_path=root/'fixture-home'/'config.yaml'
                if config_path.is_symlink():raise RuntimeError('Unexpected fixture config link')
                original_config=config_path.read_bytes() if config_path.is_file() else None
                try:
                    config_path.write_text('model:\n  default: synthetic-codex-no-generation\n  provider: openai-codex\n  api_key: MESH_INHERITED_POISON\n')
                    inherited_params={'request_id':'mesh-codex-preflight-inherited','source':'tool','model':'synthetic-codex-no-generation',
                        'provider':'openai-codex','toolsets':['file'],'safe_mode':True,'ignore_rules':True,'cwd':str(root/'workspace'),'max_turns':50}
                    inherited=await rpc('session.create',inherited_params)
                    observed=await rpc('prompt.lookup',{'session_id':inherited['session_id'],'submission_id':'codex-never-submitted'})
                    if observed.get('found') is not False or observed.get('profile_contract',{}).get('api_key_configured') is not False:
                        raise RuntimeError('Safe Codex policy inherited an owner profile key')
                    codex_checks['profile-key-ignored']=observed
                finally:
                    if original_config is not None:config_path.write_bytes(original_config)
                    else:
                        if config_path.parent!=root/'fixture-home':raise RuntimeError('Fixture config restoration escaped root')
                        config_path.unlink()
                if len(requests)!=before_codex or any(marker in json.dumps(codex_checks) for marker in ('MESH_POISON_NOT_EXPORT','MESH_INHERITED_POISON')):
                    raise RuntimeError('Codex preflight created provider work or exported a key')
                (root/'codex-preflight-evidence.json').write_text(json.dumps({'schema':'mesh-codex-preflight/v2','qualification':'PASS','cases':codex_checks,'providerRequestsAdded':0,'promptsSubmitted':0},indent=2))
                stage='create'
                params={'request_id':'mesh-local-create-fixture','source':'tool','model':'mesh-local-fixture',
                    'provider':'custom','base_url':endpoint,'api_key':'synthetic-local-provider',
                    'toolsets':['file'],'safe_mode':True,'ignore_rules':True,'cwd':str(root/'workspace'),'max_turns':4}
                created=await rpc('session.create',params);sid=created['session_id']
                replayed=await rpc('session.create',params)
                if replayed['session_id']!=sid:raise RuntimeError('Native creation retry changed session')
                creation_error=await rpc('session.create',{**params,'max_turns':3},expect_error=True)
                creation_reason=creation_error.get('data',{}).get('reason',creation_error.get('message'))
                if creation_reason!='invalid_params':raise RuntimeError('Wrong native creation-conflict refusal')
                stage='submit';submission={'session_id':sid,'text':'Read and edit the provided synthetic proof, then finish.',
                    'submission_id':'mesh-local-submit-fixture','finite':True}
                admitted=await rpc('prompt.submit',submission);admission=admitted['admission_id']
                stage='worker_start';await asyncio.wait_for(worker_started.wait(),45)
                worker=runner.session_authority._managed_workers[sid]
                if worker.worker is None or worker.worker[0]==os.getpid():raise RuntimeError('No verified separate native worker')
                submission_error=await rpc('prompt.submit',{**submission,'text':'Conflicting payload must never execute.'},expect_error=True)
                submission_reason=submission_error.get('data',{}).get('reason',submission_error.get('message'))
                if submission_reason!='admission_conflict':raise RuntimeError('Wrong native submission-conflict refusal')
                before_lookup=len(requests)
                lookup=await rpc('prompt.lookup',{'session_id':sid,'submission_id':submission['submission_id']})
                missing=await rpc('prompt.lookup',{'session_id':sid,'submission_id':'never-submitted-fixture'})
                other=await rpc('session.create',{**params,'request_id':'mesh-other-local-create'})
                cross=await rpc('prompt.lookup',{'session_id':other['session_id'],'submission_id':submission['submission_id']})
                if (lookup.get('found') is not True or lookup.get('receipt',{}).get('admission_id')!=admission
                        or lookup.get('session_id')!=sid or lookup.get('submission_id')!=submission['submission_id']
                        or missing.get('found') is not False or cross.get('found') is not False
                        or len(requests)!=before_lookup):raise RuntimeError('Native read-only request lookup is not exact or created work')
                pid,birth=worker.worker
                if worker.process.poll() is not None:raise RuntimeError('Native worker exited before tool work')
                worker_release.set();stage='receipt';deadline=time.monotonic()+60
                while True:
                    receipt=await rpc('prompt.receipt',{'session_id':sid,'admission_id':admission,'include_result':True})
                    if receipt['status']=='terminal':break
                    if receipt['status']=='unknown' or time.monotonic()>deadline:raise RuntimeError('Native worker did not produce terminal receipt')
                    await asyncio.sleep(.05)
                final=receipt.get('result',{}).get('final_response')
                if final!='mesh local fixture completed' or proof.read_bytes()!=b'Mesh local session proof.\n':
                    raise RuntimeError('Actual local worker did not complete file edit')
                stage='process_exit';deadline=time.monotonic()+10
                while worker.process.poll() is None:
                    if time.monotonic()>deadline:raise RuntimeError('Native worker handle did not exit')
                    await asyncio.sleep(.02)
                by_request=await rpc('prompt.lookup',{'session_id':sid,'submission_id':submission['submission_id'],'include_result':True})
                if by_request.get('receipt',{}).get('admission_id')!=admission or by_request.get('receipt',{}).get('result',{}).get('final_response')!=final:
                    raise RuntimeError('Native terminal request lookup lost its result')
                count=len(requests);stage='replay';again=await rpc('prompt.submit',submission)
                if again['admission_id']!=admission or len(requests)!=count:raise RuntimeError('Submission retry created work')
                stage='mesh_binding'
                import shutil
                node=shutil.which('node')
                if node is None:raise RuntimeError('Existing Node is required for Mesh binding qualification')
                (root/'node-binding-config.json').write_text(json.dumps({'endpoint':endpoint,'workspace':str(root/'workspace'),'realNimsReview':json.loads((root/'manifest.json').read_text()).get('realNimsReview',False)}))
                script=Path(__file__).resolve().parents[1]/'test'/'fixtures'/'native-local-binding.mjs'
                dropped=False;native_submitted=None;node_calls={};native_session=None;native_request=None
                released=False
                async def release_fixture_child(params):
                    nonlocal released,stage,pending_write
                    if released or params!={'admission_id':native_submitted}:
                        raise RuntimeError('Fixture release did not select its original assignment')
                    stage='assignment_process_observation'
                    assignments=runner.session_authority._mesh_assignment_processes
                    baseline_processes=assignments[admission].observe()
                    current_assignment=assignments[native_submitted]
                    held=current_assignment.observe()
                    wire_held=await rpc('prompt.lookup',{'session_id':native_session,'submission_id':native_request})
                    if wire_held.get('process_scope',{}).get('process_tree_ended') is not False:
                        raise RuntimeError('Authenticated native readback did not retain the live assignment child')
                    if (not baseline_processes['processTreeEnded'] or held['processTreeEnded']
                            or not held.get('allRootsEnded') or held.get('activeProcesses',0)<1
                            or not held['assignmentLaunchSealed'] or held['terminationRequested']):
                        raise RuntimeError('Assignment process scope failed to retain its late child')
                    try:
                        current_assignment.popen([sys.executable,'-c','raise SystemExit(99)'])
                    except RuntimeError:pass
                    else:raise RuntimeError('Retired native assignment launched a replacement root')
                    child_release.write_text('release fixture child')
                    deadline=time.monotonic()+10
                    while True:
                        ended=current_assignment.observe()
                        if ended['processTreeEnded']:break
                        if time.monotonic()>deadline:raise RuntimeError('Assignment child did not end naturally')
                        await asyncio.sleep(.02)
                    if ended['terminationRequested'] or ended['writerQuiescence']:
                        raise RuntimeError('Process observation was confused with whole-writer clearance')
                    wire_ended=await rpc('prompt.lookup',{'session_id':native_session,'submission_id':native_request})
                    if wire_ended.get('process_scope',{}).get('process_tree_ended') is not True:
                        raise RuntimeError('Authenticated native readback did not observe the ended assignment')
                    (root/'assignment-process-evidence.json').write_text(json.dumps({
                        'heldAfterRootExit':held,'naturallyEnded':ended,'differentAssignment':baseline_processes,
                        'authenticatedHeld':wire_held['process_scope'],'authenticatedEnded':wire_ended['process_scope'],
                        'lateRootRefused':True,'wholeWorkerReleaseQualified':False},indent=2))
                    # Hold a real owner transaction while its tracked mutation remains pending.
                    from gateway.session_runtime_workers import tracked_write
                    def delayed_write():
                        def write(conn):
                            write_entered.set()
                            if not write_release.wait(15):raise RuntimeError('Fixture writer gate timed out')
                            conn.execute("INSERT OR REPLACE INTO state_meta(key,value) VALUES(?,?)",
                                ('mesh.fixture.retirement-write','committed'))
                        return runner.session_authority.db._execute_write(write)
                    pending_write=asyncio.create_task(tracked_write(runner.session_authority,delayed_write))
                    if not await asyncio.to_thread(write_entered.wait,3):raise RuntimeError('Fixture writer did not start')
                    began=time.monotonic()
                    blocked=await rpc('prompt.lookup',{'session_id':native_session,'submission_id':native_request})
                    latency=time.monotonic()-began
                    if blocked['process_scope']['authority_writes_drained'] or latency>2:
                        raise RuntimeError('Retirement readback waited on or overlooked an unfinished write')
                    evidence=json.loads((root/'assignment-process-evidence.json').read_text())
                    evidence.update(blockedWrite=blocked['process_scope'],blockedLookupSeconds=latency)
                    (root/'assignment-process-evidence.json').write_text(json.dumps(evidence,indent=2))
                    released=True
                    return {'released':True}
                async def release_fixture_write(params):
                    if params!={'admission_id':native_submitted} or pending_write is None or write_release.is_set():
                        raise RuntimeError('Fixture writer release did not select its original assignment')
                    write_release.set()
                    await asyncio.wait_for(asyncio.shield(pending_write),5)
                    ready=await rpc('prompt.lookup',{'session_id':native_session,'submission_id':native_request})
                    if not all(ready['process_scope'][key] is True for key in
                            ('execution_closed','authority_writes_drained','worker_resources_idle')):
                        raise RuntimeError('Exact native retirement conditions did not become ready')
                    from hermes_state_runtime import apply_worker_receipt,RuntimeStoreError
                    db=runner.session_authority.db
                    with db._read_ctx() as conn:
                        worker_row=dict(conn.execute('SELECT * FROM worker_executions WHERE execution_id=?',
                            ('admission-worker:'+native_submitted,)).fetchone())
                    touched=[]
                    def forbidden(*_):
                        touched.append(True)
                        raise RuntimeError('Closed native execution reached its mutation handler')
                    try:
                        await asyncio.to_thread(apply_worker_receipt,db,epoch=runner.session_authority.epoch,
                            execution_id=worker_row['execution_id'],session_id=worker_row['session_id'],
                            generation=worker_row['generation'],sequence=worker_row['last_sequence']+1,
                            operation='fixture.after_finish',payload={},handlers={'fixture.after_finish':forbidden})
                    except RuntimeStoreError as error:
                        if error.reason!='stale_generation':raise
                    else:raise RuntimeError('Closed native execution accepted a new mutation')
                    if touched:raise RuntimeError('Retired worker mutation handler executed')
                    evidence=json.loads((root/'assignment-process-evidence.json').read_text())
                    evidence.update(authenticatedEnded=ready['process_scope'],writeCommitted=True,closedMutationRefused=True)
                    (root/'assignment-process-evidence.json').write_text(json.dumps(evidence,indent=2))
                    return {'writesDrained':True}

                node_environment=dict(os.environ)
                review_manifest=json.loads((root/'manifest.json').read_text())
                if review_manifest.get('realNimsReview'):
                    # Only the reviewer process receives existing owner runtime paths.
                    # The native worker retains isolated roots and no provider secrets.
                    paths=review_manifest['reviewerRuntimePaths']
                    if set(paths)!={'APPDATA','LOCALAPPDATA','USERPROFILE','HOME','CODEX_HOME'}:
                        raise RuntimeError('Unexpected reviewer runtime-path fields')
                    for key,value in paths.items():
                        if value is None:node_environment.pop(key,None)
                        else:node_environment[key]=value
                with (root/'node-binding.log').open('wb') as node_log:
                    node_process=subprocess.Popen([node,str(script),str(root)],cwd=root/'source',env=node_environment,
                        stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=node_log,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
                    try:
                        while True:
                            line=await asyncio.wait_for(asyncio.to_thread(node_process.stdout.readline),90)
                            if not line:raise RuntimeError('Mesh binding fixture exited before completion')
                            frame=json.loads(line)
                            if frame.get('done'):
                                if frame['admissionId']!=native_submitted:raise RuntimeError('Mesh bound a different native admission')
                                break
                            method=frame['method'];node_calls[method]=node_calls.get(method,0)+1
                            if method=='mesh.fixture.release-child':
                                result=await release_fixture_child(frame['params'])
                            elif method=='mesh.fixture.release-write':
                                result=await release_fixture_write(frame['params'])
                            else:result=await rpc(method,frame['params'])
                            if method=='prompt.submit' and not dropped:
                                native_submitted=result['admission_id'];native_session=frame['params']['session_id'];native_request=frame['params']['submission_id'];dropped=True
                                answer={'id':frame['id'],'error':'synthetic reply loss after durable native admission'}
                            else:answer={'id':frame['id'],'result':result}
                            node_process.stdin.write((json.dumps(answer)+'\n').encode());node_process.stdin.flush()
                        if await asyncio.to_thread(node_process.wait,10)!=0:raise RuntimeError('Mesh binding fixture failed')
                    finally:
                        if node_process.poll() is None:node_process.kill();await asyncio.to_thread(node_process.wait,5)
                        node_process.stdin.close();node_process.stdout.close()
                if not released or not dropped or node_calls.get('session.create')!=1 or node_calls.get('prompt.submit')!=1:
                    raise RuntimeError('Mesh binding did not reconcile the single original native dispatch')
                report={'qualification':'PASS','sessionId':sid,'replayedSessionId':replayed['session_id'],
                    'admissionId':admission,'replayedAdmissionId':again['admission_id'],'finalResponse':final,
                    'distinctVerifiedWorker':True,'ownerPid':os.getpid(),'workerPid':pid,'workerBirth':birth,'workerHandleExited':True,
                    'workerExitCode':worker.process.returncode,'replayCreatedNoProviderWork':True,'providerRequests':len(requests),
                    'nativeBaselineProviderRequests':count,'meshBindingVerified':True,'meshBindingDroppedReply':True,
                    'scope':'actual native owner/private bootstrap/WS/local frozen session/process worker/file tools/SQLite receipt; synthetic local provider',
                    'unauthenticatedRefused':True,'creationConflictRefused':True,'submissionConflictRefused':True,
                    'creationRefusalReason':creation_reason,'submissionRefusalReason':submission_reason,
                    'requestLookupVerified':True,'missingRequestDoesNotCreate':True,'crossSessionLookupRefused':True,
                    'wholeWorkerReleaseQualified':True,'liveInstallation':False}
    except BaseException as error:
        (root/'local-session-failure.json').write_text(json.dumps({'stage':stage,'errorClass':type(error).__name__,
            'message':str(error) if type(error) is RuntimeError else None,'providerRequests':len(requests)},indent=2))
        raise
    finally:
        worker_release.set();write_release.set()
        try:
            if runner is not None:
                if getattr(runner,'session_runtime_descriptor',None) is not None:
                    await drain_gateway_runtime(runner)
                    # Native reserves ten seconds from this budget for tail cleanup.
                    await settle_gateway_runtime(runner,budget=40)
                from gateway.session_runtime_workers import join_authority_work
                authority=getattr(runner,'session_authority',None)
                if authority is not None:
                    await join_authority_work(authority,5)
                    if any(not task.done() for task in _authority_tasks(authority)):
                        raise RuntimeError('Disposable native owner retains authority tasks')
        finally:
            if runner is not None:
                for assignment in getattr(getattr(runner,'session_authority',None),'_mesh_assignment_processes',{}).values():
                    assignment.dispose()
            if control is not None:await control.stop()
            process_ownership.close();await service.cleanup()
    if report is None:raise RuntimeError('No completed native local session evidence')
    report['ownerSettled']=True
    (root/'local-session-evidence.json').write_text(json.dumps(report,indent=2))
    return report


if __name__=='__main__':
    if len(sys.argv)==3 and sys.argv[1]=='--child':
        import asyncio
        print(json.dumps(asyncio.run(child(Path(sys.argv[2]).resolve()))))
    elif len(sys.argv)==3 and sys.argv[1]=='--verify':
        print(json.dumps(verify(Path(sys.argv[2]).resolve())))
    else:
        if len(sys.argv) not in (3,4) or (len(sys.argv)==4 and sys.argv[3]!='--real-nims'):raise SystemExit('Usage: native_root python_executable [--real-nims] | --verify directory')
        from integrations.qualify_hermes_runtime import runtime_environment
        from integrations.windows_writer_fence import WindowsWriterFence
        native,executable=sys.argv[1:3];root=prepare_local(native)
        if len(sys.argv)==4:
            manifest=json.loads((root/'manifest.json').read_text());manifest['realNimsReview']=True
            manifest['reviewerRuntimePaths']={key:os.environ.get(key) for key in ('APPDATA','LOCALAPPDATA','USERPROFILE','HOME','CODEX_HOME')}
            (root/'manifest.json').write_text(json.dumps(manifest,indent=2))
        environment=runtime_environment(root,native,executable,('--safe-mode',))
        print(json.dumps({'directory':str(root),'state':'running_isolated_local_session'}),flush=True)
        fence=WindowsWriterFence('local-session-fixture',str(uuid.uuid4()))
        try:
            with (root/'local-session-runtime.log').open('wb') as log:
                with fence.popen([executable,str(Path(__file__).resolve()),'--child',str(root)],
                        cwd=str(root/'source'),env=environment,stdout=log,stderr=subprocess.STDOUT) as process:
                    try:code=process.wait(timeout=240)
                    except BaseException:fence.terminate();raise
            fence.seal()
            before_cleanup=fence.wait(5000)
            (root/'local-session-fixture-processes.json').write_text(json.dumps(before_cleanup,indent=2))
            print(json.dumps({'directory':str(root),'exitCode':code}),flush=True)
            if code==0:print(json.dumps(verify(root)),flush=True)
            sys.exit(code)
        finally:fence.terminate();fence.close()
