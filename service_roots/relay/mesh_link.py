"""Reference-only Mesh branch of Relay's real message route; no task store here."""
import asyncio
import json
import hashlib
import re
import sys
import uuid
from fastapi.responses import JSONResponse

PROTOCOL_OUT = sys.stdout
pending = {}

async def replies():
    while True:
        line = await asyncio.to_thread(sys.stdin.readline)
        if not line:
            import os
            os._exit(0)  # Exact owning Mesh pipe closed; no orphan server.
        try:
            value = json.loads(line)
            future = pending.get(value.get('rpcId'))
            if future and not future.done():
                future.set_result(value)
        except (ValueError, TypeError):
            pass

class MeshLink:
    def __init__(self, sessions):
        self.sessions = sessions
        with sessions.lock, sessions.db:
            sessions.db.execute('''CREATE TABLE IF NOT EXISTS mesh_task_references (
                conversation_id TEXT NOT NULL REFERENCES sessions(id),
                message_id TEXT NOT NULL, task_id TEXT, message_hash TEXT NOT NULL,
                PRIMARY KEY(conversation_id,message_id))''')

    def references(self, conversation_id):
        with self.sessions.lock:
            return [dict(r) for r in self.sessions.db.execute(
                'SELECT conversation_id,message_id,task_id FROM mesh_task_references WHERE conversation_id=? AND task_id IS NOT NULL ORDER BY message_id',
                (conversation_id,))]

    def unlinked(self, conversation_id):
        with self.sessions.lock:
            return [r['message_id'] for r in self.sessions.db.execute(
                'SELECT message_id FROM mesh_task_references WHERE conversation_id=? AND task_id IS NULL', (conversation_id,))]

    async def recover(self):
        # Only restore an already canonical reference. No replay creates a task.
        with self.sessions.lock:
            rows = list(self.sessions.db.execute('SELECT conversation_id,message_id FROM mesh_task_references WHERE task_id IS NULL'))
        for row in rows:
            rpc_id = str(uuid.uuid4())
            pending[rpc_id] = asyncio.get_running_loop().create_future()
            try:
                PROTOCOL_OUT.write(json.dumps({'event':'mesh_relay_recover','rpcId':rpc_id,'conversationId':row['conversation_id'],'messageId':row['message_id']})+'\n')
                PROTOCOL_OUT.flush()
                result = await asyncio.wait_for(pending[rpc_id],timeout=3)
                if result.get('taskId'):
                    with self.sessions.lock,self.sessions.db:
                        self.sessions.db.execute('UPDATE mesh_task_references SET task_id=? WHERE conversation_id=? AND message_id=? AND task_id IS NULL', (result['taskId'],row['conversation_id'],row['message_id']))
            finally:
                pending.pop(rpc_id,None)

    async def message(self, agent, body, intent):
        if (not isinstance(body, dict) or set(body) != {'id', 'text', 'conversationId', 'meshIntent'}
                or body.get('meshIntent') != 'create_task'
                or not isinstance(body.get('id'), str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', body['id'])
                or not isinstance(body.get('text'), str) or not body['text'].strip()
                or len(body['text']) > 4000 or '\0' in body['text']
                or body.get('conversationId') != agent.conversation_id
                or not re.fullmatch(r'[0-9a-f-]{36}', intent)):
            return JSONResponse({'ok': False, 'error': 'Explicit Mesh message intent and current conversation required.'}, status_code=400)
        async with __import__('relay_server').MESSAGE_LOCKS[agent.id]:
            try:
                message_hash = hashlib.sha256(body['text'].encode('utf-8')).hexdigest()
                with self.sessions.lock,self.sessions.db:
                    old = self.sessions.db.execute('SELECT task_id,message_hash FROM mesh_task_references WHERE conversation_id=? AND message_id=?', (agent.conversation_id,body['id'])).fetchone()
                    if old and old['message_hash'] != message_hash:
                        return JSONResponse({'ok':False,'error':'Relay message identity already used with different text.'},status_code=409)
                    if not old:
                        # Atomically retain the actual Relay transcript and pending identity
                        # before canonical admission. No task contents/state live here.
                        self.sessions.db.execute('INSERT INTO messages(session_id,role,content,attachments,created_at) VALUES(?,?,?,?,?)', (agent.conversation_id,'you',body['text'],'[]',__import__('relay_db').utc_now()))
                        self.sessions.db.execute('INSERT INTO mesh_task_references VALUES (?,?,NULL,?)', (agent.conversation_id,body['id'],message_hash))
                agent.msgs = self.sessions.messages(agent.id,agent.conversation_id)
            except Exception:
                return JSONResponse({'ok':False,'error':'Relay could not retain the message identity.'},status_code=503)
            rpc_id = str(uuid.uuid4())
            future = asyncio.get_running_loop().create_future()
            pending[rpc_id] = future
            request = {'event': 'mesh_relay_link', 'rpcId': rpc_id, 'intent': intent,
                       'conversationId': agent.conversation_id, 'messageId': body['id'], 'text': body['text']}
            try:
                PROTOCOL_OUT.write(json.dumps(request) + '\n')
                PROTOCOL_OUT.flush()
                result = await asyncio.wait_for(future, timeout=3)
                if not result.get('ok'):
                    return JSONResponse({'ok': False, 'error': result.get('error', 'Mesh link unavailable.')}, status_code=result.get('status', 503))
                task_id = result['taskId']
                if not re.fullmatch(r'[0-9a-f-]{36}', task_id):
                    raise ValueError('Invalid canonical reference')
                with self.sessions.lock, self.sessions.db:
                    old = self.sessions.db.execute('SELECT task_id FROM mesh_task_references WHERE conversation_id=? AND message_id=?', (agent.conversation_id, body['id'])).fetchone()
                    if old and old['task_id'] is not None and old['task_id'] != task_id:
                        raise ValueError('Conflicting canonical reference')
                    self.sessions.db.execute('UPDATE mesh_task_references SET task_id=? WHERE conversation_id=? AND message_id=?', (task_id,agent.conversation_id,body['id']))
                agent.msgs = self.sessions.messages(agent.id, agent.conversation_id)
                return JSONResponse({'ok': True, 'conversationId': agent.conversation_id, 'messageId': body['id'], 'taskId': task_id, 'duplicate': result.get('duplicate', False)})
            except Exception:
                return JSONResponse({'ok': False, 'error': 'Relay could not persist or recover the Mesh reference. Retry the same message id.'}, status_code=503)
            finally:
                pending.pop(rpc_id, None)
