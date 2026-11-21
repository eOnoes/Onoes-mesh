# Remaining owner checks

## November 21 source qualification

The remote telemetry candidate uses the existing private laptop identity and
strict SSH host-key verification. The approved deployment profile would need
to opt in with `MESH_TRIPP_HARDWARE=1`. An explicit machine-status refresh can
then collect RAM, CPU, GPU and available temperature readings for Tripp's PC.
Model residency requires a separately verified laptop source. A cached online
flag alone cannot establish that a model is loaded.

The SSH collector has been exercised locally on Windows. End-to-end qualification
on Tripp still requires that laptop to be online. Eddie's accepted main-PC phone
checks are retained. The first MCP reader and composed Workroom update trial use
disposable projects. Live channel/tool enrollment is pending.

## Current Workroom - 2026-11-18

Open [Workroom](https://emitchell.tail8c4a75.ts.net:8453/#workroom) or
[Inference](https://emitchell.tail8c4a75.ts.net:8453/#inference).
The current release checklist is in [RELEASE-OPERATIONS.md](RELEASE-OPERATIONS.md).
The older 8446 installation described below is separate; its checks do not apply
automatically to the current Workroom.

Already confirmed by Eddie: card creation, editing, touch-drag, saved review/Done,
reload, both themes, background/resume, rotation with an unsaved draft, network
reconnection, starting a scoped team from the phone, and main-PC Nemotron
load/chat/unload ending STOPPED. Do not repeat these simply because work resumed.

Also accepted by Eddie: [Relay](https://emitchell.tail8c4a75.ts.net:8453/#relay)
shows his messages separately from Echo's replies, and older history loads without
replacing messages or losing the reading position. The Workroom and Mind screens
also passed the post-cutover phone smoke check. Preserve these accepted results;
no repeat phone test is requested here.

The next production phone check is a complete production team workflow after the
legacy recovery and production enrollment have been qualified. That prerequisite
is not ready: automatic assignment and Rook remain off, and the eight historical
job holds have not been cleared. The approved shared-facts Mind reader and limited
Workroom project-sync connection have been activated and phone-verified; this is not broad shared-chat or
agent-private memory access. No phone test, restart or service change is requested
by this document. When ready, Nims will
provide the exact link, card name, short steps and expected result together.

Remaining first-release gates: C1 production workflow without operator rescue;
C4 deployed release/custody and owner acceptance; E2 qualified production team.
Other machines and broader shared conversation context, skills and MCP tools remain later stages of the full goal.

The tested November 18 Help and board-reconnect source candidates are not yet
installed into the live runtime. The standalone backup-source confinement fix
is installed and its real milestone backup passed restore checks without a
service restart. Keep those deployment states separate.

## Historical 8446 checks - retained for that separate installation

The following source revisions, requests and pending states are historical.
They are not the current Workroom checklist or permission to run a command.

Current source HEAD: `d077f2d83ed9607f21139aa71a86743918a50f74`; accepted recovery merge `64a1d257f638cc390ad0ba2a152849d15bbca6ba`. Private URL: **https://emitchell.tail8c4a75.ts.net:8446/**. Exact mapping: [HOST-CLOSURE.md](HOST-CLOSURE.md). These are deferred checks, not instructions to restart now or execute Eddie's current pending proposal.

## Confirmed; do not repeat the checklist

[Owner feedback, 2026-10-04](.runner/owner-feedback/phone-flow-confirmed-20261004.md) confirms physical phone access/navigation, saved Test for Echo opening and reported Save/Approve/Deny/Cancel traversal. Read-only parent evidence records revision22 and actual cancellation: cancelled=true/cleanupVerified=true, rootExit1/statefailed. Task done does not mean command success. A **separate newer pending proposal** stays unapproved. Every click/denial is not durably reconstructed. Older literal `ownerAcceptance: pending` fields remain historical, qualified by this narrower confirmation.

## Laptop — PENDING OWNER HOME WINDOW

Echo owns the home reminder; no reminder/account/email action is created here. No repeated SSH/ping while parked and no assumption that offline means broken.

| Gate | Check when home | Retain as passing evidence |
| --- | --- | --- |
| M1 laptop-origin shell | Laptop on existing tailnet: `curl.exe --fail https://emitchell.tail8c4a75.ts.net:8446/`. No route/enrollment changes. | Device, command/exit, time and returned Onoes-Mesh shell. PC HTTP200 does not substitute. |
| M5 physical Wi-Fi | Phone → Inference → Refresh nodes with laptop Wi-Fi on until available cached Online=true/ready and last-success timestamp. Owner turns Wi-Fi off, refreshes and watches aging. | Actual flag/timestamps, ready→stale→offline. Cached Online can lag Wi-Fi; ready ages at30s, offline at60s from last success without another success. cli_timeout/access_denied is unavailable, not proved offline. No packet/model readiness claim. |

Single M1 review is paused until laptop-origin success ([ledger](.runner/manager-handled.json), `m1-persist.next`), not completed or an independent ready lane.

## Separate owner windows, unrelated to laptop

Arrange narrowly through Echo; do not repeat confirmed basic phone flow.

| Gate | Owner action / scope | Passing observation |
| --- | --- | --- |
| Physical same-cookie background/resume | Open existing task, background/suspend phone page, return before old five-minute session expires, deliberately recover/Start if locked. Read only, no run/message. | Locked content clears; deliberate recovery promptly restores same task/current revision. Record device/browser/event/time. Parent trusted-browser evidence does not establish the physical phone event. |
| M1 owner-PC persistence | Echo coordinates preserving-store PC restart/phone refresh with separately agreed task. Owner data is never a crash fixture. | Same saved task survives. Parent native/UI evidence already passes; physical check remains. |
| M3 owner-PC interrupted run | Separately scope original PC kill/restart + phone read with fresh disposable store/task and exact owned server under Echo supervision. | Failed/UNKNOWN, never false completed, same store/URL, no automatic replay. This document authorizes no protected-deployment kill. |
| Remaining M2 output/denial evidence | If full M2 acceptance is needed, Echo agrees only missing version-output/denial-no-execution check on a new disposable task. Leave current pending proposal untouched. | Actual `node --version` stdout/exit and denial with zero executions; traversal alone does not prove both. |
| M4 physical Relay | Separately agreed test context: send one message, open canonical Mesh task, reconnect. | Same task/reference, no duplicate or execution authority. Basic Mesh navigation does not cover Relay. |
| M6 physical standalone | Existing README M6 disposable-store/assigned-port procedure in a separate host window; original M2 version/deny check. | Mode standalone, optional services absent, actual output/denial. Keep regular owner deployment separate. |
| M0 owner receipts | Read `.runner/m0-smoke/RUN.json`, `.runner/m0-hang/RUN.json`, `.runner/m0-real-import/RUN.json` with parent ledger/review qualifications. | Acknowledge causes/durations; hang was two10s empty-output attempts with dispatcher exit5, not a60s timeout observation. |

## Echo's local disposition

Review/adopt only these two documents and JOB.md; collect host identity again if source advanced. Owner store is `D:/Dev/Onoes-Mesh/test/app03-manager-m1-disposable`, SQLite AND Relay, despite its name. Tested startup/recovery references and default-store discrepancy are in HOST-CLOSURE.md; do not use bare default startup as owner recovery.

Keep auxiliary pinned `npm run check` unavailable without `APP03-CONTRACT.json`; identify its legitimate source before any separately admitted scope, never invent pins. Keep full native qualification **BLOCKED_PROCESS_EVIDENCE**: absence cannot repair missing original acquisitions. Do not repeat custody/race campaigns or unreproduced cleanup diagnosis. Cosmetic feedback stays deferred. No additional missing affected-product check is established here.

Whole-build acceptance/final15m cleanup retirement remain unestablished. Close gates only with exact scoped evidence; laptop deferral is neither a pass nor a blocker for this completed local handoff.
