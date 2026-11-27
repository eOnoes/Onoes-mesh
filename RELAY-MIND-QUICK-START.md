# Relay + Mind Quick Start

Hi Eddie — here's the short way to use Onoes-Mesh Relay and Mind from your phone or PC.

## Getting In

- Phone (away from home): make sure Tailscale is connected first.
- At home: keep the home PC and the app running.
- Relay: https://emitchell.tail8c4a75.ts.net:8453/#relay
- Mind: https://emitchell.tail8c4a75.ts.net:8453/#mind
- Same links work on a PC.

Relay and Mind are the current focus. Workroom, Rook and Inference work is parked — skip Workroom's old trial checklist.

## Echo Chat (works today)

1. Open Relay from the menu.
2. Choose **Echo** in the Conversation agent.
3. If needed, press **Use current** to bind Echo to its current conversation.
4. Type your message and deliberately press **Send** (the arrow).
5. Your messages and ECHO replies appear separately.
6. **Refresh** re-reads the same destination; **Load older messages** keeps older history.

Opening or refreshing never submits a message. Basic Echo send, reply, history and reload are already owner-confirmed.

## Native Nims (installed; physical-phone acceptance pending)

Only if the connection is available:

1. Open the separate section **Nims · project chats** — not the Echo/Deep Conversation agent dropdown.
2. Use **Conversation** to pick a project chat, then **Refresh Nims** to read it.
3. Use **More conversations** / **Earlier messages** for paging if present.
4. When messaging is available, **Message Nims** and **Send to Nims** continue that selected chat.
5. A new chat opens **Chat title (optional)** and **Start with a message**; press **Create chat** deliberately to start it, or **Cancel** to back out.

The native Nims connection is installed in the live Relay app (port 8453). Browser checks at 390 and 1440 widths passed history, Refresh, Cancel-draft and Lock privacy; no new native message test was run. Physical-phone acceptance is still pending. Messages stay in the existing Codex project — it does not clone the project, switch to Echo, or auto-send on opening. Native permissions and approval prompts still belong to Codex desktop. If Nims isn't reachable, leave the draft as-is and use Echo or the current Codex directly — don't change destination silently.

## Mind Memory

1. Open Mind.
2. Press **Check memory connection**.
3. Type a search, then press **Read matching memories**.

An empty result means no match in permitted scopes — not proof data was deleted. Shared project context is deliberately saved; full Relay/Telegram transcripts are not automatically merged. Each enrolled agent has its own private home; this guide doesn't grant broader access or claim every agent is enrolled.

## Handoff Between Agents

You can ask Echo to read Nims's current shared handoff from Mind and report its author, revision and next action. A later update does not prove Echo already read it. The Nims→Mind→Echo read path already passed an actual bounded check.

## If Something Seems Stuck

- Refresh or reopen to read saved history. Drafts are memory-only and may be lost when access ends.
- An uncertain send is not a failed send. Don't blindly resend, create new IDs, or auto-retry. Check the message's existing delivery status; if it's still unclear, ask Nims or Echo for help with that exact message.
- No attachment support is currently promised.

## A Good First Step

Just read an existing Echo conversation or search shared Mind facts. No new task, model load, or acceptance test is required.
