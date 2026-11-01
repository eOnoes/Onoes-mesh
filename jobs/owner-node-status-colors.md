# Owner-requested small node-status readability change

## Owner authority and scope

Eddie: "Status offline. Lets make a SMALL change here. Status: Offline (red text), Online (lime green text) so it is much faster at a glance work." Follow-up: "Busy (yellow text)".

One narrowly scoped presentation lane, separate from read-only review-M1. Use the existing runner and explicit gpt-6.1-sol/high, workspace-write, approval_policy=never; no model substitution. One writer per disjoint worktree, one integrator; manager must not duplicate an active native writer. No redesign or expanded milestones.

## Change

- Target 03 Inference → PC and laptop tailnet state → PC/laptop node status text (public/app.js renderNodeProbes and public/styles.css).
- Show existing fresh ready status as **Online**, lime green; existing offline as **Offline**, red. Status words only need coloration, not the whole paragraph/card.
- Provide **Busy**, yellow, where a genuine existing status source supplies busy. Do NOT infer node workload from the global UI busy flag, disabled controls, a pending refresh, stale observation, cached Online=true, or presence of a Codex process. If this node-probe contract lacks busy telemetry, prepare the presentation mapping/style without inventing telemetry and disclose that no runtime busy state is established.
- Keep Stale separate (amber/yellow is appropriate), Unavailable/unknown/not_configured neutral, including observation-unavailable versus cached status wording. Do not make unavailable reads falsely green/current or falsely establish offline.
- Preserve backend schema, status aging thresholds, timestamps, cached Tailscale Online field, observation provenance, all readiness-unknown disclaimers, fixed read-only probe behavior, admission and privacy/lifecycle guards. No backend/auth/model/task logic changes.
- Preserve text labels and safe DOM construction, so colour is not the only signal. Reuse existing CSS tokens or introduce narrowly scoped semantic tokens; keep the existing layout.

## Discovery prerequisites

Parent has indexed ONLY canonical public/ under path-local repo local/Onoes-Mesh-2e213bc5 with AI summaries off. High-confidence source: public/app.js::renderNodeProbes#function (line 354 at HEAD 6e4c5798922bdd533db78e2f8ba5c8e84512a6ff). Parent verified indexed renderer source; no parent source edits.

Before a native Codex run in a new worktree, manager pre-index that exact worktree's public/ and any admitted existing focused test paths with use_ai_summaries=false; do not rely on canonical/snapshot cache identity or weaken approval_policy=never for indexing. Codex uses resolve_repo/plan_turn and verifies source freshness before changing it.

## Tests and live acceptance

- Test labels and classes for Online/Offline plus stale/unavailable preservation; verify intended lime/red/yellow CSS mappings and legitimate Busy presentation without claiming live busy telemetry.
- Exercise current focused node-probe UI regression tests on disposable fixtures; add a focused regression if none verifies this renderer. Run syntax checks and git diff --check. Do not run broad parked suites or mutate owner task/proposal stores.
- Integrate only the verified scoped source/test diff; preserve canonical dirty docs and untracked evidence. No broad staging, reset, clean, unrelated merges or restarts.
- Verify exact private HTTPS live origin https://emitchell.tail8c4a75.ts.net:8446/ in phone/desktop viewports: 01 Overview → Start local session → wait verified banner → 03 Inference → Refresh nodes. Inspect actual visible status text and computed CSS. Static assets may need navigation/reload only; don't restart listener unless proven startup-bound and preserve exact owner data if a scoped restart is needed.
- Physical laptop Wi-Fi-off baseline/aging observation remains owner's evidence, not synthetic busy/model proof. Parent has recorded owner's Offline observation; Wi-Fi-on recovery still pending.

## Return

Report commit and actual files changed, test command/results, precise deployment/browser verification, active native process identity/exit evidence and any Busy contract limitation. Call complete only if live deployed/rendered colours are verified; otherwise state the actual blocker. No inference/model launch, task/proposal execution, OS/startup change, credentials, public exposure or unrelated work.


## Same-manager exact admission addendum
Read .runner/inputs/parent-admission.md BEFORE edits, and .runner/WORKER-COMMS.md. It binds baseline, allowed source/tests, exact pre-index identity, actual sandbox precheck, retained proof/cleanup, append-only records and Echo-only live integration/readback. Do not interact with owner origin/store/session/deployment or replace inherited JOB history; return independently verifiable candidate, never claim live completion as worker.
