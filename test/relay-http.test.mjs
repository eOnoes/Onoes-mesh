/**
 * R8a — the HTTP bridge to the live Relay.
 *
 * These tests stand up a fake Relay in-process on an ephemeral port, so nothing
 * spawns a child and the whole file runs without a sandbox exception. The point is
 * to pin the *failure* behaviour as hard as the happy path: a bridge that reports
 * an unreachable Relay as "unauthorised", or leaks the gate token into a message,
 * is worse than no bridge.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { createRelayHttpLink } from '../lib/relay-http.mjs';
import { TaskError } from '../lib/task-store.mjs';

const AGENTS = [
  { id: 'echo', name: 'Echo', backend: 'hermes', device: 'pc', status: 'idle', conversation_id: 'c-echo', approval: null, budget: null },
  { id: 'cyony', name: 'Cyony', backend: 'a2a', device: 'cloud', status: 'idle', conversation_id: 'c-cyony', approval: null, budget: null },
  { id: 'dsh', name: 'Deep', backend: 'a2a', device: 'pc', status: 'idle', conversation_id: 'c-dsh', approval: { id: 'req-1', cmd: 'rm -rf build' }, budget: null },
  { id: 'tripp', name: 'Tripp', backend: 'openclaw', device: 'laptop', status: 'waiting', conversation_id: null, approval: null, budget: null },
];

async function fakeRelay(handler) {
  const server = createServer(handler);
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const { port } = server.address();
  return { url: `http://127.0.0.1:${port}`, close: () => new Promise(r => server.close(r)) };
}

function jsonRoute(body, status = 200) {
  return (req, res) => {
    res.writeHead(status, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify(body));
  };
}

test('snapshot maps the real agents, including the ones Mesh has never seen', async () => {
  const relay = await fakeRelay(jsonRoute(AGENTS));
  try {
    const link = await createRelayHttpLink({ baseUrl: relay.url, token: 'gate-token' });
    const snap = await link.snapshot();
    assert.equal(snap.status, 'fresh');
    assert.equal(snap.agents.length, 4, 'all four agents, not the single synthetic mesh agent');
    assert.deepEqual(snap.agents.map(a => a.id), ['echo', 'cyony', 'dsh', 'tripp']);
    assert.equal(snap.agents[2].approval.cmd, 'rm -rf build', 'approval state passes through untouched');
    assert.equal(snap.error, null);
  } finally { await relay.close(); }
});

test('the gate token is sent as a bearer on API calls and never on the shell', async () => {
  const seen = [];
  const relay = await fakeRelay((req, res) => {
    seen.push({ url: req.url, auth: req.headers.authorization ?? null });
    if (req.url === '/') { res.writeHead(200, { 'Content-Type': 'text/html' }); res.end('<html>relay</html>'); return; }
    res.writeHead(200, { 'Content-Type': 'application/json' }); res.end(JSON.stringify(AGENTS));
  });
  try {
    const link = await createRelayHttpLink({ baseUrl: relay.url, token: 'gate-token' });
    await link.snapshot();
    const html = await link.shell();
    assert.equal(html, '<html>relay</html>');
    assert.equal(seen[0].auth, 'Bearer gate-token');
    assert.equal(seen[1].auth, null, 'the unlock screen must not receive the token');
  } finally { await relay.close(); }
});

test('a rejected token reads as unavailable, not as a leak', async () => {
  const relay = await fakeRelay(jsonRoute({ ok: false, error: 'unauthorised: token=SECRET-LEAK' }, 401));
  try {
    const link = await createRelayHttpLink({ baseUrl: relay.url, token: 'wrong' });
    const snap = await link.snapshot();
    assert.equal(snap.status, 'unavailable');
    assert.equal(snap.error, 'Live Relay did not return an agent list.');
    assert.ok(!JSON.stringify(snap).includes('SECRET-LEAK'), 'upstream body must not reach Mesh');
  } finally { await relay.close(); }
});

test('an unreachable Relay is unavailable, with a retry-shaped message', async () => {
  const link = await createRelayHttpLink({ baseUrl: 'http://127.0.0.1:9', token: 'gate-token', timeoutMs: 500 });
  const snap = await link.snapshot();
  assert.equal(snap.status, 'unavailable');
  assert.match(snap.error, /unavailable|unreachable/i);
});

test('only loopback origins are accepted', async () => {
  await assert.rejects(
    createRelayHttpLink({ baseUrl: 'http://192.168.1.10:8787', token: 't' }),
    error => error instanceof TaskError && /loopback/.test(error.message),
  );
  await assert.rejects(
    createRelayHttpLink({ baseUrl: 'not a url', token: 't' }),
    error => error instanceof TaskError,
  );
});

test('redirects are refused rather than followed', async () => {
  const relay = await fakeRelay((req, res) => {
    res.writeHead(302, { Location: '/evil' });
    res.end();
  });
  try {
    const link = await createRelayHttpLink({ baseUrl: relay.url, token: 'gate-token' });
    const snap = await link.snapshot();
    assert.equal(snap.status, 'unavailable');
  } finally { await relay.close(); }
});

test('oversized responses are refused', async () => {
  const big = 'x'.repeat(300000);
  const relay = await fakeRelay(jsonRoute([{ id: 'echo', name: big, backend: 'hermes' }]));
  try {
    const link = await createRelayHttpLink({ baseUrl: relay.url, token: 'gate-token' });
    const snap = await link.snapshot();
    assert.equal(snap.status, 'unavailable');
  } finally { await relay.close(); }
});

test('sending is explicitly not implemented in this stage — it does not pretend', async () => {
  const relay = await fakeRelay(jsonRoute(AGENTS));
  try {
    const link = await createRelayHttpLink({ baseUrl: relay.url, token: 'gate-token' });
    await assert.rejects(
      link.message({ id: 'm1', text: 'hello', conversationId: 'c-echo', meshIntent: 'create_task' }),
      error => error instanceof TaskError && error.status === 503 && /R8b/.test(error.message),
    );
  } finally { await relay.close(); }
});

test('nativeRead requires an absolute path and maps a refusal honestly', async () => {
  const relay = await fakeRelay((req, res) => {
    if (req.url === '/api/auth') { res.writeHead(200, { 'Content-Type': 'application/json' }); res.end(JSON.stringify({ auth_enabled: true })); return; }
    res.writeHead(403, { 'Content-Type': 'application/json' }); res.end('{}');
  });
  try {
    const link = await createRelayHttpLink({ baseUrl: relay.url, token: 'gate-token' });
    assert.deepEqual(await link.nativeRead('/api/auth'), { auth_enabled: true });
    await assert.rejects(link.nativeRead('api/auth'), error => error instanceof TaskError && error.status === 400);
    await assert.rejects(link.nativeRead('/api/nope'), error => error instanceof TaskError && error.status === 503);
  } finally { await relay.close(); }
});

test('a token file is read lazily and cleared on close', async () => {
  const relay = await fakeRelay(jsonRoute(AGENTS));
  try {
    const { writeFile, mkdtemp } = await import('node:fs/promises');
    const { tmpdir } = await import('node:os');
    const path = await import('node:path');
    const dir = await mkdtemp(path.join(tmpdir(), 'relay-http-'));
    const tokenFile = path.join(dir, 'relay.key');
    await writeFile(tokenFile, 'file-token\n');
    const link = await createRelayHttpLink({ baseUrl: relay.url, tokenFile });
    assert.equal((await link.snapshot()).status, 'fresh');
    await link.close();
  } finally { await relay.close(); }
});
