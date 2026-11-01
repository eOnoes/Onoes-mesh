# REVIEW-M3 — functional assembly review

Reviewed `f6d86a4bc1c9dff2d6827ee064e7c4654724057f..37bd103c6170882da8f8ede1013dc4d3d9a566a3` on 2026-10-03 America/Chicago (execution evidence timestamps are UTC, 2026-10-04). Read GOAL.md and the M3 product diff, excluding generated `test/app03-*` artifacts from source review. Read existing M3 tests and canonical `D:/Dev/Onoes-Mesh/.runner/m3-crash-compose/parent-product-check.json` as evidence only. No product changes made.

## Defects

None reproduced. No functional assembly gate identified within this review's scope. This is a review result, not owner acceptance or milestone closure.

## Actual local checks

| Command | Result |
| --- | --- |
| `npm test` | Exit 0; 30 baseline checks + 1 real npm-start HTTP check; zero failures/skips |
| `node --test --test-timeout=55000 test/m3-idempotent*.mjs test/m3-crash-compose*.mjs test/m3-crash-recovery*.mjs test/m3-crash-bridge.test.mjs test/m2-approve.test.mjs test/m2-proposal.test.mjs test/privacy01.test.mjs` | Exit 0; 54 checks, zero failures/skips; includes fixture discovery |
| `C:/Python314/python.exe -B -m unittest -v test.test_owned_job test.test_owned_capture test.test_owned_cancel` | Exit 0; 19 native checks, zero skips |

Logs: `test/app03-review-m3-npm.log`, `test/app03-review-m3-focused.log`, `test/app03-review-m3-native.log`. Native PID/create identities, original retained-handle exit assertions, cleanup-failure assertions, fixed argv/cwd, auth/origin/CSRF, ownership, persistence and replay safeguards remained intact. Node v24.14.0 / native Windows / Python 3.14.

## Independent app/API and Chrome exercise

Disposable store: `test/app03-review-m3-browser/tasks.sqlite`; actual app at `http://127.0.0.1:49529`, bound only to IPv4 loopback. Review helper copied the existing composed browser fixture into disposable evidence, changing only its import depth and evidence-path prefix. Actual server/UI/bridge were used; launch logging observed real spawns without replacing execution or results.

- Ordinary UI path: Start local session → Workroom → Create task → select `node lib/slow-command.mjs` → Save pending proposal. First save succeeded, pending revision 2. No HTTP400 or stale resave409 reproduced; no edge-case campaign conducted.
- UI Cancel: task `a15d2c2a-a0a2-4518-a31a-83b141395984`, run `978d8b0d-4152-406b-ba7d-3e76ee74454a`. Approve enabled Cancel while running. Cancel persisted failed / FAIL / cancelled true / exit 1 / cleanup verified true, with actual root and descendant start output and no completion output. Root PID 1448012, creationTime100ns `134355471330146834`; descendant PID 2787360, creationTime100ns `134355471330519193`. Observer retained the original bridge/root/descendant handles and asserted all exit-signaled. The same result survived restart and was reread in Chrome.
- UI crash/recovery: task `e4f6f795-b588-43eb-824b-80fea90e0c5b`, run `fce5ec6c-5ea1-49e7-bff5-e25e8bcc69aa`. Killed only the original retained server object, PID 4032404 / creationTime100ns `134355470700503592`, while the fixed ten-second command was live. Root PID 2011308 / `134355471920033023`; descendant PID 2830272 / `134355471920398245`. Original server/bridge/root/descendant handles all exit-signaled. Restarted same store and URL with server PID 3747904, created `2026-10-04T00:26:32.7235156Z`. Chrome required fresh admission and showed the same run at revision 4 as failed with UNKNOWN outcome, unknown process observations, no automatic retry, and disabled Approve/Cancel. Task open/done remained separate from run outcome.
- Independent API script: repeated approvals of both prior terminal attempts returned HTTP200 and identical saved tasks with unchanged SQLite rows. New `node --version` task received concurrent approval statuses `[202,200]`, one run `57003bbf-225f-4bae-87e4-6b5bd5369d1d`, actual stdout `v24.14.0\r\n`, exit 0, verified cleanup. Later duplicate approval returned the same terminal result. SQLite gained exactly one execution. Original server log has exactly two bridge launches for the two browser slow runs; restarted server log has exactly one launch for this deliberate version proposal, and none for replay.

Evidence: browser `*-live-identities.json`, `*-handle-exits.json`, `*-before.json`, Cancel result/reopened SQLite snapshots, `independent-api.json`, server identity/log files, and `recovery.png` under `test/app03-review-m3-browser/`. Requested suites additionally prove replacement fencing, interrupted approved/running recovery once, persistence migrations, admission invalidation and unchanged no-replay results across repeated restarts.

## Stabilization list — not an assembly gate

- Builder's reported transient browser proposal HTTP400 / stale resave409 remains unconfirmed; ordinary reviewer save succeeded. Revisit only if reproduced during stabilization, with exact request/response evidence.
- Browser helper assumes every newly observed running command is the slow root/descendant fixture. After the independent short version run, its observer timed out waiting for a descendant and helper exited 1 through its `finally` cleanup. Completed Cancel/crash retained-handle proofs and independent API assertions had already passed. Minimal future harness scope: restrict observation to the slow command. No product defect inferred and no helper/test source fixed here.

## Cleanup and limitations

The helper's `finally` checked the recorded server PID/create identity before termination and awaited its retained ChildProcess close; both server logs were saved. Chrome review tab closed. Cleanup audit `C:/Python314/python.exe -B test/app03-review-m3-cleanup.py` passed after correcting the disposable audit script's import path (initial attempt could not import `lib`). It checked 46 recorded identities from this run's evidence, plus supervisor PID 3048516, independent bridge PID 3981944 and root PID 2094596; all absent or exit-signaled. Original slow-command exit proof comes from handles retained while live, not PID absence. No process-name cleanup or unrelated-service termination used. Disposable stores/evidence retained; no existing DB/data deleted.

Suite-created untracked M3 evidence was relocated intact beneath `test/app03-review-m3-suite/` to satisfy the review artifact namespace; `relocations.json` maps original handles printed in logs to retained locations. Product/test/config/README/service_roots stayed unchanged. No cloud, credentials, runner/dispatcher changes, Actions, pushes or M4-worktree inspection. Real Chrome desktop used; no phone/Tailscale owner check. Full-page screenshot timed out; viewport screenshot succeeded. Owner acceptance remains pending. Host runner can commit the review artifacts; no sandbox widening requested.
