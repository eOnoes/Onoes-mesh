# Current build closure handoff

Prepared 2026-10-04 for Echo, sole canonical manager `f46e2ca656b9`. The integrated build is usable and its scoped recovery repair is accepted/deployed. [Newer owner feedback][owner] confirms basic physical phone navigation, saved-task opening and reported controls. **Whole-build acceptance and full process-custody qualification are not complete.** Laptop checks are **PENDING OWNER HOME WINDOW**. This completes the missing documentation deliverable, with no product implementation. Remaining gates: [NEXT-OWNER-CHECKS.md](NEXT-OWNER-CHECKS.md).

## Source and deployment

Read-only Git collection from this worktree AND canonical `D:/Dev/Onoes-Mesh` returned HEAD `d077f2d83ed9607f21139aa71a86743918a50f74`, package version `0.1.0`. Initial tracked status in the worker worktree was clean; canonical dirty MORNING/OVERNIGHT handoffs and unowned work are preserved, not reported clean. Latest scoped product adoption, merge `64a1d257f638cc390ad0ba2a152849d15bbca6ba`, is an ancestor of HEAD. All eight adopted recovery production/test blobs and checkout SHA256 values match [integration-readback.json][integration]. HEAD adds records; DECISIONS.md differs from that earlier receipt, not the adopted product bytes. Collected hashes appear below.

Verified private URL: **https://emitchell.tail8c4a75.ts.net:8446/**, private Serve to `http://127.0.0.1:4317`. Retained [deployment][deploy] proves HTTP200/exact HTML and app.js bytes, regular Mesh with native Relay and unchanged owner rows; [browser readback][browser] proves deliberate recovery of the same owner task before expiry. [Final protected readback][preserve] records Mesh PID2612068/create1791123042.2126422 and Relay PID3671748/create1791123042.2858684. These are receipt-time identities, not permission to act on a PID. Current morning snapshot also records byte-equal loopback/private readback at16:23:28Z. This writer performed no live network/process check.

## Original deliverables reconciled

“Built” means integrated implementation; “verified” names retained parent checks, not worker exit alone. Historical checks stay historical. [Current recovery acceptance][recovery], exact [integrated checks][current-checks] and [regression][regression] cover affected current code: npm31+1, named94, full M2/M3 31, standalone M2/M3 31, boundaries43, native Relay HTTP2, exit0/zero skips. Browser emulation is not physical owner acceptance. No entire milestone is promoted to fully owner-accepted here.

| Original GOAL deliverable | Implementation and exact retained evidence | Qualification / remaining gate |
| --- | --- | --- |
| M0 `m0-smoke` | `lib/version.mjs`, `test/version.test.mjs`; commit `8c2fa4f…`, JOB present. Parent [ledger][ledger] key `m0-smoke`: npm29; [REVIEW-M0.md](REVIEW-M0.md) independently verifies commit/export. | Built/historically verified; owner reading three RUN cause/duration records not retained as confirmed. |
| M0 `m0-hang` | Runner/dispatcher; [RUN][hang-run]: two10s empty-output attempts. [DISPATCH][hang-dispatch]: `--idle 60`, runnerExit5. Parent [hang check][hang-check]: no matches/unknowns; ledger `m0-hang`: independent raw classification, clean worktree. | Accepted bounded zero-output replay, not an observed60s idle expiry. Later absence cannot supply original native exits. |
| M0 `m0-real` | Actual `lib/owned_job.py` (GOAL says `lib/owned-job.py`), `test/test_owned_job.py`. Named-import failure repaired by `test/__init__.py`; ledger `m0-real-import`: native19/npm29/retained-descendant30. Single review defects repaired under ledger `m0-runner-custody` (native27/dispatcher20), `m0-dispatch-exit` (native exits0/2/3/4/5, suite20). | Built/parent-verified historically; native19 also retained in [observer receipt][observer]. Does not close later full-qualification acquisition gaps. |
| M1 `m1-serve` | `test/m1-serve.mjs`, npm start/proxy/Serve. Ledger `m1-serve`: actual HTTP/assets/admission; current [deployment][deploy] binds served bytes. | PC/private checks pass; laptop-origin check parked. Single M1 review expressly deferred in ledger `m1-persist.next`. |
| M1 `m1-persist` | `lib/task-store.mjs`, real UI/start adapter. [Parent persistence][persist]: identical UI-created task ID/revision after actual termination and npm start on same store. | Built/automatically verified. Phone opening confirmed; owner-PC restart/phone refresh pending. |
| M2 `m2-proposal` | `config/commands.json`, `lib/command-proposals.mjs`, store/API/UI. [Parent proposal][proposal]: pending command/cwd and same task after restart; parent ledger records branch/integrated checks. | Built/verified; owner control traversal is narrower than durable evidence for every click. |
| M2 `m2-approve` | `lib/command-execution.mjs`, `lib/owned-command.py`, guarded API/UI. [Parent approval][approve]: actual version stdout/exit0/cleanup true, denial0 runs after restart. Single [M2 review](REVIEW-M2.md), ledger `review-M2`, current regression31. | Built/verified; physical version-output/denial-no-run acceptance not fully reconstructed. Current separate pending proposal stays untouched. |
| M3 `m3-idempotent` | Execution/store replay fence. [Parent replay][replay]: same run after restart, executionCount1; current full/standalone31 and standalone browser replay. | Built/verified; physical replay check not inferred. |
| M3 `m3-crash` | Bridge/store/API/UI, fixed `lib/slow-command.mjs`. [Composed parent][crash]: native Cancel/cleanup, exact disposable-server crash/same-store UNKNOWN. Single [M3 review](REVIEW-M3.md), ledger `review-M3`, current regression/browser. | Built/verified. Owner feedback records actual cancelled=true/cleanupVerified=true, execution failed/rootExit1; task done is separate. Owner-PC crash/restart pending. |
| M4 `m4-link` | `lib/relay-link.mjs`, `service_roots/relay`, guarded native frame/canonical reference. Accepted [runtime parent][relay] and single [M4 parent review][review4]: same task on reconnect/both-process restart, zero proposals/executions. [Saved-list][saved] and [CSP][csp] repairs accepted; current M4 HTTP2. | Built/verified. Original rejected runtime/failed attempts retained. Basic Mesh-phone feedback does not confirm physical Relay send/reconnect. |
| M5 `m5-nodes` | `lib/node-probes.mjs`, API/UI; `lib/inference-observation.mjs` keeps separate service contract. [Core parent][probe], [UI parent][nodes]: fixed CLIexit0 PCready/laptopoffline; single [M5 parent review][review5]: API-to-DOM, controlled aging/private clearance. | Built/verified cached Tailscale Online only. Sandbox cli_timeout proved neither host offline. Physical Wi-Fi parked; packet/model/inference readiness unknown. |
| M6 `m6-standalone` | Startup/server/service boundaries: `MESH_STANDALONE=1 npm start`, optional services absent. [Original parent][standalone], [single parent review][review6], current regression31/boundaries43, [corrected browser][corrected]: output/replay/denial/real Cancel/exact disposable restart/UNKNOWN/no replay spawn. | Built/verified product paths; wrapper failure, reviewer Git ownership restriction and historical custody gaps retained. Physical standalone M2 pending. |

## Startup, recovery and data

**Owner dataDir is `test/app03-manager-m1-disposable`, absolute `D:/Dev/Onoes-Mesh/test/app03-manager-m1-disposable`. Its `tasks.sqlite` and Relay subdirectory contain retained owner data despite the name. Never use it as a test/crash fixture or cleanup target.** Newer owner feedback retains a separate unapproved slow-command proposal; leave it untouched.

Tested references: `npm start` resolves to `node test/m1-serve.mjs` ([package.json](package.json), parent M1 persistence). README's hidden `./tools/start-mesh.ps1` / `./tools/stop-mesh.ps1` restart sequence has composed deployment evidence; helpers retain SQLite, but stop-mesh checks its recorded root identity, not whole descendant custody. Accepted native serving argv is in [preservation evidence][preserve]. Deliberate UI Start/recovery restores admission after proof clearance: bootstrap403 → challenge200 → completion201 → fresh health verification → same saved task. [Parent verdict][verdict] establishes trusted lifecycle clearance with zero automatic requests. After interruption, inspect failed/UNKNOWN; replacement requires a new saved proposal and explicit approval, never automatic replay.

README needs a narrow later correction: default npm/helper startup selects `test/app03-mesh`, not the owner directory; bare helpers do not establish accepted Relay configuration. Its “persistence builder still implementing”, successful native M5 read pending, legacy blank-pending assertion unresolved and blanket phone-pending statements are superseded by the receipts above. 8443 is an old route example; accepted route is8446. Proposed host correction: qualify startup with existing `-DataDir test/app03-manager-m1-disposable -PreviewPort 4317` parameters and retained regular-Mesh/Relay configuration, link current recovery and update only stale status sentences. No helper/config/route change or startup execution here. Standalone uses README's separate M6 disposable-store procedure.

Deployment/final readback preserve historical logical owner digest `7303e17ad4c3e868ad282ec3ee7832a55d20d1c78b26213b908dbf7235befebd` across that deployment/browser readback. This is not a backup or a digest of later owner revision22. Git history cannot restore SQLite/Relay data or reverse execution. No backup restoration/older-release rollback was tested here; Echo must preserve the entire store and separately qualify rollback before operational changes. This writer made no DB read/export.

## Limits and disposition

[BUGS.md](BUGS.md) retains nonblocking history: intermittent incomplete native process-list query failed closed (`cleanupVerified=false`); bounded [parent reconciliation][cleanup-bug] did not reproduce it in30 trials/34 original exits and claims no repair. Disposable preparation-gate503/409 and initial Relay cold-start deadline have unproven causes. Saved-list, [Deny/Cancel labels and legacy pending assertion][deny-cancel], CSP and observer parent-generation source defects are repaired with retained parent receipts. Cosmetic save/navigation feedback stays deferred.

Full qualification remains **BLOCKED_PROCESS_EVIDENCE** ([observer][observer]): original fast-child handle/identity/argv/exit acquisitions unavailable; one transient owned qualification cmd window recorded. Later absence/acquired exits cannot repair missing original receipts. Current recovery regression's first M6 root exited1 on its own conhost assertion despite four product stages; one unchanged detached launch exited0 without erasing that failure. Review-M6 sandbox git-status128, worker archive/custody breaches and unavailable headless lifecycle remain historical limits; real parent shared-browser lifecycle is distinct. Separate child source review produced no verdict, not an independent-model audit PASS. First phone-session-loss candidate remains rejected.

Genuinely missing local gate: auxiliary `npm run check` cannot qualify its pinned contract because `APP03-CONTRACT.json` is absent (current verdict/morning and local existence check). Do not invent pins or relabel npm test as that check. Full native qualification has failed evidence, not a never-run check. No other never-qualified affected product check is established by this reconciliation; Echo must identify an exact command/source binding before a new scope. M1 review is a paused laptop dependency. This handoff closes neither gate.

Only HOST-CLOSURE.md, NEXT-OWNER-CHECKS.md and three-line JOB.md change. Verification: tracked `git diff --check` exit0; each new-file `git diff --no-index --check -- NUL <file>` exit1 solely for added content, with no whitespace diagnostics after correcting one appended blank EOF line. Source/input hashes and canonical receipt links were checked read-only. No setup/product tests/services/owner-data/ledger/history/commit/push/Actions changes. jdocmunch indexing was refused by approval_policy=never; bounded direct reads used without escalation. Echo independently reviews/adopts these documents; notification is not acceptance. Existing cleanup/final-retirement decisions remain manager-owned.

## Parent adoption qualification

Echo independently matched all54 input hashes,31 canonical receipt links and8 accepted recovery source/test blob/checkout bindings. The original three-line JOB.md replaced historical records; it is retained in the original candidate commit but NOT adopted as a replacement. The scoped correction restores the complete baseline JOB and appends this handoff plus parent verdict. Canonical dirty handoffs remain protected. Only documentation is integrated; existing real browser/API/native acceptance is retained, not rerun or promoted to whole-build acceptance.

[ledger]: .runner/manager-handled.json
[integration]: .runner/owner-phone-session-recovery/integration-readback.json
[recovery]: .runner/owner-phone-session-recovery/parent-product-check.json
[verdict]: .runner/owner-phone-session-recovery/PARENT-VERDICT.md
[current-checks]: .runner/owner-phone-session-recovery/parent-integrated/checks.json
[regression]: .runner/owner-phone-session-recovery/parent-regression/results.json
[deploy]: .runner/owner-phone-session-recovery/deployment-check.json
[browser]: .runner/owner-phone-session-recovery/deployed-browser-readback.json
[preserve]: .runner/owner-phone-session-recovery/final-protected-readback.json
[hang-run]: .runner/m0-hang/RUN.json
[hang-dispatch]: .runner/m0-hang/DISPATCH.json
[hang-check]: .runner/review-M0/parent-hang-process-check.json
[persist]: .runner/m1-persist/parent-product-check.json
[proposal]: .runner/m2-proposal/parent-browser-check.json
[approve]: .runner/m2-approve/parent-browser-check.json
[replay]: .runner/m3-idempotent/parent-browser-check.json
[crash]: .runner/m3-crash-compose/parent-product-check.json
[relay]: .runner/m4-runtime-fix/parent-browser-check.json
[review4]: .runner/review-M4/parent-product-check.json
[saved]: .runner/fix-relay-saved-list-retry/parent-product-check.json
[csp]: .runner/fix-relay-csp-inline/parent-product-check.json
[probe]: .runner/m5-node-probes/parent-product-check.json
[nodes]: .runner/m5-nodes/parent-product-check.json
[review5]: .runner/review-M5/parent-product-check.json
[standalone]: .runner/m6-standalone/parent-product-check.json
[review6]: .runner/review-M6/parent-checks.json
[corrected]: .runner/owner-phone-session-recovery/parent-regression/m6-corrected-result.json
[observer]: .runner/fix-m6-observer-parentage/parent-product-check.json
[cleanup-bug]: .runner/fix-owned-cleanup-list/parent-product-check.json
[deny-cancel]: .runner/owner-deny-cancel-labels/parent-product-check.json
[owner]: .runner/owner-feedback/phone-flow-confirmed-20261004.md

## Collection hashes

Receipt links above are repository-relative paths in canonical D:/Dev/Onoes-Mesh after adoption. Current MORNING/OVERNIGHT, owner feedback, ledger and supplied parent receipts were read from the read-only .runner/host-closure-inputs/ copies below; tracked historical handoffs were not substituted. Other explicitly referenced parent receipts were accessible read-only at canonical paths. These hashes identify documentation inputs, not new product acceptance.

| Adopted recovery source/test file | Collected SHA256 |
| --- | --- |
| lib/trial-session.mjs | `612b80789a45cf3a0e3305352769fc96e77b926f3ae5ad325dd214818880fc60` |
| public/app.js | `6687f4f625a3b8e45bde130de279b5169c581106a8c6c1c3fc43275213e7c3b5` |
| public/index.html | `423b79a8cc3bca7eef69ed227d8eb4d6ccecb5849b1403dcd05a1fca88d5520f` |
| server.mjs | `8f089aa662679b7fbeb634a37749cd98210101e1cf42f900c17cd67dc0aaf05e` |
| test/owner-phone-session-loss-browser.mjs | `7f00daf554fe99354b9f412f7bd54d56436cdbbfbe6fc49be605aa1c96ca593a` |
| test/privacy01.test.mjs | `ea9df96cdb21030d4eeaada1d91db331eea1338ba097bb94704eb63534571d96` |
| test/session-recovery-http.test.mjs | `a1da3fd711767353ef5e416b22ee7241000e403a2f40e87e24a6c6d8d3396757` |
| test/trial-session.test.mjs | `02bc44d0cdb28f40faaf0a9f81c6c8ccc74f977359626e03aa90ff51194530bb` |

<details>
<summary>SHA256 of retained documentation inputs</summary>

Paths beginning I/ mean .runner/host-closure-inputs/; C/ means D:/Dev/Onoes-Mesh/. No prefix means this worktree.

```text
2adfca275c80d5ff5fe4038c9b4124c03a2361cf890dc917c15872d4ba11bcb2  GOAL.md
e6052bc5339cf5324f8582d720455c28362942e5a028ba3a82eb7baa21545666  README.md
79ae767911e0b133b1e1599495ed4e6f2a29cfd0c0b6aff27ef51a3a8f1e86c1  BUGS.md
29cfccdd7379b47f2a31700bbc1cb3bc1d141e6903b445187caedc468c36e592  package.json
18be34ff5c7d881d5796364db530212b35b52f9b933dcd14d77d760f5b21fc77  tools/start-mesh.ps1
8e4f04b35755c22c0f52d9e2fe517e2dc9928794c322894a5311a50a695e8975  tools/stop-mesh.ps1
d2ba72b35901d228043407579c29f7e0335d1fead9afc2e295d105063bf73efd  REVIEW-M0.md
b70dc3c466458a0adea34745caec45f5c273d21bb15e221021d85600bca4bdb9  REVIEW-M2.md
6bc75dbf5f3d1e94f08dec999a9ae4011550d7bdca0dbcb5e965f4f7850e7a7f  REVIEW-M3.md
d093e373a01e9a027caf5c3dc56563cc47bb130a1ab602d8074b75b861f7a393  REVIEW-M4.md
26e1b6403543239a4cda3da4598e0612b6c1bccd22d63aa02a9c95aa410d9c71  REVIEW-M5.md
c0e483f1b83f12702ee3c5fe05ff5b9040fecd31443f6d5b509971225c8d7a61  REVIEW-M6.md
969098de48f140c46dac948338b4e9ffb62ada049d279fccda8c8895f4b7aa0b  I/MORNING-HANDOFF.md
2403b640a256ac27df56aed68292c9e5033cbc7a10eac60810f38c17eee6a6f4  I/OVERNIGHT-HANDOFF.md
6beadb5efb8c0eb8291c5077e58bab635dfec867aed87c074a95d99bf412d80f  I/WORKER-COMMS.md
c028dc5becf0f4068818acc06202d686a70720536350931845680534c962898d  I/.runner/manager-handled.json
a98e5df78553f3da84799e8aafcc203a882c3f63a67e83f6cdfacbdbaad3cf4d  I/.runner/fix-m6-observer-parentage/parent-product-check.json
3f2fc069a37ab3a5cd6239cfb547e657e004f564cfec01fe6cf2e18124f45fdb  I/.runner/fix-relay-csp-inline/deployment-check.json
25cfb910edf04a15f93b367b4b78cb76b4ba12c1a9977eb77b8044d4511d7ed4  I/.runner/fix-relay-csp-inline/parent-product-check.json
a7ae92b45253909ec514552aa2527a961b3df46ddb4c125a802236d1b089e631  I/.runner/m1-persist/parent-product-check.json
82f3785252d24e94116c0575d36b8d23021ad584930b86af4dce252e4c92ebd0  I/.runner/m3-crash-compose/parent-product-check.json
53e8ec28d6a1e19f9e7b0a9660a96b6d4bd85acff60120dc4da927934ae592cd  I/.runner/m5-node-probes/parent-product-check.json
768a295d7e4b9838ff5de2ecdb3b722d6bec5e422ba147fd4e5fa289d93c7ff5  I/.runner/m5-nodes/deployment-check.json
a2e2948777a166c014d9f5ecd190846ad3ab145f34e393ee4edba7447df86c73  I/.runner/m5-nodes/parent-product-check.json
b69dff8d9a4c2d414dece4ba65ec48c54ce2ae93afcfb1981297581383824035  I/.runner/m6-standalone/deployment-check.json
4e2496873345717030b152dd1966777d89ee9b393c0def8eb6fe90f1b31af4dd  I/.runner/m6-standalone/parent-product-check.json
a2d4212f7e335aa6ca6d15edd6b86783101555e1fb3824308bdecf226d387bf3  I/.runner/owner-deny-cancel-labels/parent-product-check.json
d038a9342186aa0cf06427403fbb2e18db25bdf5d3e7de814024427e5ca2840d  I/.runner/owner-feedback/phone-flow-confirmed-20261004.md
45cb3623f84800adbcb587412d87ed8b1bd23c26fcc9ba873354096a9138c366  I/.runner/owner-phone-session-recovery/deployed-browser-readback.json
c7daf472425150d7b02d68aec668d057ba40bce9b620ada326b6ba25531517e0  I/.runner/owner-phone-session-recovery/deployment-check.json
537d6649d9940a306b4301a6e076209a52f969d4f3dc3d229eb0118acb6bec20  I/.runner/owner-phone-session-recovery/final-protected-readback.json
da3e7b76104f31fb70a202389c98f1b86817b1717a6e2314b97536e1708db25b  I/.runner/owner-phone-session-recovery/integration-readback.json
02bfa07a9ef20a7e57f2d9702241b8173f70e1f2e4e17919cae4102cff1a6d6f  I/.runner/owner-phone-session-recovery/parent-product-check.json
4930523e44cd8d5de395f36f268a6929e91d7a8d913bd62baabb2bcfaa3dce06  I/.runner/owner-phone-session-recovery/PARENT-VERDICT.md
7046f3d38c9dc4130998ff62a222abf3e854f5fae0bdb54810eb68001ae823a2  I/jobs/host-closure-handoff.md
c4cd8e6bc1ff56f64b481c103f52d46843d076a0a71365c6d33caf809eb58b3f  C/.runner/m0-smoke/RUN.json
bf3a66fdad7db7d119c2257a76cc0a7c8f9b4d57c1e18b6843893431ab24fa60  C/.runner/m0-hang/RUN.json
da6c01268c3282e13524c0f8dce7e6070c8e37caf0b7e9d461de1f43d3a7b0cb  C/.runner/m0-hang/DISPATCH.json
d0357e0f8f7482eeffa4344075ab2f9cf2f2cb87ad3816003767bbdfd41109aa  C/.runner/m0-real-import/RUN.json
d1041841905a9a4229b72bbee584aa152579c9eb0286e7cf6bb6a6d87f992d76  C/.runner/review-M0/parent-hang-process-check.json
4ad720c082463000f490ab8ecd17b90594dd4e35932fce894ea83973ee152008  C/.runner/m2-proposal/parent-browser-check.json
43d964eb64914477d6f0abe3271bc655c89afcd6ccd014612d4ea0124b94ad72  C/.runner/m2-approve/parent-browser-check.json
ff446973e1f84fe95bab44d5a8ad2ba10a4bcf25c81ddd28b87f79774060cd47  C/.runner/m3-idempotent/parent-browser-check.json
22a233f307ed3fe537cc1eebb8d4f9c0e4604a4e0fdefdd073cf6a4452c274f9  C/.runner/m4-runtime-fix/parent-browser-check.json
9eaff337f7152d022718abed1f4b4c71302a588406be394e4093b456b04a39bf  C/.runner/review-M4/parent-product-check.json
6a07a5ea2ae9864d5f2d8995c8dcab66e051d6c4b04af6f0a3f92e77d19270c0  C/.runner/review-M5/parent-product-check.json
5dcbff0027a5c2afdd8ee0af9cab8275f43c611966d52c1af71d2f056dc80c15  C/.runner/review-M6/parent-checks.json
34951c4530f93f4c304a628100b4f5bcf70bb2fb03c6284086f5fa1fac80c2fe  C/.runner/fix-relay-saved-list-retry/parent-product-check.json
cc03360f26d94e9482994a19bea59de10f94452128a277ffec365d6cb5d2052a  C/.runner/fix-owned-cleanup-list/parent-product-check.json
685e954a09e7ebc096589f8d60268430d35328acfda0e4160c93b038dcfe0e73  C/.runner/owner-phone-session-recovery/startup-readback.json
3b9e142d3b250e08f9285e21b1ff7469c7a30c8b027d22aa642ef463fe01b11b  C/.runner/owner-phone-session-recovery/parent-integrated/checks.json
d97c5ef2d9e112fe47e8b626f018ccb16f34b05f938f0c67827c45b1ef1ac364  C/.runner/owner-phone-session-recovery/parent-regression/results.json
a9de93385b7b991f82875f2b5510e8c2333e7bc977f6203568fca0f894f2c820  C/.runner/owner-phone-session-recovery/parent-regression/m6-original-failure.json
5ff76c5f6cbbf8a886a15239fc88fbeb62a9fbd36d302319e98d58f1aaf01f0b  C/.runner/owner-phone-session-recovery/parent-regression/m6-corrected-result.json
```

</details>
