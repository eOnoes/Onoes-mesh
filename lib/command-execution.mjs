import { spawn } from 'node:child_process';
import { access, realpath } from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';
import { fileURLToPath } from 'node:url';
import { validateProposal } from './command-proposals.mjs';

export const EXECUTION_ROOT = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const ROOT = EXECUTION_ROOT;
// Explicit installed native runtime; no PATH, launcher, PYTHONPATH or HTTP override.
const PYTHON = 'C:\\Python314\\python.exe';
export const GIT = 'C:\\Program Files\\Git\\cmd\\git.exe';
const NODE = 'C:\\Program Files\\node.exe';
const SLOW = path.join(ROOT, 'lib', 'slow-command.mjs');
const fixedArgv = () => [[NODE, '--version'], [GIT, 'status'], [NODE, SLOW]];

function validatePlan(plan) {
  if (!plan || Object.keys(plan).sort().join(',') !== 'argv,cwd' || plan.cwd !== ROOT ||
      !Array.isArray(plan.argv) || !fixedArgv().some(argv =>
        argv.length === plan.argv.length && argv.every((value, i) => value === plan.argv[i])))
    throw new Error('Invalid fixed command plan.');
  // Snapshot before asynchronous work so callers cannot change a checked plan.
  return { argv: [...plan.argv], cwd: ROOT };
}
export function validateOwnedResult(result) {
  if (!result || !['PASS','FAIL'].includes(result.status) || typeof result.cleanupVerified !== 'boolean' ||
      typeof result.timedOut !== 'boolean' || typeof result.stdout !== 'string' || typeof result.stderr !== 'string' ||
      !(result.rootPid === null || Number.isSafeInteger(result.rootPid) && result.rootPid > 0) ||
      !(result.rootExitCode === null || Number.isSafeInteger(result.rootExitCode) && result.rootExitCode >= 0 && result.rootExitCode <= 0xffffffff) ||
      !(result.error === null || typeof result.error === 'string') ||
      (result.cancelled !== undefined && typeof result.cancelled !== 'boolean') ||
      (result.status === 'PASS' && (!result.cleanupVerified || result.timedOut || result.cancelled || result.rootExitCode !== 0 || !result.rootPid || result.error !== null)))
    throw new Error('Invalid ownership result.');
  return result;
}
export async function prepareExecution(proposal) {
  const fixed = validateProposal(proposal);
  if (process.platform !== 'win32') throw new Error('Native Windows ownership unavailable.');
  const cwd = await realpath(ROOT);
  if (cwd.toLowerCase() !== path.resolve(ROOT).toLowerCase()) throw new Error('Invalid fixed cwd.');
  const argv = fixed.command === 'node --version' ? [NODE, '--version'] :
    fixed.command === 'git status' ? [GIT, 'status'] :
    fixed.command === 'node lib/slow-command.mjs' ? [NODE, SLOW] : null;
  const executable = argv?.[0];
  if (!executable || !path.isAbsolute(executable)) throw new Error('Invalid fixed command.');
  if (process.execPath !== NODE) throw new Error('Invalid installed Node runtime.');
  await access(PYTHON); await access(executable);
  await access(path.join(ROOT, 'lib', 'owned-command.py'));
  if (argv[1] === SLOW && await realpath(SLOW) !== SLOW) throw new Error('Invalid fixed script.');
  return validatePlan({ argv, cwd });
}

// Existing callers still await one promise. Opt in with { signal } and await
// its FAIL result after native cleanup; abort never kills the ownership bridge.
export function executeOwned(plan, { signal } = {}) {
  return new Promise((resolve, reject) => {
    plan = validatePlan(plan);
    if (signal !== undefined && !(signal instanceof AbortSignal)) throw new TypeError('Expected AbortSignal.');
    if (signal?.aborted) return resolve(validateOwnedResult({ status: 'FAIL', rootPid: null,
      rootExitCode: null, timedOut: false, cleanupVerified: true, error: 'execution cancelled before launch',
      stdout: '', stderr: '', cancelled: true }));
    const child = spawn(PYTHON, ['-I', '-B', path.join(ROOT, 'lib', 'owned-command.py')], {
      cwd: ROOT, windowsHide: true, stdio: ['pipe', 'pipe', 'pipe'], shell: false,
      env: { SystemRoot: 'C:\\Windows', WINDIR: 'C:\\Windows', TEMP: os.tmpdir(), TMP: os.tmpdir(),
        PATH: 'C:\\Windows\\System32;C:\\Program Files\\Git\\cmd',
        GIT_CONFIG_NOSYSTEM: '1', GIT_CONFIG_GLOBAL: 'NUL', GIT_TERMINAL_PROMPT: '0', GIT_OPTIONAL_LOCKS: '0',
        GIT_CONFIG_COUNT: '2', GIT_CONFIG_KEY_0: 'core.fsmonitor', GIT_CONFIG_VALUE_0: 'false',
        GIT_CONFIG_KEY_1: 'safe.directory', GIT_CONFIG_VALUE_1: ROOT }
    });
    let output = ''; let errors = ''; let cancelled = false;
    const abort = () => {
      cancelled = true;
      if (!child.stdin.destroyed) child.stdin.write('{"cancel":true}\n');
    };
    const detach = () => signal?.removeEventListener('abort', abort);
    child.stdout.on('data', chunk => { output += chunk; });
    child.stderr.on('data', chunk => { errors += chunk; });
    child.once('error', error => { detach(); reject(error); });
    child.stdin.on('error', () => { /* close reports bridge failure */ });
    child.once('close', code => {
      detach();
      child.stdin.destroy();
      try {
        if (code !== 0) throw new Error(`Ownership bridge exited ${code}: ${errors}`);
        const result = JSON.parse(output);
        // Cancellation wins even if it raced native completion/result delivery.
        if (cancelled) Object.assign(result, { status: 'FAIL', cancelled: true,
          error: result.error || 'execution cancelled' });
        resolve(validateOwnedResult(result));
      } catch (error) { reject(error); }
    });
    child.stdin.write(JSON.stringify(plan) + '\n');
    signal?.addEventListener('abort', abort, { once: true });
    if (signal?.aborted) abort();
  });
}
