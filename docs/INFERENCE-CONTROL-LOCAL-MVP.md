# Mesh local inference MVP — 48 to 72 hour slice

**Purpose:** get Eddie and Echo using one real local model on the PC before adding phone access or a runtime marketplace.

**Scope status:** proposal. No runtime is started and no model is loaded by this document. The existing milestone list is unchanged.

## MVP definition

A local Mesh tab can:

1. Show honest PC/runtime status with timestamps.
2. Propose and explicitly authorize loading one fixed approved model profile.
3. Start exactly one owned runtime through a fixed launch profile.
4. Prove readiness by health/read-back, not by process existence alone.
5. Provide a local session chat while that runtime is proven `RUNNING`.
6. Show basic live CPU/RAM/GPU/VRAM/runtime telemetry.
7. Explicitly Stop/Unload the owned runtime and verify process exit and state transition.
8. Fail closed on timeout, wrong PID, stale telemetry, changed executable, ambiguous model/GPU mapping, or uncertain shutdown.

## First lane

Use the existing llama.cpp CUDA build first because it explicitly accepts GGUF and exposes the detected RTX 4080 SUPER. Use the verified Qwen3.8-Flash-Next UD-Q6_K_XL profile as a fixed allowlisted model. Do not expose llama.cpp directly; bind it to loopback and proxy only the minimum chat/health calls through Mesh.

Strata remains a second adapter qualification, not a dependency for the first usable local result. Its own Qwen3.8 model/profile and Windows launch/API contract must be proven separately; do not assume the llama.cpp UD-Q6 files are interchangeable.

## Audit constraints folded into the MVP

- Mesh server owns the runtime child; the browser never spawns or kills it.
- One active runtime and one in-flight Load/Stop/Unload operation at a time.
- Load/Stop/Unload require a non-skippable server-side confirmation and the existing session, Origin, Host, and CSRF guards.
- Runtime identity is PID + creation time + exact executable + argv hash. Ambiguity disables controls.
- Readiness requires a real bounded runtime health response and GPU attribution; process existence alone is insufficient.
- The existing 4 KiB POST cap and short general UI request timeout must not be weakened globally. Chat gets a separate bounded request path and returns `UNKNOWN` on timeout or abort.
- Session-only means no prompt/response SQLite rows, no prompt logging, and a tested empty history after a new session/tab admission.
- The first real model load is a separate hardware-impacting gate; discovery and fixture work do not start it automatically.

## Minimal state machine

`STOPPED → PROPOSED → AUTHORIZED → STARTING → RUNNING`

Terminal alternatives:

- `START_FAILED`
- `UNCERTAIN`
- `STOPPING → STOPPED`

No automatic retry. `UNCERTAIN` requires a fresh observation and a deliberate owner decision; it never enables a new start or assumes the old process is gone.

## Reuse instead of rebuilding

- Existing Mesh session, Host/Origin/CSRF checks, and explicit admission.
- Existing proposal/approve/deny/cancel task flow and SQLite receipt pattern.
- Existing owned-process identity model: PID, creation time, executable, argv/cwd evidence, and protected-process rules.
- Existing PWA layout and approved Health First visual direction.
- Existing private loopback/Tailscale deployment without changing its route for the local MVP.

## Do not build in this slice

- Phone UI or phone-specific sync.
- Public/Funnel exposure.
- Arbitrary model picker or arbitrary launch parameters.
- Multi-runtime selector in the user-facing UI.
- Multi-GPU optimizer or automatic tensor-split tuning.
- Durable prompt/response history.
- Prometheus, long-term dashboards, forecasting, or fleet/node orchestration.
- Automatic model switching, automatic retries, or broad process cleanup.
- Strata control until its separate qualification is complete.

## Minimal endpoints/operations

- `GET /api/inference/status`: current state, freshness, fixed profile, runtime identity, health, and telemetry; read-only.
- `POST /api/inference/propose-load`: creates a fixed-profile proposal; browser cannot supply executable/model/argv/path.
- `POST /api/inference/approve-load`: explicit authorization; starts only the fixed profile through the owner bridge.
- `POST /api/inference/chat`: session-only prompt/response proxy, allowed only while `RUNNING`; bounded body, timeout, and output size.
- `POST /api/inference/stop`: explicit authorization; stops only the positively identified owned runtime.
- `GET /api/inference/receipt/:id`: redacted lifecycle receipt; no prompt or response content.

Exact endpoint names may follow the existing Mesh route conventions; the security properties are mandatory.

## Acceptance gate

The local MVP is usable when, from the PC browser and a stopped starting state:

- Mesh shows `STOPPED` and real freshness metadata.
- Eddie presses Load, sees the exact fixed profile proposal, and authorizes it.
- The runtime starts with the approved GGUF profile and the UI reaches `RUNNING` only after health/read-back succeeds.
- A prompt returns a local response through Mesh.
- CPU/RAM/GPU/VRAM/runtime identity visibly update from real probes or say `UNKNOWN`/`UNAVAILABLE`.
- Stop/Unload requires explicit confirmation, returns a receipt, and verifies the owned process is gone.
- A forced startup failure, stale probe, wrong PID, or uncertain shutdown leaves controls disabled and does not fabricate `STOPPED` or `RUNNING`.
- Existing `npm test` and the actual local-start proof remain green.

Phone access becomes a thin second client after this gate: reuse the same authenticated Mesh route and API, without adding phone-specific runtime logic.
[H[2J[3J