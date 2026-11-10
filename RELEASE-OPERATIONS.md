# Mesh private release candidate

## Current readiness - 2026-11-10

Running Mesh build `114cf18da16a` was reconciled with saved source on 2026-11-09.
All 23 data tables and 14 cards were preserved; shared services were unchanged.
Evidence: `integrations/live-source-custody-qualification.json`.

- Local/phone: Eddie confirmed card creation, editing, movement, saved review/Done,
  both themes, background/resume, rotation with an unsaved draft and network recovery.
  The full end-to-end production worker workflow still requires acceptance.
- Latest full local gate: `npm test` passed 468 checks (367 Node + 101 Python),
  with static/design checks; all 210 Workroom tests passed. The server now accepts
  an explicit native worker connection and uses it for dispatch, observation and
  verified retirement. An actual admitted HTTP test proved a mismatched profile
  holds without a prompt or Relay fallback. This used a synthetic transport;
  the normal launcher still supplies no binding and enrollment remains off. See
  `integrations/native-server-binding-qualification.json` and the project checkpoint.
- Native gateway transport: hidden, lazy local helper implemented using existing
  discovery/private-control ticket helpers; remote targets are refused before
  authentication. A real read-only check looked up the existing unsubmitted probe
  twice in 539 ms, using one helper that exited cleanly. Admissions stayed zero;
  no session creation or prompt submission. Synthetic process/WebSocket tests
  cover uncertain disconnect, no automatic reconnect/resend and sanitized errors.
  The trusted bootstrap helper is available, but the normal launcher remains off.
  See `integrations/native-gateway-transport-qualification.json`.
- Guide team pilot: one synthetic build, verified retirement and one independent
  synthetic review passed through the actual admitted server; results survived
  restart with owner review still pending. The prepared real trial is guide-copy
  only, one builder plus one Nims review, no retries or automatic Done. It requires
  separate owner approval tied to its exact scope hash. Native workspace selection
  may narrow only within the checkout; normal startup remains unchanged/off.
  See `integrations/guide-team-pilot-qualification.json`.
- Main-PC health: live read-only CPU/RAM/GPU and fixed supervisor observations
  verified, including shared concurrent refreshes and honest unloaded/unknown states.
  Responsive UI and selected-workspace reload verified. Model lifecycle controls,
  per-model resource attribution and the other two machines remain unqualified.
- Native worker bridge: the finite file-only real Codex path passed on November 10.
  Two bounded trials exposed about 80 seconds in client construction: a Git
  version lookup used by request headers. A targeted two-file fix preserves
  Hermes identity and canonical CLI provenance checks while removing Git from
  header construction. Final real worker construction took 1.566 seconds; the
  task completed, its exact requested append was independently verified, all
  original guide bytes were preserved, and the worker exited. No restart.
  This qualifies the tested file-only/max-four-turn path, not production
  enrollment, terminal tools or the complete automatic board/team workflow.
  See integrations/native-startup-batch-qualification.json and
  integrations/native-header-startup-qualification.json.
  The updated disposable fixture also passes with all nine bridge/header files
  byte-identical to the installed implementation; its provider remains synthetic.
  See integrations/native-header-fixture-qualification.json.
- Explicit openai-codex closed-profile preflight is implemented and tested.
  One live unsubmitted session's public policy matched the requested file/terminal
  toolsets and workspace, with zero admissions. After bridge installation, its
  authenticated closed-profile lookup also verified no API key configured for
  that exact session; repeated reads left admissions at zero. The finite file-only
  real-generation path now passed as above; production enrollment remains unqualified. See
  `integrations/native-installed-profile-qualification.json`.
  Eddie approved bridge maintenance on 2026-11-09;
  all seven reviewed files are installed and the gateway drained/restarted safely.
  Health, installed hashes, unchanged Mesh/model processes and zero-prompt public
  policy readback passed. Initial cold startup exceeded its first health window;
  configured MCP startup errors remain a separate finding. Production worker
  enrollment and Rook activation are still unqualified. See
  `integrations/native-bridge-maintenance-qualification.json`.
- Rook candidate ede8e4ae is already included in this checkout. Its local tests
  are not deployed acceptance. Rook remains OFF pending its own approved identity,
  reporting transport, one scheduler owner and deployed integration checks.
- The in-app parent goal retains all six original stages: two done, three working
  and one blocked; owner review remains pending. Its saved evidence is current
  through startup milestone 57397b0 and the prior 449-check baseline. The complete
  build goal remains open.
- Mind live database/keys/access remain OFF. Eddie owns; Echo and Nims operate.
  Canonical store identity must be established before connection. Shared memory,
  skills and MCP tools remain unfinished. Model-service maintenance was declined.
- Backups are manual/milestone only to E:\App-Backups, per Eddie's decision;
  off-device protection is deferred. The latest verified backup is recorded in
  the checkpoint. Whole-app production acceptance is not claimed.

Historical records below describe their dated baselines, not today's loaded code.

The canonical current Workroom installation is this `mesh-workroom-ab` checkout,
served at https://emitchell.tail8c4a75.ts.net:8453/#workroom through Tailscale Serve
to loopback port 4320. The selected store is `data/workroom-preview/tasks.sqlite`.
The original 8446 installation and its separate data remain preserved; no stores
have been merged or relocated. Use 8453 for current Workroom work.

Overview → App shows the package version, running process's startup source digest,
start time and selected database. The digest covers package/server/serve plus
lib/public/shared/config, including uncommitted source. It is not a Git commit or
an assertion that subsequent disk edits are loaded. Restart after deploying code.
The admitted, no-cache `/api/release` response provides the full source digest.

## Startup and recovery

Run `powershell -NoProfile -File integrations/restart-workroom-preview.ps1 -Action Status`
from this checkout. Use Start, Restart or Stop deliberately. The launcher verifies
executable, start time, command and app identity before stopping its owned process;
it refuses unrelated port occupants. Stop pauses the named recovery task; Start
or Restart resumes it. Do not use default npm start for the owner installation.
The process receipt is `../workroom-ab-preview-process.json`.
The limited-user task `ONOes Mesh Workroom Recovery` restores a missing process
at logon and on its minute check, without replaying tasks or restarting shared apps.

## Backup and rollback

Run `node integrations/backup-mesh-to-library.mjs`. Open
`E:\App-Backups\ONOes-Mesh\LATEST.txt` for the latest verified matching source/data
snapshot and RESTORE.txt. Restore into an isolated location first. Preserve the
current database with WAL/SHM before any deliberate replacement. Do not merge the
original 8446 data or overwrite another checkout. The root is shared by app-specific
backups; this command only backs up Mesh. Eddie selected manual and milestone
backups on 2026-11-07. No automatic backup schedule is enabled. Keep labelled
milestone copies; no automatic pruning or deletion is configured. E: is the chosen
local destination; off-device protection remains deferred. Credentials, external
Relay configuration and models are excluded.

## Qualification and remaining gates

This is a private release candidate, not a whole-app production acceptance claim.
The real worker → review → correction → review flow, permission denial/recovery,
local database/source restore and named process recovery have recorded evidence
in WORKROOM-AB-CHECKPOINT.md. Agent lists and delivery receipts are not proof of
coding tools, repository access or completion. Agent workspace opens those same
saved Workroom cards; it introduces no scheduler or automatic dispatch.

Physical-phone recovery checks are accepted (see the case table below).
Eddie confirmed creating/editing cards, touch-dragging with a lead, reload/theme
persistence, background/resume, rotation with an unsaved draft and network
reconnection. He also confirmed starting the recovery-notes scoped team from
his phone. These checks do not qualify the newer native automatic worker-to-review
route or Rook activation. Inference lifecycle
qualification is separate: Eddie selected the currently running Nemotron 3.5 Bolt
lane first. Its prepared identity-bound bridge is not installed; Eddie explicitly
deferred shared-model maintenance. Keep the model service running. Other engines
and binary availability do not qualify ownership or lifecycle. The qualified
Mesh-only team lane uses locked scope, Echo building and DeepSeek/Nims review,
then pauses for owner review. Mind deliberately retrieves selected saved Workroom
records under [MIND-CONTRACT.md](MIND-CONTRACT.md); it adds no personal memory
store or automatic writes. Additional workspaces/runtime profiles and
push/Telegram synchronization remain unqualified/deferred. Review this record
when the runtime lock or owner acceptance changes.

Ordinary Relay acceptance and compatibility decisions are recorded in RELAY-INTEGRATION.md. The new conversation surface exposes one explicit selector and one ordinary submit path; legacy snapshot-era header/session choices are bypassed. Actual private history/lock/reconnect acceptance sent no real message. Phone hold/drag and typing/focus are owner-confirmed. Workroom background/resume, rotation/draft and network reconnect are owner-confirmed in the recovery case table; these do not claim a new ordinary Relay send interrupted in flight.

## Local model supervisor observations

The named Mesh launcher enables MESH_MODEL_OBSERVATION=1. Non-standalone Mesh
then adds a read-only supervisor catalog to the admitted inference status. Only
fixed loopback GET /health and GET /v1/models on the existing registered lanes
are allowed. No generation/admin endpoint, model switch, remote URL or proxy
configuration comes from the browser. Standalone/default instances make no probes.

The Inference panel refreshes this observation every4 seconds only while visible,
connected and admitted. Concurrent reads share one probe set. Observations expire
after5 seconds and clear on privacy lock; late responses cannot restore them.
Reported loaded is a supervisor claim, distinct from retained process custody,
GPU attribution and qualification to control a model. Missing model files, failed
identity checks, loading races and unavailable services remain explicit.

Eddie selected Nemotron 3.5 Bolt as the first model for control qualification. Its
current runtime is the bundled b11669 on the supervisor's existing8099/child8199
lane. Do not use the legacy b11446 Flash-Next profile for Nemotron. Read-only
health/model identity is proven; load/unload/chat/cancellation are not yet qualified.
Before enabling controls, add and verify an identity-bound supervised control path:
exact runtime/model and original-process custody, atomic residency preconditions,
receipt/idempotency, restart/unknown-outcome handling and cancellation readback.
The current global /admin/unload has no expected-resident identity and cannot
safely serve as Mesh's qualified stop adapter. The proxy holds its lock through
generation, so disconnect/cancel behavior also requires explicit qualification.
Preserve the active resident model while preparing this work.

## Relay service recovery

Use `powershell -NoProfile -File integrations/relay-service.ps1 -Action Status`
to identify the existing loopback service and its launcher/listener PIDs. `-Action
Start` starts the existing installed service hidden only when no matching process
is running or starting and its port is free. It never kills a process or modifies
Relay source/config/credentials. An unrecognized port owner is a refusal, not a
cleanup target. This is an explicit recovery helper, not a new periodic task.
Relay data remains in its original private store; take an online SQLite snapshot
before recovery/maintenance. Restoring Relay does not restart its agent backends.

## Prepared Nemotron control component - not live

`lib/supervisor_mesh_control.py` now contains the fixed-Nemotron owner gate,
retained-supervisor binding and versioned routing seam. Run `npm run
test:supervisor-control` for its refusal, receipt, original-process and restart
tests. The component accepts only a verified empty lane for load or the exact
verified Nemotron resident for unload. It never adopts or terminates a discovered
PID. Binary/path/arguments/working-directory/listener evidence must match; load
requires child health/model readback. Expected-state tokens are consumed before
work; duplicate commands return receipts, changed payloads conflict, stale owners
and busy native work refuse. New boots invalidate old tokens; lost/unknown
receipts must be inspected, never converted into a fresh automatic replay.

`node integrations/prepare-nemotron-supervisor.mjs` writes a fresh candidate under
private data/, pins its original supervisor/dependency/runtime hashes, and checks
Python syntax. It changes no live source and starts no model/supervisor. Then
`npm run test:supervisor-candidate` exercises the actual patched Handler on
disposable HTTP ports with a fake owner. Those tests are not native lifecycle
qualification. The candidate has bounded JSON routes only on the existing8099
lane, code/boot identity and receipt reads that remain available while an owner
operation holds its lock. Existing legacy endpoints are preserved.

The durable SQLite journal, fixed client, controller and admitted confirmation UI
are implemented. `npm test` now includes the Node model-control and nonempty
model-table backup/restore tests. After preparing the exact current candidate,
`npm run test:supervisor-integration` also exercises actual Mesh admission, the
real client and actual candidate HTTP/gate on disposable ports with a fake owner.
This proves protocol integration, not a live model lifecycle.

If an original receipt is unavailable, status remains UNKNOWN and new model work
stays blocked. Resolve unknown command creates a session-bound proposal; explicit
confirmation asks the source-bound native gate to inspect/fence that original
request under its owner lock. Existing receipts are returned instead of replaced;
active work or uncertain ownership refuses recovery. A verified fence consumes
the current precondition, prevents delayed original execution and durably retains
the old UNKNOWN outcome and audit evidence. It does not unload, load, or claim
that the original action failed. Lost recovery replies leave Mesh blocked until
readback or another explicit recovery confirmation. No automatic command replay.

Still required before enabling Mesh controls: revalidate/review live source and
process ownership, coordinate the shared-supervisor cutover, then prove real
Nemotron load/unload, chat cancellation, lost-response/restart and fencing recovery. The current resident model is
untouched. Prepared code and passing fixtures do not enable native controls.
Generated Python bytecode is excluded from source backups/release hashes; the
Python source itself remains included and versioned.

## Guarded Nemotron chat

Mesh chat uses the source/boot-bound /mesh/v1/chat route on the supervisor, never a
POST directly to the model child. The native gate checks the original resident
under its existing owner lock, consumes the observed precondition before sending
one request, and keeps that lock throughout generation. The supervisor idle timer
is refreshed before and after work. A returned answer is usable only after model
health/GPU verification and unchanged original process identity; the new token
must match the token returned for that chat. No prompt/reply is stored in the
operation journal or native gate receipts.

Cancellation shuts down only that chat's original child connection. Closing the
connection does not establish cancellation: the native gate remains busy until
readback shows every child slot idle, or the retained original process handle has
exited. Busy/unavailable readback remains UNKNOWN and blocks subsequent controls;
status may reconcile it later, without replaying chat. Disconnect/timeout can
therefore return UNKNOWN rather than inventing a completed cancellation. Control
JSON remains4KiB; chat JSON has a separate20KiB bound for escaped3000-byte prompts.
The original model API endpoint,512-token output bound,40-second native deadline
and50-second client deadline are fixed. Responses are bounded independently.

`npm run test:supervisor-control` includes actual socket cancellation against a
fake child with Connection: close headers (no running model required). Candidate
HTTP and cross-chain tests also exercise guarded chat. These are preparation;
actual Nemotron cancellation/idle readback and the shared supervisor cutover still
require real lifecycle qualification before MESH_NEMOTRON_CONTROL is enabled.

## Stop, pause and interrupted work

These controls have different effects. A closed page, disconnected stream or
paused team is not evidence that native work stopped.

| Surface | Actual effect | Completion evidence / current limit |
| --- | --- | --- |
| Local command Cancel | Requests cancellation of the exact current saved execution; verifies its owned process tree | Verified cleanup is required for �Cancelled.� Missing/false cleanup is �Cancellation unconfirmed�; work may remain running. No automatic retry. |
| Team Pause next team steps | Prevents future handoffs | Already accepted agent work continues; pause does not claim cancellation. |
| Close saved team attempt | Closes the paused/review attempt and preserves history | Does not cancel accepted agents. Unresolved accepted work still prevents a new attempt. |
| Cancel unsent worker preview | Discards the preview before dispatch | Nothing is sent; no accepted worker is stopped. |
| Echo / Deep conversation | Read or send to the explicitly selected conversation | No qualified per-task native cancellation adapter. Stop reading is not stop execution. |
| Nims connection close | Closes the connection; unfinished local receipts become interrupted | No automatic replay; interrupted is not independently verified native cancellation. |
| Model controls | Prepared Nemotron bridge only; disabled in live Mesh | Real load/unload/chat/cancellation acceptance awaits owner-authorized maintenance. |

Real Windows local-command acceptance on 2026-11-07 used isolated HTTP servers,
SQLite stores and disposable Node root/descendant processes. Explicit cancel
verified original handles exited, persisted its result, rejected stale/wrong
run IDs, admission/origin violations and repeat cancel, and reopened without
replay. A separate crash check verified original caller/bridge/root/descendant
handles exited; reopening retained UNKNOWN/server_restart with null cleanup,
refused replay and did not turn a restart into a success/cancellation claim.
Run locally with `node --test --test-timeout=30000 test/m3-crash-compose.test.mjs`.
These checks do not qualify remote agent or model cancellation.

Relay places long connection and privacy details under Conversation details.
Refresh preserves a reader's earlier position; readers near the bottom follow
new messages. Jump to latest returns to the latest saved exchange. The owner's
phone loading/reloading is confirmed; background/resume and the latest chat
layout still require physical-phone acceptance.


## Telemetry polling while mobile/backgrounded

Control and the shared Inference host readings allow one active collector read,
with an8s browser timeout. Hidden pages abort their read, clear displayed metrics
and stop polling; returning starts a fresh read. A late pre-hide/timed-out result
cannot replace the new reading. Existing host/model expiry rules remain active.
These are read-only HTTP observation controls, not cancellation or shutdown of
model generation/services. Deterministic lifecycle tests and a real stalled-read
browser fixture pass; physical-phone acceptance remains separate.


## Local verification commands

`npm test` includes baseline/static checks, actual npm-start HTTP assets, model
protocol tests, workspace/privacy checks and portable Workroom handoff/review/
permission/reconciliation/session regressions. `npm run test:workroom` runs the
portable workflow group alone. These checks use isolated local fixtures; no live
agent/model sends or GitHub Actions are required.

`npm run test:release-evidence` separately verifies the historical live rework
record and an actual owner snapshot restore. It requires the existing private
`../workroom-rework-final.json` and `../workroom-backup-latest.json` plus its
snapshot. Keep these checks separate from portable default tests; do not publish
private evidence or silently replace missing live evidence with a synthetic pass.

For the prepared cross-repository Mind path, explicitly select the canonical
checkout with `MESH_MIND_SOURCE` and run `npm run test:mind-integration`. That uses
only temporary synthetic memory. Neither a passing fixture nor these commands
authorize live memory activation or replace physical-phone acceptance.

## Overview source and freshness meanings (2026-11-07)

Overview reports adapter observations at the displayed check time. Those are
snapshots, not proof of model readiness, coding access, task completion or recall.

| Surface | Actual authority / meaning |
| --- | --- |
| Relay bridge | HTTP Relay snapshot when source is live_relay_http; isolated_relay identifies the isolated adapter. Reachability does not prove a send or completed task. |
| Legacy inference adapter | Optional original service observation. Separate Inference/Control supervisor and PC readings own their own source times, expiry and unavailable states. not_configured here does not say no model is running. |
| Standalone Agent adapter | Optional original service observation. Agent separately displays Relay peers and saved Workroom handoffs; roster presence does not prove coding capability. |
| Legacy Mind adapter | Optional original service observation. Workroom owns selected task snapshots. Canonical Onoes-Mind recall has a separate explicit connection check in Mind and remains disconnected. |

Overview clears prior connection rows on invalid/unavailable responses. Each row
shows source, observation time, probe duration and errors. Consult the relevant
workspace for its separate operation result and freshness status.

## Readiness words describe different evidence

| Label | What it proves and where it comes from |
| --- | --- |
| Service reachable | A timestamped adapter/health observation succeeded. It does not prove an agent can code, a model is resident or a task ran. |
| Agent available | A Relay roster/status observation names the peer. Capabilities and the selected current conversation must still match before a send; roster status is not repository/tool access. |
| Model reported loaded | A recent supervisor observation reports that model on that lane. The5s observation lifetime is separate from Control's15s hardware lifetime. It is not retained process custody or proven GPU attribution. |
| Runtime qualified | Exact runtime/model/owner and actual load/chat/cancel/unload evidence have been accepted for that profile. Native Nemotron lifecycle is still unqualified; its prepared bridge is inactive and controls stay gated. |
| Task accepted | A retained send/receipt identifies the exact task revision, destination and attempt. It does not prove a reply, successful implementation or approval. Unknown sends require same-identity deliberate recovery. |
| Task complete | The saved workflow has current evidence, a valid independent review and a deliberate owner Done transition. A service status, worker report or all-done checklist alone cannot substitute. |

Overview source labels and workspace observations were reconciled in the actual
private app. The observation-meaning map closes B1's explanation requirement;
it does not close D2's stronger runtime-to-GPU attribution or C's physical/live
release acceptance. Each unavailable/stale state retains its own source/time
meaning rather than being converted into a healthy completion claim.

## Same-origin active-tab admission reuse (2026-11-07)

A new explicit/authorized connection asks an already admitted, unlocked, visible
same-origin Mesh tab for a current proof over BroadcastChannel. The handoff is
RAM-only and contains only the CSRF proof and expiry, never cookie IDs, actors,
grants, cards, messages or drafts. The receiver still verifies `/api/health` with
the current HttpOnly cookie and candidate proof before admission. Rejected proof
clears access; receipt of a channel message alone never grants it. There is no
cross-origin channel, network service, storage expansion or session TTL extension.

The frozen session manager/HTTP guard and recovery nonce rotation are unchanged.
Without a responding active tab or supported channel, normal bootstrap/recovery
continues. This does not guarantee simultaneous cold-tab startup or background/
partitioned-browser continuity. Existing lock, expiry, logout and privacy clearing
remain authoritative. A tab does not replay tasks/messages when it connects.

Actual two-tab browser acceptance on a disposable store: save in tab B; stale
Save card in tab A is rejected with Task changed. Reload before saving, while
its unsaved field stays visible. Cancel edits closes that stale editor; reopen
the card to see tab B's saved value. Copy any draft you want to reapply before
cancelling. No silent overwrite or automatic merge. Both actual live Tailscale
board tabs also stayed connected after opening the second and refreshing the
first; owner cards were not edited for this check.

## Device-wide GPU metric validity (2026-11-07)

The NVIDIA collector now parses exactly one10-field device sample. Explicit zero
is valid; blank, unsupported, nonnumeric, negative and nonfinite counters remain
unknown. Percent counters outside0–100 are unknown; zero/unknown total memory
cannot produce a percentage, and used memory above its reported total is refused.
Malformed, oversized and multi-device output is unavailable rather than silently
blending cards or choosing a GPU. Supporting multiple devices requires a separate
per-device view; three machines are not assumed to mean one summed GPU sample.

The API marks these figures scope=device, attribution=unverified. Control notes
state that the whole graphics card includes other apps and per-model usage is
unavailable. High usage is not proof that a new model can load or must evict an
existing one. Existing15s hardware freshness/clearing and separate5s supervisor
observation rules remain unchanged. D2's strong model/runtime/GPU attribution and
D3's real control lifecycle are still open; no model operation was qualified here.

## Served-browser dependency release check (2026-11-07)

The mandatory npm-start HTTP test now fetches every linked shell script and
stylesheet, follows static and literal dynamic module imports recursively, and
checks status, JavaScript/CSS MIME and JavaScript syntax on the actual served
body. It verifies both the backend and phone-origin preview adapter. Current
coverage is23 linked resources per entry point, including session-entry and
nested Workroom modules. No imports are evaluated and no third-party URL is
contacted. Computed dynamic imports require explicit coverage rather than being
silently skipped. The traversal is bounded to128 resources,1MiB bodies and3s reads.

Negative HTTP fixtures prove missing modules, HTML served as JavaScript, and
external dependencies fail the gate. This catches the missing-static-allowlist
failure observed during two-tab work. Import-stripping VM tests alone do not
qualify browser startup. This delivery/syntax check does not claim DOM behavior,
CSS layout/assets imported by CSS, service-worker lifecycle, arbitrary JavaScript
parsing, physical-phone acceptance, runtime/model controls or live memory access.


## Historical local qualification snapshot - 2026-11-07

Runtime build ad3fe3cfb807 includes Agent changes committed as d1143fb.
The complete local npm test passed 207 checks (40 baseline, 1 HTTP, 29 model,
45 workspace and 92 Workroom), zero failures. Separate npm run test:ui passed
13 mock UI checks. These do not qualify the uninstalled native model bridge.

Eddie confirmed actual-phone create/edit/save, touch move with Nims/Echo owner,
reload/reopen and theme switching. Remaining phone acceptance includes long
checklists, handoff, permission/results, recorded review and deliberate Done,
plus network/background/session recovery.

Agent distinguishes configured roles, adapter-declared capabilities and saved
task evidence. Nims declares read-only planning/review, with building unavailable.
Echo has verified bounded Mesh artifacts and source-linked reports; this grants
no other repository access. The existing real automatic Echo-to-Nims qualification
ended at needs_review with pending/unapplied review, not automatic Done. Its seven
artifact tests pass. This proves the review gate, not whole-app owner acceptance.
Exact receipts and remaining requirements are in the running private checkpoint.


## Latest verified candidate - 2026-11-07

Live build6147b15367ea (runtime source bb9a029) is a private candidate, not final
acceptance. Consolidated current-code checks: npm test210/210, test:ui13/13 and
test:release-evidence7/7 PASS. Complete counts are40baseline+1HTTP+29model+
45workspace+95Workroom. The latter two commands are separate checks, not added
to the default-suite count. The saved guide workflow exercised a useful Echo
build, actual Nims changes-requested finding, Echo correction and fresh approved
Nims review. Its owner-recorded approval and deliberate Done remain pending.

The selected E-drive backup contains current exact guide/adapter/timeline/health
source bytes and13cards; hashes, isolated data restore and restored-source HTTP
passed. Manual/milestone backup policy is implemented; no automatic schedule or
pruning is enabled. Off-device protection is explicitly deferred, not verified.

Remaining acceptance: full physical-phone task/review/Done and network/device
recovery, owner release custody, and broader team qualification. Model control
maintenance remains deferred; load/stop/unload/chat controls are disabled while
read-only PC/model observations remain available. Mind folder is still empty;
canonical store enrollment, approved recovery policy, access and live activation
are not complete. Shared memory/writes/skills/MCP, external apps and the laptop/
future AI-box fleet remain in the active overall objective. The running private
checkpoint is authoritative for later evidence and changes to these gates.

## Machine connection observations

Inference -> Machines / read-only exposes the existing fixed PC/laptop Tailscale
records. Check machine status performs an admitted local CLI read. These are
cached connection observations, not packet probes, remote hardware measurements,
model readiness or control permission. The future AI box has no configured identity.
No check yet is Not checked; an unusable first result is Unavailable; an expired
positive check is Check expired. Refresh deliberately to obtain current records.
Native node-probe v1 compatibility and its separate provenance fields remain intact.

## Current PC/phone recovery acceptance

The current C2 recovery contract is accepted from these distinct evidence sources:

| Case | Evidence and result |
| --- | --- |
| Phone background/resume | Owner returned from another app and reopened the completed card successfully. |
| Phone keyboard/rotation | Unsaved draft and keyboard remained usable through landscape/back; edit cancelled. |
| Phone network loss/reconnect | Owner disconnected/reconnected without saving/sending offline; guide still Done. |
| Session expiry | Real isolated browser rejected stale save, cleared private data and restored original saved state after fresh admission; database unchanged. |
| Conflicting edit | Real browser and HTTP checks preserve newer goal and retain the older draft for reconciliation. |
| Duplicate activation | Real desktop double-click saved one Done transition and sent no agent messages. |
| Uncertain delivery/restart | HTTP/store tests retain original send identity and refuse blind duplicate dispatch. |

This does not claim physical double-finger testing during a native agent run,
remote machine hardware qualification, native model lifecycle or whole-app owner
release acceptance. Those broader requirements retain their separate gates.


Manual replay: run `node test/serve-recovery-acceptance.mjs` from this checkout.
Use its printed loopback URL and Start local session; all three cards are
disposable synthetic data, with workers disconnected. Double-click the approved
card's Move to Done and verify one saved transition. For expiry, edit the pending
card without saving, create the empty file at the printed expireFlag path, then
save: access must be rejected and private data cleared. Start a fresh session
and verify the original goal. Ctrl+C stops only this disposable server; its
evidence remains in the printed unique data directory. This is a desktop replay,
not live phone or model-lifecycle acceptance.


Scoped-team Start/Resume checks unresolved worker receipts on other cards before
admitting the attempt. If it names another card, inspect that original worker
result there; pausing or closing a team does not cancel accepted work. An applied
worker result or existing native terminal outcome releases the same reservation
as the lower-level handoff guard. No receipt is removed and no worker is retried
by this check. The handoff-time guard remains active for later races.

## 2026-11-08 readiness update (supersedes older current-state summaries)

The parent Workroom card, Finish Onoes-Mesh - all assessed stages, now has progress
revision20. Its six original checklist entries and status remain unchanged:
A/B done, C/E/F working, D blocked on deferred shared-model maintenance. The
whole goal remains open with review pending. Refresh/reopen shows this summary;
it is not a scoped worker assignment and does not authorize automatic dispatch.

Latest tested candidate code is01f0ea1, pushed to the existing branch. Complete
local npm test265/265 (40+1+29+67+128), static/diffPASS; optional frozen contract
file absent/skipped. A later doc-only audit isd307ad8. These source results are
not live Rook acceptance or a measurement of the current deployed build identity.
The admitted live board policy still has managed flow off and14saved tasks.

Managed candidate paths have disposable SQLite/HTTP/browser evidence for claims,
original-send recovery, clarification, owner changes and accepted-result reload.
Managed workspace admission now requires verified terminal evidence from the
previous writer, even if its progress report was applied or its team closed.
The earlier paragraph allowing an applied report to release a writer describes
legacy unflagged behavior only; do not apply it to the managed candidate.

Rook remains separately built by Echo in an isolated4e321ea snapshot. Qualification
still needs its real identity/Relay health, durable Echo send-to-native-run
binding, tool/child completion guarantees, bounded same-chain retry, actual
report delivery, reviewed deployment and new owner-phone acceptance. Echo was
asked one read-only question through Relay; acceptance is not a reply or native
completion proof. See ROOK-MESH-INTEGRATION.md for the exact source audit.

Native model control/lifecycle remains unqualified and maintenance deferred.
Onoes-Mind has no verified canonical live store, keys or activated service here.
Shared context/skills/MCP, external apps and three-machine hardware integration
remain in scope and incomplete. Current source test totals do not close those
stages. Manual/milestone E backups continue; no scheduled/off-device protection
or automatic pruning is claimed.


## 2026-11-08 Relay receipt activation update

Live Relay now preserves exact send-to-native-run bindings and exposes the
owner-authenticated read-only receipt endpoint. Actual Node Mesh adapter/live
Relay/real Hermes acceptance passed with a completed no-tools Echo check and
stable pinned run readback. No automatic worker retry or writer release enabled.
Main Mesh runtime/managed mode unchanged; Rook remains unqualified and off.

Deployment caught an existing30-day accepted-outbox cleanup removing one old
receipt. It was recovered from the fresh backup by guarded insert only. Durable
outbox receipts now remain until deliberate cleanup; other retention unchanged.
Final pre-check data hashes prove all15sessions/210messages/43receipts preserved.
The intentional test then adds two messages and one native-bound receipt.
Manual verified E post-deployment backup contains15/212/44 and active source.
No credentials/native memory included, model service restarted or schedule enabled.
See ROOK-MESH-INTEGRATION.md and private checkpoint for exact evidence and limits.


## 2026-11-08 merged Rook foundation readiness

The private Mesh instance on8453 now runs tested coreccdfed0/buildc2b70d20799e
(started19:14:32Z). Complete local suite272/272/staticPASS; stronger recovery/writer
and large-document guards retained. All14saved cards/original user-data tables
preserved across restart. New durable sweep state is idle, not a running schedule.
Live admitted Rook status is not_configured/managedoff/schedulerfalse; claim-next
POST409 confirms no automatic intake. Parent progress22 retains sixoriginalstages
and the whole goal. Latest verified manual Ebackup includes that intentional update.

Rook runtime/identity/health/Relay reporting, affirmative child-writer completion,
full automatic workflow and owner activation acceptance remain unfinished. Mind,
model maintenance, external apps and other machine qualification remain separate
original requirements. Relay's live receipt observation is complete but never
substitutes for positive writer quiescence. No auto assignment or watcher enabled.


2026-11-08 Rook notices rollout: build0a0ab3234660 verified on private8453, 14cards/19 prior tables unchanged. Rook not_configured/managedoff. Verified pre/post E backups19-46-40-090_UTC_45dcd303 and19-47-12-720_UTC_0ba21e07. Later claim-handoff guards are candidate only; full288 localtestsPASS. No native model/Relay restart or watcheractivation.


2026-11-08: live07732e9cffb6 installs read-only Rook assignment holds and d02a178 handoff guards, all14cards/21tables preserved. Full290testsPASS. Managedflow/Rookscheduler remainoff; nativequiescence/identity/reporttransport notqualified. Parentprogress24 intentionallyupdates evidence.


2026-11-09: private Mesh restarted with tested e0892f9 safeguards. Named process
healthy, private Tailscale page HTTP200; all22 prior data tables and14 cards
unchanged, SQLite integrity ok. New empty local-session table is migration only.
No native route enrollment or Rook activation. See the integration checkpoint.


## 2026-11-09 — current native bridge maintenance proposal (not executed)

Verified candidate: integrations/native-live-policy-qualification.json records the actual unsubmitted Codex session's exact public file/terminal policy and zero admissions. Full application regression remains434 (337Node/97Python); the new operator checker was exercised on the real saved session, including reopen with matching request receipt. These facts do not qualify private credential absence or Codex generation.

Prepared seven-file bridge package: data/native-bridge-rollout-fb4d589d-0904-4282-bd67-5be857252ebe. Current candidate hashes, five rollback originals and installed before-hashes all rechecked PASS (../native-bridge-maintenance-precheck.json). No live file changed. Native CLI status independently recognizes Windows Scheduled Task Hermes_Gateway and runningPID9804. This gateway is shared by Echo, Relay and Telegram.

Maintenance scope, pending launcher/import-root verification and Eddie's permission:
1. Revalidate exact runtime owner, launch root and manifest baselines. Use the supported native gateway stop WITHOUT --yes/--interrupt/--all. Its current help says active turns/jobs/delegations require confirmation and noninteractive execution refuses; do not override that refusal.
2. Only after authoritative stop/quiescence confirmation, install the seven manifest-listed source files. Never replace source under a live owner. Preserve all settings, keys, sessions, conversations and task data.
3. Start through the existing registered launcher with hidden windows; verify one owner, health, exact installed hashes and original shared clients. On failure, stop safely, restore the five exact original sources and remove only the two introduced helpers if they still match this manifest. Never remove data or unrelated files.
4. Read back the original test session through the installed closed-profile bridge; require exact tools/model/workspace and key-presence=false before any separate generation qualification. Private references alone are not proof either way.

This proposal does not enroll Rook, grant a production worker principal, activate automatic work, change model credentials, restart the shared local-model service, or connect Mind. Those existing gates remain independent. No maintenance permission has yet been assumed.


## 2026-11-09 — reviewed native bridge maintenance ready, permission pending
- Previous goal turn classified progress: live public policy, commit0fe6f18 and verified backup. Outstanding index32209 finished0 after219s; VBS explicitly unsupported. Bounded reader23878 finished0 but file not indexed. No duplicate/restart on observation timeout. One soft progress warning logged to ~/.hermes/agent-lab/logs/smart-stop.jsonl after repeated no-output reads; CPU/process metadata proved work remained active until terminal.
- With muncher confirmed unable to handle VBS, read only selected non-secret runtime startup settings. Launcher is UTF16BOM (initial UTF8 decode failed before output; corrected encoding); same1870bytes/SHA485eb282c27762c1ec26f9079a00694db25bad255ab6ad99417cded2212525e4. It declares expected HERMES_HOME, prepended hermes-agent PYTHONPATH, current directory and exact3.14.9 Python, hidden sh.Run(...,0,False). Native CLI independently recognizes Hermes_Gateway/PID9804. No launcher modification.
- Added source-only native_bridge_maintenance.py with exact seven-file allowlist; only two known new helpers can be absent originals. All package/candidate/baseline/current hashes checked before mutation, candidate syntax parsed, stopped-runtime guard required before/every/after replacement. No service controls or credential handling. Rollback restores exact five originals/removes only exact-hash introduced helpers; unexpected edits/path escapes refuse before mutation. Partial failures require safe stopped-state reconciliation, never blind restart.
- Five meaningful focused tests PASS: busy runtime no mutation, full apply/exact rollback, tampered package no mutation, unexpected installed edits preserved, path escape refused. Real package dry-run PASS7; actual live guard correctly refuses native8642 listener. No live source was copied/deleted and no gateway stopped. Full434 remains prior unchanged-production baseline, not falsely counted as a new full run.
- Maintenance package before/candidate/rollback hashes rechecked PASS7. Readiness and existing RELEASE-OPERATIONS.md contain concrete scope. Asked Eddie once for brief shared Echo/Relay/Telegram gateway maintenance; model service/Mesh stay running, active work must not be interrupted, Rook/Mind/autowork remain off. Approval pending; no timeout can count as approval.
- Next dependent step only after approval: native guarded stop, prove stopped/no workers, apply exact source-only package, existing hidden launcher restart, health/hash/closed-policy readback. Production identity/enrollment, real Codex generation and Rook activation remain separate unqualified gates. Goal active/incomplete.


Maintenance follow-up: focused tests now7/7, adding safe recovery after runtime returns mid-copy and refusing to classify an original source as a removable helper. Full Python discovery PASS136 in11.208s (../native-bridge-python-regression.log), including existing native process/identity/retirement guards. This is the actual discovered Python count, not the previous narrower97-test command. Prior337 Node tests remain unchanged baseline; no new claim of whole production activation. No service or source installation performed; permission remains pending.

### Current build checklist — 2026-11-09
- [x] Phone board create/edit/drag/theme/reload and recovery checks accepted by Eddie.
- [x] Disposable native builder -> actual independent Nims review verified; Eddie acceptance remains a separate decision.
- [x] Live Codex public file/terminal policy verified on one unsubmitted session with zero admissions.
- [x] Bridge source package, rollback, registered hidden launcher and operator safeguards prepared/tested.
- [ ] Shared Echo/Relay/Telegram gateway maintenance permission, bridge installation and actual recovery verification.
- [ ] Key-free closed-policy readback, real Codex generation qualification and approved production worker binding.
- [ ] Rook own identity/report transport/single scheduler/deployed acceptance and separate activation.
- [ ] Mind canonical live ledger/keys/scope setup and reviewed connection; currently disconnected.
- [ ] Main-PC inference controls/health qualification, then laptop and future AI-box integration. Existing model service stays running.
- [ ] Whole-app release acceptance across local/phone workflows and external integrations; not complete.


## 2026-11-09 — live main-PC health verified; simultaneous refresh collection fixed
- Previous turn is progress (9b81541 installer/rollback,136 Python regressions, verified backups); native shared-gateway maintenance approval remains pending and untouched. Continued independent original-goal read-only main-PC health requirement.
- Persistent local index-client19451 amortized startup: after first cold query, later exact lookups completed in milliseconds. Traced server.mjs to actual live serve.mjs /inference/summary, OS CIM plus nvidia-smi and fixed supervisor GETs. Existing functionality found; no duplicate monitor added.
- Read engine lock/runtime notes before Qwen status calls. Notes say binaries unbuilt, but all three named binaries now exist at the declared UnbiasedStrata build/bin with valid PE headers and nonzero real sizes. Verified presence before existing observer requests; no binary launched, config changed or retired8094/8096 called. Authoritative notes left unchanged; binary presence alone is not runtime/control qualification.
- Live authenticated GET /inference/summary PASS: current CPU/RAM/whole-card GPU metrics, fresh fixed-model observation, honest zero GPU use, no model loaded reported. Existing main-PC supervisorPID7196/birth1793378692.992652, no llama-server processes before/after; read-only checks did not load/unload/restart anything. Gate key used only in memory for existing operator auth, not exported/copied into records. Raw hardware details stay in local ignored evidence; tracked report is minimal.
- Reproduced concurrent refresh bug: three GETs returned at least two distinct generated samples (timestamps may collide, so not claimed as exact collector count). Existing cache only saved completed data and did not share pending work. Added 16-line monotonic shared summary reader; one pending promise per collector, two-second cache from completion, failed/expired reads never masquerade as fresh. No control/auth/UI payload or model-state changes.
- Focused cache/GPU/supervisor13/13 testsPASS and serve.mjs syntaxPASS. Predeploy backup E:/App-Backups/ONOes-Mesh/2026-11-09_09-31-45-639_UTC_0cd598af verifiedtrue14tasks268sourcefiles/allrestorechecksPASS.
- Named Mesh-only restart40168->54404; shared Echo gateway/native sources/model service unchanged. Actual three concurrent GETs after restart returned one identical fresh sample; observed exactly one owned PowerShell hardware collector. All23 SQLite table rows fingerprint-identical to predeploy backup, integrity/FK pass,14cards preserved. Model supervisor/process identities unchanged. Evidence integrations/main-pc-health-qualification.json plus local before/after files; no model control requests.
- Main-PC health data collection is verified live. Phone appearance/interaction acceptance, model lifecycle control, laptop/AI-box integration, shared bridge/Rook/Mind activation remain unfinished. Goal active/incomplete; this does not redefine the full finish line.


## 2026-11-09 — health UI verified; selected workspace now survives reload
- Previous goal turn is progress (e0f53c0 live shared collector,13 tests, exact23-table preservation and E backup). Shared native gateway maintenance decision remains pending; no timeout/goal continuation taken as approval.
- Hidden IAB tab63 tested private8453. Inference390x844 and844x390, Control390x844: settled document and panel widths exactly match scroll widths (no horizontal overflow). Initial resize screenshot caught the rail animation; settled geometry/screenshot confirmed no persistent clipping. Browser simulation is not actual phone-owner acceptance.
- Live read-only refresh updates status without enabling unqualified controls. Locked only this test workspace, observed private model observations cleared and controls disabled; existing separately authorized PC hardware readings remain available. Reconnect restored the normal authorized view. Natural expired model observation visibly became unknown and cleared previous details, then fresh data returned. No tasks edited, agent sent, model action or shared-service maintenance performed.
- Verified actual navigation bug: choosing Control from Inference left #inference; hard reload selected Inference. Central activate() now mirrors one whitelisted workspace into history.replaceState, preserving existing URL query/browser state, avoiding a page navigation/hashchange loop. Existing link selection and keyboard focus retained; missing history API cannot block panel selection. No router/framework added.
- Navigation4PASS; Rook notice5PASS; required npm run test:workroom195PASS (actual command count, not earlier aggregated337 Node baseline). Extra legacy wf-draft-preservation suite6FAIL before execution because outdated VM setup cannot parse current imports. Reproduced identical failure on unchanged Git HEAD in isolated temp fixture; not caused by navigation change, not weakened or hidden. Repair that harness remains an explicit release backlog item. Initial restricted temp mkdir failed; approved isolated rerun completed and preserved baseline failure log.
- Actual browser after static asset reload: selecting Control sets #control; reloading stays Control. No Mesh process restart needed. Screenshot proof saved in visualization root; temporary390/844 overrides reset, own test tab63 closed, CUA completed once. Main-PC health report links new UI evidence, without claiming real-phone acceptance or model-control qualification.
- Goal active/incomplete. Next independent corrections: restore the old draft-test harness or continue local-app acceptance; shared native installation awaits actual maintenance answer. Rook/Mind/model-service gates unchanged.


## 2026-11-09 — legacy draft checks restored and normal test gate expanded
- Previous turn classified progress:46cf7ee fixed actual selected-view reload with responsive/reconnect UI proof and verified backup. Revalidated clean tracked tree;22 unrelated untracked integrations preserved. Gateway maintenance decision remains pending.
- Restored legacy draft VM fixture for app.js static imports and explicit unrelated Relay/Mind/Agent workspace adapters. Production code and every original assertion unchanged. An initial overbroad static-import regex also removed dynamic import and failed syntax; narrowed to import+horizontal-space declarations, retaining actual dynamic Workroom initializer. Intermediate failures preserved, no checks suppressed.
- Six original checks PASS: unsaved fields through running/terminal updates, latest-revision single Save, clean-field passive refresh, explicit reload/conflict behavior and privacy/session/task/run stale-response fences.
- Isolated negative control deliberately disables draft preservation in a temporary source copy. Repaired tests catch the actual Saved-vs-Unsaved mismatches (2 failures,4 fence checks still pass); live source unchanged. No mutation test file committed or executed against the running app.
- Added draft6/navigation4/summary-cache5 to test:workspaces, included by standard npm test. Full npm test terminal0 PASS: Node40+1+29+87+195=352; Python97; total449 plus static/design guard. Earlier Python136 remains historical unchanged-code evidence, not counted again. Metadata extraction initially tripped on log glyph encoding; ASCII failure-count parsing fixed reporting, not test results.
- Qualification record saved; navigation record preserves historical6 failures and now marks current6/6 repair resolved. No app code deployment, live restart/model request/worker dispatch/credential change/Rook/Mind activation.
- Legacy test-harness backlog item resolved. Next useful independent work: update the in-app goal checklist via normal authorized app access; disk checkpoint is current, earlier operator API session was unadmitted. Preserve original stages/unfinished states. Shared bridge installation awaits actual maintenance answer; original whole goal active/incomplete.


## 2026-11-09 — running checklist synchronized inside Workroom
- Used the normal authorized Tailscale Workroom UI, not a direct database write or bypass of the earlier unadmitted operator API. Existing parent card c2a77ea9-05bb-4b63-85c7-c2d8e9fb2547 / Finish Onoes-Mesh — all assessed stages now has current Result and verification evidence through code milestoneb3ba728 and449 local checks.
- Prior result/evidence archived verbatim in ../goal-progress-before-sync-20261109.json; verified pre-edit E backup10-13-40-978_UTC_482a4190 also preserves original progress52. Edited only Result summary/evidence; all six original stage names/statuses retained: done,done,working,blocked,working,working. Original goal/criteria/lead/lane/identity preserved, parent notDone, reviewpending; no review recorded and no agent action sent.
- Normal Save displayed Goal and checklist saved. Hard reload/reopen shows new449-check result and exact2/6 state. Read-only SQLite cross-check: taskrevision1 unchanged, progressrevision53, all other13 card rows unchanged, integrityok; only workroom_progress and workroom_events differ from pre-edit backup. Thus no dispatch/claim/model tables changed.
- Hidden own IABtab64 closed and CUA completion sent once. One heading locator missed because case/accessibility text differed; fresh AX index used to blur input/show Save, no duplicate save/retry. Screenshot saved in visualization root. Details retain all55 historical timeline entries; UI history disclosure only collapsed in temporary test tab.
- App checklist now current; disk checkpoint remains full evidence/lessons record. Shared Echo gateway maintenance question stillpending; model restart stilldeclined, Rook/Mind/autowork remainoff, live Codex generation/productionbinding/laptop/AIbox/finalacceptance incomplete. Goal active; original scope unchanged.

## 2026-11-10: production worker connection audit

The dedicated native adapter is implemented, but `server.mjs` currently creates
its team runner without `nativeWorker` or `nativeObserver`. That source path uses
Relay handoffs. The standalone real-provider startup success does not qualify
this full production team route. Nims already has the existing `nims` identity;
Agent workspace connection status is a separate observation.

Focused assignment, receipt, retirement and Nims recovery checks passed 35/35
using local synthetic fixtures and guarded HTTP routes. No real task was sent.
The current adapter creates sessions with a 50-turn limit; the earlier real
file-only diagnostic used four turns. These are different qualification scopes.

Evidence and ordered remaining work:
`integrations/native-production-binding-readiness.json`. Next implement the
explicit, disabled-by-default binding and qualify its exact profile before
requesting any further live task. Rook and Mind remain off.


## 2026-11-10: approved guide team trial held; enrollment prerequisite identified

- Eddie approved one builder and one read-only reviewer, no retries. Actual builder ran once; review was never sent. Original guide bytes preserved, but exact append missed one LF (6159 versus6160bytes). Failed copy remains untouched.
- Native turn completed without whole-worker process tracking; writer quiescence is UNPROVEN. No manual release, retry, Done, or production enrollment. Trial IDs and hashes: integrations/guide-team-live-qualification.json.
- Source confirms process scope requires owner environment MESH_LOCAL_PROCESS_SCOPE=1. Echo's fresh Relay answer (MESH_SCOPE_COORD_20261110) confirms shared launcher does not explicitly set it; inherited runtime value unknown. No retroactive scope recovery. Recommendation: separately reviewed dedicated Mesh owner/profile, isolated home/data/loopback port. Shared services unchanged.
- Added strict process-capability preflight for automatic Codex teams. Missing, false and string values prevent prompt submission. Prepared two-file native capability patch in a disposable copy only; NOT installed or enabled. Four offline behavior checks cover authorization, platform, flag and no invented scope.
- Future pilot now explains exact escaped newlines, limits builder checks to available file tools and retains independent host/reviewer SHA/directory checks. HTTP admission lasts ten minutes beyond the eight-minute trial limit; expiry reports its actual status. Existing failed intent cannot be reused after source changes.
- Focused pilot checks5/5 pass. Full-suite final result recorded separately below. No live app, Rook, Mind, model service, credentials or shared gateway changes.
- Lesson: a completed agent turn is not writer retirement; capability must be proven before dispatch. Synthetic end-to-end success is not deployed acceptance.

- Final local npm test: exit0. Full Node and Python suites passed; test log data/guide-pilot-corrections-full-tests.log. Restricted first run could not bind test servers; rerun with required local access passed.
- Held-trial backup: SQLite snapshot preserved separately. Automatic restore rehearsal changed durable provenance and therefore FAILED verification; it is not a verified restore. Original evidence and snapshot retained without modifying live data.


## 2026-11-10: supported worker maintenance prepared
- Previous goal turn was progress: strict team preflight, actual failed-trial evidence,474checks and verified main backup. This slice found a material correction to the proposed isolated gateway: installed host_rendezvous.py enforces one gateway owner per Windows user, multiplexing profiles. A separate home/port does not qualify a second owner. Preserve native locks, existing identities and credentials; do not evade using a lock-directory/user/role override.
- Added --require-process-scope to the existing frozen unsubmitted-probe verifier. Authenticates only after loopback discovery, uses only prompt.lookup and exports allowlisted profile fields. Literal true confirms capability only; never claims worker retirement/enrollment. Actual installed read-only check exit2 HELD, zero probe admissions and zero new prompts, exact closed model/workspace/tools/max50 profile valid. Saved data/native-worker-readiness.json.
- Prepared exact three-file maintenance package with candidate/rollback bytes and original hashes: native session_controls.py, canonical.py and existing Hermes_Gateway.vbs process flag. Initial launcher parse correctly refused UTF16; fixed explicit BOM-preserving decoding/encoding, with unchanged hidden launch arguments. Prepared data/native-worker-maintenance-prepared.json. No installed changes, new credentials, gateway/model restart, Rook or Mind activation.
- Existing owner receives a shared process environment setting; this is shared gateway maintenance, not isolated deployment. Requires explicit maintenance approval and confirmed absence of active work before installation/restart. No new model trial included; original held trial remains held.
- integrations/NATIVE-WORKER-MAINTENANCE.md contains exact change scope, rollback and read-only acceptance. integrations/native-worker-maintenance-qualification.json records real probe plus source hashes and prepared artifact.
- One restricted Python fixture run stalled during async-test startup; confirmed its exact PID40524/command and stopped ONLY that test. Parent preparation finished successfully. Elevated full gate pending. No service process was touched.

- Final npm test exit0:369Node +114Python =483checks. Original two installed-profile tests retained verbatim in their original file; seven new readiness/launcher tests are separate. All test/owned helper processes terminal; code index final two-file refresh pending. No new provider task.
- Installed source and launcher hashes rechecked: all three still match their originals. Prepared candidate is not installed. Next: explicit shared gateway maintenance decision; full goal remains active/incomplete.


## 2026-11-10: unfinished-team restore verification corrected
- Previous goal turn was progress: prepared supported single-owner gateway maintenance,483checks, committed/pushed476de60, verified source/data and rollback backups. Gateway decision was pending; Eddie now explicitly approved maintenance WHEN IDLE. This authorizes the prepared three-file update and shared gateway restart only after authoritative live no-active-job confirmation. No model-service restart/new provider trial authorized.
- Compared failed preserved rehearsal with snapshot: only workroom_automation reason/revision/state changed. Original active revision2 becomes paused revision3 with exact standard restart reason; card/review data unchanged. This is intentional no-replay recovery, not data loss. Original FAILED receipt/evidence retained.
- New lib/workroom-backup.mjs checks every saved user table, rather than only the previous12-table durable hash list plus row counts. Permits only exact active->paused reason/+1revision and prepared->unknown send state, with all other fields/IDs/payloads/holds unchanged. Requires safety recovery to actually occur; unchanged active/prepared states fail. No production recovery behavior changed.
- Actual original held trial restored successfully in a NEW isolated directory, integrity/FK PASS, one saved task, strict all-table fidelity PASS. Original native worker quiescence remains UNPROVEN and no retry/review/release/Done was performed. Tests reject invented quiescence, changed task/assignment/scope/review/revision, missing safety pause or tables/rows. Focused3PASS; full gate running.
- First restricted E backup reads failed; same read-only comparison succeeded with approved library access, no private message contents printed. No service process touched.

- Full npm test exit0:372Node+114Python=486checks. Actual held-trial isolated restore compares all23tables, permits exactly one safe team pause, no uncertain sends; no private/live store was changed.
- Approved maintenance live preflight: authenticated native control identify/status both answered; ownerPID6080/instance1236809ce08a4c10852afd23b8bbc4a6 ready, active_agents=1. Idle condition NOT met. No installation/restart. Live source data/gateway-live-activity.json. Wait for authoritative zero-active-work response, not a stale status file.
