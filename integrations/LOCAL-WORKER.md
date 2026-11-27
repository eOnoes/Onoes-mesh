# Local Qwen worker — candidate

## Quick start

1. Prepare a task JSON outside editable source: `allowed_files` (at most four
   writable files), `context_files`, `instruction`, literal `checks` and
   optionally `repairs`. See `integrations/local-worker-example.json`.
2. Supply the existing pinned runtime JSON and its exact hash. Keep both
   documents off Git; use placeholders here, never keys or private paths.
3. Preview without a model call — this validates the pins and creates nothing:

   ```powershell
   python -B integrations/local_worker_candidate.py preview --task TASK.json --runtime RUNTIME.json --runtime-sha256 HASH
   ```

4. Run the task deliberately, with the same arguments and `run` in place of
   `preview`. The first attempt has a 12-tool/180-second ceiling; an optional
   pre-admitted repair (`repairs: 1`) adds one 8-tool/120-second attempt.
5. Inspect the evidence: the staged workspace, `review.patch` and `RESULT.json`.
   Passing fixed checks yield `READY_FOR_REVIEW`, never an applied change.
6. Review the diff and run appropriate functional tests yourself, then decide
   whether to apply it to the isolated worktree. Fixed checks are static and
   content-only; no functional test runs automatically.

## Limits and review

This is a small Python task layer over the existing DSH headless worker, not a
new agent service or a replacement for DSH. It uses the existing exact local
Qwen profile, filesystem boundary, credential custody and owned-process guard.
No additional Python packages, model weights, port or startup task are needed.

The operator creates a task JSON and a separately pinned runtime JSON. Runtime
paths and hashes select the reviewed Node/DSH CLI, existing guard, pure checker,
route probe, headless profile and source/run directories. Runtime and task
documents stay outside editable source. The runtime contains paths and hashes,
not credential values. Never put these private machine documents in Git.

Each task selects at most four writable files and twelve total files. The layer
copies those files into a fresh disposable capsule. DSH receives that capsule
as its working directory, a bounded context excerpt and the fixed acceptance
checks. The source checkout is never the child's working directory. Extra or
context-file changes are rejected for review; observed unadmitted file calls
also stop the attempt. This audit supplements the existing DSH boundary and is
not a claim that an external observer can prevent every tool call in advance.

The first attempt has a 12-tool/180-second ceiling. One focused repair may be
admitted in advance (`repairs: 1`), limited to 8 tools/120 seconds. A guard stop,
permission failure, uncertain actor or changed source is held without a repair.
There is one worker lease per run root. Existing leases and task IDs are never
replayed or automatically declared stale; review original evidence first.

The built-in check types are `text_contains`, `json_fields`, `preserve_suffix`
and `python_syntax`. Text checks are literal and must be described that way in
the task. JSON checks distinguish booleans from numbers and reject duplicate
keys/non-JSON constants. Suffix checks compare the original bytes exactly.
Python syntax is parsed only: candidate code is never imported or executed.
These checks do not replace functional tests or independent design review.

Successful output is `READY_FOR_REVIEW`, not an applied or production-approved
change. Evidence includes the staged workspace, source hashes in `PLAN.json`,
per-attempt raw logs, fixed-check results, `review.patch` and `RESULT.json`.
`history.jsonl` is a compact operator history. Failed quality checks stop after
the admitted attempt(s); `HELD.json` preserves guard/runtime uncertainty and
the lease. Do not rerun or remove it merely because a PID looks absent.

Create `STOP-REQUEST.json` in the current task evidence directory to request a
stop of that newly owned child only. No other process is targeted. Keep Codex
responsible for reviewing the diff, running appropriate functional tests and
deciding whether to apply it to the isolated worktree.

Reviewed task-specific lessons can be supplied explicitly. Workers cannot edit
their own runtime, tests, budgets or lesson library. Changes are compared with
baselines before adoption. The first guidance comparison was a tie; that
candidate remains inactive. This layer has not established a general quality,
speed or subscription-saving advantage over DSH.

Run the pure local suites with:

```powershell
python -I -B test/local_worker_checks_test.py
python -I -B test/local_worker_candidate_test.py
```

The second suite's three Windows process-integration cases additionally use
`MESH_LOCAL_WORKER_GUARD_SOURCE` pointing to the already-reviewed guard source.
They run harmless synthetic children, not models. Without that explicit local
path, those three cases are skipped. Local runtime setup is operator-owned;
there is no installer that provisions credentials or changes services.


## Trial decision

Keep this experimental for the next three admitted small tasks. Record each
actual diff, fixed-check outcome, independently reviewed acceptance, repair
count, tool count and time. Compare like tasks with the previous direct DSH
workflow. Retain the layer if it preserves correctness and reduces review or
repair work; revise or scrap it if its overhead and failure rate outweigh that
benefit. Do not infer a general speed or allowance saving from one task.

Current evidence: 33 pure-check tests and 20 task/process tests passed, including
three actual Windows owned-process cases with synthetic children. The first real
DSH-backed task produced the quick start in one attempt, 7 tools and 25.68 seconds,
with no source application or functional code execution. Its exact preserved
history and diff were independently reviewed before being copied into this
isolated source branch. One earlier helper implementation hit its 12-tool cap
on the 13th observed call; that stopped attempt and original artifacts remain
in the evaluation record. No cap was raised or attempt resumed.
