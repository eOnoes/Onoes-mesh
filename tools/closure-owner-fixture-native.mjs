// In-process manager backend. Import is inert; no public control endpoint exists.
import { spawn } from 'node:child_process';
import { mkdir, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { performance } from 'node:perf_hooks';
import { WORKTREE, ROOTS, RUNTIMES, launchSpec, validateAdmission, filesystemInspection } from './closure-owner-fixture.mjs';

const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);
const normalized = p => path.win32.normalize(p).toLowerCase();
const requireThat = (condition, code) => { if (!condition) throw Error(code); };

// Pure directory identity only; executable/file identifiers retain their comparison.
export const sameNativeDirectory = (a, b) => typeof a === 'string' && typeof b === 'string' &&
  /^[A-Za-z]:[\\/]/.test(a) && /^[A-Za-z]:[\\/]/.test(b) &&
  path.win32.resolve(a).toLowerCase() === path.win32.resolve(b).toLowerCase();

/** Same ready-receipt predicate used before any service launch. */
export function validateHarnessRetention(identities, harnessPid, observerPid) {
  const manager = identities.find(i => i.pid === harnessPid);
  const observer = identities.find(i => i.pid === observerPid);
  requireThat(manager && observer && observer.parentPid === harnessPid &&
    sameNativeDirectory(manager.worktree, WORKTREE) && sameNativeDirectory(manager.currentDirectory, WORKTREE) &&
    normalized(manager.executable) === normalized(RUNTIMES.node) && !manager.commandLineError &&
    normalized(observer.executable) === normalized(RUNTIMES.observer), 'HARNESS_RETENTION');
  return { manager, observer };
}

/** Pure descriptor check: npm is the launch root; m1-serve is its descendant. */
export function validateNativeSpec(spec) {
  const mode = Object.keys(ROOTS).find(k => k !== 'evidence' && ROOTS[k] === spec?.dataDir);
  requireThat(mode && same(spec, launchSpec(mode)), 'NATIVE_DESCRIPTOR');
  requireThat(spec.env.PYTHONDONTWRITEBYTECODE === '1' && !('NODE_OPTIONS' in spec.env) &&
    !('PYTHONPATH' in spec.env), 'NATIVE_ENVIRONMENT');
  return mode;
}

export function validateNativeIdentity(i, { argv, cwd = WORKTREE, executable = RUNTIMES.node } = {}) {
  requireThat(i && Number.isSafeInteger(i.pid) && i.pid > 0 && ![process.pid,2612068,3671748].includes(i.pid) &&
    /^\d+$/.test(i.creationTime100ns ?? '') && !i.commandLineError && !i.currentDirectoryError &&
    normalized(i.executable) === normalized(executable) && sameNativeDirectory(i.currentDirectory, cwd) &&
    Array.isArray(i.argv) && i.argv.length === argv.length &&
    i.argv.every((v, n) => n === 0 ? (normalized(v) === normalized(argv[n]) ||
      executable === RUNTIMES.node && argv[1] === 'test/m1-serve.mjs' && v === 'node') : v === argv[n]), 'NATIVE_IDENTITY');
  return i;
}

// Shared shutdown algorithm; the pure seam never selects a native monitor.
async function stopOwnedApp(app, { budget, collect, snapshot, bounded, call, now, pause, save }, { interruption = false } = {}) {
  budget(); await collect(app); requireThat(app.root, 'NPM_CUSTODY_UNAVAILABLE');
  const depth = i => { let n = 0, p = i; const seen = new Set();
    while (p && !seen.has(p.pid)) { seen.add(p.pid); n++; p = [...app.identities.values()].find(v =>
      v.pid === p.parentPid && v.creationTime100ns === p.parentCreationTime100ns); } return n; };
  // Workloads must close before their console infrastructure. Keep the observer
  // outside this app's acquired tree and alive until every owned mode is verified.
  const held = [...app.identities.values()].sort((a,b) =>
    Number(a.custodyClass === 'infrastructure') - Number(b.custodyClass === 'infrastructure') || depth(b) - depth(a));
  if (interruption) {
    requireThat(app.server, 'INTERRUPTION_SERVER_UNAVAILABLE');
    held.sort((a,b) => (b.pid === app.server.pid ? 1 : 0) - (a.pid === app.server.pid ? 1 : 0));
  }
  const errors = [];
  for (const identity of held) {
    try {
      budget(); const records = await snapshot(); const current = records.find(i => i.pid === identity.pid &&
        i.creationTime100ns === identity.creationTime100ns);
      requireThat(current, 'ORIGINAL_HANDLE_MISSING');
      if (current.exitSignaled) continue;
      requireThat(current.executable === identity.executable && current.commandLine === identity.commandLine &&
        same(current.argv, identity.argv), 'NATIVE_IDENTITY_CHANGED');
      await bounded(call('kill', identity));
    } catch (error) {
      errors.push(Error(`${app.mode}:${identity.pid}:${identity.creationTime100ns}:${error.message}`, { cause: error }));
    }
  }
  if (errors.length) {
    app.cleanupErrors = errors.slice(0, 32).map(error => error.message.slice(0, 4096));
    await save(app); throw new AggregateError(errors, 'ORIGINAL_CONTROL_UNVERIFIED');
  }
  const end = now() + Math.min(10000, budget());
  while (now() < end) {
    const records = await collect(app);
    if ([...app.identities.values()].every(i => records.some(r => r.pid === i.pid &&
      r.creationTime100ns === i.creationTime100ns && r.exitSignaled && Number.isInteger(r.exitCode)))) {
      await bounded(app.closed); app.cleanupVerified = true; await save(app); return;
    }
    await pause();
  }
  await save(app); throw Error('ORIGINAL_EXITS_UNVERIFIED');
}

async function closeOwnedApps(apps, stop, finish, save) {
  const errors = [];
  for (const app of apps) if (app.child?.pid && !app.cleanupVerified) {
    try { await stop(app); } catch (error) {
      app.failure = `${app.mode}:${error.message}`;
      try { await save(app); } catch (saveError) { errors.push(saveError); }
      errors.push(Error(app.failure, { cause: error }));
    }
  }
  // A broken observer cannot be replaced by absence checks or PID-only control.
  if (errors.length) throw new AggregateError(errors, 'NATIVE_CLEANUP_UNVERIFIED');
  await finish();
}

export async function runPureFixtureShutdown({ fake, apps, interruption = false } = {}) {
  requireThat(fake?.kind === 'pure-mock' && fake.runtime === false, 'PURE_SEAM_ONLY');
  await closeOwnedApps(apps, app => stopOwnedApp(app, fake, { interruption }), fake.finish, fake.save);
  return { evidence: 'PURE_MOCK_NOT_RUNTIME_EVIDENCE' };
}

export function createNativeEffects({ admissionBytes, expectedSha256, guard, remaining } = {}) {
  const bytes = Buffer.from(admissionBytes ?? '');
  // Validation is also enforced here; importing/calling a factory is never admission.
  const authorize = () => { const a = validateAdmission(bytes, expectedSha256); guard(); return a; };
  let monitor, closed = false, prepared = false, last = -Infinity;
  const apps = new Set();
  const now = () => { const t = performance.now(); requireThat(t >= last, 'NATIVE_MONOTONIC'); last = t; return t; };
  const budget = () => { const ms = remaining(); requireThat(Number.isFinite(ms) && ms > 0, 'NATIVE_CLEANUP_DEADLINE'); return ms; };
  const pause = () => new Promise(resolve => setTimeout(resolve, 20));
  const bounded = async (promise, maxMs = 15000) => {
    let timer;
    try { return await Promise.race([promise, new Promise((_, reject) => {
      timer = setTimeout(() => reject(Error('NATIVE_OPERATION_DEADLINE')), Math.min(maxMs, budget()));
    })]); } finally { clearTimeout(timer); }
  };
  async function save(app) {
    if (!monitor) return;
    await writeFile(path.win32.join(WORKTREE, ROOTS.evidence, `generation-${app.mode}-${app.generation}.json`),
      JSON.stringify({ mode: app.mode, generation: app.generation, npmPid: app.child?.pid, server: app.server,
        retained: [...app.identities.values()], startup: app.info, failure: app.failure, cleanupErrors: app.cleanupErrors,
        cleanupVerified: app.cleanupVerified === true, stdout: app.stdout, stderr: app.stderr }, null, 2));
  }
  const snapshot = () => bounded(monitor.call('snapshot'));
  function acquireTree(app, records) {
    for (const i of records) {
      const key = `${i.pid}:${i.creationTime100ns}`;
      if (app.identities.has(key)) app.identities.set(key, i);
    }
    const root = records.find(i => i.pid === app.child.pid &&
      (!app.root || i.creationTime100ns === app.root.creationTime100ns));
    if (!root) return;
    if (!app.root) {
      validateNativeIdentity(root, { argv: [RUNTIMES.node, RUNTIMES.npm, 'start'] });
      requireThat(root.parentPid === process.pid, 'NPM_PARENT'); app.root = root;
    }
    app.identities.set(`${root.pid}:${root.creationTime100ns}`, root);
    let changed = true;
    while (changed) {
      changed = false;
      for (const i of records) {
        const key = `${i.pid}:${i.creationTime100ns}`;
        if (app.identities.has(key)) continue;
        const parent = [...app.identities.values()].find(p => p.pid === i.parentPid &&
          p.creationTime100ns === i.parentCreationTime100ns);
        if (parent) {
          requireThat(![2612068,3671748,process.pid,monitor.child.pid].includes(i.pid) &&
            !i.commandLineError && Array.isArray(i.argv) && sameNativeDirectory(i.worktree, WORKTREE), 'DESCENDANT_IDENTITY');
          app.identities.set(key, i); changed = true;
        }
      }
    }
  }
  async function collect(app) { const records = await snapshot(); acquireTree(app, records); await save(app); return records; }
  const stopApp = (app, options) => stopOwnedApp(app, { budget, collect, snapshot, bounded,
    call: (...args) => monitor.call(...args), now, pause, save }, options);
  return Object.freeze({
    kind: 'native', runtime: true,
    async retainManager() {
      const a = authorize(); requireThat(!monitor && !closed, 'MANAGER_DUPLICATE');
      await filesystemInspection().pins(a); await filesystemInspection().fresh(); authorize();
      // Exclusive evidence root creation precedes observer file generation.
      await mkdir(path.win32.join(WORKTREE, ROOTS.evidence)); authorize();
      const { custody } = await import('../test/m6-standalone-fixture.mjs');
      const env = Object.freeze({ ...launchSpec('standalone').env, PYTHONPATH: WORKTREE });
      monitor = await custody(path.win32.join(WORKTREE, ROOTS.evidence), { env, timeoutMs: Math.min(15000, budget()) });
      validateHarnessRetention(monitor.receipt.ready.identities, process.pid, monitor.child.pid);
      authorize();
    },
    async prepareExclusive(roots) {
      authorize(); requireThat(monitor && !prepared && same(roots, ROOTS), 'PREPARE_SCOPE');
      for (const mode of ['mesh','standalone']) { authorize(); await mkdir(path.win32.join(WORKTREE, ROOTS[mode])); }
      prepared = true;
    },
    async launchRetained(spec, generation) {
      authorize(); const mode = validateNativeSpec(spec);
      requireThat(monitor && prepared && !closed && Number.isSafeInteger(generation) && generation > 0, 'NATIVE_NOT_PREPARED');
      const app = { mode, generation, identities: new Map(), stdout: '', stderr: '' }; apps.add(app);
      try {
        authorize();
        const child = spawn(spec.executable, spec.argv, { cwd: spec.cwd, shell: false, windowsHide: true,
          env: spec.env, stdio: ['ignore','pipe','pipe'] }); app.child = child;
        app.closed = new Promise(resolve => child.once('close', (code, signal) => resolve({ code, signal })));
        child.on('error', error => { app.failure = error.message; });
        child.stderr.on('data', b => { app.stderr = (app.stderr + b).slice(-65536); });
        let buffer = '';
        child.stdout.on('data', b => {
          app.stdout = (app.stdout + b).slice(-65536); buffer += b;
          if (buffer.length >= 262144) { app.failure = 'STARTUP_OUTPUT_LIMIT'; buffer = ''; return; }
          let index; while ((index = buffer.indexOf('\n')) >= 0) {
            const line = buffer.slice(0,index); buffer = buffer.slice(index+1);
            try { const value = JSON.parse(line); if (value.event === 'mesh_listening') app.info = value; } catch { /* npm banner */ }
          }
        });
        const end = now() + Math.min(15000, budget());
        while (now() < end) {
          authorize(); const records = await collect(app);
          if (app.info && app.root) {
            const i = [...app.identities.values()].find(r => r.pid === app.info.pid && !r.exitSignaled);
            if (i) {
              validateNativeIdentity(i, { argv: [RUNTIMES.node, 'test/m1-serve.mjs'] });
              requireThat(i.pid !== app.root.pid && app.info.dataDir === spec.dataDir && app.info.mode === mode &&
                app.info.previewUrl === spec.previewUrl, 'SERVER_DESCRIPTOR');
              app.server = i; await save(app);
              return Object.freeze({ handle: app, generation, pid: i.pid, creationTime100ns: i.creationTime100ns,
                executable: RUNTIMES.node, argv: Object.freeze([RUNTIMES.node,'test/m1-serve.mjs']),
                retainedBeforeControl: true, npmPid: app.root.pid });
            }
          }
          if (app.failure || child.exitCode !== null || child.signalCode !== null) throw Error('NATIVE_STARTUP_FAILED');
          await pause();
        }
        throw Error('NATIVE_STARTUP_DEADLINE');
      } catch (error) {
        app.failure = error.message; await save(app);
        try { if (app.child?.pid) await stopApp(app); }
        catch (cleanup) { throw new AggregateError([error,cleanup], 'STARTUP_CLEANUP_UNVERIFIED'); }
        throw error;
      }
    },
    async listeners(held) {
      authorize(); const app = held.handle; requireThat(apps.has(app) && app.generation === held.generation, 'NATIVE_GENERATION');
      await collect(app); await bounded(monitor.call('listeners'));
      const rows = monitor.receipt.stages.at(-1).listeners;
      const records = await collect(app);
      const owned = rows.filter(l => [...app.identities.values()].some(i => i.pid === l.pid &&
        i.creationTime100ns === l.creationTime100ns && !i.exitSignaled));
      requireThat(records.some(i => i.pid === held.pid && i.creationTime100ns === held.creationTime100ns &&
        !i.exitSignaled), 'LISTENER_GENERATION_EXITED');
      requireThat(owned.length > 0 && owned.every(l => l.host === '127.0.0.1' && ![4317,8446].includes(l.port)), 'OWNED_LOOPBACK');
      const server = owned.filter(l => l.pid === held.pid);
      const backend = new URL(app.info.url);
      requireThat(backend.hostname === '127.0.0.1' && server.some(l => l.port === Number(backend.port)) &&
        server.some(l => l.port === Number(launchSpec(app.mode).env.MESH_PREVIEW_PORT)), 'EXACT_PREVIEW_LISTENER');
      return server.map(l => ({ ...l, generation: held.generation }));
    },
    async revalidate(held) {
      budget(); requireThat(apps.has(held.handle) && held.handle.generation === held.generation, 'NATIVE_GENERATION');
      const records = await collect(held.handle); const i = records.find(r => r.pid === held.pid && r.creationTime100ns === held.creationTime100ns);
      validateNativeIdentity(i, { argv: held.argv });
      return { ...held, live: !i.exitSignaled };
    },
    async stopRetained(held, options) { requireThat(apps.has(held.handle) && held.generation === held.handle.generation, 'NATIVE_GENERATION'); await stopApp(held.handle, options); },
    async originalExit(held) {
      const records = await collect(held.handle); const i = records.find(r => r.pid === held.pid && r.creationTime100ns === held.creationTime100ns);
      return { handle: held.handle, generation: held.generation, signaled: held.handle.cleanupVerified === true && i?.exitSignaled === true, exitCode: i?.exitCode };
    },
    async close() {
      if (closed) return;
      await closeOwnedApps(apps, stopApp, async () => { if (monitor) await bounded(monitor.finish()); }, save);
      closed = true;
    },
  });
}
