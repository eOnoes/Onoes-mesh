"""Boot copied real Relay using only server-owned loopback/disposable inputs."""
import asyncio
import json
import os
import socket
import sys
from pathlib import Path
expected = {'mesh_only': True, 'debug': False, 'agents': {'mesh': {'name': 'Mesh Workroom', 'backend': 'mesh', 'demo_fallback': False}}}
if json.loads(Path(os.environ['RELAY_CONFIG_PATH']).read_text()) != expected:
    raise RuntimeError('Only isolated Mesh-only Relay config is admitted')
import mesh_link
import relay_auth

capability = os.environ['MESH_RELAY_CAPABILITY']
relay_auth.load_token = lambda _root: capability  # Synthetic, ephemeral; no key files.
sys.stdout = sys.stderr  # Diagnostics are not RPC.
import relay_server as relay
import uvicorn

class ConfinedGate:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] == 'http':
            from fastapi.responses import Response
            headers = dict(scope['headers'])
            origin = f'http://127.0.0.1:{listener.getsockname()[1]}'.encode()
            allowed = {('GET', '/'), ('GET', '/api/agents'), ('GET', '/api/auth'), ('GET', '/api/agents/mesh/sessions'), ('POST', '/api/agents/mesh/message')}
            if (scope.get('client', [None])[0] != '127.0.0.1'
                    or headers.get(b'host') != origin[7:]
                    or headers.get(b'origin') != origin
                    or headers.get(b'authorization') != ('Bearer ' + capability).encode()
                    or (scope['method'], scope['path']) not in allowed):
                await Response(status_code=403)(scope, receive, send)
                return
        await self.app(scope, receive, send)

listener = socket.socket()
listener.bind(('127.0.0.1', 0))
listener.listen(32)

async def main():
    reader = asyncio.create_task(mesh_link.replies())
    server = uvicorn.Server(uvicorn.Config(ConfinedGate(relay.app), log_level='error', access_log=False))
    serving = asyncio.create_task(server.serve(sockets=[listener]))
    while not server.started:
        if serving.done():
            await serving
            raise RuntimeError('Relay failed to start')
        await asyncio.sleep(0.01)
    await relay.MESH_LINK.recover()
    mesh_link.PROTOCOL_OUT.write(json.dumps({'event': 'mesh_relay_listening', 'pid': os.getpid(), 'port': listener.getsockname()[1]}) + '\n')
    mesh_link.PROTOCOL_OUT.flush()
    try:
        await serving
    finally:
        reader.cancel()
        relay.SESSIONS.db.close()

asyncio.run(main())
