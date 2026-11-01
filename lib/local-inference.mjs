import { randomUUID } from 'node:crypto';
import os from 'node:os';
import { TaskError } from './task-store.mjs';

// Server-owned identity. No request may select a node, model, or launch setting.
export const LOCAL_PROFILE = Object.freeze({
  nodeId: 'this-pc', runtimeId: 'llama-cpp-cuda-b11446', id: 'qwen38-flash-next-q6',
  model: 'Qwen3.8-Flash-Next-UD-Q6_K_XL',
  modelRevision: '38bb39ee97821de2c9009abb7e93950eec396e66', shards: 6,
  executable: 'E:\\Echo-DB\\tools\\llama-b11446-cuda12.4\\llama-server.exe',
  executableSha256: '485972547DB06AB4864628F59F099FC2B7FCF0FEF1ED79D0D8871D226FFCCEB1',
  cwd: 'E:\\Echo-DB\\tools\\llama-b11446-cuda12.4',
});
export const LOCAL_LIMITS = Object.freeze({ freshMs: 5000, proposalMs: 30000,
  controlMs: 2000, chatMs: 15000, promptBytes: 3000, outputBytes: 16384 });

// Deliberately no native spawn/kill/fetch path until the Windows retained-handle,
// shard manifest, exact argv, listener, GPU attribution and exit gates qualify.
// Environment variables and browser input cannot lift this gate.
export function createDisabledLocalAdapter(reason = 'NATIVE_QUALIFICATION_REQUIRED') {
  return Object.freeze({ enabled: false, source: 'none', reason });
}
const exact = (value, keys) => value && Object.getPrototypeOf(value) === Object.prototype &&
  Object.keys(value).length === keys.length && keys.every(k => Object.hasOwn(value, k));
const reject = (status, message) => { throw new TaskError(status, message); };
const identityKeys = ['pid', 'createdAt', 'executable', 'executableSha256', 'cwd', 'argvHash'];
const same = (a, b) => a && b && identityKeys.every(k => a[k] === b[k]);
const validIdentity = v => v && Number.isSafeInteger(v.pid) && v.pid > 0 &&
  typeof v.createdAt === 'string' && Number.isFinite(Date.parse(v.createdAt)) &&
  v.executable === LOCAL_PROFILE.executable && v.executableSha256 === LOCAL_PROFILE.executableSha256 &&
  v.cwd === LOCAL_PROFILE.cwd && /^[a-f0-9]{64}$/.test(v.argvHash);

export function createLocalInference({ adapter = createDisabledLocalAdapter(), now = Date.now } = {}) {
  if (adapter.enabled && (!['disposable_fixture', 'qualified_native'].includes(adapter.source) ||
      ['observe', 'start', 'stop', 'chat'].some(k => typeof adapter[k] !== 'function')))
    throw new TypeError('Invalid local inference adapter.');
  let state = adapter.enabled ? 'UNKNOWN' : 'UNAVAILABLE', lease = null, observed = null;
  let revision = 0, busy = false, pending = null, lastTime = 0;
  const receipts = new Map();
  function time() {
    const at = now();
    if (!Number.isSafeInteger(at) || at < lastTime) { state = 'UNCERTAIN'; reject(409, 'Inference clock is uncertain.'); }
    lastTime = at; return at;
  }
  function transition(next) { if (state !== next) { state = next; revision++; } }
  const fresh = at => Number.isSafeInteger(at) && at <= time() && time() - at <= LOCAL_LIMITS.freshMs;
  async function bounded(work, ms, external) {
    const controller = new AbortController(); let timer;
    const abort = () => controller.abort();
    external?.addEventListener('abort', abort, { once: true });
    try {
      if (external?.aborted) throw new Error('aborted');
      return await Promise.race([work(controller.signal), new Promise((_, fail) => {
        timer = setTimeout(() => { controller.abort(); fail(new Error('deadline')); }, ms);
        controller.signal.addEventListener('abort', () => fail(new Error('aborted')), { once: true });
        if (controller.signal.aborted) fail(new Error('aborted'));
      })]);
    } finally { clearTimeout(timer); external?.removeEventListener('abort', abort); controller.abort(); }
  }
  async function read() {
    if (!adapter.enabled) return;
    try {
      const value = await bounded(signal => adapter.observe({ signal }), LOCAL_LIMITS.controlMs);
      observed = value;
      if (!fresh(value?.observedAt)) throw new Error('stale');
      if (lease) {
        // Exit must refer to the original retained process, never absence by PID.
        if (value.exited === true && value.exitVerified === true && same(value.identity, lease) &&
            value.listenerAbsent === true) { lease = null; transition('STOPPED'); }
        else if (validIdentity(value.identity) && same(value.identity, lease) && value.retainedHandle === true &&
            value.listener?.pid === lease.pid && value.listener?.host === '127.0.0.1' &&
            value.health?.ok === true && fresh(value.health.observedAt) &&
            value.health.profileId === LOCAL_PROFILE.id && value.gpuMapping === 'VERIFIED') transition('RUNNING');
        else transition('UNCERTAIN');
      } else if (state !== 'UNCERTAIN' && value.custodyClear === true && value.listenerAbsent === true) transition('STOPPED');
      else transition('UNCERTAIN');
    } catch { observed = null; transition('UNCERTAIN'); }
  }
  function snapshot() {
    const at = time();
    if (adapter.enabled && !busy && observed && (!fresh(observed.observedAt) ||
        (state === 'RUNNING' && !fresh(observed.health?.observedAt)))) transition('UNCERTAIN');
    const available = adapter.enabled && !busy;
    const reason = !adapter.enabled ? adapter.reason : busy ? 'OPERATION_IN_PROGRESS' :
      state === 'UNCERTAIN' || state === 'UNKNOWN' ? 'OWNERSHIP_OR_HEALTH_UNKNOWN' : null;
    return { schemaVersion: 'mesh-local-inference/v1', nodeId: LOCAL_PROFILE.nodeId,
      runtimeId: LOCAL_PROFILE.runtimeId, profile: LOCAL_PROFILE, source: adapter.source,
      state, revision, servedAt: new Date(at).toISOString(),
      observedAt: observed && fresh(observed.observedAt) ? new Date(observed.observedAt).toISOString() : null,
      freshness: observed && fresh(observed.observedAt) ? 'FRESH' : 'UNAVAILABLE', freshForMs: LOCAL_LIMITS.freshMs,
      runtime: state === 'RUNNING' ? { ...lease, status: 'VERIFIED' } : { status: 'UNKNOWN' },
      health: state === 'RUNNING' ? 'HEALTHY' : 'UNKNOWN',
      telemetry: { sampledAt: new Date(at).toISOString(), source: 'node_os',
        cpuUtilizationPercent: 'UNKNOWN', ramTotalBytes: os.totalmem(), ramFreeBytes: os.freemem(),
        gpu: 'UNAVAILABLE', vram: 'UNAVAILABLE', gpuMapping: state === 'RUNNING' ? 'VERIFIED' : 'UNKNOWN' },
      controls: { load: available && state === 'STOPPED', stop: available && state === 'RUNNING',
        unload: available && state === 'RUNNING', chat: available && state === 'RUNNING', reason },
    };
  }
  function requireAdmission(admitted) { if (!admitted()) reject(401, 'Local session expired.'); }
  async function exclusive(work) {
    if (busy) reject(409, 'Inference operation already in progress.');
    busy = true;
    try { return await work(); } finally { busy = false; }
  }
  return Object.freeze({
    async status() {
      if (!busy) await exclusive(read);
      return snapshot();
    },
    async propose(action, body, session, admitted) {
      if (!['load', 'stop', 'unload'].includes(action) || !exact(body, [])) reject(400, 'Fixed profile only; no configuration accepted.');
      return exclusive(async () => {
        await read(); requireAdmission(admitted);
        if (!adapter.enabled || (action === 'load' ? state !== 'STOPPED' : state !== 'RUNNING')) reject(409, 'Inference control unavailable. Refresh status.');
        const proposal = { id: randomUUID(), action, state: 'PROPOSED', profile: LOCAL_PROFILE,
          revision, expiresAt: time() + LOCAL_LIMITS.proposalMs };
        pending = { ...proposal, session, identity: lease && { ...lease } };
        return { proposal };
      });
    },
    async approve(body, session, admitted) {
      if (!exact(body, ['proposalId', 'confirm']) || body.confirm !== true) reject(400, 'Explicit proposal confirmation required.');
      return exclusive(async () => {
        const p = pending;
        if (!p || p.id !== body.proposalId || p.session !== session || p.expiresAt <= time()) reject(409, 'Proposal is missing, expired, or belongs to another session.');
        await read(); requireAdmission(admitted);
        if (p.revision !== revision || (p.action === 'load' ? state !== 'STOPPED' : state !== 'RUNNING' || !same(lease, p.identity))) reject(409, 'Proposal evidence changed. Refresh and propose again.');
        pending = null; // Consume before executing: approval replay cannot start twice.
        const receipt = { id: randomUUID(), proposalId: p.id, nodeId: LOCAL_PROFILE.nodeId,
          runtimeId: LOCAL_PROFILE.runtimeId, profileId: LOCAL_PROFILE.id, action: p.action,
          authorizedAt: new Date(time()).toISOString(), state: 'AUTHORIZED' };
        try {
          transition(p.action === 'load' ? 'STARTING' : 'STOPPING');
          if (p.action === 'load') {
            const started = await bounded(signal => adapter.start(LOCAL_PROFILE, { signal }), LOCAL_LIMITS.controlMs);
            if (!validIdentity(started)) throw new Error('identity');
            lease = Object.freeze(Object.fromEntries(identityKeys.map(k => [k, started[k]])));
          } else {
            await bounded(signal => adapter.stop(lease, { signal }), LOCAL_LIMITS.controlMs);
          }
          await read();
          if (p.action === 'load' ? state !== 'RUNNING' : state !== 'STOPPED') transition('UNCERTAIN');
        } catch { observed = null; transition('UNCERTAIN'); }
        receipt.state = state; receipt.completedAt = new Date(time()).toISOString();
        receipt.readBackVerified = p.action === 'load' ? state === 'RUNNING' : state === 'STOPPED';
        receipts.set(receipt.id, { session, receipt });
        if (receipts.size > 64) receipts.delete(receipts.keys().next().value);
        return { receipt, status: snapshot() };
      });
    },
    receipt(id, session) {
      const entry = receipts.get(id);
      if (!entry || entry.session !== session) reject(404, 'Receipt unavailable in this session.');
      return { receipt: entry.receipt };
    },
    async chat(body, admitted, signal) {
      if (!exact(body, ['prompt']) || typeof body.prompt !== 'string' || !body.prompt.trim() ||
          Buffer.byteLength(body.prompt) > LOCAL_LIMITS.promptBytes) reject(400, 'A prompt of 1..3000 UTF-8 bytes is required.');
      return exclusive(async () => {
        await read(); requireAdmission(admitted);
        if (state !== 'RUNNING') reject(409, 'Chat requires a verified RUNNING runtime.');
        try {
          const response = await bounded(async innerSignal => {
            const stream = await adapter.chat({ prompt: body.prompt, maxTokens: 512, stream: true }, { signal: innerSignal });
            let output = '', bytes = 0;
            for await (const chunk of stream) {
              if (innerSignal.aborted || typeof chunk !== 'string') throw new Error('invalid');
              bytes += Buffer.byteLength(chunk);
              if (bytes > LOCAL_LIMITS.outputBytes) throw new Error('output limit');
              output += chunk;
            }
            return output;
          }, LOCAL_LIMITS.chatMs, signal);
          await read(); requireAdmission(admitted);
          if (state !== 'RUNNING') throw new Error('readback');
          return { nodeId: LOCAL_PROFILE.nodeId, runtimeId: LOCAL_PROFILE.runtimeId, response };
        } catch { observed = null; transition('UNCERTAIN'); reject(503, 'Chat result UNKNOWN. Refresh status before another operation.'); }
      });
    },
  });
}
