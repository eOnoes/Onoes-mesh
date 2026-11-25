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
  It selects up to eight literal keywords from conversational wording, removes
  filler/duplicates, and ranks alternative matches inside that private home.
  Query selection is bounded to 512 characters. Explicit tool recall retains
  ALL-term matching by default; `match_mode: "any"` opts into alternatives.
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

Requires Mind's private-home transport with exact binding fingerprints and ranked
alternative-keyword recall, qualified at Mind commit `0fe0e10`. The host embeds AgentHomeServer over its already
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

## Existing protected writer attachment

The Mesh `NativeProjectSyncHost` candidate accepts an explicit tuple of reviewed
`agent_home_bindings`. Its default remains empty. When selected, it constructs
the private homes over the same already-open CheckpointedLedger, with the same
kernel-held writer lease. Project and home HTTP handlers share `writer_lock`,
including project authorization/readback. Trusted direct owner operations on the
running ledger must also hold that lock.

All store/home bindings are validated before either listener starts. If attachment
or listener startup fails, both listeners are retired before the ledger and lease
close. Normal close follows the same order. Readiness includes both selected
interfaces; `agent_home_options()` returns only the current endpoint and binding
fingerprints, never credentials. It does not enroll agents or issue credentials.

Existing process/startup profiles do not expose this optional parameter, so this
source change cannot enable private homes through an old service approval. The
actual profile upgrade, protected home enrollment, backup and one-profile Hermes
cutover remain a separate reviewed rollout. No native memory is imported by this
attachment. `test_writer_host.py` exercises the real protected writer on synthetic
stores and requires `MIND_SOURCE` to identify the new reviewed Mind SDK explicitly.

Writer qualification: all six native attachment/recovery checks passed in
377.24 seconds. All 35 existing writer/event/HTTP cases are covered by passing
runs (eight initial passes and 27 corrected-environment passes, plus eight
subtests). The initial regression run stopped at a child import failure; the
child did not inherit Mind's source path. Direct reproduction confirmed that
cause, and the failed plus unrun cases passed after setting `PYTHONPATH` to the
reviewed source. This is composed coverage, not a claimed clean single 35-case
invocation. No live service was changed.

## Exact home startup profile

The existing project-service launcher now accepts an explicit v5 profile. It
preserves the original project enrollment, store/key/history paths and project
grants, and requires the separate `run_agent_homes` action plus an exact
agent/home fingerprint and fixed loopback-port approval. The runtime cannot
enroll itself. Existing schemas still reject private-home fields/actions.
The reviewed SDK upgrade must retain identical migrations; candidate-file changes
are limited to the attached writer and shared-lock HTTP modules. The operator
validator and unrelated recovery modules retain their enrolled bytes.

The exact v5 profile passed 18 native checks under Python 3.11, then the final
19-case suite under production Python 3.14. The owned process proof starts with
owner-enrolled disposable access, serves selected private facts and project
receipts, restarts at the same private endpoint, and rolls back to project-only
service with the original project receipt still stable. Both legacy release and
relocation checks passed separately. Mind's stable-port transport passed 26
checks under each Python version. The long 3.14 process check emitted a scheduled
180-second diagnostic stack while checking Windows permissions and later passed;
that snapshot did not terminate the run or trigger a retry.

Live Echo setup remains unactivated. A realistic conversational recall check
exposed a provider query issue: passing the whole sentence to literal AND search
missed the saved fact. Follow-up qualification corrected it with bounded keyword
selection and ranked private alternatives; the exact previously failing question
then passed through the actual Hermes loader/manager. Mind's 77 private-home and
transport checks passed under production Python, and all 16 provider checks passed
with the normal timeout. Native saved memory/preferences still require a finite
reviewed import/cutover; no raw transcript migration is proposed.

## Finite curated-memory bootstrap

Mind's owner-side `curated_home_import` contract is qualified at `71ab025`.
It reads only the two approved Hermes MEMORY.md and USER.md files, pins their
identities and raw hashes, and writes one private profile snapshot through the
existing AgentHome API. Keeping the initial curated notes/preferences together
preserves the previous always-loaded context atomically. The combined 8 KiB
bound rejects oversized input without truncation. Original files remain intact;
new memories continue to use ordinary individual records.

Import is not a model-facing action. It needs the reviewed owner and enrolled
home credentials, rechecks the source snapshot before writing, and uses a stable
one-time event. Retry cannot overwrite later corrections/forget or import changed
legacy files as a new authority. The receipt describes the historical import.

All 95 Mind import/home/transport cases passed under the writer's Python 3.14.3.
The complete 17-case provider suite passed under both the earlier test interpreter
and Echo's exact hidden-launcher Python 3.14.9 (185.44 s). The new integration
checks fresh provider sessions after retiring only disposable native test files,
then proves that a canonical correction becomes current. Source bootstrap/import
is inactive until the finite live plan is approved. Actual private file contents,
home credentials and Echo's memory configuration have not been changed.
