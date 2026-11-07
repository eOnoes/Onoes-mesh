# Mesh repo index — which tree is which

Historical baseline as of 2026-10-31. The current deployment note below supersedes the
older hosting, authentication and working-tree descriptions. A previous Mesh main repo (`D:\Dev\Onoes-Mesh`) was deleted without ever being
committed anywhere, and its entire history went with it. That is why this file exists.

## Current working deployment - updated 2026-11-04

Use the private Workroom preview for the current goal:

    https://emitchell.tail8c4a75.ts.net:8453/#workroom

- Working copy: C:/Users/eMitchell109/Documents/ChatGPT/Nims Chat/mesh-workroom-ab, branch workroom/identity-and-relay. Local implementation changes are not a published release.
- Preview listener: loopback port 4320; backend port is assigned by the app. Database: data/workroom-preview/tasks.sqlite. Preserve this store and its history.
- Current preview has Tailscale owner-identity admission at its configured private host, local task-session admission, and existing origin/CSRF guards. The historical "No authentication" statement below does not describe this preview.
- Original deployment remains on 8446 -> loopback 4317, associated with D:/Mesh. It was not replaced, merged or deleted. Never assume these two deployments share the same data store.
- Exact current preview process receipt: ../workroom-ab-preview-process.json. Rehearsed restart helper: integrations/restart-workroom-preview.ps1. Online backup/isolated restore receipt: ../workroom-backup-latest.json. Revalidate process identity; never stop by name or port.
- DeepSeek A2A approval update was explicitly authorized and installed on 2026-11-04. Its new process/backup receipt is under data/dsh-approval-rollout; the original seven interrupted requests require explicit reconciliation. The DSH web app and Relay are separate services.
- Current goal, acceptance evidence, open backlog and runtime qualification limits: WORKROOM-AB-CHECKPOINT.md. A connected service or passing fixture does not prove a model is resident, a worker is executing, or a task is approved.

## Authoritative inference qualification pointer - corrected 2026-11-07

For Qwen3.6-35B-A3B and Qwen3.8-Flash-Next, the authority is
`E:/Echo-DB/runtimes/UNBIASED-STRATA-LOCK.md`, followed by `RUNTIMES.md`
and Echo's `ustrata_call.md`. Only `E:/Echo-DB/tools/UnbiasedStrata` is approved
for those families. Qwen3.8-27B (`qwen35`) is the documented llama.cpp exception.

All three expected Windows binaries now exist under that tree's `build/bin`:
`unbiased-strata.exe`, `strata.exe`, `strata-poly.exe`. Their presence supersedes
the old missing-binary observation, but does not prove transport, ownership,
cancellation, model identity or GPU attribution. The supervisor owns the ports;
do not start a competing listener or use retired8094/8096.

The previously listed `Documents/Codex/2026-11-03/task/unbiased-coder-source`
Maya/DeepSeek build is a different project. Its lock is not authority for these
Qwen families. Preserve that evidence as historical, not as a replacement engine.
The Mesh fixed legacy llama.cpp Flash-Next profile remains unqualified/disabled.
Do not repoint it at an existing executable merely to enable controls.

An eventual promotion requires an explicit code/data release record and verified backups. Do not copy over either live database or blindly merge the preview into the original tree. GitHub publication remains separately authorized.

## Historical original deployment - retained for reference

Mesh is hosted on the tailnet so the same URL works from this PC or from a phone. That is the
operator's standard: host via Tailscale so an agent can hand over one clickable link and it
works wherever they are.

    https://emitchell.tail8c4a75.ts.net:8446          <- original deployment, not the current preview

Published by:

    tailscale serve --bg --https=8446 http://127.0.0.1:4317

Locally the same app is at `http://127.0.0.1:4317`.

**Started by** `tools\start-mesh.cmd`, launched from a Startup-folder entry
(`%APPDATA%\...\Startup\mesh.cmd`). It is idempotent — it refuses to start a second copy — and
it re-asserts the serve mapping after a successful boot.

**Two constraints are the app's own, not the launcher's:**

- `startApp` refuses a `dataDir` that is not `test/app03-*`. Mesh cannot be pointed at an
  arbitrary folder; its state lives in `test/app03-mesh`.
- `startApp` refuses a fixed port and requires an OS-assigned one, so **the backend port
  changes every boot**. Only the preview port (4317) is stable, which is why that is what the
  tailnet publishes. Never hardcode the backend port.

**Historical authentication description (superseded for the 8453 preview).** This baseline
described tailnet-only access without an unlock gate. Consult the current deployment note
above before making any statement about today's access boundaries.

## Repo layout

    public/      the seven-tab PWA: index.html, app.js, styles.css, sw.js, icons
    shared/      tokens.css — the ONLY place a colour may be defined
    lib/         server-side modules (task store, connections, probes, relay link)
    tools/       start-mesh.cmd and friends
    test/        the tracked suite; npm test / test:ui / check
    _incoming/   staged, NOT integrated — see below

## The truth

    D:\Mesh        its own git repo, branch master, pushed to github.com/eOnoes/Onoes-mesh

Seven tabs: 01 Overview, 02 Relay, 03 Inference, 04 Workroom, 05 Agent, 06 Mind, 07 Control.
Design tokens live in `shared/tokens.css` and nowhere else. `npm test`, `npm run test:ui` and
`npm run check` all pass. Vendored deps and test output are untracked deliberately.

## Archived — do not use, do not edit

Renamed 2026-10-31 so a bare directory listing cannot be mistaken for a live project. The
operator will review and remove these personally.

| Path | What it was |
|---|---|
| `D:\Dev\Onoes-Mesh-local-box-archived` | the donor: the tree the current base was imported from. Kept as fallback. |
| `D:\Dev\Onoes-Mesh-local-box-wt-archived` | a worktree of the donor, branch `job/inference-control-panel-design` — which has **zero unique commits** |
| `D:\Dev\Onoes-Mesh-wt-archived` | 1.0 GB of pre-split worktrees (m4-link, closure-*, review-M*). May hold the only copy of some abandoned work. |
| `D:\Dev\mesh-preview-archived` | visual captures from the old look |
| `D:\Dev\Onoes-Mesh-sandbox` | **NOT RENAMED** — held open by another process. Still the only other copy of the 78 files staged in `_incoming/sandbox/`. |

`D:\Dev\Onoes-Mesh` is **absent** — deleted, never committed, history unrecoverable.

## The trap these trees set

Three of them had no `.git` of their own, so `git -C` inside them walked up to `D:\Dev\.git`
and reported an unrelated project, `NSM.ShiftReport.Generator`. Three different directories
appeared to have the same "214 dirty entries" — it was never their status.

Before trusting any git answer about a directory:

    git -C <dir> rev-parse --absolute-git-dir

If that path is not the directory you are standing in, you are inside somebody else's repo.

## Not yet integrated

`D:\Mesh\_incoming\sandbox\` holds 78 files harvested from the sandbox: 63 source plus 12
design/intent docs and 3 icons. They are staged, **not wired in**, because they are a
different relay architecture from what the base already vendors in `service_roots/relay/`:

    base vendors      relay_server, relay_sessions, relay_notify, relay_channels, relay_webpush
    sandbox brings    relay_chat, relay_store, relay_events, relay_supervisor,
                      relay_decisions, relay_qualification, relay_mind_adapter,
                      relay_push*, relay_proactive

No filename collisions, but overlapping purpose — `relay_push*` and `relay_webpush` are two
push implementations and only one should win. That is an architecture decision, not a file
move, and it has not been made.

## Archived history

`D:\Mesh-archive\Mesh-full-history-2026-10-31.bundle` holds the six-commit history that was
squashed into the single baseline commit for the first publication. It is the only
step-by-step record of the import and cleanup.
