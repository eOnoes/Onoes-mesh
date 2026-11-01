# Independent M0 review

Reviewed `git diff master~10..master` at `3b5683f8023a43f056e64af2047fecc90c213be8`; the base is initial app `a5ca8b68ae2e1ab08c3edb4e19f43fa46900767e`, including integration `b6edbb1` and this review prompt. Read GOAL.md sections 5–6 and the supplied runner contract. Current owner authorization permits two disjoint builders; M1 requires Eddie go. This review fixes nothing. Missing per-job review and diff size are not findings.

## Commands and results

All commands ran locally from this worktree on native Windows. Python commands used the following environment only inside their command process; no global environment or settings changed:

```powershell
$env:PYTHONPATH='C:/Users/eMitchell109/AppData/Local/hermes/hermes-agent/venv/Lib/site-packages'
$env:PYTHONDONTWRITEBYTECODE='1'
```

| Check | Result |
| --- | --- |
| `npm test` | PASS: 29 executed, 29 passed, zero failed/cancelled/skipped/todo; Node test duration 443.0938 ms. SQLite experimental warning is not acceptance evidence. |
| `C:/Users/eMitchell109/AppData/Local/Python/pythoncore-3.14-64/python.exe -m unittest -v test.test_owned_job test.test_mesh_runner test.test_mesh_dispatch` | PASS: all 32 expected tests executed: owned-job 6, runner 13, dispatcher 13; zero skips; 109.687 s. Dispatcher launches were mocked. Native runner fixtures used disposable Git repositories and Python CLI stubs. |
| `git diff --check` | PASS: exit 0, no whitespace errors. Rechecked after writing the review artifacts; Git reported only its LF-to-CRLF conversion warning for JOB.md. |
| `git diff --check master~10..master` | PASS: no output. |
| `git diff --no-index --check -- NUL REVIEW-M0.md` | Exit 1 for the new-file comparison; no whitespace diagnostics, only LF-to-CRLF conversion warnings for the artifacts. This is separate from the passing required tracked diff check. |
| Smoke source and committed outcome | PASS: `package.json` version is `0.1.0`; `lib/version.mjs:3` exports its value using a URL relative to the module; `test/version.test.mjs` compares the export to the package value and is registered by `test/check.mjs`. `git log -1 job/m0-smoke`, `git show job/m0-smoke:JOB.md`, and `git merge-base --is-ancestor 8c2fa4f master` confirm smoke commit `8c2fa4f37ed7ac38379c9bb19b48cda0b42550a3`, its three-line JOB.md, and integration. The historical Git blocker in that JOB.md does not outweigh the actual commit evidence. No smoke builder launched. |
| Current hang evidence | Read only `D:/Dev/Onoes-Mesh/.runner/m0-hang/RUN.json`, `DISPATCH.json`, both referenced native logs, and the current manager-fire log. RUN ended `2026-10-03T16:38:06+00:00`; DISPATCH argv has `--idle 60`; exactly two attempts of 10.0 s; DISPATCH `runnerExit=5`. |
| Independent native-log classification | PASS: imported this worktree's current `tools.mesh_runner.is_output_item`; parsed every JSON line and classified every `item.completed`. Each attempt has three raw items: two configuration warnings classified false and one empty agent message classified false. Both independently yield `output_items=0`, `tool_events=0`. Token usage and Codex exit 0 do not establish meaningful output. The inherited smoke JOB.md in RUN was not used for hang acceptance. |
| `git -C D:/Dev/Onoes-Mesh-wt/m0-hang status --porcelain=v1 --untracked-files=all` | PASS: empty output; hang worktree clean. |
| Hang process inspection | PARTIAL / UNCHECKED overall absence. Recorded dispatcher PID `2144320` is absent. psutil inspected live `codex.exe`/`node.exe`, creation identities, command lines and working directories; no accessible process matched the hang worktree. Thirteen accessible identities were stable; other inspectable creation times predating the job exclude those identities from this job's launches. Four later identities deny both command-line and cwd access: node PIDs `630620` (created `1791047755.930552`), `1550628` (`1791047757.255314`), `1906336` (`1791047757.250764`), and Codex PID `3754580` (`1791047755.576108`). Their creation identities were stable, but their ownership cannot be established from cwd/argv. `Get-CimInstance Win32_Process` also returned Access denied. No unrelated process was terminated. Do not record a full process-absence pass. |
| Completion delivery evidence | Current mocked suite passes busy-followup, success, exhaustion, failure and exception cases. The actual hang's current manager-fire log says “already being fired by the scheduler; not run again”; its older DISPATCH has only `managerFireExit=0`, without a durable delivery outcome. That ended run does not prove delivery by the merged repair. Real manager delivery remains UNCHECKED by design: no Hermes manager was fired. |
| Additional focused reproducers | Three defects below reproduced independently. The CLI-failure reproducer used the existing disposable runner fixture; the dispatcher reproducer mocked every launch. The orphan reproducer used a native disposable Python parent and child; only that child's matching PID/create identity and unique argv marker were eligible for fixture termination, and termination plus wait completed. |

jcodemunch resolved this worktree as not indexed. Used direct diff/source inspection; did not create an index outside the two permitted repository artifacts. No implementation/tests, milestones, scheduler state, other worktrees, or global configuration were edited. No hang rerun, real Codex/model launch, or GitHub Actions operation occurred. Shared Git metadata is outside the writable roots; the host runner owns the review commit.

## Actionable defects

1. **P1 — Runner reports a failed Codex CLI as success when it emitted any meaningful item.** Location: `tools/mesh_runner.py:81`, `tools/mesh_runner.py:105`, and `tools/mesh_runner.py:167`. The reason starts as `done` and never incorporates a naturally exited CLI's nonzero return code. Meaningful output disables the zero-output exit, leaving `done` mapped to runner exit 0. Reproducer under the command-local Python environment:

   ```python
   from test.test_mesh_runner import MeshRunnerTests, measured_events
   case = MeshRunnerTests()
   case.setUp()
   try:
       code, receipt = case.run_fixture(
           measured_events('Fixture response before CLI failure'), exitcode=7)
       print(code, receipt['attempts'][0]['returncode'],
             receipt['attempts'][0]['reason'])
   finally:
       case.doCleanups()
   ```

   Measured output: `0 7 done`, one attempt. A CLI that reports progress and then fails can therefore be represented as a successfully completed job. Incorporate CLI failure into the final outcome (documented Codex-error exit 4), retaining explicit timeout outcomes and the two-attempt zero-output policy. Cover nonempty output followed by nonzero CLI exit. This defect exists in the retained runner path, not in the narrow warning filter.

2. **P1 — Normally exited CLI roots leave job descendants running.** Location: `tools/mesh_runner.py:79` and `tools/mesh_runner.py:91` (cleanup helper at line 34). Cleanup runs only while the CLI root is still alive. Once it exits, the runner neither terminates nor verifies any surviving descendants; a later PID-based tree walk cannot recover reparented processes reliably. Native Windows reproducer: substitute only the CLI executable boundary with a disposable Python stub, using the same `run_codex` function, real polling, logs and process creation. Have the stub read stdin, start `subprocess.Popen([sys.executable, '-I', '-c', 'import time; time.sleep(30)', uniqueMarker])`, record that child's PID and psutil creation time, emit `{"type":"item.completed","item":{"type":"agent_message","text":"fixture output"}}`, and exit 0. Use idle/wall 60 s and a disposable temporary cwd.

   Measured result: root exit 0, reason `done`, `killed_pids=[]`; native child PID `1553060`, creation time `1791048079.7106512`, was still alive after `run_codex` returned. Its creation identity and unique argv marker both matched the fixture. The review then terminated and waited for only that child. This is a runner custody defect; the new `lib/owned_job.py` native tests pass but the CLI runner does not use that custody. Establish descendant custody before launching/resuming the root and verify cleanup on every completion path, including natural root exit, while retaining the runner's existing clocks. Add a native normal-root-exit/surviving-descendant regression.

3. **P2 — Dispatcher process exits 0 after a runner exit 5 if notification succeeds.** Location: `tools/mesh_dispatch.py:133`, `tools/mesh_dispatch.py:144`, and `tools/mesh_dispatch.py:152`. The runner code is stored in JSON but never propagated after successful completion delivery. `main()` falls through; Python exits 0. Thus the receipt's `runnerExit=5` and the actual dispatcher process exit are different, contrary to the requested dispatcher-exit-5 check. Reproducer in a separate native Python process, with all runner/Hermes launches mocked:

   ```python
   from test.test_mesh_dispatch import MeshDispatchTests, SUCCESS
   case = MeshDispatchTests()
   case.setUp()
   try:
       value = case.run_main(5, [(0, SUCCESS, '')])
       print(value, case.receipt()['runnerExit'],
             case.receipt()['managerFire']['status'])
   finally:
       case.doCleanups()
   ```

   Measured output: `None 5 succeeded`; native Python process exit was 0. The existing nonzero-completion test also permits this fallthrough. Deliver and persist the completion first, then propagate the runner's failure code when delivery succeeds; retain visible notification-failure and runner-exception paths. Assert actual dispatcher exit behavior for runner codes 0, 2, 3, 4 and 5. The historical hang receipt supplies runner exit evidence only; its dispatcher process exit was not recorded and cannot be reconstructed here.
