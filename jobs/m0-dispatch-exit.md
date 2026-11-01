Goal: Repair REVIEW-M0.md defect 3 within M0: dispatcher propagates runner exit after durable completion.
Read GOAL.md sections 5-6 and REVIEW-M0.md defect 3. Two disjoint builders are authorized.
Own tools/mesh_dispatch.py and test/test_mesh_dispatch.py only; parallel builder owns runner files, do not edit them.
After persisting and delivering completion successfully, dispatcher actual process exit must equal runner exit for 0,2,3,4,5.
Retain visible nonzero notification-failure paths and runner-exception behavior, durable pending/success receipts, busy retry and bounded budget.
Deliver completion BEFORE exiting; do not bypass manager busy claims, remove scheduler locks or infer delivery from exit0.
Update existing mocked regression expectations and add actual native subprocess exit assertions for codes 0,2,3,4,5.
Mock runner and Hermes boundaries for subprocess checks; NEVER invoke real manager or Codex during tests.
Retain hidden launches, supplied tools, model/effort/clocks, dispatch single-job lock and identity receipts.
Check: native Windows -m unittest -v test.test_mesh_dispatch passes all expected tests, zero skips; npm test; git diff --check.
Use C:/Users/eMitchell109/AppData/Local/Python/pythoncore-3.14-64/python.exe, command-local PYTHONPATH=C:/Users/eMitchell109/AppData/Local/hermes/hermes-agent/venv/Lib/site-packages and PYTHONDONTWRITEBYTECODE=1.
Record exact command/interpreter/counts/skips/durations and actual exit assertions in three-line JOB.md; append rationale to DECISIONS.md.
Allowed: tools/mesh_dispatch.py, test/test_mesh_dispatch.py, DECISIONS.md append only, JOB.md.
Do not edit runner files, native owned-job source/tests, other worktrees, GOAL.md, REVIEW-M0.md, archives/D:/tmp, Forge/Phi/models, cron/global settings or scheduler locks.
No sandbox weakening, milestone changes, real hang rerun, or questions. Host runner commits if shared Git metadata is denied.
M1 waits for Eddie go. Do not redo the one milestone review.
