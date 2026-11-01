# Mesh proactive contact and notifications — requested next capability

Status: owner approved enabling the generic-content Web Push architecture and proactive contact. Implementation and device permission remain pending; nothing is live yet.

Binding owner caveat: only Echo may initiate contact, and only to Eddie. No Cyony, Tripp, builders, auditors, other agents or other recipients get publishing/notification authority. Enforce the author/recipient boundary at the backend, not just in UI labels. Proactive contact is messaging; it does not automatically start project work.

## Owner request

Echo should be able to initiate contact in Relay without Eddie sending a message first. A phone notification should appear in the system notification area, with a Mesh/message icon where the phone supports it.

After Echo is genuinely idle for roughly 2–3 hours and unfinished projects exist, present a question with:
1. Take a break — snooze another 4 hours.
2. Work on project A.
3. Work on project B.
4. Custom response.

## Proposed implementation boundaries

- Persist an authentic Echo-originated message/question, attributed to Echo and bound to the authorized Eddie/Echo room; do not manufacture a user prompt or edit native message provenance.
- Deliver room changes to open clients using the accepted HTTP-action/SSE-event architecture with durable replay.
- Use opt-in browser Web Push plus service-worker notifications for a sleeping/closed PWA. SSE alone does not provide this.
- Request notification permission from a deliberate Settings action. Browser/OS control notification icon appearance, badges, sounds and action counts. Show all four choices in Relay; notification can open the question, with an optional snooze shortcut where supported.
- Keep the full question, project details and response authority on the private Tailscale backend. Proposed push contents: generic 'Echo has a question for you', without project names or approval secrets. Standard Web Push still involves the browser vendor's push service and outbound internet; this is not a purely tailnet-only notification channel. Require owner acceptance of that architecture before enabling external push.
- Schedule on the authoritative PC/backend, not a multi-hour browser/service-worker timer. The current PC must be awake to generate/send contact. Tailscale is needed to open Relay and answer; opening a notification does not itself approve or start work.
- Define genuine idle across active execution and supervision; suppress routine idle nudges while workers/projects are already progressing or no actionable unfinished project exists. Quiet hours and snooze should be durable and configurable.
- One outstanding nudge, deduplicated delivery, stable question/action IDs, and idempotent answers. Expired or stale project choices must not dispatch work.
- Choosing a project selects work within its existing authorization; it is not blanket approval for spending, OS/security changes or deletion. Custom response remains free text.

## Acceptance sequence

1. Echo sends one harmless real proactive message; it appears on the open phone without a user message or refresh.
2. Explicitly enable notifications and receive one labeled test with the phone app backgrounded/closed; tap returns to the exact question.
3. Verify snooze and all four in-app choices against durable state without launching owner projects during testing.
4. Simulate a due idle question using isolated state before enabling a real idle-contact schedule. Verify no duplicate nudge, no unanswered-choice auto-start, busy suppression and quiet hours.

Reference: https://developer.mozilla.org/en-US/docs/Web/Progressive_web_apps/Guides/Offline_and_background_operation
