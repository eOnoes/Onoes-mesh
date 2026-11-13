import { createHash } from 'node:crypto';
import { readFile, realpath, writeFile } from 'node:fs/promises';
import { databaseFileIdentity } from '../lib/database-identity.mjs';
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import { DatabaseSync } from 'node:sqlite';
import { resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
import { homedir } from 'node:os';
import {makeLegacyRecoveryPlan,assessLegacyRecovery,captureLegacyRecoveryRows,validateLegacyRecoverySnapshot,legacyMachineIdentity} from '../lib/workroom-legacy-evidence.mjs';

const run = promisify(execFile);
const sha = value => createHash('sha256').update(value).digest('hex');
export function readLegacyRows(databasePath, sendIds) {
  const db = new DatabaseSync(databasePath, { readOnly: true });
  try {
    db.exec('PRAGMA query_only=ON; BEGIN;');
    const result = captureLegacyRecoveryRows(db, sendIds);
    db.exec('COMMIT;');
    return result;
  } finally { db.close(); }
}

export async function observeLegacyRecovery({ workspace, databasePath, sendIds, sourceFiles }) {
  if (process.platform !== 'win32') throw Error('The live collector requires this Windows PC.');
  const { stdout } = await run('powershell.exe', ['-NoProfile', '-NonInteractive', '-Command',
    String.raw`$ErrorActionPreference='Stop'; $o=Get-CimInstance Win32_OperatingSystem; $p=Get-CimInstance Win32_ComputerSystemProduct; $g=(Get-ItemProperty -LiteralPath 'HKLM:\SOFTWARE\Microsoft\Cryptography' -Name MachineGuid).MachineGuid; @{host=$o.CSName;bootedAt=$o.LastBootUpTime.ToUniversalTime().ToString("o");windowsMachineGuid=$g;hardwareUuid=$p.UUID} | ConvertTo-Json -Compress`],
  { windowsHide: true, timeout: 15000, maxBuffer: 8192 });
  const machine = JSON.parse(stdout.trim());
  const databaseIdentity = databaseFileIdentity(databasePath);
  const snapshot = { workspace: await realpath(workspace), databasePath: await realpath(databasePath), databaseIdentity,
    host: machine.host, machineIdentity: legacyMachineIdentity(machine), bootedAt: machine.bootedAt, observedAt: new Date().toISOString(), sources: {},
    ...readLegacyRows(databasePath, sendIds) };
  for (const [name, file] of Object.entries(sourceFiles)) snapshot.sources[name] = sha(await readFile(file));
  validateLegacyRecoverySnapshot(snapshot);
  return snapshot;
}

export function legacyRecoverySources(workspace) {
  return {
    meshClaimPolicy: resolve(workspace, 'lib/workroom-claim-policy.mjs'),
    meshWorkroom: resolve(workspace, 'lib/workroom.mjs'),
    legacyRecoveryStore: resolve(workspace, 'lib/workroom-legacy-recovery.mjs'),
    recoveryPlanner: resolve(workspace, 'integrations/legacy-recovery-plan.mjs'),
    pcCustodyVerifier: resolve(workspace, 'lib/pc-recovery-evidence.mjs'),
    legacyEvidence: resolve(workspace, 'lib/workroom-legacy-evidence.mjs'),
    legacyAuthorization: resolve(workspace, 'lib/workroom-legacy-authorization.mjs'),
    writerStates: resolve(workspace, 'lib/workroom-writer-states.mjs'),
    meshDispatchBarrier: resolve(workspace, 'lib/workroom-dispatch-barrier.mjs'),
    databaseIdentity: resolve(workspace, 'lib/database-identity.mjs'),
    meshServer: resolve(workspace, 'server.mjs'),
    meshServingProxy: resolve(workspace, 'serve.mjs'),
    meshFlow: resolve(workspace, 'lib/workroom-flow.mjs'),
    meshAutomation: resolve(workspace, 'lib/workroom-automation-store.mjs'),
    meshAutomationRunner: resolve(workspace, 'lib/workroom-automation.mjs'),
    meshNativeSessions: resolve(workspace, 'lib/workroom-local-sessions.mjs'),
    relayStore: 'D:/Dev/Onoes-Relay/relay_sessions.py', relayServer: 'D:/Dev/Onoes-Relay/relay_server.py',
    relayNativeReceipts: 'D:/Dev/Onoes-Relay/relay_native_receipts.py',
    hermesRuns: resolve(homedir(), 'AppData/Local/hermes/hermes-agent/gateway/platforms/api_server_runs.py'),
    dshBridge: resolve(homedir(), '.dsh/profiles/a2a/node_modules/dsh-a2a-server/lib/index.js'),
  };
}

async function main() {
  const [action, input, output] = process.argv.slice(2);
  if (!['prepare', 'inspect'].includes(action) || !input || !output) throw Error('Use prepare <exact-scope.json> <new-plan.json> or inspect <plan.json> <new-assessment.json>. No apply action exists.');
  const value = JSON.parse(await readFile(resolve(input), 'utf8'));
  const workspace = action === 'prepare' ? process.cwd() : value.workspace;
  if (await realpath(workspace) !== await realpath(process.cwd())) throw Error('Run from the reviewed Mesh workspace.');
  const snapshot = await observeLegacyRecovery({ workspace, databasePath: action === 'prepare'
    ? resolve('data/workroom-preview/tasks.sqlite') : value.databasePath,
  sendIds: value.targets.map(t => t.sendId), sourceFiles: legacyRecoverySources(workspace) });
  const result = action === 'prepare' ? makeLegacyRecoveryPlan(snapshot) : assessLegacyRecovery(value, snapshot);
  await writeFile(resolve(output), JSON.stringify(result, null, 2) + '\n', { flag: 'wx' });
  process.stdout.write(JSON.stringify({ action, output: resolve(output), targetCount: result.targets?.length || result.targetCount,
    planHash: result.planHash, status: result.status || 'prepared_only', reasons: result.reasons || [], canRelease: false }) + '\n');
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  main().catch(error => { process.stderr.write(error.message + '\n'); process.exitCode = 1; });
}
