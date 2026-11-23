# Remaining owner checks

## Current owner checks · November 23, 2026

| Where | What you can do |
| --- | --- |
| Phone · Workroom | Open the board to create, edit or move a card. The guide and direct card links are installed. The phone checks for dragging, review, reload, rotation and reconnect have passed. [Open Workroom](https://emitchell.tail8c4a75.ts.net:8453/#workroom) |
| Phone · Relay | Read conversations and older messages. Mesh maintenance currently pauses outgoing messages. The tested update that explains the pause in the composer is awaiting its Mesh and card-writer reconnect. |
| At the PC · 3D Print Pilot | When ready to share the pilot, have the saved backup archive password available for the two local prompts. The existing shared Mesh card is connected to Mind. The print pilot is still private to Workroom. |
| At the PC · supervised work | Arrange a quiet recovery window for the historical job holds. After recovery and route qualification, start one real card from the phone with Echo building and Nims reviewing. Rook activation follows that check. |
| Inference · other machines | The installed release lists **Tripp's PC** and its reported model, **Nemotron-boat**. The TEMP update identifies the rebuilt Linux desktop as **omarchy**. Mesh observed it offline. After rollout and its next connection, use **Other machines → Check machine status** to verify its CPU and GPU temperatures. |

The desktop update also reads RAM, CPU and GPU use over the same SSH connection. CPU use comes from two short samples. RAM use accounts for memory Linux can make available. On a multi-GPU desktop, Mesh shows the highest measured GPU usage and temperature. A missing temperature shows **Temperature unavailable**. Readings expire after 30 seconds.

The main-PC Nemotron load, chat and unload check already passed from the phone. The release guide covers startup, recovery and the remaining supervised job check. [Release operations](RELEASE-OPERATIONS.md)

## November 21 development check for project handoff

The cross-repository handoff now uses events captured by the Workroom card
store when a shared printing spec changes. Echo's channel and Nims's MCP client
must read the same updated CAD filename and card revision. Replaying the event
must preserve the receipt. Removing Nims's tool grant must leave Echo's allowed
project read available. To run this qualification, install Mind's optional MCP
test dependency, set `PYTHONPATH` to the matching Mind checkout, and run
`python -m pytest -q test/project-context-handoff-qualification.py` from Mesh.
It uses temporary agent identities and an in-memory board.

## Workroom acceptance record · November 18, 2026

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

At the November 18 check, the backup fix was installed and its restoration test passed. The Help and reconnect changes shipped in the November 23 phone release.

## Historical 8446 checks - retained for that separate installation

The following source revisions, requests and pending states are historical.
They are not the current Workroom checklist or permission to run a command.

Current source HEAD: `d077f2d83ed9607f21139aa71a86743918a50f74`; accepted recovery merge `64a1d257f638cc390ad0ba2a152849d15bbca6ba`. Private URL: **https://emitchell.tail8c4a75.ts.net:8446/**. Exact mapping: [HOST-CLOSURE.md](HOST-CLOSURE.md). These are deferred checks, not instructions to restart now or execute Eddie's current pending proposal.

### Confirmed checks on the older installation

[Owner feedback, 2026-10-04](.runner/owner-feedback/phone-flow-confirmed-20261004.md) confirms physical phone access/navigation, saved Test for Echo opening and reported Save/Approve/Deny/Cancel traversal. Read-only parent evidence records revision22 and actual cancellation: cancelled=true/cleanupVerified=true, rootExit1/statefailed. Task done does not mean command success. A **separate newer pending proposal** stays unapproved. Every click/denial is not durably reconstructed. Older literal `ownerAcceptance: pending` fields remain historical, qualified by this narrower confirmation.

### Earlier laptop checks · archived

Echo owns the home reminder; no reminder/account/email action is created here. No repeated SSH/ping while parked and no assumption that offline means broken.

| Gate | Check when home | Retain as passing evidence |
| --- | --- | --- |
| M1 laptop-origin shell | Laptop on existing tailnet: `curl.exe --fail https://emitchell.tail8c4a75.ts.net:8446/`. No route/enrollment changes. | Device, command/exit, time and returned Onoes-Mesh shell. PC HTTP200 does not substitute. |
| M5 physical Wi-Fi | Phone → Inference → Refresh nodes with laptop Wi-Fi on until available cached Online=true/ready and last-success timestamp. Owner turns Wi-Fi off, refreshes and watches aging. | Actual flag/timestamps, ready→stale→offline. Cached Online can lag Wi-Fi; ready ages at30s, offline at60s from last success without another success. cli_timeout/access_denied is unavailable, not proved offline. No packet/model readiness claim. |

Single M1 review is paused until laptop-origin success ([ledger](.runner/manager-handled.json), `m1-persist.next`), not completed or an independent ready lane.

### Other owner windows recorded for the older installation

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

### Echo's local disposition on the older installation

Review/adopt only these two documents and JOB.md; collect host identity again if source advanced. Owner store is `D:/Dev/Onoes-Mesh/test/app03-manager-m1-disposable`, SQLite AND Relay, despite its name. Tested startup/recovery references and default-store discrepancy are in HOST-CLOSURE.md; do not use bare default startup as owner recovery.

Keep auxiliary pinned `npm run check` unavailable without `APP03-CONTRACT.json`; identify its legitimate source before any separately admitted scope, never invent pins. Keep full native qualification **BLOCKED_PROCESS_EVIDENCE**: absence cannot repair missing original acquisitions. Do not repeat custody/race campaigns or unreproduced cleanup diagnosis. Cosmetic feedback stays deferred. No additional missing affected-product check is established here.

Whole-build acceptance/final15m cleanup retirement remain unestablished. Close gates only with exact scoped evidence; laptop deferral is neither a pass nor a blocker for this completed local handoff.
