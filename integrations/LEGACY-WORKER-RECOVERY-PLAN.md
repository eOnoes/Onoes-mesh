# Historical worker recovery — proposal for review

Status: PARKED at Eddie's clarification. A PC restart is not required to continue
the Mesh build. The briefly scheduled 7:00 a.m. restart automation was deleted;
no Windows power command was queued or executed. Do not recreate it from older
instructions. Further testing grants no live hold release or PC restart authority.

## What testing established

- Six historical Echo sends each have exactly one identical request-text match in the correct canonical native conversation. These are candidate correlations, not a replacement for a durable dispatch receipt.
- Each matched admission is terminal/completed. Its original canonical result is present.
- The native idempotency store has no retained row for those exact run IDs. Exact session/owner-epoch/generation queries find no matching worker-execution ledger rows. The results contain no structured whole-worker retirement proof.
- The two original DSH task records exist, but their structured records contain task outcomes rather than worker-retirement proof.
- Twenty-six existing local receipt/binding/claim tests passed. These tests verify current guards; they do not retroactively establish historical process exit.

All eight live holds remain. No original record has been modified. No retry, cancellation, cleanup, process termination, credential change or service restart was performed in this investigation.

## Recommended next review: controlled main-PC recovery window

If no original retirement evidence can be supplied, review a one-time maintenance procedure that establishes a new local process boundary. A normal full Windows restart is a possible component because it terminates the previous local process instance; it does not prove historical task success or remote-worker retirement.

This is a proposed route to investigate and rehearse, not an approved closure policy. It must not automatically release the eight holds.

Before asking Eddie to approve a real restart:

1. Establish that each affected writer is local to this PC. Any unresolved external or remote writer remains held. Candidate content correlation alone is insufficient to assert this.
2. Identify the actual startup/recovery owners and pending-work replay behavior of Mesh, Relay, the native gateway and the DSH bridge. Show how the maintenance window prevents new/replayed assignment of the affected work. Do not alter credentials, subscriptions or unrelated applications.
3. Prepare exact rollback/recovery steps, a matching source/data snapshot, and checks for the preserved board, original receipts and assignment identities.
4. Rehearse the recovery acceptance rules on a disposable store. A missing, stale, wrong-machine or incomplete maintenance record must retain every hold. Task completion, file completion, owner approval alone and an unrelated successful test must never impersonate a native retirement receipt.
5. Define a distinct operator-maintenance record if such a policy is approved. Preserve original unknown retirement fields and historical evidence. Never fabricate a native-local binding or silently set historical writer-quiescence fields to true.
6. Present the reviewed exact procedure and its disruption to Eddie: a PC restart interrupts all applications and any model service, so current testing approval is not enough. Eddie must have a chance to save active work and explicitly authorize that maintenance window. The earlier instruction to leave the model service running still applies.

If the above gates cannot be met, keep the legacy work held and identify the specific missing prerequisite. Do not keep rerunning the same negative queries.

## What would count as recovery acceptance

An approved procedure would need actual before/after machine-instance evidence, no automatic replay of the held assignments, restored source/data identity, and proof that its scope covers all affected local writers. Remote or unmapped writers would remain blocked. Only a separately reviewed closure mechanism could consume that evidence; no such mechanism is installed by this document.

Do not confuse administrative recovery with a successful build, review, owner acceptance or historical retirement. Rook, normal native enrollment and live Mind remain off until their own gates pass.

## Startup review findings (read-only, 2026-11-11)

- Current Mesh, native gateway and Relay process identities/start times were read and remained unchanged. No startup task was edited or run.
- The enabled Workroom recovery task starts the private preview through its existing hidden launcher. A separate `mesh.cmd` login entry calls `D:/Mesh/tools/start-mesh.cmd`, the original Mesh deployment. A full PC restart therefore affects both deployment stories; neither store may be overwritten or conflated.
- Relay and DSH have login shortcuts targeting their existing launchers. The inspected DSH launcher checks its existing loopback listener and starts the bridge hidden if needed. This is launcher behavior, not proof that bridge/task restoration cannot replay work.
- The Relay launcher starts the existing Relay server. It can rotate the previous run log; preserve evidence before any approved launch. No launcher was executed in this review.
- The scheduled native gateway is enabled at login, and the local-model supervisor also has an enabled login task. A PC restart would interrupt and restart more than Mesh. The earlier model-service restriction remains in force.
- The real Relay `SessionStore.outbox_recover` was exercised on a disposable database: an accepted row stayed byte-for-byte unchanged, a pending row stayed unchanged, an interrupted sending row became retrying, repeat recovery did nothing, and same-store reopen preserved the rows. This tests the actual store transition, not complete server dispatch after startup.
- Native admission code selects queued/started/unknown as pending. Read-only checks show all six exact matched admissions are terminal and excluded by that selector. This does not qualify every gateway startup path.
- The matched admissions' recorded lineage was also checked for worker-ledger rows at the exact epoch/generation; no row was found. The retirement gap remains.

Remaining before an execution-ready proposal: full DSH task-restoration behavior, complete native startup/intake behavior, affected-writer locality, replay prevention across all startup owners, and the separately reviewed closure mechanism. No restart or hold release should be requested as though these remaining gates were already satisfied.

### Additional real-import checks

The installed DSH bridge entry file still matches the previously qualified hash `06b7585153e100d12a1efc875f79e29e1e06998c29be29293635a2433e4cf410`. Its actual loopback listener owner was observed without stopping it. This is source/process custody evidence, not proof of every loaded byte.

The installed `FileTaskStore` was imported alone and given a fresh synthetic file. Initialization and exact-ID reads preserved both completed and working records, and the fixture file stayed unchanged. No bridge or executor was constructed. This qualifies persistence restoration only; full bridge startup remains open.

Five recovery checks passed against a real `SessionDB` in a disposable native checkout with the recovery source hash matched to the installed file. They cover old interrupted Kanban work becoming unknown, preserved completed/queued/unknown/current-owner records, idempotent recovery, and stale-epoch rejection. No live database or gateway was used. Child-worker termination and full gateway startup are not established by these five checks.

Earlier test attempts are retained: shared Windows temporary-directory access was unavailable; a hand-written minimal database lacked the real child-worker schema; and an initial full-schema fixture used invalid worker kind/status labels. Corrected fixtures use the actual native schema and its allowed `kanban`/`terminal` values. These failures did not establish product defects.

The first indexed native recovery view was stale despite its freshness annotation. Real imports exposed the difference. Only the exact recovery and worker helper files were reindexed, with AI summaries/context providers disabled; no installed source was edited. Do not treat earlier indexed source excerpts as independent current-runtime proof. Startup caller views still require the same current-source qualification before claiming complete startup coverage.

## Evidence

## Current restart prerequisites

### Read-only PC boundary verifier

The existing `integrations/verify-live-release.mjs` retains its normal `capture`/`verify` modes for a Mesh-only restart. It also supports:

```text
node integrations/verify-live-release.mjs capture-pc data/<fresh-window-name>.json
node integrations/verify-live-release.mjs verify-pc data/<same-window-name>.json
```

The PC modes do not restart anything. Capture records the Windows boot time, hashed hostname, app source digest, saved-board digest and assignment-hold digest. It refuses to overwrite an existing capture. Verification requires a newer Windows boot on the same machine and the same source, board and holds. A failed check creates no verified receipt. A successful receipt explicitly leaves worker retirement unestablished and grants no hold clearance.

Four guard tests passed, including invalid/missing evidence, same/older boot, wrong machine, changed source/board/holds and preserved records. Actual live rehearsal rejected the same Windows boot and capture overwrite, and the original Mesh-only modes passed using separate fixture receipts. The full local code gate passed 514 checks. A real post-PC-reboot success remains NOT RUN. Use a fresh capture only when an actual maintenance window is approved; the rehearsal capture is historical test evidence, not that window's baseline.

Read-only Windows checks found that Workroom recovery, the native gateway and the
model supervisor use `Interactive` logon tasks. Automatic Windows login is disabled.
A restart must not be treated as unattended phone-access recovery: someone needs an
existing way to sign in afterward. No password was read and no login setting changed.
Eddie confirmed he can sign in when home, then clarified that a restart should not
be scheduled just to continue app work. The one-time 7:00 a.m. automation was deleted.
Login availability is not an outstanding question or permission to restart.

The installed DSH plugin's actual `apply` function was mounted twice with synthetic persistent tasks and real ephemeral `127.0.0.1` HTTP listeners. Both mounts preserved completed and working task readback, rejected incorrect authentication and reported zero active agents. Only fixture listeners were closed. This covers the standalone bridge branch with a minimal service context, not the complete DSH CLI/profile startup or a live restart. A restored `WORKING` task record is historical state, not evidence of a currently running agent.

Native startup caller files were refreshed before review. Initialization invokes old-epoch recovery before adapters connect. Later recovery can schedule pending local rows, pauses unknown turns, and selects queued/unknown native session targets. The six matched completed admissions are not themselves pending work. These source and component checks do not qualify all cron, bot, detached, hosted or external work, and do not grant historical hold clearance.

Do not spend additional test runs trying to recreate missing historical retirement receipts. The remaining review is an operator recovery decision with declared local-writer coverage, safe replay/intake handling, a login-capable maintenance window and distinct, truthful maintenance evidence. The existing instruction to keep the model service running remains effective. No reboot, live retry, cleanup or hold release is approved by these findings.

## Additional evidence

Local-only records:

- `data/legacy-echo-exact-payload-correlation-20261111.json`
- `data/legacy-echo-matched-run-metadata-20261111.json`
- `data/legacy-echo-canonical-result-retirement-check-20261111.json`
- `data/legacy-echo-exact-worker-ledger-20261111.json`
- `data/legacy-dsh-original-task-metadata-20261111.json`
- `data/legacy-dsh-structured-receipt-check-20261111.json`
- `data/legacy-recovery-guard-tests-20261111.log`
- `data/legacy-recovery-startup-tasks-20261111.json`
- `data/legacy-recovery-startup-owners-20261111.json`
- `data/legacy-recovery-startup-shortcuts-20261111.json`
- `data/legacy-relay-startup-recovery-proof-20261111.json`
- `data/legacy-native-pending-selector-check-20261111.json`
- `data/legacy-echo-lineage-worker-check-20261111.json`
- `data/legacy-native-recovery-source-custody-20261111.json`
- `data/legacy-dsh-startup-source-custody-20261111.json`
- `data/legacy-dsh-store-restore-proof-20261111.json`
- `data/legacy-native-epoch-valid-schema-tests-20261111.log`
- `data/native-compression-real-checkout/tests/agent/test_mesh_epoch_recovery.py`
- `data/legacy-dsh-full-startup-proof-20261111.json`
- `data/legacy-dsh-full-startup-tests-20261111.log`
- `data/verify-dsh-startup-replay-20261111.mjs`
- `data/legacy-recovery-postboot-login-preflight-20261111.json`
- `data/legacy-original-turn-tool-metadata-20261111.json`
- `data/goal-startup-path-review-readback-20261111.json`

These observations cover the inspected stores and exact identities. They are not an exhaustive search of every log or a proof that no external evidence exists.


## 2026-11-13: tested transport hold for the proposed window

The operator candidate now has a real Windows-exclusive loopback TCP hold in native_transport_hold.py. This addresses new listener admission without depending on how that listener was launched. It refuses an occupied endpoint and does not terminate its owner. A fresh disposable qualification held the installed-source Hermes profile lock and the transport reservation in the same child; competing profile owner and transport binds were both refused, then both became available after explicit release. It does not establish existing-worker or direct-execution coverage. No live provider is enrolled and no actual native port is held.

The next executable slice is a trusted provider that couples these holds to the exact Mesh database-held lease and recovery transaction through COMMIT, with evidence of lifetime/failure behavior and truthful remaining coverage. Do not pass a copied Python snapshot as authority, weaken the synchronous final guard, or claim this component alone authorizes the cold-boot window. Original records and all eight holds remain unchanged. Startup-method clarification may help the final maintenance recipe; it does not block continued local provider implementation and is not itself restart approval.


## 2026-11-13: transaction lifetime connection implemented locally

The in-process Node adapter now supplies actual profile and port handles in the same process as the canonical SQLite transaction. Both native and database-bound Mesh capabilities are required through the synchronous final check and COMMIT. No JSON snapshot or observed PID can replace a native capability. Failure/exit cases were exercised on disposable resources; full577 tests pass. A reviewed exact resource fingerprint is part of the plan source hash. Optional resource-JSON preparation is read-only and is not coverage approval.

Remaining before a real window: resolve the current independent-review reply mismatch; establish the exact declared local-writer and replay scope without claiming unknown/remote retirement; review exact startup/resource configuration and disruption; obtain explicit owner window/plan authority; then use actual later-boot evidence and actual held resources. No restart, old-hold release, native/Rook/Mind enrollment or new paid team trial is authorized by these local tests.


## 2026-11-13: independent current-source review accepted

The reply mismatch is resolved for source-review purposes. A single corrective
request completed with the exact new marker, matching5source hashes and matching
native/display digest. Echo found no blocking defect in the same-process hold
and COMMIT path. Its cleanup caveat remains fail-closed; resources may stay held
until process exit after a native close failure. This review does not execute
tests independently or establish production/local-writer/replay coverage.

Original request fingerprint and transcript comparison prove correct Relay
submission; the separate request was incorporated into a compression summary
before the wrong older answer. Compression-associated task drift is observed;
its precise cause is not established. No compression/native code was changed.

Next: finish the operator scope/startup/replay/restore record, then obtain exact
window authority. No restart, hold release, Rook/Mind activation or paid team
trial is granted. Preserve unknown outcomes and original eight hold records.
Evidence: data/native-review-corrective-assessment-20261113.json.


## 2026-11-13: current owner scope and real sequencing corrections

Owner now declares only Echo/DSH on this desktop. DSH web login startup is now
explicitly installed at the owner's request; include its named shortcut with
the existing DSH A2A shortcut, Hermes_Gateway and Onoes Deep Watchdog owners in
any reviewed pause/restoration recipe. Current profile metadata and API listener
were matched read-only. This is scoped configuration evidence, not retirement.

The canonical snapshot now excludes only the paused singleton gate's ephemeral
holder nonce so a pre-restart plan can precede its post-restart private lease.
The canonical transaction separately checks the real holder in both its own
committing view and the lease's connection. Real disposable tests reproduced
both prior failures and prove final holder/admission substitution rolls back.
Full582 checks PASS, static source review accepted for the current valid schema;
no actual restart or live recovery. Old plans/fingerprints are historical and
must not be applied to the current15-card board or changed source.

Next required implementation: a thin trusted one-shot operator assembly and
source-backed startup/replay fence provider using the existing authorization,
observation, actual native and database capabilities. Do not replace coverage
with JSON booleans, add an HTTP apply route, or ask for restart/apply authority
as though that assembly is already implemented. Keep exact8 outcomes unknown,
retain source/data before/after evidence and restore exact approved startup
settings separately. Only request the real operator window after this is
concrete, reviewed and qualified on disposable data.


## 2026-11-13: assembled one-shot operator candidate

`integrations/legacy-recovery-operator.mjs` now composes the existing canonical
recovery store, owner-record reader, real Windows native holds and Mesh dispatch
lease in one process. There is no HTTP endpoint, scheduler, automatic pause,
resume, startup modification or restart action. This is a local candidate, not
live-recovery acceptance. Independent review of this new assembly remains pending.

Operator CLI (from the exact reviewed workspace):

```text
node integrations/legacy-recovery-operator.mjs prepare <absolute-scope.json> <reviewed-scope-sha256> <new-plan.json>
node integrations/legacy-recovery-operator.mjs inspect <absolute-scope.json> <reviewed-scope-sha256> <plan.json>
node integrations/legacy-recovery-operator.mjs apply <absolute-scope.json> <reviewed-scope-sha256> <plan.json> <absolute-owner-record.json> <reviewed-owner-sha256>
```

Scope contract `mesh/legacy-operator-scope/v1`: owner Eddie; locality
`desktop_echo_dsh_only`; exact workspace/database; nativeResources with the
reviewed Hermes gateway.lock and both loopback families on3081/4123/8642;
relay/hermes database paths and file identities; DSH task-store path; exactly
eight bindings (sendId/agentId/conversationId plus six unique admissionId and two
unique nativeTaskId); each binding's nativeFingerprint hashes its exact selected
metadata projection. Startup contains the two named scheduled tasks with action/
principal fingerprints and two original/parked DSH shortcuts with pinned bytes.
Additional reviewed source files may extend, never replace, required source pins.
The scope file and operator source are themselves pinned in the frozen plan.
No credentials or chat contents belong in the scope or approval record.

Prepare requires an already paused, drained, unheld Mesh gate and verified
startup/replay controls. Freeze before the later same-machine boot, then acquire
fresh private holds after boot. Apply requires the exact unexpired owner record,
unchanged complete board/source/identity, actual held capabilities, disabled
nonrunning scheduled owners, absent original login shortcuts and pinned parked
files. It independently reads accepted Relay receipts, terminal Echo admissions
and completed DSH task metadata, and refuses any uncertain queue state. It
rechecks controls/sources/owner/capabilities at COMMIT and leaves dispatch paused
on success or failure. No original send is retried, changed or marked successful;
its historical outcome remains unknown. Rerunning after a committed board change
is not a substitute for inspecting the saved canonical recovery receipt.

Evidence:56 focused checks and full587 checks PASS (466 Node/121 Python). Actual
Windows native holds and disposable databases were used; fixture boot/task
observations were simulated through an import-only test seam unavailable to CLI
JSON, flags or environment. Actual read-only PC inspection correctly refused
the currently enabled scheduled restart owners. No live scope/plan/approval was
created, no startup owner was paused and no holds were cleared.

New blocker: actual Relay has2 retrying deliveries (DSH and Cyony, older than the
selected Workroom eight); Hermes has1 unknown admission from another conversation.
They were inspected as IDs/status metadata only and left unchanged. Do not hide,
requeue, retire or delete them merely to make recovery pass. Next: obtain exact
authoritative reconciliation evidence and a reviewed disposition for those
records, review the composed operator and exact scope, then request the real
login-capable maintenance window. No restart is scheduled or approved now.


## 2026-11-13: recovery receipts now bind the exact original delivery

A new regression reproduced a real defect in the assembled candidate: a matching
receipt ID/terminal status could pass while its input text differed. Recovery
now opens the pinned original Workroom database read-only and checks task, agent,
conversation and rendered delivery against Relay content. It uses saved
`payload.trim()`, not the shorter card `text`; the actual eight records prove
those fields differ. Echo checks only the selected admission's JSON text field;
DSH requires the selected completed task/context and exactly one matching user
text. Scope now requires the exact Workroom `databaseIdentity` as well as its path.
No original payload or conversation is copied into a receipt or a review packet.

Tests reject changed Relay/native text, coherent-but-wrong conversation bindings,
and swapping completed DSH tasks in the same conversation. Both unknown native
status and changed input at the final guard roll back all provisional recovery
references/events. Full588 checks PASS (467 Node/121 Python). Actual read-only
correlation proves all6 Echo and2 DSH original deliveries match their exact native
inputs; this is not proof of writer retirement or permission to release holds.

The unrelated2 retrying Relay records remain unchanged, with null transport
references and no exact send-to-task retirement proof. The older Hermes unknown
admission has owner epoch2 versus current10 but no matching worker execution;
epoch age and missing worker metadata are not terminal proof. Relay startup's
recovery function marks interrupted sends retrying; that function itself does
not dispatch, and message() suppresses existing-ID submissions. Background
watchdog/adapter behavior is not yet qualified, so do not weaken the conservative
queue gate. New direct source-only Echo review is in progress; no tools or live
inspection were requested. No reboot, startup changes, cleanup or activation.


### Correlation review result: further changes required before live use

Echo's exact source-only reply matched the question marker, native terminal
receipt digest and unchanged source hashes. It identified DSH history ambiguity
and missing Python/JavaScript trimming parity coverage. This is not approval of
the operator or of live recovery. Actual metadata confirms the second original
DSH task contains the original input at index0 and a later different user input
at index2. Its completed status is not evidence that the original request alone
completed. Keep unknown outcomes, queue gates, startup controls and live holds.

Next slice: qualify the native DSH request-specific boundary against the actual
two-input history and add its regression, plus exact parity with Relay's Python
`str.strip` rule (not merely JavaScript `trim`, including Unicode edge cases).
Do not solve the ambiguity by marking original work successful, dropping native
correlation, or silently rejecting a legitimate original history as finished
implementation. Current588 proof applies to the current candidate only; full
assembly independent acceptance and actual runtime activation remain open.
Evidence: data/operator-correlation-review-assessment-20261113.json and
data/operator-dsh-request-boundary-20261113.json. Source-only review used no
machine inspection or tools and no new worker/trial/activation authority.


## 2026-11-13: DSH originating-message boundary and exact Relay normalization

The operator now requires each DSH binding's `originMessageId` and
`originFingerprint`. The first history message must match that reviewed identity,
its full canonical fingerprint and the original rendered delivery; the message
ID must occur exactly once across the task store. Later follow-ups are allowed.
A matching text appearing elsewhere, a substituted origin or a copied origin in
another task cannot qualify. The completed task state is current replay-state
evidence only. Original work outcome remains explicitly unknown. No claim of
original-request success or whole-writer retirement follows from task status.

Current installed native methods FileTaskStore.save, ResultManager's task-event
merge and DefaultRequestHandler's known-task request-context path were inspected
through a hash-matched one-file snapshot. Their exact bodies were evaluated with
isolated store/context/error adapters and synthetic requests: origin persisted,
follow-up appended and completed task retained its origin. This is method-level
qualification, not full-plugin startup or concurrency acceptance. The same pure
origin predicate passed read-only against the actual two original DSH tasks,
including the historical task with two user inputs. No live queue gate was
bypassed, no task changed and no private input text was recorded.

Relay transport uses Python str.strip, not JavaScript trim. A reproduced failure
for U+0085 is fixed with Python's exact whitespace classifier, including control
separators and excluding BOM. Tests compare every Unicode codepoint with Python
and preserve interior whitespace; integrated receipt tests cover both boundary
normalization and BOM retention. Relay's installed Python and the test runtime
were both3.14.3 with the same29 whitespace codepoints. Full591 local checks PASS
(470 Node/121 Python);9 operator cases PASS, with pre-fix failures recorded for
both review findings. New source-only Echo review is in progress; do not claim
independent approval until its exact reply and digest are verified.

No PC/model/native restart, startup pause, live scope/plan/approval, queue cleanup,
old-hold release, new paid trial, Rook/Mind activation or GitHub push occurred.
The two retrying Relay rows and older unknown Hermes admission still need a
reviewed reconciliation/containment procedure. Current first release remains
18/21; these are recovery-provider correctness changes, not production signoff.

Tooling lesson: index_file on the installed profile resolved the broad user-root
index and took202seconds. Only that owned helper was interrupted after its result
returned, not any app/service. A one-file snapshot index_folder unexpectedly
replaced602 project index entries; source files were untouched. Restoring the
index with the supported explicit tracked-path list avoids any directory walk.
The oversized terminal JSON was rejected before execution; a finite structured
SDK call now restores the same authorized metadata. Do not use index_folder on a
subdirectory of an existing index without explicit identity/scope semantics.
A disposable qualification script initially failed before execution due to its
relative imports; corrected and successfully qualified unchanged native bytes.


### Independent review of origin and strip fixes

Echo's exact terminal source-only reply matched its question marker, native
UTF-8 digest and unchanged source hashes. It confirms both prior findings are
addressed. This is static review of the supplied diff, not live recovery approval.
It adds a store-provenance contingency: a source record with no embedded taskId
might be relocated while its message identity/fingerprint stays unchanged and
unique. The reviewed scope already pins the task/origin pair and preparation
checks it; the remaining qualification must explicitly test frozen-scope
relocation and establish adequate snapshot/source integrity without asserting
historical success. Do not dismiss the contingency without proving its scope,
or claim a task was historically bound merely because current text matches.

Next: finish that one association-integrity qualification (consider a reviewed
whole-store snapshot hash checked on the same bytes used by the predicate),
then determine the authoritative replay/containment behavior for the unrelated
uncertain queues. No retirement, retry, cleanup or maintenance authority follows
from this review. Keep the current real two-input history supported; do not turn
a blanket refusal of valid history into a completion claim.

Explicit tracked-path indexing restored the project index:746 files added,
8526 symbols, no directory walk and no source-file change. Owned lookup clients
14995/70115 and finite restoration3822 are terminal; no index job remains.
Evidence: data/operator-origin-strip-review-assessment-20261113.json,
data/operator-native-origin-qualification-20261113.json and
data/operator-index-restoration-20261113.json.


## 2026-11-13: reviewed DSH snapshot integrity qualified

Recovery scope now requires `dsh.sha256`, the reviewed canonical task-store byte
hash. The snapshot verifier hashes the exact bounded bytes it parses; the same
store is also a required hashed plan source. There is no automatic refresh when
records change. A new reviewed scope/plan is required. Relocating an origin or
changing any selected/unselected task-store byte after review therefore refuses
recovery. Legitimate two-user history exists before fixture scope preparation
and passes the complete composed operator. Final snapshot mutation rolls back
all provisional recovery references/events and leaves dispatch paused.

Pre-fix regression reproduced acceptance of changed unselected store data.
Focused10 cases and full592 checks PASS (471 Node/121 Python). A read-only probe
of the actual canonical store uses the same snapshot verifier and qualifies the
two original DSH associations, preserving original outcomes unknown. It creates
no live recovery scope, plan, approval or write. Echo's exact terminal source-only
review matches marker/native digest/unchanged source and closes the snapshot
finding for the correctly reviewed bytes, conditioned on readPinned's actual
hash/size checks. Those checks are in the current implementation; runtime
extinction, replay exclusion and activation remain separate requirements.

The remaining unknown native admission is messaging/Telegram, intent queue,
older epoch; it is outside the original Workroom eight. No private message or
principal ID was disclosed. Source inspection and isolated execution of the
actual inspected methods show native session recovery refuses unknown work
(including unknown plus queued), and the bot retry gate rejects unknown/started/
queued, accepting only settled failed results that classify as retryable. Relay
constructor starts an empty memory queue; outbox recovery preserves retrying
rows, fresh drain does not deliver them, duplicate IDs return before enqueue,
and only a deliberate new fixture enqueue reaches its run-turn stub.

This is method-level evidence with route/key/result/store/error stubs, not full
startup, current loaded-code, other-adapter recovery or old-writer retirement
proof. The bot source is edited/uncommitted in its own checkout; it was only read
and hashed, never edited or committed here. The old Cyony receipt still has a
current A2A agent route; current registry also has a separate OpenClaw adapter,
whose recovery is outside the probe. Keep the conservative global queue guard
unmodified. We have not authorized ignoring or retiring any of those records.

Next design question to Echo asks whether exact retained non-replaying holds can
be carried unchanged, what separate prior-writer containment remains necessary,
and which minimum evidence is needed before implementing such a contract. No
actual IDs/paths/private content are in that question, and no actions were
requested. Prefer retaining unknown history over administrative cleanup, but do
not equate non-replay with writer quiescence or infer retirement from missing
rows/age. No maintenance window request until the executable boundary is ready.

Evidence: data/operator-snapshot-full-proof-20261113.json,
data/operator-snapshot-live-probe-20261113.json,
data/operator-snapshot-review-assessment-20261113.json and
data/operator-retained-queue-source-probe-20261113.json. Source-only reviews and
method fixtures do not grant live activation. No restart, queue cleanup, old-hold
release, new paid team trial, Rook/Mind activation or GitHub push occurred.


### Retained-hold design result and actual route boundary

Echo's exact design reply matches the question/native digest. A narrow retained
record contract can establish preservation and non-replay of covered paths; it
cannot establish prior-writer retirement. Bind exact source/store/record/route/
runtime evidence and all dispatch/ownership fields, recheck at every gate and
commit, and block missing/changed/duplicate/unclassified evidence. No general
ignore flag, no retry-eligible failure exception and no inference from age or
missing worker rows. Separate positive retirement/containment is required for
every writer that could affect the selected scope. Remote writers remain
explicitly outside a local claim and unresolved without their own evidence.

Actual public route metadata shows the old Cyony receipt's A2A endpoint is not
loopback; comparison with this PC's interface addresses confirms it does not
resolve to this PC. No peer was contacted. This does not prove the peer is live
or identify/retire an old worker. A PC restart must not be presented as resolving
that record. Eddie's declaration that original Workroom jobs used only Echo/DSH
on this desktop remains the selected-eight scope; do not broaden it implicitly.

Further source trace: SessionAuthority._schedule invokes _drain; its claim-retry
path handles unknown_execution and may separately settle eligible unattended
automation. That additional path is not qualified by the initial method probe,
and absence of unknown_execution text in session_admission.py is not evidence
that the overall admission path is unguarded or fully qualified. The general
unknown native-recovery and bot retry tests remain limited to their inspected
methods. Do not turn them into a blanket full-startup non-replay claim.

Next implementation/evidence slice: define per-record retained scope from actual
store/route/workspace linkage, qualify every relevant startup/claim/adapter path
for those exact states, and retain all unrelated UNKNOWN history. Establish
covered local old-writer extinction plus restart-owner containment separately.
If any writer could still affect the selected workspace, keep the hold. Current
operator global queue guard remains unchanged; no exclusion, retirement or live
recovery is authorized by this design advice. Do not ask for a restart as though
these outstanding conditions are already satisfied.
