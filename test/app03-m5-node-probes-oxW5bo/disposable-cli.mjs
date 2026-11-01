import { readFileSync } from 'node:fs';
const input = JSON.parse(readFileSync(process.argv[2], 'utf8'));
if (input.mode === 'timeout') { setInterval(() => {}, 1000); }
else if (input.mode === 'oversized') { process.stdout.write('x'.repeat(1048577)); setInterval(() => {}, 1000); }
else if (input.mode === 'invalid_utf8') { process.stdout.write(Buffer.from([0xff])); }
else { process.stdout.write(input.stdout ?? ''); process.stderr.write(input.stderr ?? ''); process.exitCode = input.exitCode ?? 0; }
