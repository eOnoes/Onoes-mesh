# Workroom to Onoes-Mind: smallest sync slice

Read-only source audit, November 14 Chicago / November 15 UTC, 2026.
Decision: use one deterministic recorder, not another AI agent. This is a design
recommendation, not a live binding, write permission or implementation approval.

Mesh inspected at `08f336cad619a122e30d91f55329598f063f8902`;
Mind at `76c0273637ced688411960e067aabad6eaf4168e`.
Private exact-source evidence: `data/workroom-mind-sync-audit-source-proof-20261114.json`.
Mind has existing untracked audit/candidate files; none were changed. No live
store, keys, services, tests or agents were used. Earlier test records were not rerun.

## What exists and what does not follow from it

| Inspected implementation | Verified behavior | Limit for this build |
| --- | --- | --- |
| Mesh `lib/workroom.mjs:23,81,191` | Stable task IDs; separate task/brief/progress state; saved events; revision-checked brief/stage writes and event insertion in one transaction. | Existing event details are human-readable text, not complete immutable sync payloads. A polling reader cannot reconstruct every historical state from them. The inspected schema stores a project label as text. |
| Mind `Ledger.remember`, `onoes_mind/ledger.py:770` | Authenticates, binds event IDs per principal, persists records/receipts, rejects changed claim/kind/project content under an existing event ID. | It is a memory-submission API, not a qualified project-sync endpoint. Its digest covers claim/kind/project, not every envelope field. Replayed evidence or visibility changes are not fully bound by that digest. |
| Same memory writer | Shared writes use the built-in shared scope for operator; other callers fall back to private memory. Rejected-secret submissions can return durable=true. | Do not borrow operator credentials, impersonate Echo, treat durable=true as success, or assume a generic writable grant enforces the required project boundary. |
| Mind `Ledger.create_work_item`, `ledger.py:176`, and `BridgeServer.dispatch`, `bridge.py:132` | The bridge can create work items/stages and claim/complete them using local-test-runtime identities. | Reusing it would introduce another scheduler and task-state authority. It is not the card-history recorder. |
| `MESH_RECALL_INTERFACE.md` | Prepared, inactive, scoped read-only recall; runtime enrollment/initialization work is also prepared separately. | Recall grants no write path. Prepared source is not an initialized canonical live store or activation approval. |

This bounded audit does not prove that no unrelated candidate exists anywhere in
Mind. It establishes that these inspected interfaces do not provide the complete
production sync contract. No existing write endpoint is endorsed for reuse as-is.

## Ownership: keep the two systems from drifting

- Eddie owns the project and its data. Echo/Nims are operators or task leads;
  task assignment must not silently change the human project owner.
- Workroom owns card content, lane, lead, build/review results and task revisions.
  Mind records those facts with their source and observation time. It must not
  independently move a card, dispatch a worker, approve a review or release a hold.
- Mind owns canonical project identity and durable project knowledge/history.
  Use one explicitly approved Mind project ID for the first Mesh project, with
  many card IDs linked to it. A project label or title rename does not mint a new ID.
  The inspected APIs do not establish a project registry/resolution contract.
- One Done card is a completed task, not proof the entire project is finished.
  Record task completion and its actual review/evidence state separately. Do not
  derive a project-wide completion flag in this first slice.
- Start one-way: Workroom to Mind. A later Mind edit must not overwrite Workroom.
  Any conflict becomes visible for deliberate resolution.

## Smallest implementation proposed

1. A Mind-owned authenticated receipt API for one registered Mesh source and one
   approved project/scope. Give the adapter a separate purpose-specific service
   identity, not a recall token, shared agent token or operator credential.
   Server-derived identity/project permissions must constrain every accepted event.
   No caller-selected principal, arbitrary scope, SQL, commands or filesystem access.
2. In Mesh's existing database, add a delivery outbox and card-to-project link.
   This is pending transport state, not a second memory authority. Capture an
   immutable, bounded event payload in the SAME transaction as its source change.
   Cover creation, assignment, stage change, blockers and completion evidence;
   trace the actual transaction for each mutation before implementation. Do not
   parse old prose events into invented historical snapshots. Existing cards need
   a deliberately labeled baseline, not fabricated original creation events.
3. One serial delivery loop. No Rook/AI worker is needed. Reuse exact event IDs and
   full-payload hashes. Report pending/confirmed/blocked with last confirmed source
   revision. The card save works while Mind is offline; it never claims sync success.
   No new per-edit approval prompts after the project and eligible fields are enrolled.

The first payload should carry schema version, registered Mesh source ID, event ID,
source sequence, Mind project ID, card ID, source task/brief/progress revisions,
event kind, recorded time, bounded approved summary and evidence references.
Keep raw conversations, execution payloads, credentials, private memory and arbitrary
attachments out. The evidence reference is a locator/hash, not automatic retrieval
or independent verification of its claim.

The registered Mesh source ID must survive an approved restore. An unapproved clone
must not become another active writer under it. Bind the real store/environment
through the existing reviewed setup process; a source folder or schema match is
not identity. No live source ID or scope is selected by this document.

## Receipts, ordering and recovery

- Bind the canonical hash of the ENTIRE versioned sync payload at the receiver.
  Same event/hash returns the original result. Same event/different hash refuses.
- Mark confirmed only after an accepted receipt identifies that exact event, hash,
  card, project and source revision. An HTTP200, durable=true or generic duplicate
  response is insufficient. Preserve rejected-secret and rejected-policy outcomes.
- After uncertain delivery, look up the same event/hash. Retry the same immutable
  event only under the receiver's verified idempotency contract; never replace it
  with a fresh ID to get around uncertainty. Back off offline errors; a revoked
  identity or binding mismatch blocks delivery and never changes credentials.
- Preserve per-card ordering. A delayed older event may enter history but must not
  roll back the current projection. Include a source sequence alongside the separate
  revisions; compare equality as well as ordering and refuse conflicting payloads.
- Receipt acknowledgement is separate from the original card transaction. A crash
  after Mind commits but before local acknowledgement must reconcile without a
  second record. Backups/restores must preserve pending IDs and acknowledged state.
- Retention/deletion is a separate explicit contract: no deleted private content
  should be resurrected by retrying an old outbox or replaying a restored backup.
  Do not enable delivery until that policy and its receiver checks are reviewed.

## Minimum acceptance checks before any live enrollment

Use disposable synthetic stores and the actual receiver API/client path:

1. Card save and outbox insert commit together; either failure rolls both back.
2. Creation, lead, stage, blocker and completion events retain exact IDs/revisions.
3. Rename keeps the Mind project link; multiple cards link to one project; one Done
   card cannot complete the project or manufacture owner acceptance.
4. Duplicate and lost-ack delivery create one canonical record; changed full-payload
   hash under the same ID is refused, including provenance/visibility changes.
5. Offline saves stay usable and visibly pending; restart resumes the same IDs.
6. Out-of-order events cannot overwrite newer state; revision rollback/restore
   requires reconciliation rather than silently becoming a new source.
7. Private/out-of-project/wrong-identity/revoked writes refuse; generic recall
   credentials and operator impersonation refuse. Rejection is never shown synced.
8. Authoritative correction/deletion survives old pending retries and restored
   outboxes; old evidence is not promoted to current fact or restored after purge.
9. Actual Mind readback shows the accepted project/card facts and provenance, with
   no private transcript copy, scheduler calls, external fetches or direct DB writes.
10. App lock/unavailable states display honest sync status and leak no credential.

Before live use, still establish the canonical Mind store, protected key custody,
registered source, single project/scope, service identity and reviewed activation.
Eddie's existing private-folder approval does not initialize or activate those.

## Handoff to Echo

Please review this ownership split and the first-event/receipt contract against
canonical Mind. Identify the smallest Mind-owned write boundary and any existing
implementation that can satisfy it with exact source references. In particular,
confirm full-envelope idempotency, per-project grants and correction/deletion
behavior. Do not implement, provision keys/identities, open a live store, dispatch
workers or activate anything based on this audit. Nims will keep Mesh's outbox
behind that qualified boundary. No additional AI steward is proposed.

This enables a future Echo status answer from Mind whether Eddie asks through
Relay or Telegram. It does not merge those native chat transcripts, configure
MCP clients or grant tool execution permissions; those remain separate full-goal work.
