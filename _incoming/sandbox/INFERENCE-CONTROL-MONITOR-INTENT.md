# Onoes-Mesh — Inference Control Monitor Intent

> **Status:** PLANNING. Notes only; no implementation or service integration is authorized by this document.
> **Likely predecessor:** `Inference-control` (name not found in the current Onoes-Mesh sandbox search; confirm against older snapshots before building).
> **Owner:** Eddie / Echo
> **Date:** 2026-10-14

## Purpose

Add a private Mesh tab that shows whether the local AI box is healthy, what inference is loaded, where it is loaded, and how much thermal/memory headroom remains. It must also provide narrowly scoped **Stop**, **Pause**, and **LLM Unload** actions without broad process killing or authority over Mind, Relay, Hermes memory, or production state.

## First useful slice

1. **Telemetry card**
   - CPU temperature and utilization.
   - GPU temperature, hotspot/VRAM temperature when the driver exposes them, utilization, power, fan state, VRAM used/total and percentage.
   - System RAM used/available/total and percentage.
   - RAM temperature only when a real DIMM/board sensor exists; otherwise show `unavailable`, never a guessed value.
   - Sensor freshness, source, and `UNKNOWN/STALE` state when a reading is unavailable.

2. **Inference inventory**
   - Loaded model name/path and revision or file hash when available.
   - Runtime/backend and owning PID.
   - GPU assignment and per-GPU memory contribution.
   - State: `not_loaded`, `loading`, `loaded`, `running`, `stopping`, `unloading`, `unknown`.
   - Distinguish display-only GPU activity from model compute activity. A desktop process using a GPU is not an LLM.
   - If the runtime cannot prove model-to-GPU mapping, display `GPU_MAPPING_UNKNOWN` with the evidence rather than inferring it from memory usage.

3. **Controls**
   - **Pause:** request a runtime-supported pause/admission-drain; do not pretend that generic process suspension is safe.
   - **Stop:** stop one positively identified inference job/runtime only.
   - **LLM Unload:** request model unload through the owning runtime, then verify VRAM release and process state.
   - Disable controls when ownership, PID/creation identity, runtime, or target model is ambiguous.
   - Every action follows: `proposal → explicit authorization → execute → read-back verification → receipt`.

## Current hardware baseline

Verified on 2026-10-14:

- System RAM: 128 GB installed, approximately 127.14 GiB usable.
- RTX 4080 SUPER: GPU 0, 32,760 MiB, 0 MiB used, 0% utilization, display disabled.
- RTX 4070: GPU 1, 12,282 MiB, 1,695 MiB used, 9% utilization, display enabled.
- Current 4070 activity is desktop/display software; no model process was identified.

This baseline is evidence for the first adapter only, not a permanent hardware assumption. Add AMD telemetry adapters later for the planned MI50/MI100 system.

## Proposed boundary

```text
GPU/host sensors + runtime process inventory
                ↓  read-only local collector
        private Mesh telemetry endpoint
                ↓
        Inference Control tab
                ↓
   scoped action broker for owned runtimes only
```

- Collector and action broker run on the PC, preferably loopback-bound and supervised with exact executable, PID/creation-time, argv, cwd, data-root and listener checks.
- Mesh remains private. No public bind, Funnel, public proxy, or new external telemetry service.
- The tab is observational by default. It does not connect to Mind, Relay outbox, Hermes native memory, MCP, delegation, or model providers.
- The collector may read telemetry and process metadata, but must not read credentials or model prompt/content data.
- Do not use image-wide `taskkill`, `pkill`, broad Python cleanup, or “kill all GPU processes.”

## Minimal status shape

```json
{
  "host": "echo-pc",
  "sampled_at": "2026-10-14T00:00:00Z",
  "freshness": "fresh",
  "cpu": {"utilization_pct": 12.4, "temperature_c": 48.0},
  "ram": {"used_pct": 16.3, "used_gib": 20.7, "total_gib": 127.1, "temperature_c": null},
  "gpus": [
    {"index": 0, "name": "RTX 4080 SUPER", "utilization_pct": 0, "vram_used_pct": 0,
     "temperature_c": 29, "display_active": false, "models": []},
    {"index": 1, "name": "RTX 4070", "utilization_pct": 9, "vram_used_pct": 13.8,
     "temperature_c": 49, "display_active": true, "models": []}
  ],
  "inference": [],
  "actions": {"pause": "disabled_no_owned_runtime", "stop": "disabled_no_owned_runtime", "unload": "disabled_no_owned_runtime"}
}
```

The example is illustrative. Values must come from live sensors and runtime metadata; stale or unsupported fields remain explicit `null`/`UNKNOWN`.

## Runtime adapters

Start with one owned NVIDIA runtime adapter. It should combine `nvidia-smi`/driver telemetry with the runtime's own model/process status, because GPU memory alone cannot identify a model. Add adapters only after the first slice is stable:

- NVIDIA: `nvidia-smi` plus the specific LLM runtime's process/model API.
- AMD: `amdsmi`/ROCm telemetry where supported; mark unsupported sensor fields clearly.
- Generic fallback: host RAM/CPU only, with GPU/model mapping unavailable.

No runtime is automatically started, loaded, unloaded, or reconfigured by telemetry discovery.

## Safety and lifecycle rules

- Read-back is mandatory after every action: target PID/creation identity, runtime state, model state, VRAM change, and action receipt.
- A failed or uncertain stop/unload is `UNCERTAIN`, not `success`; do not retry blindly.
- Pause is runtime-specific. If unsupported, show `unsupported` rather than suspending a process at the OS level.
- Unload must not terminate the display driver, desktop compositor, Mesh, Hermes, Telegram, or unrelated GPU applications.
- Emergency stop, if later requested, is a separately approved control with a named runtime allowlist and an explicit confirmation boundary.
- The dashboard must not imply that `0 MiB` means no display reservation or that a desktop process is model inference.

## Acceptance tests before implementation reaches the real PC

1. Synthetic sensor payload with fresh, stale, missing, and impossible readings.
2. Two-GPU fixture distinguishing display activity from model compute.
3. Model-to-GPU mapping fixture with one model, split model, no mapping, and conflicting runtime data.
4. Wrong PID, recycled PID, wrong creation time, wrong executable, wrong cwd, and wrong runtime all refuse actions.
5. Pause/stop/unload fake runtime proves proposal, authorization, execution, read-back, and receipt ordering.
6. Failed response and timeout remain `UNCERTAIN` without blind replay.
7. No broad process kill, public listener, credential read, prompt read, Mind/Relay write, or external telemetry success.
8. Restart/reconnect preserves the dashboard's safe disabled state until ownership is revalidated.
9. Real read-only inventory on the PC is compared with `nvidia-smi`; no mutation or model load occurs during the first deployment check.

## Decisions for the build phase

1. Which current runtime(s) are allowed to expose Pause, Stop, and Unload?
2. Should ordinary Stop/Unload require a confirmation dialog, or may Eddie grant a short emergency-stop lease?
3. Is the tab display-only for the first release, with controls deferred until the read-only telemetry slice passes?
4. Which Mesh private route and supervisor own the collector, and what is the rollback command?
5. Should the dashboard retain a short redacted history of samples, or show current state only?

## Explicit exclusions

No live Mind connection, model serving, model loading, production-memory access, Relay outbox mutation, public networking, BIOS/OS changes, driver changes, automatic reboot, or broad process cleanup belongs in this slice.
