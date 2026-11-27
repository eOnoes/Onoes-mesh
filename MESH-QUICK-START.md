# Mesh quick start: Relay and Mind

Hi Eddie — today's priority is Relay and Mind, using your phone or Echo's PC. Relay and Mind use the existing private address on port 8453.

Relay is at https://emitchell.tail8c4a75.ts.net:8453/#relay. Messages to and replies from Echo, plus history, have been verified to work and to survive a page reload. Quick check: open the Relay link, send Echo a short message, then reload the page and confirm both sides of the exchange are still there. Nims chats in the existing native project-chat panel inside Relay; that chat is a separate conversation from Echo, so do not expect the two threads to merge.

Mind is at https://emitchell.tail8c4a75.ts.net:8453/#mind. Use the two buttons there: "Check memory connection" confirms Mind can be reached, and "Read matching memories" shows what it can recall. Nims's current shared handoff can be retrieved by Echo with its author, source, revision and next action. Agent-private memory stays separate from deliberately shared project context — sharing is a deliberate act, not automatic.

Phone verification passed for the tested Cyony connection, including its expected host and account. That check did not enroll Cyony into Mind — Cyony's Mind enrollment is not active, so do not assume a generic Tailscale sign-in approves any connection. Workroom, Rook and Inference are parked; nothing there needs your attention today. Do not paste passwords or verification codes into chat. The Workroom guide below is historical — read it for reference only, and do not start teams from it.

# Mesh quick start: phone acceptance

Open the current private Workroom at https://emitchell.tail8c4a75.ts.net:8453/#workroom. Use port 8453 for this Workroom; the older 8446 installation and its data are separate. Workroom is a private release candidate, not whole-app production acceptance.

Open the [running Mesh checklist](https://emitchell.tail8c4a75.ts.net:8453/#task=c2a77ea9-05bb-4b63-85c7-c2d8e9fb2547) to see each milestone and what still needs attention. From the board, tap **Finish Onoes-Mesh — all assessed stages** to open the same card.

## Make and shape a task

1. Tap “+ New task.” Enter a short title and description, choose Nims or Echo as project lead, then tap “Create task.” If prompted, tap “Start fresh local session”; previously saved tasks remain available, but an unsaved editor draft is not restored. In the task card, use “Edit card” to set the Project, Goal, Acceptance criteria and Project lead. In “Goal, checklist and review,” add a few small checklist steps and tap “Save changes.” A checklist is a progress aid, not proof of approval.
2. To open a task, tap it once. On a phone, hold briefly on the card and drag to move it; swipe without holding to scroll. Dragging changes the board stage only—it does not start an agent. “Done” is both a board stage and a checklist status: marking a checklist step Done does not approve or finish the task; moving the board stage to Done requires a recorded approved review and your deliberate action.
3. A project lead can ask for a plan without edits. Read the proposed workspace, allowed files and checks before using the proposed scope/team. Lock the plan only after the scope matches what you intend. For this task, verify the locked assignment names Echo as builder and Nims as the read-only independent reviewer. Available workers depend on connected, qualified adapters; if either assignment is missing or differs, do not start—report the mismatch rather than substitute. The lane is one build followed by one review; it does not automatically retry or rework. Starting it is an explicit action: tap “Start scoped team.” Planning, saving a card or locking scope does not start work.

## Follow and review work

Open the card to see “Agent-reported updates”; “Independent review” appears once a review is available. “Work timeline,” “Conversation and history,” and “Team handoffs” show the handoff trail and task activity. “Refresh agent replies” checks for saved replies; while the card is open, “Follow agent replies while this card is open” can follow them. An accepted handoff means the message was queued, not that work is complete.

Read a report and its result/evidence before choosing “Apply update to checklist.” Applying a report is not approval. Inspect the independent review and use “Record this review” to record it. If the review requests changes, keep the task open for correction and a fresh review. Mark the board stage “Done” only after an approved review is recorded and you deliberately choose Done. Completed checklist steps alone never approve or finish a task.

If a DeepSeek handoff is waiting on permission, open “DeepSeek permissions,” tap “Check DeepSeek approval,” and inspect the exact tool and arguments. “Allow this tool once” is limited to that request; “Deny this request” refuses it. Do not treat a missing permission panel or an accepted handoff as permission granted.

## Save, refresh and protect your work

Use “Refresh board” or reload the page, reopen the task and confirm saved changes, reports and review history are still there. Check the page’s available theme modes for readable text and controls; theme appearance does not verify task state.

Confirmed recovery cases include switching to another phone app, then reopening the completed card successfully; keeping an unsaved draft and keyboard usable through landscape/back; and reconnecting after network loss without saving or sending offline. A separate isolated-browser expiry check rejected a stale save, cleared private page data, then restored the original saved task after fresh admission. Fresh admission restores saved state, not unsaved drafts. These checks do not establish offline-send support or what happens if radio loss interrupts a native agent run.

If another edit makes the open editor stale, Save may be rejected with “Task changed.” The unsaved field stays visible. Copy any draft you want to keep before tapping “Cancel edits”; reopen the card to see the other saved changes. Some card details may already have saved before a later progress conflict. There is no silent merge.

Backups are manual or milestone-based; no automatic schedule or off-device backup is enabled. The documented backup writes to E:\App-Backups\ONOes-Mesh; check LATEST.txt for the verified matching source/data snapshot. Keep labelled milestone copies. Do not merge the older 8446 store into the current Workroom store.

Current limits: the listed phone recovery cases are accepted, but whole-app owner release acceptance remains open. Main-PC Nemotron 3.5 Bolt is qualified for the tested profile, including Eddie's phone load/chat/unload check ending STOPPED. Use the [Inference tab](https://emitchell.tail8c4a75.ts.net:8453/#inference) for model controls; other models and machines are not covered by that qualification. Mind can recall deliberately shared project facts. Workroom syncs the existing Mesh goal card, and the Mind tab can retrieve its current result. The 3D Print Pilot card is private to Workroom while its connection is being prepared. Relay and Telegram still have separate conversations. Off-device backup remains deferred. Automatic assignments and production workers remain off pending legacy recovery and enrollment; the isolated scoped-team trials do not authorize starting production work. The scoped team flow pauses for owner review; it does not auto-approve or mark Done. See [remaining owner checks](NEXT-OWNER-CHECKS.md) before a new acceptance run.

## Phone workflow reference

Eddie has already passed the basic card and recovery checks. These steps explain
the workflow; they are not a request to repeat tests or start a team now. The
remaining production-team check waits for qualified enrollment.

- Open the 8453 link; create a small test task with a title, goal, project lead and checklist.
- Tap to open it; try hold-and-drag, then swipe-scroll. Confirm a move did not start an agent.
- Save a plan, check its workspace/allowed files/checks, lock it, and confirm the Echo-build/Nims-review scope before “Start scoped team.”
- Inspect the report and timeline; record the independent review. Confirm checklist completion alone does not mark Done, then deliberately set Done only if the review is approved.
- Reload and reopen the card; confirm saved details and review remain. Try the available theme modes and report any phone readability or touch issue.
