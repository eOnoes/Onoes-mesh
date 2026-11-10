"""Private stdio bridge to an already-running local native gateway. Never starts it."""
import argparse
import asyncio
import contextlib
import json
from pathlib import Path
import sys
import threading
from urllib.parse import urlsplit

LIMIT = 1024 * 1024
METHODS = frozenset(('session.create', 'prompt.submit', 'prompt.lookup'))


def validate_frame(line, last_id):
    if len(line) > LIMIT:
        raise ValueError('Oversized frame')
    frame = json.loads(line)
    if (not isinstance(frame, dict) or set(frame) != {'id', 'method', 'params'}
            or type(frame['id']) is not int or not last_id < frame['id'] <= 2**53 - 1
            or frame['method'] not in METHODS or not isinstance(frame['params'], dict)):
        raise ValueError('Invalid frame')
    return frame


def require_loopback(origin, scheme):
    parsed = urlsplit(origin)
    if (parsed.scheme != scheme or parsed.hostname != '127.0.0.1'
            or parsed.username is not None or parsed.password is not None
            or not parsed.port or parsed.query or parsed.fragment):
        raise ValueError('Expected the existing loopback gateway')


def emit(frame):
    value = json.dumps(frame, ensure_ascii=True, separators=(',', ':'))
    if len(value.encode('utf-8')) > LIMIT:
        raise ValueError('Oversized response')
    sys.stdout.write(value + '\n')
    sys.stdout.flush()


async def bridge(ws, readline, output=emit):
    pending = set()

    async def send():
        last_id = 0
        while line := await readline():
            frame = validate_frame(line, last_id)
            last_id = frame['id']
            if len(pending) >= 32:
                raise ValueError('Too many requests')
            pending.add(last_id)
            await ws.send_json({'jsonrpc': '2.0', **frame})

    async def receive():
        async for message in ws:
            if message.type.name != 'TEXT':
                raise ValueError('Native WebSocket closed')
            reply = json.loads(message.data)
            if 'id' not in reply:  # Native notifications do not carry a result.
                continue
            if reply['id'] not in pending:
                raise ValueError('Unexpected response identity')
            pending.remove(reply['id'])
            if ('result' in reply) == ('error' in reply):
                raise ValueError('Invalid native response')
            output({'id': reply['id'], 'error': 'Native request refused.'} if 'error' in reply
                   else {'id': reply['id'], 'result': reply['result']})
        raise ConnectionError('Native connection ended')

    tasks = [asyncio.create_task(send()), asyncio.create_task(receive())]
    try:
        done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            task.result()
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


async def main(native_root, home):
    native_root, home = Path(native_root), Path(home)
    if not native_root.is_absolute() or not home.is_absolute() or not native_root.is_dir() or not home.is_dir():
        raise ValueError('Explicit existing runtime paths required')
    sys.path.insert(0, str(native_root))
    # Keep incidental import output away from the private RPC protocol.
    with contextlib.redirect_stdout(sys.stderr):
        from aiohttp import ClientSession
        from hermes_cli.gateway_client import _session_ticket, gateway_ws_target
        from hermes_cli.gateway_runtime import discover_gateway_endpoint
    discovery = await asyncio.to_thread(discover_gateway_endpoint, home, timeout=5)
    if discovery.state != 'ready':
        raise RuntimeError('Existing gateway unavailable')
    require_loopback(discovery.endpoint.api_origin, 'http')
    ticket = await asyncio.to_thread(_session_ticket, home, discovery.endpoint,
                                    purpose='interactive', refuse_restart_wait=True)
    url, protocols = gateway_ws_target(discovery.endpoint, ticket)
    require_loopback(url, 'ws')
    queue = asyncio.Queue(maxsize=32)
    loop = asyncio.get_running_loop()

    def read_input():
        # A daemon avoids a blocked executor thread preventing exit on WS loss.
        while True:
            line = sys.stdin.buffer.readline(LIMIT + 1)
            try:
                asyncio.run_coroutine_threadsafe(queue.put(line), loop).result()
            except Exception:
                return
            if not line or len(line) > LIMIT:
                return

    async with ClientSession() as client:
        async with client.ws_connect(url, protocols=protocols, max_msg_size=LIMIT, timeout=10) as ws:
            if not protocols or ws.protocol != protocols[0]:
                raise RuntimeError('Native protocol was not accepted')
            threading.Thread(target=read_input, daemon=True).start()
            await bridge(ws, queue.get)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--native-root', required=True)
    parser.add_argument('--home', required=True)
    args = parser.parse_args()
    try:
        asyncio.run(main(args.native_root, args.home))
    except Exception:
        # No native exception, private-control reply, ticket, URL or prompt in errors.
        emit({'type': 'fatal', 'error': 'Native gateway connection unavailable.'})
        sys.exit(1)
