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
qualification is separate: the authoritative UnbiasedStrata lock currently says
its Windows binary is not built. Do not substitute a retired engine. The qualified
Mesh-only team lane uses locked scope, Echo building and DeepSeek/Nims review,
then pauses for owner review. Mind deliberately retrieves selected saved Workroom
records under [MIND-CONTRACT.md](MIND-CONTRACT.md); it adds no personal memory
store or automatic writes. Additional workspaces/runtime profiles and
push/Telegram synchronization remain unqualified/deferred. Review this record
when the runtime lock or owner acceptance changes.

Ordinary Relay acceptance and compatibility decisions are recorded in RELAY-INTEGRATION.md. The new conversation surface exposes one explicit selector and one ordinary submit path; legacy snapshot-era header/session choices are bypassed. Actual private history/lock/reconnect acceptance sent no real message. Phone hold/drag and typing/focus are owner-confirmed; physical background/resume recovery is a distinct remaining check.
