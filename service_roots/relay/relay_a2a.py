"""A2A v1.0 transport for Relay.

Some agents expose no native Hermes API surface, only an A2A endpoint. Cyony on the
cloud host is the live example: she runs an A2A v1.0 listener on port 9900 and has no
Hermes Desktop and no API server.

A2A is a *conversational* protocol. It gives us streaming text and a genuine task
lifecycle, and it does not expose tool-level progress, approvals, or steering, because
remote peers have no operator surface. This module therefore reports those capabilities
as unavailable so the UI states that plainly instead of showing dead panels.

Wire facts verified against the live endpoint (2026-09-17):
  * Agent card at ``/.well-known/agent-card.json``
  * JSON-RPC methods ``message/send`` and ``message/stream`` (legacy aliases
    ``SendMessage`` / ``SendStreamingMessage`` are also accepted)
  * ``contextId`` returned inside the result and stable across turns
  * ``message/stream`` is SSE of JSON-RPC-wrapped StreamResponse objects with
    ``task`` / ``statusUpdate`` / ``artifactUpdate`` members
  * A clarifying question arrives as ``TASK_STATE_INPUT_REQUIRED``, which Hermes
    signals by prefixing the reply with the literal ``[INPUT_REQUIRED]`` marker
  * Bearer auth on every request
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import re
import uuid
from typing import Any, AsyncIterator

import httpx

# A2A v1.0 task lifecycle states.
STATE_SUBMITTED = "TASK_STATE_SUBMITTED"
STATE_WORKING = "TASK_STATE_WORKING"
STATE_INPUT_REQUIRED = "TASK_STATE_INPUT_REQUIRED"
STATE_COMPLETED = "TASK_STATE_COMPLETED"
STATE_FAILED = "TASK_STATE_FAILED"
STATE_CANCELED = "TASK_STATE_CANCELED"
STATE_REJECTED = "TASK_STATE_REJECTED"

TERMINAL_STATES = frozenset(
    {STATE_COMPLETED, STATE_FAILED, STATE_CANCELED, STATE_REJECTED}
)

# Hermes' inbound A2A adapter prefixes a clarification reply with this marker.
INPUT_REQUIRED_MARKER = "[INPUT_REQUIRED]"

_JSONRPC_METHODS = ("message/send", "SendMessage")
_STREAM_METHODS = ("message/stream", "SendStreamingMessage")
_TEXT_RE = re.compile(r'"text"\s*:\s*"((?:[^"\\]|\\.)*)"')


class A2AError(RuntimeError):
    """An A2A request failed in a way worth showing to the operator."""

    def __init__(self, message: str, *, status: int = 0, code: Any = None):
        super().__init__(message)
        self.status = status
        self.code = code


class _MethodUnsupported(A2AError):
    """The peer does not implement this JSON-RPC method name.

    Peers disagree on the streaming method spelling, so this is a signal to try the
    next candidate rather than a failure to report.
    """


def _part_texts(container: Any) -> list[str]:
    """Text from a ``parts`` list, tolerating anything else."""
    found: list[str] = []
    if isinstance(container, dict):
        for part in container.get("parts") or []:
            if isinstance(part, dict) and isinstance(part.get("text"), str):
                found.append(part["text"])
    return found


def _extract_texts(payload: Any) -> list[str]:
    """Collect text parts from a Task, Message, artifact, or StreamResponse member.

    Covers the shapes A2A actually sends: a task's own parts, its ``status.message``
    (which is how a clarifying question arrives), and its artifacts — plus the
    ``statusUpdate`` / ``artifactUpdate`` stream members.
    """
    if not isinstance(payload, dict):
        return []
    found = _part_texts(payload)
    for status in (payload.get("status"), payload.get("statusUpdate")):
        if isinstance(status, dict):
            found.extend(_part_texts(status))
            found.extend(_part_texts(status.get("status")))
            message = status.get("message")
            if isinstance(message, dict):
                found.extend(_part_texts(message))
            # statusUpdate wraps the status one level deeper.
            nested = status.get("status")
            if isinstance(nested, dict) and isinstance(nested.get("message"), dict):
                found.extend(_part_texts(nested["message"]))
    artifact = payload.get("artifactUpdate")
    if isinstance(artifact, dict):
        found.extend(_part_texts(artifact.get("artifact")))
    # A member passed on its own (rather than wrapped) still carries its artifact.
    if isinstance(payload.get("artifact"), dict):
        found.extend(_part_texts(payload["artifact"]))
    for artifact in payload.get("artifacts") or []:
        if isinstance(artifact, dict):
            found.extend(_part_texts(artifact))
            found.extend(_part_texts(artifact.get("artifact")))
    message = payload.get("message")
    if isinstance(message, dict):
        found.extend(_part_texts(message))
    # De-duplicate while preserving order.
    unique: list[str] = []
    for text in found:
        if text not in unique:
            unique.append(text)
    return unique


def _state_of(node: Any) -> str:
    if not isinstance(node, dict):
        return ""
    status = node.get("status")
    if isinstance(status, dict):
        return str(status.get("state") or "")
    if isinstance(status, str):
        return status
    if "state" in node:
        return str(node.get("state") or "")
    inner = node.get("statusUpdate")
    if isinstance(inner, dict):
        return _state_of(inner)
    return ""


def _task_id_of(node: Any) -> str:
    if not isinstance(node, dict):
        return ""
    for candidate in (node.get("id"), node.get("taskId"), (node.get("statusUpdate") or {}).get("taskId")
                      if isinstance(node.get("statusUpdate"), dict) else None):
        if candidate:
            return str(candidate)
    return ""


def _context_id_of(node: Any) -> str:
    if not isinstance(node, dict):
        return ""
    direct = node.get("contextId")
    if direct:
        return str(direct)
    inner = node.get("statusUpdate")
    if isinstance(inner, dict) and inner.get("contextId"):
        return str(inner["contextId"])
    return ""


def _has_visible_text(text: str) -> bool:
    """True when the caller would see something after the marker is stripped."""
    if not text.strip():
        return False
    clean, _needs_input = strip_input_required(text)
    return bool(clean.strip())


def strip_input_required(text: str) -> tuple[str, bool]:
    """Split Hermes' clarification marker off a reply.

    Returns ``(clean_text, needs_input)``.
    """
    stripped = text.lstrip()
    if stripped.upper().startswith(INPUT_REQUIRED_MARKER):
        return stripped[len(INPUT_REQUIRED_MARKER):].strip(), True
    return text, False


class A2AClient:
    """Talk to one A2A peer on behalf of Relay."""

    def __init__(
        self,
        base_url: str,
        token: str = "",
        *,
        connect_timeout: float = 10.0,
        read_timeout: float = 600.0,
    ):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self._timeout = httpx.Timeout(
            read_timeout, connect=connect_timeout, write=60.0, pool=connect_timeout
        )
        self._client: httpx.AsyncClient | None = None
        self._card: dict | None = None

    # ------------------------------------------------------------- plumbing --
    def _headers(self, extra: dict | None = None) -> dict:
        headers = {"Accept": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        if extra:
            headers.update(extra)
        return headers

    async def client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=self._timeout)
        return self._client

    async def aclose(self) -> None:
        if self._client is not None and not self._client.is_closed:
            with contextlib.suppress(Exception):
                await self._client.aclose()
        self._client = None

    @staticmethod
    def _raise_rpc_error(response: httpx.Response, error: Any) -> None:
        if isinstance(error, dict):
            code = error.get("code")
            message = str(error.get("message") or "A2A peer returned an error")
        else:
            code, message = None, str(error)
        if response.status_code in (401, 403):
            raise A2AError(
                "auth rejected - check the peer token matches her A2A configuration",
                status=response.status_code, code=code,
            )
        if response.status_code == 429:
            raise A2AError(
                f"peer rate limited Relay (HTTP 429): {message}",
                status=429, code=code,
            )
        raise A2AError(f"peer rejected the request: {message}", status=response.status_code, code=code)

    # --------------------------------------------------------------- agent --
    def _card_candidates(self) -> list[str]:
        """Agent-card URLs to try, most specific first.

        Some peers serve the card at the origin root while the JSON-RPC endpoint
        lives on a sub-path (DSH serves the card at ``/.well-known/agent.json`` but
        RPC at ``/a2a``), so both the base path and the origin are tried.
        """
        from urllib.parse import urlsplit

        split = urlsplit(self.base_url)
        origin = f"{split.scheme}://{split.netloc}"
        candidates = [f"{self.base_url}{p}" for p in ("/.well-known/agent-card.json",
                                                      "/.well-known/agent.json")]
        candidates += [f"{origin}{p}" for p in ("/.well-known/agent-card.json",
                                                "/.well-known/agent.json")]
        seen: set[str] = set()
        ordered: list[str] = []
        for candidate in candidates:
            if candidate not in seen:
                seen.add(candidate)
                ordered.append(candidate)
        return ordered

    async def agent_card(self, *, refresh: bool = False) -> dict:
        """Fetch the peer's Agent Card (cached)."""
        if self._card is not None and not refresh:
            return self._card
        client = await self.client()
        last: Exception | None = None
        for url in self._card_candidates():
            try:
                response = await client.get(url, headers=self._headers())
            except Exception as exc:  # transport level
                last = exc
                continue
            if response.status_code == 200:
                card = response.json()
                self._card = card if isinstance(card, dict) else {}
                return self._card
            last = A2AError(
                f"agent card request returned HTTP {response.status_code}",
                status=response.status_code,
            )
        if isinstance(last, A2AError):
            raise last
        raise A2AError(f"could not reach the A2A peer: {last}")

    async def capabilities(self, *, refresh: bool = False) -> dict:
        """Relay-facing capability report for this peer.

        A2A exposes a conversation, not an operator control plane, so the
        unavailable features are reported as false rather than left ambiguous.
        """
        card = await self.agent_card(refresh=refresh)
        advertised = card.get("capabilities") or {}
        return {
            "transport": "a2a",
            "reachable": True,
            "version": str(card.get("version") or ""),
            "streaming": bool(advertised.get("streaming")),
            "push_notifications": bool(advertised.get("pushNotifications")),
            "sessions": True,             # contextId is durable on the peer
            "run_status": True,           # task lifecycle states
            "run_stop": True,             # tasks/cancel
            "tool_progress": False,       # not exposed to remote peers
            "reasoning": False,
            "subagents": False,
            "run_approval": False,        # remote peers get no operator surface
            "run_steer": False,
            "goals": False,
            "attachments": False,
            "session_chat_streaming": bool(advertised.get("streaming")),
            "note": "A2A gives chat, streaming, lifecycle, and stop. Tool progress, "
                    "approvals, steering, and goals need an on-host bridge.",
        }

    async def probe(self) -> dict:
        card = await self.agent_card(refresh=True)
        return {
            "reachable": True,
            "name": str(card.get("name") or ""),
            "skills": len(card.get("skills") or []),
            "capabilities": await self.capabilities(),
        }

    # ----------------------------------------------------------------- task --
    async def get_task(self, task_id: str) -> dict:
        """``tasks/get`` — the reliable way to retrieve a finished task's result.

        This peer does not always emit an ``artifactUpdate`` on the stream, so the
        stream alone can end with no text at all. The task record carries the reply
        in both ``status.message`` and ``artifacts``.
        """
        if not task_id:
            return {}
        client = await self.client()
        bare = task_id[5:] if task_id.startswith("task-") else task_id
        last: Any = None
        for candidate in (task_id, bare):
            body = {
                "jsonrpc": "2.0", "id": f"get-{uuid.uuid4().hex[:12]}", "method": "tasks/get",
                "params": {"id": candidate, "taskId": candidate},
            }
            try:
                response = await client.post(
                    self.base_url,
                    headers=self._headers({"Content-Type": "application/json"}),
                    json=body,
                )
            except Exception as exc:
                last = exc
                continue
            if response.status_code != 200:
                last = A2AError(f"tasks/get returned HTTP {response.status_code}",
                                status=response.status_code)
                continue
            payload = response.json()
            if "error" in payload:
                last = A2AError(
                    f"tasks/get rejected: {(payload['error'] or {}).get('message')}",
                    code=(payload["error"] or {}).get("code"),
                )
                continue
            result = payload.get("result", {})
            return result if isinstance(result, dict) else {}
        if isinstance(last, A2AError):
            raise last
        return {}

    @staticmethod
    def _rpc_body(method: str, text: str, context_id: str) -> dict:
        return {
            "jsonrpc": "2.0",
            "id": f"relay-{uuid.uuid4().hex[:12]}",
            "method": method,
            "params": {
                "message": {
                    # messageId is REQUIRED by the A2A v1.0 Message. Hermes tolerated
                    # its absence, but DSH answers without it by opening an event
                    # stream that carries no frames at all — a silent empty turn.
                    "messageId": uuid.uuid4().hex,
                    "role": "ROLE_USER",
                    "parts": [{"text": text, "mediaType": "text/plain"}],
                    **({"contextId": context_id} if context_id else {}),
                }
            },
        }

    async def send(
        self, text: str, *, context_id: str = "", request_id: str = ""
    ) -> dict:
        """Non-streaming ``message/send``. Returns the terminal task result."""
        client = await self.client()
        body = self._rpc_body(_JSONRPC_METHODS[0], text, context_id)
        if request_id:
            body["id"] = request_id
        try:
            response = await client.post(
                self.base_url, headers=self._headers({"Content-Type": "application/json"}),
                json=body,
            )
        except Exception as exc:
            raise A2AError(f"could not reach the A2A peer: {exc}") from exc
        if response.status_code != 200:
            raise A2AError(
                f"peer returned HTTP {response.status_code}", status=response.status_code
            )
        payload = response.json()
        if "error" in payload:
            self._raise_rpc_error(response, payload["error"])
        return payload.get("result", {})

    async def stream(
        self, text: str, *, context_id: str = "", request_id: str = ""
    ) -> AsyncIterator[dict]:
        """Stream one turn, negotiating the peer's streaming method name.

        The A2A spec calls it ``message/stream``; some servers (DSH) implement only
        the legacy ``SendStreamingMessage`` and answer the spec name with a JSON-RPC
        "Invalid method" error. Each spelling is tried until one returns real SSE.
        """
        last: Exception | None = None
        for method in _STREAM_METHODS:
            try:
                async for event in self._stream_with(
                        method, text, context_id=context_id, request_id=request_id):
                    yield event
                return
            except _MethodUnsupported as exc:
                last = exc
                continue
        raise A2AError(f"this peer supports no streaming method Relay knows: {last}")

    async def _stream_with(
        self, method: str, text: str, *, context_id: str = "", request_id: str = ""
    ) -> AsyncIterator[dict]:
        """Stream one turn as Relay-shaped events, using a specific method name.

        Yields:
          ``{"kind": "accepted"}``                        once the peer starts the task
          ``{"kind": "status", "status": <relay status>}`` on task-state transitions
          ``{"kind": "artifact", "text": ...}``           on streamed text
          ``{"kind": "terminal", ...}``                   once, and last
        """
        client = await self.client()
        body = self._rpc_body(method, text, context_id)
        if request_id:
            body["id"] = request_id
        headers = self._headers({
            "Content-Type": "application/json", "Accept": "text/event-stream",
        })
        task_id = ""
        collected: list[str] = []
        last_state = ""
        accepted = False
        try:
            async with client.stream("POST", self.base_url, headers=headers, json=body) as response:
                if response.status_code != 200:
                    detail = (await response.aread()).decode("utf-8", "replace")[:300]
                    raise A2AError(
                        f"peer returned HTTP {response.status_code}"
                        + (f": {detail}" if detail else ""),
                        status=response.status_code,
                    )
                # A server that does not know this method answers with JSON (usually a
                # -32601 error) instead of an event stream. That is a method-name
                # mismatch, not a transport failure, so let the caller try the next.
                content_type = (response.headers.get("content-type") or "").lower()
                if "text/event-stream" not in content_type:
                    detail = (await response.aread()).decode("utf-8", "replace")[:200]
                    raise _MethodUnsupported(
                        f"{method}: peer did not open an event stream "
                        f"(content-type={content_type or 'none'}) {detail}".strip()
                    )
                async for line in response.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    raw = line[5:].strip()
                    if not raw or raw == "[DONE]":
                        continue
                    try:
                        frame = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(frame, dict) and "error" in frame:
                        self._raise_rpc_error(response, frame["error"])
                    if isinstance(frame, dict) and "result" in frame:
                        frame = frame["result"]
                    if not isinstance(frame, dict):
                        continue

                    if not accepted:
                        accepted = True
                        yield {"kind": "accepted"}

                    task_id = _task_id_of(frame) or task_id
                    # Prefer the artifact member: when a frame carries both an
                    # artifact and a status, the artifact holds the payload text
                    # and the status parts are incidental.
                    if isinstance(frame.get("artifactUpdate"), dict):
                        member = frame["artifactUpdate"]
                    elif isinstance(frame.get("task"), dict):
                        member = frame["task"]
                    elif isinstance(frame.get("statusUpdate"), dict):
                        member = frame["statusUpdate"]
                    else:
                        member = frame
                    context = _context_id_of(frame)
                    if context:
                        yield {"kind": "context", "context_id": context}

                    state = _state_of(member)
                    if state and state != last_state:
                        last_state = state
                        yield {"kind": "status", "state": state,
                               "status": self.relay_status(state), "task_id": task_id}

                    texts = _extract_texts(member)
                    fresh = [t for t in texts if t not in collected]
                    for chunk in fresh:
                        collected.append(chunk)
                        yield {"kind": "artifact", "text": chunk, "task_id": task_id}

                    if state in TERMINAL_STATES:
                        text = "\n".join(collected).strip()
                        # Recover only when nothing reached the operator: an empty
                        # stream, or a marker-only reply. The task record is
                        # authoritative, and recovery never duplicates streamed text.
                        if task_id and not _has_visible_text(text):
                            # Recover when nothing visible arrived (an empty stream
                            # or a marker-only reply). The task record is authoritative.
                            try:
                                task = await self.get_task(task_id)
                            except Exception as exc:
                                task = {}
                                yield {"kind": "retrieve_failed", "error": str(exc)}
                            recovered = "\n".join(
                                t for t in _extract_texts(task) if t not in collected
                            ).strip()
                            if recovered:
                                collected.append(recovered)
                                text = "\n".join(collected).strip()
                                yield {"kind": "artifact", "text": recovered,
                                       "task_id": task_id, "retrieved": True}
                        yield {
                            "kind": "terminal", "state": state, "task_id": task_id,
                            "text": text,
                        }
                        return
        except A2AError:
            raise
        except (GeneratorExit, asyncio.CancelledError):
            # The consumer stopped reading (or the turn was cancelled). That is not
            # a transport failure and must not be rewritten into one.
            raise
        except Exception as exc:
            raise A2AError(f"A2A stream failed: {exc}") from exc

        # The stream closed without any terminal member: report what we have,
        # flagged as unresolved so nothing claims a clean completion.
        yield {
            "kind": "terminal", "state": last_state or "TASK_STATE_UNKNOWN",
            "task_id": task_id, "text": "\n".join(collected).strip(), "truncated": True,
        }

    @staticmethod
    def relay_status(state: str) -> str:
        """Map an A2A task state onto Relay's status vocabulary."""
        return {
            STATE_SUBMITTED: "working",
            STATE_WORKING: "working",
            STATE_INPUT_REQUIRED: "waiting",
            STATE_COMPLETED: "done",
            STATE_FAILED: "stopped",
            STATE_CANCELED: "stopped",
            STATE_REJECTED: "stopped",
        }.get(state, "working")

    async def cancel(self, task_id: str) -> dict:
        """``tasks/cancel`` for the stop button.

        The peer task id looks like ``task-<uuid>``; the canonical A2A method takes
        just the id, so both spellings are attempted.
        """
        if not task_id:
            raise A2AError("no active task to cancel", code="no_task")
        client = await self.client()
        bare = task_id[5:] if task_id.startswith("task-") else task_id
        last: Any = None
        for candidate in (task_id, bare):
            body = {
                "jsonrpc": "2.0", "id": f"cancel-{candidate}", "method": "tasks/cancel",
                "params": {"id": candidate, "taskId": candidate},
            }
            try:
                response = await client.post(
                    self.base_url,
                    headers=self._headers({"Content-Type": "application/json"}),
                    json=body,
                )
            except Exception as exc:
                last = A2AError(f"could not reach the A2A peer: {exc}")
                continue
            if response.status_code != 200:
                last = A2AError(
                    f"cancel returned HTTP {response.status_code}",
                    status=response.status_code,
                )
                continue
            payload = response.json()
            if "error" in payload:
                last = A2AError(
                    f"cancel rejected: {(payload['error'] or {}).get('message')}",
                    code=(payload["error"] or {}).get("code"),
                )
                continue
            return payload.get("result", {})
        if isinstance(last, A2AError):
            raise last
        raise A2AError("cancel failed")
