import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
import { readMaintenanceRecovery } from '../lib/workroom-legacy-recovery.mjs';

export { readMaintenanceRecovery };
if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  try {
    const [scopePath, planPath, ...extra] = process.argv.slice(2);
    if (!scopePath || !planPath || extra.length) throw Error('Use <scope.json> <plan.json> for read-only recovery readback.');
    const result = readMaintenanceRecovery(JSON.parse(readFileSync(scopePath, 'utf8')), JSON.parse(readFileSync(planPath, 'utf8')));
    process.stdout.write(JSON.stringify(result) + '\n');
  } catch (error) { process.stderr.write(error.message + '\n'); process.exitCode = 1; }
}
