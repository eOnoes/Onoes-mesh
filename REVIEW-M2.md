# M2 functional review — 2026-10-03

Reviewed `job/review-M2` at `22d62df030012926ab4ecc5e452b673a5f733bcc`, the approval diff `aa50ea23ad9a8df9856c672d430d3d2284dd07cb..HEAD`, and the proposal implementation integrated at `15022886b47c6b2cf38ae73705870ee0f15d4d81`, against GOAL.md's M2 Task → run path. This is the single M2 review; no product fixes were made.

## Reproduced defects

No blocking reproduced M2 defects. No concrete non-blocking functional defects were reproduced, so there is no numbered defect list or stabilization fix queue from this review.

## Checks run in this worktree

| Actual command | Result |
| --- | --- |
| `node --version` | `v24.14.0` |
| `npm test` | Exit 0; 30 + 1 passed; zero failures/skips; 637.249 ms + 332.6546 ms |
| `node --test --test-timeout=55000 test/m2-approve.test.mjs test/m2-proposal.test.mjs test/privacy01.test.mjs` | Exit 0; 35/35 passed (9 approval, 5 proposal, 21 privacy); zero failures/skips; 2091.7864 ms |
| `C:/Python314/python.exe -B -m unittest -v test.test_owned_job test.test_owned_capture` | Exit 0; 12/12 passed; zero skips; 0.935 s |
| `git diff --check` | Exit 0 |

Full command output is retained in `test/app03-review-m2-checks-20261003/{npm-test,m2-node-tests,python-tests}.txt`. Privacy/UI harness checks are synthetic DOM tests; the HTTP/process/SQLite tests and Chrome interaction below are real application checks.

1. **Real HTTP/process/SQLite approval and restart passed.** Task `aacd62c1-c9bd-42a6-8aff-ffa345597241`, execution `618d4b1a-4005-44a8-ac28-1a98f8b93326`, native root PID `3952356`; actual stdout `"v24.14.0\r\n"`, exit 0, cleanup verified true, stderr empty. Server PID `4027436` → `3507216` at `http://127.0.0.1:53558/` retained the exact result and other task. Store: `test/app03-m2-approve-4a6dc66a-1d37-470c-bef6-91a746e79a00`. Repropose/deny created zero executions for that proposal and retained the historical approved execution. The test also restarted after denial and verified it persisted.
2. **Proposal-only and denial-only paths passed without execution.** Actual child servers installed executor tripwires before application imports. Create, propose, read, deny and restart did not invoke an executor. A separate denial-only SQLite store had zero total execution rows. Exact pending proposal persistence passed across server PID `2954112` → `3124548`, task `d85c0224-9f8e-416a-ba6a-ba0e4b3bf8d3`, store `test/app03-m2-approve-proposal-http-886221cf-fed3-4813-b63f-2d5001c0f7d4`.
3. **Necessary boundaries passed.** HTTP tests rejected absent admission, incorrect/absent CSRF, nonexact/null/absent Origin and Host, actor claims, stale revisions, extra request fields, arbitrary cwd and non-whitelisted commands without execution records. `git status` ran through native custody using the fixed absolute Git executable and this worktree's actual root. Additive v1/v2 migration preserved existing task fields/proposals; invalid persistence remained byte-identical and unavailable. Unavailable bridge and unverified cleanup did not become successful execution or task done. Native tests covered actual output/nonzero exit, capture timeout/cleanup, assign-before-resume failure, retained descendant exit proof, fatal close errors and handle-count preservation.

## Actual Chrome reproduction and result

Fresh disposable store: `test/app03-review-m2-browser-20261003-c10854b7-2eb1-4722-851c-436f2c1e2361`, real `node server.mjs` at `http://127.0.0.1:53936/`. No owner/deployment database was opened.

1. Open the URL in Chrome, click **Start local session**, then **04 Workroom**. Enter `M2 functional review` in Title and click **Create task**. Task `fe249583-008a-43d1-9734-4d31f53477e8` was created at revision 1, status open.
2. Select **node --version** in Whitelisted command and click **Save pending proposal**. Revision 2 displayed exactly `{"command":"node --version","cwd":"."}` and pending/not executed; Approve/Deny became available. Click **Approve**. Revision 4 displayed completed, run `28a4f376-e6f0-4679-99b6-42406dabecf1`, stdout `v24.14.0`, exit 0, cleanup verified true, no error/stderr. Read-only SQLite inspection matched the installed Node version, fixed argv/cwd and native result (root PID `3913616`); task remained open.
3. Stop the exact server process (PID/start time/executable matched) and restart the same store and port: PID `3903736` → `3355960`. Reload Chrome, click **Start local session**, **04 Workroom**, and the saved task. The identical task/revision/run/output/exit/cleanup appeared.
4. Click **Save pending proposal** again (revision 5), then **Deny** (revision 6). UI displayed denied/no execution record for this proposal and cleared the current run output. Read-only SQL confirmed exactly one historical approved run, that run unchanged, decision executionId NULL, and zero runs for task/proposalRevision 5.
5. Stop/restart the same disposable server again: PID `3355960` → `69340`. Reload, re-admit, and reopen the task. Revision 6 still displayed denial with no current run. Read-only SQLite compared task and decision exactly with the saved pre-restart values and confirmed historical runs 1 / denied-proposal runs 0.

Retained evidence in that store: `approved-db.json`, `denied-db.json`, `after-restart-db.json`, `browser-proof.json`, and each server's stdout/stderr. Final exact server PID `69340` was stopped; its loopback endpoint was unreachable afterward. Test fixtures stopped their child servers and retained disposable SQLite files. No database deletion occurred.

The independent parent browser proof at `D:/Dev/Onoes-Mesh/.runner/m2-approve/parent-browser-check.json` was read for context: task `fde25357-22fc-4281-a833-d535a8e86719`, run `1dd27b26-ad9a-4db9-abd1-bcdc3f9bdd02`, `v24.14.0`, exit 0/cleanup true, historical approved runs 1, denied-proposal runs 0 after restart. It was not replayed or substituted for this worktree's checks.

## Stabilization and pending acceptance

No reproduced non-blocking functional stabilization items. Terminal-style visual choices remain deferred to Eddie. M3 repeat-approval returning the first result and crash/recovery/cancel belong to the next product milestone, not M2 defects. Existing M2 tests exercise duplicate prevention; this review does not claim M3 acceptance.

Eddie's laptop/phone acceptance remains pending: phone propose → approve → inspect output → repropose → deny → confirm no denied-proposal run. Local session admission and agent browser clicks do not establish Eddie's identity or owner acceptance. M0 stays closed; the simultaneous m3-idempotent worktree was not edited.

Only this report, append-only JOB.md/DECISIONS.md and disposable evidence were written. No source fixes, runner review, archive reads, cloud/credentials/public exposure, Actions or push. jcodemunch resolved this worktree as unindexed; automatic approval review rejected targeted indexing under the never-approval policy, so the small M2 source set was read directly. Report staging/commit is left to the host runner; shared Git metadata lies outside this job's writable roots.
