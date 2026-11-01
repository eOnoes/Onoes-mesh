"""Native Hermes API client for Relay: the Runs API plus native session resources.

This replaces the old ``/v1/chat/completions`` shim. Two things change as a result:

1. **The agent owns the transcript.** Runs are submitted with a stable
   ``session_id``, so Hermes persists the conversation in its own session store.
   Relay stops shipping a rolling window of history as prose, which is what
   duplicated and truncated context before. The same session is visible to the
   Hermes Desktop app and to any other channel, which is what makes Relay a
   first-class client rather than a parallel universe.
2. **Progress is real.** ``/v1/runs/{id}/events`` emits structured lifecycle
   events (tool start/complete, reasoning, subagents, approvals, terminal
   status), and stop/approve/steer are native operations rather than local
   guesses.

Capabilities are read from ``/v1/capabilities`` rather than assumed, so pointing
Relay at an older Hermes degrades honestly instead of silently misbehaving.

Note: ``POST /v1/runs`` accepts text only. Unlike ``/v1/chat/completions`` it has
no inline-image path, so image attachments are reported as unsupported on this
transport instead of being sent and silently dropped. A file/artifact transport
is a deliberate follow-up, not an accident.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import time
from typing import Any, AsyncIterator

import httpx

# Run statuses that mean "this run will not change again".
# Mirrors gateway/platforms/api_server_run_idempotency.TERMINAL_STATUSES in
# Hermes 0.21.0. Kept as a literal so Relay does not import Hermes' private
# modules; `unavailable` here means "the gateway cannot report on it".
TERMINAL_STATUSES = frozenset(
    {"completed", "failed", "cancelled", "interrupted", "expired", "unavailable"}
)

# Structured event names emitted by /v1/runs/{run_id}/events.
EVENT_MESSAGE_DELTA = "message.delta"
EVENT_TOOL_STARTED = "tool.started"
EVENT_TOOL_COMPLETED = "tool.completed"
EVENT_REASONING = "reasoning.available"
EVENT_SUBAGENT_START = "subagent.start"
EVENT_SUBAGENT_COMPLETE = "subagent.complete"
EVENT_APPROVAL_REQUEST = "approval.request"
EVENT_APPROVAL_RESPONDED = "approval.responded"
EVENT_RUN_STEERED = "run.steered"

# Approval choices accepted by POST /v1/runs/{run_id}/approval.
APPROVAL_CHOICES = ("once", "session", "always", "deny")

# Free-text event fields that may carry tool output; clipped before display.
MAX_FEED_PREVIEW = 400


class HermesError(RuntimeError):
    """A Hermes request failed in a way worth showing to the operator."""

    def __init__(self, message: str, *, status: int = 0, code: str = ""):
        super().__init__(message)
        self.status = status
        self.code = code

    @property
    def is_busy(self) -> bool:
        """True when the gateway is at its concurrency cap rather than broken."""
        return self.status == 429


class HermesUnsupported(HermesError):
    """The connected gateway does not advertise a capability Relay needs."""


def _clip(text: Any, limit: int = MAX_FEED_PREVIEW) -> str:
    flat = " ".join(str(text or "").split())
    return flat if len(flat) <= limit else flat[: limit - 1] + "…"


def _fmt_duration(value: Any) -> str:
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        return ""
    if seconds < 1:
        return f"{seconds * 1000:.0f}ms"
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes, rest = divmod(seconds, 60)
    return f"{int(minutes)}m{rest:04.1f}s"


def _decode_sse_data(payload: str) -> dict | None:
    """Decode one SSE ``data:`` payload into an object, or None if it is not JSON."""
    text = payload.strip()
    if not text or text == "[DONE]":
        return None
    try:
        decoded = json.loads(text)
    except json.JSONDecodeError:
        return None
    return decoded if isinstance(decoded, dict) else None


async def iter_sse_events(lines) -> "AsyncIterator[dict]":
    """Yield decoded JSON objects from an async stream of SSE lines."""
    async for line in lines:
        if not line.startswith("data:"):
            continue
        event = _decode_sse_data(line[5:])
        if event is not None:
            yield event


class HermesRunsClient:
    """Thin async client for one Hermes API server."""

    def __init__(
        self,
        base_url: str,
        api_key: str = "",
        *,
        model: str = "",
        session_key: str = "",
        connect_timeout: float = 10.0,
        read_timeout: float | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.session_key = session_key
        self._timeout = httpx.Timeout(
            read_timeout, connect=connect_timeout, write=30.0, pool=connect_timeout
        )
        self._client: httpx.AsyncClient | None = None
        self._capabilities: dict | None = None

    # ------------------------------------------------------------- plumbing --
    def _headers(self, extra: dict | None = None) -> dict:
        headers = {"Accept": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        if self.session_key:
            headers["X-Hermes-Session-Key"] = self.session_key
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
    def _raise_for_status(response: httpx.Response, what: str) -> None:
        if response.status_code < 400:
            return
        detail = ""
        code = ""
        try:
            body = response.json()
            if isinstance(body, dict):
                error = body.get("error")
                if isinstance(error, dict):
                    detail = str(error.get("message") or "")
                    code = str(error.get("code") or "")
                else:
                    detail = str(error or body.get("message") or "")
        except Exception:
            detail = _clip(response.text, 200)
        if response.status_code in (401, 403):
            raise HermesError(
                "auth rejected - check the agent's api_key_file matches API_SERVER_KEY",
                status=response.status_code,
                code=code or "unauthorized",
            )
        if response.status_code == 429:
            retry_after = response.headers.get("Retry-After", "")
            suffix = f" (retry after {retry_after}s)" if retry_after else ""
            raise HermesError(
                f"{what}: gateway is at its run limit{suffix}",
                status=429,
                code=code or "concurrency_limited",
            )
        raise HermesError(
            f"{what}: HTTP {response.status_code}{' - ' + detail if detail else ''}",
            status=response.status_code,
            code=code,
        )

    # --------------------------------------------------------- capabilities --
    async def capabilities(self, *, refresh: bool = False) -> dict:
        """Return the gateway's advertised capabilities (cached)."""
        if self._capabilities is not None and not refresh:
            return self._capabilities
        client = await self.client()
        response = await client.get(f"{self.base_url}/v1/capabilities", headers=self._headers())
        self._raise_for_status(response, "capabilities")
        payload = response.json()
        self._capabilities = payload if isinstance(payload, dict) else {}
        return self._capabilities

    @staticmethod
    def _features(capabilities: dict) -> dict:
        """Feature flags live under a ``features`` object in the advertised payload.

        Falls back to the top level so an older or flatter response still parses.
        """
        nested = capabilities.get("features")
        return nested if isinstance(nested, dict) else capabilities

    @staticmethod
    def _feature(capabilities: dict, name: str) -> bool:
        """True when a named feature flag is advertised as available.

        A flag may be a bare boolean or an object such as
        ``{"supported": true, "durable": true}``.
        """
        value = HermesRunsClient._features(capabilities).get(name)
        if isinstance(value, dict):
            return bool(value.get("supported"))
        return bool(value)

    async def require_runs_api(self) -> dict:
        """Assert the gateway advertises the Runs API; raise HermesUnsupported if not."""
        capabilities = await self.capabilities()
        missing = [
            name
            for name in ("run_submission", "run_status", "run_events_sse")
            if not self._feature(capabilities, name)
        ]
        if missing:
            raise HermesUnsupported(
                "this Hermes build does not advertise the Runs API "
                f"(missing: {', '.join(missing)}). Relay needs it for real "
                "streaming, stop, and approvals.",
                code="runs_api_unavailable",
            )
        return capabilities

    # ------------------------------------------------------------- sessions --
    async def session_exists(self, session_id: str) -> bool:
        client = await self.client()
        response = await client.get(
            f"{self.base_url}/api/sessions/{session_id}", headers=self._headers()
        )
        if response.status_code == 200:
            return True
        if response.status_code == 404:
            return False
        self._raise_for_status(response, "session lookup")
        return False

    async def ensure_session(self, session_id: str, *, title: str = "") -> bool:
        """Make sure a Hermes session row exists for ``session_id``.

        Returns True when the session exists afterwards. The gateway treats a
        duplicate title as an error (400), so an existing row or a title clash is
        never fatal here: the row is what matters, not its label.
        """
        if await self.session_exists(session_id):
            return True
        client = await self.client()
        response = await client.post(
            f"{self.base_url}/api/sessions",
            headers=self._headers({"Content-Type": "application/json"}),
            json={"id": session_id, **({"title": title} if title else {})},
        )
        if response.status_code in (200, 201):
            return True
        if response.status_code == 409:
            return True
        if response.status_code in (404, 405, 501):
            # Sessions API absent: /v1/runs still creates its own row on first use.
            return False
        if 400 <= response.status_code < 500:
            # Most likely "title already in use" - retry unlabelled, then accept
            # whatever the gateway decides: the run itself is what matters.
            retry = await client.post(
                f"{self.base_url}/api/sessions",
                headers=self._headers({"Content-Type": "application/json"}),
                json={"id": session_id},
            )
            return retry.status_code < 400 or retry.status_code == 409
        self._raise_for_status(response, "session create")
        return True

    async def session_messages(self, session_id: str, *, limit: int = 50) -> list[dict]:
        client = await self.client()
        response = await client.get(
            f"{self.base_url}/api/sessions/{session_id}/messages",
            headers=self._headers(),
            params={"limit": limit, "order": "latest"},
        )
        self._raise_for_status(response, "session messages")
        payload = response.json()
        return payload.get("data") or []

    # ----------------------------------------------------------------- runs --
    async def submit_run(
        self,
        *,
        text: str,
        session_id: str,
        idempotency_key: str = "",
        model: str = "",
        instructions: str = "",
    ) -> dict:
        """Admit one run and return the 202 body ``{run_id, status, replayed}``."""
        payload: dict[str, Any] = {"input": text, "session_id": session_id}
        chosen_model = model or self.model
        if chosen_model:
            payload["model"] = chosen_model
        if instructions:
            payload["instructions"] = instructions
        headers = {"Content-Type": "application/json"}
        if idempotency_key:
            # Durable on the Hermes side, so a Relay restart + retry cannot
            # double-submit the same user message.
            headers["Idempotency-Key"] = idempotency_key
        client = await self.client()
        response = await client.post(
            f"{self.base_url}/v1/runs", headers=self._headers(headers), json=payload
        )
        self._raise_for_status(response, "run submit")
        body = response.json()
        if not isinstance(body, dict) or not body.get("run_id"):
            raise HermesError("run submit: gateway returned no run_id", code="malformed_response")
        return body

    async def run_status(self, run_id: str) -> dict:
        client = await self.client()
        response = await client.get(
            f"{self.base_url}/v1/runs/{run_id}", headers=self._headers()
        )
        if response.status_code == 404:
            raise HermesError(
                f"run {run_id} is not known to the gateway (it may have expired or "
                "the gateway restarted)",
                status=404,
                code="run_not_found",
            )
        self._raise_for_status(response, "run status")
        payload = response.json()
        return payload if isinstance(payload, dict) else {}

    async def stream_events(self, run_id: str) -> Any:
        """Async generator of decoded run events.

        Hermes closes the stream with a ``: stream closed`` comment when the run
        settles; the generator simply ends there.
        """
        client = await self.client()
        async with client.stream(
            "GET", f"{self.base_url}/v1/runs/{run_id}/events", headers=self._headers()
        ) as response:
            self._raise_for_status(response, "run events")
            async for event in iter_sse_events(response.aiter_lines()):
                yield event

    async def stop_run(self, run_id: str) -> dict:
        client = await self.client()
        response = await client.post(
            f"{self.base_url}/v1/runs/{run_id}/stop", headers=self._headers()
        )
        if response.status_code in (404, 409):
            # Already finished or never active here: terminal state wins.
            return {"run_id": run_id, "status": "already_settled"}
        self._raise_for_status(response, "run stop")
        return response.json()

    async def approve_run(self, run_id: str, *, choice: str, request_id: str = "") -> dict:
        if choice not in APPROVAL_CHOICES:
            raise ValueError(f"invalid approval choice: {choice}")
        body: dict[str, Any] = {"choice": choice}
        if request_id:
            body["request_id"] = request_id
        client = await self.client()
        response = await client.post(
            f"{self.base_url}/v1/runs/{run_id}/approval",
            headers=self._headers({"Content-Type": "application/json"}),
            json=body,
        )
        self._raise_for_status(response, "run approval")
        return response.json()

    async def steer_run(self, run_id: str, text: str) -> dict:
        client = await self.client()
        response = await client.post(
            f"{self.base_url}/v1/runs/{run_id}/steer",
            headers=self._headers({"Content-Type": "application/json"}),
            json={"input": text},
        )
        self._raise_for_status(response, "run steer")
        return response.json()

    async def wait_for_terminal(
        self, run_id: str, *, timeout: float = 15.0, interval: float = 0.75
    ) -> dict:
        """Poll a run until it reaches a terminal status or the timeout elapses."""
        deadline = time.monotonic() + timeout
        last: dict = {}
        while time.monotonic() < deadline:
            last = await self.run_status(run_id)
            if str(last.get("status") or "") in TERMINAL_STATUSES:
                return last
            await asyncio.sleep(interval)
        return last

    async def probe(self) -> dict:
        """Cheap readiness probe used by the heartbeat: capabilities + model list."""
        capabilities = await self.capabilities(refresh=True)
        client = await self.client()
        response = await client.get(f"{self.base_url}/v1/models", headers=self._headers())
        self._raise_for_status(response, "models")
        data = response.json().get("data") or []
        return {
            "capabilities": capabilities,
            "models": [str(item.get("id") or "") for item in data if isinstance(item, dict)],
        }


def split_attachments(
    text: str, attachments: list[dict], *, image_types: frozenset[str] | set[str]
) -> tuple[str, list[str]]:
    """Split attachments into text Relay can inline and images it must refuse.

    Returns ``(text_with_files_inlined, unsupported_image_names)``.
    ``POST /v1/runs`` has no image input, so image files are reported back to the
    operator rather than silently dropped.
    """
    body = text.strip()
    unsupported: list[str] = []
    blocks: list[str] = []
    for item in attachments:
        if item.get("type") in image_types:
            unsupported.append(str(item.get("name") or "image"))
            continue
        blocks.append(
            f"--- Attachment: {item['name']} ---\n{item.get('text', '')}\n--- End attachment ---"
        )
    if blocks:
        base = body or "Please review the attached files."
        body = base + "\n\n" + "\n\n".join(blocks)
    if not body:
        body = "Please review the attached files."
    return body, unsupported
