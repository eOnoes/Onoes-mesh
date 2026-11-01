# Inference-control panel — design review

**Status:** visual direction approved by Eddie; design-only mockup; no live implementation or control authority.
**Mockup:** `docs/inference-control-panel-mockups.html`

## Approved visual direction

Use the mockup's terminal-ops language: dark near-black background, monospace typography, thin square-edged borders, compact metric blocks, muted secondary text, and semantic green/amber/red status labels. Keep the safety posture visible above the data. Use bracketed/all-caps state labels where they improve scanning, but pair every color with text for accessibility. On mobile, stack cards vertically and keep the host-freshness and safety blocks first.

The current live Mesh Inference tab remains synthetic/read-only until real telemetry and ownership evidence exist. Do not replace honest `SYNTHETIC`, `UNKNOWN`, or `UNAVAILABLE` states with illustrative hardware values.

## Decision proposal

Use a hybrid rather than choosing one version wholesale:

- **Visual shell from the newer syntax-heavy version:** monospace, square borders, `//`/`>`/`[STATE]` labels, compact ops language, and semantic status colors. This fits Mesh and makes evidence states unmistakable.
- **Readability from the earlier card layout:** more breathing room, larger primary values, short explanatory notes, and responsive stacking. This keeps the phone view usable.
- **Product structure:** Option A is the landing view; Option B is the drill-down for an ownership-verified runtime; Option C is deferred until the mixed-GPU/multi-node case is real.

That gives us the strongest identity without making the phone panel feel like a compressed terminal dump.


Use a mobile-first single scroll:

1. Freshness and host status.
2. CPU, RAM and GPU health cards.
3. Inference inventory as the first place a model appears.
4. Scoped action row, disabled until ownership and mapping are proven.
5. Safety sequence and read-back receipt language.

This matches the existing Mesh tab family, makes stale/unknown state visible before any action, and works when no model is loaded.

## Alternatives

- **Option B — Operator card first:** best when one owned runtime is active; puts model identity and actions above telemetry. Risk: a user may over-focus on the model card before checking freshness and host health.
- **Option C — Nodes and runtime lanes:** best for the future mixed NVIDIA/AMD box and multiple runtimes; makes ownership boundaries clear. Risk: too abstract for the first local slice.

## Non-negotiable display rules

- `UNKNOWN`, `STALE`, and `GPU_MAPPING_UNKNOWN` are explicit states, not blank values.
- Display GPU activity is labeled separately from model compute.
- VRAM use alone never identifies a model.
- Controls stay disabled when runtime, PID/creation identity, target model, or GPU mapping is ambiguous.
- Pause means runtime-supported admission drain; it is never generic OS suspension.
- Every action is shown as proposal → authorization → execute → read-back → receipt.

## Eddie approval questions

1. Approve Option A for the first implementation slice, or choose Option B/C?
2. Keep the first release display-only until live telemetry and ownership checks pass?
3. Require confirmation for Stop and LLM Unload even after ownership is proven?
4. Start with the current owned NVIDIA adapter or generic host-only telemetry?
5. Show current state only, or retain a short redacted sample history?

## Scope boundary

No route changes, public bind, Tailscale changes, model loading, runtime startup, Mind/Relay linkage, credentials, prompt content, or broad process control are included.
