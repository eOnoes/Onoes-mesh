import assert from 'node:assert/strict';
import http from 'node:http';
import { EventEmitter } from 'node:events';
import { PassThrough } from 'node:stream';
import { NODE_IDENTITIES, TAILSCALE_EXECUTABLE } from '../lib/node-probes.mjs';

// Controlled stream/clock evidence stays separate from the native browser check.
export function controlledProbe() {
  let tick = 0, online = true, failure = false, held = false;
  const calls = [], pending = [];
  const spawnImpl = (binary, argv, options) => {
    assert.equal(binary, TAILSCALE_EXECUTABLE);
    assert.deepEqual(argv, ['status', '--json']);
    assert.equal(options.shell, false); assert.equal(options.windowsHide, true);
    calls.push({ binary, argv, options });
    const child = new EventEmitter(); child.stdout = new PassThrough(); child.stderr = new PassThrough();
    const complete = () => {
      const peer = n => ({ DNSName: n.dnsName, TailscaleIPs: [n.tailscaleIp], Online: online });
      if (failure) child.stderr.write('Access is denied');
      else child.stdout.write(JSON.stringify({ BackendState: 'Running', Self: peer(NODE_IDENTITIES[0]), Peer: { laptop: peer(NODE_IDENTITIES[1]) }, User: { secret: 'PRIVATE_MARKER' } }));
      child.emit('close', failure ? 1 : 0, null);
    };
    child.kill = () => { child.emit('close', null, 'SIGTERM'); return true; };
    if (held) pending.push(complete); else setImmediate(complete);
    return child;
  };
  return { calls, options: { spawnImpl, clock: () => Date.parse('2026-10-04T01:00:00.000Z') + tick, monotonic: () => tick },
    advance: ms => { tick += ms; }, offline: () => { online = false; }, fail: () => { failure = true; },
    hold: () => { held = true; }, release: () => { held = false; pending.splice(0).forEach(f => f()); } };
}
export function request(app, route, { method = 'GET', headers = {}, body } = {}) {
  return new Promise((resolve, reject) => {
    const req = http.request(app.url + route, { method, headers }, res => {
      const chunks = []; res.on('data', c => chunks.push(c));
      res.on('end', () => resolve({ status: res.statusCode, headers: res.headers, text: Buffer.concat(chunks).toString(), json() { return JSON.parse(this.text); } }));
    });
    req.on('error', reject); req.end(body);
  });
}
export async function admit(app) {
  const res = await request(app, '/api/trial-session/bootstrap', { method: 'POST', headers: { Origin: app.url, 'Content-Type': 'application/json' }, body: '{}' });
  assert.equal(res.status, 201);
  return { Cookie: res.headers['set-cookie'][0].split(';')[0], 'X-Trial-CSRF': res.json().csrfToken };
}
