"""Disposable real local-session/RPC/process qualification; never enroll live access."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid


def verify(root):
    report = json.loads((root/'local-session-evidence.json').read_text())
    manifest = json.loads((root/'manifest.json').read_text())
    if report['qualification'] != 'PASS' or report['wholeWorkerReleaseQualified']:
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
            or report.get('workerPid')==report.get('ownerPid')):
        raise RuntimeError('Native local receipt/replay/process evidence is incomplete')
    processes=json.loads((root/'local-session-fixture-processes.json').read_text())
    if not processes['processTreeEnded'] or processes['activeProcesses'] or processes['terminationRequested']:
        raise RuntimeError('Disposable owner/process tree did not end naturally')
    result = {'qualification':'PASS','checks':['pinned_candidate_hashes','actual_file_bytes',
        'native_session_and_submission_identity_replay','verified_separate_worker_and_observed_exit',
        'private_auth_and_conflict_refusals','owner_settled_and_fixture_tree_ended_naturally'],
        'wholeWorkerReleaseQualified':False,'liveInstallation':False}
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
    home=root/'fixture-home'
    if Path(get_hermes_home()).resolve()!=home.resolve():raise RuntimeError('Non-isolated native home')
    proof=root/'workspace'/'local-session-proof.md';proof.write_bytes(b'Before local session edit.\n')
    requests=[];worker_started=asyncio.Event();worker_release=asyncio.Event()
    async def provider(request):
        body=await request.json();requests.append({'tools':[t.get('function',{}).get('name') for t in body.get('tools',[])],
            'roles':[m.get('role') for m in body.get('messages',[])]})
        tools=requests[-1]['tools'];is_worker='write_file' in tools
        if is_worker and not worker_started.is_set():
            worker_started.set();await asyncio.wait_for(worker_release.wait(),30)
        previous=[m for m in body.get('messages',[]) if m.get('role')=='tool']
        call=is_worker and len(previous)<2
        name='read_file' if not previous else 'write_file';args={'path':str(proof)}
        if name=='write_file':args['content']='Mesh local session proof.\n'
        message=({'role':'assistant','content':None,'tool_calls':[{'id':'local-proof-'+str(len(previous)),
            'type':'function','function':{'name':name,'arguments':json.dumps(args)}}]} if call else
            {'role':'assistant','content':'mesh local fixture completed' if is_worker else '{"title":"Local worker proof"}'})
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
                count=len(requests);stage='replay';again=await rpc('prompt.submit',submission)
                if again['admission_id']!=admission or len(requests)!=count:raise RuntimeError('Submission retry created work')
                report={'qualification':'PASS','sessionId':sid,'replayedSessionId':replayed['session_id'],
                    'admissionId':admission,'replayedAdmissionId':again['admission_id'],'finalResponse':final,
                    'distinctVerifiedWorker':True,'ownerPid':os.getpid(),'workerPid':pid,'workerBirth':birth,'workerHandleExited':True,
                    'workerExitCode':worker.process.returncode,'replayCreatedNoProviderWork':True,'providerRequests':count,
                    'scope':'actual native owner/private bootstrap/WS/local frozen session/process worker/file tools/SQLite receipt; synthetic local provider',
                    'unauthenticatedRefused':True,'creationConflictRefused':True,'submissionConflictRefused':True,
                    'creationRefusalReason':creation_reason,'submissionRefusalReason':submission_reason,
                    'wholeWorkerReleaseQualified':False,'liveInstallation':False}
    except BaseException as error:
        (root/'local-session-failure.json').write_text(json.dumps({'stage':stage,'errorClass':type(error).__name__,
            'message':str(error) if type(error) is RuntimeError else None,'providerRequests':len(requests)},indent=2))
        raise
    finally:
        worker_release.set()
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
        if len(sys.argv)!=3:raise SystemExit('Usage: native_root python_executable | --verify directory')
        from integrations.qualify_hermes_runtime import prepare,runtime_environment
        from integrations.windows_writer_fence import WindowsWriterFence
        native,executable=sys.argv[1:];root=prepare(native)
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
