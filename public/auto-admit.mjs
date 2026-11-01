// Start the app's own session once the gate has proven you hold the key.
//
// app.js keeps its own admitted flag and only fetches tasks from its Start handler, so a
// valid cookie alone still shows "Locked". The readable `mesh_gate` cookie is what tells
// this module the gate is real - browser tests never have it, so they see the plain
// locked board exactly as they expect.
const gated = document.cookie.split(';').some((c) => c.trim() === 'mesh_gate=1');
if (gated) {
  const start = document.getElementById('demo-start');
  const total = document.getElementById('total-count');
  if (start && !start.disabled && total && total.textContent.trim() === 'Locked') {
    start.click();
    if (location.hash === '#unlock') history.replaceState(null, '', location.pathname);
  }
}