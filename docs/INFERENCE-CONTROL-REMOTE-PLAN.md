# Mesh remote inference control — proposed build slice

**Status:** proposal; no runtime is started and no model is loaded by this document.

## Goal
From a phone on the private connection, Eddie can see live PC/inference state, explicitly request one approved model load, use a session chat for local inference, and stop/unload that owned runtime. The PC remains the execution boundary.

## Recommended boundary

```text
Phone browser
    ↓ private Tailscale/Serve Mesh session
Mesh inference tab + session chat
    ↓ authenticated, CSRF-protected action broker
Loopback-only runtime supervisor
    ↓ exact allowlisted executable/argv/cwd/model path
One owned inference runtime
    ↓
Local GGUF model
```

- Keep the existing private route; no Funnel, public bind, or new external telemetry service.
- Mesh never accepts arbitrary executable paths, model paths, argv, ports, or runtime settings from the phone.
- Start with two named runtime lanes, qualified separately: the existing llama.cpp CUDA 12.4 build for the verified UD-Q6 GGUF, and the existing Strata CUDA 12 build for Strata's own Qwen3.8 model path/API. Do not assume the same GGUF/profile is interchangeable between them.
- Keep a single Mesh adapter interface above both lanes. The phone selects an approved profile, never an executable path, model path, argv, port, or arbitrary runtime setting.
- The downloaded six-shard `Qwen3.8-Flash-Next UD-Q6_K_XL` profile is the first llama.cpp candidate. Strata compatibility remains `UNKNOWN` until its documented model setup and API are qualified.
- Default to session-only chat history; do not persist prompt/content data unless separately approved.

## Required state machine

`not_loaded → loading → loaded → running → stopping/unloading → not_loaded`

Failure and timeout states are `UNCERTAIN`, never silently retried. A recycled PID, changed creation time, changed executable, changed cwd, wrong model hash, or ambiguous GPU mapping disables controls.

## Phone workflow

1. Open private Mesh route and establish the existing local session.
2. See host health, runtime state, model profile, GPU/VRAM/temperature, process identity, and freshness.
3. Press **Load Qwen3.8 Q6**.
4. Review a proposal naming the exact model profile and expected runtime transition.
5. Explicitly authorize; the PC-owned broker starts the fixed runtime.
6. Read back process identity, runtime health, model state, GPU assignment, and VRAM change.
7. Use session chat only after `running` is proven.
8. **Stop** or **Unload** requires confirmation and the same read-back receipt.

## Telemetry to track while running

- Host CPU/RAM and freshness.
- Per-GPU temperature, hotspot/VRAM temperature where supported, utilization, power, fan state, VRAM used/total.
- Runtime PID plus creation time, executable, cwd, argv hash, start time, state, health/readiness.
- Model profile, revision/file hashes, load time, prompt/generation counters, active request, queue/admission state.
- GPU mapping only when proven by runtime evidence; otherwise `GPU_MAPPING_UNKNOWN`.
- Action receipt history with redacted metadata only; prompts and generated content stay out of telemetry by default.

## Phases

1. **Contract and fixtures:** state machine, fixed profile, ownership checks, synthetic telemetry, wrong-PID/recycled-PID tests.
2. **Read-only live collector:** host/GPU/runtime/model inventory; no process starts.
3. **Fixed load/unload broker:** one model profile, explicit authorization, read-back verification, no arbitrary settings.
4. **Phone chat:** session-only prompt/response path, bounded request size/time, runtime admission and cancellation.
5. **Controlled expansion:** additional model profiles/runtimes only after the first lane is stable.

## Decisions required before implementation

1. First adapter order: qualify llama.cpp against the verified UD-Q6 profile, then qualify Strata against its own documented Qwen3.8 lane?
2. Confirm private Tailscale-only access; no public/Funnel exposure.
3. Confirm session-only chat history with no prompt/content persistence at first.
4. Confirm explicit authorization for Load, Stop, and Unload rather than one-click actions.
5. Confirm whether one active runtime is sufficient for the first release, while keeping both runtime lanes available.

## Hard exclusions

No arbitrary phone-supplied commands or paths, public exposure, credentials in browser payloads, prompt logging by default, broad process killing, automatic model switching, automatic retry after uncertain outcomes, or control of unrelated GPU/display processes.
