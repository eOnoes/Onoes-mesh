import { startApp } from '../server.mjs';
// Parent-owned browser review launcher. No process is launched by importing it.
// It binds only an assigned IPv4 loopback port and retains synthetic SQLite.
const lifetimeMs = Number(process.env.APP03_PREVIEW_MS ?? 300000);
if (!Number.isSafeInteger(lifetimeMs) || lifetimeMs < 1 || lifetimeMs > 300000) throw new Error('Preview lifetime must be 1..300000 ms.');
const hardStop = setTimeout(() => { console.log(JSON.stringify({ event: 'preview_hard_stop', pid: process.pid })); process.exit(1); }, lifetimeMs);
let app; let stopping = false;
async function stop(reason) {
  if (stopping) return; stopping = true;
  clearTimeout(deadline);
  try { await app?.close(); console.log(JSON.stringify({ event: 'preview_stopped', pid: process.pid, reason, listenerClosed: true, syntheticDataRetained: true })); }
  finally { clearTimeout(hardStop); }
}
const deadline = setTimeout(() => { stop('automatic_deadline').catch(() => process.exit(1)); }, Math.max(1, lifetimeMs - 500));
try {
  app = await startApp({ dataDir: `test/app03-preview-${process.pid}-${Date.now()}` });
  console.log(JSON.stringify({ event: 'preview_listening', pid: process.pid, url: app.url, scope: 'SYNTHETIC LOCAL TRIAL', maxLifetimeMs: lifetimeMs }));
  for (const signal of ['SIGINT','SIGTERM']) process.once(signal, () => { stop(signal).catch(() => process.exit(1)); });
} catch {
  clearTimeout(deadline); clearTimeout(hardStop); console.error('APP03 preview startup failed.'); process.exitCode = 1;
}
