import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
import { DatabaseSync } from 'node:sqlite';
import { databaseFileIdentity } from '../lib/database-identity.mjs';
import { createLegacyRecoveryStore } from '../lib/workroom-legacy-recovery.mjs';
import { createDispatchBarrier } from '../lib/workroom-dispatch-barrier.mjs';

// Readback never opens a writable connection, initializes tables or releases a hold.
export function readMaintenanceRecovery(scope, plan) {
  if (scope?.schema !== 'mesh/legacy-operator-scope/v3' ||
      scope.databasePath !== plan?.databasePath || scope.databaseIdentity !== plan.databaseIdentity ||
      databaseFileIdentity(scope.databasePath) !== plan.databaseIdentity ||
      !/^[a-f0-9]{64}$/.test(plan.planHash ?? '') || plan.disposition !== 'historical_outcome_unknown' ||
      plan.targets?.length !== 8 || new Set(plan.targets.map(t => t.sendId)).size !== 8) {
    throw Error('Exact scope, database identity and eight-send plan are required for readback.');
  }
  const db = new DatabaseSync(scope.databasePath, { readOnly: true });
  try {
    db.exec('PRAGMA query_only=ON; BEGIN;');
    const recovery = createLegacyRecoveryStore(db);
    for (const target of plan.targets) {
      const row = recovery.read(target.taskId, target.sendId);
      if (row?.planHash !== plan.planHash || row.recoveryId !== plan.recoveryId ||
          row.state !== 'owner_recovered_unknown' || row.workerRetirementEstablished !== false ||
          !db.prepare('SELECT id FROM tasks WHERE id=?').get(target.taskId)) {
        throw Error('Recovery evidence or original board task did not read back for all eight sends.');
      }
    }
    const gate = createDispatchBarrier(db).status();
    if (gate.state !== 'paused' || gate.held || gate.activeAdmissions !== 0) {
      throw Error('Dispatch is not paused, unheld and drained after recovery.');
    }
    if (databaseFileIdentity(scope.databasePath) !== plan.databaseIdentity) throw Error('Database identity changed during readback.');
    return { status: 'eight_recoveries_read_back', planHash: plan.planHash, targetCount: 8,
      disposition: 'historical_outcome_unknown', originalTasksPresent: true,
      dispatchRemainsPaused: true, workerRetirementEstablished: false, readOnly: true };
  } finally { db.close(); }
}
if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  try {
    const [scopePath, planPath, ...extra] = process.argv.slice(2);
    if (!scopePath || !planPath || extra.length) throw Error('Use <scope.json> <plan.json> for read-only recovery readback.');
    const result = readMaintenanceRecovery(JSON.parse(readFileSync(scopePath, 'utf8')), JSON.parse(readFileSync(planPath, 'utf8')));
    process.stdout.write(JSON.stringify(result) + '\n');
  } catch (error) { process.stderr.write(error.message + '\n'); process.exitCode = 1; }
}
