// Public shell registration only; registration does not prove offline readiness.
export async function registerPublicShell() {
  const origin = new URL(location.href);
  if (origin.protocol !== 'http:' || origin.hostname !== '127.0.0.1' ||
      !origin.port || Number(origin.port) < 1 || origin.username || origin.password) {
    return 'unavailable: approved assigned loopback origin required';
  }
  if (!('serviceWorker' in navigator)) return 'unavailable: worker feature absent';
  const worker = new URL('/sw.js', origin.origin);
  if (worker.origin !== origin.origin) return 'unavailable: origin mismatch';
  try {
    await navigator.serviceWorker.register(worker.href, { type: 'module', scope: '/' });
    return 'registered: control and offline readiness still require verification';
  } catch {
    return 'unavailable: worker registration failed; private data requires online admission';
  }
}
registerPublicShell().then(status => console.info('Public shell:', status));
