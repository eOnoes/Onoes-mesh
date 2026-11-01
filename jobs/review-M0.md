Goal: ONE independent second-agent M0 diff review. Fix nothing.
Read GOAL.md sections 5-6 only; current owner permits two disjoint builders and M1 needs Eddie go.
Review git diff master~10..master (initial app a5ca8b6 through integration b6edbb1 and this review prompt), plus the runner's supplied contract.
Focus functional correctness of smoke, zero-output classification, real Win32 job cleanup and completion-event delivery.
Run npm test (29 tests, zero skips) and the native Windows named Python suites:
C:/Users/eMitchell109/AppData/Local/Python/pythoncore-3.14-64/python.exe -m unittest -v test.test_owned_job test.test_mesh_runner test.test_mesh_dispatch
Set command-local PYTHONPATH=C:/Users/eMitchell109/AppData/Local/hermes/hermes-agent/venv/Lib/site-packages and PYTHONDONTWRITEBYTECODE=1 for psutil; no global changes.
Require every expected Python test to execute; skipped tests are not acceptance.
Run git diff --check. Inspect smoke version/export and committed JOB.md; do not launch another smoke builder.
Inspect ended m0-hang RUN.json and DISPATCH.json under D:/Dev/Onoes-Mesh/.runner/m0-hang read-only, not archive/history.
Using CURRENT tools/mesh_runner.py is_output_item, independently classify both hang native logs; expect two empty attempts, zero tools, dispatcher exit5.
Verify hang worktree clean and no job-owned Codex/node processes; use PID/create identity and worktree matching, never terminate unrelated processes.
Do not rerun hang or fire any real Hermes manager from checks; dispatch tests mock launches.
Do not infer acceptance from exit0, inherited JOB.md, warnings, or builder claims. Each finding needs file/line and concrete reason/reproducer.
Write REVIEW-M0.md: check commands/results, then numbered actionable defects with severity; write 'Defects: none' if none.
A measured runner/dispatcher defect is within M0, not a milestone change. Missing per-job review/diff size is not a defect.
If scope blocks a check, report the actual blocker and skipped/unchecked result, not pass.
Check: REVIEW-M0.md present with numbered defects or explicit none and all check results; JOB.md three-line outcome.
Allowed: REVIEW-M0.md, JOB.md only. Host runner commits if sandbox cannot write shared Git metadata.
Do not touch implementation/tests, DECISIONS.md, GOAL.md, old docs, cron state/locks, global settings, other worktrees, D:/tmp, Forge, Phi or model operations.
