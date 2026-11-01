# Single M5 functional review — 2026-10-03 (America/Chicago)

Done: No concrete reproduced blocker in the fixed PC/laptop cached Tailscale Online -> authenticated API -> 390x844 Inference-card path, or its necessary authorization/private-data safety. This is one report-only review of f8c467b..9a02254. No source fix or further dispatch.

Scope: M5 changes in server.mjs, public/app.js and public/index.html, with their M5 API/browser fixtures and privacy regression. lib/node-probes.mjs is unchanged dependency context, not a new diff finding. Current worktree HEAD592d5b0 has no differences from9a02254 in lib/public/config/test/package/server. Unrelated M4 report artifacts and the M6 worktree were not reviewed. Read GOAL.md, SUPERVISION.md and BUGS.md; this prompt controls report-only scope, closed M0, paused cloud and pending owner acceptance. Styling remains deferred.

Findings: None reproduced. No new numbered stabilization items are warranted by this bounded review. Existing BUGS.md observations remain outside this M5 diff and were not changed.

Checks (all local; final runs have zero failures/skips):

| Exact command | Result | Retained logs |
| --- | --- | --- |
| npm test | Exit0;30/30 plus npm-start1/1 | test/app03-review-m5-checks/npm.{stdout,stderr}.log |
| node --test --test-timeout=20000 test/m5-node-probes.test.mjs test/m5-nodes-api.test.mjs test/privacy01.test.mjs | Exit0;34/34 | test/app03-review-m5-checks/focused.{stdout,stderr}.log |
| node test/m5-nodes-browser.mjs | Exit0; real Chromium390x844 native API-to-DOM equality, controlled aging and delayed private clearance | test/app03-review-m5-checks/browser.{stdout,stderr}.log |

Browser environment: M5_NODES_PLAYWRIGHT=C:/Users/eMitchell109/AppData/Local/hermes/hermes-agent/node_modules/playwright-core/index.mjs; M5_NODES_CHROMIUM=C:/Users/eMitchell109/AppData/Local/ms-playwright/chromium-1243/chrome-win64/chrome.exe. MESH_RELAY=0 keeps these disposable checks disconnected from Relay.

Execution cwd was test/app03-review-m5-checks/source. All72 copied source/test/config files are unchanged worktree bytes; source-manifest.json records equal source/copy SHA256 values. This confines automatically generated DBs/evidence to the permitted disposable review directory. run.ps1 invokes the installed npm CLI for npm test and the exact named Node commands. NODE_OPTIONS imports the disposable observe.mjs only to retain ChildProcess identities/original close events; no executable/argv/probe-result substitution. Two preparation failures are retained separately: Windows absolute-path ESM import rejected, then missing server.mjs in the disposable copy. Only the disposable harness was corrected; these exit1 attempts are not product defects or passes.

Reproduced evidence:

- API tests denied unadmitted/missing-CSRF/wrong-origin requests and nonempty refresh configuration without launching a probe; GET/HEAD only age cache. Concurrent refreshes coalesce. Delayed responses after expiry/logout return empty401/no-store. Existing inference-service contract remains distinct.
- Real browser native refresh at2026-10-04T02:45:55.695Z returned cli_timeout for both fixed identities. Online and last-success are null. Cards equal that sanitized snapshot and explicitly say unavailable/offline not established; packet/inference/model readiness stay unknown. This is a sandbox limitation, not a proved offline pair or a successful native read. No denial cause was inferred. Native screenshot visually inspected.
- Separate disposable transport/clock assertions cover ready -> stale -> offline, unchanged last success, unavailable after failed observation, local aging without requests, logout clearance and held late response after offline clearance. The controlled screenshot was visually inspected and says TEST ONLY; it provides no native or physical Wi-Fi acceptance.
- Native/controlled browser proof and screenshots: test/app03-review-m5-checks/source/test/app03-m5-nodes-browser-c20f78e0-7da5-4dd7-a234-12264347fab1/. Controlled API/probe evidence and every disposable DB are retained below the same review directory.

Host evidence read only, separately attributed: D:/Dev/Onoes-Mesh/.runner/m5-nodes/{parent-product-check,deployment-check,deploy-browser-check}.json. Parent receipt identifies merge9a02254, branch/integrated npm30+1/probeAPIprivacy34 zero skips, and original fixed CLI1237968 exit0. Its2026-10-04T02:28:53.827Z snapshot reports PC Online=true/ready and laptop Online=false/offline. Deployed390x844 cards equal the2026-10-04T02:36:42.174Z sanitized native snapshot and retain local completion timestamps/unknown readiness. Deployment receipt preserves the same dataDir and identical owner-row digest. These receipts corroborate qualified-host success; this sandbox did not independently reproduce that successful read. No referenced builder worktree was inspected.

Process closure: *-launcher.json and *-processes.jsonl retain PID/create/executable/argv/purpose/parent relationships and original owned-process exits. Browser Node2132516/create02:45:51.9067512Z exits0; Chrome2183068/create02:45:52.4853043Z original child exits0; fixed tailscale.exe2932544/create02:45:53.6794696Z argv status --json closes SIGTERM under the existing2s timeout (no numeric Windows exit code claimed). Browser proof records both disposable app listeners closed. final-known-pids.json finds all75 recorded distinct identities absent; no extra stop was issued. Chromium internal children/short diagnostic helpers were not independently inventoried. Protected serving shell127.0.0.1:4317 returned HTTP200; shared/manual/serving/pending workloads were left alone. No deletion or DB staging.

Next: Host owns the scoped shared-Git handoff for REVIEW-M5.md and append-only DECISIONS.md/JOB.md. Evidence/DBs remain unstaged. Eddie's actual phone/Wi-Fi owner acceptance remains pending. Review ends once here; no dispatch, source repair or review repeat.

Blocked: No reproduced product blocker. NOT_RUN successful native Online read independently in this sandbox (cli_timeout limitation), physical phone/Wi-Fi changes/acceptance, laptop-origin acceptance, model/service starts, deployment/configuration changes, cloud, public exposure, commit/push/Actions. No sandbox weakening.
