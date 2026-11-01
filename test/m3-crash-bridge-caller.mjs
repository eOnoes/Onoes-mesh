// Disposable real caller used by the exact-handle observer; no server/UI edits.
import { writeFile } from 'node:fs/promises';
import { prepareExecution, executeOwned } from '../lib/command-execution.mjs';

// Harmless when included in a node --test test/m3-crash-bridge*.mjs glob.
if (['cancel', 'kill-caller', 'kill-bridge'].includes(process.argv[2]) && process.argv[3]) {
  const controller = new AbortController();
  if (process.argv[2] === 'cancel') process.stdin.once('data', () => controller.abort());
  const start = performance.now();
  const result = await executeOwned(await prepareExecution({ command: 'node lib/slow-command.mjs', cwd: '.' }),
    { signal: controller.signal });
  const evidence = { result, elapsedMs: performance.now() - start, callerPid: process.pid };
  await writeFile(process.argv[3], JSON.stringify(evidence, null, 2));
  console.log(JSON.stringify(evidence));
  process.stdin.destroy();
}
