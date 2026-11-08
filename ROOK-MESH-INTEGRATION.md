# Rook / Mesh integration checkpoint

Status: local candidate, 2026-11-08. Not deployed or activated. Echo owns Rook's scheduler/agent; Mesh owns the authoritative board, claim records and team runner. Do not install a second scheduler. Rook v3 is the behavioral contract.

## Candidate board API

All routes remain behind Mesh's existing session/request protections. These are owner-session APIs for now, **not a newly provisioned Rook service identity**. Do not copy owner/Nims/Echo credentials into Rook or automate owner-session bootstrap as its permanent authentication. Agree and qualify Rook's identity and least-privilege adapter before live connection.

- `GET /api/workroom`: persisted tasks and `teamPolicy.simpleFlow` when enabled. Creation time is `createdAt` (UTC ISO), not `created_at`. Read the returned task/brief/progress/flow revisions; never infer them.
- `POST /api/workroom/{taskId}/claim`: aged, unassigned idea claim. Body is exactly `{revision, taskRevision, briefRevision, progressRevision}`; all values are nonnegative integers. `revision` is the current flow revision, or zero when no flow exists. Server rechecks twelve-hour original age, ownership, lane, completed state, previous claim and unresolved worker under an immediate SQLite transaction. Success returns `{flow}`. Disabled managed flow or changed/ineligible work returns 409; malformed input returns 400. Authentication failures remain 401/403.
- `GET /api/workroom/{taskId}/claim`: read-only `{flow}`; null before intake. After claiming, `flow.claim` includes `claimId`, `taskId`, `dispatchId`, `trigger` (`aged`/`manual`), `claimedAt`, original `createdAt`, `intendedLead`, and the original task/brief/progress/flow revision basis. The original planning dispatch ID is saved before delivery. Subsequent worker/reviewer IDs remain in the existing team/send receipts.
- `GET /api/workroom/rook`: read-only `mesh-rook-board/v1` observation with claimed cards and managed-flow enablement. Connection explicitly reports `not_configured` until the real Rook identity/health adapter is qualified. This is board status, not proof that Rook is installed or running. The current candidate intentionally provides no writable health or identity registration endpoint.

Rook requests a claim; the Mesh runner owns actual dispatch. Rook must not dispatch a second worker itself. After a lost claim response, inspect the board/original claim; do not blindly submit another claim or a fresh send ID. A claim with no native receipt may still be queued, in flight or uncertain. The exact saved receipt, not a timeout, determines what happened.

Manual movement into In progress uses the existing brief PATCH and preserves an explicit lead. It saves the lane change and claim atomically, bypassing original-age/unassigned checks only. A failed claim rolls back the edit. Existing active intake and unresolved sends block a fresh manual trigger. Ordinary edits do not reset `createdAt`. Deliberately saving an answer or requesting changes uses the existing owner workflow, not an aged sweep.

## Verified locally

- Twelve-hour boundary, malformed/future timestamps, owned/completed/claimed/clarification cards and unresolved delivery exclusions.
- Failed and cancelled assignments do not re-enter fresh intake. Retry is not implemented as an aged claim; it still needs same-chain, authoritative terminal-state reconciliation and a bounded retry contract before activation.
- Two store connections cannot replace one claim. The planned ID and original basis persist after reopening the database.
- Real HTTP simultaneous claims yield one 200 and one 409. Readback survives an app restart; the fixture dispatches zero workers. Missing session, bad CSRF and foreign Origin are refused.
- A forced database failure rolls back a manual lane move and its history. An explicit Echo lead is preserved. An unavailable claimed Nims lead waits rather than substituting Echo.
- Existing disposable managed-flow tests exercise scope/build/independent review/Done, bounded corrections, clarification, and separate owner acceptance/changes. These use fake peers, not a live Rook integration.
- Actual disposable browser checks passed: new idea stays unassigned, Work on this queues it with Nims, Done offers Accept result/Request changes, saved change request returns to the middle lane and survives reload, and a saved clarification answer queues fresh intake. Both themes checked at 390x844; no real workers dispatched. Browser discovered and fixed a frozen-interface assignment error, hidden owner feedback and misleading queued-work wording. Accept result was subsequently clicked in a fresh disposable browser fixture and persisted across reload; native readback confirms Done, accepted owner decision bound to the current progress revision, and zero worker sends. This is synthetic acceptance, not Eddie accepting a real result.

Full local `npm test`: 265 passing (40 + 1 + 29 + 67 + 128). `npm run check`: passing; optional frozen contract file absent, so that optional pin check is skipped. Logs: `../mesh-writer-release-full.log` and `../mesh-writer-release-static.log`.

## Remaining before activation

Recovery qualification update: restart before delivery uses the same persisted planning dispatch once. Restart after an accepted delivery but before saving its phase resumes the saved receipt without another send. Unknown/prepared deliveries pause for reconciliation. Automatic intake/team handoffs explicitly refuse the separate deliberate uncertain-send retry path, including a receipt appearing during asynchronous preflight. Claim state/revision/send identity are rechecked after peer discovery and before delivery; a superseded claim cannot dispatch or overwrite its replacement. No automatic terminal-failure retry is enabled by these checks.

Echo coordination: build Rook in an isolated snapshot from frozen commit `4e321ea` and return a patch/test evidence. Nims owns integration into this shared checkout; later Mesh recovery commits are integrated here, not a reason for Echo to edit the shared source or chase each new HEAD. Process counts alone do not identify active file writers. Existing unrelated untracked integration files must remain untouched.

Workspace release qualification update: with managed flow enabled, Start/Resume and lower-level worker reservation retain the previous card's workspace slot until its verified terminal receipt exists. An applied progress report, paused/closed team or restart does not suffice. The real HTTP fixture now applies the first worker's report and still rejects the next start/resume with zero worker dispatch. Legacy unflagged behavior is retained while the candidate remains off.

**Specific Echo integration gap:** `recordSendOutcome` currently binds only an accepted DeepSeek send, and the HTTP reconciler uses the verified DeepSeek outcome adapter. A caller-supplied Echo outcome, even shaped like a valid terminal receipt, is refused. Do not loosen that check or manufacture a proof hash. We need Echo/Relay's authoritative terminal-run observation, bound to the original Mesh task, send, agent and conversation/native task. Ask Echo which existing endpoint/event provides this, how it authenticates the binding, and whether completion guarantees all source-writing tools/children have finished. Implement and qualify the trusted adapter before releasing Echo's writer slot. Same-card correction/review timing and cross-process/outside-app writers remain part of that qualification; the cross-card guard alone does not establish them.

1. Agree the Rook service identity/auth adapter with Echo, with no inherited broad credentials; qualify real Relay agent presence and Mesh health updates. Keep `not_configured` truthful until then.
2. Qualify exact-dispatch recovery at both crash boundaries and same-chain bounded failure retry. Fresh scans must never treat failed/cancelled/uncertain claims as new ideas.
3. Qualify workspace serialization across the deployed runner and Rook, including overlapping scheduled/manual triggers, source changes and any outside writers. Current global active-team gating is not proof of safety across all applications.
4. Finish real Rook card-bound question/report delivery. The disposable browser paths above are verified; physical-phone acceptance of this new managed flow remains outstanding.
5. Deploy reviewed Mesh changes, then connect one Rook scheduler, test end-to-end with a disposable task, and separately approve activation. `MESH_SIMPLE_FLOW` remains off in the named live launcher. No real cards or running model services were changed for these checks.

The obsolete `integrations/sweep-workroom-backlog.mjs` now exits with an error and queues nothing. Do not schedule it. Echo's Rook replaces that prototype.

## Read-only Relay source audit and coordination

On 2026-11-08 Nims inspected the indexed actual `D:/Dev/Onoes-Relay` source, not just Mesh's staged copies:

- `relay_hermes.py`, `HermesRunsClient.run_status`: reads `/v1/runs/{run_id}`; a missing run is an error, not evidence of completion. `submit_run` advertises `{run_id,status,replayed}` admission.
- `relay_server.py`, `hermes_send`: passes the original message ID as Hermes's idempotency key and the conversation as `session_id`; receives `run_id`, consumes events or polls status, and later removes the ID from `active_run_ids`. This establishes a potential live observation path, not a durable Mesh-send-to-native-run binding across restart.
- `relay_server.py`, `_receipt` and `list_outbox`: explicitly document **admission only**. Their response fields (`state`, `attempts`, `transport_ref`, `error`, `created_at`, plus `idem_key` in the list) must not be interpreted as worker termination.
- `_persist_hermes_reply` persists answer text once; it does not itself establish that subprocesses or source-writing tools have ended. That guarantee still needs the native runtime's authoritative contract.

A single read-only question was sent to Echo through the existing Mesh Relay conversation, as authorized by Eddie's coordination request. Relay visibly accepted it; a later explicit refresh still showed no answer. Native run identity for this question is unverified, so this is **not a verified-running job or wait**. Do not resend it to manufacture progress. The question asks for the durable binding, exact native outcome lookup and child/tool completion guarantee, with source/schema only and no source edits, service changes, grants or worker dispatch.

Evidence: `data/echo-terminal-question-2026-11-08/receipt.json` and `../mesh-echo-terminal-question.png`. The current live task count remains 14; no new Workroom question card was found, so no task ID is invented. The old generic `relay-http.message` linking path is not sufficient evidence that the current chat UI created a card.

Relay's `rev-parse` reported `5cc0154`; its tracked-status check failed with a referenced worktree metadata path error. No Relay Git repair was attempted and no clean-working-tree assertion is made. This audit does not qualify the live Echo adapter or authorize activation.

## Echo answer received - 2026-11-08

Echo replied to the original scoped question. Redacted answer retained at
`data/echo-terminal-question-2026-11-08/echo-answer.txt`. This supersedes the
previous pending-reply observation; it does not establish native completion proof.

Echo reports no existing durable Mesh-send/session/native-run binding in the
inspected Relay/Hermes source. Relay's session activity can contain run IDs but
cannot unambiguously join multiple sends in one session. The inspected Hermes
research snapshot may not implement the Idempotency-Key durability that Relay's
client expects, and its terminal status/event retention is not a durable replay
log. Echo explicitly did not verify that snapshot against the deployed gateway.
These are source-audit findings, not verified live gateway behavior.

Echo also reports that native run completion does not establish that all writing
children/tools ended. Nims independently verified Relay's TERMINAL_STATUSES
includes unavailable; never map that state to success or writer quiescence.
The proposed receipt needs original send/agent/conversation/workspace/native-run
binding plus affirmative per-run tool/subagent/child completion evidence. A bare
native run ID or accepted outbox row cannot close the acceptance-to-binding crash
gap. Missing/expired/404/unavailable evidence must preserve uncertainty.

Fresh live Relay observations: Echo status done, activeRunIds empty, no native
outcome; latest outbox entry accepted once with no native reference. The exact
original chat message has only k/t fields in the public agent snapshot, so no
message ID was invented from that text. One following Echo answer was observed.
Metadata proof: native-observation.json in the evidence folder above. These
observations do not prove a Rook build is running or that a writer has stopped.

The existing Echo gateway URL observed from Relay is http://localhost:8642.
Nims made one anonymous GET to the source-confirmed /v1/capabilities path; it
returned401 and the read stopped. No gateway key was read/copied and no identity
was borrowed. This confirms access protection, not gateway version/features.
A distinct version-only follow-up was accepted through the existing session-bound
Relay client with saved send ID304a1fe3-a038-462e-bb65-e6fbccb8502c. Its prepared
intent was written before submission, and re-execution refuses to resend it.
Evidence: deployment-followup.json and gateway-capabilities-observation.json.

Do not start a parallel Rook implementation, treat a research snapshot as deployed,
or silently widen the reconciler. Resolve the deployed native-runtime contract
before planning a production adapter or activating managed automatic building.
