# Single functional M4 review

No concrete blocker reproduced in the real Relay message → canonical Workroom task → reconnect → both-process restart path, or its necessary admission/data-safety boundaries. Owner phone acceptance remains **pending**. No product fixes or further jobs dispatched.

Reviewed `243e0d6..3da3025`, GOAL.md and SUPERVISION.md. Checkout HEAD is `f8c467bb3aea485f370312a1600e7be61d05e182`; scoped product/test/package bytes equal 3da3025. Reviewed the bridge, canonical transaction/migration, admission routes, native Relay adapter/UI, and phone inspection changes. No m5-nodes worktree inspection. Repo/doc MCP resolution returned unindexed; narrow current-source reads were sufficient for this bounded diff.

## Local coverage

| Command | Actual result |
| --- | --- |
| `npm test` | Exit 0; 30+1 passed; zero skips/failures |
| `node --test --test-timeout=20000 test/m4-link-store.test.mjs test/m4-link-ui.test.mjs test/m4-link-http.test.mjs` | Exit 0; six passed; zero skips/failures |
| `node --test --test-timeout=60000 test/app03-review-m4-browser.mjs` | Exit 0; one functional browser check passed |
| `git diff --check` | Exit 0 |

Logs: [checks](test/app03-review-m4-checks/). Fixed confined Python dependencies were already present; no installation, network setup or sandbox bypass was needed.

The named suite exercised actual copied Relay HTTP/SQLite/native processes, five concurrent same-message retries, changed-text refusal, canonical-commit/Relay-reference-write failure and read-only recovery, reconnect, and both-process restart on the original port/store. Canonical task `32155765-1945-4db0-b551-fa309a126a08` remained unique. Denied unadmitted/CSRF/origin/direct-Relay/control/configuration/command-field requests left no task/execution. Transaction failure rolled back task creation; version-4 migration preserved the existing task. Relay retained transcript/reference only; no proposal, decision, execution or outbox entry.

Independent Chromium 390×844 used the actual admitted native HTML, ordinary page scrolling, native Send and native task link. Message `8579baed-b28b-4771-bc51-8597bc8f85fd` created task `538e9a4c-cf05-44d2-8d01-1f010d86e6e7`. That task survived reconnect and both-process restart at `http://127.0.0.1:62905`, followed by fresh session admission. SQLite confirmed one task/transcript/reference and zero proposals/decisions/executions/outbox. Inspection and result headings received focus within the viewport; the fresh task honestly showed Not run. Logout cleared task/reference/native-frame data. No JavaScript page exceptions. Console observations are listed below, not reported as zero errors. [Browser proof](test/app03-review-m4-browser-0eb6ac1e-465d-40e4-9257-af8cd3635e10/browser-proof.json).

## Short stabilization list

1. **Native handoff leaves the saved-task list stale.** Reproduce: admit a fresh empty board, open native Relay, send, click its Mesh task link. Expected: the new canonical task also appears in Saved tasks. Actual: editor shows the correct task, but the list has zero buttons until Refresh; Refresh then supplies its selectable row. Evidence: final browser proof and `native-handoff.json`; handler at public/app.js:454–461 selects without loading the board. Nonblocking: canonical task is visible and editable, and Refresh resolves the list. Scoped later job: refresh the task list during native handoff while retaining session-generation checks.
2. **Native rendering emits blocked inline-style CSP messages.** Same send/handoff path produced four console messages beginning “Applying inline style violates”; no page exceptions or broken linkage. Expected: native rendering uses styles permitted by the existing CSP. Actual: style attributes are blocked. Evidence: final `pre-restart-console.json`/browser proof. Scoped later styling/stabilization job: reconcile native templates with permitted styles without weakening admission or CSP. Two subsequent 401 console entries were expected stale-session refusal after deliberate server restart; fresh admission recovered normally.

Existing BUGS.md cold-start, incomplete native JobObject process-list and disposable preparation-gate observations remain stabilization items; not re-audited or elevated into M4 blockers.

## Limits and process closure

**NOT_RUN:** physical phone/Eddie acceptance, owner's current cached PWA bytes, new owner-data mutation/cancellation, and fresh laptop/Tailscale acceptance. Accessible parent-browser/deploy-browser JSON receipts were read as corroboration only: parent Relay task `89061908-e88c-4210-b193-200672132ac4`, owner task `0c15d341-d506-44b7-a8af-07b53eba6579`, with owner acceptance pending. They do not substitute for Eddie's check. Styling and unrelated adversarial/runner/custody reviews were outside scope.

Retained browser iterations document a corrected Windows ESM import, initial pointer attempts before scrolling the outer page, stale-board observation, console classification, and a corrected asynchronous logout wait. Final pointer send/link passed after ordinary scrolling; no product change or synthetic DOM click was used.

Only owned disposable fixture ChildProcesses/pipes and the owned headless Chromium session were closed. [Process inventory](test/app03-review-m4-checks/process-inventory.json) records PID, creation FILETIME, executable, launch argv/purpose, original-handle exit evidence and final presence checks for 28 receipt entries, including duplicate observations of the same Mesh process. Every recorded native handle was exit-signaled; none of those original identities remained. Final browser identities: Mesh 3333052/create134355537383658319 → 3785844/create134355537439227613; Relay 2172688/create134355537384438578 → 767212/create134355537429075507 → 2328212/create134355537439891146; Chromium 1716664/create134355537393931345. Mesh fixture stops exited 1; Relay and Chromium exited 0. Exact executables/argv are retained in inventory, fixture logs and chrome-launch.json.

First pointer-timeout attempt lacked pre-acquired native handles for Mesh418380/Relay1030084; both PIDs were absent on the final targeted check, with that narrower evidence recorded separately in `early-browser-cleanup.json`. No additional stop was attempted. Helpers exited through their owned ChildProcess lifecycle. Protected existing Mesh shell at loopback4317 returned HTTP200; serving Mesh/Relay/gateways/manual work/pending dispatchers were not stopped or changed. Disposable stores/logs retained; no deletion, shared Git write, push, Actions, credentials, global settings or exposure change.
