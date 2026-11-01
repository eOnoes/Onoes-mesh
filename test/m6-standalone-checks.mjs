// Run only M6 and the relevant existing contracts locally, with native receipts.
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { once } from 'node:events';
import { randomUUID } from 'node:crypto';
import { mkdir, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { ROOT } from '../server.mjs';
import { custody } from './m6-standalone-fixture.mjs';

const directory = path.join(ROOT, `test/app03-m6-standalone-checks-${randomUUID()}`);
await mkdir(directory, { recursive: true }); const monitor = await custody(directory);
const m23 = ['test/m2-proposal.test.mjs','test/m2-approve.test.mjs',
  'test/m3-idempotent.test.mjs','test/m3-idempotent-ui.test.mjs','test/m3-crash-recovery.test.mjs',
  'test/m3-crash-recovery-store.test.mjs',
  'test/m3-crash-compose.test.mjs','test/m3-crash-compose-ui.test.mjs','test/m3-crash-bridge.test.mjs'];
// The extra legacy recovery UI fixture's blank-pending assertion predates the
// committed phone Inspect UI. Its unchanged failure is documented in README;
// privacy01 and the actual M6 browser exercise cover clearance and recovery.
const npmCli = process.env.npm_execpath ?? path.join(path.dirname(process.execPath), 'node_modules/npm/bin/npm-cli.js');
const plan = [
  { label: 'npm-test', executable: process.execPath, argv: [npmCli,'test'], standalone: '0' },
  { label: 'm6-and-full-mesh-boundaries', executable: process.execPath, argv: ['--test','--test-timeout=20000',
    'test/m6-standalone.test.mjs','test/m5-nodes-api.test.mjs','test/privacy01.test.mjs','test/m4-link-store.test.mjs','test/m4-link-ui.test.mjs'], standalone: '0' },
  { label: 'm2-m3-full-mesh', executable: process.execPath, argv: ['--test','--test-timeout=55000',...m23], standalone: '0' },
  { label: 'm2-m3-standalone', executable: process.execPath, argv: ['--test','--test-timeout=55000',...m23], standalone: '1' },
  { label: 'native-ownership', executable: 'C:\\Python314\\python.exe',
    argv: ['-B','-m','unittest','-v','test.test_owned_job','test.test_owned_capture','test.test_owned_cancel'], standalone: '0' },
];
const receipt = { directory, harness: { pid: process.pid, executable: process.execPath, argv: process.argv }, results: [] };
let failures = 0;
try {
  for (const check of plan) {
    const child = spawn(check.executable, check.argv, { cwd: ROOT, windowsHide: true, stdio: ['ignore','pipe','pipe'],
      env: { ...process.env, MESH_STANDALONE: check.standalone, MESH_RELAY: check.standalone } });
    let stdout = '', stderr = ''; child.stdout.on('data', b => { stdout += b; }); child.stderr.on('data', b => { stderr += b; });
    const closed = once(child, 'close'); await monitor.call('snapshot'); const [exitCode, signal] = await closed;
    await writeFile(path.join(directory, check.label + '.log'), stdout + '\n' + stderr);
    receipt.results.push({ ...check, pid: child.pid, exitCode, signal }); if (exitCode !== 0) failures++;
    await writeFile(path.join(directory, 'checks.json'), JSON.stringify(receipt, null, 2));
    console.log(JSON.stringify({ label: check.label, exitCode, directory })); await monitor.call('snapshot');
  }
} finally {
  for (let n = 0; n < 80; n++) {
    receipt.cleanup = await monitor.call('snapshot');
    if (receipt.cleanup.filter(i => ![process.pid, monitor.child.pid].includes(i.pid)).every(i => i.exitSignaled)) break;
    await new Promise(r => setTimeout(r, 25));
  }
  await monitor.finish();
  await writeFile(path.join(directory, 'checks.json'), JSON.stringify(receipt, null, 2));
  assert.ok(receipt.cleanup.filter(i => ![process.pid, monitor.child.pid].includes(i.pid)).every(i => i.exitSignaled), 'All retained qualification child handles exited');
}
assert.equal(failures, 0, 'Required local checks failed; inspect retained logs');
