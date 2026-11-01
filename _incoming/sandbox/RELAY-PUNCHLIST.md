# Relay punch list

Status: keep Mesh as a private web app/PWA. A thin native shell is deferred until Relay lifecycle and recovery are stable.

## Order of work

### 1. Host lifecycle protection — next

- Add a Mesh-owned drain/readiness contract.
- Put a visible identity tag on the Relay process command line and health response (`onoes-mesh-relay`, role `relay`) so agents can distinguish it from other Python services before stopping anything.
- Track `starting`, `ready`, `draining`, `offline`, and `failed` explicitly.
- Keep new sends out during a reset while preserving active runs, approvals, drafts, and held handoffs.
- Extend the reviewed `start-relay.ps1` identity checks into a parent-owned supervisor contract.
- Permit one bounded recovery attempt; stop and report on repeated failure.
- Test recovery against isolated data and an unrelated listener. Never broad-kill Python processes.

### 2. Deploy and qualify Relay on 8772

- Parent-owned operation only; do not restart 8772 during static work.
- Verify exact process identity, loopback binding, `/api/relay/health`, and readiness.
- Verify the private 8450 route points to 8772 and does not expose 8771.
- Keep 8771 treated as the older handoff/to-do listener, not Relay evidence.

### 3. Real harmless text path

Against the actual local Hermes API at 8642, with no Mind and no dangerous tool:

- Send one harmless text turn.
- Read the exact final reply back into Relay.
- Verify durable room/run ownership and fresh-document recovery.
- Verify uncertain submit does not duplicate a run.
- Verify stop, offline, reconnecting, and completed-with-empty-output states honestly.

### 4. Approval boundary

- Exercise one harmless approval event through the real installed backend contract.
- Verify exact run ID and request ID binding, stale rejection, duplicate-tap rejection, and refresh recovery.
- Keep Allow once / Always allow / Deny visible only where native scope supports them.
- Keep typed denial reason labeled Relay-local because the installed route does not forward `reason` to the agent.

### 5. Attachments and photo path

- Qualify the actual session-chat image input against the installed parser.
- Use a synthetic labeled image first; prove the model received pixels, not merely that staging succeeded.
- Verify fresh-document metadata and viewer recovery.
- Keep the photo overlay and stage bounded to the chat column, not the full browser window.
- Keep unsupported stop/approval behavior visibly disclosed for photo turns.

### 6. Optional notifications

- Keep Web Push disabled unless explicitly provisioned.
- Separate package readiness, enrollment, provider acceptance, phone receipt, sound, and click recovery.
- Do not make notifications a prerequisite for usable Relay chat.
- Keep the current simple expanding/collapsing card UI as the working surface; defer front-end redesign.

### 7. Mind decision gate

Only after Relay is passable and recoverable:

- Choose the destination/protocol: Hermes Runs API or Maya lean HTTP.
- Test a server-side adapter against an isolated fake.
- Validate bounded envelopes, stable handoff IDs, duplicate refusal, sanitized read-back, and fail-closed destination checks.
- Keep `relay-outbox.db` held on lane B until the adapter and destination are separately approved.
- Do not enable Mind, send outbox rows, or promote model/tool output into Mesh policy.

## Current state

- Sandbox contract suite: 210 tests passed, 13 skipped with the explicit project-local dependency path.
- 8772 Relay: not deployed/running at the last check.
- 8771: older handoff/to-do listener; not Relay qualification.
- 8642: Hermes API server remains a separate dependency.
- Mind: off.
- Held outbox: unchanged; no rows sent or marked sent.
- Native app shell: explicitly deferred.
