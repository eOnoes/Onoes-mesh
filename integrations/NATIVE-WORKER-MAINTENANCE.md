# Mesh native worker maintenance

Status: installed under Eddie's explicit idle-only maintenance approval. The new
gateway is ready and the never-submitted read-only probe confirms process tracking.
No new agent trial, production worker enrollment, Rook or Mind activation occurred.

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


### Pre-maintenance observation (historical, 2026-11-10)

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


### Completed maintenance and next qualification

A later genuine idle window was confirmed by repeated same-owner active-work reads:
zero agents and zero work items immediately before the native pause request. The
original process exited after accepting pause-for-update; no operator force-kill
was issued. Exactly the three reviewed candidates were installed, then the existing
hidden Hermes_Gateway launcher was started once. The new owner PID47220, instance
7e25cbc75c434c0ca73bc88b9be400a5, initially reported starting and later ready. The
readiness timeout did not cause another launch or replacement process.

The existing never-submitted probe returned process_scope_supported=true, the
exact closed Codex contract and zero admissions. All nine native implementation
hashes match the original reviewed bridge plus the two approved capability changes.
The separate model supervisor answers health (idle, loaded=false, servable=true);
no model service restart/load/unload was requested, and pre-maintenance residency
was not recorded. Normal Mesh production binding remains off.

The earlier busy-gateway external-drain command was rejected before execution. It
never created a live marker. Its unused offline prototype and five simulated tests
are archived under data/native-drain-offline-candidate-20261110, outside normal app
operation. The authorized idle-only maintenance was used instead.

A new guide-copy trial is prepared with the deployed nine-file baseline and stricter
exact-append instructions. Preparation sent no model request. It needs separate
approval for one new builder and one independent reviewer, with no retries. The
previous failed trial remains held; this maintenance does not prove its writer
retirement or approve any card.
