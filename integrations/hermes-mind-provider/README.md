# Onoes-Mind memory provider for Hermes

This adapter uses Hermes's supported MemoryProvider plugin seam. Copying this
package does not enroll an agent or activate a private home. Live deployment
status and exact access approvals belong in the operator's private checkpoint.
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

## Shared-reader compatibility

When this SDK also serves Mesh's shared reader, use Mind `baea45b` or later.
Internal search/private-home results retain revision IDs, while the original
shared-recall v1 HTTP response keeps its original nine record fields. Test actual
HTTP output with Mesh's existing strict validator; an empty response alone misses
this compatibility defect. No grant or credential change is needed for the fix.
Keep deployed SDK directories immutable. A server-only compatibility release can
retain a separately pinned older private client when the home protocol/binding
fingerprint is unchanged; verify current recall after the reconnect.

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

## Owner-side configuration switch

`owner_profile_switch.py` is an inactive installer helper, outside the plugin.
It never stops a gateway, enrolls a credential or imports memory. The approved
installer must first qualify the complete provider/source binding, stop Echo
through its existing supported controls, and keep other configuration writers
stopped throughout the operation. Its required quiescence callback must return
True; unknown or busy state refuses the write.

Preparation pins the original raw configuration and the one Echo provider profile.
Installation saves an exclusive private backup, checks both pins again, then uses
Hermes's existing comment-preserving one-document writer. Only four memory
settings change; credential templates, the shared-project MCP reader, Telegram,
model settings and unrelated memory settings are retained. No merged defaults or
expanded environment secrets are written back. Prepared config payloads stay out
of representations and metadata. The helper is not a model-facing tool or a CLI.

Rollback requires the exact installed config digest and retained backup. It
restores the original settings using Hermes's supported replacement API, preserving
comments; the original raw bytes remain in the private backup. Drift, an existing
backup or an uncertain interrupted attempt is preserved for inspection, not
silently retried or overwritten. These checks are not a cross-process CAS lock;
the installer owns the exclusive maintenance window and durable phase evidence.
Live setup remains separate from disposable source qualification.

## Composed Echo rollout rehearsal

The real owned-process rehearsal passed as one test under Echo's Python 3.14.9
in 822.67 seconds. It first saved a project receipt on the project-only service,
stopped that owned writer, and imported two disposable curated files through the
existing canonical writer lease. The v5 service then served that private home to
fresh actual Hermes memory managers. A new selected fact and the imported profile
survived a writer restart at the same private address.

The check restored the original Hermes configuration, revoked only the new Echo
credential, retained both canonical records and original native files, and restarted
the original project-only service. The original project event returned the same
receipt; the withdrawn private endpoint was unavailable. No model, real gateway,
Docker container or actual private memory was used. A future live cutover still
needs its owner approval and an idle Echo gateway reload; this proof is not a
claim of a deployed private home.

The initial composed attempt reached restart recovery, then failed in its test-only
revocation assertion because it called a nonexistent snapshot method. Its original
source/XML are retained. The corrected test uses the supported recall API, and
reads restored configuration through Hermes's supported raw-config reader. The
next attempt was cancelled at Eddie's request for Docker relocation. The final
fresh run above passed all five recorded phases without skips or retries inside
the run. These are one composed test's phases, not five independent test cases.

## Owner-side current handoff refresh (inactive)

The v6 writer profile can attach one already admitted shared handoff to its
existing private-home listener. It requires the explicit run_handoff_refresh
action and exact handoffRefresh target fingerprint as well as the existing home
approval. Earlier profile versions cannot acquire the endpoint. The running
service creates no principal, credential, scope, schema or additional listener.

handoff_drop_candidate.py is a local owner client, not a model-facing tool.
Its reviewed profile pins the SDK/client sources, one Nims handoff, existing
Windows operator custody and separate private input/journal folders. It reads
only a deliberately selected JSON envelope in that input folder. The envelope
contains expected_revision_id, event_id, document and review_ref. Markdown may
be carried inside the versioned document; identity and document revision remain
canonical. Credential values never belong in arguments, output or handoff files.
This local owner credential is not a cloud/device publishing credential.

Run its finite --preview, --read or --publish operation with --profile and the
reviewed --sha256 under python -I. Preview creates nothing and needs no live
credential/service. Publish persists a payload-free intent before exactly one
send. An uncertain reply preserves the original event and input; only a deliberate
--reconcile with the same canonical payload can reconcile it. It never retries
automatically. A recorded receipt proves a past commit, not the current handoff;
use --read for current state. Input edits, different source/profile pins and
out-of-folder files are refused. No live profile or activation is installed by
copying this client. Actual enrollment/runtime approval is separate.

## Portable Hermes private home (inactive)

On POSIX, registration selects `PortableOnoesMindProvider`; Windows keeps the
existing Windows provider and v1 profile. The portable implementation reuses the
same prompts, selected-fact prefetch and tool schema. Writes go through Mind's
existing `AgentHomeSession`, using its remote HTTPS client and POSIX encrypted
delivery journal. There is no automatic resend or local recall fallback.

The exact owner-pinned profile schema is `onoes-mind-hermes-provider/posix-v1`.
It pins the Hermes home, stable agent, complete SDK source hashes, home-binding
fingerprint, private credential file, separate journal key and directory, one
Tailscale HTTPS endpoint, review reference and context budget. It carries no
database path or credential value. The existing native-memory and user-profile
flags must both be false. Profile/custody permissions and current source/profile
pins are checked, and subagent/cron/flush contexts cannot use the primary home.

Provisioning the profile, a dedicated agent credential and a separate encrypted
intent key is an operator action outside plugin startup. Copying these source
files grants no memory access and does not publish an endpoint. Use Mind source
`553defc` or later with the portable client/state modules and `cryptography`.
Do not copy Windows DPAPI envelopes to Linux or edit an immutable deployed SDK.

The optional shared-project tool remains a reference to the separately enrolled
reader. This provider does not itself grant or implement remote shared-context
access. Cloud-side runtime/version matching, reviewed enrollment and actual
normal-agent acceptance still have to be proved before a live rollout.

`test_portable_provider.py` exercises Hermes's actual plugin loader and
MemoryManager with disposable profiles, real local TLS and synthetic canonical
homes. Set `MIND_SOURCE` and `HERMES_SOURCE` to the reviewed code and run it on
Linux. The existing `test_provider.py` remains the native Windows regression.
No model call, real profile or live ledger belongs in either test.

## Shared-project reader on the canonical host (inactive source)

The optional v7 service profile extends the existing private-home/handoff
listener with separately enrolled read-only project readers. It does not add a
listener, writer, ledger, scheduler or automatic enrollment. Existing v1-v6
profiles retain their original behavior. A live rollout needs separately
reviewed source/profile changes and explicit access approval.

The profile adds `projectReaderBindings`: sorted, unique rows containing an
`AgentContextBinding`, the absolute private `toolGrantPath`, and its exact
`toolReviewRef`. Each reader must bind the same canonical database identity as
the writer. Its project may differ from the writer's permitted capture projects:
read permission must not imply a new write permission. The grant file belongs
outside the canonical data and source trees.

Approval must include `run_project_reads` and the exact `projectReads` descriptor
from `project_read_approval`, alongside existing home and handoff approvals.
Running receipts expose only the bound principal, project, shared scope and
fingerprint. Credentials and grant-file paths are not client options.

Startup opens query-only readers after acquiring the existing canonical writer
lease. Each request checks its purpose-bound reader credential and current
separate `read_project_context` grant, including private-file qualification.
Shutdown retires listeners before closing readers and the canonical writer,
then releases the lifetime lease. A failed reader close retains the lease.

`test_shared_project_service.py` uses synthetic enrollment and exact owned
processes to check v7 admission, current shared reads, grant withdrawal, restart
and rollback to the v6 private-home/handoff surface. Set `MIND_SOURCE` and
`MESH_SOURCE` explicitly. The separate SDK HTTP/MCP suites qualify protocol and
scope behavior; this host test does not establish cloud TLS, native agent
version compatibility or normal-model acceptance. Use Mind source `4a7c3e3`
or later; do not modify an immutable deployed SDK to obtain these modules.

A separate isolated protocol check pairs an MCP 2.3 client with the pinned
1.26 reader process over synthetic local TLS. It verifies the current handoff
and grant/profile withdrawal using the v2 client result API (`is_error`).
This does not qualify Cyony's native Hermes tool adapter or grant live access.

## Cyony exact native runtime rehearsal (not activated)

The pinned public image `nousresearch/hermes-agent@sha256:adb7890916de63245523492be8f68f9d2095fecbec4e2a6dab7960381f0fc002`
was matched to the running cloud agent: Python3.14.9, UID10000, MCP2.3.0,
cryptography50.0.2, pydantic2.14.1 and eight memory/MCP source fingerprints.
Ten portable-provider cases passed in that exact image with synthetic homes,
canonical stores and local TLS. No live cloud profile or model was used.

`test_native_shared_reader.py` composes the actual memory-provider loader and
MemoryManager with Hermes's real MCP discovery, model-facing definitions and
registry dispatch. One composed case verifies the current Nims JSON handoff and
provenance, private/shared separation, denied caller scope overrides, current
grant withdrawal, changed-profile denial, private continuity and scoped teardown.
All these phases passed together; they are one test, not separate case counts.

The fixture keeps native MCP2.3 unchanged and creates a separate disposable
MCP1.26 reader child. Mount its pinned pure package at `/reader-deps` and the
verified `pydantic-settings==2.13.1` child dependency at `/reader-extra`.
The latter is absent from the native image: do not downgrade or modify the
native gateway to supply it. `MIND_SOURCE` and `HERMES_SOURCE` select reviewed
SDK and actual image source as in the portable-provider tests. The test requires
POSIX and uses no live credentials, model calls or external network.

Native MCP discovery/cleanup is profile scoped. Retire the selected connection
with its explicit registry scope and name; an unscoped name-only shutdown does
not close another profile's reader. The rehearsal leaves no registered reader.
Source and fixture success do not approve a live endpoint, enrollment, cloud
configuration, gateway restart or normal-agent acceptance task.

## Portable owner configuration switch (inactive)

`portable_owner_switch.py` reuses Hermes's raw-config parser and atomic writer.
It selects exact reviewed private-home and reader profiles, actor/project/reader
identity, SDK/source fingerprints and the dedicated reader interpreter. The
home prompt must name the actual `mcp__onoes_mind_mesh__read_project_context`
tool. Both profiles use the same reviewed private HTTPS endpoint; the helper
creates no credentials, endpoint, service, scheduler or memory records.

The switch preserves unrelated settings, Blender, literal secret references,
comments and native MEMORY.md/USER.md files. It exclusively saves the original
config in a private owner-selected folder, checks the caller's quiescence twice,
and refuses changed input or an occupied reader name. Rollback requires the exact
installed config, receipt and original backup; withdrawing new profile files
must not prevent restoration. It never silently overwrites another writer.

The actual native composed case now also installs this switch, checks model
prompt/tool-name agreement and rolls it back. Seventeen focused owner cases
verify refusal/recovery and the concrete gateway's provider cache fingerprint.
Fingerprint change is not proof of safe live hot replacement or drained work:
the installer still needs a verified maintenance/admission boundary.

`test_legacy_home_clients.py` runs the deployed public Echo/Deep client SDKs in
isolated subprocesses against a fresh candidate host. Set MIND_SOURCE and the
explicit MIND_LEGACY_ECHO_SOURCE / MIND_LEGACY_DEEP_SOURCE code roots. Both
clients passed save/recall/correct/forget and cross-actor denial on Linux and
Windows. No live client profiles, credentials or canonical database are used.

## Native external-drain rehearsal

The pinned gateway already supports `.drain_request.json`: its watcher refuses
new chat turns, its API returns retryable `503 gateway_draining`, and its
in-process scheduler receives the same dispatch gate. Reuse that native control;
do not introduce a second supervisor. These are source-version-specific findings.

`test_native_maintenance.py` runs the real marker writer/watcher and API admission
response around the portable owner switch and rollback. A synthetic in-flight
work hook prevents a premature switch; admission remains held through rollback.
Clearing the marker restores admission. Separate cases verify that an old epoch
or expired marker is ignored, while malformed content stays drain-active.

Four native cases passed without a model or running gateway. Their synthetic
work hooks are not proof that deployed workers, children, transcripts or config
writers have drained. The marker expires after one hour and does not survive
container recreation as an active hold. A live plan must verify exact owner and
current drain/work state, keep its window bounded, preserve other writers and
qualify normal gateway retirement separately. Do not infer safe hot replacement
from the provider cache signature or use an idle snapshot as a maintained hold.
## Scoped native service lifecycle

`test_native_service_lifecycle.py` exercises the actual image's S6ServiceManager
and /command tools in a temporary unprivileged supervision tree. A worker holds
its exit after TERM: the native stop request and desired-state update complete
while its exact old PID still runs. Only after clean planned exit and old-process
retirement is a successor started. A second profile's PID and saved intent stay
unchanged. A missing service refuses without changing the selected intent.

Both cases pass. This is native control qualification with harmless workers,
not proof of a real gateway's transcript flush or every background child. The
fixture needs executable temporary service scripts; Docker tmpfs otherwise
mounts noexec. Keep that exception confined to the disposable s6 fixture. Never
point the test at the real /run/hermes-service tree.

## Proposed private Mind path

`private_mind_route.py` is a pure configuration planner for `/mind-agents/` on
Mesh's existing HTTPS8453 listener, targeting the existing loopback19124 host.
It retains Mesh's root4320 route and every unrelated route/listener, refuses a
changed snapshot, occupied/ambiguous mount or Funnel on its selected listener,
and rolls back only its unchanged added path. No reset or global replacement.
It makes no network, credential, service or Tailscale change itself.

Eleven local cases and a preview/inverse against the captured Windows config
passed. That captured config is historical; live installation requires a fresh
reviewed snapshot, approved new access, same-target TLS/protocol verification
and exact readback. The selected endpoint is not live merely because this
planner or its tests exist. Keep the separately proposed Cyony Relay route and
its approval independent from any Mind permission.
## Cloud host profile preparation

`cloud_host_profiles.py` prepares the existing v7 host view from exact reviewed
v6 bytes. It retains Deep/Echo bindings, Nims's fixed handoff, original operator
enrollment and the other existing projects. Its only added capabilities are
Cyony's private home and context-cyony's read of shared Onoes-Mesh facts. A
prepared view is not an owner approval; the native service still requires one.

Twelve pure cases pass. `test_cloud_host_composed.py` adds one actual owned
Windows v6 -> v7 -> v6 process case on a synthetic ledger: old private notes and
handoff survive, new scopes require new approval, cross-actor reads fail, grant
withdrawal preserves private access and rollback removes the added routes. Set
MIND_SOURCE, MESH_SOURCE and MESH_CANDIDATE_SOURCE to the exact reviewed code.
The case passed against both the current released adapter and the compatible
artifact; these are two runs of one case, not two independent cases.

The live enrollment still protects older core adapter bytes. Five differences
were line endings; three were unrelated newer helper revisions. Do not broaden
the native source allowlist. The compatible artifact retains all nine protected
core files byte-for-byte and selects only the existing two host/HTTP upgrade
seams plus the reviewed service controller. It passes the same composed case.
The test fixture accepts an older operator module without assuming its newer
operator-enrollment constant; runtime validation rules remain unchanged.

Inactive actual profile views also pass the audited native runtime metadata
checker (source hashes, owner permissions and database stat only); no approval,
credential, SQLite connection or service is created by that check. The actual
native curated files are under HERMES_HOME/memories, not directly under its
root. Their contents and any import remain separately approved live work.

## Inactive offline cloud client

`cloud_client_package.py` builds a fingerprinted ZIP of public SDK/plugin code,
two credential-free Cyony profiles and isolated MCP 1.26 dependencies. It checks
the independently supplied outer ZIP fingerprint before reading its manifest,
then checks every payload hash. It excludes custody, intent keys and the Hermes
configuration. Preparation does not grant access or activate a provider.

The POSIX materializer requires the exact reviewed interpreter and native
package directory, a current-user-owned home and unused installation roots.
It installs private files and a dedicated reader environment without pip or
network access. Native MCP 2.3 and existing configuration remain unchanged.
An existing installation is refused; a partial failure requires inspection
before continuing, rather than an automatic overwrite or retry.

Eleven pure cases verify package integrity and refusal conditions.
`test_native_client_package.py` adds one complete disposable Hermes case:
serialize/reload/install the package, save a synthetic private note through the
real memory provider, discover and dispatch the shared-context tool, check Nims
author/revision/next action and provenance, then restore the original config.
Its local test CA is confined to a separate fixture startup file; no production
profile or package overrides certificate verification. No model is called.

The actual prepared 207-file bundle also passed code-only installation in the
matching isolated image, using its exact observed interpreter. That check made
no memory calls and created no credentials or config. These results qualify the
package, not deployed enrollment. Live permissions, curated import, transport
configuration and gateway maintenance remain separately reviewed operations.

## Finite cloud enrollment and curated notes

`cloud_enrollment.py` is an owner-process helper around Mind's supported private
home and project-reader enrollment APIs. It refuses either preexisting Cyony
identity before issuing access and requires a protected receipt for the first
commit before beginning the second. Failed or uncertain custody/receipt saves
stop the sequence. The caller supplies the approved plan, exclusive writer
lease, encrypted backups and private custodian; the helper opens none of them.

Conditional revocation accepts only that attempt's trusted receipt and unchanged
credential/grant/epoch fingerprints. Both identities are checked before either
is revoked. Another credential, changed scope or epoch, different project or
another attempt holds recovery. Existing identities, memory and custody are
retained. Ten disposable-ledger cases verify these paths on Windows and Linux.

`cloud_curated_transfer.py` captures only the explicitly approved MEMORY.md and
USER.md, checks file identities, private file permissions, credential-like text
and a combined size bound, then supplies fingerprinted private transport bytes.
Transport bytes contain private notes and must never be printed or put in Git.
The metadata descriptor omits text. Keep its original host/path/file identities
with the protected owner receipt for remote-source provenance.

Canonical-host staging uses owner-prepared private directories and the existing
Mind curated importer, including its original file hashes, stable event and
replay behavior. There is no direct database insertion or transcript ingestion.
Windows staging requires exact explicit operator/SYSTEM/Administrators rules;
it does not change permissions or accept Python's OWNER RIGHTS substitute.
Seven synthetic cases qualify import/readback, preserved originals, replay,
changed-source/transport denial, secret rejection and the transfer size bound.
These helpers do not activate cloud enrollment, move real notes or call models.

`cloud_owner_phase.py` connects the enrollment helper to existing Windows DPAPI
custodians and protected, exclusive attempt/receipt files. It verifies private
and shared authentication, imports an explicitly prepared two-file snapshot
with source metadata and checks the current record. Two native Windows cases
pass: complete custody/import/readback/revocation and partial reader-custody
failure followed by revocation of only the recorded private enrollment.

`cloud_custody_delivery.py` is the corresponding finite POSIX delivery primitive.
It verifies every installed public package byte and private file identity before
writing three new private custody files, syncs them and reads them through the
actual SDK credential classes. It changes no config and starts no service.
Four cases pass in the matching cloud image: SDK readback/repeat refusal and
refusal of changed public code, an invalid token or unresolved intent state.
Credentials are inputs from the separately approved owner operation; the helper
does not issue them, send SSH requests or retry uncertain delivery.

These are component/operation proofs on disposable data. The enclosing live
installer still needs fresh backups, approved host/route/gateway changes,
maintained admission and writer quiescence, exact protected delivery receipts,
normal startup restoration and end-to-end acceptance before claiming enrollment.

## Inactive startup views

`cloud_startup_profiles.py` prepares eight linked capture/connected startup
views from exact original bytes. It retains the existing reader, settings,
shared card fields, data locations and Nims target. It updates the reviewed
host/grant links, the controller fingerprints in both launch modes and their
nested hashes, with new exclusive attempt/output paths. Raw originals remain
available for the enclosing installer's rollback. It writes or selects nothing.

Ten pure cases pass, covering the complete hash graph and refusal of changed
originals, broken links, incorrect descriptors, stale source pins, occupied
attempt paths or reused profile targets. The actual inactive draft also showed
that the installed controller is v6: selecting a v7 profile alone is insufficient.
Two public native files need the reviewed upgrade; the HTTP seam already matches.
The existing nine protected core files stay exact. Proposed grant contents do
not authorize enrollment. Copied-workspace native startup qualification remains
separate from this pure preparation check.

`test_cloud_startup_composed.py` passed one complete owned Windows rehearsal in
an explicitly named copied workspace: the deployed app baseline, two-file host
upgrade, exact nested startup preflight, explicit new-writer first activation,
capture-to-connected transition, private-home authentication, shared Nims
document/provenance and reopening the original saved card through Mesh HTTP.
The unchanged reader stays running. Originals remain byte-for-byte intact.
Only disposable ledgers, credentials and owned processes are used; no models.

The copy must include the installed Koffi package and its matching Windows
native optional package. The peer checks fail before HTTP without that complete
dependency closure. Verify the native self-peer prerequisite before starting
test services. The baseline fixture must also match the deployed launcher API;
using a newer optional worker fixture against the old API is not qualification.
These dependencies/fixtures are test preparation, not production guard changes.

This composed case uses one SDK root for the roles. The actual proposed writer
SDK differs from the current reader/capture SDK. Native source-origin checks
must remain enforced: prepare aligned same-grant reader/capture runtime views
and qualify that old-to-new SDK transition before the enclosing live installer
or activation review. The single-SDK pass does not qualify the mixed-root plan.

`prepare_aligned_startup` extends that graph with two same-grant reader views.
It moves capture and reader SDK pins to the writer's exact runtime while
retaining the reader binding, credential path, original enrollment/terminal
proof, owner and scope. Non-SDK helper pins and executables cannot change as
part of this alignment. Fresh state paths and all parent hashes are sealed
together; the original ten files remain available unchanged for rollback.
The planner writes nothing and cannot activate or enroll a reader.

Nineteen startup cases and twelve host-conversion cases pass together. The
two-SDK native rehearsal in `test_cloud_sdk_transition_composed.py` uses separate
cold Python processes for forward and inverse operation, keeping the native
module-origin checks intact. Its existing deployed-app baseline, original SDK,
new SDK and saved board use only disposable profiles/data and exact child
handles. Explicit reader/writer activation precedes recurring recovery; the
recovery controller is not changed to start unknown actors.

Rollback must also restore the selected public ownership receipt, alongside the
private profiles. Startup intentionally refuses a receipt belonging to another
profile set. The copied workspace begins with no public receipt: after the
forward child exits, the caller holds the existing launcher window, validates
its exact PID/birth and attempt, archives its attempt/output files and receipt,
then restores that originally absent slot. A live installer instead preserves
and restores its reviewed original beforeimage. Never remove an unknown or
living owner's receipt to make a profile switch pass.

The complete cold-process SDK transition and inverse passed on Windows. After
returning to the original SDK, the same saved card reopened and the original
read-only reader returned the same shared Nims handoff with provenance through
Mesh HTTP. The two initial failed inverse attempts are retained as diagnostics;
they are not additional passing cases. This is one disposable composed case,
not deployed cloud acceptance. Both SDKs retain identical migration bytes.

## Finite cloud installation candidate

`cloud_install_window.py` encloses the native operations in one write-once
window. It qualifies the installed client while the cloud gateway is stopped,
then deliberately releases normal native startup. Failures must rehold and
reconcile actors before revoking new access or restoring source/configuration.
Unknown retirement leaves a held result. Earlier evidence prevents replay;
operation results and raw exception messages are not copied into its journal.
Ten fault/privacy/replay cases pass, together with the existing 31 profile cases.
These callback-contract tests do not qualify a live installer or new permission.

`cloud_windows_cutover.py` supplies concrete cold-process Windows operations,
reusing the native controllers, original MindRoles control and launcher window.
The extended `test_cloud_sdk_transition_composed.py` beforeimage mode passed one
complete owned Windows case: start/publish the original selection, retire its
exact owner and peers, cold new-SDK startup and retirement, restore the exact
original published receipt, then cold old-SDK startup and saved-card/shared
handoff readback. This includes the real original beforeimage, rather than only
an originally empty receipt slot. It changes no production selection or guard.

The complete cross-host enclosing installation/rollback remains separate
qualification work. No cloud enrollment,
route, credential delivery or activation follows from these local passes.

`cloud_native_gateway.py` now qualifies the scoped native cloud lifecycle in a
no-network container without host mounts or model calls. It verifies native
source, the exact service/profile owner and a fresh acknowledged drain with
the complete native work count. Optional display details never replace that
count. A retained kernel process handle, wanted-down state and clean exit prove
retirement; a service readiness notification is not used as proof of death.
The same native stopped intent is finalized after retirement, avoiding a late
gateway status flush restoring its cached running intent. The native code stays
unchanged. The no-signal value follows [s6's status contract](https://skarnet.org/software/s6/s6-svstat.html).

Its private, plan-bound stop receipt can be reopened by a cold process; pending
start evidence blocks replay. The native fixture passed foreign-marker and
changed-source refusal, kernel retirement, cold receipt resume and normal
restart, with another service's PID/intent unchanged. This is one native case;
the earlier failed interface attempts remain diagnostics. The standalone
`native_cloud_gateway_fixture.py` is inert when imported. The cross-host
installation, credentials, route and live gateway remain unactivated.


### Cold owner entry points and exact source selection

`cloud_gateway_entry.py` provides finite stop, stopped verification, release and
running verification commands. It checks the exact owner authorization, pinned
entry/native/service files and private evidence before native imports or service
actions. Deliberate release additionally requires the same window's held
qualification and unchanged selected files. Conditional rollback uses a separate
generation: rehold only the exact owner that this window started, restore the
original configuration, qualify it while stopped and release the original.
Missing results and pending starts remain held, without retries.

The isolated native fixture passed that actual separate-process entry, including
unapproved-plan, unqualified-release and changed-file refusal; kernel retirement,
cold restart, exact new-owner rehold and original configuration/release; peer
unchanged. This is a lifecycle fixture with synthetic qualification evidence, not
a live Mind/client or cross-host installation test. No model request is made.

`cloud_windows_entry.py` provides cold-SDK inspect/retire/start/restore commands
around the qualified native Windows controls. It independently requires the
existing recovery task to be disabled with the exact reviewed definition before
process actions. It creates or changes no task. Inert import and a real read-only
refusal check passed; successful enclosing Windows entry acceptance is NOT RUN.

`cloud_source_selection.py` limits source selection to the two reviewed runtime
seams and the existing hidden recovery wrapper. All three original byte images
are durable before replacement using the original Windows primitive. Seven
owned-file cases pass native replacement, UTF-8/both UTF-16 orders, partial
failure recovery, drift refusal and admission/replay limits. This preserves the
existing recovery task rather than introducing a scheduler. The complete
cross-host adapter/entry and installed-path acceptance remain outstanding.


### Canonical owner entry and public-code bootstrap order

`cloud_owner_entry.py` is the cold Windows owner operation. It verifies the
completed encrypted before-backup in its original runtime before importing the
selected owner SDK, then reuses the native writer lease/checkpoint authority and
protected operator custody. The reviewed access remains exactly Cyony's private
home and context-cyony's read-only Mesh project. Curated capture is limited to
MEMORY.md/USER.md; existing custody fingerprints remain unchanged. A separate
cold revoke uses only the recorded new identity receipts and retains memory.

One owned native integration passed an actual encrypted backup/recovery
readback, cold owner admission, curated profile readback and cold exact
revocation while existing Echo/Deep credentials stayed valid. No production
store, credential, cloud service or model was used. Eleven enrollment checks
include early refusal when the store lacks the existing Mesh recall extension;
that refusal commits no private home and saves no custody. This does not
implicitly create another Mesh identity or initialize an extension.

The finite window now materializes public client code before curated capture,
because capture uses the frozen SDK validators. Private credential delivery is
a separate later operation after enrollment and Windows startup. Thirteen
fault/order/privacy/replay cases pass. Public files alone do not select memory
configuration or enable access. The deployed private route and
the enclosing cross-host installer remain outstanding; live enrollment remains
unapproved and inactive.


### Concrete cloud client and native operation exclusion

`cloud_client_entry.py` now executes public materialization, approved two-file
curated capture/export, private credential delivery, native portable switch and
read-only qualification under the existing gateway's verified stopped state.
The qualifier uses the actual configured provider over verified TLS and its
dedicated MCP1.26 stdio reader to retrieve the current shared Nims handoff,
revision and provenance. It starts no model and does not enroll a principal.

The gateway and client entries share a private retained-inode kernel operation
lock. Another participant blocks before a write; nested same-thread checks
reuse the existing descriptor. This is this installer's scoped exclusion, not
a machine-wide idle claim. Normal native startup remains the admission release;
the authorized running intent is recorded before s6 can launch a child.

Portable rollback uses the native backend's explicit file backup/restore
capability and restores the original bytes/checksum atomically. Another native
backend is refused before selection; unrelated settings are never rewritten.

One complete owned no-network container case passed actual default-trust TLS,
provider recall, dedicated MCP handoff read, operation-lock refusal, non-file
backend refusal, native release/rehold, exact original configuration restore
and original release. Both native boots observed running intent beforehand;
the peer service was unchanged. The API used a synthetic POSIX SDK Ledger;
Windows checkpoint/DPAPI owner proof is the separate native owner test. Earlier
failed attempts remain diagnostics. This does not qualify the complete
Windows-to-cloud installer, its deployed private route or live Cyony access.


### Exact maintenance-task flag control

`cloud_windows_task.py` snapshots, pauses and restores an exact hash-bound
Windows scheduled task. It preserves all other task settings, retains private
original and attempt receipts, refuses drift/replay, and never registers,
starts, stops or reschedules a task. The enclosing approved installer must bind
it to Mesh's existing recovery task; the helper grants no owner authority.

Six native tests passed using uniquely named disposable tasks with no triggers
and no action execution. Both originally enabled and disabled states restored;
foreign definition changes blocked pause/restore. All test tasks were removed.
This qualifies the task-control primitive only: the positive cold Windows entry
and complete cross-host installation/rollback remain outstanding. No live task,
app, credential, memory permission or cloud configuration changed.


### Concrete child-phase transport (inactive installer component)

`cloud_phase_runner.py` constructs the existing cold Windows owner/service,
backup and cloud gateway/client commands. It keeps SDK lifetimes separate,
binds the approved SSH recipe and immutable container ID, and conveys private
stdin/stdout without copying it into general journals. Each attempt is one-shot;
transport timeout never proves remote-writer retirement. Noninteractive phases
cannot consume terminal input. It adds no service, scheduler or worker.

Seven local real-child checks pass for private-byte transport, no-input phases,
replay prevention, nonzero exit, uncertain timeout and admission boundaries.
Those tests make no remote or model call. The command bindings themselves and
complete enclosing adapter/owner entry are not end-to-end qualified. This is an
inactive component, not a standalone installer or new access authorization.


### Enclosing owner window: local proof, cloud qualification pending

`cloud_install_entry.py` wires the finite installer to the existing task, cold
Windows phases, canonical owner entry, backups, exact source selection, private
route and cloud client/gateway operations. It has no default owner approval or
live plan. Unknown transport and partial startup hold before compensation;
the original recovery-task setting returns only after complete new/original
health. It adds no supervisor, scheduler, model call or database write path.

The real Windows backup command now passes --run and its pinned approval, then
checks the protected native result and recovered archive instead of prose.
One owned native case passed parent backup, cold enrollment/revocation and
exact-binding DPAPI payload assembly with a local private capture sink. Another
native case used a trigger-free task, launcher mutex, three owned process
birth identities and actual file replacement: live main/peers blocked writes;
after retirement all three files selected/restored exactly. Fourteen final cold
admission/rollback refusal checks passed. Existing agent custody stayed intact.

These are local component proofs, NOT full installer acceptance. The hard-bound
production cold Windows entry, deployed private route and complete cross-host
window remain unqualified. The new original-held client/schema change is still
a separate unqualified development candidate; do not activate this entry with
the older client. Cloud testing remains stopped after an uncertain SSH attempt
until the existing route and that exact test actor are reconciled. No new trial,
route, live credential or agent access follows from publishing this source.


## Current Cyony connection status

The owner successfully approved the existing Echo-PC to Cyony SSH connection
from his phone. The expected host/account and the current running container
and native gateway were then verified read-only, and six public gateway
source hashes still match the prepared image. The earlier authentication
stop is resolved for that verified route. The inactive cloud_phase_runner
source now pins exactly the existing verified dedicated-key recipe with
strict host checking, no forwarding and host-key updates disabled, and never
accepts a caller-rehashed different recipe. Forty-six focused local
transport/installer/window tests pass, plus a no-execution composition check
using the actual verified recipe. No production installer, new memory
identity, credential, private endpoint or gateway restart was enabled by
those checks, and Mind enrollment remains inactive. The production cold
Windows entry, deployed private TLS route and complete cross-host
installation/rollback remain unqualified; the old remote test retirement
remains unresolved. A zero-active-agent snapshot is not a drain or
retirement proof. Remaining acceptance gates stay in place.
