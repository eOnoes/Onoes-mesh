"""Isolated fake Hermes API server for Relay contract tests.

Binds an ephemeral loopback port (never 8642/8771/8772), serves the exact shapes the
installed API server emits, and records every approval payload it receives so a test can
prove what Relay really sent. No dangerous command is ever executed.
"""
from __future__ import annotations

import json
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class FakeHermes:
    def __init__(self, *, capabilities=None, approval_forwards_reason=False):
        self.capabilities = capabilities or {
            "features": {
                "approval_events": True,
                "run_approval_response": True,
                "run_events_sse": True,
                "runs_idempotency": {"supported": True, "durable": True, "retention_seconds": 86400},
            }
        }
        self.approval_forwards_reason = approval_forwards_reason
        self.approvals: list[dict] = []
        self.steers: list[dict] = []
        self.sessions: dict[str, dict] = {}
        self.runs: dict[str, dict] = {}
        self.events: dict[str, list[tuple[int, dict]]] = {}
        self.idempotency: dict[str, str] = {}
        self.requests: list[dict] = []
        self.fail_next_status = 0
        self._lock = threading.Lock()
        self._seq = 0
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                return

            def _json(self, status, payload, headers=None):
                body = json.dumps(payload).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                for key, value in (headers or {}).items():
                    self.send_header(key, value)
                self.end_headers()
                self.wfile.write(body)

            def _body(self):
                length = int(self.headers.get("Content-Length", "0"))
                raw = self.rfile.read(length) if length else b"{}"
                try:
                    parsed = json.loads(raw or b"{}")
                except json.JSONDecodeError:
                    return {}
                return parsed if isinstance(parsed, dict) else {}

            def do_GET(self):
                fake.requests.append({"method": "GET", "path": self.path})
                if self.path == "/v1/capabilities":
                    self._json(200, fake.capabilities)
                    return
                if "/events" in self.path:
                    self._events(self.path.split("/")[3])
                    return
                if self.path.startswith("/v1/runs/"):
                    run_id = self.path.split("/")[3]
                    run = fake.runs.get(run_id)
                    if run is None:
                        self._json(404, {"error": "not found"})
                        return
                    self._json(200, run)
                    return
                self._json(404, {"error": "not found"})

            def _events(self, run_id):
                last_seq = -1
                if "?" in self.path:
                    for part in self.path.split("?", 1)[1].split("&"):
                        if part.startswith("last_seq="):
                            try:
                                last_seq = int(part.split("=", 1)[1])
                            except ValueError:
                                last_seq = -1
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-cache")
                self.end_headers()
                # A conforming consumer only sees the content type after the first write.
                self.wfile.write(b": open\r\n\r\n")
                self.wfile.flush()
                for seq, event in list(fake.events.get(run_id, [])):
                    if seq <= last_seq:
                        continue
                    frame = f"id: {seq}\r\ndata: {json.dumps(event)}\r\n\r\n".encode("utf-8")
                    self.wfile.write(frame)
                self.wfile.write(b": stream closed\r\n\r\n")

            def do_POST(self):
                body = self._body()
                fake.requests.append({"method": "POST", "path": self.path, "body": body,
                                      "idempotency": self.headers.get("Idempotency-Key", "")})
                if self.path == "/api/sessions":
                    fake.sessions[str(body.get("id") or "")] = {"id": body.get("id")}
                    self._json(201, {"id": body.get("id")})
                    return
                if self.path.startswith("/api/sessions/") and self.path.endswith("/chat"):
                    session_id = self.path.split("/")[3]
                    content = body.get("content")
                    run_id = "run_" + uuid.uuid4().hex[:12]
                    reply = "saw the photo" if isinstance(content, list) else "ok"
                    fake.runs[run_id] = {"run_id": run_id, "status": "completed", "output": reply,
                                         "session_id": session_id}
                    fake.emit(run_id, {"event": "run.completed", "run_id": run_id, "status": "completed",
                                       "output": reply})
                    self._json(200, {"run_id": run_id, "session_id": session_id,
                                     "message": {"role": "assistant", "content": reply}})
                    return
                if self.path == "/v1/runs":
                    key = self.headers.get("Idempotency-Key", "")
                    fingerprint = json.dumps(body, sort_keys=True)
                    if key and key in fake.idempotency:
                        if fake.idempotency[key] != fingerprint:
                            self._json(409, {"error": "Idempotency-Key was already used with a different request payload"})
                            return
                        run_id = fake.runs_by_key[key]
                        self._json(202, {"run_id": run_id, "status": "completed", "replayed": True},
                                   {"Idempotency-Replayed": "true"})
                        return
                    run_id = "run_" + uuid.uuid4().hex[:12]
                    fake.runs[run_id] = {"run_id": run_id, "status": "running", "output": "",
                                         "session_id": body.get("session_id", "")}
                    if key:
                        fake.idempotency[key] = fingerprint
                        fake.runs_by_key[key] = run_id
                    self._json(202, {"run_id": run_id, "status": "running", "replayed": False})
                    return
                if self.path.startswith("/v1/runs/") and self.path.endswith("/approval"):
                    run_id = self.path.split("/")[3]
                    payload = dict(body)
                    payload["_forwards_reason"] = fake.approval_forwards_reason
                    with fake._lock:
                        fake.approvals.append(payload)
                    choice = str(body.get("choice") or "")
                    request_id = str(body.get("request_id") or "")
                    pending = fake.pending.get(run_id) or []
                    if request_id and request_id not in pending:
                        self._json(409, {"error": f"Run has no pending approval: {run_id}",
                                         "code": "approval_not_pending"})
                        return
                    fake.pending[run_id] = [p for p in pending if p != request_id] if request_id else []
                    if choice == "deny":
                        fake.emit(run_id, {"event": "run.failed", "run_id": run_id, "status": "failed",
                                           "error": "BLOCKED: denied by user"})
                        fake.runs[run_id] = {"run_id": run_id, "status": "failed", "error": "denied"}
                    else:
                        fake.emit(run_id, {"event": "run.completed", "run_id": run_id, "status": "completed",
                                           "output": "went ahead"})
                        fake.runs[run_id] = {"run_id": run_id, "status": "completed", "output": "went ahead"}
                    self._json(200, {"object": "hermes.run.approval_response", "run_id": run_id,
                                     "choice": choice, "request_id": request_id, "resolved": 1})
                    return
                if self.path.startswith("/v1/runs/") and self.path.endswith("/steer"):
                    run_id = self.path.split("/")[3]
                    fake.steers.append({"run_id": run_id, "input": body.get("input")})
                    self._json(200, {"object": "hermes.run.steer", "run_id": run_id, "accepted": True})
                    return
                if self.path.startswith("/v1/runs/") and self.path.endswith("/stop"):
                    run_id = self.path.split("/")[3]
                    fake.runs[run_id] = {"run_id": run_id, "status": "cancelled"}
                    self._json(200, {"run_id": run_id, "status": "cancelled"})
                    return
                self._json(404, {"error": "not found"})

        self.pending: dict[str, list[str]] = {}
        self.runs_by_key: dict[str, str] = {}
        self.handler = Handler
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        # The installed route is the authority for whether a typed reason is forwarded.
        self._install_reason_capability()

    def _install_reason_capability(self) -> None:
        """Point the cached capability at this fixture's approval route, exactly the way
        the real detector reads the installed ``_handle_run_approval`` source."""
        import relay_decisions

        route = ("def _handle_run_approval(self, request):\n"
                 "    choice = request.get('choice')\n"
                 + ("    resolved = resolve_gateway_approval(key, choice, reason=request.get('reason'))\n"
                    if self.approval_forwards_reason else
                    "    resolved = resolve_gateway_approval(key, choice)\n")
                 + "    return resolved\n")
        relay_decisions._CAPABILITY = relay_decisions.detect_reason_support(route)
        relay_decisions._CAPABILITY["_forwards_reason"] = self.approval_forwards_reason

    # -- helpers --------------------------------------------------------------------

    def emit(self, run_id: str, event: dict) -> int:
        with self._lock:
            self._seq += 1
            seq = self._seq
            self.events.setdefault(run_id, []).append((seq, event))
        return seq

    def request_approval(self, run_id: str, request_id: str, *, choices=None, command="rm -rf /tmp/x",
                         description="dangerous command", pattern_key="danger:abc"):
        self.pending.setdefault(run_id, []).append(request_id)
        self.runs[run_id] = {"run_id": run_id, "status": "waiting_for_approval",
                             "approval": {"event": "approval.request", "run_id": run_id,
                                          "request_id": request_id, "command": command,
                                          "description": description, "pattern_key": pattern_key,
                                          "choices": choices or ["once", "session", "always", "deny"]}}
        self.emit(run_id, {"event": "approval.request", "run_id": run_id, "request_id": request_id,
                           "command": command, "description": description, "pattern_key": pattern_key,
                           "choices": choices or ["once", "session", "always", "deny"]})
        return run_id

    def finish(self, run_id: str, status: str = "completed", output: str = "went ahead", error: str = ""):
        """End a run exactly the way the installed API server does: terminal status, then
        the ``run.<status>`` event carrying the output/error."""
        self.runs[run_id] = {"run_id": run_id, "status": status,
                             **({"output": output} if status == "completed" else {}),
                             **({"error": error or status} if status != "completed" else {})}
        event = {"event": f"run.{status}", "run_id": run_id, "status": status}
        event.update({"output": output} if status == "completed" else {"error": error or status})
        self.emit(run_id, event)
        return run_id

    def close(self):
        self.server.shutdown()
        self.server.server_close()
