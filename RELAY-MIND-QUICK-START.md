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
2. Tap the agent badge at the top right, then choose **Echo**; the picker closes.
3. The top-left menu contains current-chat/history controls; use **Use current** there if needed.
4. Type your message and deliberately press **Send** (the arrow).
5. Your messages and ECHO replies appear separately.
6. The top-left menu holds **Refresh** and **Load older messages**. Scroll up to read; the down-arrow jumps to the latest message. The composer stays at the bottom and follows keyboard viewport changes.

Opening or refreshing never submits a message. Basic Echo send, reply, history and reload are already owner-confirmed.

## Cyony Chat (phone verified)

1. In Relay, tap the top-right agent badge and choose **Cyony**.
2. If needed, use **Use current** in the top-left menu.
3. Type your message and deliberately press **Send** once.
4. Your message and Cyony's reply appear separately; reopen or reload to read saved history.

Eddie confirmed that Cyony replied and the reply stayed after closing and reloading. No repeat connection test is needed. Cyony's private Mind home is not connected yet.

## Native Nims project chats

Only if the connection is available:

1. Tap the top-right agent badge and choose **Nims**.
2. Open the top-left menu and use **Conversation** to pick a project chat; the menu closes after selection. **Refresh Nims** re-reads it.
3. Use **More conversations** / **Earlier messages** for paging if present.
4. When messaging is available, use the bottom composer and its send arrow to continue the selected chat.
5. **New chat** in the top-left menu opens **Chat title (optional)** and **Start with a message**; press **Create chat** deliberately to start it, or **Cancel** to back out.

The native Nims connection is installed in the live Relay app (port 8453). Browser checks at 390 and 1440 widths passed history, Refresh, Cancel-draft and Lock privacy; no new native message test was run. Eddie confirmed project chats work on his phone. The new messenger layout still needs his physical-phone feel/keyboard check. Messages stay in the existing Codex project — it does not clone the project, switch to Echo, or auto-send on opening. Native permissions and approval prompts still belong to Codex desktop. If Nims isn't reachable, leave the draft as-is and use Echo or the current Codex directly — don't change destination silently.

## Mind Memory

1. Open Mind; canonical memory search comes first. **Saved task context (optional)** stays collapsed unless needed.
2. Press **Check memory connection**.
3. Type a search, then press **Read matching memories**.

An empty result means no match in permitted scopes — not proof data was deleted. Shared project context is deliberately saved; full Relay/Telegram transcripts are not automatically merged. Each enrolled agent has its own private home; this guide doesn't grant broader access or claim every agent is enrolled.

## Handoff Between Agents

You can ask Echo to read Nims's current shared handoff from Mind and report its author, revision and next action. A later update does not prove Echo already read it. The Nims→Mind→Echo read path already passed an actual bounded check.

## If Something Seems Stuck

- Refresh or reopen to read saved history. Drafts are memory-only and may be lost when access ends.
- An uncertain send is not a failed send. Don't blindly resend, create new IDs, or auto-retry. Check the message's existing delivery status; if it's still unclear, ask Nims or Echo for help with that exact message.
- **Back to Mesh** in the top-left menu returns to the other tabs, including when the workspace is locked. **Lock workspace** uses the existing privacy lock.
- Nims lists its existing project chats. Other agents currently expose their selected conversation and older messages; the new layout does not promise a complete previous-chat chooser for every backend.
- No attachment support is currently promised.

## A Good First Step

Just read an existing Echo conversation or search shared Mind facts. No new task, model load, or acceptance test is required.
