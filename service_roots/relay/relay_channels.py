"""Notification channel adapters (Phase 2.6).

A channel is a callable `(payload, note) -> {"ok": bool, ...}`. That shape is why the
tests can substitute fakes -- including fakes that fail -- and why exit test 2.2 ("with
Web Push deliberately broken, a critical event still arrives by ntfy") is a unit test
rather than an outage rehearsal.

**Payload discipline lives in `relay_notify.transport_payload`, not here.** These
adapters receive the already-minimal payload and must not add to it. The one exception
is a title derived purely from the category, because the policy allows the event *type*
to cross and a notification reading only a URL is unusable.
"""
from __future__ import annotations

import ipaddress
import json
import socket
from pathlib import Path
from urllib.parse import urlsplit

import httpx

import relay_webpush as webpush
from relay_notify import CATEGORY_LABELS

#: ntfy priorities, mapped from the category's urgency. Derived, never content-derived.
_PRIORITY = {"immediate": "high", "aggregate": "low", "soft": "low"}

#: RFC 8030 requires TTL: how long the push service should keep trying. An approval that
#: arrives after the decision has been made is worse than none, so immediate messages get
#: a day (survives the phone being off overnight) and everything else gets an hour. The
#: inbox is the record of truth either way, so dropping one is not losing it.
_TTL = {"immediate": "86400"}
_TTL_DEFAULT = "3600"


def ntfy_channel(url: str, topic: str, *, token: str | None = None,
                 click_base: str | None = None, timeout: float = 10.0,
                 client: httpx.Client | None = None):
    """Build the ntfy channel callable.

    ntfy runs **outside the tailnet**, so it is the weaker channel and this is the
    adapter the 2.8 rule is really about. It therefore sends:

      * body  -- the deep link, nothing else
      * Title -- a label derived from the category
      * and no agent name, no conversation title, no command, no path

    `click_base` makes tapping the notification open Relay at the deep link. Without it
    the tap opens the ntfy app's own topic view, which satisfies nothing: a notification
    that lands you somewhere other than the thing it is about is a failure of the
    notification, not of the user (2.5). It must be Relay's own address as the *phone*
    sees it, which is why it is configuration rather than something derived.

    The topic is a shared secret: anyone who knows it can read the messages, which is
    why it is supplied from `.private/` rather than from `config.json`. That is also why
    this deployment runs with real auth on.

    The returned callable never raises. A channel that can break the notification plane
    is worse than a channel that reports its own failure.
    """
    endpoint = f"{str(url).rstrip('/')}/{topic}"
    base = str(click_base or "").rstrip("/")
    owned = client is None
    client = client or httpx.Client(timeout=timeout)

    def send(payload: dict, note: dict) -> dict:
        category = str(payload.get("type") or "")
        headers = {
            "Title": CATEGORY_LABELS.get(category, "Relay"),
            "Priority": _PRIORITY.get(str(note.get("urgency") or ""), "default"),
            "Tags": category or "relay",
        }
        link = str(payload.get("link") or "")
        if base and link:
            # Resolve the deep link against the address the phone uses, so the tap lands
            # on the exact approval rather than wherever the app happened to be.
            headers["Click"] = base + ("" if link.startswith("/") else "/") + link
        if token:
            headers["Authorization"] = f"Bearer {token}"
        try:
            response = client.post(endpoint, content=link, headers=headers)
        except Exception as exc:
            return {"ok": False, "reason": f"{type(exc).__name__}: {exc}"}
        ok = 200 <= int(getattr(response, "status_code", 0)) < 300
        return {"ok": ok, "status": getattr(response, "status_code", None),
                **({} if ok else {"reason": f"HTTP {getattr(response, 'status_code', '?')}"})}

    send.endpoint = endpoint          # for diagnostics and tests
    send.owns_client = owned
    return send


def validate_push_endpoint(url: str) -> str:
    """Check a subscription endpoint before Relay is willing to POST to it.

    Relay makes an outbound request to whatever URL a subscription carries, which makes
    this an SSRF boundary rather than a formality: an endpoint pointing at
    `http://127.0.0.1:8788/...` or a link-local address would turn the notification
    plane into a way to probe the operator's own network. Real push services are always
    https on a public host, so requiring exactly that costs nothing.

    A hostname that does not resolve, or resolves only to private addresses, is refused
    for the same reason. This is not a substitute for the gate -- it is what stops a
    stored subscription from becoming a capability.
    """
    parts = urlsplit(str(url))
    if parts.scheme != "https":
        raise ValueError("push endpoint must be https")
    if not parts.netloc or parts.username or parts.password:
        raise ValueError("push endpoint must be a plain absolute URL")
    host = parts.hostname or ""
    if not host:
        raise ValueError("push endpoint has no host")

    addresses: list[str] = []
    try:
        # A literal address needs no lookup; a name gets resolved so a DNS entry
        # pointing inward cannot slip past.
        addresses = [str(ipaddress.ip_address(host))]
    except ValueError:
        try:
            addresses = [info[4][0] for info in socket.getaddrinfo(host, None)]
        except OSError as exc:
            raise ValueError(f"push endpoint host does not resolve: {host}") from exc

    for address in addresses:
        ip = ipaddress.ip_address(address)
        if (ip.is_private or ip.is_loopback or ip.is_link_local
                or ip.is_reserved or ip.is_multicast or ip.is_unspecified):
            raise ValueError(f"push endpoint resolves to a non-public address: {address}")
    return str(url)


def webpush_channel(store, *, private_key, subject: str = "mailto:relay@localhost",
                    timeout: float = 10.0, client: httpx.Client | None = None):
    """Build the Web Push channel.

    Each device gets its own frame: RFC 8291 encryption is per subscription, because the
    whole point is that the push service cannot read it. The payload encrypted is the
    same allow-listed `{type, id, link}` the other transports get -- the transport being
    confidential does not make it a licence to put content in it.

    A subscription the push service reports as gone (404/410) is retired rather than
    retried forever, and recorded so health can show the device dropped off.
    """
    client = client or httpx.Client(timeout=timeout)

    def send(payload: dict, note: dict) -> dict:
        subscriptions = store.push_subscriptions(active_only=True)
        if not subscriptions:
            return {"ok": False, "reason": "no subscribed devices"}

        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        urgency = str(note.get("urgency") or "")
        ttl = _TTL.get(urgency, _TTL_DEFAULT)
        sent = 0
        failures: dict = {}

        for sub in subscriptions:
            try:
                encrypted = webpush.encrypt(body,
                                            webpush.b64url_decode(sub["p256dh"]),
                                            webpush.b64url_decode(sub["auth"]))
                headers = {
                    "Authorization": webpush.vapid_authorization(
                        sub["endpoint"], private_key, subject=subject),
                    "Content-Encoding": "aes128gcm",
                    "Content-Type": "application/octet-stream",
                    "TTL": ttl,
                    "Urgency": "high" if urgency == "immediate" else "normal",
                }
                response = client.post(sub["endpoint"], content=encrypted,
                                       headers=headers)
            except Exception as exc:
                failures[str(sub["id"])] = f"{type(exc).__name__}: {exc}"
                store.push_subscription_mark(sub["id"], ok=False)
                continue

            status = int(getattr(response, "status_code", 0))
            if 200 <= status < 300:
                sent += 1
                store.push_subscription_mark(sub["id"], ok=True)
                continue
            failures[str(sub["id"])] = f"HTTP {status}"
            store.push_subscription_mark(sub["id"], ok=False)
            if status in (404, 410):
                store.push_subscription_disable(sub["id"])

        result = {"ok": sent > 0, "sent": sent, "devices": len(subscriptions)}
        if failures:
            result["failures"] = failures
        if sent == 0 and failures:
            result["reason"] = "every device failed"
        return result

    send.kind = "webpush"
    return send


def load_vapid_key(root: Path, notify: dict) -> tuple[object | None, str]:
    """Read the VAPID signing key and subject from `.private/vapid.json`.

    The file holds the server's own identity, so it is a secret like any other. Absent
    or unreadable means the channel is not configured -- the same rule the ntfy adapter
    follows, and for the same reason: a channel that is *believed* configured and is not
    is how you come to trust silence.
    """
    secret = str((notify or {}).get("vapid_file") or ".private/vapid.json").strip()
    path = Path(secret) if Path(secret).is_absolute() else root / secret
    try:
        blob = json.loads(path.read_text(encoding="utf-8"))
        key = webpush.private_key_from_b64(str(blob["private_key"]))
    except Exception:
        return None, ""
    return key, str(blob.get("subject") or "mailto:relay@localhost")


def load_channels(config: dict, root: Path, *, store=None,
                  client: httpx.Client | None = None) -> dict:
    """Build the configured channels from config, honouring the secrets split.

    Nothing is enabled by default. A notification plane with no channel is honest about
    being unable to interrupt you; one that is *believed* to be configured and is not is
    how you end up trusting silence.
    """
    channels: dict = {}
    notify = (config or {}).get("notify") or {}

    push = notify.get("webpush") or {}
    if push.get("enabled") and store is not None:
        key, subject = load_vapid_key(root, push)
        if key is not None:
            channels["webpush"] = webpush_channel(store, private_key=key,
                                                  subject=subject, client=client)

    ntfy = notify.get("ntfy") or {}
    if ntfy.get("enabled"):
        topic = str(ntfy.get("topic") or "").strip()
        token = ""
        secret = str(ntfy.get("secret_file") or "").strip()
        if secret:
            path = (root / secret) if not Path(secret).is_absolute() else Path(secret)
            try:
                blob = json.loads(path.read_text(encoding="utf-8"))
                topic = topic or str(blob.get("topic") or "")
                token = str(blob.get("token") or "")
            except Exception:
                # A configured channel we cannot read is not configured -- and it must
                # not take Relay down with it.
                return channels
        if topic:
            channels["ntfy"] = ntfy_channel(
                str(ntfy.get("url") or "https://ntfy.sh"), topic, token=token or None,
                # Relay's address as the *phone* sees it, so a tapped notification opens
                # Relay at the deep link instead of the ntfy app's topic view.
                click_base=str(notify.get("public_url") or "").strip() or None,
                client=client)
    return channels
