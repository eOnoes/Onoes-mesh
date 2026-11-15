# Onoes-Mind setup readiness

November14 Chicago / November15 UTC,2026. Owner: Eddie. Operators: Echo and Nims.

## What is ready

The existing protected setup path passed12 tests on the current Windows session.
It protects fixture keys before creating an empty fixture database, keeps the
store identity consistent, refuses existing data, cancels without creating a
database, and preserves attempted files after a later failure. These tests used
temporary private folders, synthetic keys and fixture passwords only. The native
test window was withdrawn. No real password or live Mind data was used.

This requalifies the prepared host at Mind commit76c0273, not live initialization
or recovery. No live D: folder inspection or modification was needed.

## What blocks recommending real setup

A separate synthetic probe made a valid empty backup with deletion sequence0.
Backup verification passed. Canonical restore refused that backup because the
current deletion history was unchanged, rather than strictly newer. It created
no restore destination and left the snapshot intact.

This is the already documented recovery-policy gap, now reproduced on the
current checkout. Creating a fake deletion, loosening the comparison, trusting a
backup timestamp or calling an unreviewed alternate restore would not solve it.
Do not create live keys/store or call Mind ready while this remains unresolved.

## Concrete next proposal: recovery-policy amendment, code/test only

Prepare and qualify the amendment already described in canonical
`MIND-RECOVERY-GUIDE.md`, section Proposed equal-history amendment.

- Allow unchanged-history recovery only when separately trusted current evidence
  proves that exact store/environment/snapshot deletion head is still current.
- A valid HMAC, adjacent checksum, file time or copied backup is not proof of
  freshness. Define who owns the current checkpoint and what rollback/corruption
  threats it actually withstands before calling it trusted.
- If a newer deletion exists, verify the complete chain and replay every later
  tombstone. Refuse missing, stale, mismatched, corrupt or rolled-back evidence.
- A deletion cannot be reported complete before its checkpoint is durably
  acknowledged. Test interruption around that acknowledgement.
- Default legacy refusal remains. Do not alter the frozen Ledger.restore core or
  existing qualification pins silently. An inert candidate is not activation.
- Use disposable data to prove fresh/unchanged success with current proof, stale
  history/checkpoint refusal, later purge replay, wrong store/environment refusal,
  corrupt/truncated chain refusal and crash/retry behavior.

The canonical guide explicitly leaves this policy decision to Eddie. This is a
request to approve preparing/testing that bounded amendment for review, not a
request to initialize the real store, create live keys, grant access, install a
service or enable Mesh memory. Any implementation must be separately qualified
against the real chosen checkpoint authority before deployment.

## Later operator journey, after recovery is qualified

1. Review the exact empty destination D:/App-Data/Onoes-Mind, owner/environment,
   protected key custody and backup/recovery plan. Approve real initialization
   separately; the prior folder approval alone is insufficient.
2. Eddie enters a unique recovery password in the local secure prompt and saves
   it in his password manager. Never put it in chat, Relay or agent output.
3. Protect the keys before creating the empty ledger; retain the identity and
   initialization receipt. Do not issue agent credentials or start memory access.
4. Back up matching data, keys and authoritative deletion evidence to the approved
   private location, then prove recovery into a separate folder.
5. Review/enroll one project scope and purpose-specific identities before a
   separately authorized live connection. Recall, project sync and MCP tool
   permissions are distinct contracts.

## Evidence and limits

- `data/mind-operator-setup-requalification-20261114.log`:12PASS,55.023seconds.
- `data/mind-setup-requalification-proof-20261114.json`: source and log hashes.
- `data/mind-fresh-backup-policy-proof-20261114.json`: valid snapshot/refused
  unchanged-history restore; no output database or policy bypass.
- Canonical Mind source remained unchanged; no full Mind suite was rerun and no
  production concurrency, cross-account recovery or live-memory access is proven.

Mesh stays usable. Its historical recovery holds, paused worker gate, pending
phone Relay acceptance and first-local-release18/21 state are unchanged. No PC
restart or model/agent task is part of this preparation.

## Approved development result - November15,2026

Eddie approved bounded recovery-policy development/testing in this chat. An
inactive candidate is now under integrations/mind-recovery-candidate.23actual
candidate checks and5unchanged canonical Phase1B regressions pass. The strict
default and frozen canonical source remain unchanged. No live keys/store/access.
The synthetic authority demonstrates protocol behavior, not production currentness
or whole-PC/same-login rollback resistance. Real authority selection/qualification,
private runtime storage and operator integration remain before live setup. Read
the candidate README and private data/mind-checkpoint-candidate-proof-20261114.json.

## Persistent authority development result - November15,2026

The inactive candidate now has an explicit-create/open private local journal
provider with store/environment/authority UUID and physical-file binding, durable
purge intent and acknowledgement, current-head validation and transaction-scoped
leases.38composed checks PASS122.005s, including actual temporary Windows ACLs
and owned-child exits before/before-COMMIT/after acknowledgement. No PC restart
or real data involved. Copied/missing journals are not silently adopted/recreated.
Proposed current-state location under the E: Mind root is for review only; runtime
updates on deletion, real permissions/independent source selection and all real
writers/host integration remain unqualified. It does not protect against rollback
of the journal itself, same-login/admin replacement or a whole-PC rollback.
See candidate README and data/mind-persistent-authority-proof-20261114.json.

## Current first-time operator integration

The inactive operator_setup_candidate joins the canonical protected native key
enrollment and empty-store initializer to the separate private journal, first
registered backup and actual unchanged-history restore rehearsal. Preflight
requires three empty, disjoint private directories; no permission is changed by
the API. The first backup includes SQLite/metadata, the encrypted key package,
matching deletion history and restore notes. Rehearsal reads the exported key
package/history rather than requiring originals on D:. Keys are never returned
in a receipt. Final success is saved only after source/rehearsal handles close;
activated/runtimeEnrollment/recoveryQualified remain false.

A fresh names/ACL-only check found D:/App-Data/Onoes-Mind empty and privately
permissioned; no database/key content was opened and no Ecurrent journal folder
was created. See data/mind-live-folder-metadata-preflight-20261114.json.

Before live memory use, retain the full acknowledged current deletion chain
independently: the present journal has heads/receipts, not a recoverable complete
chain. Initial empty-history recovery cannot qualify after-deletion recovery if
the newer original history is lost. No live setup approval is requested by this
operator code or its temporary-data tests. Current test proof is recorded in
data/mind-whole-operator-qualified-proof-20261114.json once the source-bound run
finishes; earlier pre-export results remain separate.

Current whole-journey qualification completed:9PASS323.270s, source-stable before/
after hashes; first backup includes encrypted key package/history and actual
rehearsal succeeds with the original key/history copies temporarily unavailable.
The earlier38recovery/journal source hashes still match their proof. These are
separate checks, not a claimed47case combined full-suite run. Live Mind stays off.
Final evidence:data/mind-whole-operator-final-qualification-20261114.json.


## Full deletion-history retention candidate - qualification pending

The inactive v2 journal now retains the complete acknowledged chain atomically
with its head and purge receipt. Recovery can obtain the held chain even when
the original database/history are unavailable, authenticate it through canonical
Mind code, replay deletions, and create a fresh recovery-local history. The earlier
head-only limitation is addressed in candidate code, not yet live-qualified.
See integrations/mind-recovery-candidate/README.md. Current composed proof will be
data/mind-retained-history-qualified-proof-20261114.json; older 38/9 proofs are
historical and do not qualify changed sources. Live setup, all real writer binding,
independent review, actual current-history placement/custody and operator approval
remain outstanding. No activation or new real key/store is authorized.


Full-history candidate qualification completed:56checks PASS422.497s in one
composed run (23recovery,9operator setup,24persistent journal). Candidate and
canonical dependency hashes stayed identical before/after and at final inspection.
Actual cases include two later deletions followed by source-history loss, original
database/history unavailability, full-chain retention after owned process exit,
missing/stale retained history, divergent acknowledgement, and an internally
consistent forged head/hash rejected by canonical HMAC authentication before any
restore output. Existing destination history is preserved.
Evidence:data/mind-retained-history-qualified-proof-20261114.json and composed log.
This supersedes the pending qualification above. No independent reviewer, full Mesh
or full Mind suite, live placement/permissions, real writer enrollment or activation
was performed. The unchanged canonical restore remains strict. The next step is
reviewed operator/real-writer integration; no live initialization is implied.


## Protected writer-host preparation

An inactive opt-in CheckpointedLedgerCandidate now makes the ordinary host API
require the managed deletion path and stable operation IDs. Existing canonical
Ledger/factories, services and restore core are unchanged. Nine temporary host
checks passed; composed regression qualification is pending. See candidate README
and data/mind-checkpointed-host-qualified-proof-20261114.json. This is not a
whole-machine writer inventory or security boundary against arbitrary Python/SQL.
Every real factory and restored writer must still explicitly adopt the reviewed
host before live memory can be considered protected. Live setup stays off.


Protected-host qualification completed:56checks PASS257.144s in one composed
run (23recovery,24persistent journal,9host). All candidate/canonical dependency
hashes were stable before/after and at final verification. This is a different
56case suite from the earlier retained-history/operator run: the native operator
setup suite was not repeated. Its unchanged implementation remains separately
evidenced; no combined full-Mind or full-Mesh pass is claimed. Proof and log:
data/mind-checkpointed-host-qualified-proof-20261114.json and composed-tests log.
The actual Mesh service was read-only checked running/healthy under its named
owner receipt. All live services, canonical Mind source and activation gates stay
unchanged. Next local priority: remaining Mesh release blockers; retain the Mind
operator/factory adoption requirement for the later approved live connection.


## Source handoff inventory - November15,2026 (inactive)

Bounded source audit at Mind76c0273 / Mesh1cc75c0. This is an adoption map,
not production writer enrollment or permission to initialize/connect Mind.

| Path / symbol | Current behavior | Required adoption |
| --- | --- | --- |
| Mind store_init.initialize_new_ledger | Returns a plain Ledger through __new__/__init__, not Ledger(...) | Keep bootstrap private; close it before the separately reviewed protected runtime opener. A constructor-only search misses this factory. |
| Mind store_init.restore_new_ledger | Strict reviewed-history restore returns a plain Ledger | Preserve strict default; recovery output is not automatically a runtime writer. |
| Candidate restore_checkpoint_candidate | Verified checkpoint restore returns a plain writable Ledger | Add an explicit inactive restore-to-protected-host handoff; close plain handle before returning protected handle. Never fall back to plain Ledger on failure. |
| Candidate initialize_checkpointed_candidate | Plain bootstrap and restore rehearsal; closes both before receipt; runtimeEnrollment=false | Keep setup/rehearsal offline. Later runtime enrollment must explicitly reopen via protected host, not reuse bootstrap handles. |
| Candidate CheckpointedLedgerCandidate | Checks private files, source identity, current history and bound authority before writable use | Reuse this existing opener; no second memory store or new security authority. |
| Mind recall_http.ReadOnlyRecallLedger | mode=ro and query_only=ON; separate read-only recall path | Preserve read-only connection. Do not replace with a writable host. Reviewed store identity/scope binding remains separate. |
| Mind bridge.BridgeServer / worker.SyntheticWorkerAdapter | Accept injected Ledger; bridge has test-runtime defaults | Future runtime composer must supply reviewed writer and real identity; these classes are not deployed-writer evidence. |
| Mind pre_runtime_campaign / scripts/run_performance_campaign | Plain constructors in synthetic/performance fixtures | Keep fixtures distinct from runtime enrollment; passing them does not qualify a live writer. |

Next bounded implementation: an INACTIVE handoff around existing checkpoint
restore and protected opener, using disposable data only. Acceptance must prove
that the plain restored handle closes before protected reopen; a later managed
purge is retained and replayed; wrong identity, authority or stale history refuses
handoff; failed reopen preserves outputs without returning an unprotected writer;
and no service/agent access or automatic runtime enrollment occurs. A recovered
copy must not silently become a second active writer: approved source selection
and original-writer retirement remain separate runtime gates.

Audit limits: exact key symbol bodies were fresh, but early global searches
reported stale index and the reference tool ignored file_pattern. This is a
bounded source inventory, not whole-machine/dynamic-call absence proof. Canonical
Mind code, strict restore, live services and all activation gates are unchanged.
No tests rerun for this documentation-only audit; prior56-case results retain
their original scopes. Private source-hash proof:
data/mind-factory-handoff-audit-20261115.json.


## Offline protected restore handoff - candidate qualification

The restore-to-protected-host implementation proposed in the inventory above is
now implemented locally and remains inactive.17 temporary host/handoff checks pass
on source-stable code. It closes the plain handle before protected reopen, uses
only retained history into a new recovery-local file, refuses shared external
history and rechecks an intervening deletion. Failed reopen preserves artifacts
and returns no unprotected writer. See candidate README and private proof:
data/mind-protected-restore-handoff-proof-20261115-r2.json.

This advances the bounded recovery handoff, not real factory enrollment or
exclusive writer retirement. Canonical Mind, operator bootstrap, read-only recall
and services remain unchanged. No live setup/access, keys, credentials, PC restart,
model operation or paid agent task. Full Mind/Mesh suites were not repeated.
