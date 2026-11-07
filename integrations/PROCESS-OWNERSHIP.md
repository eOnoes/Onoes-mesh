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
