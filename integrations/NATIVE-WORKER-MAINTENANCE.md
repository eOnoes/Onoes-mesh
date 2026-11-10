# Mesh native worker maintenance

Status: prepared only. No installation, gateway restart, new agent task, Rook
activation or Mind access is authorized by this document.

## Supported owner arrangement

Installed Hermes `gateway/host_rendezvous.py` defines one gateway owner per Windows
user, multiplexing profiles. A separate HERMES_HOME and port do not establish an
independent supported gateway owner. Preserve the existing host-role lock and
normal discovery. Do not change HERMES_GATEWAY_LOCK_DIR, XDG_STATE_HOME, Windows
user, host role, credentials or gateway identity to evade that boundary.

The earlier suggestion to start a second dedicated gateway under the same account
is superseded. Use closed Mesh assignment policies through the existing owner;
keep the existing Echo builder and `nims` reviewer identities. This does not enroll
Rook or turn on normal Mesh automatic dispatch.

## Prepared changes

Run `python integrations/prepare-native-worker-maintenance.py` to prepare private
candidate and rollback files under a new `data/native-worker-maintenance-*` folder.
It changes no installed file, starts no process and reads no credentials or chats.
The exact current package is identified in
`data/native-worker-maintenance-prepared.json`.

Only three installed files are proposed:

1. `hermes-agent/gateway/session_controls.py`: expose a strict boolean process
   capability in authenticated lookup replies. It does not create tracking for
   old admissions or waive retirement evidence.
2. `hermes-agent/tui_gateway/contracts/canonical.py`: accept that optional boolean.
3. `gateway-service/Hermes_Gateway.vbs`: add process environment
   `MESH_LOCAL_PROCESS_SCOPE=1` immediately after the existing WScript.Shell
   assignment. Preserve the original encoding, every original byte, launch
   command and hidden-window arguments.

The setting belongs to the shared owner, not an individual request. Its impact
must be reviewed as shared maintenance; do not call it isolated deployment.
The source files are hash-pinned. Any drift or existing launcher setting stops
preparation. The package includes original bytes for rollback.

## Installation and rollback boundary

Before installation, obtain Eddie's explicit approval for these three files and
a brief shared Hermes gateway restart. Relay/Telegram agent responses may pause;
this does not restart the separate local-model service. Do not interrupt active
work. Identify the actual launcher/task and check active work using supported
owner controls. Unknown activity blocks maintenance; do not infer inactivity from
an old status file or kill matching Python processes.

After approval and a confirmed maintenance window, recheck all original hashes,
preserve the exact original files, install only the reviewed three candidates,
and restart only the named Hermes gateway using its established service controls.
Do not remove shared locks or substitute a second owner. If owner health or the
read-only check fails, stop new dispatch and restore the exact three originals
through the same approved maintenance process. Keep failure evidence. No automatic
provider retry is part of rollback.

## Read-only acceptance before another task

Use the installed Hermes Python to run:

```text
integrations/verify-native-installed-profile.py --require-process-scope
```

This accepts only the existing frozen, never-submitted probe. It validates native
receipt identity, exact closed Codex model/workspace/tools/50-turn contract, and
zero probe admissions. Discovery must be loopback before ticket authentication.
It sends only prompt.lookup; it creates no session and sends no prompt. Missing,
false or non-boolean process capability yields HELD and exit2. Only the public
allowlisted contract is saved to `data/native-worker-readiness.json`.

Even CAPABILITY_CONFIRMED is not worker retirement or full-team acceptance.
Existing failed trial IDs stay held: no retroactive scope, manual release,
replacement admission, review or repair of the failed copy.

Only after owner health and read-only readiness pass should a new disposable
one-build/one-review trial be proposed for separate approval. Verify actual process
retirement, exact artifact, independent review and saved card state before any
production worker enrollment or Rook activation.


### Current approved maintenance observation (2026-11-10)

Eddie approved the prepared three-file maintenance **when idle**. That approval
remains valid; it does not authorize interrupting active work. Nothing is installed.
The fresh same-owner `active-work` control response reports one active chat item.
Wait for that work to finish; do not force it or start a second gateway.

`query_gateway_control(home, "status")` answers live but reads saved status data.
Its fresh answer timestamp does not make its activity counter a live aggregate.
The `/health` response exposes only status/platform/version. Neither proves idle.
Use the supported `active-work` verb and bind its PID to the same `identify` owner;
unavailable/malformed replies remain unknown. Echo also reports incomplete child
process coverage and counter-error gaps, so a zero response alone is not a complete
all-writers-ended proof. Before any maintenance, resolve those remaining checks
and confirm the restart method will not force timed-out work. The standard
`pause-for-update` request is not an indefinite wait-or-refuse guarantee. No drain,
shutdown or restart was requested during this observation.
