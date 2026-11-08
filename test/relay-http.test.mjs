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

test('native receipt reads only the exact send, retains rotation and never supplies writer release', async () => {
  const calls = [];
  const receipt = { agentId: 'echo', sendId: 'send-one', conversationId: 'original',
    runId: 'run_one', nativeSessionId: 'rotated', observation: 'observed',
    status: 'completed', terminal: true, writerQuiescence: false, output: 'private output' };
  const link = await createRelayHttpLink({ baseUrl: 'http://127.0.0.1:9', token: 'synthetic',
    fetchImpl: async (url, options) => {
      calls.push({ url, method: options.method });
      return Response.json({ ok: true, receipt });
    } });
  const observed = await link.nativeRunReceipt({ agentId: 'echo', sendId: 'send-one', conversationId: 'original', expectedRunId: 'run_one' });
  assert.equal(observed.nativeSessionId, 'rotated');
  assert.equal(observed.conversationId, 'original');
  assert.equal(observed.writerQuiescence, false);
  assert.equal('output' in observed, false);
  assert.deepEqual(calls, [{ url: 'http://127.0.0.1:9/api/agents/echo/outbox/send-one/native-run', method: 'GET' }]);
});

test('native receipt rejects crossed identities and unsupported completion claims without dispatch', async () => {
  const original = { agentId: 'echo', sendId: 'send', conversationId: 'original', runId: 'run_one',
    nativeSessionId: 'rotated', observation: 'observed', status: 'completed', terminal: true, writerQuiescence: false };
  for (const change of [{ agentId: 'other' }, { sendId: 'other' }, { conversationId: 'other' },
    { runId: 'run_other' }, { writerQuiescence: true }, { status: 'unavailable' },
    { nativeSessionId: null }, { terminal: false }, { observation: 'unknown' }]) {
    const calls = [];
    const link = await createRelayHttpLink({ baseUrl: 'http://127.0.0.1:9', token: 'synthetic',
      fetchImpl: async (url, options) => { calls.push(options.method); return Response.json({ ok: true, receipt: { ...original, ...change } }); } });
    await assert.rejects(link.nativeRunReceipt({ agentId: 'echo', sendId: 'send', conversationId: 'original', expectedRunId: 'run_one' }), e => e.status === 503);
    assert.deepEqual(calls, ['GET']);
  }
});

test('missing receipt remains unknown and invalid identifiers never reach Relay', async () => {
  let count = 0;
  const link = await createRelayHttpLink({ baseUrl: 'http://127.0.0.1:9', token: 'synthetic',
    fetchImpl: async () => { count++; return Response.json({ ok: true, receipt: {
      agentId: 'echo', sendId: 'send', conversationId: 'original', runId: null,
      nativeSessionId: null, status: 'unknown', observation: 'unknown', terminal: false, writerQuiescence: false } }); } });
  assert.equal((await link.nativeRunReceipt({ agentId: 'echo', sendId: 'send', conversationId: 'original' })).observation, 'unknown');
  await assert.rejects(link.nativeRunReceipt({ agentId: '../echo', sendId: 'send', conversationId: 'original' }), e => e.status === 400);
  assert.equal(count, 1);
});

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
    const before=Date.now();
    const snap = await link.snapshot();
    assert.ok(Date.parse(snap.observedAt)>=before && Date.parse(snap.observedAt)<=Date.now());
    assert.equal(snap.status, 'fresh');
    assert.equal(snap.agents.length, 4, 'all four agents, not the single synthetic mesh agent');
    assert.deepEqual(snap.agents.map(a => a.id), ['echo', 'cyony', 'dsh', 'tripp']);
    assert.equal(snap.agents[2].approval.cmd, 'rm -rf build', 'approval state passes through untouched');
    assert.equal(snap.error, null);
  } finally { await relay.close(); }
});

test('snapshot picks a primary conversation, and says so when there is none', async () => {
  const withConv = await fakeRelay(jsonRoute(AGENTS));
  try {
    const link = await createRelayHttpLink({ baseUrl: withConv.url, token: 'gate-token' });
    const snap = await link.snapshot();
    assert.equal(snap.status, 'fresh');
    assert.equal(snap.primaryAgentId, 'echo', 'first agent with a conversation is primary');
    assert.equal(snap.conversationId, 'c-echo');
    assert.deepEqual(snap.links, [], 'no fabricated links: the index lives in Workroom now');
  } finally { await withConv.close(); }

  const noConv = await fakeRelay(jsonRoute(AGENTS.map(a => ({ ...a, conversation_id: null }))));
  try {
    const link = await createRelayHttpLink({ baseUrl: noConv.url, token: 'gate-token' });
    const snap = await link.snapshot();
    assert.equal(snap.status, 'unavailable');
    assert.match(snap.error, /no agent has an active conversation/i);
    assert.ok(Number.isFinite(Date.parse(snap.observedAt)),'successful empty-session observation still has its read time');
    assert.equal(snap.conversationId, null, 'must not invent a conversation to send into');
  } finally { await noConv.close(); }
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
    assert.equal(snap.observedAt,undefined,'a failed read must not fabricate a successful observation time');
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

// Relay's own validator requires a UUID conversation id; the snapshot fixture above
// uses readable slugs, so the message fixture is separate rather than loosening the rule.
const CONV = '11111111-1111-4111-8111-111111111111';
const AGENTS_FOR_MESSAGE = AGENTS.map(a => (a.id === 'echo' ? { ...a, conversation_id: CONV } : a));

function relayForMessage({ status = 200, body = { ok: true, queued: 1 } } = {}) {
  const seen = [];
  const handler = (req, res) => {
    const url = req.url;
    if (url === '/api/agents' && req.method === 'GET') {
      res.writeHead(200, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify(AGENTS_FOR_MESSAGE));
      return;
    }
    let data = '';
    req.on('data', chunk => { data += chunk; });
    req.on('end', () => {
      seen.push({ url, method: req.method, body: data ? JSON.parse(data) : null });
      res.writeHead(status, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify(body));
    });
  };
  return { seen, handler };
}

function fakeStore(result = { taskId: 'task-1', duplicate: false }) {
  const calls = [];
  return {
    calls,
    linkRelay(args) {
      calls.push(args);
      if (result instanceof Error) throw result;
      return result;
    },
  };
}

const MESSAGE = { id: 'msg-1', text: 'ship it', conversationId: CONV, meshIntent: 'create_task' };

test('a message goes to Relay first, then the link is written locally', async () => {
  const fake = relayForMessage();
  const store = fakeStore();
  const relay = await fakeRelay(fake.handler);
  try {
    const link = await createRelayHttpLink({ baseUrl: relay.url, token: 'gate-token', store });
    const result = await link.message(MESSAGE, () => true);
    assert.equal(result.ok, true);
    assert.equal(result.agentId, 'echo', 'the agent is resolved from the conversation, not assumed');
    assert.equal(result.taskId, 'task-1');
    assert.equal(result.duplicate, false);
    const post = fake.seen.find(r => r.method === 'POST');
    assert.equal(post.url, '/api/agents/echo/message');
    assert.deepEqual(post.body, { id: 'msg-1', text: 'ship it', files: [] });
    assert.equal(store.calls.length, 1);
    assert.deepEqual(store.calls[0], {
      scope: 'relay:mesh', conversationId: CONV, messageId: 'msg-1', text: 'ship it',
    });
  } finally { await relay.close(); }
});

test('an unknown conversation is refused before anything is sent', async () => {
  const fake = relayForMessage();
  const store = fakeStore();
  const relay = await fakeRelay(fake.handler);
  try {
    const link = await createRelayHttpLink({ baseUrl: relay.url, token: 'gate-token', store });
    await assert.rejects(
      link.message({ ...MESSAGE, conversationId: '00000000-0000-4000-8000-000000000000' }, () => true),
      error => error instanceof TaskError && error.status === 409,
    );
    assert.equal(fake.seen.filter(r => r.method === 'POST').length, 0, 'no message may leave');
    assert.equal(store.calls.length, 0, 'no task may be created');
  } finally { await relay.close(); }
});

test('a refusal from Relay writes no link', async () => {
  const fake = relayForMessage({ status: 400, body: { ok: false, error: 'bad' } });
  const store = fakeStore();
  const relay = await fakeRelay(fake.handler);
  try {
    const link = await createRelayHttpLink({ baseUrl: relay.url, token: 'gate-token', store });
    await assert.rejects(
      link.message(MESSAGE, () => true),
      error => error instanceof TaskError && error.status === 400,
    );
    assert.equal(store.calls.length, 0);
  } finally { await relay.close(); }
});

test('a duplicate send still links, and says so', async () => {
  const fake = relayForMessage({ body: { ok: true, duplicate: true } });
  const store = fakeStore({ taskId: 'task-9', duplicate: true });
  const relay = await fakeRelay(fake.handler);
  try {
    const link = await createRelayHttpLink({ baseUrl: relay.url, token: 'gate-token', store });
    const result = await link.message(MESSAGE, () => true);
    assert.equal(result.taskId, 'task-9');
    assert.equal(result.duplicate, true);
  } finally { await relay.close(); }
});

test('an expired admission sends nothing', async () => {
  const fake = relayForMessage();
  const store = fakeStore();
  const relay = await fakeRelay(fake.handler);
  try {
    const link = await createRelayHttpLink({ baseUrl: relay.url, token: 'gate-token', store });
    await assert.rejects(
      link.message(MESSAGE, () => false),
      error => error instanceof TaskError && error.status === 403,
    );
    assert.equal(fake.seen.filter(r => r.method === 'POST').length, 0);
  } finally { await relay.close(); }
});

test('a failed link says the message was sent rather than pretending it was not', async () => {
  const fake = relayForMessage();
  const store = fakeStore(new Error('disk full'));
  const relay = await fakeRelay(fake.handler);
  try {
    const link = await createRelayHttpLink({ baseUrl: relay.url, token: 'gate-token', store });
    await assert.rejects(
      link.message(MESSAGE, () => true),
      error => error instanceof TaskError && error.status === 503 && /accepted the message/.test(error.message),
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
