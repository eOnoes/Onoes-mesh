# Onoes / DeepSeek Harness web login startup

Installed at Eddie's request on 2026-11-13. The per-user Windows Startup shortcut
is **Onoes DeepSeek Harness Web**. Its stable installed files live under
`%LOCALAPPDATA%\Onoes\Launchers\DSH-Web`, independent of this checkout.

The shortcut runs `wscript.exe` with `start-hidden.vbs`, which runs the local
PowerShell launcher hidden. No execution-policy override, administrator grant,
credential, recurring watcher or Windows automatic-login setting is added.
The existing separate DSH A2A/Relay bridge startup entry is preserved.

At sign-in the launcher checks loopback `127.0.0.1:3081`. If occupied, it exits
without starting or stopping a server. Otherwise it starts the verified existing
Node/DSH installation with `web --host 127.0.0.1 --port 3081 --no-open`. A local
mutex suppresses simultaneous startup attempts while readiness is checked.
DSH authentication and the existing private Tailscale mapping are unchanged.
DSH output/authentication URLs are not copied into a launcher log.

`last-start.json` in the installed folder records the latest check. Missing
runtime files or a failed launch produce `launch-failed`; a slow start can be recorded as
`started-listener-not-yet-ready`. This is one startup attempt, not a watchdog or
an automatic retry loop. An occupied port is not proof of a healthy DSH server.
The process receipt is operational metadata, not authority to terminate a PID.

Actual Windows PowerShell 5.1 smoke verification covered parsing, preservation
of the current DSH listener, a new hidden disposable server, real HTTP readback,
duplicate suppression, cleanup using only the retained owned fixture process,
and unchanged protected DSH process start time. The installed Startup shortcut
was then invoked and produced a fresh `port-already-listening` receipt. The
November 22 readback found the shortcut still present after a later boot, but
both launcher files were missing. The private route returned HTTP 502. Restoring
the two files from the installed Mesh copy and matching their hashes to the
original installation receipt brought the listener back. A second invocation of
the actual shortcut kept the same process. The private route then returned the
expected DSH authentication challenge. Automatic startup at a subsequent
sign-in still needs direct observation.

If the private route returns 502, check for `start-hidden.vbs` and
`start-dsh-web.ps1` in the shortcut's working directory. Match both against the original
installation receipt before restoring a missing copy. Run the existing shortcut
once and check `last-start.json` for `listener-ready` or `port-already-listening`.
Verify the listener belongs to DSH and accepts connections on loopback. An
unauthenticated request to the private route should receive the DSH sign-in
challenge.

To disable: turn off **Onoes DeepSeek Harness Web** in Windows Startup apps, or
remove only its named shortcut from the current user's Startup folder. This
does not stop the running DSH process. Preserve the separate DSH A2A shortcut.

For a future separately approved recovery window, include this explicit new
startup owner in the startup/pause/restoration inventory. It does not change the
eight historical Workroom holds or approve production workers, Rook or Mind.
