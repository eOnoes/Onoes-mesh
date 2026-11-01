# M0 runner repair: distinguish real output from warnings/empty messages
Goal: fix the measured zero-output defect before retrying m0-hang.
Read GOAL.md; owner override supersedes historical phase/gate practices.
Evidence: .runner/m0-hang/RUN.json ended 2026-10-03T16:20:18+00:00.
Its native.1.jsonl has two item.completed errors (configuration warnings)
and one item.completed agent_message with empty text; no tools or real response.
The supplied runner counted these as three output items, stopped after one
attempt and returned 0 instead of the required two attempts and exit 5.
Keep original receipt item counts for auditability; correct zero-output
classification consistently in both the retry decision and final exit decision.
Exclude only demonstrated non-output events, not genuine text/tool activity.
Do not broaden sandbox permissions, suppress tests, or weaken hang assertions.
Preserve idle/wall clocks, two-attempt budget, cleanup and host Git commit behavior.
Check: add Windows unittest regression tests against the measured event shape:
warning-only plus empty message => two attempts, exit 5;
nonempty response or genuine tool event => original successful behavior;
ordinary timeout/cleanup and command failure behavior must not regress.
Use isolated disposable fixture repos/stub CLI processes where needed; never
launch or stop a second live production m0-hang job from this builder.
Run the new unittest suite with native Windows Python and npm test.
Write JOB.md: Done / Next / Blocked, including exact checks and results.
Allowed files: tools/mesh_runner.py; test/test_mesh_runner.py; JOB.md;
DECISIONS.md only for a necessary one-line interpretation.
Read-only evidence: .runner/m0-hang/RUN.json and native.1.jsonl in parent repo.
Do-not-touch: GOAL.md, MESH_HANDOFF.md, canonical docs, mesh_dispatch.py,
manager state, other prompts/branches/worktrees, Lifecycle12 staged input,
archive, unrelated Forge/Phi services, credentials and global Codex settings.
Do not add milestones. This is a defect-repair job within M0.
After merge, Echo will retry the unchanged m0-hang acceptance check once.
