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
