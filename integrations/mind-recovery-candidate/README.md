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


## Opt-in checkpointed host candidate (inactive)

CheckpointedLedgerCandidate opens an existing explicitly selected private source
and independently bound journal. It checks the source identity in read-only mode
before constructing the canonical Ledger, then checks current authenticated
history and source integrity while holding the authority. Missing source/history
are not initialized or silently adopted.

The host requires a stable operation_id for purge, retains canonical operator
authentication/confirmation, and uses the existing durable intent/acknowledgement
protocol. Its append hook refuses ordinary direct/base-class delete calls and
cross-thread use of another operation's permit. A reentrant per-host lock protects
the managed call. The shared helper accepts only the exact canonical purge bound
to that same ledger when the adapter selects a writer explicitly.

This is an opt-in trusted application API, NOT a sandbox against arbitrary Python,
SQL, same-login/admin access or an independently opened legacy Ledger. No existing
factory, service or runtime import has been changed. A restored plain Ledger must
not be enrolled as a production writer without the reviewed protected host. All
actual host factories and recovery handoffs must be enumerated/enrolled before
claiming every real writer is protected; that remains an activation prerequisite.

Bounded source review: current Ledger.purge appends authenticated history and then
updates source state; strict Ledger.restore separately replays history offline.
LifecycleWorker.apply refuses PURGED proposals; its transition method is metadata
state handling, not a canonical Ledger purge. Indexed module searches located no
other direct .purge caller, but the index reported stale globally; this is not
whole-machine or dynamic-call absence proof. The current runtime/factory inventory
remains unqualified. Canonical source is untouched.

Nine actual host checks passed in92.850s with private TEMP source/journal folders.
Earlier fixture failures are retained separately: Windows refused the initial TEMP
root permission change; canonical qualification also correctly refused an inherited
journal folder. The corrected fixture protects dedicated TEMP source/journal
folders explicitly; no production permission or privilege setting was changed.
A source-bound composed recovery/journal/host run is pending at
data/mind-checkpointed-host-qualified-proof-20261114.json. The earlier56case
retained-history/operator proof describes its earlier source version and does not
qualify this changed helper/host. No independent or live verification is claimed.


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
Canonical adoption table and next disposable-data acceptance checks are in
MIND-SETUP-READINESS.md under the same heading. Source-bound audit proof:
data/mind-factory-handoff-audit-20261115.json. No factory/service was changed,
no live store or keys opened, and no runtime writer enrolled by this audit.


## Offline recovery-to-protected-writer handoff (inactive)

restore_checkpointed_candidate now composes the existing verified checkpoint
restore with CheckpointedLedgerCandidate. It closes the ordinary restored handle
before reopening through the existing identity/history/authority checks. Failure
never returns an ordinary writer, never retries, and preserves attempted outputs.
Only deletion_history=None is accepted: the independently retained authenticated
chain is recovered into a new destination-local file. Even a current externally
supplied history is refused, so a recovered writer cannot append to the original
store's history through this helper. Explicit-history recovery remains available
through the separate offline restore candidate.

17 actual private TEMP host/handoff checks PASS with source hashes stable before
and after. This includes the existing9 host regressions and8 handoff cases: closed
plain handle before protected reopen, later managed deletion retained/replayed,
failed protected reopen with closed plain handle/preserved artifacts, wrong
identity, stale supplied history, unbound authority, current external history,
and authoritative deletion advancing in the close/reopen gap (stale copy refused).
The initial15-case pass is historical; the final changed source is qualified by
data/mind-protected-restore-handoff-proof-20261115-r2.json and its log.

This does not establish exclusive runtime ownership or retire another writer.
The caller must independently establish offline/exclusive source selection before
any real runtime use. No production factory/service imports this helper. Canonical
Mind, strict restore, operator bootstrap and read-only recall remain unchanged.
No live store, key, service, agent identity or automatic enrollment is activated.
No full Mind/Mesh suite or independent review is claimed. Remaining: reviewed real
factory adoption, runtime identity/authority/custody, source ownership/retirement,
operator invocation, and explicit live-setup/access approval.


## Earlier preview-first entry (archive settings superseded below)

operator_setup_entry.py exposes the existing complete setup journey; the default
only checks selected folder metadata/private ACLs and prints a preview. It does
not create folders or keys, alter permissions, contact services, or enroll agents.
Help needs no Mind import: python integrations/mind-recovery-candidate/operator_setup_entry.py --help

The reviewed canonical Mind package must be available on PYTHONPATH for preview
or setup. Supply explicit --directory, --authority-directory, --backup-directory,
--environment-id, --owner-ref, --authority-ref and --review-ref; no live paths or
environment are defaulted. Three existing private, empty, disjoint folders are
required. Omit --initialize for preview. No live invocation is approved here.

After separate owner approval only, --initialize additionally requires an
--approval-ref and a local interactive terminal. It displays the preview, asks
for CREATE EMPTY MIND STORE, then rechecks directory identities/emptiness before
calling the unchanged setup candidate. The approval reference/typed phrase are
deliberate-action checks, not an authentication system or proof that approval
actually exists. The recovery password goes only in the existing native secure
prompt, never a command argument, chat or output. A fixed inactive completion
projection omits keys/envelopes and requires the actual rehearsal receipt. Native
failure text is not echoed; outputs are preserved with no retry or cleanup.

9 actual entry checks PASS103.795s on source-stable code, including one complete
native TEMP setup/backup/restore journey; other checks cover preview/cancellation,
missing approval reference, noninteractive refusal, changed destinations, secret
error suppression and help. Existing operator code was unchanged; its earlier
suite is separate evidence. Proof:data/mind-operator-entry-proof-20261115.json.
No live paths, private permissions, keys or services were changed; no full Mind
or full Mesh result is claimed by these9 checks. Real authority/source selection,
exclusive runtime ownership and owner-reviewed initialization remain outstanding.


## Encrypted whole-backup candidate for exFAT E: (inactive)

The canonical MIND-RECOVERY-GUIDE already records E: as exFAT. A fresh metadata
check confirms C:/D: are NTFS and E: is exFAT; the live D:/App-Data/Onoes-Mind
folder remains empty/private. The temporary NTFS operator tests did NOT qualify
E: for plaintext backups or a private current journal. The earlier proposed
E: private-journal placement must not be used. No drive was reformatted and no
live folder, key, database, account, credential or service was changed.

encrypted_backup_candidate.py adds a trusted local export/import API using the
portable 7-Zip26.06 standalone x64 tool. The official extra archive and bootstrap
were verified against GitHub release SHA256 digests before use; the derived
7za.exe SHA256 is pinned in code. Nothing is installed globally or added to PATH.
Source: https://www.7-zip.org/download.html and
https://github.com/ip7z/7zip/releases/tag/26.06 . Format:
https://www.7-zip.org/7z.html . This uses standard AES-256 7z content/header
encryption, not a new crypto format or a claim of authenticated encryption.

Export reads only the four explicitly selected snapshot/metadata/encrypted-key/
history files from private NTFS storage, verifies their publication/context and
history prefix, and builds a fixed manifest in separate empty private staging.
The caller can select a snapshot basename; archive names normalize to snapshot.sqlite
and snapshot.sqlite.meta. All five entries must be encrypted with the expected
names/sizes. Every entry is read back in RAM and checked before the verified
ciphertext alone is exclusively copied to the selected .7z destination. A private
NTFS export receipt records its fingerprint. Existing outputs are preserved.

Import requires an independently selected expected archive fingerprint and exact
snapshot publication. It checks the complete fixed inventory and all manifest
hashes in RAM before writing fixed-name files exclusively into a private empty
NTFS destination. The external tool never extracts paths. An archive checksum or
copied journal is NOT proof of current deletion history. Canonical restore still
needs the separately bound current authority and reviewed source ownership.

Passwords go only over the hidden owned child's stdin, never command arguments
or environment. There is no password CLI, browser/MCP/Relay endpoint, download,
scheduler, startup registration or live-setup binding in this module. The caller
must supply a strong separately saved password through a reviewed local native
operator path; that connection is still outstanding. Python/child memory erasure
is not guaranteed. This trusted operator API assumes stable operator-controlled
directories; it is not a hostile-filesystem or same-login/admin security boundary.
Plaintext remains in private staging or RAM. Failure preserves attempted outputs
and performs no retry/cleanup. Cross-account/machine recovery is not qualified.

7 actual Windows tests PASS183.898s (runner elapsed184.056s), using real canonical
synthetic Mind snapshots, encrypted canonical key packages, actual E: ciphertext,
and private TEMP NTFS folders. Tests cover source loss and key recovery, a later
purge still absent after canonical protected restore, password absent from child
arguments, encrypted headers, wrong password, changed source/tool/archive,
existing output and wrong-store refusals. The original runner's marker parser
missed unittest's shared-line prefix after all7 tests passed. Preserved that
reporting failure; supplementary readback verified the SAME completed run, source
hashes and E: archive without a rerun. Proofs:
data/mind-encrypted-backup-proof-20261115.json and
data/mind-encrypted-backup-qualified-readback-20261115.json.

Proposed next layout, NOT enrolled: keep live data on D:, a separate private
current journal under %LOCALAPPDATA%/Onoes-Mind/Current-State on C: NTFS, private
snapshot/archive staging outside the live folder on D:, and only encrypted
milestone archives under E:/App-Backups/Onoes-Mind. The journal is current-state
storage, not a scheduled backup. No new C:/D: private directories were created.
This remains local-PC custody, not off-device/whole-PC rollback protection.
Next: reviewed secure local password/operator integration and actual layout/
permission/runtime binding approval. No live initialization is authorized.


## Archive-backed first-setup entry (inactive, supersedes earlier entry settings)

operator_setup_entry now requires the qualified encrypted archive path as part of
first setup. Preview remains read-only. The five explicit private empty disjoint
NTFS folders are data, current authority, first snapshot/rehearsal, archive work,
and archive readback. Additional required flags are --archive-staging-directory,
--archive-rehearsal-directory, --encrypted-backup and --archive-tool. The encrypted
destination's parent must exist; the destination must be absent and outside those
private folders. The pinned tool is checked before keys are created. No live paths
or passwords are defaulted; --help still needs no canonical Mind import.

After separately approved local interactive confirmation, the operator enters and
confirms the saved archive password through getpass's masked local input. Echoed
fallback raises an error; there are no password flags/environment/MCP/browser
inputs. Matching/valid passwords and rechecked folder/tool identities precede
native key enrollment. The existing native recovery-key screen remains unchanged.
The operator must retain the archive password and recovery-key password separately
in the password manager (they need not be the same). Never send them to an agent.

After the existing private NTFS setup/rehearsal closes, the entry exports and
verifies the encrypted destination, unpacks that actual archive into private NTFS
readback, obtains keys from that recovered encrypted key package, and performs an
actual protected empty-store restore against the separately held current authority.
Only after that handle closes does it exclusively write
setup-with-encrypted-backup-receipt.json and print setup_complete_inactive.
The older checkpointed-initialization-receipt is bootstrap evidence only. A later
archive failure explicitly reports that an empty store exists and overall setup
did not finish; no final completion, deletion, automatic retry or activation.

13 actual Windows TEMP entry checks PASS238.627s (runner238.816s), captured Python
and archive-tool hashes stable. The positive native journey uses the real E:
archive with original key/history and private-backup artifacts made unavailable;
its final receipt check proves the recovered handle is closed. It does not remove
the original empty source database. Other cases cover failure preservation,
password mismatch, echoed-input fallback refusal, existing archive, confirmation,
noninteractive/missing-approval refusal, changed folders, native cancellation,
secret error suppression, preview and help. Fixture passwords only. The unchanged
archive component's earlier7-case suite is separate evidence, not a combined full
Mind run. Proof:data/mind-encrypted-operator-proof-20261115.json.

The native getpass interaction still needs real operator keyboard acceptance;
fixture tests substitute only its input values and exercise the echo-fallback
guard. No live folder creation/ACL changes, keys, database, service, credentials
or memory connection were performed. Proposed C: journal/D: private staging/E:
ciphertext layout still needs exact owner review and custody approval. No PC or
app restart is required by this operator flow; automatic workers/Rook/Mind stay off.


## Reviewed empty support-folder action (not applied)

prepare_storage.ps1 prepares only absent empty support directories. Default is
read-only preview. It requires a bounded exact private JSON plan and its SHA256,
the current reviewed Windows owner, ordinary existing anchors, NTFS for private
folders, no overlapping existing data, and an explicit ordered list of all new
parents. Existing targets are never altered. Duplicate fields/targets, wrong
owner/fingerprint, out-of-anchor paths and reparse ancestry are refused.

Only after separately approved -Apply does it create the listed folders. Private
folders get exactly operator/SYSTEM/Administrators FullControl with inheritance
disabled, using the canonical folder action's ACL rules. No existing parent/data
permissions are changed. An optional ordinary encrypted-archive parent can be on
exFAT. It writes no key/database/credential/service or startup setting. WhatIf
performs preflight and creates nothing. Failures preserve partial empty folders
for review; no deletion, cleanup or retry. A stable operator-controlled filesystem
is required; this is not hostile concurrent replacement isolation.

9 actual Windows checks PASS21.913 seconds, runner22.05seconds, with captured
Python/PowerShell hashes stable. Tests use owned TEMP folders for actual apply
and canonical private-folder qualification. Existing target/permissions, owner,
fingerprint, anchor, junction and actual E: exFAT refusals are covered. The E:
case is refusal-only; no E: private target is created. Proof:
data/mind-storage-action-proof-20261115.json. This is not a full Mind/app test run.

The exact live proposal stays private under data/mind-storage-preparation-20261115.
It creates six private C:/D: parent/support folders and one ordinary E: encrypted
backup parent, leaving the approved existing D: data folder unchanged. No actual
support folders or permissions have been applied. Owner approval is required
before this action; folder approval never authorizes real keys/store/activation.
The original canonical prepare-private-storage.ps1 for the existing D: folder is
unchanged and must not be rerun. Actual no-change preview evidence and the script/
plan fingerprints are kept with the private proposal before requesting approval.
