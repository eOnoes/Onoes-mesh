# Onoes-Mind memory provider for Hermes

This source candidate uses Hermes's supported MemoryProvider plugin seam. It is
not installed in Echo's real profile and does not activate any private home.
The existing shared-project MCP reader remains independent.

## Behavior

- One instance binds to one reviewed Windows Hermes profile and canonical Mind
  store/agent home. No model-supplied agent, scope, store, or credential choices.
- Selected memory and personality/profile facts use `onoes_memory`. There is no
  automatic raw transcript ingestion, native-memory import, or second memory DB.
- Every meaningful turn reads current private profile facts and matching memory.
  Results carry canonical record/revision/provenance and snapshot IDs, are bounded
  whole entries, and are reference data. Corrections and forget are visible on
  the next read. Forget suppresses recall; owner hard purge remains separate.
- Offline, revoked, misbound or changed profiles fail explicitly. No cached or
  native-memory fallback. Both native memory flags must be false before the
  plugin reports available; registering an external provider alone is insufficient.
- The optional `shared_project_tool` only names the separately authorized MCP
  reader in static instructions. Automatic shared-project prefetch is not supplied.
- Write intent is sealed with current-user Windows protection before sending.
  Uncertain outcomes retain the exact event/payload for deliberate `pending` and
  `reconcile`; there is no automatic resend. Acknowledged/refused intents retain
  payload-free receipt/hash metadata. This outbox is not a recall authority.
- A native kernel lock serializes outstanding writes across provider instances.
  Profile/source pins and exact store/home fingerprints are checked before use.
- Subagent, cron and flush contexts cannot read or write this primary-agent home.
  Same-account scoping is not isolation from hostile code under that Windows user.

## Integration contract

Requires Mind's private-home transport with exact binding fingerprints, initially
qualified at Mind commit `63c6391`. The host embeds AgentHomeServer over its already
open canonical ledger and shares its existing writer lease and serialization lock.
Do not start a second canonical writer or let an agent choose a database path.

Install package contents under the reviewed profile's `plugins/onoes_mind/` only
as part of a separately reviewed live cutover. `memory.provider` selects
`onoes_mind`; `memory.memory_enabled` and `memory.user_profile_enabled` are false.
`memory.onoes_mind` contains exactly `profile_path` and its `profile_sha256`.
The private owner-reviewed JSON profile schema and accepted fields are enforced
in `config.py`. No credentials belong in config or source. Windows home custody
holds the purpose-bound credential in a protected directory, separately from the
canonical store and intent journal.

The profile pins its Hermes home, agent ID, complete Mind SDK source hashes,
reviewed RecallBinding, custody/journal directories, exact loopback home endpoint,
review reference, context byte budget and optional shared-project tool name.
The SDK loads under a source-specific namespace to avoid silently using a
different already-imported Mind version in Hermes.

## Native acceptance

Set `MIND_SOURCE` and `HERMES_SOURCE` to the reviewed Mind and installed Hermes
source roots. Run `test_provider.py` with pytest in Hermes's matching Python.
Use a fresh `--basetemp` beneath an existing disposable `data/` directory. The
suite creates only synthetic ledgers, credentials and Hermes profiles; private
test directories receive owner/SYSTEM/Administrators permissions. It imports the
actual Hermes loader and MemoryManager, sends actual loopback requests and uses
actual Windows encryption/locking. No model/provider calls or live services.

Qualification does not authorize real credential enrollment, native memory
migration, startup/profile trust changes or live activation. Next useful slice:
embed the home service in the existing canonical writer and rehearse one-profile
cutover/rollback on copies before presenting the exact live plan.

November 24 qualification: all 15 native acceptance cases passed (132.60 s),
then the complete selected-fact/correction/forget path passed separately with
Hermes's default 8-second prefetch bound (37.99 s for fixture and full path).
The initial test runner lacked pytest; the existing matching Python 3.11 runner
was used without installation. A disposable path-layout error was corrected
before the passing runs. Private test credentials/databases are not source.
