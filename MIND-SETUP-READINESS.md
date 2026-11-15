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
