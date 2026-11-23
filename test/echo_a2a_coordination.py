"""Opt-in test of the installed Hermes A2A transport with a deterministic reply.

Run with Python and the path to a Hermes checkout with its own venv. Only the
child interpreter imports Hermes. Its profile, peer token and listener are
temporary. The caller uses standard HTTP, as a separately enrolled client would.
"""
import asyncio
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
import uuid


def exchange(base, method, params, token):
    request_id = str(uuid.uuid4())
    headers = {'Content-Type': 'application/json'}
    if token:
        headers['Authorization'] = 'Bearer ' + token
    body = {'jsonrpc': '2.0', 'id': request_id, 'method': method, 'params': params}
    req = urllib.request.Request(base, data=json.dumps(body).encode(), headers=headers)
    with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req, timeout=15) as response:
        answer = json.load(response)
    assert answer['id'] == request_id and 'error' not in answer, answer.get('error')
    return answer['result']


async def run_fixture(home, checkout):
    assert Path(os.environ['HERMES_HOME']).resolve() == home == Path.cwd()
    assert home.name.startswith('mesh-a2a-check-') and not (home / 'config.yaml').exists()
    # Both sides use loopback. Catch unexpected network activity during imports or dispatch.
    def local_only(event, args):
        if event in ('socket.bind', 'socket.connect') and isinstance(args[1], tuple):
            if args[1][0] not in ('127.0.0.1', '::1'):
                raise RuntimeError('The A2A test only supports loopback')
    sys.addaudithook(local_only)
    token = secrets.token_urlsafe(32)
    os.environ.update(A2A_AGENT_NAME='echo-fixture', A2A_HOST='127.0.0.1',
                      A2A_PEER_TOKENS='nims:'+token, A2A_TRUSTED_PEERS='nims', A2A_REPLY_TIMEOUT='8')
    sys.path.insert(0, str(checkout))
    from gateway.config import PlatformConfig
    from plugins.platforms.a2a.adapter import A2AAdapter

    adapter = A2AAdapter(PlatformConfig(extra={'port': 0, 'advertised_toolsets':['coordination']}))
    seen = []
    async def answer(event):
        seen.append((event.source.user_id,event.source.chat_id))
        return 'The fixture engine is ready.' if len(seen)==1 else 'The fixture has no loaded model.'
    adapter.set_message_handler(answer)
    assert await adapter.connect()
    try:
        host,port = adapter._httpd.server_address[:2]
        assert host == '127.0.0.1' and port>0
        base = f'http://{host}:{port}/'
        context = str(uuid.uuid4())
        def ask(message, credential):
            params = {'message':{'messageId':str(uuid.uuid4()), 'role':'ROLE_USER',
                                 'contextId':context,'parts':[{'text':message}]}}
            return exchange(base,'SendMessage',params,credential)
        try:
            await asyncio.to_thread(ask,'Fixture question',None)
        except urllib.error.HTTPError as error:
            assert error.code==401
            error.close()
        else:
            raise AssertionError('Missing peer credential was accepted')
        assert seen==[]
        task_ids=[]
        for question,expected in [('Which fixture engine is ready?', 'The fixture engine is ready.'),
                                  ('Does it have a model loaded?', 'The fixture has no loaded model.')]:
            result=await asyncio.to_thread(ask,question,token)
            task=result.get('task',result)
            assert task['contextId']==context and task['status']['state']=='TASK_STATE_COMPLETED'
            texts=[p.get('text') for artifact in task.get('artifacts',[]) for p in artifact.get('parts',[])]
            assert expected in texts, (list(task),texts)
            task_ids.append(task['id'])
        assert len(set(task_ids))==2 and seen==[('nims',context)]*2
        (home/'result.json').write_text(json.dumps({'peer':seen[0][0],'distinctTasks':len(set(task_ids)),
            'contexts':len(set(c for _,c in seen)),'unauthenticatedStatus':401}),encoding='utf-8')
    finally:
        await adapter.disconnect()


def main():
    if len(sys.argv)==4 and sys.argv[1]=='--fixture':
        asyncio.run(run_fixture(Path(sys.argv[2]).resolve(),Path(sys.argv[3]).resolve()))
        return
    if len(sys.argv)!=2: raise SystemExit('Pass the installed Hermes checkout as the sole argument.')
    checkout=Path(sys.argv[1]).resolve(strict=True)
    executable=checkout/'venv'/('Scripts/python.exe' if os.name=='nt' else 'bin/python')
    env={k:v for k,v in os.environ.items() if k.upper() in {
        'SYSTEMROOT','WINDIR','COMSPEC','PATH','PATHEXT','TEMP','TMP','LANG','SYSTEMDRIVE'}}
    with tempfile.TemporaryDirectory(prefix='mesh-a2a-check-') as tmp:
        home=Path(tmp).resolve()
        env.update(HERMES_HOME=str(home),HOME=str(home),USERPROFILE=str(home),LOCALAPPDATA=str(home),
                   APPDATA=str(home),PYTHONIOENCODING='utf-8',PYTHONDONTWRITEBYTECODE='1',NO_PROXY='*')
        subprocess.run([str(executable),'-B',str(Path(__file__).resolve()),'--fixture',str(home),str(checkout)],
                       env=env,cwd=home,check=True,timeout=60,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        result=json.loads((home/'result.json').read_text(encoding='utf-8'))
        assert result=={'peer':'nims','distinctTasks':2,'contexts':1,'unauthenticatedStatus':401}
        print('PASS: the named Nims peer received two final answers in one context; anonymous access was refused.')


if __name__=='__main__':
    main()
