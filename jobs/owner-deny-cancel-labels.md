# Owner feedback — Deny versus cancellation/cleanup labels

Status: NEXT dependency-ready narrow functional UI repair after verified fix-relay-saved-list-retry merge ee6f389. Working M1–M6 assembly/single reviews are retained; this repairs the concrete owner confusion, not cosmetics. Native gpt-6.1-sol/high workspace-write idle900/wall14400 via existing tools/mesh_dispatch.py. Read GOAL.md and SUPERVISION.md. Allowed: necessary public/app.js/public/index.html label/explanation changes; new focused test/owner-deny-cancel*.mjs and optional exact stale expectation in existing UI test only if reproduced. Append-only JOB.md/DECISIONS.md. No server/store/lib/Relay/config/styles/auth/runner/GOAL/review changes; disjoint fix-owned-cleanup-list owns lib/owned_job.py. Do not stage generated evidence/dependencies or directories; host owns source-only shared-Git commit. Use existing native JSONL and durable JOB.md/BLOCKED.md handoff/completion notification contract; no A2A/framework setup.

Owner: 'Done, I was not able to confirm the cancellation/cleanup but I did deny it. Maybe there is a button label name issue I am missing?'

Verified against current private Mesh origin and read-only live SQLite:
- Task Test for Echo, id0c15d341-d506-44b7-a8af-07b53eba6579.
- Stored proposal decision is denied with executionId null; no execution was created for that denied proposal.
- Current inspection says 'Denied · no executor invoked and no execution record created for this proposal' and 'Not run. No process result exists for this proposal.'
- Earlier separate runs preserve cancelled=true and cleanupVerified=true; do NOT present them as evidence this latest denial cancelled a run.
- UI labels are bare Approve / Deny / Cancel. Cancel is disabled unless a run is active. Slow whitelisted command is node lib/slow-command.mjs.

Next narrow UI repair when current UI lane is free:
- Label Deny as 'Deny proposal (do not run)' and Cancel as 'Cancel running command' or equally clear text.
- Explain that denial occurs before execution, so cancellation/process cleanup is not applicable.
- For completed cancellation, visibly distinguish 'Cancelled — cleanup verified' from cleanup pending/unknown. No positive cleanup claim unless actual stored evidence says true.
- Preserve existing API/authorization semantics; labels and adjacent functional explanation only, no styling redesign or additional framework.
- Verify pending -> denied (no run) and active -> cancel -> actual result visibility in phone viewport using disposable data, preserving owner's task.

Required checks: npm test; relevant current privacy/decision/cancel UI tests; actual Chromium390x844 create -> propose benign whitelist -> deny -> visible explicit no-run/no-cleanup-applicable state and zero execution, then separate controlled slow command -> approve -> Cancel running command -> actual cancellation/cleanup result -> inspect/reload. No passing API/mock-only substitute; stored cleanup false/unknown must stay honest. Playwright core C:/Users/eMitchell109/AppData/Local/hermes/hermes-agent/node_modules/playwright-core/index.mjs; Chromium C:/Users/eMitchell109/AppData/Local/ms-playwright/chromium-1243/chrome-win64/chrome.exe. Existing owner-inspect-browser helper may be reused after screening imports, but avoid browser-cache02/external baseline suites (read forbidden archive). Screen checks before invoking; never read D:/tmp/archive. No aesthetic/style/CSP repair.
Retain PID/create/exe/argv/purpose/ancestry and original native exit cleanup receipts for every owned temporary browser/app/execution/helper; verify native child windows are hidden, never assume Windows venv wrapper hides its child. No deployment restart/owner DB mutation/owner command replay/protected Mesh4317/private8446/Relay stop, file/DB/lock deletion, OS/cloud/money/credentials/public exposure/push/Actions. Host handles private preserving-data deployment. Real check failure => one exact BLOCKED.md line and retained handoff; no scope expansion or dispatch. Do not claim owner's physical phone acceptance.
