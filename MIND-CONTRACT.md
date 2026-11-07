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
