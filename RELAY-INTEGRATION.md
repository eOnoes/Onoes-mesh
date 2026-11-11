# Relay integration and ordinary chat

Relay owns the agent directory, pinned native-conversation routing and delivery/outbox
receipts. Each native backend owns its original transcript; Relay exposes that
history and may retain its existing cache. Mesh Workroom's existing SQLite store
owns tasks, plans, handoffs, task-linked replies and review decisions.
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
| Push/notifications | Relay-owned inbox/policy with Web Push selected for a future Mesh delivery adapter; Mesh currently uses foreground refresh only |
| Telegram/proactivity synchronization | Deferred; no credentials, subscriptions or writes added |
| Attachment upload/download and deletion | Unqualified; UI disabled rather than importing a partial implementation |
| External/personal/cross-channel memory | Separate selected source and scope; Mind currently reads selected Workroom records only |

Historical staged/sandbox sources remain preserved. No claim is made that every
historical file was audited or merged. Import only a separately qualified feature
when requested; preserve the current gate, session boundaries and authoritative
stores. Local contract tests and live read-only acceptance are distinct from a new
live agent send; the current pass does not dispatch a real conversation message.

## Short phone Relay layout (2026-11-07)

The reduced-height phone layout compacts destination controls and lets the
transcript shrink below its normal minimum so the composer remains visible.
Existing destination selection, connection status and Conversation details stay
available. No control is auto-submitted or rebound. At390x500 both themes showed
the composer within the viewport and no outer main overflow;390x844 retained an
unsent RAM draft after resizing. These are browser-width checks, not a physical
keyboard/background/rotation acceptance. No real message was sent.


## Saved task progress and ordinary-chat acceptance (2026-11-07)

Relay now has a Task progress action. Choose a saved Workroom card to view its
goal, checklist counts/statuses and recorded review. The selected record follows
saved updates on the existing visible Relay poll; no task is selected automatically.
This view does not bind a card to a conversation, assign work or send context.
Completed checklist steps never imply approved review. Selection/body remain in
RAM and clear with the existing session/privacy lifecycle. The sheet's Done
control stays visible while scrolling, including reduced-height phone layouts.

Actual admitted browser acceptance reselected the same Echo conversation after
privacy lock/reconnect and reload. The prior explicitly authorized coordination
question and its real reply each appeared exactly once. Attachments remained
honestly disabled. This pass sent no new message and created/edited no user task
through ordinary chat. Stable retry/draft/session-change guards remain covered by
the existing contract tests. Browser reconnection is not full physical-phone,
network-loss or keyboard/rotation acceptance; those remain open.

Current compatibility decision remains Relay-owned routing/outbox, original native
transcripts and Workroom-owned task/review records. Historical sandbox features remain
preserved. The dated decision below selects the future notification path; live
delivery remains unqualified. No push/Telegram synchronization is implied by this release.
Full canonical Mind context, writes, shared skills and MCP access are separate
outstanding work. See the private running checkpoint for evidence and live status.


## Foreground delivery and staged notification boundary

For the current release, public/chat.mjs polls the selected native Relay
conversation every five seconds while its panel and document are visible.
public/relay-conversation.mjs shares one pending refresh per admission and
selection. A slow agent/history read can finish without the next timer tick
invalidating it. Explicit selection and privacy changes start a new epoch; old
results cannot paint into that epoch or hold its refresh hostage. Failed reads
release the shared operation so the next deliberate/polled read can recover.

The preserved _incoming/sandbox/app.js instead has startProactiveStream: an
EventSource room stream plus startProactivePoll catch-up, message sequence cursor
and gap reconciliation. That proactive event contract is not the current native
selected-agent history contract. Do not import it as a second conversation path
or assume its cursor/room identity matches native conversations. The existing
public/pwa-register.mjs only permits its assigned HTTP loopback shell worker; it
is not a qualified Tailscale phone push subscription/notification implementation.

Retain native Relay as conversation/outbox authority and Workroom as task/review
authority. Foreground refresh is the only current conversation update path.
Background phone push, its credential/subscription custody and its event
contract still require activation-specific review and qualification; no push provider,
subscription, Telegram mirror, credential or second store is installed here.
The dated decision below closes F2's compatibility choice. Background delivery
implementation and activation remain separate work.

## Compatibility decision — 2026-11-11

Use one Relay-owned notification pipeline for any future Mesh background notices:
Relay inbox/store, existing `Notifier` policy, then Web Push. Mesh keeps its current
foreground refresh until that adapter is separately implemented and qualified.
Do not add a Mesh notification database, second dispatcher, parallel sandbox room
stream or automatic Telegram mirror.

| Record or responsibility | Owner |
| --- | --- |
| Agent directory and pinned conversation routing | Relay; preserve existing agent IDs |
| Original chat transcript | The selected native backend, exposed through Relay |
| Delivery intent, idempotency and transport receipts | Relay outbox; accepted does not mean completed |
| Tasks, plans, claims, worker reports and review decisions | Workroom's existing store and guarded APIs |
| Notification inbox, deduplication, quiet hours and delivery receipts | Existing Relay notification store/policy |
| Future Mesh background transport | Web Push through that Relay-owned pipeline only |
| Durable shared memory, corrections and provenance | Canonical Onoes-Mind; currently not connected live |

Source review found reusable notification primitives, not a qualified Mesh-origin
phone-push integration. `relay_notify.transport_payload` allow-lists only type,
notification ID and link. `SessionStore.push_subscription_add` stores device
subscriptions in Relay's existing database, keyed by endpoint. Neither constitutes
a memory grant or per-agent authorization. No live subscriptions or keys were read.

Important integration condition: the current `_dispatch` can attempt both Web Push
and ntfy for a critical notice when both are configured. A future Mesh adapter must
select Web Push only for Mesh-origin events within the same Relay-owned pipeline;
it must not silently inherit a second ntfy destination or change existing non-Mesh
Relay channel settings. That routing is a prerequisite, not a claimed existing feature.

Before background delivery is enabled, qualify the actual Mesh HTTPS origin and
service-worker scope, existing admission/authentication, subscription ownership,
removal/revocation, deduplication and a validated authenticated deep link. The current
loopback shell worker is not proof of phone push support. Do not include chat text,
task titles, file paths, credentials or arbitrary caller-provided links in a push.
Opening a notice must never approve work, release a claim or dispatch a worker.

Telegram remains optional. Cross-channel context belongs to the separately scoped
Onoes-Mind integration; this decision adds no raw-chat copying or shared-memory store.
Keep the preserved sandbox files intact and import a feature only after its specific
contract is qualified. The ordinary selected-conversation integration already provides
the current release's single foreground update path.

Verification: existing notification/push tests were run with fake delivery channels
and temporary stores. The original run had one clock-dependent test failure during
quiet hours. A one-line noon fixture correction was prepared as
`integrations/relay-notify-clock.patch`, applied only to an isolated test copy, and
85 tests passed against unchanged production modules. This qualifies those primitives,
not live push delivery. The Relay source was left untouched because broader Git status
encountered an unrelated broken worktree reference; no Git repair was attempted.

F2's documented compatibility decision is complete. Background delivery, canonical
Mind memory/skills/MCP and full release acceptance are still unfinished. No service,
credential, subscription, notification or scheduler was activated by this decision.
