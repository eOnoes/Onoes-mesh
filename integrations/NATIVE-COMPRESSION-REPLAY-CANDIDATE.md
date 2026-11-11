# Native compression replay candidate — not installed

The selected Echo run admitted the correct new Rook question, but its saved
compressed carrier ended by restating the older maintenance question as active.
The exact faulty execution path remains unproven. No native installation,
gateway restart, history repair, or new provider trial is authorized here.

## Narrow defect and proposed correction

In `ContextCompressor._reappend_inflight_user_task`, the guard checks content
after the **first** summary end marker. A carrier can contain older markers in
its historical context. That guard can therefore decide that a current request
is already present even when nothing follows the latest boundary.

The adjacent `_has_merged_inflight_replay` method already uses the last marker.
The proposed one-line patch makes the replay guard agree with that boundary.
It does not replace a live request, alter scope, or suppress completed work.

Patch: `integrations/native-compression-replay-candidate.patch`.

Frozen native source SHA-256:
`2a4fcfe558e7319cf26842c7898a671140c0b5f2d06da33245e6eced391acd43`.
Candidate SHA-256:
`5dff87f2411431919aeeb8e4ec49defa1644f936d147b9b4a23b3eb342cb5c9d`.

## Evidence and limits

All diagnostic paths below are relative to the actual Mesh checkout:
`C:/Users/eMitchell109/Documents/ChatGPT/Nims Chat/mesh-workroom-ab`.
Do not substitute the separate `D:/Dev/Onoes-Mesh-sandbox` checkout.

- Frozen source and receipts: `data/native-compression-replay-candidate/`.
- The isolated boundary probe compiles two unchanged method bodies from the
  selected snapshot and uses synthetic text carriers and dependency doubles.
  It imports no installed native packages and makes no provider calls.
- Baseline: four checks pass, nested-boundary check fails. Candidate: five pass.
  Covered: nested historical marker, one replay, existing live content,
  current user after summary, and absent input/boundary.
- Candidate Python syntax passes. Installed source still matches the frozen
  baseline. Native owner PID 47220 still owns port 8642, with its existing
  creation time. No source or service change was installed by this work.
- An initial real-import probe emitted the native source-update self-check's
  “update is still running” refusal. It was not repeated. The final diagnostic
  avoids native imports; that initial probe is not native acceptance evidence.

These checks **do not** qualify full compression, multimodal input, persistence,
the loaded gateway, or prove that this patch fixes the earlier live incident.
The Mesh default 503-check gate is unchanged historical evidence; these five
diagnostics are not added to its count.

## Before installation

Reconcile the patch with the current native source and its owner; preserve dirty
work. In an isolated native checkout, add a normal behavior regression and run
the required native `scripts/run_tests.sh` path, including real compression,
repeat compaction, role alternation, persistence/reload and multimodal cases.
The AST boundary probe is diagnostic only, not a substitute for those tests.
Then review the exact deployed source/runtime, check all-worker quiescence,
and obtain any required shared-gateway maintenance approval. Keep the candidate
uninstalled until those checks are satisfied. Do not release historical writer
holds or replay earlier tasks as part of this patch.
