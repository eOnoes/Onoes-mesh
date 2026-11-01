# Build supervision and leftover-process closure

## Delivery order
Functional application first; stabilization next; owner-directed terminal styling last. Cleanup is routine build hygiene, not a new feature, runner redesign or reason to idle productive builders.

## Cadence
- Inspect owned build-process leftovers every **15 minutes** while this project is being supervised.
- A completed/failed/cancelled job gets a **10-minute grace period** before leftover termination is considered.
- Repeat the check at every milestone closure and **15 minutes after final build closure**. Retire the project-specific recurring sweep after that final verified check; retain this flow for future builds.
- Live builders, valid long jobs and completion dispatchers awaiting acknowledgment are not leftovers. `RUN.json` ending or an empty window alone is insufficient.

## Ownership and protection
1. At launches and periodic checks, record job-bound process ownership: PID, creation time, executable, exact argv (or its hash if argv contains secrets), purpose and parent/descendant relationship. Store non-secret receipts under `.runner/process-cleanup/`. Distinguish Windows Python redirector wrappers from their native children.
2. Preserve active Codex workers, pending completion delivery, Mesh's serving PID and its children, Hermes gateways/supervisor, shared MCP/services, manual terminals/browsers and unrelated projects. Do not kill by a name, matching title, port alone or guessed stale PID.
3. Eligible cleanup requires a finished current job, elapsed grace, an independently handled matching end/commit receipt, successful completion delivery where applicable, positive retained ownership, and no active/shared/manual use. If any proof is missing, record `unresolved` and leave the process running.
4. Immediately before termination re-read PID, creation time, executable and argv against the receipt; PID reuse or mismatch means leave untouched. Use an exact retained process object/handle where available. Terminate only the owned eligible leaf/tree, never a broad Python/Node/Codex/Windows Terminal kill or deletion of lock files.
5. Wait a bounded interval, then use an exact-identity force stop only if the same approved process survives. Verify the original process object exited; wrapper exit is not proof its native child exited. Truly unkillable Windows processes stay `unresolved`, not falsely `closed`; do not reboot/change OS to clean them.
6. Record before/after identity, action, exit verification and protected-service checks. Preserve sources, worktrees, logs, databases, credentials and historical accounting. This authorizes process cleanup, not file/data deletion.

## Project flow
Launch with verified non-focus-stealing behavior → build → verify/merge → deliver completion acknowledgment → grace period → owned-leftover sweep → verify absence and protected app health → next milestone. Product work continues while independent eligible cleanup happens.

The existing Mesh manager reads the cleanup receipts each turn. A separate scoped `Mesh owned-process cleanup` cron runs the fifteen-minute hygiene check without launching builders or replacing the manager. Normal checks stay quiet/local; confirmed cleanup failures or identity uncertainty are recorded for the manager, and actual owner-decision blockers are escalated.

## Future builds
Copy this process-closure step into the next project's handoff and supervision instructions. Keep the same default cadence unless the project's actual runtime needs another recorded choice. Every builder brief names its owned temporary services/processes and requires a cleanup receipt; no blanket machine-wide zombie sweeps.
