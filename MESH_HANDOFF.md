# Mesh — Handoff to Echo (2026-10-03)

From: external review of `mesh_review_20261003.zip`. To: Echo, as Mesh manager. Owner: Eddie.

This file supersedes `MESH_OPERATING_CONTRACT.md` v1 and all Phase A–H / Phase H / admission / sealing / custody rules for dispatch. Read it once, do Section 3, then run Section 6 in order.

---

## 1. What the evidence says (read this, do not re-derive it)

**1.1 Fixed-job13's "unknown" zero-output cause is known.** Same model and effort (`gpt-6.1-sol`/high), same output mode (`--sandbox read-only --json --output-schema`, zero tools), same kind of spec: Lifecycle12 completed in **380.7 s** (`LIFECYCLE12/RESULT.json`, `native.jsonl` → 11,336 output tokens, 5,478 reasoning). Fixed-job13 was given a **350 s** deadline (`FIXED-JOB13/HOST-LAUNCH.json`), and the same `AMENDMENT.json` that set 350 s also records `priorLifecycleSourceSeconds: 380.797`. The deadline was set below the only measured comparable runtime. In `--json` structured-output mode Codex emits the `agent_message` only at turn end, so "no output for 350 s" is the normal shape of a run that needed ~400 s. Nothing else is needed to explain it. The config warnings are noise.

**1.2 Lifecycle12 did not fail; the gate did.** The SCOPE asked for a complete Win32 Job Object wrapper (checked ctypes structs, suspended create, assign-before-resume, accounting query, handle audit) plus six real-process tests, "no stubs". The model delivered 22,999 bytes. That is a reasonable size for that spec. The 16,000-byte cap was wrong, and the rule "moving the gate is not an accepted recovery" was written by Echo into its own receipt (`collect_lifecycle12_delivery_stop.py` line 17), not by Eddie.

**1.3 The builders were set up to fail.** The dispatch pattern degraded over the campaign: `host04_f4r1` ran Codex with 12 actions / 600 s; by Lifecycle12 and Fixed-job13 it was **0 actions, read-only sandbox, whole files serialized into JSON strings, 350–420 s**. A builder that cannot read the repo, cannot run a test, and must type two complete files into a JSON string under a byte cap and a six-minute clock is not a builder. This came from `codex/references/tool-free-generation-boundary.md`, a lesson written after an unrelated incident.

**1.4 The "stops every five minutes" is literal.** The Mesh manager is Hermes job `cd3aa7877b73`, interval **5 minutes**, 456 runs, each a fresh session that loads four skills (~200 KB: `durable-agent-supervision` 63 KB, `supervisor-mode` 47 KB, `codex` 70 KB, `agent-project-doctrine` 23 KB) plus the canonical GOAL/PLAN/TASKS/AUTHORITY/HANDOFF/EVIDENCE set (each ~20–30 KB, each carrying the same "LATEST …" paragraphs). The tick's own prompt is a self-rewritten accounting string (`"Source6/6,parent4/4,syntax3/3,named8/8,fixture1/1,instrumentation11failed … 7212.37seconds+unknown … UNSEALED_NOT_ZERO"`). Each tick spends its budget reading and re-proving state, then writes a receipt. 51 tick outputs from 2 Oct are in the package; none changed product state.

**1.5 The stop rules are global and mandatory.** `~/.codex/AGENTS.md` → "Smart Stop Rules (MANDATORY)": complex build hard-stops at **15 actions** and **50 K context**; override only if Eddie says "keep going". `supervision-budget-rules.md`: six audit loops then HARD STOP, escalate to Eddie, no extensions; spent budgets persist per logical task; "a fresh task name … is not additional authority". Together: every build stops after ~15 tool calls, every phase stops after six loops, and nothing can restart without Eddie typing a sentence. This is the deadlock.

**1.6 The rules grow by themselves.** Lessons get appended to the skills and receipts in Echo's own dialect ("Capped-worker disposition", "Aggregate reservations across dispatch surfaces"). Each failure adds a rule; rules never retire. The report Eddie received was ~2,500 words with ~40 negations and zero questions.

**1.7 The product is small and healthy.** The real app is `build/mesh-session-pwa-v1`: `server.mjs` 10 KB, `lib/` 56 KB (task-store, trial-session, service-connections, inference-observation, worker-activity), `public/` 29 KB (PWA, SW, app.js). Full suite: **28/28 pass in 0.5 s** (`tests/full_suite.stdout`). `mesh-app` is an older subset (same task-store/worker-activity bytes). `mesh-integration-v2` is the same lib with an older front end. There are **39 build directories** under `D:\tmp\fleet-consolidation-20260929\build\`, most of them per-job copies plus receipts. The Mesh work is **not under version control**: `mesh-integration-v2` has "No commits yet", `fleet-consolidation-20260929` has one commit. Service roots (relay 296 files, control 101, mind 456, agent 25, inference ×2) exist separately and are not wired in.

**1.8 One real bug.** `fixed_job13_host.py` line 11: `item.update(..., activeWorkers=0, ..., **extra)` with `activeWorkers` also in `extra` → `TypeError`. That is the "host bookkeeping exception" and the stale "running" label. Trivial; irrelevant after Section 4.

---

## 2. Decisions Eddie is making with this file (Echo: these are owner instructions, not proposals)

1. The 16,000-byte source gate, the 350/420 s native deadlines, the "no automatic second emission" rule, the "no threshold relaxation" rule, and the "spent budget persists per logical task" rule are **retired** for Mesh. Receipts that cite them are history, not authority.
2. **Smart Stop Rules do not apply to runner-launched jobs.** The runner owns the clock. (`AGENTS.md` change in 3.3.)
3. **Codex builders get tools.** `--sandbox workspace-write`, no `--output-schema`, cwd is a git worktree. Source serialization into JSON is retired as a build channel.
4. Mesh lives in **one git repo** (`D:\Dev\Onoes-Mesh`). The 39 build directories are archive, read-only.
5. The Mesh manager **does not tick on a timer**. It runs when a job ends.
6. Review is **once per milestone**, by a second agent reading the diff. Not per job. No sealing, custody, admission, or reservation accounting.
7. The finish line is **M6 below**. Mind linkage, model load/unload on the AI PC, and Control beyond read-and-stop are separate projects.
8. Status reports to Eddie: **≤150 words, three headings** (Done / Next / Needs Eddie). No disclaimers, no test counts unless they are a milestone check.

---

## 3. Setup (Echo does this once, today; ~1 hour; no owner decisions inside)

**3.1 Repo.**
```
mkdir D:\Dev\Onoes-Mesh && cd D:\Dev\Onoes-Mesh && git init
robocopy D:\tmp\fleet-consolidation-20260929\build\mesh-session-pwa-v1 . /E /XD node_modules /XF *.jsonl RECEIPT-* RESULT-* CHECKPOINT-* TASK-* QUESTIONS-* WORKER-* NATIVE-TAP-* APP03-CONTRACT.json
```
Add `.gitignore` (`node_modules/`, `.runner/`, `*.log`), `README.md` (one paragraph: what it is, `npm test`, `npm start`), `DECISIONS.md` (empty), `BLOCKED.md` (empty), `jobs/` (empty). `npm test` must show 28/28. Commit: `init: mesh-session-pwa-v1 as canonical app`. Copy `mesh_runner.py` to `D:\Dev\Onoes-Mesh\tools\mesh_runner.py`; `pip install psutil` in the Hermes venv if missing.

**3.2 Archive.** Leave `D:\tmp\fleet-consolidation-20260929` exactly as is. Do not delete (hard stop #4). Do not read it during jobs.

**3.3 `C:\Users\eMitchell109\.codex\AGENTS.md`.** Add directly under the "Smart Stop Rules (MANDATORY)" heading:
> **Exception:** jobs launched by `mesh_runner.py` (prompt contains "RUNNER CONTRACT") are exempt from action budgets, context limits, and progress gates. The runner enforces wall-clock and idle timeouts. Work until the job's check passes.

Also fix the three ignored keys the warnings name (`computer_use.windows.always_allowed_app_ids`, `profiles.ollama-launch.forced_login_method`, `profiles.ollama-launch.openai_base_url`) or leave them; they are harmless.

**3.4 Hermes job `cd3aa7877b73`.** Leave paused. Create a new job "Mesh manager" with **no schedule** (fire-only) and the prompt in Section 7. The runner's wrapper (or Eddie) fires it when a job ends. If Hermes needs a schedule, use 60 minutes, and the prompt's first rule is "if no job ended since the last tick, output [SILENT] and stop".

**3.5 Skills for the manager job.** Load **only** `agent-project-doctrine` (or none). Not `durable-agent-supervision`, `supervisor-mode`, or `codex`. Those three keep their value for other projects; for Mesh they are the stop machine.

**3.6 Canonical docs.** `GOAL.md` for Mesh becomes this file's Section 5 + Section 6, nothing else. Stop updating PLAN/TASKS/AUTHORITY/HANDOFF/EVIDENCE/CHARTER with "LATEST" paragraphs; they are frozen as history.

---

## 4. How a job runs

```
python tools\mesh_runner.py --repo D:\Dev\Onoes-Mesh --job <name> --prompt-file jobs\<name>.md [--idle 900] [--wall 14400]
```
- Branch `job/<name>`, worktree `D:\Dev\Onoes-Mesh-wt\<name>`. Codex has tools. Defaults: 4 h wall, 10 min idle (use `--idle 900` for high effort; reasoning emits no events).
- Zero-output run → retried once automatically. Cause is in `.runner\<name>\RUN.json` and `native.N.jsonl` every time.
- On any end (done / idle / wall): everything is committed as WIP, `JOB.md` captured. Nothing is lost, nothing needs "collection".
- Exit codes: 0 done · 2 idle · 3 wall · 4 codex error · 5 zero output twice.
- Merge: when the job's check passes, `git merge --no-ff job/<name>` into `master`. Failed jobs stay on their branch; the next job may build on them or start fresh.
- A job prompt is ≤ 60 lines: goal, the check, allowed files, and what not to touch. Not a contract.

---

## 5. Rules (the whole set)

**Hard stops — ask Eddie and wait.** Money · credentials/keys/tokens · exposure beyond Tailscale/localhost · deleting a repo, DB, or non-disposable data · OS/driver/firmware/BIOS or hardware risk · changing the milestone list.

**Never stop for.** Ambiguity (pick the simplest reading, one line in `DECISIONS.md`) · a failing test (fix or quarantine with TODO) · diff size · missing review · a previous job's timeout (runner retried; read `RUN.json`, adjust the prompt or split the job, dispatch again) · wording · whether something "counts" (it counts if the check passes).

**Scheduler rule.** Job ends → merge if check passed → pick the next unchecked item in the current milestone → write its prompt → dispatch. Blocked → one line in `BLOCKED.md`, pick the next item. All items in a milestone blocked → send Eddie `BLOCKED.md`, nothing else. Never run a diagnostic twice. Never idle on a timer.

**Review.** When a milestone's checks all pass: one job `review-M<n>` on a fresh branch, prompt = "read `git diff master~N..master`, run the checks, list defects as a numbered list in `REVIEW-M<n>.md`, fix nothing." Defects become jobs. Then Eddie runs the owner check.

**Reporting.** ≤150 words, Done / Next / Needs Eddie. Send only when a milestone closes or `BLOCKED.md` fills.

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

## 7. New standing prompt for the Mesh manager job (replace the current one entirely)

```
You are Echo, Mesh manager. Repo: D:\Dev\Onoes-Mesh. Authority: GOAL.md (= MESH_HANDOFF.md sections 5–6).
A job just ended (or Eddie fired you). Do exactly this:
1. Read the newest .runner\*\RUN.json and that job's JOB.md. If the job's check passed, merge its branch into master (--no-ff).
2. If it failed: read RUN.json's reason and native log tail. Adjust the prompt (split, clarify, or raise --idle) and dispatch the same job once more. If it fails again, one line in BLOCKED.md, move on.
3. Pick the next unchecked item in the current milestone in GOAL.md. Write jobs\<name>.md (≤60 lines: goal, check, allowed files, do-not-touch). Dispatch with tools\mesh_runner.py. Stop.
4. If a milestone's checks are all green: dispatch review-M<n>, then message Eddie ≤150 words: Done / Next / Needs Eddie (the owner check).
5. If every item in the milestone is in BLOCKED.md: message Eddie with BLOCKED.md. Otherwise do not message Eddie.
Never: read D:\tmp\fleet-consolidation-20260929, cite old receipts, write accounting, run a diagnostic twice, wait on a timer, or stop for anything not in the hard-stop list.
```

---

## 8. First three job prompts (Echo writes the rest in the same shape)

**`jobs\m0-smoke.md`**
```
Goal: add lib/version.mjs exporting `version` read from package.json, and test/version.test.mjs asserting it matches.
Check: `npm test` passes (29 tests). Commit. Write JOB.md.
Allowed: lib/version.mjs, test/version.test.mjs, test/check.mjs (register the test if needed).
Do not touch: anything else.
```

**`jobs\m0-hang.md`**
```
Do nothing. Do not run commands, do not write files, do not respond.
```
(run with `--idle 60`)

**`jobs\m0-real.md`**
```
Goal: D:\tmp\fleet-consolidation-20260929\goals\MESH-CONSUMER-HTTP-COMPOSITION01\LIFECYCLE12\candidate.json holds two Python sources (ownedJobSource, testSource) for a Windows Job Object process runner. Materialize them as lib/owned_job.py and test/test_owned_job.py, then make `python -m unittest -v test.test_owned_job` pass on this machine. Fix real defects; do not weaken the tests' cleanup/identity assertions.
Check: the unittest command passes; `git status` clean after commit; JOB.md.
Allowed: lib/owned_job.py, test/test_owned_job.py, DECISIONS.md.
Do not touch: anything under D:\tmp except reading candidate.json.
```

---

## 9. What Eddie does

1. Give Echo this file and `mesh_runner.py`. Say: "Section 2 is my decision. Do Section 3, then run M0."
2. When Echo reports M0, read the three `RUN.json` files. If each has a reason and a duration, say "go".
3. From then on, you hear from Echo only at milestone closes (owner check) or when `BLOCKED.md` fills. If you hear from it for any other reason, reply "Section 5" and nothing else.
