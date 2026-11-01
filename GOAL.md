## 5. Rules (the whole set)

**Hard stops — ask Eddie and wait.** Money · credentials/keys/tokens · exposure beyond Tailscale/localhost · deleting a repo, DB, or non-disposable data · OS/driver/firmware/BIOS or hardware risk · changing the milestone list.

**Never stop for.** Ambiguity (pick the simplest reading, one line in `DECISIONS.md`) · a failing test (fix or quarantine with TODO) · diff size · missing review · a previous job's timeout (runner retried; read `RUN.json`, adjust the prompt or split the job, dispatch again) · wording · whether something "counts" (it counts if the check passes).

**Scheduler rule.** Job ends → merge if check passed → pick the next unchecked item in the current milestone → write its prompt → dispatch. Blocked → one line in `BLOCKED.md`, pick the next item. All items in a milestone blocked → send Eddie `BLOCKED.md`, nothing else. Never run a diagnostic twice. Never idle on a timer.

**Review.** When a milestone's checks all pass: one job `review-M<n>` on a fresh branch, prompt = "read `git diff master~N..master`, run the checks, list defects as a numbered list in `REVIEW-M<n>.md`, fix nothing." Defects become jobs. Then Eddie runs the owner check.

**Reporting.** ≤150 words, Done / Next / Needs Eddie. Send only when a milestone closes or `BLOCKED.md` fills.

**Process closure.** Follow `SUPERVISION.md`: scoped owned-process sweeps every 15 minutes, 10-minute post-job grace, milestone cleanup and a 15-minute final follow-up. Capture ownership, preserve active/pending/shared/manual workloads, recheck exact identity before stopping leftovers, and verify native exit plus protected app health. Routine cleanup stays quiet and does not delay functional work.

---

## 6. Milestones (each owner check is ≤ 2 minutes on the phone or PC)

Paths are in `D:\Dev\Onoes-Mesh`.

**M0 — Runner proven** (today)
- `m0-smoke`: add `lib/version.mjs` exporting the package version and a test for it. Check: `npm test` passes, commit exists on `job/m0-smoke`, `JOB.md` present.
- `m0-hang`: prompt is "do nothing and do not respond". Run with `--idle 60`. Check: exit 5, two attempts in `RUN.json`, worktree clean, no `codex.exe`/`node.exe` from the job left running.
- `m0-real`: port Lifecycle12's `candidate.json` (`ownedJobSource`/`testSource`) into `lib/owned-job.py` + `test/test_owned_job.py` and make the tests pass on Windows. Check: `python -m unittest test.test_owned_job` passes. (This retrieves the work the gate threw away; it is also the process-custody piece Phase B wanted.)
Owner check: Eddie reads three `RUN.json` files; each has a cause and a duration.

**M1 — Phone → task**
- `m1-serve`: `npm start` serves the PWA on `127.0.0.1:<port>`; `tailscale serve` maps it; document the URL in `README.md`. Check: `curl` over Tailscale from the laptop returns the shell.
- `m1-persist`: task created in the UI survives `npm start` restart (task-store already does this; prove it through the real UI, not the mock).
Owner check: open URL on phone, create task "hello", restart server from PC, refresh phone, task is there.

**M2 — Task → run**
- `m2-proposal`: a task can hold one proposal (`{command, cwd}`) from a whitelist in `config/commands.json` (start with `node --version`, `git status`).
- `m2-approve`: approve/deny buttons on the task; approve runs the command via `lib/owned-job` (from M0), stores exit code + stdout; deny stores a denial and runs nothing.
Owner check: on the phone, propose `node --version`, approve, see output; propose again, deny, see denial, confirm nothing ran (`RUN` log empty).

**M3 — Replay and recovery**
- `m3-idempotent`: approving twice runs once; the second approve returns the first result.
- `m3-crash`: kill `node server.mjs` while a 10-second whitelisted command runs; restart; task shows `unknown`/`failed`, never `done`; cancel on a running task kills the job object.
Owner check: Eddie does the kill/restart from PC and reads the task state on the phone.

**M4 — Relay**
- `m4-link`: a message in Relay (`service_roots/relay`, minimal adapter) creates or links a Mesh task; reconnect keeps the same task id. Workroom task-store is the only task store; Relay holds a reference.
Owner check: send a message in Relay, see the same task in Mesh after reconnect.

**M5 — Inference read-only**
- `m5-nodes`: `lib/inference-observation.mjs` probes the PC and the laptop over Tailscale; UI shows ready / offline / stale from real probes with timestamps. No model operations.
Owner check: turn the laptop's Wi-Fi off, node goes stale then offline on the phone.

**M6 — Standalone**
- `m6-standalone`: `MESH_STANDALONE=1 npm start` runs the Agent workspace with Relay/Mind/Inference absent; M2 and M3 checks pass.
Owner check: run it, do the M2 check.

Out of scope for Mesh: Mind linkage, model load/inference/unload, AI-PC commissioning, Control beyond read + stop, cosmetic overhaul.

---

