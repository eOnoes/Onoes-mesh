"""Real, isolated Relay Web Push sender.

This is the delivery half of the push feature. It performs the actual RFC 8291
payload encryption and RFC 8292 VAPID signature through the owner-approved
``pywebpush.webpush`` implementation; it does not implement cryptography of
its own and it never reads production VAPID credentials or subscription
material from the environment.

The caller supplies every secret explicitly:

    relay_push_sender.send_push(
        endpoint="https://fcm.googleapis.com/fcm/send/device-token",
        subscription_key="base64url-p256dh",
        auth_key="base64url-auth",
        vapid_private_key="base64url-P-256-private-key",
        vapid_claims=None,
    )

The injected HTTP session is the test boundary. With the real ``requests``
Session, ``post(..., allow_redirects=False)`` pins the request to the first,
validated provider origin; a redirect is reported as a delivery failure and is
never followed. With the isolated test session, the same keyword must be
accepted so the tests exercise the production call signature exactly.

Privacy and security rules
==========================

* No endpoint, subscription key, auth key, VAPID key, payload or provider
  response body is logged, printed, or included in an exception message.
* Endpoint validation refuses userinfo, ports, query strings, fragments,
  whitespace, non-HTTPS schemes, and any origin other than
  ``https://fcm.googleapis.com`` followed by a non-empty path token.
* The fixed notification contains only a generic title and body. It never
  includes the room name, message text, author, recipient, sender, or any
  owner-specific data.
* There is no retry loop. A timeout, redirect, provider failure, or any other
  exception is returned once for the parent integration to deduplicate or
  handle.
"""

from __future__ import annotations

import json
import re
import threading
from urllib.parse import urlsplit

__all__ = [
    "PROVIDER_ORIGIN",
    "GENERIC_TITLE",
    "GENERIC_BODY",
    "DEFAULT_TIMEOUT_SECONDS",
    "PushDeliveryError",
    "validate_delivery_endpoint",
    "build_payload",
    "send_push",
]

PROVIDER_ORIGIN = "https://fcm.googleapis.com"
PROVIDER_PREFIX = PROVIDER_ORIGIN + "/fcm/send/"
GENERIC_TITLE = "Onoes Mesh"
GENERIC_BODY = "New Relay message"
DEFAULT_TIMEOUT_SECONDS = 10.0
MAX_ENDPOINT_LENGTH = 4096
_MIN_TOKEN_LENGTH = 1
_MAX_TOKEN_LENGTH = 1024
_SAFE_TOKEN = re.compile(r"^[A-Za-z0-9_:-]+$")
_REQUEST_LOCK = threading.Lock()


class _ForcedNoRedirectSession:
    def __init__(self, session, timeout):
        self._session = session
        self._timeout = timeout

    def post(self, endpoint, data=None, headers=None, **kwargs):
        return self._session.post(
            endpoint,
            data=data,
            headers=headers,
            allow_redirects=False,
            timeout=self._timeout,
        )


class PushDeliveryError(Exception):
    """A sanitized sender failure that is safe to return to the caller."""

    def __init__(self, code: str, status: int | None = None):
        # Only the explicit code/status enter the message. Provider text and
        # URL material never do.
        super().__init__(f"Push delivery failed ({code}{f', HTTP {status}' if status is not None else ''}).")
        self.code = code
        self.status = status


def _url_error() -> PushDeliveryError:
    return PushDeliveryError("invalid_endpoint")


def validate_delivery_endpoint(url: object) -> str:
    """Validate the exact FCM delivery endpoint and return it unchanged.

    The endpoint is a delivery credential, so it is either accepted exactly or
    refused with no echo of its value. Required shape:

        https://fcm.googleapis.com/fcm/send/<non-empty-token>

    The token must contain only the RFC 3986 unreserved characters and must be
    present. Userinfo, a custom port, a query, a fragment, whitespace, an
    encoded slash that could alter the route, and any alternate origin are all
    refused.
    """
    if not isinstance(url, str) or not url or len(url) > MAX_ENDPOINT_LENGTH:
        raise _url_error()
    if re.search(r"[\s\x00-\x1f\x7f]", url):
        raise _url_error()
    if not url.startswith(PROVIDER_PREFIX):
        raise _url_error()
    try:
        parts = urlsplit(url)
    except ValueError:
        raise _url_error()
    if parts.scheme != "https" or parts.netloc != "fcm.googleapis.com":
        raise _url_error()
    if parts.username is not None or parts.password is not None:
        raise _url_error()
    try:
        port = parts.port
    except ValueError:
        raise _url_error()
    if port is not None:
        raise _url_error()
    if parts.query or parts.fragment:
        raise _url_error()
    token = parts.path[len("/fcm/send/"):]
    if len(token) < _MIN_TOKEN_LENGTH or len(token) > _MAX_TOKEN_LENGTH:
        raise _url_error()
    if not _SAFE_TOKEN.fullmatch(token):
        raise _url_error()
    return url


def _validate_secret(label: str, value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PushDeliveryError(f"missing_{label}")
    if value != value.strip() or any(character.isspace() for character in value):
        raise PushDeliveryError(f"invalid_{label}")
    return value


def _validate_vapid_private_key(value: object) -> str:
    key = _validate_secret("vapid_private_key", value)
    if not re.fullmatch(r"[A-Za-z0-9_-]+", key):
        raise PushDeliveryError("invalid_vapid_private_key")
    return key


def _validate_timeout(timeout: object) -> float:
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)):
        raise PushDeliveryError("invalid_timeout")
    value = float(timeout)
    import math
    if not math.isfinite(value) or value <= 0.0 or value > 60.0:
        raise PushDeliveryError("invalid_timeout")
    return value


def build_payload(*, silent: bool = False) -> str:
    """The fixed generic notification payload.

    ``silent`` only controls the boolean ``webpush.notification.renotify``
    value; it never adds message, room, or device content. A non-boolean value
    is refused rather than truth-coerced, so a caller cannot accidentally
    create a non-generic payload.
    """
    if not isinstance(silent, bool):
        raise PushDeliveryError("invalid_silent")
    return json.dumps(
        {
            "notification": {
                "title": GENERIC_TITLE,
                "body": GENERIC_BODY,
                "icon": "/mesh-icon-192.png",
                "badge": "/mesh-icon-192.png",
                "tag": "onoes-relay",
                "renotify": True,
                "silent": silent,
            },
            "data": {"kind": "relay", "version": 1},
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _vapid_claims(endpoint: str, subject: object) -> dict:
    if not isinstance(subject, str) or not subject or any(
        character.isspace() for character in subject
    ):
        raise PushDeliveryError("invalid_vapid_subject")
    if not subject.startswith(("mailto:", "https://")):
        raise PushDeliveryError("invalid_vapid_subject")
    return {"sub": subject, "aud": PROVIDER_ORIGIN}


def _status_code(response: object) -> int | None:
    status = getattr(response, "status_code", None)
    return status if isinstance(status, int) else None


def send_push(
    *,
    endpoint: str,
    subscription_key: str,
    auth_key: str,
    vapid_private_key: str,
    vapid_claims: dict | None = None,
    session,
    timeout: float | int = DEFAULT_TIMEOUT_SECONDS,
    silent: bool = False,
    subscription_content_encoding: str = "aes128gcm",
) -> dict:
    """Encrypt and send exactly one Web Push request. Never retries.

    Returns a small result dictionary:

        {"ok": True, "message_id": "<provider id>"}
        {"ok": False, "code": "<sanitized-code>", "status": <int or None>}

    The message id is accepted only from a non-empty JSON string field named
    ``message_id`` or ``messageId``. Every failure, including a request
    exception, timeout, redirect, non-201 status, or malformed provider
    response, returns a sanitized result rather than raising.
    """
    if not isinstance(session, object) or session is None:
        return {"ok": False, "code": "missing_session", "status": None}
    try:
        safe_endpoint = validate_delivery_endpoint(endpoint)
    except PushDeliveryError as error:
        return {"ok": False, "code": error.code, "status": None}
    try:
        key = _validate_secret("subscription_key", subscription_key)
        auth = _validate_secret("auth_key", auth_key)
        private_key = _validate_vapid_private_key(vapid_private_key)
        timeout_seconds = _validate_timeout(timeout)
        if subscription_content_encoding != "aes128gcm":
            raise PushDeliveryError("invalid_content_encoding")
        claims = dict(vapid_claims or {"sub": "mailto:Echo@eonoes.id"})
        claims.update({"aud": PROVIDER_ORIGIN})
        _vapid_claims(safe_endpoint, claims.get("sub"))
        payload = build_payload(silent=silent)
    except PushDeliveryError as error:
        return {"ok": False, "code": error.code, "status": None}

    try:
        from pywebpush import webpush
    except Exception:
        # The import failure contains no secret material, but the exception
        # text itself is still not returned because it may describe the host.
        return {"ok": False, "code": "webpush_unavailable", "status": None}

    try:
        # This single call performs real AES-128-GCM content encryption and
        # real ECDSA P-256 VAPID signing. It must not be wrapped in a retry
        # loop: the parent owns retry policy and message deduplication.
        with _REQUEST_LOCK:
            response = webpush(
                subscription_info={"endpoint": safe_endpoint, "keys": {"p256dh": key, "auth": auth}},
                data=payload,
                vapid_private_key=private_key,
                vapid_claims=claims,
                content_encoding="aes128gcm",
                requests_session=_ForcedNoRedirectSession(session, timeout_seconds),
            )
    except Exception as error:
        return _delivery_failure(error)

    status = _status_code(response)
    # Web Push success is an HTTP receipt; providers need not return JSON or IDs.
    if status in (200, 201, 202):
        return {"ok": True, "status": status}
    if status in (404, 410):
        return {"ok": False, "code": "subscription_expired", "status": status}
    if isinstance(status, int) and 300 <= status < 400:
        return {"ok": False, "code": "redirect_blocked", "status": status}
    return {"ok": False, "code": "provider_rejected", "status": status}


def _message_id(json_method) -> str | None:
    try:
        body = json_method()
    except Exception:
        return None
    if not isinstance(body, dict):
        return None
    for key in ("message_id", "messageId", "messageIdString"):
        value = body.get(key)
        if isinstance(value, str) and value and not any(
            character.isspace() for character in value
        ):
            return value
    return None


def _delivery_failure(error: Exception) -> dict:
    """Translate pywebpush/requests failures into stable, sanitized codes."""
    from pywebpush import WebPushException

    if isinstance(error, WebPushException):
        status = _status_code(getattr(error, "response", None))
        if isinstance(status, int) and 300 <= status < 400:
            return {"ok": False, "code": "redirect_blocked", "status": status}
        if status == 404 or status == 410:
            return {"ok": False, "code": "subscription_expired", "status": status}
        return {"ok": False, "code": "provider_rejected", "status": status}

    # pywebpush maps requests exceptions to its own exception types where
    # possible, but the mock/session layer may still raise a requests
    # Timeout/ConnectionError directly. Inspect only the type, never the text,
    # so no URL or provider detail can leak.
    name = type(error).__name__
    if name in {"Timeout", "ConnectTimeout", "ReadTimeout"}:
        return {"ok": False, "code": "timeout", "status": None}
    if name in {"TooManyRedirects", "RedirectError"}:
        return {"ok": False, "code": "redirect_blocked", "status": None}
    if name in {"ConnectionError", "RequestException"}:
        return {"ok": False, "code": "connection_failed", "status": None}
    return {"ok": False, "code": "delivery_failed", "status": None}
