# Single M6 functional review

Exact product diff `e3e4de5..35fc15a`; current product/test/config bytes match the target. Unrelated reports/docs excluded. No fixes.

1. **No reproduced M6 product defect or necessary authorization/data-safety blocker.** Standalone overrides ambient Relay enablement; actual Agent/Workroom runs without Relay/Mind/Inference/tailnet children. Flag-off boundaries, admission/Origin/CSRF/no-store, whitelist and native ownership remain covered.

Independent commands ran from the unchanged disposable copy at `test/app03-review-m6-20261003/source`:

| Command | Actual result |
| --- | --- |
| `node test/m6-standalone-checks.mjs` | Exit **1**: npm 30+1, boundaries 30, native 19 pass; M2/M3 full and standalone each 30/31. Zero skips. |
| `node test/m6-standalone-browser.mjs` | Exit **0**, actual Chromium 390x844 PASS; no page exceptions. |

Browser environment: `M6_STANDALONE_PLAYWRIGHT=C:/Users/eMitchell109/AppData/Local/hermes/hermes-agent/node_modules/playwright-core/index.mjs`, `M6_STANDALONE_CHROMIUM=C:/Users/eMitchell109/AppData/Local/ms-playwright/chromium-1243/chrome-win64/chrome.exe`. Node harnesses launched detached without a console; native assertions unchanged.

Actual npm-start browser proof stores `v24.14.0`/exit0/cleanup true; approval replay leaves launches/rows unchanged, and denial creates no launch/execution. Cancel verifies original bridge/root/descendant exits and root stdout naming both retained PIDs. Exact-server kill, same-store/URL restart, UNKNOWN recovery and replay without spawn pass. Result headings are within the viewport.

**Qualification limit:** the sole failure in each M2/M3 suite is fixed `git status` returning exit128: Git rejects repository ownership by `eMitchell109` under `CodexSandboxOffline`. Native cleanup is true. This unchanged environment restriction does not establish an M6 regression; no Git trust/sandbox changes or rerun. Authorized host receipts separately report integrated 31/31 in both modes and owner-row preservation; they do not replace this review's failed command.

Evidence: `test/app03-review-m6-20261003/{source-manifest,launch-receipt,cleanup}.json`, qualification logs, and nested `checks.json`, `native-processes.json`, `browser-proof.json`, SQLite stores/screenshots. All 526 retained identities absent; original exits recorded; three acquisition-race events disclosed without native-handle claims. No extra cleanup termination; protected loopback4317 shell HTTP200. Four authorized host receipts copied as `host-*.json`; owner task untouched.

Physical owner acceptance remains pending. Stale legacy blank-pending assertion was not rerun. No deployment, cloud, push/Actions, source changes or dispatch. Shared-Git commit remains host-owned; review ends once.
