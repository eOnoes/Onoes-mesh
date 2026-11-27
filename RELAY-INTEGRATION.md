# Relay integration and ordinary chat

Relay owns the agent directory, pinned native-conversation routing and delivery/outbox
receipts. Each native backend owns its original transcript; Relay exposes that
history and may retain its existing cache. Mesh Workroom's existing SQLite store
owns tasks, plans, handoffs, task-linked replies and review decisions.
There is no new scheduler, duplicate conversation store or imported sandbox tree.

## Direct peer questions

Relay and Hermes A2A are separate routes. A folder handoff records a request. Its presence alone cannot confirm pickup. An A2A Agent Card confirms discovery. A completed reply with the intended peer identity and conversation context confirms an exchange.

Run `python test/echo_a2a_coordination.py <Hermes checkout>` to check the installed adapter with a temporary profile and deterministic answers. It verifies two HTTP messages in one context using an ephemeral credential for Nims. The test never contacts Echo. Production communication requires its own enrollment and an approved execution policy for incoming questions.

## Compact directory - November15,2026

Agent discovery now uses admitted GET /api/relay/native/api/agents. Mesh requests
Relay GET /api/agents?view=directory with its existing server-side authentication.
Relay projects the approved8metadata fields, at most128agents and65536bytes; it
refuses excess instead of truncating the list. Default/full Relay reads remain
compatible. Mesh retains its262144byte response cap and exact-session send guard.
Only the two client directory reads changed; conversation history and Send still
use their existing /relay/api/... proxy and pinned session paths described below.
The648-check local gate and actual authenticated live directory reads passed.
This does not qualify long transcript pagination or enable workers/Rook/Mind.

## Bounded conversation pages - November15,2026

The phone starts with10recent messages using Relay's existing cursor API. Load
older messages fetches the preceding10 and preserves the reader's position,
selected session and draft. Polling retains loaded older messages and fills a
large reconnect gap forward instead of skipping replies. Each request keeps the
existing262144byte cap; a single oversized message is an explicit error rather
than truncated content. The transcript stays in RAM and clears with admission.
No server schema, native session or Send contract changed.

The full651-case suite passed;2scroll cases separately pass, including the new
prepend-position/privacy check added after that suite loaded its tests. The real
controller read recent/older pages and refreshed via admitted Mesh routes;53KB
and75KB pages fit the cap. No agent message was sent. Phone acceptance is pending.
Private evidence: data/relay-history-pages-qualification-20261114.json.

## Ordinary conversation

During Mesh recovery maintenance, Relay shows the conversation and keeps the
composer editable. The gateway includes its local dispatch state with history
and send-capability reads. The phone disables Send while the pause is visible
and checks again before recording a new send attempt. Refreshing after
maintenance makes the saved draft available for an explicit Send. An earlier
unconfirmed attempt keeps its original receipt.

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

When the selected task needs clarification, Relay shows the saved question. A
paused team shows its saved reason. Open card in Workroom takes you to that
specific card, where you can respond. Returning to Relay uses the phone's Back
action. Simply opening the card reads its saved state.
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

## Compact closed board-steward status - November15,2026

The closed Rook notice keeps a44pixel summary tap target without the generic
box padding/margins. Actual desktop1280 and phone390x844 browser views both
measure45pixels for the closed panel; the open panel still exposes its controls.
Actual Tailscale browser checks selected Echo and loaded10older messages while
preserving the same reading offset. Browser viewport emulation is not Eddie
accepting the feature on his physical phone. No send or worker action occurred.
This CSS-only change used browser layout checks; the earlier651full and2scroll
test results remain separate. Evidence:data/relay-compact-status-browser-proof-20261114.json.


## Native Nims project chats - November26,2026

Relay can wrap the existing local Codex project conversations using the installed
first-party app-tools MCP server. Codex remains the conversation authority. This
does not create a second Nims identity, model process or transcript database.
Mind receives deliberate handoffs rather than a copy of the entire conversation.

The connection is disabled by default and refused in standalone mode. Enrollment
requires trusted `codexDesktopOptions`: one reviewed Windows project directory,
actual caller-chat ID, installed Node/server paths and SHA256 pins, and the local
desktop endpoint. Neither HTTP nor browser storage can enroll a connection or
override host, caller, model, thinking, approval policy or project directory.

Two explicit profile modes are available:

- `native_codex_desktop_readonly`: conversation list and history only.
- `native_codex_desktop_messaging`: adds deliberate Send and New chat actions.

The optional transport setting `discovery: "single_local_codex_desktop"` looks
only in the local Windows named-pipe namespace. A reviewed fixed namespace
`\\.\pipe\codex-app-tools` requires exactly one desktop candidate and stores no
per-instance endpoint. A previously reviewed explicit instance is retained when
present; otherwise exactly one Codex desktop candidate must exist. Missing
or ambiguous instances are refused. A subsequent read can reconnect after a
failed connection, rechecking source pins, caller and project. This does not
restart Codex, retry a failed native write, or establish another access route.
An actual desktop restart remains a separate acceptance check; synthetic peer
retirement/reconnection does not prove that owner workflow.

Admitted routes:

- GET `/api/relay/codex/status`: configured mode, not a reachability claim.
- POST `/api/relay/codex/catalog`: approved project and native conversations.
- POST `/api/relay/codex/history`: one selected conversation and opaque older
  turn/item cursor. Both first-party page formats are identity-checked.
- POST `/api/relay/codex/send`: request ID, selected thread ID and text.
- POST `/api/relay/codex/new`: request ID, approved project ID, title and text.
- POST `/api/relay/codex/receipt`: lookup only; never dispatches work.

The normal admitted cookie/CSRF checks apply, including a fresh access check
immediately before native dispatch. Native caller and target must be in the one
reviewed local project. User and assistant messages remain separate; reasoning,
tools and ordinary native output payloads are excluded. For messaging only, the
reader also requests native outputs to recognize the exact codex_app delegation
envelope. Only this verified caller plus a matching own delivery receipt can
produce a “YOU · via Relay” message; arbitrary outputs stay hidden. Message bodies
remain in Codex and are rendered literally. Older
pages preserve reading position. Each conversation has a separate in-memory
draft; opening or switching a chat never sends. New chat requires an initial
message and explicit Create. It preserves native defaults and uses the existing
project without creating a worktree. A setup-only client ID is not a ready chat ID.
Approvals that Codex requires still belong to its native desktop interface.

Messaging creates `codex-requests.sqlite` inside the existing owned app-data
directory. It contains request IDs, destination, payload hash, timestamps and
delivery state only, never message bodies or credentials. A claim commits before
the native call. Repeated IDs return their saved outcome; unresolved identical
payloads cannot bypass the guard using a new ID. Lost replies and restarts remain
unconfirmed. An accepted receipt means Codex acknowledged the request, not that
the work is finished. There is no timeout-based release or automatic resend.

Browser session storage keeps only request metadata for checking uncertain sends;
drafts and queued text are memory-only and clear when access ends. If receipt
storage fails, reading remains available but sending is blocked. A later session
checks saved receipts without sending. The existing manual/milestone backup
includes an online WAL-safe receipt snapshot and isolated readback when the
journal exists. Keep the current journal when restoring older app/task data;
never overwrite newer receipts or interpret missing history as permission to retry.

Source qualification covers the real first-party reader plus synthetic native
messaging through the actual Mesh HTTP/UI and SQLite receipts. One owner-approved real native chat and one follow-up passed through the actual
Mesh HTTP routes. Both native user prompts and both replies were read back from
that same chat, without retries or a second transcript store. Persistent production
enrollment, same-current-chat steering, actual desktop restart and owner phone
acceptance remain pending.
No live reader/messaging profile is installed by this source milestone.


The existing native Mesh input frame and private launch profile now accept the
optional `codexDesktopOptions` field. It is validated before being passed through
the same inherited pipe; it cannot be supplied as a startNativeMesh appOptions
override or through the recall-only input reader. Existing profiles without the
field retain their behavior. Source/model/caller/host overrides remain refused.

Codex availability is independent of Mesh startup. Trusted config shape is
checked immediately, but executable/server pins are checked before a native proxy
launch when a chat is opened. If Codex is absent or its installed files changed,
the Nims read refuses the stale connection while the rest of Mesh stays usable.
Review new installed-file pins before reconnecting; never accept changed code by
disabling the check. Gateway and native-frame checks use a synthetic app peer and
temporary private app data, without enrolling the live phone service.

## Stopped-agent conversation guidance

When the selected agent reports stopped and the newest displayed message is from
the user, Relay notes stopped and no agent reply yet, and suggests checking the
agent connection. This notice is a current-conversation observation only. It is
not proof that delivery failed and not a promise the agent is reachable. Status
alone never disables Send, blocks the composer or retries anything. Uncertain
receipt, maintenance, historical or stale-session and catching-up guidance still
take precedence over this note. The notice clears on a new agent reply or a
changed status; the existing privacy lock keeps clearing private history and
drafts. The change uses only existing status and history reads. It repairs no
remote endpoint, creates no peer, changes no credentials or scopes, and does not
activate Cyony Mind. Unit and browser checks verify this notice path separately
from any unqualified live Cyony connection; neither qualifies a live deployment.
