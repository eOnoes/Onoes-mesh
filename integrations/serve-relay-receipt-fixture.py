"""Short-lived full Relay fixture for Mesh HTTP acceptance; no live endpoints."""
import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
import socket
import sys


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--candidate', required=True)
    args = parser.parse_args()
    root = Path(args.candidate).resolve()
    proof = json.loads((root / 'qualification.json').read_text(encoding='utf-8'))
    code = (root / 'relay_server.py').read_text(encoding='utf-8')
    if not proof.get('passed') or hashlib.sha256(code.encode()).hexdigest() != proof['candidateServerSha256']:
        raise RuntimeError('Candidate qualification/hash mismatch')
    for name, expected in proof['copiedSourceSha256'].items():
        if Path(name).name != name or hashlib.sha256((root / name).read_bytes()).hexdigest() != expected:
            raise RuntimeError('Dependency hash mismatch')
    # This fixture accepts only the generated synthetic config and credentials.
    config = json.loads((root / 'synthetic-config.json').read_text(encoding='utf-8'))
    expected_agent = {'name': 'Synthetic Echo', 'backend': 'hermes', 'device': 'fixture',
                      'url': 'http://synthetic-native', 'api_key': 'synthetic-native-access',
                      'demo_fallback': False}
    if config != {'agents': {'echo': expected_agent}, 'notifications': {}}:
        raise RuntimeError('Refusing non-synthetic config')
    if (root / 'synthetic-relay.key').read_text(encoding='utf-8') != 'synthetic-relay-access':
        raise RuntimeError('Refusing non-synthetic credential')
    os.environ.update({'RELAY_CONFIG_PATH': str(root / 'synthetic-config.json'),
                       'RELAY_AUTH_KEY_FILE': str(root / 'synthetic-relay.key'),
                       'RELAY_SESSION_DB': str(root / 'synthetic-full-server.sqlite'),
                       'RELAY_SKIP_OPENCLAW': '1',
                       'RELAY_ARTIFACTS_DIR': str(root / 'synthetic-artifacts'),
                       'RELAY_ATTACHMENT_STORE': str(root / 'synthetic-attachments')})
    sys.path.insert(0, str(root))
    import httpx
    import uvicorn
    loop = asyncio.new_event_loop()
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(('127.0.0.1', 0))
    listener.listen(16)
    port = listener.getsockname()[1]
    libraries = [Path(sys.prefix).resolve(), Path(sys.base_prefix).resolve()]
    def audit(event, values):
        if event in {'socket.connect', 'socket.getaddrinfo', 'subprocess.Popen', 'os.system',
                     'os.startfile', 'os.startfile/2'}:
            raise RuntimeError('Fixture forbids outgoing network and child processes')
        if event == 'open' and not isinstance(values[0], int):
            path = Path(values[0]).resolve()
            mode = str(values[1] or '')
            flags = int(values[2] or 0)
            writing = any(c in mode for c in 'wax+') or bool(flags & (
                os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND))
            if not path.is_relative_to(root) and (writing or not any(
                    path.is_relative_to(library) for library in libraries)):
                raise RuntimeError('Fixture refused external file access')
    sys.addaudithook(audit)
    import relay_server
    agent = relay_server.AGENTS['echo']
    def native_http(request):
        if request.method != 'GET' or request.url.path != '/v1/runs/run_full':
            raise AssertionError('Fixture permits only exact saved-run native GET')
        return httpx.Response(200, json={'run_id': 'run_full', 'status': 'completed',
                                       'session_id': 'rotated-full-session',
                                       'output': 'synthetic private answer'})
    native = relay_server.HermesRunsClient('http://synthetic-native', api_key='synthetic-native-access')
    native._client = httpx.AsyncClient(transport=httpx.MockTransport(native_http))
    agent.hermes = native
    info = {'baseUrl': f'http://127.0.0.1:{port}', 'agentId': 'echo', 'sendId': 'full-send',
            'conversationId': agent.conversation_id, 'expectedRunId': 'run_full'}
    (root / 'receipt-fixture-info.json').write_text(json.dumps(info), encoding='utf-8')
    stop = root / 'receipt-fixture-stop'
    if stop.exists():
        raise RuntimeError('Old fixture stop flag exists; use a fresh qualified candidate')
    server = uvicorn.Server(uvicorn.Config(relay_server.app, host='127.0.0.1', port=port,
                                         access_log=False, log_level='warning'))
    async def run():
        async def deadline():
            for _ in range(90):
                await asyncio.sleep(1)
                if stop.exists():
                    break
            server.should_exit = True
        monitor = asyncio.create_task(deadline())
        try:
            print(json.dumps(info), flush=True)
            await server.serve(sockets=[listener])
        finally:
            monitor.cancel()
            try:
                await monitor
            except asyncio.CancelledError:
                pass
    try:
        loop.run_until_complete(run())
        loop.run_until_complete(loop.shutdown_asyncgens())
        loop.run_until_complete(loop.shutdown_default_executor())
    finally:
        relay_server.SESSIONS.close()
        listener.close()
        loop.close()


if __name__ == '__main__':
    main()
