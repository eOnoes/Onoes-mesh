# Project leads and delegated teams

Eddie's selected direction (2026-11-06): new tasks start with Nims (Codex) or Echo
as lead. The lead clarifies the request using applicable preference MD files and
current app conventions, settles scope/spec with Eddie, then chooses the right
builder, auditor and independent reviewer. Keep this flow small and reuse the
existing Workroom task/send/report/review store.

## Available now

Creation saves Nims/Echo in the existing owner field, atomically with the task.
The editor and unassigned-move prompt offer the same two leads. Historical other
owners are retained; editing preserves their current value unless deliberately
changed. This is project responsibility, separate from the worker/reviewer IDs.
No worker starts at creation, assignment or board movement.

Echo's explicit planning action targets Echo's current Relay conversation and
freezes policy mesh-lead/v1 into the existing send receipt. It requests actual
preference/document sources, missing scope questions, a small pending checklist,
acceptance checks and suggested downstream roles. It must not claim those
sources were read if unavailable or start other agents during planning.

Nims now has a task-scoped Codex app-server connector for read-only planning and review, using the existing ChatGPT sign-in. It is a separate worker thread with the supplied brief/preferences, not this desktop conversation. Mesh refuses Nims-led planning sends to another peer.
Accepted historical sends and same-identity recovery remain preserved.

## Scope lock and team proposal â€” available 2026-11-06

New lead-managed cards enroll in a draft plan. The collapsible Plan, scope and team
panel saves spec, workspace, allowed files, checks, boundaries and a distinct
builder/reviewer. Lock scope and team is an explicit admitted owner action; it does
not dispatch or approve completed work. Connected peers are validated at lock;
actual tool/repository qualification and dispatch permissions remain separate.

Changing brief, goal, checklist wording or lead makes the lock stale. Checklist
status/result updates alone preserve it. Work/review handoffs bind the exact plan
revision and chosen roles under the existing reservation transaction, freeze scope
into the payload, and reject stale uncertain retries. Accepted receipts stay
immutable. A re-lock requires fresh worker provenance; old reports/reviews cannot
approve a new plan. Planning reports may still populate a draft checklist before
locking. Unchanged legacy cards keep their existing workflow; saving their first
proposal deliberately enrolls them. SQLite backup verification includes plan rows.

## Qualified automatic lane — 2026-11-06

The lead can return a source-bound structured assignment proposal. Use proposed
scope and team saves a draft only. Eddie reviews it, locks scope, then explicitly
starts the scoped team. Creating/locking a card never dispatches work.

Automatic execution is currently qualified only for this Mesh workspace, with
Echo as builder and DeepSeek or Nims as independent reviewer. It applies a
completed worker report, sends one review, and stops at Needs review. It never
applies approval or moves the card to Done. Nims cannot be the coding worker.

Only one team/writer runs at a time. Blocked reports, uncertain delivery, stale
scope, missing peers, timeout or restart pause progression. Resume is explicit
and preserves send identities; close retains the previous attempt's receipts.
There is no automatic repair loop. The 50-operation cap bounds controller
transitions, not every tool invocation inside another agent.

This adds no API key, public port or expanded permissions. Codex runs hidden,
read-only, and declines tool approval requests. Existing session admission and
handoff provenance remain required. Local inference profiles, other workspaces,
broad parallel teams and cross-channel memory remain unqualified/deferred.
