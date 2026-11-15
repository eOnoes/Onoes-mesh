# Inactive Mind checkpoint-recovery candidate

Eddie approved development/testing of the equal-history recovery proposal in this
chat. He did **not** approve live setup, key creation, memory access, a new authority
service, deployment or changes to the default recovery rule.

This module is deliberately outside canonical Mind. Nothing imports it from Mesh's
running app or Mind's operator host. There is no CLI, installer or startup hook.
Canonical Mind remains at `76c0273637ced688411960e067aabad6eaf4168e` unchanged.

## What the candidate implements

- A trusted-producer snapshot publication path registers exact snapshot/metadata
  hashes, store UUID, environment and authenticated deletion-history prefix.
- Recovery holds an authority lease and checks its current acknowledged head. It
  allows equal history only with the matching independently registered snapshot.
  With newer history, it replays the complete authenticated tombstone chain in RAM
  before exposing the restored ledger. A stale but valid history is refused.
- The snapshot bytes and metadata are captured before writing. The unchanged
  canonical audit-chain and deletion-chain verification methods are reused.
- New targets are reserved exclusively. Existing databases/recovery sidecars are
  preserved. A late failure closes and retains its attempted target; it never
  returns that ledger as a usable result or retries over it.
- Purge validates operator authority before admission, durably blocks recovery
  before mutation, and reports completion only after exact checkpoint acknowledgement.
  A lost acknowledgement stays blocked across fixture restart. An acknowledged
  retry uses the same operation identity and receipt; divergence is refused.

SQLite's documented deserialize limitation requires journal-mode bytes18/19 to be
normalized in the **RAM copy only**. Registration and matching use the original
unmodified snapshot bytes. Source: [SQLite deserialize documentation](https://www.sqlite.org/c3ref/deserialize.html).
No plaintext staging snapshot or key file is created by the candidate.

## The trust boundary is still a deployment gate

`authority.hold()` must provide a stable current checkpoint and exact snapshot
registration while excluding managed checkpoint writers. `begin_purge()` must
durably block recovery before the underlying mutation, and `ack_purge()` must
durably bind its exact operation and resulting head before success. The lease's
exit/commit must succeed before a restored ledger can be returned.

The test authority is a separate SQLite fixture with real transactions, persistent
pending intents and receipts. It is **not a production authority**. Its initial
current source is explicitly selected by the test. Copying this fixture into a
live folder, setting a JSON trusted flag, providing a review string, signing a
backup, or restoring all its files together does not establish currentness.

No rollback resistance is claimed against the same Windows login, an administrator,
whole-PC restore, or replacement of both backup and authority. No new protection,
account, secret, service or independent storage was provisioned. A real provider
must be separately selected, threat-modelled and qualified before this candidate
can be integrated or used on real/private data.

All deletion writers must participate in the same protocol. A managed purge is
excluded by a held authority transaction; an unacknowledged/unmanaged change that
is observed in the supplied history fails the head check. That is not proof of
global exclusion of arbitrary writers or prevention of a malicious writer outside
the authority contract. Restored runtime ownership/concurrency and private output
storage permissions remain separate deployment requirements.

## Qualification

From the current Mesh checkout, with canonical Mind at `D:/Dev/Onoes-Mind`:

```powershell
python -B -m unittest discover -s integrations/mind-recovery-candidate -p test_checkpoint_candidate.py -v
```

**23 candidate tests passed**, including empty/populated equal-history restore,
actual canonical recall, later-purge replay, stale valid/truncated/corrupt history,
missing registration, wrong identity/environment/keys, altered metadata, duplicate
and divergent purge IDs, lost acknowledgement and fixture restart, exclusive
restore/purge fencing, malformed admission, captured-byte verification, unauthorized
admission refusal, late failure preservation and unchanged default refusal.

**Five unchanged canonical Phase1B tests passed** separately. No full Mesh or full
Mind suite was rerun for this isolated, unwired candidate. Earlier red logs are
retained: they exposed WAL RAM handling, fixture connection cleanup and a fixture
key rejected as a placeholder. Those were corrected without changing canonical code.

Private evidence:

- `data/mind-checkpoint-candidate-qualified-tests-20261114.log`
- `data/mind-checkpoint-canonical-regressions-20261114.log`
- `data/mind-checkpoint-candidate-proof-20261114.json`

## Next integration slice

Review the producer/authority contract and select an independently trusted current
checkpoint source. Qualify its real persistence, permissions, rollback threat model,
every deletion-writer entry point, crash/reconciliation behavior and private restore
ownership. Then integrate deliberately with the operator host and run actual
end-to-end acceptance. Do not change the frozen core, its pins, the existing strict
default or any live binding as a side effect of this candidate.

No live initialization or connection is recommended solely by these test results.
