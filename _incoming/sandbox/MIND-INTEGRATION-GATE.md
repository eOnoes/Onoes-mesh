# Mesh → Mind integration gate

Status: design boundary only. Mind is **OFF** and no delivery is wired.

## Current facts

- Mesh's browser talks to the local Mesh server, not directly to the Hermes API server.
- Relay's model-facing boundary is the loopback Hermes Runs API at `127.0.0.1:8642`, with the API key kept server-side.
- Mesh keeps durable room/run correlation, paper metadata, reply links, and attachment identifiers in its local SQLite state.
- `data/relay-outbox.db` is a held lane-B test handoff. It must not be sent, marked sent, or copied to another drive until a separate Mind approval and delivery contract exist.
- Maya's lean candidate is a separate loopback HTTP model boundary. Lean mode excludes MCP, dashboard/static management, vision, and self-update paths. It must not be silently substituted for the Hermes API server.

## Required future boundary

Mind may be connected only through an explicit server-side adapter with:

1. **One named destination and protocol.** The adapter must state whether it calls the Hermes Runs API or the Maya lean HTTP API. No browser call, file watcher, or implicit fallback may choose the destination.
2. **Loopback and authentication.** Bind locally, authenticate at the server boundary, keep credentials out of HTML/JS/logs, and refuse a non-loopback or unconfigured destination.
3. **Explicit opt-in.** Mind activation must be a separate configuration/approval event. Starting Mesh, opening Relay, setting a goal, or receiving a message must not activate Mind.
4. **Typed input envelope.** Pass a bounded room-turn record with stable message IDs, explicit attachment references, and a declared instruction/data distinction. Relay text, paper, photos, model output, and tool results remain untrusted data; they do not become system/developer instructions merely because Mind receives them.
5. **Idempotent delivery.** Use a durable handoff key and read-back state. An uncertain timeout must remain `held` or `inflight`; it must never be blindly retried into a duplicate Mind turn.
6. **Output firewall.** Limit response size, redact secret-like values, reject instruction-like tool results, and keep returned model/tool content in the data plane. No returned content may modify Mesh policy, enable MCP, alter a destination, or grant permissions.
7. **Failure containment.** Mind failure must leave Relay usable and must not mutate standing goals, approvals, permanent allowlists, or the held outbox lane.
8. **Separate acceptance.** Prove the adapter against an isolated fake first, then a harmless local target. Production model execution, Maya/GLM execution, phone behavior, and Mind delivery are separate gates.

## Not yet allowed

- No `relay-outbox.db` row may be sent or marked sent.
- No Mind process or model may be started for this design step.
- No MCP server may be enabled as part of Mind integration.
- No model-generated instruction may be promoted into Mesh policy.
- No direct browser-to-Maya or browser-to-Mind route may be added.

## Next implementation slice

Before wiring Mind, implement and test only the adapter contract against an isolated local fake: input schema validation, bounded payloads, stable handoff IDs, one-way held/inflight/accepted states, duplicate refusal, sanitized read-back, and fail-closed destination checks. Keep the real outbox and Mind disabled until those tests pass and Echo reviews the exact destination/protocol choice.
