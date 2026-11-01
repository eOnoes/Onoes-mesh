Goal: M1 phone -> task: make the ACTUAL app create/list/reopen tasks and retain them after server restart.
Read GOAL.md. M0 is complete and merged; do not change runner/dispatcher or repeat runner tests.
Owner direction: stop speculative engineering; make the app work. Preserve baseline useful code.
Use the existing durable task store and real UI/API, not a mock, synthetic-only demo or second task store.
Boot the app locally, create task "hello" through its real browser UI, restart the actual server using the same test data directory, reload and prove the same task survives.
Fix concrete defects you encounter on that path, including actual UI wiring. Do not write hypothetical failure frameworks.
Retain existing authorization, origin guards and protected execution boundaries; do not remove them to make a demo pass.
Use a disposable isolated test store. Do not delete owner databases or reuse real service state.
Check: npm test passes, real UI create/restart/reopen proof with URL and task ID, no fake test outputs.
If browser tooling is unavailable, implement and exercise the real API and record the ONE remaining browser check honestly; do not stall all coding.
Allowed: server.mjs, lib/**, public/**, test/** except test/m1-serve*, JOB.md and append-only DECISIONS.md.
Do not touch package.json, README.md, tools/**, GOAL.md, other worktrees, archive, service roots or system settings.
Parallel m1-serve owns package/start instructions and tools/start-mesh.ps1, tools/stop-mesh.ps1.
Keep the current server startup/environment interface usable; tell Echo one concrete integration requirement in JOB.md if needed.
No public exposure, new credentials, Tailscale enrollment, CI/runners, cloud changes or speculative audit work.
Work directly with workspace-write tools. Host runner commits when shared Git metadata is sandbox-denied.
JOB.md: Done / Next / Blocked, with exact checks and a usable local app URL.
