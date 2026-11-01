# The Relay design — reference copy, do not edit

This is the UI the operator asked us to retain. It is **the source of truth for the look**,
archived here because nothing else guaranteed its survival:

| copy | location | off-machine? |
|---|---|---|
| live | `D:\Dev\Onoes-Relay\static\index.html` | **no** (not a git repo) |
| source repo | `...\Onoes-Relay\relay-stage\static\index.html` | **no** (no remote) |
| planning repo | `...\design-handover\relay-design-reference\` | **no** (no remote) |
| **this copy** | `D:\Mesh\design-reference\` | **yes** — pushed to GitHub |

All three original copies were byte-identical when this was made
(sha256 `3BB0B405A22C2F25E9A83BCE9466CEF336C9F9CD0E165FEA0548695FE96858BD`). Before this commit, that design existed in exactly one place with no
off-site backup.

## Rules

- **Read-only reference.** The Mesh app does not serve this file and must not import it.
  It exists so the design can be read, diffed and reproduced.
- If the live Relay UI changes, re-copy it here and update the hash above.
- Do not "improve" it. It is the target, not a draft.

## What makes that look

Two rows of chrome, not one:

    row 1   three 9px dots · `relay — a2a@pc · waiting on you` · `copy all`
    row 2   hamburger · agent pills (Echo / Cyony / Tripp / Deep) with 7px status dots

Then a scrolling feed of message blocks, each with a left border, an uppercase speaker
label (`YOU` blue, agent name amber or green) and a `[copy]` affordance. A composer sits
pinned at the bottom: `▸  +  Agent · type a message…` with a circular send button.

The drawer is organised into sections — `CONVERSATIONS`, `MCP` (13 servers, right-aligned
status), `ACTIVITY` — with uppercase headers and hairline separators.

Settings is its own panel: `appearance` (dark/light), `terminal text` (Aa −3px / current /
+3px), `follow new output`, `notifications on this device`, `send a test`,
`reset settings · saved on this device`.

Body is monospace throughout. Sans appears only in chrome.
