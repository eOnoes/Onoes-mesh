// Start the app's own session when this shell came from the gate adapter.
//
// app.js keeps its own admitted flag and fetches tasks only from its Start handler, so a
// valid cookie alone still shows "Locked". It asks /gate/status rather than reading a
// cookie: plain m1-serve fixtures have no such route, so browser tests keep the locked
// board they assert on.
async function maybeStartSession() {
  let allow = false;
  try {
    const response = await fetch('/gate/status', { cache: 'no-store' });
    if (response.ok) {
      const status = await response.json();
      allow = Boolean(status.local || status.gated);
    }
  } catch {
    allow = false;
  }
  if (!allow) return;

  const start = document.getElementById('demo-start');
  const total = document.getElementById('total-count');
  if (start && !start.disabled && total && total.textContent.trim() === 'Locked') {
    start.click();
    if (location.hash === '#unlock') history.replaceState(null, '', location.pathname);
  }
}

maybeStartSession();