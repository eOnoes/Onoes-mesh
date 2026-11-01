// Fixed harmless M3 fixture. No caller-supplied duration, path, cwd or argv.
import { spawn } from 'node:child_process';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const script = fileURLToPath(import.meta.url);
const cwd = path.dirname(path.dirname(script));
if (process.argv.length === 2) {
  const child = spawn(process.execPath, [script, '--owned-child'], {
    cwd, shell: false, windowsHide: true, stdio: ['ignore', 'inherit', 'inherit']
  });
  child.once('error', error => { console.error(error.message); process.exitCode = 1; });
  child.once('exit', code => { if (code !== 0) process.exitCode = 1; });
  console.log(`M3 slow root ${process.pid}; descendant ${child.pid}; started`);
  setTimeout(() => console.log('M3 slow root completed after 10 seconds'), 10000);
} else if (process.argv.length === 3 && process.argv[2] === '--owned-child') {
  console.log(`M3 slow descendant ${process.pid}; started`);
  setTimeout(() => console.log('M3 slow descendant completed after 10 seconds'), 10000);
} else {
  throw new Error('Invalid fixed slow command arguments.');
}
