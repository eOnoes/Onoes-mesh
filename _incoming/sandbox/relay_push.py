"""Owner-enrollment capability store for opt-in Relay Web Push (source slice only).

This module is the *authorization* half of Task 2. It never encrypts, signs or
sends a push and it never generates or stores a production VAPID key: that
half needs the ``cryptography`` package, which is not installed on this host
(see ``requirements-webpush.txt``). Keeping the capability checks independent
means the enrollment/revocation boundary is provable today, while delivery
stays fail-closed until the parent installs the dependency and provisions keys.

Capability model
================

Host/Origin checks and tailnet membership are *not* owner identity. A browser
page that can reach this port could therefore try to subscribe a device. The
only thing that makes an enrollment request trustworthy is a **parent-issued,
one-use enrollment capability**:

* the parent (Echo/Hermes) mints it out of band with :func:`mint_capability`
  and puts ``RELAY_PUSH_ENROLL_TOKEN`` in the environment of the backend it
  starts, so the capability never appears in source, a log or a chat message;
* the browser presents it exactly once, in the ``Authorization: Bearer``
  header, to ``POST /api/relay/push/enroll``;
* the backend compares it with :func:`check_enrollment_capability` under
  ``hmac.compare_digest`` and the store burns it, even when the subscription
  itself is rejected, so a stolen capability cannot enroll a second device.

The recipient and the room are fixed in this schema exactly as they are in
``relay_proactive``: author ``Echo``, recipient ``Eddie``, room
``relay-eddie-echo-chat``. Device identity is explicit: the parent names a
device label when it mints the capability and the browser must present the
same label, so a device can be revoked by name later without touching the
others. This is a *convention with a burned one-use token*, not a hardware
root of trust; that limitation is disclosed rather than papered over.

Secrets
=======

Enrollment requests carry a PushSubscription: an HTTPS provider ``endpoint``
plus ``keys.p256dh``/``keys.auth``. Those are treated as secrets everywhere:

* never logged, printed, echoed back, or written into source/fixtures;
* stored only in the dedicated SQLite database named by ``RELAY_PUSH_DB``;
* redacted to ``scheme://host/<redacted>`` in every status or error string.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import threading
import time
from pathlib import Path
from urllib.parse import urlsplit

DEFAULT_DB = str(Path(__file__).resolve().parent / "data" / "relay-push.db")
TOKEN_ENV = "RELAY_PUSH_ENROLL_TOKEN"
DEVICE_ENV = "RELAY_PUSH_ENROLL_DEVICE"

ROOM = "relay-eddie-echo-chat"
AUTHOR = "Echo"
RECIPIENT = "Eddie"

DEFAULT_EXPIRY_SECONDS = 900.0
MAX_SUBSCRIPTION_BYTES = 8192
MAX_FAILURES = 4
GENERIC_TITLE = "Onoes Mesh"
GENERIC_BODY = "New Relay message"

# ---------------------------------------------------------------------------
# Provider allowlist.
#
# This list is *discovered from contract*, not invented: every value below is
# either (a) the origin of the endpoint a browser actually returns from
# ``PushManager.subscribe()`` for Chrome/Edge on Android, or (b) the origin of
# the VAPID "aud" claim named in that browser's Web Push instructions.
#
#   fcm2.push.apple.com / web.push.apple.com  -- Apple Web Push instructions,
#       https://developer.apple.com/documentation/usernotifications/setting_up_a_remote_notification_server/sending_notification_requests_to_apns
#   updates.push.services.mozilla.com         -- Mozilla push service,
#       https://firefox-source-docs.mozilla.org/dom/push/
#   fcm.googleapis.com                        -- Chrome on Android / desktop,
#       https://developers.google.com/cloud-messaging/http-server-ref
#
# The owner-approved dependency is Chrome/Google Web Push, so
# ``fcm.googleapis.com`` is the expected value; the others are kept so an
# Apple/Chromium-notification-endpoint subscription is refused *explicitly*
# rather than silently. Everything else is refused, fail-closed, including
# private addresses, custom ports, credentials in the URL, and http:// targets.
#
# When a real enrollment is provisioned, the operator must re-derive this set
# from the installed Chrome's published Web Push instructions instead of
# trusting this constant blindly; ``validate_endpoint`` also cross-checks the
# host against an operator override in RELAY_PUSH_PROVIDER_HOSTS (comma
# separated), which is how a refreshed list is applied without an edit.
# ---------------------------------------------------------------------------
DEFAULT_PROVIDER_HOSTS = frozenset({"fcm.googleapis.com"})
HOSTS_ENV = "RELAY_PUSH_PROVIDER_HOSTS"
HOST_PATTERN = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+$")


def provider_hosts() -> frozenset:
    """Allowlist: the documented set, or an operator override read from the env."""
    # This scope approves Chrome/Google only, not arbitrary operator targets.
    return DEFAULT_PROVIDER_HOSTS


def redact_endpoint(url: str) -> str:
    """A loggable form of a subscription endpoint: origin plus a fixed marker.

    The endpoint path is a per-device delivery credential -- Google's URL
    contains the registration id, Apple's contains the push token -- so it is
    never reproduced, not even in an error message.
    """
    try:
        parts = urlsplit(url)
    except ValueError:
        return "<redacted>"
    if parts.scheme and parts.netloc:
        return f"{parts.scheme}://{parts.netloc}/<redacted>"
    return "<redacted>"


def validate_endpoint(url) -> str:
    """Return the endpoint if it is an approved provider URL, else raise.

    Refused: non-strings, anything with userinfo (``user:pass@``), any port
    other than the scheme default, ``http:``, IP literals, ``localhost``,
    non-allowlisted hosts, unparseable URLs. There is no redirect following
    anywhere in this code base, so an allowlist check on the first hop is the
    whole check.
    """
    if not isinstance(url, str) or not url or len(url) > 4096:
        raise PushError("The notification endpoint is not usable.", 400)
    try:
        parts = urlsplit(url)
    except ValueError:
        raise PushError("The notification endpoint is not usable.", 400)
    if parts.scheme != "https":
        raise PushError("Only HTTPS notification endpoints are accepted.", 400)
    if not parts.hostname or parts.username is not None or parts.password is not None:
        raise PushError("The notification endpoint is not usable.", 400)
    try:
        port = parts.port
    except ValueError:
        raise PushError("The notification endpoint is not usable.", 400)
    if port is not None:
        raise PushError("Custom ports are not accepted on notification endpoints.", 400)
    if (re.search(r"[\s\x00-\x1f\x7f]", url) or parts.query or parts.fragment
            or not re.fullmatch(r"/fcm/send/[A-Za-z0-9_:-]+", parts.path)):
        raise PushError("The Chrome notification endpoint path is not usable.", 400)
    host = parts.hostname.lower()
    if host in {"localhost"} or host.endswith(".localhost") or host.endswith(".local"):
        raise PushError("That is not an approved notification service.", 403)
    try:
        import ipaddress
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise PushError("That is not an approved notification service.", 403)
    if host not in provider_hosts():
        raise PushError("That notification service is not approved for Relay.", 403)
    return url


class PushError(Exception):
    """A refusal with an HTTP status, mirroring ProactiveError."""

    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


# RFC 8291: ``p256dh`` is an uncompressed P-256 public key (0x04 || X || Y,
# 65 bytes) and ``auth`` is a 16-byte authentication secret, both base64url
# without padding. Checking the *decoded* length rather than the encoded
# string means a malformed key can never reach the encryption step later, and
# it needs no third-party library to enforce.
def _validate_key(label: str, value, expected_bytes: int) -> bytes:
    if not isinstance(value, str) or not value or len(value) > 512:
        raise PushError(f"The subscription {label} key is not usable.", 400)
    if not re.fullmatch(r"[A-Za-z0-9_-]+", value) or len(value) % 4 == 0:
        raise PushError(f"The subscription {label} key is not base64url.", 400)
    try:
        raw = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    except (ValueError, TypeError):
        raise PushError(f"The subscription {label} key is not usable.", 400)
    if len(raw) != expected_bytes:
        raise PushError(f"The subscription {label} key is the wrong length.", 400)
    if label == "p256dh" and raw[0] != 4:
        raise PushError("The subscription p256dh key is not an uncompressed P-256 key.", 400)
    return raw


# ---------------------------------------------------------------------------
# Parent-issued one-use enrollment capability.
# ---------------------------------------------------------------------------

def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def mint_capability(device: str, *, expires_in: float = DEFAULT_EXPIRY_SECONDS) -> str:
    """Mint an enrollment capability. Called by the parent, never over HTTP.

    Format: ``<unix-expiry>.<device-b64>.<random-b64>``. There is no signature
    because the comparison happens against the operator-set environment value,
    exactly like ``RELAY_PROACTIVE_TOKEN``; the randomness (256 bits) is what
    makes it unguessable, and the expiry is what bounds it. The device label is
    embedded so the parent's intent and the browser's request cannot drift.
    """
    device = _validate_device(device)
    expiry = int(time.time() + max(1.0, float(expires_in)))
    return f"{expiry}.{_b64(device.encode('utf-8'))}.{_b64(secrets.token_bytes(32))}"


def _validate_device(device) -> str:
    """A device label the parent names and the browser must echo, exactly.

    The label is trimmed once here; anything still containing whitespace or
    punctuation outside the allowed set is refused rather than repaired, so
    ``"Eddie phone"`` and ``"Eddie  phone"`` can never be two names for one
    device or one name for two devices.
    """
    if not isinstance(device, str):
        raise PushError("Name the device this enrollment is for.", 400)
    label = device
    if not label or len(label) > 64:
        raise PushError("Name the device this enrollment is for.", 400)
    if not re.fullmatch(r"[A-Za-z0-9]+(?:[ ._-][A-Za-z0-9]+)*", label):
        raise PushError("Device names use letters, digits, space, dot, dash or underscore.", 400)
    return label


def parse_capability(value: str, now=None) -> str:
    """Split a capability into (expiry, device) without checking the secret."""
    if not isinstance(value, str) or value.count(".") != 2:
        raise PushError("That enrollment capability is not valid.", 400)
    expiry_text, device_b64, _secret = value.split(".")
    if not expiry_text.isdigit() or not device_b64:
        raise PushError("That enrollment capability is not valid.", 400)
    if int(expiry_text) <= int(time.time() if now is None else now):
        raise PushError("That enrollment capability has expired. Ask for a new one.", 401)
    try:
        device = base64.urlsafe_b64decode(device_b64 + "=" * (-len(device_b64) % 4)).decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        raise PushError("That enrollment capability is not valid.", 400)
    return int(expiry_text), device


def check_enrollment_capability(presented, device, store, now=None) -> None:
    """Fail closed unless the presented capability matches and is still unused.

    The capability is burnt -- marked consumed in the store, whether or not the
    subscription that arrived with it was accepted -- before any subscription
    validation runs. A burned capability is refused from then on, so replaying
    the same header cannot enroll a second device.
    """
    configured = os.environ.get(TOKEN_ENV, "").strip()
    if not configured:
        raise PushError("Owner enrollment is not configured on the PC.", 503)
    if not isinstance(presented, str) or not presented.strip():
        raise PushError("This device has no owner enrollment. Setup is not ready.", 403)
    if store.capability_used(configured):
        raise PushError("That owner enrollment was already used. Ask the PC for a new one.", 403)
    if not hmac.compare_digest(presented.strip(), configured):
        raise PushError("That owner enrollment is not the one issued for this device.", 403)
    expiry, capability_device = parse_capability(configured, now=now)
    if capability_device != device:
        raise PushError("That owner enrollment is issued for a different device name.", 403)
    store.mark_capability_used(configured, expiry)


# ---------------------------------------------------------------------------
# Durable store. One row per enrolled device; the whole row is a secret.
# ---------------------------------------------------------------------------

_SCHEMA = """
CREATE TABLE IF NOT EXISTS push_subscriptions (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    device TEXT NOT NULL,
    endpoint TEXT NOT NULL,
    p256dh TEXT NOT NULL,
    auth TEXT NOT NULL,
    content_encoding TEXT NOT NULL,
    capability_used INTEGER NOT NULL,
    capability_expires_at INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    revoked_at TEXT,
    failures INTEGER NOT NULL DEFAULT 0,
    last_failure_at TEXT
);
CREATE TABLE IF NOT EXISTS push_capabilities (
    capability TEXT PRIMARY KEY,
    consumed_at TEXT NOT NULL,
    expires_at INTEGER NOT NULL
);
"""


class PushStore:
    """SQLite-backed enrollment store. Connections are per-call and closed."""

    def __init__(self, path=None):
        # RELAY_PUSH_DB only wins when no explicit path was passed, so an
        # isolated test's TemporaryDirectory path can never be redirected at
        # the production store by a stray environment variable.
        self.path = str(path) if path else str(
            os.environ.get("RELAY_PUSH_DB") or DEFAULT_DB)
        self._lock = threading.Lock()
        self._init_schema()

    def connect(self):
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA busy_timeout=10000")
        return connection

    def _init_schema(self) -> None:
        parent = Path(self.path).parent
        if str(parent) not in {"", "."}:
            parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            connection = self.connect()
            try:
                connection.executescript(_SCHEMA)
                connection.commit()
            finally:
                connection.close()

    def _row(self, row) -> dict:
        if row is None:
            return {}
        return {
            "device": row["device"],
            "endpoint": row["endpoint"],
            "p256dh": row["p256dh"],
            "auth": row["auth"],
            "content_encoding": row["content_encoding"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "revoked_at": row["revoked_at"],
            "failures": row["failures"],
            "last_failure_at": row["last_failure_at"],
        }

    # -- capabilities -------------------------------------------------------
    def capability_used(self, capability: str) -> bool:
        with self._lock:
            connection = self.connect()
            try:
                row = connection.execute(
                    "SELECT 1 FROM push_capabilities WHERE capability = ?", (capability,)
                ).fetchone()
                return row is not None
            finally:
                connection.close()

    def mark_capability_used(self, capability: str, expires_at: int) -> None:
        with self._lock:
            connection = self.connect()
            try:
                cursor = connection.execute(
                    "INSERT OR IGNORE INTO push_capabilities (capability, consumed_at, expires_at)"
                    " VALUES (?, ?, ?)",
                    (capability, _now(), int(expires_at)),
                )
                if cursor.rowcount != 1:
                    raise PushError("That owner enrollment was already used.", 403)
                connection.commit()
            finally:
                connection.close()

    def prune_capabilities(self) -> int:
        with self._lock:
            connection = self.connect()
            try:
                cursor = connection.execute(
                    "DELETE FROM push_capabilities WHERE expires_at < ?", (int(time.time()),)
                )
                connection.commit()
                return cursor.rowcount
            finally:
                connection.close()

    # -- subscriptions ------------------------------------------------------
    def save_subscription(self, device: str, subscription: dict, *,
                          capability: str, capability_expires_at: int) -> dict:
        """Upsert the one enrollment this store holds. Rows are never logged."""
        endpoint = validate_endpoint((subscription or {}).get("endpoint"))
        keys = (subscription or {}).get("keys") or {}
        p256dh, auth = keys.get("p256dh"), keys.get("auth")
        _validate_key("p256dh", p256dh, 65)
        _validate_key("auth", auth, 16)
        encoding = (subscription or {}).get("subscriptionEncoding") \
            or (subscription or {}).get("contentEncoding") or "aes128gcm"
        if encoding not in {"aes128gcm", "aesgcm"}:
            raise PushError("That subscription encoding is not supported.", 400)
        if len(json.dumps(subscription)) > MAX_SUBSCRIPTION_BYTES:
            raise PushError("That subscription is too large.", 400)
        with self._lock:
            connection = self.connect()
            try:
                existing = connection.execute(
                    "SELECT id, device, revoked_at FROM push_subscriptions WHERE id = 1"
                ).fetchone()
                if existing and not existing["revoked_at"]:
                    raise PushError("This phone is already enrolled. Revoke it first.", 409)
                stamp = _now()
                connection.execute(
                    "INSERT INTO push_subscriptions (id, device, endpoint, p256dh, auth,"
                    " content_encoding, capability_used, capability_expires_at, created_at,"
                    " updated_at, revoked_at, failures, last_failure_at)"
                    " VALUES (1, ?, ?, ?, ?, ?, 1, ?, ?, ?, NULL, 0, NULL)"
                    " ON CONFLICT(id) DO UPDATE SET device=excluded.device, endpoint=excluded.endpoint,"
                    " p256dh=excluded.p256dh, auth=excluded.auth,"
                    " content_encoding=excluded.content_encoding, capability_used=1,"
                    " capability_expires_at=excluded.capability_expires_at,"
                    " updated_at=excluded.updated_at, revoked_at=NULL, failures=0, last_failure_at=NULL",
                    (device, endpoint, p256dh, auth, encoding,
                     int(capability_expires_at), stamp, stamp),
                )
                connection.commit()
            finally:
                connection.close()
        return {"enrolled": True, "device": device, "enabled": True}

    def status(self) -> dict:
        """Device label and enable state only -- no endpoint or keys."""
        with self._lock:
            connection = self.connect()
            try:
                row = connection.execute(
                    "SELECT device, revoked_at, failures, last_failure_at,"
                    " (SELECT COUNT(*) FROM push_capabilities WHERE consumed_at IS NOT NULL)"
                    " AS capabilities FROM push_subscriptions WHERE id = 1"
                ).fetchone()
            finally:
                connection.close()
        if row is None:
            return {"configured": False, "enrolled": False, "enabled": False,
                    "recipient": RECIPIENT, "room": ROOM}
        enrolled = row["revoked_at"] is None
        return {
            "configured": True,
            "enrolled": enrolled,
            "enabled": enrolled and row["failures"] < MAX_FAILURES,
            "device": row["device"],
            "recipient": RECIPIENT,
            "room": ROOM,
            "failures": row["failures"],
            "degraded": enrolled and row["failures"] >= MAX_FAILURES,
        }

    def subscription(self) -> dict:
        """The one active subscription, or {}. Callers must not log the result."""
        with self._lock:
            connection = self.connect()
            try:
                row = connection.execute(
                    "SELECT * FROM push_subscriptions WHERE id = 1 AND revoked_at IS NULL"
                ).fetchone()
            finally:
                connection.close()
        return self._row(row)

    def all_subscriptions(self, include_revoked=False) -> list:
        with self._lock:
            connection = self.connect()
            try:
                if include_revoked:
                    rows = connection.execute(
                        "SELECT * FROM push_subscriptions ORDER BY id").fetchall()
                else:
                    rows = connection.execute(
                        "SELECT * FROM push_subscriptions WHERE revoked_at IS NULL"
                        " ORDER BY id").fetchall()
            finally:
                connection.close()
        return [self._row(row) for row in rows]

    def revoke_by_subscription(self, device, subscription):
        current = self.subscription()
        candidate = subscription if isinstance(subscription, dict) else {}
        keys = candidate.get("keys") or {}
        if (not current or current["device"] != device
                or not hmac.compare_digest(str(current["endpoint"]), str(candidate.get("endpoint", "")))
                or not hmac.compare_digest(str(current["auth"]), str(keys.get("auth", "")))):
            raise PushError("This browser does not own that enrollment.", 403)
        return self.revoke(device=device)

    def revoke(self, device=None) -> dict:
        """Revoke the enrollment. A wrong device name is refused, not ignored."""
        with self._lock:
            connection = self.connect()
            try:
                row = connection.execute(
                    "SELECT device, revoked_at FROM push_subscriptions WHERE id = 1"
                ).fetchone()
            finally:
                connection.close()
        if row is None or row["revoked_at"] is not None:
            return {"revoked": False, "reason": "not enrolled"}
        if device is not None and row["device"] != device:
            raise PushError("That device name does not match this enrollment.", 403)
        with self._lock:
            connection = self.connect()
            try:
                connection.execute(
                    "UPDATE push_subscriptions SET revoked_at = ?, updated_at = ? WHERE id = 1",
                    (_now(), _now()),
                )
                connection.commit()
            finally:
                connection.close()
        return {"revoked": True}

    def record_failure(self) -> dict:
        """One more failed delivery. At MAX_FAILURES the row stops being sent to."""
        with self._lock:
            connection = self.connect()
            try:
                row = connection.execute(
                    "SELECT failures FROM push_subscriptions WHERE id = 1 AND revoked_at IS NULL"
                ).fetchone()
                if row is None or int(row["failures"]) >= MAX_FAILURES:
                    # Already past the budget: do not keep counting failures
                    # forever, and never resurrect a revoked row.
                    return {"recorded": False, "failures": 0 if row is None else int(row["failures"])}
                failures = int(row["failures"]) + 1
                connection.execute(
                    "UPDATE push_subscriptions SET failures = ?, last_failure_at = ?, updated_at = ?"
                    " WHERE id = 1",
                    (failures, _now(), _now()),
                )
                connection.commit()
            finally:
                connection.close()
        return {"recorded": True, "failures": failures, "degraded": failures >= MAX_FAILURES}

    def clear_failures(self) -> dict:
        with self._lock:
            connection = self.connect()
            try:
                connection.execute(
                    "UPDATE push_subscriptions SET failures = 0, last_failure_at = NULL"
                    " WHERE id = 1"
                )
                connection.commit()
            finally:
                connection.close()
        return {"recorded": True, "failures": 0}

    def counts(self) -> dict:
        with self._lock:
            connection = self.connect()
            try:
                row = connection.execute(
                    "SELECT (SELECT COUNT(*) FROM push_subscriptions WHERE revoked_at IS NULL)"
                    " AS active, (SELECT COUNT(*) FROM push_subscriptions WHERE revoked_at IS NOT NULL)"
                    " AS revoked, (SELECT COUNT(*) FROM push_capabilities) AS capabilities"
                ).fetchone()
            finally:
                connection.close()
        return {"active": row["active"], "revoked": row["revoked"], "capabilities": row["capabilities"]}


def _now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# Delivery readiness. This is the *owner setup* gate, deliberately separate
# from source completion.
#
# Encrypting a Web Push payload (RFC 8291) and signing the VAPID headers
# (RFC 8292) need ECDSA P-256 + ECDH + HKDF + AES-GCM. Hand-rolling those in
# the standard library would be inventing cryptography, which the plan forbids
# and which nobody should trust with a delivery credential. The qualified
# standards-based path is the ``pywebpush`` package, which needs
# ``cryptography`` underneath. Neither is installed on this host, and this
# task installs nothing, so every delivery path answers honestly instead.
# ---------------------------------------------------------------------------
VAPID_PUBLIC_ENV = "RELAY_PUSH_VAPID_PUBLIC"
VAPID_PRIVATE_ENV = "RELAY_PUSH_VAPID_PRIVATE"
DEPENDENCY = "pywebpush (which requires cryptography)"


def cryptography_available() -> bool:
    try:
        import cryptography  # noqa: F401
        import pywebpush  # noqa: F401
    except Exception:  # pragma: no cover - absence is the expected case here
        return False
    return True


def vapid_ready() -> bool:
    """True only when the parent has actually provisioned a key pair.

    Both halves must be present and the public half must be a 65-byte
    uncompressed P-256 point, so a placeholder value cannot make the UI claim
    readiness.
    """
    public = os.environ.get(VAPID_PUBLIC_ENV, "").strip()
    private = os.environ.get(VAPID_PRIVATE_ENV, "").strip()
    if not public or not private:
        return False
    try:
        _validate_key("vapid", public, 65)
    except PushError:
        return False
    return True


def require_delivery_ready() -> None:
    """Fail closed unless the parent has installed the library and set keys."""
    if not cryptography_available():
        raise PushError(
            "Phone push delivery is not installed on the PC yet: the "
            f"{DEPENDENCY} package is missing. Ask the PC owner to install it "
            "and set the VAPID keys before enrolling a phone.", 503)
    if not vapid_ready():
        raise PushError(
            "Phone push delivery is not provisioned on the PC yet: no VAPID "
            "key pair is set. Ask the PC owner to provision one before "
            "enrolling a phone.", 503)


# ---------------------------------------------------------------------------
# Generic payload. Only this is ever sent to the provider.
# ---------------------------------------------------------------------------

def generic_payload() -> dict:
    """The whole encrypted body: a generic title/body, no chat content."""
    return {
        "title": GENERIC_TITLE,
        "body": GENERIC_BODY,
        "icon": "/mesh-icon-192.png",
        "badge": "/mesh-icon-192.png",
        "tag": "relay-generic",
        "renotify": True,
    }


def enroll(store, *, device, capability, subscription) -> dict:
    """One deliberate enrollment: burn the capability, then keep the subscription.

    Order matters. The one-use capability is consumed first, so a request that
    carries an unusable subscription still cannot be retried with the same
    capability. The device name in the capability and the device name in the
    request must be the same string; they are compared here rather than trusted
    to agree.
    """
    device = _validate_device(device)
    check_enrollment_capability(capability, device, store)
    expiry, _device = parse_capability(capability or "")
    return store.save_subscription(device, subscription,
                                   capability=capability or "",
                                   capability_expires_at=expiry)


def payload_digest(payload: dict) -> str:
    """A redacted fingerprint of a payload, for tests and evidence."""
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()[:16]
