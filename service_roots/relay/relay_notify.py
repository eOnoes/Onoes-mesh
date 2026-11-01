"""The notification plane (Phase 2).

An internal event goes in one end and, at most, one user-visible notification comes out
the other. Three things sit in between, and they are deliberately separate:

    event --> policy (decide) --> inbox row --> channel dispatch

**Policy is a pure function of the category, the clock and what was recently sent.**
Keeping it pure is what makes exit tests 2.3 (quiet hours) and 2.4 (one event -> one
notification) testable without a phone, a push service or a clock manipulation: the
decision is a value, not a side effect.

The category table below implements `docs/notification-policy.md` rather than inventing
a second opinion. Where that document says **DECISION NEEDED**, the proposed default is
used and named as such, so the choice is visible rather than buried.

Two hard rules from the policy, both enforced here rather than left to callers:

1. **`digest` is never immediate.** A notification that fires when nothing is wrong
   trains the reader to ignore the ones that matter, so this is a property of the
   category, not a parameter.
2. **Break-through belongs to the category, not the sender.** An agent cannot promote
   its own message to urgent, so urgency is looked up, never accepted from a caller
   that wants attention.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import relay_db

#: The category table, transcribed from `docs/notification-policy.md`.
#:
#: `break_through` means "wakes you during quiet hours". `min_interval_s` is the rate
#: limit per conversation: repeats inside it aggregate into the previous notification
#: with a count instead of producing a new one.
#:
#: Rate-limit numbers are the **proposed defaults** the policy document lists, not
#: settled values -- the doc marks them DECISION NEEDED.
CATEGORIES: dict[str, dict] = {
    "approval": {"urgency": "immediate", "break_through": True,  "min_interval_s": 0},
    "waiting":  {"urgency": "immediate", "break_through": False, "min_interval_s": 900},
    "error":    {"urgency": "immediate", "break_through": True,  "min_interval_s": 300},
    "cost":     {"urgency": "immediate", "break_through": True,  "min_interval_s": 0},
    "digest":   {"urgency": "aggregate", "break_through": False, "min_interval_s": 3600},
}

#: Soft cost is the aggregate half of the `cost` category: a soft threshold is not worth
#: waking anyone, a hard one is. Modelled as an urgency override rather than a sixth
#: category so the policy table stays the single source of truth.
SOFT = "soft"

#: Human-readable labels, derived **only** from the category. A push or ntfy payload
#: may carry the event type (2.8), so a label that is a pure function of the category
#: leaks nothing beyond it. Anything that varies with the event -- an agent name, a
#: command, a path -- is content and must not appear here.
CATEGORY_LABELS: dict[str, str] = {
    "approval": "Approval needed",
    "waiting": "Waiting on you",
    "error": "Something failed",
    "cost": "Cost alert",
    "digest": "Work finished",
}

#: Quiet hours, local time, as [start, end) hours. **DECISION NEEDED** in the policy
#: document; 23:00-07:00 is the proposed default.
QUIET_START_HOUR = 23
QUIET_END_HOUR = 7


@dataclass
class Decision:
    """What the policy decided, as a value. Never performs anything itself."""
    action: str                      # deliver | defer | suppress | aggregate
    category: str
    urgency: str
    reason: str
    deliver_at: str | None = None
    aggregate_target: int | None = None

    def as_dict(self) -> dict:
        return {"action": self.action, "category": self.category,
                "urgency": self.urgency, "reason": self.reason,
                "deliver_at": self.deliver_at,
                "aggregate_target": self.aggregate_target}


def in_quiet_hours(now: datetime, *, start: int = QUIET_START_HOUR,
                   end: int = QUIET_END_HOUR) -> bool:
    """True when local time falls in the quiet window, wrapping midnight."""
    hour = now.hour
    if start == end:
        return False
    if start < end:
        return start <= hour < end
    return hour >= start or hour < end


def next_quiet_end(now: datetime, *, end: int = QUIET_END_HOUR) -> datetime:
    """The next moment quiet hours end, so a deferral has a real time attached."""
    candidate = now.replace(hour=end, minute=0, second=0, microsecond=0)
    if candidate <= now:
        candidate += timedelta(days=1)
    return candidate


def resolve_category(category: str, urgency: str | None = None) -> tuple[str, str, bool]:
    """Return `(category, urgency, break_through)` for a request.

    Raises on an unknown category rather than falling back to a default: a typo that
    silently became a `digest` would be a notification that never arrives, and nobody
    would ever find out why.
    """
    key = str(category or "").strip().lower()
    if key not in CATEGORIES:
        raise ValueError(f"unknown notification category {category!r}")
    spec = CATEGORIES[key]
    if key == "digest":
        # Hard rule 1: the category's urgency is not negotiable.
        return key, "aggregate", spec["break_through"]
    if key == "cost" and str(urgency or "").lower() == SOFT:
        return key, SOFT, False
    return key, spec["urgency"], spec["break_through"]


def decide(category: str, *, now: datetime | None = None, urgency: str | None = None,
           last_sent: datetime | None = None,
           aggregate_target: int | None = None,
           quiet_hours: bool = True) -> Decision:
    """The whole policy, as a pure function.

    Order matters: dedup happens before this (it is a database constraint), repeats
    aggregate before quiet hours are considered, and quiet hours are the last word
    because a suppressed notification should still be *recorded* as suppressed.

    `quiet_hours` defaults to True so the pure policy matches `docs/notification-policy.md`
    and the policy tests stay meaningful. The operator has declined quiet hours, and that
    choice is applied at the wiring layer (`Notifier(quiet_hours=False)`) rather than by
    weakening the documented policy here.
    """
    key, resolved, breaks = resolve_category(category, urgency)
    now = now or datetime.now().astimezone()
    spec = CATEGORIES[key]

    limit = int(spec["min_interval_s"] or 0)
    if limit and last_sent is not None:
        elapsed = (now - last_sent).total_seconds()
        if elapsed < limit:
            if aggregate_target:
                return Decision("aggregate", key, resolved,
                                f"within the {limit}s rate limit; folded into the "
                                f"existing notification", aggregate_target=aggregate_target)
            return Decision("suppress", key, resolved,
                            f"within the {limit}s rate limit and nothing to fold into")

    if quiet_hours and in_quiet_hours(now) and not breaks:
        if spec["urgency"] == "aggregate" or resolved == SOFT:
            return Decision("suppress", key, resolved,
                            "quiet hours: aggregated into the next digest")
        end = next_quiet_end(now)
        return Decision("defer", key, resolved,
                        "quiet hours: delivered at the end of the window",
                        deliver_at=end.astimezone(timezone.utc)
                        .isoformat(timespec="seconds"))
    return Decision("deliver", key, resolved, "no rule suppressed it")


def transport_payload(note: dict) -> dict:
    """What may leave the host on Web Push or ntfy (2.8).

    Built by **allow-list**, not by removing fields. A deny-list is how content leaks
    the day somebody adds a field and forgets to add it to the removal list. The three
    keys here are the entire permitted surface, and they are identical for both
    transports because ntfy is the weaker channel and cannot be given *less* than the
    minimum while still being useful.

    Never present: message content, agent output, conversation titles, file names,
    paths. A notification reading "approval needed: delete D:\\Dev\\prod-db" has leaked
    the operation to a third party; "Approval needed" plus a link has not.
    """
    return {"type": note.get("category"), "id": note.get("id"),
            "link": note.get("deep_link") or ""}


def deep_link(agent_id: str, *, category: str, session_id: str | None = None,
              event_seq: int | None = None, note_id: int | None = None) -> str:
    """A link that lands on the exact thing, not the home screen (2.5).

    The target is carried in the query string so the client can honour it *after* the
    unlock gate rather than losing it at the gate -- landing on the conversation list
    is a failure of the notification, not of the user.
    """
    parts = [f"agent={agent_id}", f"n={note_id if note_id is not None else ''}"]
    if session_id:
        parts.append(f"c={session_id}")
    if category:
        parts.append(f"cat={category}")
    if event_seq is not None:
        parts.append(f"seq={event_seq}")
    return "/#" + "&".join(parts)


class Notifier:
    """Ties the store, the policy and the channels together.

    Channels are callables taking `(payload, note)` and returning a dict with at least
    `ok`. They are injected so the tests can substitute fakes -- including fakes that
    fail, which is how exit tests 2.2 and 2.5 are exercised without breaking anything
    real.
    """

    def __init__(self, store, *, channels: dict | None = None, quiet: bool = True):
        self.store = store
        self.channels = dict(channels or {})
        #: Operator preference. Quiet hours are a policy default, not a law: the operator
        #: declined them, so the wiring turns them off while `decide()` keeps the
        #: documented behaviour for anything that still asks for it.
        self.quiet = quiet

    # ------------------------------------------------------------ dispatch --
    def _dispatch(self, note: dict) -> dict:
        """Send on the non-inbox channels, in authority order. Never raises."""
        results: dict = {}
        payload = transport_payload(note)
        critical = note.get("urgency") == "immediate"
        for name in ("webpush", "ntfy"):
            send = self.channels.get(name)
            if send is None:
                results[name] = {"ok": False, "reason": "not configured"}
                continue
            if name == "ntfy" and not critical:
                # ntfy is the fallback for critical events; spending it on a digest
                # would make it a second, noisier copy of push.
                results[name] = {"ok": False, "reason": "not critical"}
                continue
            try:
                outcome = send(payload, note)
                results[name] = outcome if isinstance(outcome, dict) else {"ok": bool(outcome)}
            except Exception as exc:                      # a channel must not break the plane
                results[name] = {"ok": False, "reason": f"{type(exc).__name__}: {exc}"}
        return results

    def _delivered_somewhere(self, delivery: dict) -> bool:
        return any(info.get("ok") for info in delivery.values())

    # --------------------------------------------------------------- entry --
    def notify(self, agent_id: str, category: str, *, title: str, body: str = "",
               session_id: str | None = None, event_seq: int | None = None,
               dedup_key: str | None = None, urgency: str | None = None,
               deep_link_override: str | None = None,
               now: datetime | None = None) -> dict:
        """Record, decide, and (maybe) deliver. Always leaves the inbox with an answer.

        The inbox row is written *before* any channel is touched, so a crash or a hung
        channel still leaves the operator able to see that something happened. That is
        the ordering that makes "silence is never the failure mode" true rather than
        aspirational.
        """
        now = now or datetime.now().astimezone()
        key = str(dedup_key or (f"seq:{event_seq}" if event_seq is not None else "")).strip()

        # Dedup first, and as a *lookup* -- the unique index behind `dedup_key` is the
        # real guard. An earlier version inserted here as its check, which made the
        # real insert below collide with the row it had just created and silently
        # return that half-built row.
        if key:
            existing = self.store.notify_find(key)
            if existing:
                return {"ok": True, "duplicate": True, "id": existing["id"],
                        "category": existing["category"]}

        # Rate limit / aggregation against what was recently sent for this conversation.
        recent = self.store.notification_recent_for_dedup(
            category, session_id, agent_id=agent_id,
            since=(now - timedelta(hours=2))
            .astimezone(timezone.utc).isoformat(timespec="seconds"))
        last_sent = None
        target = None
        for row in recent:                       # newest first
            if row.get("delivered_at") or row.get("state") in ("inbox", "deferred"):
                try:
                    last_sent = datetime.fromisoformat(str(row["created_at"]))
                except ValueError:
                    last_sent = None
                if row["state"] in ("inbox", "deferred"):
                    target = int(row["id"])
                break

        decision = decide(category, now=now, urgency=urgency, last_sent=last_sent,
                          aggregate_target=target, quiet_hours=self.quiet)

        if decision.action == "aggregate" and decision.aggregate_target:
            bumped = self.store.notification_bump(decision.aggregate_target)
            return {"ok": True, "aggregated": True, "id": decision.aggregate_target,
                    "count": (bumped or {}).get("aggregate_count"),
                    "decision": decision.as_dict()}

        # `decide` may have coerced a category (digest -> aggregate, cost -> soft), so
        # the stored urgency is the resolved one, never the caller's wish.
        state = {"deliver": "inbox", "defer": "deferred",
                 "suppress": "suppressed"}[decision.action]
        try:
            note, _ = self.store.notify_record(
                agent_id, decision.category, urgency=decision.urgency, title=title,
                body=body, session_id=session_id,
                deep_link=deep_link_override or deep_link(
                    agent_id, category=decision.category, session_id=session_id,
                    event_seq=event_seq),
                event_seq=event_seq, dedup_key=key or None, state=state,
                deliver_at=decision.deliver_at)
        except Exception as exc:
            # The unique index is the authority. If two callers raced past the lookup,
            # the loser is a duplicate rather than an error.
            if key and "UNIQUE" in str(exc).upper():
                existing = self.store.notify_find(key)
                if existing:
                    return {"ok": True, "duplicate": True, "id": existing["id"],
                            "category": existing["category"]}
            raise

        # The link needs the row id, which only exists now -- so it is finalised here
        # rather than guessed before the insert. The first version built it early and
        # produced `n=`, a link that cannot identify the exact notification (2.5).
        if not deep_link_override:
            final = deep_link(agent_id, category=decision.category,
                              session_id=session_id, event_seq=event_seq,
                              note_id=note["id"])
            if final != note["deep_link"]:
                note = self.store.notification_set_link(note["id"], final) or note

        report = {"ok": True, "id": note["id"], "state": state,
                  "decision": decision.as_dict(), "delivery": {}}
        if decision.action != "deliver":
            return report

        delivery = self._dispatch(note)
        ok = self._delivered_somewhere(delivery)
        # `delivered_at` means "a channel accepted it", which is the same honest
        # ceiling used for sends: Relay cannot observe the phone's notification tray.
        self.store.notification_mark(note["id"], state="inbox", delivery=delivery,
                                     delivered=ok)
        report["delivery"] = delivery
        report["degraded"] = not ok
        return report


    def deliver_existing(self, note: dict) -> dict:
        """Dispatch a notification that quiet hours deferred and that is now due.

        Deliberately does **not** re-run the policy. The decision was made when the
        event happened; re-deciding at the end of the window would let the same rule
        suppress it a second time, and a deferral that can never complete is just a
        slower way of dropping the notification.
        """
        if note.get("state") != "deferred":
            return {"ok": False, "id": note.get("id"),
                    "reason": f"not deferred (state={note.get('state')!r})"}
        delivery = self._dispatch(note)
        ok = self._delivered_somewhere(delivery)
        self.store.notification_mark(note["id"], state="inbox", delivery=delivery,
                                     delivered=ok)
        return {"ok": True, "id": note["id"], "delivery": delivery,
                "degraded": not ok}


def summarise(rows: list[dict]) -> tuple[str, str]:
    """Turn suppressed notifications into one honest summary.

    The policy folds held-back events into "the next digest" rather than dropping them,
    so this reports *counts*, never the content that was held. It says what is held, not
    what it said: a digest is the one place a notification could quietly re-introduce
    the content that 2.8 keeps off the wire, and the body is inbox-only but there is no
    reason to rehearse the detail.

    Returns `(title, body)`.
    """
    if not rows:
        return "", ""
    counts: dict[str, int] = {}
    for row in rows:
        counts[str(row.get("category"))] = counts.get(str(row.get("category")), 0) + 1
    parts = []
    for category in ("approval", "waiting", "error", "cost", "digest"):
        if counts.get(category):
            label = CATEGORY_LABELS.get(category, category)
            parts.append(f"{counts[category]}× {label.lower()}")
    total = len(rows)
    title = f"{total} notification{'s' if total != 1 else ''} held"
    # "held back" rather than "held back by quiet hours": a suppressed row may have been
    # held by a rate limit instead, and claiming otherwise would be inventing a reason.
    body = "not delivered at the time: " + ", ".join(parts)
    return title, body


def format_aggregate(title: str, count: int) -> str:
    """`3 runs failed` rather than three notifications."""
    if count <= 1:
        return title
    return f"{title} (+{count - 1} more)"


def dumps(obj) -> str:
    return json.dumps(obj, separators=(",", ":"), default=str)


# `field` is imported for the dataclass defaults used by callers extending Decision.
_ = field
