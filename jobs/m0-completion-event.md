Goal: fix a measured completion-event race in tools/mesh_dispatch.py.
The m0-hang completion fire returned "Job is already being fired by the scheduler; not run again."
After that existing manager ended, no next Mesh builder was active; the next timer was an hour away.
Make completion durable when the manager is already busy, so an ended job gets a follow-up event fire.
Use the supported Hermes CLI; never edit cron/jobs.json, scheduler locks, credentials or global config.
Do not add a polling LLM supervisor or change milestones. A bounded non-LLM event retry is fine.
Read GOAL.md and tools/mesh_dispatch.py. No archive reads.
Keep hidden subprocess launches, existing runner clock, worktree behavior and single-job lock.
Handle success, busy/coalesced fire, nonzero failure and terminal exception explicitly.
Add regression tests with mocked CLI/manager-state inputs; do not fire the real manager from tests.
Check: native Python unittest regression suite and npm test both pass; JOB.md contains results.
Allowed: tools/mesh_dispatch.py, test/test_mesh_dispatch.py, JOB.md, DECISIONS.md.
Do not touch: tools/mesh_runner.py, lib/owned_job.py, test/test_owned_job.py, GOAL.md,
MESH_HANDOFF.md, other job prompts/worktrees, cron state, archive or unrelated services.
A separate m0-real worker owns the owned-job module/tests. Do not edit its files.
Use gpt-6.1-sol/high; edit directly in your worktree. Host runner handles commits if sandbox Git metadata is denied.
