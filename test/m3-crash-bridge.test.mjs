import test from 'node:test';
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { once } from 'node:events';
import { createInterface } from 'node:readline';
import { mkdir, readFile, writeFile, access } from 'node:fs/promises';
import { randomUUID } from 'node:crypto';
import path from 'node:path';
import { EXECUTION_ROOT as ROOT, prepareExecution, executeOwned, validateOwnedResult } from '../lib/command-execution.mjs';
import { validateProposal, commandChoices, m3CommandChoice } from '../lib/command-proposals.mjs';

const PYTHON = 'C:\\Python314\\python.exe';
const slow = { command: 'node lib/slow-command.mjs', cwd: '.' };
const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
async function artifacts(name) {
  const dir = path.join(ROOT, 'test', `app03-m3-crash-bridge-${name}-${randomUUID()}`);
  await mkdir(dir); return dir;
}
async function retain(dir, name, value) {
  await writeFile(path.join(dir, name), JSON.stringify(value, null, 2));
}

test('M3 fixed plans reject arbitrary argv/paths/shell and optional cancelled PASS', async () => {
  assert.equal(process.platform, 'win32', 'Native Windows required; no skips');
  assert.equal(m3CommandChoice.command, slow.command);
  assert.deepEqual(commandChoices.map(c => c.command), ['node --version', 'git status', 'node lib/slow-command.mjs']);
  assert.deepEqual(validateProposal(slow), slow);
  const plan = await prepareExecution(slow);
  assert.deepEqual(plan, { argv: [process.execPath, path.join(ROOT, 'lib', 'slow-command.mjs')], cwd: ROOT });
  for (const invalid of [
    { ...plan, cwd: '.' }, { ...plan, cwd: path.dirname(ROOT) },
    { ...plan, argv: [process.execPath, '--eval', 'process.exit(0)'] },
    { ...plan, argv: [process.execPath, plan.argv[1], '1'] },
    { ...plan, argv: [process.execPath, path.join(ROOT, 'test', 'slow-command.mjs')] },
    { ...plan, argv: ['D:\\node.exe', '--version'] },
    { ...plan, shell: true }, { ...plan, env: {} },
  ]) await assert.rejects(executeOwned(invalid), /Invalid fixed command plan/);
  for (const command of [slow.command + ' 1', slow.command + '; git status', 'node --eval 1'])
    await assert.rejects(prepareExecution({ command, cwd: '.' }));
  const valid = { status: 'PASS', rootPid: 1, rootExitCode: 0, cleanupVerified: true,
    timedOut: false, error: null, stdout: '', stderr: '' };
  assert.equal(validateOwnedResult(valid), valid);
  assert.throws(() => validateOwnedResult({ ...valid, cancelled: true }));
  assert.throws(() => validateOwnedResult({ ...valid, cancelled: 'true' }));
  await assert.rejects(executeOwned(plan, { signal: {} }), /AbortSignal/);
  const controller = new AbortController(); controller.abort();
  const result = await executeOwned(plan, { signal: controller.signal });
  assert.equal(result.status, 'FAIL'); assert.equal(result.cancelled, true);
  assert.equal(result.rootPid, null); assert.equal(result.cleanupVerified, true);
});

test('M3 unchanged promise caller runs installed node and full fixed ten-second command', async () => {
  const dir = await artifacts('normal'); const start = performance.now();
  const version = await executeOwned(await prepareExecution({ command: 'node --version', cwd: '.' }));
  assert.equal(version.status, 'PASS'); assert.equal(version.stdout, process.version + '\r\n');
  assert.equal(version.rootExitCode, 0); assert.equal(version.cleanupVerified, true);
  assert.equal('cancelled' in version, false);
  const slowStart = performance.now(); const result = await executeOwned(await prepareExecution(slow));
  const slowElapsedMs = performance.now() - slowStart;
  assert.equal(result.status, 'PASS', JSON.stringify(result));
  assert.equal(result.rootExitCode, 0); assert.equal(result.cleanupVerified, true);
  assert.match(result.stdout, /root completed after 10 seconds/);
  assert.match(result.stdout, /descendant completed after 10 seconds/);
  assert.ok(slowElapsedMs >= 10000 && slowElapsedMs < 16000, String(slowElapsedMs));
  await retain(dir, 'evidence.json', { version, result, slowElapsedMs, elapsedMs: performance.now() - start });
  console.log(`M3 NORMAL ${dir}: ${JSON.stringify({ version, result, slowElapsedMs })}`);
});

for (const mode of ['cancel', 'kill-caller', 'kill-bridge']) {
  test(`M3 real Node caller ${mode}: retained exact root/descendant/bridge handles prove exit`, async t => {
    const dir = await artifacts(mode); const filename = path.join(dir, 'caller-result.json');
    const start = performance.now();
    const caller = spawn(process.execPath, ['test/m3-crash-bridge-caller.mjs', mode, filename], {
      cwd: ROOT, windowsHide: true, shell: false, stdio: ['pipe', 'pipe', 'pipe']
    });
    const callerClose = once(caller, 'close');
    let output = ''; let errors = '';
    caller.stdout.on('data', c => { output += c; }); caller.stderr.on('data', c => { errors += c; });
    const observer = spawn(PYTHON, ['-B', '-m', 'test.test_owned_cancel', '--observe', String(caller.pid)], {
      cwd: ROOT, windowsHide: true, shell: false, stdio: ['pipe', 'pipe', 'pipe']
    });
    let observerErrors = ''; observer.stderr.on('data', c => { observerErrors += c; });
    const observerClose = once(observer, 'close');
    const lines = createInterface({ input: observer.stdout })[Symbol.asyncIterator]();
    t.after(async () => {
      // Fixture-only fallback; ChildProcess retains the exact launched identity.
      if (caller.exitCode === null && caller.signalCode === null) caller.kill();
      observer.stdin.end();
      await Promise.all([callerClose, observerClose]);
    });
    const readyLine = await lines.next();
    assert.equal(readyLine.done, false, observerErrors);
    const ready = JSON.parse(readyLine.value); assert.equal(ready.event, 'ready');
    assert.deepEqual(ready.identities.map(p => p.role), ['caller', 'bridge', 'root', 'descendant']);
    await retain(dir, 'live-identities.json', ready);
    await pause(250); // Let both fixed command processes publish actual output.
    if (mode === 'cancel') caller.stdin.write('cancel\n');
    observer.stdin.end(JSON.stringify({ action: mode === 'cancel' ? 'wait' : mode }) + '\n');
    const verifiedLine = await lines.next();
    assert.equal(verifiedLine.done, false, observerErrors);
    const observation = JSON.parse(verifiedLine.value);
    const [observerCode] = await observerClose; await callerClose;
    assert.equal(observerCode, 0, observerErrors);
    assert.equal(observation.cleanupVerified, true);
    assert.ok(observation.identities.every(p => p.exitSignaled));
    let result = null;
    if (mode === 'cancel') {
      result = JSON.parse(await readFile(filename, 'utf8'));
      assert.equal(result.result.status, 'FAIL'); assert.equal(result.result.cancelled, true);
      assert.equal(result.result.cleanupVerified, true); assert.equal(result.result.timedOut, false);
      assert.equal(result.result.rootPid, ready.identities.find(p => p.role === 'root').pid);
      assert.match(result.result.stdout, /M3 slow root .* started/);
      assert.match(result.result.stdout, /M3 slow descendant .* started/);
      assert.doesNotMatch(result.result.stdout, /completed/);
      assert.ok(result.elapsedMs < 5000);
    } else if (mode === 'kill-caller') {
      await assert.rejects(access(filename)); // Dead caller cannot report PASS.
    } else {
      assert.doesNotMatch(output, /"status":"PASS"/);
      assert.match(errors, /Ownership bridge exited/);
    }
    const evidence = { outcome: 'interrupted', result, observation, output, errors,
      elapsedMs: performance.now() - start, nativeResultUnavailable: mode !== 'cancel' };
    await retain(dir, 'evidence.json', evidence);
    console.log(`M3 ${mode.toUpperCase()} ${dir}: ${JSON.stringify(evidence)}`);
  });
}
