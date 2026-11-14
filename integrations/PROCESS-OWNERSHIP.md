# Named Mesh process ownership

Manage this checkout's private Workroom preview from its root:

```powershell
powershell -NoProfile -File integrations/restart-workroom-preview.ps1 -Action Status
powershell -NoProfile -File integrations/restart-workroom-preview.ps1 -Action Start
powershell -NoProfile -File integrations/restart-workroom-preview.ps1 -Action Restart
powershell -NoProfile -File integrations/restart-workroom-preview.ps1 -Action Stop
```

Status is read-only and reports the app name, PID, local health, URL and receipt location. Start refuses to replace an already-running owned process. Restart remains the default for compatibility with existing deployment commands. Stop/Restart require matching executable, full-precision start time, recorded command line and named checkout ownership. An occupied unowned port is never cleared. Keep using the named launcher; do not kill Python/Node processes by runtime name or age.

The receipt is ../workroom-ab-preview-process.json (onoes-owned-process/v1). It identifies ONOe's Mesh - Workroom, exact checkout and entry point, command line, process identity, port4320 and private8453 URL. Launch uses an absolute entry-point path. Standard output/error remain ../workroom-ab-preview.out.log and ../workroom-ab-preview.err.log. No keys or tokens are stored in the ownership receipt.

The named ONOes Mesh Workroom Recovery scheduled task now runs Ensure every minute and at this user's logon, with a limited interactive-user principal and no password. It starts only a missing owned Mesh preview; it never kills a running or unowned listener. It does not supervise Relay, DSH or TTS, restart a hung-but-running process, run before user logon, or explain an unlogged exit. Task Manager/direct Stop-Process can still bypass the launcher. It does not manage TTS, original Mesh8446, DSH, Relay or other apps. Reuse the pattern deliberately per app with separate names/receipts, commands, ports and health checks. Do not adopt a running process merely because it uses Python or Node. A missing/stale/ambiguous record is a reason to investigate, never permission to kill a listener.


Recovery installation is reproducible with `powershell -NoProfile -File integrations/install-workroom-recovery.ps1`. An existing task with a different action is refused. The exported task definition is data/workroom-preview/recovery-task.xml. Inspect it with Get-ScheduledTask / Get-ScheduledTaskInfo -TaskName 'ONOes Mesh Workroom Recovery'. Named Stop writes data/workroom-preview/recovery-paused and prevents automatic restart; successful named Start or Restart removes that marker. Ensure leaves a healthy running instance alone. A per-checkout mutex serializes launcher operations. Do not use broad process cleanup for a recovery test.

The private Tailscale browser now establishes its guarded app session automatically. Lock workspace deliberately clears private UI/proof and retains only a same-tab lock preference across refresh; Reconnect workspace explicitly opens it again. It is a tab privacy control, not revocation of the device's Tailscale access. Local/manual fixtures still require manual admission. Automatic recovery never retries a save, worker send, approval decision or other mutation.


### Relay launch-input custody implementation — 2026-11-14

Previous goal turn was PROGRESS: source/row-bound retained-record review checks
passed 598 tests and the actual unapproved draft was rejected. This turn closes
a real launcher evidence gap without adopting or restarting the running service.

The named launcher now records source/config/interpreter input hashes around a
future start, exact CIM creation/command identities for its retained process and
listener, and stable-before/after evidence. A separate helper validates receipts
without process discovery or lifecycle actions. Status reports changed inputs,
missing/legacy receipts, reused identities, unrelated listener ancestry, unstable
capture and internally corrupted receipt evidence as unverified. Matching means
observed launch inputs match; LoadedBytesAttested and CanRelease stay false.
Existing healthy processes remain untouched and their missing startup evidence
is never backfilled. Unexpected config/store selectors and adapter-skipping
environment prevent a new managed start. No stop action was introduced.

Evidence contains 22 input hashes, two backend names and hashed route URLs;
configuration secrets and environment values are omitted. Recovery plans now
also freeze the managed launcher, helper and opaque Relay config hash. Backups
include the new helper. No config/key value is committed or exported in status.

Tests: ten synthetic custody cases plus privacy, source/environment drift and
selector checks pass. An isolated real Python HTTP process exercised a copy of
the full launcher algorithm, with ONLY root/interpreter/port/mutex constants
changed. It captured its real retained process, left it unchanged on a second
Start, and flagged source drift without restarting it. Only that exact retained
test process was killed/waited; live services were untouched. This is an algorithm
fixture, not a production Relay start or backend/agent qualification.
The internally altered-receipt test failed before the digest-consistency fix and
passes afterward. Windows PowerShell lacked Get-FileHash in this inherited module
environment; the helper uses ordinary .NET SHA256 with no policy changes.

Full current npm test passes 600 checks (479 Node +121 Python), exit0. The new
two-case test file is registered in test:workroom; the prior 599 run predates the
real launcher case and is preserved separately. Exact proof:
data/relay-runtime-binding-full-test-proof.json; launch tests:
data/relay-runtime-binding-launch-tests.log.

Live read-only status: Relay healthy, same retained launcher23548/listener57024,
legacy receipt unverified. Current source/config observation is not a historical
launch receipt. Actual login starts via Onoes Relay.lnk ->
D:/Dev/Onoes-Relay/tools/start-relay.cmd, NOT this managed wrapper. That cmd file
starts the same server with relative arguments and rotates one old log; it was
read but never executed/changed. The indexer cannot handle .cmd, so the single
1282-byte known file was read directly after that explicit format rejection.
The exact shortcut is in data/relay-restart-owner-inventory.json. The only matching
scheduled task found is Onoes-Relay Backup; it is not a process restart owner and
was left unchanged. This targeted inventory is not proof that no other owner
exists. No startup shortcut or task was modified.

NEXT containment proposal: keep Relay stopped alongside Echo/DSH while applying
administrative recovery, rather than requiring live loaded-byte attestation.
Before enabling any retained-record exception, the candidate must cover Relay's
third login shortcut and both 8787 loopback sockets in addition to the existing
workers, and pin the actual login launcher/config. Verify other relevant restart
owners explicitly. That offline layout/retained enrollment is NOT implemented
or approved by this milestone. A fresh managed production capture and normal
login acceptance are NOT RUN. Do not claim the legacy live receipt is upgraded,
or that the default logon shortcut now uses the managed wrapper.

The owner cross-app/other-PC writer-scope fact and exact publication through149ac87
remain pending. No real record was excluded/retried/retired, no model was loaded,
no paid agent task was sent, no service restart/boot was scheduled. Goal remains
ACTIVE18/21/parent84; production workers, Rook and live Mind remain off.


## Current maintenance ownership — 2026-11-14 UTC

Fresh read-only status reports Mesh healthy. Its recovery task runs every minute;
the DSH watchdog repeats every five minutes. The candidate now checks all five
known scheduled owners, including the model supervisor and the already-disabled
Hermes guardian, plus the three login links. After Eddie separately approved
startup preparation, the four enabled tasks were disabled and the three links
were parked; the guardian remains disabled. Running Mesh is healthy on the same
owned process. No app/service/model stop or reboot was performed. Automatic login
and recovery starts remain suspended until deliberate restoration.

The inventory, original-state table, unresolved broker ownership and proposed
stop/restore sequence have one canonical home:
[LEGACY-WORKER-RECOVERY-PLAN.md](LEGACY-WORKER-RECOVERY-PLAN.md).
Codex infrastructure and the stopped/disabled legacy HermesAgent service remain
untouched. An observed PID or name is not lifecycle authority. The real compiled
broker refusal test and full620-code gate do not authorize service control.
