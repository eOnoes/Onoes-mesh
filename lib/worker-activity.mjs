import { constants } from 'node:fs';
import fs from 'node:fs/promises';
import { TextDecoder } from 'node:util';

const MAX_BYTES = 256 * 1024;
const VERSION = 'mesh-worker-activity/v1';
const PROCESS = new Set(['starting', 'running', 'waiting', 'returned', 'failed', 'stopped', 'unknown']);
const RESULT = new Set(['pending', 'returned_unverified', 'verified', 'failed', 'unknown']);
const CLI = new Set(['Codex', 'Claude', 'Qwen', 'codex', 'claude', 'qwen', 'unknown']);
const ID = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/;
const own = (obj, key) => Object.hasOwn(obj, key);
const object = value => value !== null && typeof value === 'object' && !Array.isArray(value);
const text = (value, max) => typeof value === 'string' && value.length > 0 && value.length <= max && !/[\u0000-\u001f\u007f]/u.test(value);

function time(value) {
  if (typeof value !== 'string') return null;
  const match = /^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(?:\.(\d{1,9}))?(?:Z|\+00:00)$/.exec(value);
  if (!match) return null;
  const canonical = `${match[1]}.${(match[2] ?? '').slice(0, 3).padEnd(3, '0')}Z`;
  const ms = Date.parse(value);
  return Number.isFinite(ms) && new Date(ms).toISOString() === canonical ? ms : null;
}

function optionalTime(row, key) {
  if (!own(row, key) || row[key] === null) return null;
  if (time(row[key]) === null) throw new Error('invalid timestamp');
  return row[key];
}

function model(row, key) {
  if (!own(row, key) || row[key] === null) return null;
  if (!text(row[key], 128)) throw new Error('invalid model');
  return row[key];
}

function project(row, now, staleAfterMs, registryFreshness) {
  if (!object(row) || !text(row.runId, 128) || !ID.test(row.runId)
      || !CLI.has(row.cli) || !text(row.title, 256) || !text(row.node, 128)
      || !PROCESS.has(row.processState) || !RESULT.has(row.resultState)) {
    throw new Error('invalid worker');
  }
  if (row.taskId != null && (!text(row.taskId, 128) || !ID.test(row.taskId))) throw new Error('invalid task ID');
  let startedAt = optionalTime(row, 'startedAt');
  const lastObservedAt = optionalTime(row, 'lastObservedAt');
  let lastProgressAt = optionalTime(row, 'lastProgressAt');
  if (startedAt !== null && (time(startedAt) > now
      || (lastObservedAt !== null && time(startedAt) > time(lastObservedAt)))) startedAt = null;
  if (lastProgressAt !== null && (time(lastProgressAt) > now
      || (startedAt !== null && time(lastProgressAt) < time(startedAt))
      || (lastObservedAt !== null && time(lastProgressAt) > time(lastObservedAt)))) lastProgressAt = null;
  const observed = time(lastObservedAt);
  let freshness = observed === null || observed > now ? 'unknown'
    : now - observed > staleAfterMs ? 'stale' : 'fresh';
  if (registryFreshness === 'unknown') freshness = 'unknown';
  else if (registryFreshness === 'stale' && freshness === 'fresh') freshness = 'stale';
  // A supervisor's explicit verified result is the verification assertion.
  // Process presence alone cannot create progress or verification.
  let resultState = row.resultState;
  if (resultState === 'pending' && row.processState === 'returned') resultState = 'returned_unverified';
  if (resultState === 'pending' && row.processState === 'failed') resultState = 'failed';
  return {
    runId: row.runId, cli: row.cli, title: row.title, node: row.node,
    taskId: row.taskId ?? null, processState: row.processState,
    requestedModel: model(row, 'requestedModel'), observedModel: model(row, 'observedModel'),
    startedAt, lastObservedAt, lastProgressAt, resultState, freshness,
  };
}

async function readBoundedFile(path) {
  // Windows file IDs can exceed Number's exact integer range.
  const before = await fs.lstat(path, { bigint: true });
  if (!before.isFile() || before.isSymbolicLink()) throw new Error('not a regular file');
  if (before.size > MAX_BYTES) throw new RangeError('oversized');
  const handle = await fs.open(path, constants.O_RDONLY | (constants.O_NOFOLLOW ?? 0) | (constants.O_NONBLOCK ?? 0));
  try {
    const initial = await handle.stat({ bigint: true });
    if (!initial.isFile() || initial.dev !== before.dev || initial.ino !== before.ino) throw new Error('file replaced');
    if (initial.size > MAX_BYTES) throw new RangeError('oversized');
    const buffer = Buffer.alloc(MAX_BYTES + 1);
    let length = 0;
    while (length < buffer.length) {
      const { bytesRead } = await handle.read(buffer, length, buffer.length - length, length);
      if (bytesRead === 0) break;
      length += bytesRead;
    }
    if (length > MAX_BYTES) throw new RangeError('oversized');
    const after = await handle.stat({ bigint: true });
    if (initial.size !== after.size || initial.mtimeNs !== after.mtimeNs || initial.ctimeNs !== after.ctimeNs || BigInt(length) !== after.size) {
      throw new Error('file changed during observation');
    }
    return new TextDecoder('utf-8', { fatal: true }).decode(buffer.subarray(0, length));
  } finally {
    await handle.close();
  }
}

/** Read one explicit local registry; never retain a cached running assertion. */
export async function readWorkerActivity({ registryPath, nowIso, staleAfterMs = 600000 } = {}) {
  const now = nowIso === undefined ? Date.now() : time(nowIso);
  const validNow = now !== null;
  const snapshot = { schemaVersion: VERSION, state: 'invalid', observedAt: new Date(validNow ? now : Date.now()).toISOString(), workers: [] };
  if (!validNow || !Number.isSafeInteger(staleAfterMs) || staleAfterMs < 0) return snapshot;
  if (registryPath === undefined || registryPath === null || registryPath === '') {
    snapshot.state = 'not_configured';
    return snapshot;
  }
  if (!text(registryPath, 4096) || /^[a-z][a-z0-9+.-]*:\/\//i.test(registryPath)) return snapshot;
  let raw;
  try { raw = await readBoundedFile(registryPath); }
  catch (error) {
    snapshot.state = error instanceof RangeError || error instanceof TypeError ? 'invalid' : 'unavailable';
    return snapshot;
  }
  try {
    const registry = JSON.parse(raw);
    if (!object(registry) || registry.schemaVersion !== 'mesh-worker-registry/v1'
        || !own(registry, 'generatedAt') || !Array.isArray(registry.workers) || registry.workers.length > 64) throw new Error('invalid registry');
    const generated = time(registry.generatedAt);
    if (registry.generatedAt !== null && generated === null) throw new Error('invalid generation time');
    const registryFreshness = generated === null || generated > now ? 'unknown'
      : now - generated > staleAfterMs ? 'stale' : 'fresh';
    const workers = registry.workers.map(row => project(row, now, staleAfterMs, registryFreshness));
    if (new Set(workers.map(row => row.runId)).size !== workers.length) throw new Error('duplicate run ID');
    snapshot.workers = workers;
    snapshot.state = registryFreshness === 'unknown' ? 'unavailable'
      : registryFreshness === 'stale' || workers.some(row => row.freshness === 'stale') ? 'stale' : 'ok';
  } catch {
    snapshot.state = 'invalid';
    snapshot.workers = [];
  }
  return snapshot;
}
