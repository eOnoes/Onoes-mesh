# Inference-control panel — Codex design brief

## Assignment
Produce a **design-only, read-only mockup** for the private Mesh Inference-control panel. Do not change the Mesh milestone list, runtime behavior, routes, Tailscale/Serve configuration, owner store, Relay, Mind, or any live controls.

Read first:
- `D:/Dev/Onoes-Mesh-sandbox/INFERENCE-CONTROL-MONITOR-INTENT.md`
- `D:/Dev/Onoes-Mesh-local-box/README.md`
- `D:/Dev/Onoes-Mesh-local-box/GOAL.md`
- `D:/Dev/Onoes-Mesh-local-box/BOX/live-backup/index.html`

## Deliverables
1. A mobile-first layout recommendation for the Inference tab.
2. Two alternate layout concepts with trade-offs.
3. A static mockup only; no live data calls and no implementation of Pause, Stop, or Unload.
4. A short `INFERENCE-CONTROL-PANEL-DESIGN.md` describing information hierarchy and approval questions.
5. Keep the existing Mesh visual family; do not restyle Overview, Relay, Workroom, or Control.

## Required information hierarchy
- Header: `LOCAL / INFERENCE CONTROL`, private/local status, sampled time, freshness.
- Host health: CPU, system RAM, GPU cards, temperature/utilization/VRAM/power/fan where supported; explicit `UNKNOWN` or `STALE` when unavailable.
- Inference inventory: model name/path, revision/hash when available, backend/runtime, owner PID, GPU assignment and per-GPU contribution, and state.
- Distinguish display GPU activity from model compute. Never infer a model from VRAM use alone.
- If mapping is unproven, show `GPU_MAPPING_UNKNOWN` with evidence.
- Actions are visibly scoped and disabled in this design phase unless ownership is proven. Show the safety sequence: proposal → authorization → execute → read-back → receipt.

## Safety constraints
- No broad process kill, generic process suspend, credential/prompt access, public bind, external telemetry, Mind/Relay writes, model loading, or runtime startup.
- Pause is not generic OS suspension; it is runtime-specific and may be `unsupported`.
- Stop and LLM Unload must name one owned runtime/model and require read-back verification.
- Unknown, stale, ambiguous, recycled-PID, or conflicting evidence disables controls.

## Acceptance
- Static design only; existing product behavior unchanged.
- Mockup can be opened locally without a service.
- Include a numbered list of questions Eddie must approve before implementation.
- Record any assumptions in `DECISIONS.md`; do not invent live values.
- The runner may commit only the design artifacts on its isolated job branch; do not merge, deploy, or push.
