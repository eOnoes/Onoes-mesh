// Startup adapter for the baseline server's exported interface.
import http from 'node:http';
import { startApp } from '../server.mjs';

const dataDir = process.env.MESH_DATA_DIR ?? 'test/app03-mesh';
const port = Number(process.env.MESH_PREVIEW_PORT ?? 4317);
if (!Number.isInteger(port) || port < 0 || port > 65535) throw new Error('Invalid MESH_PREVIEW_PORT');
const app = await startApp({ dataDir });
const backend = new URL(app.url);
// Tailscale terminates HTTPS. Adapt its preserved Host/Origin to the unchanged
// loopback-only application; keep session cookies and CSRF proof intact.
const preview = http.createServer((req, res) => {
  const deny = () => { req.resume(); res.writeHead(403, { 'Cache-Control': 'no-store' }); res.end(); };
  const scheme = req.headers['x-forwarded-proto'] === 'https' ? 'https' : 'http';
  const externalOrigin = `${scheme}://${req.headers.host}`;
  if (req.headers.origin && req.headers.origin !== externalOrigin) return deny();
  if (req.headers['sec-fetch-site'] && !['same-origin', 'none'].includes(req.headers['sec-fetch-site'])) return deny();
  if (!req.url.startsWith('/') || req.url.startsWith('//')) return deny();
  const headers = { ...req.headers, host: backend.host };
  if (headers.origin) headers.origin = app.url;
  // These describe the outer proxy, not the application's local request.
  for (const name of Object.keys(headers)) {
    if (name === 'forwarded' || name.startsWith('x-forwarded-') || name.startsWith('tailscale-')) delete headers[name];
  }
  const upstream = http.request({ hostname: '127.0.0.1', port: backend.port, path: req.url, method: req.method, headers }, response => {
    res.writeHead(response.statusCode, response.headers);
    response.pipe(res);
  });
  upstream.on('error', () => {
    if (!res.headersSent) res.writeHead(502);
    res.end();
  });
  req.on('aborted', () => upstream.destroy());
  res.on('close', () => upstream.destroy());
  req.pipe(upstream);
});
try {
  await new Promise((resolve, reject) => {
    preview.once('error', reject);
    preview.listen(port, '127.0.0.1', resolve);
  });
} catch (error) { await app.close(); throw error; }
const previewUrl = `http://127.0.0.1:${preview.address().port}`;
console.log(JSON.stringify({ event: 'mesh_listening', pid: process.pid, url: app.url, previewUrl, dataDir, mode: app.mode }));
let stopping = false;
async function stop() {
  if (stopping) return;
  stopping = true;
  const closed = new Promise((resolve, reject) => preview.close(error => error ? reject(error) : resolve()));
  preview.closeAllConnections();
  await closed;
  await app.close();
}
for (const signal of ['SIGINT', 'SIGTERM']) process.once(signal, () => stop().catch(error => { console.error(error); process.exitCode = 1; }));
