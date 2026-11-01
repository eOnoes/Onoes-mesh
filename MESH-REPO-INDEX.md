# Mesh repo index — which tree is which

Authoritative as of 2026-10-31. If you are an agent or a human picking this up, read this
first. A previous Mesh main repo (`D:\Dev\Onoes-Mesh`) was deleted without ever being
committed anywhere, and its entire history went with it. That is why this file exists.

## Hosting — how to open Mesh

Mesh is hosted on the tailnet so the same URL works from this PC or from a phone. That is the
operator's standard: host via Tailscale so an agent can hand over one clickable link and it
works wherever they are.

    https://emitchell.tail8c4a75.ts.net:8446          <- give this to the operator

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

**No authentication.** Unlike Onoes-Relay, Mesh has no unlock gate — anything on the tailnet
can reach it. Tailnet-only is the only boundary.

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
