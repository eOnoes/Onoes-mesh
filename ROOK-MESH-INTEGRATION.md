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

Full local `npm test`: 260 passing (40 + 1 + 29 + 67 + 123). `npm run check`: passing; optional frozen contract file absent, so that optional pin check is skipped. Logs: `../mesh-rook-bridge-full.log` and `../mesh-rook-bridge-static.log`.

## Remaining before activation

1. Agree the Rook service identity/auth adapter with Echo, with no inherited broad credentials; qualify real Relay agent presence and Mesh health updates. Keep `not_configured` truthful until then.
2. Qualify exact-dispatch recovery at both crash boundaries and same-chain bounded failure retry. Fresh scans must never treat failed/cancelled/uncertain claims as new ideas.
3. Qualify workspace serialization across the deployed runner and Rook, including overlapping scheduled/manual triggers, source changes and any outside writers. Current global active-team gating is not proof of safety across all applications.
4. Finish actual browser qualification of the simpler card flow and card-bound question/report delivery. No new UI or physical-phone acceptance is inferred from backend tests.
5. Deploy reviewed Mesh changes, then connect one Rook scheduler, test end-to-end with a disposable task, and separately approve activation. `MESH_SIMPLE_FLOW` remains off in the named live launcher. No real cards or running model services were changed for these checks.

The obsolete `integrations/sweep-workroom-backlog.mjs` now exits with an error and queues nothing. Do not schedule it. Echo's Rook replaces that prototype.
