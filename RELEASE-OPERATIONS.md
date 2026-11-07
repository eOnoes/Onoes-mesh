# Mesh private release candidate

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
backups; this command only backs up Mesh. Scheduling and off-device protection
remain deferred. Credentials, external Relay configuration and models are excluded.

## Qualification and remaining gates

This is a private release candidate, not a whole-app production acceptance claim.
The real worker → review → correction → review flow, permission denial/recovery,
local database/source restore and named process recovery have recorded evidence
in WORKROOM-AB-CHECKPOINT.md. Agent lists and delivery receipts are not proof of
coding tools, repository access or completion. Agent workspace opens those same
saved Workroom cards; it introduces no scheduler or automatic dispatch.

Physical-phone end-to-end acceptance remains required. Inference lifecycle
qualification is separate: the approved UnbiasedStrata binaries now exist, but
existence alone does not qualify ownership or lifecycle. Do not substitute a retired engine. The qualified
Mesh-only team lane uses locked scope, Echo building and DeepSeek/Nims review,
then pauses for owner review. Mind deliberately retrieves selected saved Workroom
records under [MIND-CONTRACT.md](MIND-CONTRACT.md); it adds no personal memory
store or automatic writes. Additional workspaces/runtime profiles and
push/Telegram synchronization remain unqualified/deferred. Review this record
when the runtime lock or owner acceptance changes.

Ordinary Relay acceptance and compatibility decisions are recorded in RELAY-INTEGRATION.md. The new conversation surface exposes one explicit selector and one ordinary submit path; legacy snapshot-era header/session choices are bypassed. Actual private history/lock/reconnect acceptance sent no real message. Phone hold/drag and typing/focus are owner-confirmed; physical background/resume recovery is a distinct remaining check.

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

Still required before enabling Mesh controls: durable Mesh operation receipts and
protocol adapter/UI integration, revalidate and review the live candidate source,
coordinate the supervisor cutover, then prove real Nemotron load/unload, chat
cancellation, lost response and restart recovery. The current resident model is
untouched. Prepared code and passing fixtures do not enable native controls.
Generated Python bytecode is excluded from source backups/release hashes; the
Python source itself remains included and versioned.
