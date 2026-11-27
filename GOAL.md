# Current roadmap · November 27, 2026

**Full objective.** Relay + Onoes-Mind usable on Eddie's phone and Echo's PC first, later laptop/cloud/AI box. Reliable Echo chat, history and reconnect on Relay. Nims JSON/Markdown handoff in Mind, with Echo picking up the current source, revision and next action. Canonical private agent homes plus deliberately shared project context; wider devices only after verification; Echo orchestration afterward. Workroom, Rook and Inference are parked; Tripp is deferred; the AI box is not ready.

**Verified.** Echo phone send/reply/separate history/reload accepted. Cyony phone reply/reload accepted. Echo and Deep existing private homes and shared readers proven. Fixed Nims handoff path: actual Echo pickup document 38 / canonical record 64 accepted. Native Nims project chats installed; 390+1440 browser checks passed; physical-phone chat selection/switch still pending. Mind memory-first UI live; 222 workspace + 43 current-app checks and real deployed 390/1440 browser checks passed.

**Remaining.** Cyony private Mind enrollment/import remains OFF; original remote r12/r13 completion/retirement is UNKNOWN and the strict original proof is retained. A new local A2A preservation test passed but does not prove those original remote retirements. No rerun, quarantine or cleanup counts as a substitute. Any future enrollment needs a fresh current binding and separately authorized access. Current wider-device and orchestration acceptance is unproven; do not shrink the full goal to the current milestone.

**Current rules.** QFN authors further code in an isolated worktree; Nims plans, reviews and runs independent checks; log strengths/weaknesses and preserve original attempt caps/failures. Continue productive in-scope work per current owner rules; Smart Stop applies. No PC restart while Eddie is away or asleep. Standing tested milestone publication is subject to the existing no-Actions policy and unchanged private-access boundaries. Do NOT repeat owner/model tests already accepted.

**Where to read.** README, MIND-CONTRACT.md, RELAY-INTEGRATION.md, RELAY-MIND-QUICK-START.md and NEXT-OWNER-CHECKS.md. Exact private runtime/evidence stays in the existing local-only checkpoint.

Historical Workroom rules and milestones (retained, not current instructions)

The retry, scheduler and default-start commands below are historical. They are not authorization to resume parked work or bypass current limits.

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

