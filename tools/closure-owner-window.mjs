// PREPARED source. Import is inert; only direct CLI entry can use native custody.
import { readFile, lstat, realpath } from 'node:fs/promises';
import { appendFileSync, writeFileSync, lstatSync } from 'node:fs';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
import { performance } from 'node:perf_hooks';
import { createFixtureController, filesystemInspection, validateAdmission, sha256,
  WORKTREE, BASELINE, CANONICAL_BASELINE, RUNTIMES } from './closure-owner-fixture.mjs';

export const ADMISSION_FILE = WORKTREE + '/.runner/owner-window-runtime/RUNTIME-ADMISSION.json';
export const DRIVER_FILE = WORKTREE + '/tools/closure-owner-window.mjs';
export const MAX_WINDOW_MS = 120000;
const SHA = /^[a-f0-9]{64}$/;
const fail = code => { throw Error(code); };

/** Parent hashes this entire envelope externally, and final driver bytes separately.
 * fixtureAdmission is the unchanged controller's exact schema, not a new policy.
 */
export function validateWindowAdmission(bytes, expectedSha256, driverSha256, now) {
  if (!(typeof bytes === 'string' || Buffer.isBuffer(bytes)) || !SHA.test(expectedSha256 ?? '')) fail('WINDOW_ADMISSION_MISSING');
  if (sha256(bytes) !== expectedSha256) fail('WINDOW_ADMISSION_HASH');
  let a; try { a = JSON.parse(bytes.toString()); } catch { fail('WINDOW_ADMISSION_JSON'); }
  const fields = ['schema','state','manager','job','purpose','worktree','baseline','canonicalBaseline',
    'issuedAt','deadline','driverSha256','fixtureAdmission'];
  if (!a || JSON.stringify(Object.keys(a).sort()) !== JSON.stringify(fields.sort())) fail('WINDOW_ADMISSION_SCHEMA');
  if (a.schema !== 'closure-owner-window-runtime/v1' || a.state !== 'APPROVED' ||
      a.manager !== 'f46e2ca656b9' || a.job !== 'closure-owner-window-driver' ||
      a.purpose !== 'NEW_INTERACTIVE_OWNER_WINDOW' || a.worktree !== WORKTREE ||
      a.baseline !== BASELINE || a.canonicalBaseline !== CANONICAL_BASELINE) fail('WINDOW_ADMISSION_SCOPE');
  if (!SHA.test(driverSha256 ?? '') || a.driverSha256 !== driverSha256) fail('WINDOW_DRIVER_PIN');
  const issued = Date.parse(a.issuedAt), deadline = Date.parse(a.deadline);
  if (!Number.isFinite(now) || !Number.isFinite(issued) || !Number.isFinite(deadline) ||
      issued > now || deadline <= now || deadline <= issued || deadline - issued > MAX_WINDOW_MS) fail('WINDOW_DEADLINE');
  const fixtureBytes = JSON.stringify(a.fixtureAdmission);
  const fixtureHash = sha256(fixtureBytes);
  const fixture = validateAdmission(fixtureBytes, fixtureHash, now);
  if (fixture.issuedAt !== a.issuedAt || fixture.deadline !== a.deadline ||
      fixture.limits.starts !== 4 || fixture.limits.restarts !== 2 || fixture.limits.interruptions !== 2) fail('WINDOW_FIXTURE_BUDGET');
  return Object.freeze({ deadline, driverSha256, fixtureBytes, fixtureHash });
}

/** Only injectable PURE fakes are exposed. Native selection is private to CLI. */
export function runPureOwnerWindow(options) {
  if (options?.fake?.kind !== 'pure-mock' || options.fake.runtime !== false) fail('PURE_SEAM_ONLY');
  return runWindow({ ...options, factory: options.fake.createController, evidence: 'PURE_MOCK_NOT_RUNTIME_EVIDENCE' });
}

async function runWindow({ admissionBytes, expectedSha256, driverSha256, factory, clock, input, publish, evidence }) {
  const gate = validateWindowAdmission(admissionBytes, expectedSha256, driverSha256, clock.wall());
  const initialMono = clock.monotonic();
  if (!Number.isFinite(initialMono)) fail('MONOTONIC_CLOCK');
  const endMono = initialMono + Math.min(MAX_WINDOW_MS, gate.deadline - clock.wall());
  let lastMono = initialMono, terminal = null, failure = null, timer, detach, controller, sequence = 0;
  let serial = Promise.resolve();
  const restarted = new Set();
  const remaining = () => {
    const m = clock.monotonic();
    if (!Number.isFinite(m) || m < lastMono) fail('MONOTONIC_CLOCK');
    lastMono = m;
    return Math.min(endMono - m, gate.deadline - clock.wall());
  };
  const snapshot = () => {
    if (!controller) return undefined;
    const s = controller.status();
    return { ...s, evidence, modes: Object.fromEntries(Object.entries(s.modes).map(([mode, value]) =>
      [mode, { ...value, physical: 'NOT_OBSERVED' }])) };
  };
  const emit = (type, detail = {}) => publish({ id: `owner-window-${++sequence}`, type,
    timeUtc: new Date(clock.wall()).toISOString(), evidence, physical: 'NOT_OBSERVED',
    source: 'PREPARED_REQUIRES_INDEPENDENT_ACCEPTANCE', ...detail, controller: snapshot() });
  let finish;
  const done = new Promise(resolve => { finish = resolve; });
  const end = (reason, error) => {
    if (error && !failure) failure = error;
    if (!terminal) { terminal = reason; finish(); }
  };
  const enqueue = fn => {
    serial = serial.then(async () => {
      if (terminal) return;
      if (remaining() <= 0) { end('deadline'); return; }
      await fn();
    }).catch(error => end('error', error));
  };
  const arm = () => {
    const ms = remaining();
    if (ms <= 0) end('deadline');
    else timer = clock.setTimeout(() => { try { arm(); } catch (error) { end('error', error); } }, ms);
  };
  try {
    controller = factory(gate);
    detach = input.subscribe({
      line(line) {
        if (terminal) return;
        // No trim, alias, argv parsing or caller-selected mode/path.
        if (line === 'stop') { end('stop'); return; }
        if (line !== 'restart mesh' && line !== 'restart standalone') {
          enqueue(async () => emit('DENIED', { reason: 'MALFORMED_COMMAND' })); return;
        }
        const mode = line.slice(8);
        enqueue(async () => {
          if (restarted.has(mode)) { emit('DENIED', { reason: 'RESTART_ALREADY_CONSUMED', mode }); return; }
          restarted.add(mode); // An attempted restart cannot be retried after failure.
          const generation = controller.status().modes[mode].generation;
          await controller.restart(mode, generation);
          if (remaining() <= 0) { end('deadline'); return; }
          emit('READY', { mode, reason: 'restart', urls: urls() });
        });
      },
      eof() { end('EOF'); }, error(error) { end('input-error', error); },
      signal(signal) { end(signal); },
    });
    function urls() {
      const s = controller.status();
      if (['mesh','standalone'].some(mode => s.modes[mode].runtimeVerified !== true)) fail('READINESS_UNVERIFIED');
      return Object.fromEntries(['mesh','standalone'].map(mode => [mode, s.modes[mode].previewUrl]));
    }
    enqueue(async () => {
      await controller.validate();
      if (terminal || remaining() <= 0) { end('deadline'); return; }
      emit('CHECKPOINT', { reason: 'exact-gate-validated', admissionSha256: expectedSha256 });
      await controller.launch('mesh');
      if (terminal || remaining() <= 0) { end('deadline'); return; }
      await controller.launch('standalone');
      if (terminal || remaining() <= 0) { end('deadline'); return; }
      emit('READY', { urls: urls(), deadline: new Date(gate.deadline).toISOString(), pcLoopbackOnly: true });
    });
    arm();
    await done;
  } catch (error) { end('error', error); }
  finally {
    clock.clearTimeout(timer);
    try { detach?.(); } catch (error) { failure ??= error; }
    await serial;
    try { await controller?.close(); } catch (error) { failure ??= error; }
    try { emit(failure ? 'FAILED' : 'STOPPED', { reason: terminal, error: failure?.message,
      cleanup: failure ? 'NOT_CLAIMED' : 'CONTROLLER_CLOSE_COMPLETED' }); }
    catch (error) { failure ??= error; }
  }
  if (failure) throw failure;
  return snapshot();
}

async function exactRead(file) {
  const root = path.resolve(WORKTREE);
  if ((await realpath(root)).toLowerCase() !== root.toLowerCase()) fail('LINKED_ROOT');
  const relative = path.relative(root, path.resolve(file));
  if (relative.startsWith('..') || path.isAbsolute(relative)) fail('PATH_SCOPE');
  let current = root;
  for (const part of relative.split(path.sep)) {
    current = path.join(current, part);
    if ((await lstat(current)).isSymbolicLink()) fail('LINKED_PATH');
  }
  return readFile(current);
}

function managerInput() {
  return { subscribe(handlers) {
    let buffer = '';
    const data = chunk => {
      buffer += chunk.toString('utf8');
      while (buffer.includes('\n')) {
        const index = buffer.indexOf('\n');
        let line = buffer.slice(0, index); buffer = buffer.slice(index + 1);
        if (line.endsWith('\r')) line = line.slice(0, -1);
        if (line.length > 64) { handlers.error(Error('INPUT_LIMIT')); return; }
        handlers.line(line);
      }
      if (buffer.length > 64) handlers.error(Error('INPUT_LIMIT'));
    };
    const eof = () => handlers.eof(); // Partial final line is never an exact command.
    const error = e => handlers.error(e);
    const sigint = () => handlers.signal('SIGINT'), sigterm = () => handlers.signal('SIGTERM');
    process.stdin.on('data', data).on('end', eof).on('error', error);
    process.on('SIGINT', sigint).on('SIGTERM', sigterm);
    if (process.stdin.readableEnded || process.stdin.destroyed) handlers.eof();
    return () => {
      process.stdin.off('data', data).off('end', eof).off('error', error).pause();
      process.off('SIGINT', sigint).off('SIGTERM', sigterm);
    };
  } };
}

async function main() {
  // The only argument is Echo's separately held hash. Never accept an admission path.
  if (process.argv.length !== 3 || !SHA.test(process.argv[2]) ||
      path.win32.normalize(process.execPath).toLowerCase() !== path.win32.normalize(RUNTIMES.node).toLowerCase() ||
      path.win32.resolve(process.cwd()).toLowerCase() !== path.win32.resolve(WORKTREE).toLowerCase()) fail('CLI_SCOPE');
  const expectedSha256 = process.argv[2];
  const admissionBytes = await exactRead(ADMISSION_FILE);
  const driverSha256 = sha256(await exactRead(DRIVER_FILE));
  const gate = validateWindowAdmission(admissionBytes, expectedSha256, driverSha256, Date.now());
  const inspection = filesystemInspection();
  const pinDriver = async () => {
    if (sha256(await exactRead(DRIVER_FILE)) !== gate.driverSha256) fail('WINDOW_DRIVER_DRIFT');
  };
  const clock = { wall: Date.now, monotonic: () => performance.now(), setTimeout, clearTimeout };
  await runWindow({ admissionBytes, expectedSha256, driverSha256, clock, input: managerInput(),
    evidence: 'NATIVE_RECEIPTS_REQUIRE_PARENT_QUALIFICATION',
    factory: g => createFixtureController({ admissionBytes: g.fixtureBytes, expectedSha256: g.fixtureHash, clock,
      inspection: { async pins(a) { await pinDriver(); await inspection.pins(a); }, fresh: inspection.fresh } }),
    publish(event) {
      const dir = WORKTREE + '/.runner/owner-window-runtime';
      // Parent must prepare the directory; never create/adopt runtime stores here.
      const json = JSON.stringify(event);
      for (const name of ['WORKER-EVENTS.jsonl','STATUS.json']) {
        try {
          const stat = lstatSync(dir + '/' + name);
          if (stat.isSymbolicLink() || !stat.isFile()) fail('LINKED_STATUS');
        } catch (error) { if (error.code !== 'ENOENT') throw error; }
      }
      appendFileSync(dir + '/WORKER-EVENTS.jsonl', json + '\n');
      writeFileSync(dir + '/STATUS.json', json + '\n');
      process.stdout.write(json + '\n');
    },
  });
}

if (process.argv[1] && import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href) {
  main().catch(error => { process.stderr.write(JSON.stringify({ type: 'FAILED', reason: error.message,
    runtime: 'NOT_CLAIMED', physical: 'NOT_OBSERVED' }) + '\n'); process.exitCode = 1; });
}
