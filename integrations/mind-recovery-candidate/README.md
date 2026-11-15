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

## Persistent local journal candidate

`persistent_authority.py` now supplies a concrete inactive authority implementation.
Creation is explicit, requires an empty privately permissioned directory and an
explicitly selected canonical producer, and returns a binding to the journal's
authority UUID, Mind store/environment and physical file identity. Opening never
creates a replacement file or adopts a copied journal under the old binding.
It reuses Mind's private-storage qualification; it changes no ACL itself.

Every operation uses a transactional current head. Pending purge intents and exact
completion receipts are durable. Recovery holds the same write exclusion as the
managed producer. Required logical state is checked in addition to SQLite integrity;
a missing or malformed head is not accepted as an empty/current journal. Leases
expire when their transaction exits and cannot be used afterward.

The private journal tests use real temporary Windows ACLs and owned child processes
that deliberately exit before acknowledgement, immediately before its SQLite
COMMIT, and just after successful acknowledgement but before a response. They do
not simulate a disk power failure inside SQLite's engine or restart the PC.

### Proposed placement for later owner review; no directory created

An operator-managed current-state directory outside all dated restore packages:
`E:/App-Backups/ONOes-Mind/CURRENT-CHECKPOINT/current-checkpoint.sqlite`.
This proposal uses the already chosen separate E: drive but selects no live trust
root and changes no permission. A private directory and its retained binding need
separate review before use. Do not treat the ordinary backup root's existing
permissions as sufficient, or restore this current journal along with a dated
memory snapshot and call it current evidence.

The journal must update whenever a managed deletion occurs; those are runtime
safety writes, not periodic backups. That behavior must be explicit in activation
approval. Ordinary backups remain manual/milestone-only; no schedule was added.
If the current journal is lost, replaced, uncertain or cannot be independently
identified, recovery stays blocked. There is no automatic fallback to an older
archived journal or a newly generated identity.

Scope: privately retained, separately selected current state protects the intended
data-only restore journey and managed-operation interruption. The provider still
cannot establish freshness after rollback of the current journal itself, replacement
by a privileged/same-login writer, or loss/rollback of the whole PC. A file UUID and
HMAC do not solve that. Stronger threats require a separately protected authority
and explicit operational design; they are not silently claimed here.

Next: qualify actual placement/permissions and bind every real deletion writer to
this protocol, then qualify the operator-host integration in disposable data.
No real journal, keys, memory store, agent grant or service has been provisioned.

## Inactive first-time operator journey

`operator_setup_candidate.py` joins the prepared native key enrollment, empty-store
initialization, separately bound journal, first registered backup and an actual
unchanged-history restore rehearsal. All three directories must already exist,
be privately permissioned, empty and disjoint. It changes no ACL and has no CLI.

The first backup includes the snapshot, matching metadata, exact encrypted key
package (portable password protection plus current-account runtime protection),
matching deletion history and human restore notes. The rehearsal reopens keys
from the exported encrypted package and reads the backup's history. It does not
silently depend on the originals remaining on D:. No raw key or password is
returned in a receipt or written to the backup.
The snapshot itself is ordinary SQLite, not password-encrypted by the key package;
the backup directory's private permissions are required to protect its contents.

Cancellation creates no ledger/journal/backup. A later failure preserves its keys,
store, journal or snapshot for inspection and records no final success receipt.
The successful candidate receipt is saved only after the source and rehearsal
connections close. It explicitly has `activated=false`, `runtimeEnrollment=false`
and `recoveryQualified=false`; `candidateRehearsal=PASS` is not live qualification.

This first-time journey is for an EMPTY store with no principals or memory records.
It is not a general backup scheduler or a live recovery command. The real D: folder
was checked by names/ACL only and remained empty/private; no live key/store file
was opened. No actual E: checkpoint or initialization-backup directory was created.

### Remaining history-retention requirement

The journal currently retains heads/receipts, not the complete tombstone log. The
initial backup copies its matching history, but after later deletions that copy
can be stale. If the newer authoritative history is lost, a hash in the journal
cannot reconstruct it. Recovery must refuse instead of resurrecting forgotten
records. Before any live memory records, retain the complete acknowledged deletion
chain independently and qualify recovery after loss of the original data/history.
The empty-store rehearsal must not be presented as proof of that later journey.

Real setup still needs explicit owner approval for protected keys and destinations,
local owner password entry/custody, the actual current-history trust/retention model
and a reviewed operator invocation. No service or agent grants are included.

### Whole-journey qualification

9operator checks passed on the final source in323.270seconds. The runner hashed
its candidate and canonical dependencies before/after; all stayed unchanged. The
checks cover the native encrypted enrollment through actual backup-only restore,
cancellation, occupied/overlapping folders, journal/rehearsal/late-receipt failure
preservation, and closure before the final receipt. The backup-only test parks
the original key/history files during actual restore.38prior recovery/journal
checks remain separately evidenced with their implementation sources unchanged.
No full Mesh/full Mind suite or real setup was run.
Private proof:data/mind-whole-operator-final-qualification-20261114.json.


## Retained full-history candidate (development, not activated)

The v2 journal stores the complete acknowledged deletion-history bytes alongside
its head. Initialization captures the canonical verified chain. Managed purge
acknowledgement requires the complete successor chain, verifies hash, line count
and exact previous-byte prefix, and commits chain/head/receipt together. Missing
or inconsistent retained bytes refuse journal open; v1 is not silently migrated.
The producer authenticates the exact bytes with Mind's canonical verifier before
acknowledgement. This provider is still a trusted internal boundary, not a public
API that accepts arbitrary caller-provided heads.

Passing deletion_history=None to the inactive restore candidate selects the held
journal's immutable retained bytes. Restore re-authenticates those bytes with the
canonical HMAC-chain verifier, checks the independently registered snapshot, and
replays deletions in RAM before reserving any destination. Only then does it write
a new fsynced recovery-local history beside the new restored database. Existing
outputs are preserved; later failed outputs remain for inspection. Explicit-path
restore continues to require that supplied history match the current journal.

This supersedes the implementation gap above, subject to the pending composed
qualification. It does not qualify a live E: journal, protect against rollback of
the journal itself or whole-PC loss, enroll real deletion writers, or grant Mind
access. The previous 38/9 proofs describe their historical source versions; they
do not attest to these changed sources. Current proof, after the run completes:
data/mind-retained-history-qualified-proof-20261114.json. No real database, keys,
services, private permissions or scheduler were changed.


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
