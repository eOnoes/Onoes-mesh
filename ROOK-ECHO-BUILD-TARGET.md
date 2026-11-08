# Rook isolated build target

Eddie approved the isolated snapshot/patch approach; the missing target now exists.

- Checkout: C:/Users/eMitchell109/Documents/ChatGPT/Nims Chat/mesh-rook-echo-4e321ea
- Exact frozen HEAD: 4e321eadcd99b7cd0b6b6ba1739d35292aed9029 (detached).
- Approved contract copy in that checkout: ROOK-BUILD-CONTRACT.md (v4).
- Return artifacts: C:/Users/eMitchell109/Documents/ChatGPT/Nims Chat/rook-delivery-4e321ea
- Shared Mesh integration remains Nims-owned in mesh-workroom-ab; do not edit it.

Keep implementation/tests in the isolated checkout. Return rook.patch against
that exact base, changed-files.txt, and acceptance-report.md with actual commands,
results, limitations and any remaining blocker. Preserve existing source/data.
A baseline suite is not Rook acceptance. No GitHub push/Actions, watcher enablement,
scheduler installation, credentials/grants, live dispatch, model service changes,
Mind access or Relay restart are part of this build handoff. Deployment/activation
remain separate. Do not copy owner keys or claim quiescence from a terminal status.

The isolated checkout starts clean; ROOK-BUILD-CONTRACT.md is a deliberately added
untracked contract copy, not a pre-existing source change. Do not include that copy
as an implementation change unless deliberately documenting it in the report.

The shared Mesh branch has advanced; keep this frozen base and return a patch.
Nims will review/integrate it and qualify against current Mesh. The separate
Relay receipt candidate is not Rook acceptance and is not installed live.
