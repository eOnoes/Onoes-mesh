# Onoes-Mesh

## Current working preview - updated 2026-11-04

Open https://emitchell.tail8c4a75.ts.net:8453/#workroom for the current work. The active goal is **Finish Onoes-Mesh - all assessed stages**, task c2a77ea9-05bb-4b63-85c7-c2d8e9fb2547. Its ordered backlog, current evidence and blockers are in [WORKROOM-AB-CHECKPOINT.md](WORKROOM-AB-CHECKPOINT.md); [MESH-REPO-INDEX.md](MESH-REPO-INDEX.md) identifies the current worktree, database and process receipts.

The current preview uses data/workroom-preview/tasks.sqlite with Tailscale owner admission, local task sessions, CSRF and revision checks. The original8446 deployment and historical owner data are separate and remain protected. Read the older operating details below as historical qualification records, not instructions to overwrite a current store or start a default server.

Current facts: the real independent review and changes-requested / correction / fresh review loops are verified, with deliberate completion and preserved provenance. Permission denial and same-session recovery are proven. The Agent workspace lists observed Relay peers and links their saved task handoffs; it does not infer coding capabilities or start jobs. Overview identifies the running build and selected store. [RELEASE-OPERATIONS.md](RELEASE-OPERATIONS.md) names the canonical current installation, startup and rollback. Verified source/data backups are under E:/App-Backups/ONOes-Mesh. Physical-phone acceptance and local inference qualification remain open. Off-device backup and automatic scheduling are deferred. This is a private release candidate.

Current additions - 2026-11-06: Nims planning and a locked Mesh-only Echo build / independent Nims or DeepSeek review lane are deployed and qualified in isolated trials, pausing for owner review. Mind can deliberately retrieve a selected saved Workroom task with source revisions and recorded review status under MIND-CONTRACT.md. It adds no personal memory store or automatic writes. Eddie confirmed phone hold/drag and typing/focus are smooth. Full physical background/resume recovery and approved inference engine qualification remain open. Ordinary Relay chat/session/retry/privacy acceptance and the bounded compatibility decision are now verified under RELAY-INTEGRATION.md. Latest evidence is in the final checkpoint section.

## Historical foundation and qualification records

Onoes-Mesh is a PC-hosted PWA for shared tasks, approved command runs, Relay linkage, read-only node observations and standalone Agent use. Run `npm test` for the local suite and `npm start` for the local application. The milestones and operating rules are in `GOAL.md`.

**The retained owner store is `D:/Dev/Onoes-Mesh/test/app03-manager-m1-disposable`, including SQLite AND Relay data. Despite its disposable-looking name, it is not a crash fixture or cleanup target.** Bare default `npm start` or helper startup may select `test/app03-mesh` and does **not** necessarily restore the accepted Relay configuration. An empty alternate database does not establish that owner data was deleted. For owner recovery, use the qualified references below; the separate [M6 standalone procedure](#m6-standalone-agent--workroom) uses a fresh disposable store.

Current deployment/recovery evidence and limits: [HOST-CLOSURE.md](HOST-CLOSURE.md). Deferred physical checks: [NEXT-OWNER-CHECKS.md](NEXT-OWNER-CHECKS.md).

Use Node 24.14 or later. From this repository in PowerShell:

```powershell
npm start
```

Open **http://127.0.0.1:4317/**. Startup prints a JSON `mesh_listening` line with `url` (the server's assigned loopback port), `previewUrl` (the stable phone-preview proxy), PID and store directory. Both listeners bind only `127.0.0.1`. Ctrl+C stops this foreground command. The application keeps running until stopped; it no longer uses the five-minute preview launcher.

The entry point is `test/m1-serve.mjs`, using the unchanged `server.mjs` export `startApp({ dataDir })`. It serves the existing PWA shell and assets. The small loopback proxy adapts Tailscale's Host/Origin headers to the baseline server's loopback interface, retaining the application's session and CSRF checks. The UI uses explicit local admission and five-minute sessions. Persistence/UI integration is built and [automatically verified across actual termination and npm restart on the same store](.runner/m1-persist/parent-product-check.json).

The default store is `test/app03-mesh/tasks.sqlite`, reused on restart. It is a different store from the retained owner directory. For a separate disposable startup, use the already documented M6 standalone procedure below; it does not restore regular owner Mesh/Relay.

## Regular owner startup and recovery

The known hidden helper start/stop/restart procedure is recorded in [HOST-CLOSURE.md, Startup, recovery and data](HOST-CLOSURE.md#startup-recovery-and-data). `start-mesh.ps1` records the root identity in `.runner/mesh-serve.json`; `stop-mesh.ps1` retains SQLite but checks only that recorded root, not whole descendant custody. Logs are `.runner/mesh-serve.log` and `.runner/mesh-serve-error.log`.

The [accepted deployment receipt](.runner/owner-phone-session-recovery/deployment-check.json) and [preservation readback](.runner/owner-phone-session-recovery/final-protected-readback.json) establish regular Mesh, standalone off, native Relay retained, preview port 4317 and the actual owner directory above. Relay uses the confined Python 3.14 runtime/site-packages and copied source described in the separate M4 disposable check below. Bare helpers do not establish these prerequisites. HOST-CLOSURE records proposed `-DataDir` / `-PreviewPort` qualification, but exact helper parameter handling is **unverified here**: code navigation found no index and indexing was denied by `approval_policy=never`. The retained readbacks also do not reproduce the full accepted launch environment. No executable owner restart command is supplied until Echo qualifies those parameters and regular-Mesh/Relay prerequisites from accepted source/evidence; do not substitute defaults or place credentials in command lines.

After restart, expiry or private-content clearance, deliberately use Start/recovery to restore admission. [Accepted recovery evidence](.runner/owner-phone-session-recovery/PARENT-VERDICT.md) records bootstrap403 → challenge200 → completion201 → fresh health verification and the same saved task, with zero automatic lifecycle requests. Physical phone background/resume remains separately pending. After interruption, inspect failed/UNKNOWN; replacement requires a new saved proposal and explicit approval, never automatic replay. Preserve the entire SQLite/Relay store: Git history is not a data backup, and backup restoration/older-release rollback is not qualified.

The verified private route is **https://emitchell.tail8c4a75.ts.net:8446/**, private Tailscale Serve to `http://127.0.0.1:4317`. Keep existing routes; no publishing or route change is needed for this documentation correction. Original protected-control-pipe `Access is denied` failures remain historical in JOB.md.

`npm test` includes an actual `npm start` test using an isolated disposable SQLite store. It checks HTTP 200 and exact file equality for the shell, app.js and styles.css, plus phone-origin demo admission and task create/read through the proxy.

## Current private preview

Echo published **https://emitchell.tail8c4a75.ts.net:8446/** using private Tailscale Serve to `http://127.0.0.1:4317`; existing routes were preserved. Retained deployment evidence verifies HTTP 200/current shell and app.js bytes with regular Mesh/native Relay and unchanged owner rows. [Owner feedback, 2026-10-04](.runner/owner-feedback/phone-flow-confirmed-20261004.md) confirms basic phone access/navigation, saved-task opening and reported Save/Approve/Deny/Cancel traversal. It does not reconstruct every click or establish every physical milestone check.

Current launch retains the owner SQLite AND Relay store `D:/Dev/Onoes-Mesh/test/app03-manager-m1-disposable`. M1 persistence is built/automatically verified; owner-PC restart/phone refresh remains separately pending. Laptop-origin `curl.exe --fail https://emitchell.tail8c4a75.ts.net:8446/` and physical M5 Wi-Fi checks are **PENDING OWNER HOME WINDOW**; the older offline/SSH timeout evidence is retained. Follow NEXT-OWNER-CHECKS.md without repeating confirmed basic phone flow or touching the separate current unapproved proposal. Full custody qualification remains **BLOCKED_PROCESS_EVIDENCE**, and auxiliary `npm run check` remains unavailable without `APP03-CONTRACT.json`; no whole-build acceptance is claimed.

M3 local check, in a separately scoped disposable store/task (never the owner store or current pending proposal): in Workroom, create a task, select exactly `node lib/slow-command.mjs` (fixed repository cwd `.`), save the pending proposal, then Approve. Cancel is enabled while running and waits for the existing ownership bridge to report actual cleanup; the result is saved as failed with `cancelled: true`, captured output and exit code. Reload current task or refresh reads the latest saved result without approving. API cancellation is `POST /api/tasks/<taskId>/cancel` with exactly `{"revision":<current task revision>,"runId":"<current execution id>"}` behind the existing session/origin/CSRF guard. Stale revisions, other run IDs and terminal runs are rejected. Restart after an interrupted run preserves that run as failed/UNKNOWN with null process observations and no automatic retry; deliberate replacement requires Save pending proposal and a new Approve.

Run the retained disposable native/API crash-and-cancel proof locally:

```powershell
npm test
node --test --test-timeout=55000 test/m3-crash-compose*.mjs
node --test --test-timeout=55000 test/m2-approve.test.mjs test/m2-proposal.test.mjs test/m3-idempotent*.mjs test/m3-crash-bridge.test.mjs test/m3-crash-recovery*.mjs test/privacy01.test.mjs
C:/Python314/python.exe -B -m unittest -v test.test_owned_job test.test_owned_capture test.test_owned_cancel
```

The composed checks launch real servers and the fixed ten-second root/descendant, retain original native process handles, cancel through HTTP, and kill only the recorded disposable server identity while the command is live. They restart the same URL/store, check UNKNOWN preservation and repeated approval without spawning, and retain evidence under `test/app03-m3-crash-compose-*`. Basic phone control flow is owner-confirmed; the separate owner-PC interrupted-run/restart check remains pending.

M4 local Relay check: the current-source provenance is service_roots/relay/SOURCE.md. Host dependency setup, once per checkout, uses only the fixed disposable runtime and Python 3.14 dependencies:

```powershell
C:/Python314/python.exe -m venv test/app03-m4-link-runtime
test/app03-m4-link-runtime/Scripts/python.exe -m pip install fastapi uvicorn httpx cryptography
$env:MESH_RELAY='1'
$env:MESH_DATA_DIR='test/app03-m4-link-manual'
$env:MESH_PORT='0'
node server.mjs
```

Mesh launches `C:\Python314\python.exe` directly with `-I -S -B`, adding only the confined `test/app03-m4-link-runtime/Lib/site-packages` and copied Relay source directories. The Windows venv executable is a redirector and is used only for dependency installation; launching it would produce a different listener PID. The direct native listener must match the created child PID, and closing owned stdin ends it. Ambient imports, global/user site-packages and `.pth` hooks remain excluded; there is no fallback to global dependencies. In this retry, installed dependencies were copied from the original job's disposable Python 3.14 site-packages without networking; deployment requires the setup above in its own checkout.

Open the printed loopback URL, Start local session, then Relay. Send to Relay and create task uses the actual copied Relay message route; retain the displayed message id for retries, or deliberately choose New message. Open existing Relay terminal uses its original HTML/composer inside the same admitted page. Saved task-id buttons select the canonical Workroom task. Reconnect Relay reopens the same Relay store; restart Mesh with the same data directory and start a new local session to recover its references. Optional MESH_RELAY=1 npm start uses the existing preview adapter and the same guard. Relay stays Mesh-only with no upstream agent/executor transports. Runtime config and both SQLite files remain in the server-owned data directory; browser requests cannot choose their paths, ports, credentials or commands. A pending Relay identity whose Workroom commit succeeded is repaired by read-only reference recovery; it cannot create another task. Messages and references grant no command proposal or approval.

Exact local checks (run in a separate shell without MESH_RELAY set for the existing M2/M3 tripwire fixtures):

```powershell
npm test
node --test --test-timeout=20000 test/m4-link-store.test.mjs test/m4-link-ui.test.mjs test/m4-link-http.test.mjs
node --test --test-timeout=55000 test/m2-proposal.test.mjs test/m2-approve.test.mjs test/m3-idempotent.test.mjs test/m3-idempotent-ui.test.mjs test/m3-crash-recovery.test.mjs test/m3-crash-recovery-store.test.mjs test/m3-crash-compose.test.mjs test/m3-crash-compose-ui.test.mjs test/privacy01.test.mjs
```

The named M4 HTTP/process/SQLite/Relay test fails, without skips or fabricated success, when dependencies are missing. Once installed it boots actual Relay + Mesh, denies direct/unadmitted requests, checks original Relay HTML, forces a Relay reference-write failure after canonical commit, recovers the existing reference, retries concurrently, reconnects, restarts both on the same stores/URL, and requires exactly one task/message/reference and zero proposals/executions. Evidence is retained under test/app03-m4-link-*; do not stage disposable evidence or the venv. Physical Relay send/reconnect acceptance remains pending.

The native terminal HTML comes from the actual Relay root route through admitted `/api/relay/shell`, then loads into `srcdoc` under hashes of its fixed source script/CSS. Every new Relay HTTP route requires the existing Mesh session guard; `/relay` is absent. Native task selection checks the owned frame, origin and current document identity before reading the canonical task. Windows retry results: npm test 30 + 1 passes; focused M2/M3/privacy 47 passes; named M4 suite six passes, zero skips, including actual Relay message/recovery/reconnect/both-process restart. Retained native handles record exact executable, creation time, exit signal and exit code. Accepted parent browser/deployment evidence is mapped in HOST-CLOSURE.md; physical Relay send/reconnect acceptance remains pending.

## M5 PC and laptop observation

On the accepted private deployment, open **https://emitchell.tail8c4a75.ts.net:8446/**, Start local session, select **Inference**, and press **Refresh nodes**. The fixed identities are PC `emitchell.tail8c4a75.ts.net` / `100.72.250.65` and Laptop `emitchell109-rog.tail8c4a75.ts.net` / `100.119.162.99`. This reads the fixed local Tailscale executable with only `status --json`, through one server-owned `createNodeProbeReader`. It observes cached Tailscale `Online`, not packet reachability or inference/model readiness; those remain unknown. There are no model or remote-command controls.

For the owner Wi-Fi check, first enable the laptop's Wi-Fi and refresh until its returned Online flag is true and the card shows ready with a last-success timestamp. Turn its Wi-Fi off, then press **Refresh nodes** to observe the fixed CLI's current cached flag. Tailscale may take time to report the change; another Online=true read legitimately advances last success. After Online=false (or an unavailable read), a previous success can grant stale only until 60 seconds from that success. Without another successful refresh, the display ages from ready at under 30 seconds to stale, then offline at 60 seconds, preserving last success. Watch that timestamp rather than assuming the Wi-Fi change is detected immediately. An unavailable read, including `cli_timeout` or `cli_access_denied`, is shown separately and establishes no offline result. Local display ticks perform no requests or CLI work. Reopen admission if the five-minute session expires or the page was suspended.

Authenticated `GET`/`HEAD /api/node-probes` only return the aged cache. `POST /api/node-probes/refresh` accepts exactly `{}` under the existing Host/Origin/session/CSRF guard, coalesces concurrent refreshes, returns no-store, and rechecks admission after the asynchronous probe. Browser inputs cannot select configuration, arguments, paths, destinations or timing. The existing `/api/inference-observation` contract and service observations are unchanged.

Local checks use disposable stores and retain evidence separately from source:

```powershell
npm test
node --test --test-timeout=20000 test/m5-node-probes*.mjs test/m5-nodes-api.test.mjs test/privacy01.test.mjs
$env:M5_NODES_PLAYWRIGHT = 'C:/Users/eMitchell109/AppData/Local/hermes/hermes-agent/node_modules/playwright-core/index.mjs'
$env:M5_NODES_CHROMIUM = 'C:/Users/eMitchell109/AppData/Local/ms-playwright/chromium-1243/chrome-win64/chrome.exe'
node test/m5-nodes-browser.mjs
```

The browser check uses actual Chromium at 390×844 and the actual fixed native CLI, compares its sanitized API response against rendered identities/status/timestamps, and separately labels controlled transport/clock transitions. It also checks that local aging makes no request and a delayed reply cannot restore cleared private nodes. The sandbox-native integration attempt returned `cli_timeout` with null last-success/Online fields; it did not prove either host offline. [Parent native/UI evidence](.runner/m5-nodes/parent-product-check.json) verifies fixed CLI exit0, cached PC Online=true/ready and laptop Online=false/offline, with packet/model/inference readiness still unknown. Eddie's physical Wi-Fi check remains pending until home; cached flags can lag Wi-Fi changes and unavailable reads prove no offline result. Only the parent restarts the protected deployment; this check does not touch its owner store or Tailscale configuration.

## M6 standalone Agent / Workroom

From this checkout on Windows, use the existing npm entry point with a disposable store and an automatically selected loopback port:

```powershell
$m6Previous = @{}
foreach ($name in 'MESH_STANDALONE','MESH_DATA_DIR','MESH_PREVIEW_PORT') {
    $m6Previous[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
}
try {
    $env:MESH_STANDALONE = '1'
    $env:MESH_DATA_DIR = 'test/app03-m6-manual-' + [guid]::NewGuid().ToString()
    $env:MESH_PREVIEW_PORT = '0'
    npm start
} finally {
    foreach ($name in $m6Previous.Keys) {
        [Environment]::SetEnvironmentVariable($name, $m6Previous[$name], 'Process')
    }
}
```

Open the printed `previewUrl`. The startup JSON must report `mode: "standalone"`. Start local session → Workroom → create a task → select `node --version` → Save pending proposal → Approve → inspect actual stdout and exit code. Save another proposal and Deny; it stays denied with no execution. The fixed slow command supports Cancel and the same M3 interrupted-run recovery. Relay, Mind and Inference show `not_configured`; node observation is explicitly absent and Refresh nodes is disabled. The flag overrides ambient `MESH_RELAY=1` even with copied service roots installed. There is no Relay startup, inference worker import, tailnet CLI work, or invented readiness. HTTP/browser input cannot change the mode or configuration. Removing the flag (or setting it to `0`) preserves the regular Mesh behavior.

Run the local qualification and actual browser proof with the installed native runtimes:

```powershell
node test/m6-standalone-checks.mjs
$env:M6_STANDALONE_PLAYWRIGHT = 'C:/Users/eMitchell109/AppData/Local/hermes/hermes-agent/node_modules/playwright-core/index.mjs'
$env:M6_STANDALONE_CHROMIUM = 'C:/Users/eMitchell109/AppData/Local/ms-playwright/chromium-1243/chrome-win64/chrome.exe'
node test/m6-standalone-browser.mjs
Remove-Item Env:M6_STANDALONE_PLAYWRIGHT, Env:M6_STANDALONE_CHROMIUM
```

The qualification runs `npm test`, standalone/full-Mesh boundary checks, the named M2/M3 tests in both modes, and the original Python native ownership tests. The browser proof launches **actual `MESH_STANDALONE=1 MESH_RELAY=1 npm start`**, uses Chromium at 390×844, checks real version output/exit, replays once without spawning, re-proposes and denies, cancels the actual slow root/descendant, then kills only its retained disposable server object while running. It restarts the same store/preview URL and requires failed/UNKNOWN with unknown output and no replay spawn. Native process creation times, executable/command lines, original-handle exits, SQLite rows, source hashes and screenshots are retained under `test/app03-m6-standalone-*`; retain these databases/evidence unstaged. The native observer uses console-free `pythonw.exe`; the existing ownership tests and application bridge retain `python.exe`.

The historical legacy `test/m3-crash-recovery-ui.test.mjs` empty-result assertion was corrected in the [accepted Deny/Cancel repair](.runner/owner-deny-cancel-labels/parent-product-check.json); its original failures remain retained. The phone Inspect UI displays `Pending · not run. No process result exists for this proposal.` Scoped product checks and browser recovery are verified; full native qualification remains BLOCKED_PROCESS_EVIDENCE and physical standalone acceptance remains pending. Only the parent handles deployment and separately scoped owner checks.

### Nims and scoped teams
Nims now supports task-scoped read-only planning/review using the existing Codex ChatGPT sign-in. Ask the lead to plan, use its proposed scope/team, review and lock scope, then Start scoped team. Qualified lane: this Mesh workspace with Echo building and DeepSeek or Nims reviewing. It stops at Needs review for owner approval. Creation/locking starts nothing. Restart/uncertain delivery pauses without replay. See PROJECT-LEAD-POLICY.md for limits.
