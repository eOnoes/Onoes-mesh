## Mesh and Mind connection status | November 22, 2026

The live Workroom serves saved cards, and Mesh can retrieve the deliberately shared result from its existing linked card in Onoes-Mind. Workroom owns task stage and review. Mind keeps the linked project record and its revision history. The live writer is scoped to Onoes-Mesh.

### Changing project specifications

Use one linked Workroom card per changing specification. Keep its project and card IDs stable. When the design changes, update the shared goal with the revision, units, dimensions and CAD filename. A project reader can then return the current revision and its Workroom source reference.

A disposable integration check compared two publication paths. Publishing two ordinary owner facts with different event IDs left both searchable. Editing one linked card produced one current Mind revision. A late replay of the first event preserved the newer revision. Relay and Telegram adapters read the same result through the project tool.

The print pilot still needs explicit writer scope for its project and a read-only connection reserved for Echo. The channel checks used test credentials. Live Echo enrollment and cross-channel retrieval on Eddie's PC are pending.

For the print pilot, look up `project:3d-print-pilot/AGENT-HANDOFF.md` through the project reader. Search returns the reviewed reference. When using a copy of the guide, verify its exact bytes against the single current, operator-reviewed record. If the reference is missing, two revisions are current, or the copy differs, pause and obtain the current reviewed guide. Look up the changing dimensions and CAD filename in the linked specification.

Two disposable readers with independent grants found the same handoff. After replacement, the old copy failed verification. Withdrawing one reader's tool grant ended its lookup while the other could still read. Withdrawing the guide itself removed the remaining reader's result.

### Echo's reader and delegated workers

The first Echo reader is scoped to the shared 3D Print Pilot. It has yet to be enrolled. A worker profile can narrow the tools listed to a worker. On Windows, file access also depends on the security identity that runs the worker.

On November 23 a disposable test called the installed Hermes delegation entry with a local marker in place of a model conversation. Both an ordinary child and a child routed to a separate profile ran on another thread in the parent process. Both used the parent's Windows process token. The routed child selected the requested worker profile during its turn. Moving the entire gateway to a dedicated account would still give an in-process child that account's permissions.

For Echo-only access, keep the live reader with an independently authenticated Echo process and run ordinary workers outside that identity. Include both Hermes delegation and Workroom's native worker route when checking the deployment. The acceptance check is a project read from Echo's Relay and Telegram conversations, denied access for a disposable worker, and withdrawal of Echo's access. The same project ID and current Workroom revision should be visible in both conversations. Use synthetic project facts to qualify the arrangement before issuing the live reader credential.

To repeat the identity observation on Windows, run `integrations/qualify_hermes_worker_identity.py` with the Hermes Python executable and the source checkout used by the gateway. It uses temporary profiles, reports the loaded module hashes, and makes no model requests. The separate tool-catalog check accepts the same source checkout as its optional second argument.

### Adding one project to an existing writer

The offline owner operation `add_project` takes the complete reviewed list of project IDs and labels and one explicit `addedProjectId`. It requires a separately approved profile, fresh output paths, and exclusive access to the writer. Existing active projects must still match. A revoked credential or a previously registered project cannot be used for this operation.

The operation verifies Windows-protected storage for a fresh credential before committing the new registration, grant and credential rotation together. A storage failure leaves the previous credential usable at its original scope. Preserve the attempt and its files if completion is uncertain. A successful result identifies the added project and records `project_added_inactive`. Starting the writer and enrolling a reader each have their own approval.

For the print pilot, the intended pair is `onoes-mesh` and `3d-print-pilot`. Once the grant commits, the previous credential expires. In a disposable rehearsal, the old startup configuration was refused. Workroom saved edits to both cards locally and reopened them while offline. With the replacement writer connected, all four events matched Mind receipts. Reopening a second time preserved those receipts and both current titles.

### Linking a card on an existing board

Prepare the complete target list of card links. Keep the original projection and field approval for each existing link. For the new card, review its current revision, fields and projected content. `inspectProjectSourceAddition` previews one named addition. `prepareProjectSourceAddition` requires that card ID, the full plan hash and the `approve_exact_mesh_project_source_addition` decision. It appends one baseline in a transaction. If the acknowledgement is lost, `inspectProjectSource` can read back the completed plan and its original event IDs.

On a private copy of the 15-card board, adding a pilot card with title, stage and shared goal preserved every original row across 30 tables. The pilot's goal contained the revision-one specification and CAD reference. No service was started by the addition. The live board and writer still need their own approved link and project scope.

The live board now has a 3D Print Pilot specification card in To do. A restored 16-card backup preserved its goal and its unshared status. Both proposed startup configurations select the same three pilot fields (title, stage and goal) and retain the original card's field selection. The live writer still serves only Onoes-Mesh.

In a disposable two-project startup test, Workroom accepted a pilot edit while offline. After reconnection, all four queued and connected edits had matching receipts on the board and in Mind. The current pilot revision included the updated title and CAD filename. The original card's private description stayed out of Mind.

For the live pilot update, take the before-change archive after the existing Mind writer has stopped and its exit matches its saved run. Repeat that check against the replacement writer for the after-change archive. The operator enters the saved archive password locally for each backup. Resume delivery and verify both card receipts after the second archive passes recovery readback.

An installation rehearsal used a restored 16-card board. Interrupting the six-file update after its third replacement restored all six originals and preserved the board database hash. In a second run, losing the acknowledgement after the pilot link committed was recoverable by reading the link back. Both cards opened in offline capture, and a pilot edit kept the same queued event ID across a second startup.

## Historical connection status - 2026-11-15 Chicago

The first canonical shared read-only connection is live and accepted on Eddie's
phone. Its fixed project/onoes-mind/shared scope excludes agent-private memory;
no project facts or conversations have been ingested. The dedicated recall
credential cannot use the ordinary writer. Workroom remains the task-stage
and review authority. See MIND-SETUP-READINESS.md for the current evidence and
completed project-sync source audit. Older dated setup/preparation statements
below describe their historical state, not the current runtime.

Project writes, conversation synchronization and shared tools/skills remain
unfinished. No live writer enrollment is approved by read-only acceptance.

# Mind: selected task context

The first source is the existing Mesh Workroom store. In Mind, the admitted owner
chooses a saved task and deliberately requests Read selected task. Listing the
available titles does not retrieve a separate personal-memory database. The view
uses the same guarded Workroom GET as the task board, with no new credentials,
listener, search service, dispatch, scheduler or memory-writing endpoint.

The selected snapshot displays task ID, project, task/brief/progress revisions,
task update time and retrieval time, description, goal, checklist, result,
evidence references, saved stage, recorded decision and reviewer label. Recorded
results and labels are not independently verified facts. Open source task in
Workroom exposes the existing complete report/review provenance. No transcript,
assignment payload, external chat history or personal profile is copied here.
Source text is rendered as text; references do not execute or fetch anything.

Records from different tasks remain separate; Mind does not merge conflicts or
turn an old approval into approval of a newer revision. The view is a snapshot,
not a live assertion of agent or model state. Selecting another task or refreshing
the app clears it and requires another deliberate read. Failed, mismatched and
late responses cannot repopulate a cleared view.

No additional persisted memory is created. Clear this view removes the displayed
RAM copy, not the source task. Existing Workroom retention/deletion and backups
continue to own that record. Session lock, expiry, offline/page privacy clearance
clear context and title options through the existing application lifecycle.

External memory adapters, personal memory, cross-channel search, automatic writes,
conflict resolution and separate deletion/retention policies require their own
selected source and scope. This initial task-record reader does not qualify them.


## Current setup status (2026-11-07 Chicago)

The approved private folder is `D:/App-Data/Onoes-Mind`; read-only verification
found it empty. No live ledger, recovery keys, service principal or recall service
has been initialized there. Eddie owns the data and recovery keys; Echo and Nims
operate it. A specific runtime identity, single shared scope and live binding
still need their separate reviewed decisions. Existing synthetic recall/recovery
components are prepared, not live memory access. The earlier audit and planning
sections below are historical evidence, not instructions to activate them.

## Canonical Onoes-Mind integration boundary (2026-11-07)

The existing Onoes-Mind project owns durable agent memory, shared knowledge,
identity, provenance, corrections and deletion. Workroom remains the task and
review authority. The current selected-task reader above is not a connection
to Onoes-Mind or shared conversation memory.

Read-only source audit of the canonical Onoes-Mind implementation found:

- `onoes_mind/ledger.py::Ledger.search` authenticates its token, derives readable
  scopes from stored grants and returns active/promoted records with provenance.
  Query input is bounded; result count is capped at20. A browser-supplied scope
  hint is not authority to read another agent's private memory.
- `onoes_mind/bridge.py::BridgeServer` is the local test task-lifecycle bridge.
  Its runtime family is `local-test-runtime`, with synthetic agent identities.
  It does not expose scoped memory recall. Its default test authentication key
  is not a deployment credential; Mesh must not reuse it or impersonate Echo.
- Existing Phase1A/1B tests passed13/13 on2026-11-07 using only in-memory/temporary
  ledgers: principal isolation, shared reads, provenance, bounded recall,
  duplicate/divergent events, secret refusal and deletion-aware restore.
  This is core-ledger evidence, not live-service or cross-channel acceptance.

### Next implementation slice

Implement and qualify a Mind-owned, authenticated, versioned read-only recall
boundary before wiring Mesh to it. Use the existing ledger/policy; do not create
another memory database, copy an agent's private store, mount SQLite in Mesh or
turn the test task bridge into an assumed memory service. Keep unowned candidate
work separate from the canonical implementation.

The slice must establish the exact service/adapter identity and protocol,
server-derived caller and read grants, bounded query/results, record/project/scope
identity, source time/hash/provenance, and explicit unavailable/auth/schema errors.
Mesh holds any separately provisioned service credential only on its server;
the browser receives no token and cannot select arbitrary hosts or agent identity.
Do not grant a new principal, rotate credentials or activate a service as a side
effect of merely opening the Mind tab.

Acceptance requires the actual HTTP/adapter -> canonical ledger -> response ->
Mesh view path with temporary synthetic data, including unauthorized cross-scope
refusal, deletion/correction taking effect on the next read, and offline/lock/
late-response clearing. Only then provision the chosen live read access and
perform a selected live read under its approved grants. Retain Workroom reads
when Mind is unavailable, clearly labelled by source.

After qualified recall, add deliberate reviewed writes and agent context
consumption as separate slices. Cross-channel source IDs and receipts must
prevent duplicate ingestion; automatic summaries, personality/profile changes,
shared skills/MCP and conflict resolution remain unfinished parts of the broader
objective. No raw chat import or automatic memory write is enabled by this audit.


## Prepared canonical recall component (2026-11-07)

Onoes-Mind source milestone `ae5ab267829ffeb90c9e5caca7232afaac13afc8`
adds `onoes_mind/recall_http.py`, its actual HTTP tests and
`MESH_RECALL_INTERFACE.md`. The component wraps canonical `Ledger.search`;
it is not activated or wired into the current Mesh UI.

The versioned local read contract is `POST /v1/recall` with exactly
`{schema: "onoes-mind-recall/v1", query, limit}`. The owner-supplied bearer token
is authenticated by the ledger; no identity/scope override is accepted.
Success returns schema, requestId, source `canonical_ledger`, observedAt and
records with existing project/scope/hash/source/provenance. Limits: query512
characters, results1–20, request4096 bytes, response65536 bytes. Browser Origins,
wrong hosts, mutations, unknown fields, malformed framing and duplicate keys
are refused. No token/query logs, CORS or response caching.

All175 canonical tests passed locally, including8 new HTTP tests with temporary
synthetic ledgers. Private/shared isolation, token revocation, immediate deletion
visibility, no-write reads and bounded/error responses are verified. No real
memory service, principal, grant, credential, runtime binding or startup task
was created. Phase10/live activation gates remain open.

Next implementation is the bounded Mesh server-side client, followed by the
actual adapter -> canonical ledger -> Mesh view journey with synthetic data.
Real data access and deployment remain separately reviewed decisions.


## Mesh adapter and deliberate recall view (2026-11-07)

`lib/mind-recall.mjs` now enforces fixed IPv4-loopback routing, no URL credentials
or redirects, server-held bearer token,4s timeout,64KiB streaming response bound,
version/source/record/provenance validation and fixed errors. Query/results are
not persisted. The admitted `/api/mind/status` and `/api/mind/recall` routes do not
accept endpoint/credential/identity/scope configuration from the browser.

Live Mesh has no configured reader. The only current injection seam explicitly
requires standalone mode and disposable_fixture process options. No environment,
CLI or browser switch enables private memory access. Connection checking and
recall are separate deliberate clicks; no page-load search, transcript ingestion,
automatic write or skill/MCP execution occurs. UI renders plain text, shows source
and provenance, clears results/query on loss of access and ignores late responses.

The explicit local integration command is `npm run test:mind-integration` after
setting `MESH_MIND_SOURCE` to the canonical Onoes-Mind checkout. It starts only
owned disposable Mesh/Python processes and an in-memory synthetic ledger, checks
real HTTP -> ledger -> scoped records and offline refusal, then closes them.
The real browser also verified permitted records, literal script-like text and
lock clearing. This proves synthetic integration, not live-memory or physical
phone acceptance. A responsive attempt with the mobile navigation/admission
controls was inconclusive; do not label that acceptance complete.

Before live activation, select and verify the actual memory store, reader caller,
read grants, connection/process ownership and concurrent-writer behavior; provision
access only through the separate reviewed deployment. Full shared agent context,
reviewed writes, skills/MCP and cross-channel ingestion remain unfinished.

## Echo review reconciled: live binding remains blocked (2026-11-07)

Eddie supplied Echo's review of Mind source
`1ee82e5891f0fae54edb1bd8e874b9abbb3de97b`. Echo independently checked that
source revision and boundary implementation, but did not rerun the 178 tests or
verify Mesh revision d8445bf. The local test results above remain Nims's evidence.

Decision: use Mind's canonical ledger as the intended authority. Do not create
an independent Mesh memory store. No live canonical database path or ownership
record has been established. A workspace path is not a database identity.
Compatible SQLite tables are insufficient proof: a wrong, stale or synthetic
store can have the same schema. The existing read-only opener therefore remains
an offline-qualified component, not a qualified live binding.

### Unapproved binding record template

Every field below is UNASSIGNED until supported by evidence and reviewed. This
is a planning template, not configuration, an authorization or a runtime record.
Do not place credential values or private memory contents in this document.

| Required field | Current state / evidence needed |
| --- | --- |
| Exact canonical database path | UNASSIGNED; owner-confirmed actual file |
| Durable store identity and provenance | UNASSIGNED; canonical Mind-owned identity and verification method, independent of schema compatibility |
| Owner and authority record | UNASSIGNED; who designates this ledger canonical and where that decision is recorded |
| Environment | UNASSIGNED; explicit local production/test classification |
| Permitted shared-project scope | UNASSIGNED; exactly one owner-approved scope ID |
| Service principal | PROPOSED mesh-recall; not currently supported by principal creation, provisioned or approved |
| Permission | PROPOSED read-only to the single scope; no private agent grants |
| Credential custodian reference | UNASSIGNED; reference only, never token material |
| Revocation procedure and custodian | UNASSIGNED; identity/credential revocation and next-read rejection evidence |
| Reviewed source revisions | Mind review 1ee82e5; final binding must pin the then-reviewed Mind and Mesh revisions |
| Runtime binding approval | NOT APPROVED |
| Separate live activation approval | NOT APPROVED; Phase 10 Gate 10.9 remains open |

### Offline acceptance still required before a live decision

- [ ] Verify the selected store's Mind-owned identity/provenance; refuse a
  compatible but wrong-identity store, as well as an incompatible store.
- [ ] Qualify the dedicated service-identity contract without borrowing Echo's
  or operator's credential; permit only the explicitly designated shared scope.
- [ ] Preserve provenance on allowed shared recall; deny private/out-of-scope
  reads and caller-selected identity/scope overrides.
- [ ] Demonstrate corrected/superseded old content is absent on the next read.
- [ ] Reconfirm purge and revoked-credential visibility on the next read.
- [ ] Demonstrate no writes or external calls across that boundary.
- [ ] Review actual-store concurrency separately; synthetic tests do not prove
  production concurrency, source identity, or activation approval.

Existing synthetic tests provide useful partial evidence for scope enforcement,
provenance, purge, revocation and read-only behavior. They do not close the
unchecked items above merely by being green. Shared facts must be deliberately
admitted/promoted; private mirroring and raw chat ingestion remain disabled.

Next implementation should investigate existing Mind store identity and correction
semantics before adding validation. Do not invent a second memory authority or
select a real file/scope/credential on Eddie's behalf. Ask for the concrete owner
choices only once the binding and acceptance work is reviewable.

## 2026-11-07 prepared binding milestone

Canonical Mind now contains an inactive bound-reader preparation module. A
reviewed record must include the existing unapproved fields above plus its exact
store UUID and filesystem device/file ID. Scope is one project shared scope;
mesh-recall is a dedicated service identity. Its purpose-specific credential is
not accepted by the ordinary writer. This was necessary because a synthetic
probe found ordinary writer authentication does not itself enforce can_write.
No live metadata, identity, scope or credential was provisioned.

Bound-reader acceptance now includes wrong compatible store/file, copied UUID,
private/extra/writable/disabled grants, non-service tokens, revocation, no-write
HTTP/SQLite behavior and real Mesh -> bound Mind -> shared-only records. This
is synthetic qualification, not owner approval, real-store provenance or physical
release acceptance. See canonical Mind MESH_RECALL_INTERFACE.md for the exact
contract and anti-rollback/legacy-writer limits. Normal Mesh remains disconnected.

Canonical prepared binding source milestone: c5c90017f374a4d83b4178c623352771c274d148.
Local full suite188 PASS; actual Mesh HTTP integration2 PASS. Purpose-specific
recall token is rejected by ordinary writer authentication and remember; ordinary
writer credentials are refused by bound recall. This preparation does not activate
memory or qualify all legacy write policies. Exact live database/owner remain a
pending owner question; no actual scope/custodian/credential chosen.

## Operator source clarification and D-drive proposal (2026-11-07)

Eddie confirmed there is no verified live Mind database instance with an
established path and owner to reuse. He asked to identify the canonical database
and owner first and prefers D: if a new Mind-owned instance is needed. This is
source/planning guidance, not permission to create or activate a live store.

Local disk inspection identifies D: as NVMe and E: as a separate USB disk.
D: is a reasonable active SQLite location; this is not a measured latency claim.
The existing E:/App-Backups/ONOes-Mind root remains the backup proposal.
A filename-only inventory inside D:/Dev/Onoes-Mind found only the historical
bad.sqlite audit fixture, which must not be promoted into a live ledger. No
memory database was opened. This limited inventory does not prove no other
instance exists elsewhere on the machine.

Proposed future data location: D:/App-Data/ONOes-Mind/ledger.sqlite, owned by
Mind's authority: Eddie owns its data/keys and Echo/Nims operate it;
the specific service/runtime identity remains unassigned. Canonical
source stays D:/Dev/Onoes-Mind. The private folder was approved and created as D:/App-Data/Onoes-Mind;
read-only verification found it empty. No ledger file has been created.
Exact data path, authority/custodian, reviewed initialization and restore/deletion
history must be resolved in the binding record before provisioning. Mesh must
not create a separate memory store. Single-scope service credentials, grants,
service startup and live activation remain separately unapproved.

## Operator ownership and future team-tool contract (2026-11-07)

Eddie owns Mind's data and recovery keys. Echo and Nims (Codex) operate it.
This establishes responsibility; exact OS/runtime identity and real initialization,
credential/grant provisioning and activation remain separate reviewed decisions.

**Echo project-reader compatibility, November 22, 2026.** The MCP client from the Windows environment used by the running Echo gateway discovered the Mind project reader through an isolated Hermes profile. Through the Hermes tool registry, the same client read a synthetic print specification, then its replacement dimensions, CAD filename and matching source reference. The earlier revision, private fact and other project were absent from the updated result.

Withdrawing the test tool grant blocked the next call. Restoring it allowed the same client to read again. Rotating the test reader credential then blocked the next call with the tool grant still present. This qualifies the client and reader together. Live acceptance still requires custody of the dedicated reader credential, confirmed exclusion of delegated workers, and a real Echo response through the intended chat channels.

**Worker access to Echo’s project reader.** In Echo’s installed Hermes version, an ordinary delegated worker received a parent’s sample MCP reader even when its assignment requested only the worker utility. Turning off MCP inheritance excluded the reader for that explicit assignment. A worker with no tool list still inherited the reader.

For the print pilot, route workers through a separate process with its own profile containing only the tools intended for those workers. A fresh process with that setup kept the utility and excluded the reader in both assignment modes. The installed Workroom native binding selects the Echo builder and independent Nims reviewer from the locked plan. Its native builder requests a fixed file-only or file-and-terminal profile with user configuration disabled. The Mesh and Echo gateway processes currently run under the same Windows account. Tool selection alone provides no evidence of separate credential custody. Verify that custody before enrolling Echo’s live reader.

For future MCP tools, build reusable tools once and make them discoverable through
a shared team catalog. Mind can retain approved tool/skill descriptions, versions,
usage guidance and provenance. Actual tools execute through MCP servers with
server-enforced agent/project permissions; a recalled memory or instruction is
never an authorization grant. Each harness needs its supported MCP connection or
an explicitly configured adapter. Joining Mind alone does not configure a client.

Approved common read-only tools may be available to the team by default; writes
remain bound to the chosen workspace and existing approval policy. Credentials
stay with the executing service, not general shared memory. Agents keep separate
identities and revocation. Use private local/Tailscale routing where supported;
no public gateway or expanded access is authorized by this architecture note.
This is a future requirement for shared skills/MCP, not an implemented catalog,
connector, permission store or gateway. Finish the current store/recall work first.

## Recovery-key bundle preparation accepted (2026-11-07)

Eddie approved proceeding with the proposed recovery-file workflow. Canonical
Mind source188b6f20ab7d7748fa70d351af051cd4295efb10 now contains an inactive
Node24 key-bundle API and MIND-RECOVERY-GUIDE.md. Existing Node crypto is used;
no shared Python crypto package was installed/upgraded. No real Mind store,
Google entry or live key was created.

The temporary encrypted-file journey recovers explicit integrity keys, restores
a populated Mind snapshot and preserves newer deletion history. Full canonical
pytest199 PASS, with a driver running5 Node cases; focused recovery11 PASS.
Wrong password, ciphertext/tag modification, wrong store/environment and invalid
format/KDF fail without releasing keys. Returned buffers are local runtime
material, never agent/MCP/browser/log output. The envelope protects integrity
keys, not SQLite database contents. Runtime vault protection, private folder
permissions, secure user password entry and real setup/activation remain open.


## Workroom project-history recorder audit - November15,2026

See WORKROOM-MIND-SYNC-AUDIT.md for the current read-only source audit of Mesh
and canonical Mind76c0273. Recommend one deterministic outbox/receipt adapter,
not another agent or the local-test task scheduler. Workroom owns task stages;
Mind owns canonical project identity and records source-bound progress facts.
Shared write authorization, full-envelope event binding, confirmed receipts and
correction/deletion replay rules need a qualified Mind-owned API. One Done card
does not complete a project. No database/key/service/principal was created or
activated. This audit changes no runtime and does not close local C1/C4/E2.


## Current protected-setup requalification - November15,2026

See MIND-SETUP-READINESS.md. Current native setup fixture12cases PASS at Mind76c0273;
no real keys/store/service used. A valid empty snapshot with unchanged deletion
history reproduced canonical strict-newer refusal before destination creation.
The guide already records this policy gap and an owner-decision-pending equal-
history amendment. Live setup is not recommended until a qualified recovery
contract exists. Do not manufacture deletions, silently relax frozen restore,
or substitute adjacent hashes for independently trusted current evidence.
