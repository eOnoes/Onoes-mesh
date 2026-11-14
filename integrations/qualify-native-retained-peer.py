"""Windows adaptation of Hermes tests/gateway/fixtures/shared_authority_peer.py.
Uses real native initialization and recovery, disposable state, synthetic provider/wire.
"""

import asyncio
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import json
import os
from pathlib import Path
import socket
import sys
import threading
import traceback


class ModelPeer(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"data": [{"id": "local-wire-stub", "object": "model"}]}).encode())

    def do_POST(self):
        request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        last = next((m.get("content", "") for m in reversed(request.get("messages", []))
                     if m.get("role") == "user"), "")
        marker = "WS_SHARED" if "WS_SHARED" in json.dumps(last) else "MESSAGING_WARM"
        reply = f"LOCAL_ACK_{marker}"
        if 'BLOCK_FIFO' in json.dumps(last):
            self.server.blocked.set()
            assert self.server.release.wait(15), 'fixture model gate timed out'
        self.server.requests.append(request) if 'messages' in request else self.server.metadata_requests.append(request)
        base = {"id": "chatcmpl-local", "model": "local-wire-stub", "created": 1}
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream" if request.get("stream") else "application/json")
        self.end_headers()
        if request.get("stream"):
            for delta, finish in [({"role": "assistant", "content": reply}, None), ({}, "stop")]:
                chunk = {**base, "object": "chat.completion.chunk", "choices": [
                    {"index": 0, "delta": delta, "finish_reason": finish}]}
                self.wfile.write(("data: " + json.dumps(chunk) + "\n\n").encode())
                self.wfile.flush()
            self.wfile.write(b"data: [DONE]\n\n")
        else:
            self.wfile.write(json.dumps({**base, "object": "chat.completion", "choices": [
                {"index": 0, "message": {"role": "assistant", "content": reply}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}}).encode())


async def probe():
    from gateway.config import Platform, PlatformConfig
    from gateway.platforms.base import BasePlatformAdapter, SendResult
    from gateway.platforms.event import MessageEvent
    from gateway.run import GatewayRunner
    from gateway.session import SessionSource
    from tests.waiting import async_wait_until
    spec = importlib.util.spec_from_file_location('mesh_retained_recovery', Path(__file__).with_name('qualify-native-retained-recovery.py'))
    recovery = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(recovery)
    prepare_crash, recover_probe = recovery.prepare_crash, recovery.recover_probe
    class CaptureAdapter(BasePlatformAdapter):
        def __init__(self):
            super().__init__(PlatformConfig(enabled=True, token="local-fixture"), Platform.TELEGRAM)
            self.sent = []
            self.deliveries = []

        async def connect(self, *, is_reconnect=False):
            return True

        async def disconnect(self):
            pass

        async def send(self, chat_id, content, reply_to=None, metadata=None):
            self.deliveries.append({'chat_id': chat_id, 'content': content, 'reply_to': reply_to, 'metadata': metadata})
            self.sent.append(content)
            return SendResult(success=True, message_id=str(len(self.sent)))

        async def edit_message(self, chat_id, message_id, content, *, finalize=False):
            self.sent.append(content)
            return SendResult(success=True, message_id=message_id)

        async def send_typing(self, chat_id, metadata=None):
            pass

        async def get_chat_info(self, chat_id):
            return {"id": chat_id}

    runner = GatewayRunner()
    if importlib.util.find_spec("gateway.session_authority") is not None:
        from gateway.session_authority import initialize_session_authority
        await initialize_session_authority(runner, profile_id="default", instance_id="test-owner")
    adapter = CaptureAdapter()
    runner.adapters[Platform.TELEGRAM] = adapter
    adapter.set_message_handler(runner._handle_message)
    source = SessionSource(platform=Platform.TELEGRAM, chat_id="fixture-chat", chat_type="dm", user_id="fixture-user")
    if os.environ.get('AUTHORITY_PROBE_MODE') == 'recover':
        await recover_probe(runner, adapter, source, peer)
        return
    event = MessageEvent(text='MESSAGING_WARM', source=source, message_id='warm-1')
    await adapter.handle_message(event)
    await async_wait_until(lambda: not adapter._active_sessions, timeout=35, what='the synthetic warm-up to finish')
    assert event._gateway_accepted, adapter.sent
    assert any('LOCAL_ACK_MESSAGING_WARM' in text for text in adapter.sent), adapter.sent
    await prepare_crash(runner, adapter, source, peer)
if __name__ == "__main__":
    root = Path(os.environ['MESH_NATIVE_RETAINED_ROOT']).resolve()
    if not root.name.startswith('mesh-native-retained-') or Path(os.environ['HERMES_HOME']).resolve() != root / 'state':
        raise RuntimeError('Only the disposable state root is permitted')
    loop = asyncio.new_event_loop()  # Internal Windows self-pipe exists before application network gate.
    peer = ThreadingHTTPServer(("127.0.0.1", 0), ModelPeer)
    peer.requests = []
    peer.metadata_requests = []
    peer.blocked = threading.Event()
    peer.release = threading.Event()
    threading.Thread(target=peer.serve_forever, daemon=True).start()
    base_url = f"http://127.0.0.1:{peer.server_port}/v1"
    os.environ.update(OPENAI_API_KEY="explicit-loopback-fixture", OPENAI_BASE_URL=base_url,
                      TELEGRAM_ALLOWED_USERS="fixture-user")
    Path(os.environ["HERMES_HOME"], "config.yaml").write_text(
        f"model:\n  default: local-wire-stub\n  provider: custom\n  base_url: {base_url}\n"
        f"auxiliary:\n  title_generation:\n    enabled: false\nterminal:\n  cwd: {os.environ['HERMES_HOME']}\n"
        # The durable-FIFO proof needs queue semantics; interrupt mode redirects the running turn.
        "display:\n  busy_input_mode: queue\n")
    native = Path(os.environ['MESH_NATIVE_SOURCE']).resolve()
    if native != root / 'source': raise RuntimeError('Only the disposable source snapshot is permitted')
    allowed_reads = [root, native, Path(sys.prefix).resolve(), Path(sys.base_prefix).resolve()]
    for item in sys.path:
        if item and 'site-packages' in item:
            allowed_reads.append(Path(item).resolve())
    def audit(event, args):
        if event in ('subprocess.Popen', 'os.system'):
            raise RuntimeError('Native qualification forbids subprocesses')
        if event == 'sqlite3.connect' and not Path(args[0]).resolve().is_relative_to(root):
            raise RuntimeError('Native qualification refuses databases outside disposable state')
        if event == 'socket.bind' and (not isinstance(args[1], tuple) or args[1][0] not in ('127.0.0.1', '::1') or args[1][1] != 0):
            raise RuntimeError('Native qualification permits only disposable loopback listeners')
        if event == 'socket.getaddrinfo' and args[0] not in ('127.0.0.1', 'localhost', b'127.0.0.1', b'localhost'):
            raise RuntimeError('Native qualification refuses external DNS')
        if event == 'socket.connect':
            address = args[1]
            if not isinstance(address, tuple) or address[:2] != ('127.0.0.1', peer.server_port):
                raise RuntimeError('Native qualification permits only its synthetic provider port')
        if event == 'open' and isinstance(args[0], (str, bytes, os.PathLike)):
            target = Path(os.fsdecode(args[0])).resolve()
            mode = args[1] or ''
            flags = args[2] or 0
            writing = any(letter in mode for letter in 'wax+') or flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND)
            if writing and not target.is_relative_to(root):
                raise RuntimeError('Native qualification refuses writes outside disposable state')
            if not any(target.is_relative_to(base) for base in allowed_reads):
                raise PermissionError('Native qualification refuses outside file: ' + str(target))
    sys.addaudithook(audit)
    status = 0
    try:
        loop.run_until_complete(probe())
    except BaseException:
        traceback.print_exc()
        status = 1
    finally:
        peer.shutdown()
        peer.server_close()
        sys.stdout.flush()
        sys.stderr.flush()
    # Disposable child owns all runtime background threads (heartbeats, reapers,
    # provider pools); don't leave a lease-wait executor holding pytest hostage.
    os._exit(status)
