# Relay integration and ordinary chat

Relay remains the authority for agent identities, native conversations, history
and delivery/outbox receipts. Mesh Workroom's existing SQLite store remains the
authority for tasks, plans, handoffs, task-linked replies and review decisions.
There is no new scheduler, duplicate conversation store or imported sandbox tree.

## Ordinary conversation

The Relay tab has one composer and one submit handler. It sends ordinary text to
the explicitly displayed agent and pinned conversation. It does not create a
Workroom task. Agent disappearance never selects another agent. Native session
rotation pauses new sends until Use current conversation explicitly rebinds the
view. Reading historical messages does not redirect a send.

The client uses app.js's admission-aware request wrapper and its privacy lifecycle.
The existing `/relay/api/...` gate proxy still owns server-side Relay authentication
and private Tailscale/gate access. Those proxy routes are distinct from the trial
guard on `/api/...`; adding a client CSRF header does not make them trial-guarded
server endpoints. This slice adds no proxy allowance, public listener, credential
or broader permission. Proxy authentication and Origin checks remain unchanged.

Before sending, the client requires the existing session-binding capability and a
fresh selected-agent observation. A new send carries exactly ID, text and
expectedConversationId. Relay's outbox checks an existing ID before current-session
admission: an exact retry can acknowledge its original accepted receipt after a
session change; a new message cannot silently follow the changed conversation.
Only an explicit Send causes a POST. Polling, reload, reconnect and receipt
restoration never replay work. An accepted receipt is not an agent reply.

An uncertain send persists only its opaque ID, agent/session, version and SHA256
of the original text in tab sessionStorage. Text and other drafts remain in RAM.
Deliberate retry requires the original text and destination. Existing legacy
receipts migrate after admission, preserving ID/destination and the original draft
in RAM before removing the redundant persisted body. Invalid/conflicting receipts
remain preserved and block sending. Unavailable receipt storage prevents dispatch.

Relay outages retain the same displayed, explicitly stale observation and RAM draft
while admission remains valid; no chat.json fallback changes its source. Empty
history clears the previous display, and edits with the same last ID still render.
Session privacy clearance clears history, title options and drafts; late results
cannot restore them. Reconnect requires deliberate destination selection except
for an already pinned uncertain receipt. Message Hide is local view hiding, not
server deletion. Attachments remain disabled: historical filenames are references,
not a claimed upload, download or rendering capability.

## Explicit Workroom handoffs

Workroom keeps its existing admitted, revision-bound task APIs, frozen send basis,
same-identity recovery and independent review provenance. They may link a saved
task to Relay but never share ordinary chat's submit event. The older hidden task
link/native-terminal surfaces are retained for compatibility, not promoted into
the ordinary composer. Existing receipts, owner data and shared services remain.

## Historical staged features

| Feature | Current decision |
| --- | --- |
| Ordinary selected conversation/history | Current Relay tab and native Relay store; one submit path |
| Task intent, plans, team runs and reviews | Existing Workroom APIs and SQLite; explicit scoped workflow |
| Push/notifications | Deferred; choose one delivery path before importing a staged implementation |
| Telegram/proactivity synchronization | Deferred; no credentials, subscriptions or writes added |
| Attachment upload/download and deletion | Unqualified; UI disabled rather than importing a partial implementation |
| External/personal/cross-channel memory | Separate selected source and scope; Mind currently reads selected Workroom records only |

Historical staged/sandbox sources remain preserved. No claim is made that every
historical file was audited or merged. Import only a separately qualified feature
when requested; preserve the current gate, session boundaries and authoritative
stores. Local contract tests and live read-only acceptance are distinct from a new
live agent send; the current pass does not dispatch a real conversation message.
