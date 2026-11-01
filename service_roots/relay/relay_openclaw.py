"""FastAPI-facing adapter. Native transport runs as a child, never a web service.

Wire this object into Relay's existing Tripp backend; source access is required
to replace that backend's demo fallback. Node >=24.15 is required.
"""
import asyncio
import contextlib
import json
import os
from pathlib import Path
import uuid


class OpenClawAdapter:
    def __init__(self, state_dir, *, node="node", session_key="agent:tripp:relay",
                 url="wss://emitchell109-rog.tail8c4a75.ts.net"):
        self.state_dir = str(Path(state_dir).resolve())
        self.node, self.session_key, self.url = node, session_key, url
        self.snapshot = None
        self.pending = {}
        self.listeners = set()
        self.process = None

    async def start(self):
        env = dict(os.environ, RELAY_STATE_DIR=self.state_dir,
                   RELAY_SESSION_KEY=self.session_key, RELAY_GATEWAY_URL=self.url)
        self.process = await asyncio.create_subprocess_exec(
            self.node, str(Path(__file__).with_name("relay-adapter.mjs")),
            env=env, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL, limit=32 * 1024 * 1024,
            **({"creationflags": 0x08000000} if os.name == "nt" else {}))
        self.reader = asyncio.create_task(self._read())

    async def _read(self):
        try:
            while line := await self.process.stdout.readline():
                row = json.loads(line)
                if "event" in row:
                    self.snapshot = row["event"]["agent"]
                    for queue in self.listeners:
                        # Full snapshots supersede older queued snapshots.
                        if queue.full():
                            queue.get_nowait()
                        queue.put_nowait(row["event"])
                elif row.get("id") in self.pending:
                    future = self.pending.pop(row["id"])
                    if future.done():
                        continue
                    if "error" in row:
                        future.set_exception(RuntimeError(row["error"]))
                    else:
                        future.set_result(row.get("result"))
        finally:
            for future in self.pending.values():
                if not future.done():
                    future.set_exception(RuntimeError("Adapter exited; send outcome may be unknown"))
            self.pending.clear()
            if self.snapshot:
                self.snapshot["connection"] = "disconnected"
                for queue in self.listeners:
                    if queue.full():
                        queue.get_nowait()
                    queue.put_nowait({"type": "snapshot", "agent": self.snapshot})

    async def call(self, method, **params):
        if not self.process or self.process.returncode is not None:
            raise RuntimeError("Tripp adapter is unavailable; demo fallback is disabled")
        request_id = str(uuid.uuid4())
        future = asyncio.get_running_loop().create_future()
        self.pending[request_id] = future
        try:
            self.process.stdin.write((json.dumps({"id": request_id, "method": method,
                                                 "params": params}) + "\n").encode())
            await self.process.stdin.drain()
            return await asyncio.wait_for(future, 40)
        finally:
            self.pending.pop(request_id, None)

    async def events(self):
        queue = asyncio.Queue(maxsize=1)
        self.listeners.add(queue)
        try:
            if self.snapshot:
                yield {"type": "snapshot", "agent": self.snapshot}
            while True:
                yield await queue.get()
        finally:
            self.listeners.discard(queue)

    async def close(self):
        if not self.process:
            return
        self.process.stdin.close()
        try:
            await asyncio.wait_for(self.process.wait(), 5)
        except asyncio.TimeoutError:
            self.process.terminate()
            await self.process.wait()
        self.reader.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self.reader
