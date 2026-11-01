import test from 'node:test';
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { mkdtemp, writeFile, readFile } from 'node:fs/promises';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { createNodeProbeReader, NODE_IDENTITIES, NODE_PROBE_LIMITS,
  TAILSCALE_EXECUTABLE, TAILSCALE_STATUS_ARGV } from '../lib/node-probes.mjs';

const evidence = await mkdtemp(fileURLToPath(new URL('./app03-m5-node-probes-', import.meta.url)));
console.log(`Disposable process evidence (not live tailnet): ${evidence}`);
const fixture = join(evidence, 'disposable-cli.mjs');
await writeFile(fixture, `import { readFileSync } from 'node:fs';
const input = JSON.parse(readFileSync(process.argv[2], 'utf8'));
if (input.mode === 'timeout') { setInterval(() => {}, 1000); }
else if (input.mode === 'oversized') { process.stdout.write('x'.repeat(1048577)); setInterval(() => {}, 1000); }
else if (input.mode === 'invalid_utf8') { process.stdout.write(Buffer.from([0xff])); }
else { process.stdout.write(input.stdout ?? ''); process.stderr.write(input.stderr ?? ''); process.exitCode = input.exitCode ?? 0; }
`);
const peer = (node, online, extra = {}) => ({ DNSName: node.dnsName + '.',
  TailscaleIPs: [node.tailscaleIp], Online: online, LastSeen: '1999-01-01T00:00:00Z', ...extra });
const status = (pc = true, laptop = false, extras = {}) => ({ BackendState: 'Running',
  Self: peer(NODE_IDENTITIES[0], pc), Peer: { laptop: peer(NODE_IDENTITIES[1], laptop) }, ...extras });
const input = value => ({ stdout: JSON.stringify(value) });
let sequence = 0;

async function transport(inputs) {
  const calls = [], children = [], files = [];
  for (const value of inputs) {
    const path = join(evidence, `input-${++sequence}.json`);
    await writeFile(path, JSON.stringify(value)); files.push(path);
  }
  const spawnImpl = (binary, argv, options) => {
    assert.equal(binary, TAILSCALE_EXECUTABLE);
    assert.deepEqual(argv, ['status', '--json']);
    assert.deepEqual(options, { shell: false, windowsHide: true, stdio: ['ignore', 'pipe', 'pipe'] });
    assert.ok(calls.length < files.length, 'no automatic retry');
    const path = files[calls.length];
    // Substitute only the transport: real spawned process/streams/close/timeout,
    // with production fixed argv assertions and production parser/state logic.
    const child = spawn(process.execPath, [fixture, path], options);
    calls.push({ binary, argv, options, pid: child.pid, input: path }); children.push(child);
    return child;
  };
  const retain = async name => writeFile(join(evidence, `${name}.json`), JSON.stringify({
    provenance: 'disposable process input; not a live tailnet observation', calls,
    exits: children.map(child => ({ pid: child.pid, exitCode: child.exitCode, signalCode: child.signalCode }))
  }, null, 2));
  return { spawnImpl, calls, children, retain };
}
function time() {
  let elapsed = 0;
  const base = Date.parse('2026-10-04T01:00:00.000Z');
  return { clock: () => base + elapsed, monotonic: () => elapsed, advance: ms => { elapsed += ms; } };
}
const find = (snapshot, id) => snapshot.nodes.find(node => node.id === id);
const hasError = (node, code) => node.errors.some(error => error.code === code);

test('fixed two identities and argv; ignores unrelated/cloud/private fields and daemon LastSeen', async () => {
  const config = JSON.parse(await readFile(new URL('../config/nodes.json', import.meta.url), 'utf8'));
  assert.deepEqual(config.nodes, NODE_IDENTITIES);
  assert.deepEqual(TAILSCALE_STATUS_ARGV, ['status', '--json']);
  const data = status();
  data.Peer.cloud = { DNSName: 'cloud.example', TailscaleIPs: ['100.66.66.66'], Online: true, Secret: 'PRIVATE_MARKER' };
  data.User = { a: { LoginName: 'PRIVATE_MARKER' } };
  const tx = await transport([input(data)]), tm = time();
  const reader = createNodeProbeReader({ ...tm, spawnImpl: tx.spawnImpl });
  assert.equal(find(reader.snapshot(), 'pc').observationAvailability, 'unavailable');
  const snapshot = await reader.refresh();
  assert.equal(snapshot.source, 'disposable_transport');
  assert.equal(snapshot.nodes.length, 2);
  const pc = find(snapshot, 'pc'), laptop = find(snapshot, 'laptop');
  assert.equal(pc.status, 'ready'); assert.equal(laptop.status, 'offline');
  assert.equal(laptop.lastSuccessAt, null); assert.equal(laptop.tailscaleOnline, false);
  assert.equal(laptop.observationAvailability, 'available'); assert.ok(hasError(laptop, 'node_offline'));
  assert.equal(pc.lastSuccessAt, '2026-10-04T01:00:00.000Z');
  assert.equal(pc.lastProbeAt, pc.lastSuccessAt);
  assert.equal(pc.observationType, 'tailscale_status_cached_online');
  for (const node of snapshot.nodes) {
    assert.equal(node.inferenceReadiness, 'unknown'); assert.equal(node.modelReadiness, 'unknown');
    assert.equal(node.packetReachability, 'unknown');
    assert.equal(node.capabilities.control, false); assert.equal(node.capabilities.load, false);
    assert.equal(node.capabilities.inference, false); assert.equal(node.capabilities.unload, false);
  }
  assert.ok(!JSON.stringify(snapshot).includes('PRIVATE_MARKER'));
  snapshot.nodes[0].status = 'offline'; snapshot.nodes[0].errors.push({ code: 'invented' });
  assert.equal(find(reader.snapshot(), 'pc').status, 'ready', 'caller cannot mutate cache');
  await tx.retain('selection');
});

test('actual offline refresh: success -> stale -> offline, finite grace and unchanged last success', async () => {
  const tx = await transport([input(status(true, true)), input(status(false, false)), input(status(false, false)), input(status(true, true))]);
  const tm = time(), reader = createNodeProbeReader({ ...tm, spawnImpl: tx.spawnImpl });
  const first = await reader.refresh(), successAt = first.nodes[0].lastSuccessAt;
  tm.advance(10000);
  const failed = await reader.refresh();
  for (const node of failed.nodes) {
    assert.equal(node.status, 'stale'); assert.equal(node.lastSuccessAt, successAt);
    assert.equal(node.lastProbeAt, '2026-10-04T01:00:10.000Z');
    assert.equal(node.tailscaleOnline, false); assert.equal(node.observationAvailability, 'available');
  }
  tm.advance(49999); assert.equal(reader.snapshot().nodes[0].status, 'stale');
  tm.advance(1);
  const expired = await reader.refresh();
  for (const node of expired.nodes) { assert.equal(node.status, 'offline'); assert.equal(node.lastSuccessAt, successAt); }
  assert.equal(tx.calls.length, 3);
  tm.advance(1); const recovered = await reader.refresh();
  assert.equal(recovered.nodes[0].status, 'ready'); assert.notEqual(recovered.nodes[0].lastSuccessAt, successAt);
  await tx.retain('offline-aging');
});

test('failed native refresh cannot renew cache; denied diagnostics stay private', async () => {
  const tx = await transport([input(status()), { exitCode: 1, stdout: JSON.stringify(status()), stderr: 'control pipe: Access is denied. PRIVATE_MARKER' }]);
  const tm = time(), reader = createNodeProbeReader({ ...tm, spawnImpl: tx.spawnImpl });
  const first = await reader.refresh(); tm.advance(5000);
  const failed = await reader.refresh(), pc = failed.nodes[0];
  assert.equal(pc.status, 'stale'); assert.equal(pc.lastSuccessAt, first.nodes[0].lastSuccessAt);
  assert.equal(pc.observationAvailability, 'unavailable'); assert.equal(pc.tailscaleOnline, null);
  assert.ok(hasError(pc, 'cli_access_denied')); assert.ok(!JSON.stringify(failed).includes('PRIVATE_MARKER'));
  assert.equal(failed.nodes[1].status, 'offline'); assert.equal(failed.nodes[1].tailscaleOnline, null);
  tm.advance(55000); const expired = reader.snapshot();
  assert.equal(expired.nodes[0].status, 'offline'); assert.equal(expired.nodes[0].observationAvailability, 'unavailable');
  assert.equal(expired.nodes[0].lastSuccessAt, first.nodes[0].lastSuccessAt);
  assert.equal(expired.nodes[0].lastProbeAt, pc.lastProbeAt); assert.equal(tx.calls.length, 2);
  await tx.retain('denied-aging');
});

test('unrefreshed real success ages without a watcher or new timestamps', async () => {
  const tx = await transport([input(status())]), tm = time();
  const reader = createNodeProbeReader({ ...tm, spawnImpl: tx.spawnImpl });
  const first = await reader.refresh(); tm.advance(NODE_PROBE_LIMITS.freshMs);
  assert.equal(reader.snapshot().nodes[0].status, 'stale');
  tm.advance(NODE_PROBE_LIMITS.staleGraceMs - NODE_PROBE_LIMITS.freshMs);
  const expired = reader.snapshot(); assert.equal(expired.nodes[0].status, 'offline');
  assert.equal(expired.nodes[0].lastProbeAt, first.nodes[0].lastProbeAt);
  assert.equal(expired.nodes[0].lastSuccessAt, first.nodes[0].lastSuccessAt);
  assert.equal(expired.nodes[0].tailscaleOnline, true, 'historical cached Online is not current readiness');
  assert.ok(hasError(expired.nodes[0], 'observation_expired')); assert.equal(tx.calls.length, 1);
  await tx.retain('unrefreshed-aging');
});

test('malformed refresh loses current observation and timestamps record completion rather than start', async () => {
  const tx = await transport([input(status(true, true)), { stdout: '{' }]), tm = time();
  const reader = createNodeProbeReader({ ...tm, spawnImpl: (...args) => {
    const child = tx.spawnImpl(...args);
    child.once('close', () => tm.advance(100));
    return child;
  } });
  const first = await reader.refresh();
  assert.equal(first.nodes[0].lastSuccessAt, '2026-10-04T01:00:00.100Z');
  const failed = await reader.refresh();
  for (const node of failed.nodes) {
    assert.equal(node.status, 'stale'); assert.equal(node.observationAvailability, 'unavailable');
    assert.equal(node.lastProbeAt, '2026-10-04T01:00:00.200Z');
    assert.equal(node.lastSuccessAt, '2026-10-04T01:00:00.100Z');
    assert.equal(node.tailscaleOnline, null); assert.ok(hasError(node, 'malformed_output'));
  }
  tm.advance(59900);
  assert.ok(reader.snapshot().nodes.every(node => node.status === 'offline'));
  await tx.retain('malformed-aging-completion');
});

test('exact identity conflicts, duplicates, missing nodes and unsupported shapes never become ready', async () => {
  const mismatch = status(); mismatch.Self.DNSName = 'impostor.tail8c4a75.ts.net.';
  const duplicate = status(); duplicate.Peer.copy = { ...duplicate.Self };
  const missing = status(); missing.Peer = { cloud: peer({ dnsName: 'emitchell109-rog.tail8c4a75.ts.net.attacker', tailscaleIp: '100.66.66.66' }, true) };
  const malformed = status(); delete malformed.Self.Online;
  const cases = [
    [input(mismatch), 'pc', 'identity_mismatch'], [input(duplicate), 'pc', 'identity_ambiguous'],
    [input(missing), 'laptop', 'node_missing'], [input(malformed), 'pc', 'malformed_output'],
    [input(status(true, true, { BackendState: 'Stopped' })), 'pc', 'tailscale_not_running'],
    [input({ BackendState: 'Running', Self: {}, Peer: [] }), 'pc', 'malformed_output'],
    [{ stdout: '{' }, 'pc', 'malformed_output'], [{ mode: 'invalid_utf8' }, 'pc', 'malformed_output']
  ];
  for (const [value, id, code] of cases) {
    const tx = await transport([value]);
    const node = find(await createNodeProbeReader({ spawnImpl: tx.spawnImpl }).refresh(), id);
    assert.equal(node.status, 'offline'); assert.equal(node.observationAvailability, 'unavailable');
    assert.equal(node.tailscaleOnline, null); assert.equal(node.lastSuccessAt, null); assert.ok(hasError(node, code));
    await tx.retain(`invalid-${sequence}`);
  }
});

test('missing binary is unavailable rather than proof that the two nodes are offline', async () => {
  const path = join(evidence, 'nonexistent.exe');
  const snapshot = await createNodeProbeReader({ spawnImpl: (binary, argv, options) => {
    assert.equal(binary, TAILSCALE_EXECUTABLE); assert.deepEqual(argv, ['status', '--json']);
    return spawn(path, [], options);
  } }).refresh();
  for (const node of snapshot.nodes) {
    assert.equal(node.status, 'offline'); assert.equal(node.observationAvailability, 'unavailable');
    assert.equal(node.tailscaleOnline, null); assert.equal(node.lastSuccessAt, null); assert.ok(hasError(node, 'cli_unavailable'));
  }
  await writeFile(join(evidence, 'missing-binary.json'), JSON.stringify(snapshot, null, 2));
});

test('bounded timeout stops its own command process and leaves unrelated process alive', async () => {
  const tx = await transport([{ mode: 'timeout' }]);
  const sentinel = spawn(process.execPath, ['-e', 'setInterval(() => {}, 1000)'], { windowsHide: true, stdio: 'ignore' });
  const sentinelClosed = new Promise(resolve => sentinel.once('close', resolve));
  const started = performance.now();
  try {
    const snapshot = await createNodeProbeReader({ spawnImpl: tx.spawnImpl }).refresh();
    assert.ok(performance.now() - started < NODE_PROBE_LIMITS.timeoutMs + 1000);
    for (const node of snapshot.nodes) { assert.ok(hasError(node, 'cli_timeout')); assert.equal(node.lastSuccessAt, null); }
    assert.notEqual(tx.children[0].exitCode ?? tx.children[0].signalCode, null);
    assert.equal(sentinel.exitCode, null); assert.equal(sentinel.signalCode, null);
    process.kill(sentinel.pid, 0);
    await tx.retain('timeout');
  } finally { sentinel.kill(); await sentinelClosed; }
});

test('bounded combined process output stops only the offending command', async () => {
  const tx = await transport([{ mode: 'oversized' }]);
  const snapshot = await createNodeProbeReader({ spawnImpl: tx.spawnImpl }).refresh();
  assert.ok(snapshot.nodes.every(node => node.status === 'offline' && node.lastSuccessAt === null && hasError(node, 'output_too_large')));
  assert.notEqual(tx.children[0].exitCode ?? tx.children[0].signalCode, null);
  await tx.retain('oversized');
});

test('concurrent caller refreshes share one fixed native read and completion timestamp', async () => {
  const tx = await transport([input(status(true, true))]);
  const reader = createNodeProbeReader({ spawnImpl: tx.spawnImpl });
  const a = reader.refresh(), b = reader.refresh(); assert.equal(a, b);
  const [first, second] = await Promise.all([a, b]);
  assert.deepEqual(first, second); assert.equal(tx.calls.length, 1);
  assert.equal(first.nodes[0].lastProbeAt, first.nodes[1].lastProbeAt);
  await tx.retain('coalesced');
});
