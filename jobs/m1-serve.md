Goal: M1 serving: npm start must serve the REAL PWA on loopback, with a straightforward private phone-preview handoff.
Read GOAL.md. M0 is complete; do not reopen runner/dispatcher work or invent a new lifecycle framework.
Owner direction: make the application work, not more speculative safety scenarios or paperwork.
Use existing server.mjs and its actual startup interface; inspect it but do not edit it.
Make package.json start script work if required. Keep launch/stop helpers minimal, hidden and scoped to this app.
Run npm start in this worktree with an isolated disposable store; verify HTTP returns the actual PWA shell.
Implement tools/start-mesh.ps1 and tools/stop-mesh.ps1 only if they are needed for a reliable simple owner launch/restart.
Document actual command, loopback URL, and private Tailscale publishing handoff in README.md.
Read current Tailscale Serve/Funnel configuration if accessible; do not overwrite shared routes or change cloud/Tailscale enrollment.
If publishing is denied in the sandbox, finish the functioning local serve path and give Echo the exact private proxy command to execute. Do not bypass privileges or expose public ports.
Check: npm test passes, actual npm start HTTP proof, git diff --check, no foreground-stealing popup launchers.
Allowed: package.json, README.md, tools/start-mesh.ps1, tools/stop-mesh.ps1, test/m1-serve*.mjs, JOB.md and append-only DECISIONS.md.
Do not edit server.mjs, lib/**, public/**, other test files, tools/mesh_runner.py or tools/mesh_dispatch.py.
Parallel m1-persist owns server/lib/public persistence integration; keep your start interface compatible with baseline.
No archive, old receipts, runner audits, cosmetic overhaul, credentials, OS changes or CI/runners.
Work directly with workspace-write tools. Host runner handles sandbox-denied Git commits.
JOB.md: Done / Next / Blocked, exact HTTP/test proof and deployment handoff, not speculation.
