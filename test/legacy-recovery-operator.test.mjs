import nodeTest from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, realpathSync, writeFileSync, readFileSync, mkdirSync, existsSync, openSync, closeSync, copyFileSync } from 'node:fs';
import { tmpdir, homedir } from 'node:os';
import { join, resolve, relative } from 'node:path';
import { createHash } from 'node:crypto';
import { execFileSync, spawnSync, spawn } from 'node:child_process';
import { DatabaseSync } from 'node:sqlite';
import { createServer } from 'node:net';
import { once } from 'node:events';
import { createLegacyRecoveryStore } from '../lib/workroom-legacy-recovery.mjs';
import { openTaskStore } from '../lib/task-store.mjs';
import { databaseFileIdentity } from '../lib/database-identity.mjs';
import { createDispatchBarrier } from '../lib/workroom-dispatch-barrier.mjs';
import { nativeResourceFingerprint, productionWorkerRuntimeNames } from '../lib/windows-native-maintenance.mjs';
import { legacyRecoveryFingerprint as hash } from '../lib/workroom-legacy-evidence.mjs';
import { readLegacyRows, legacyRecoverySources } from '../integrations/legacy-recovery-plan.mjs';
import { normalizeRelayDelivery, verifyDshOrigins, inspectReplayQueues, inspectRetainedRecords, verifyRetainedReview, verifyReplayRecords, verifyStartupControls, verifyDeploymentScope, loadOperatorScope, runLegacyOperator } from '../integrations/legacy-recovery-operator.mjs';
import { readMaintenanceRecovery } from '../integrations/read-maintenance-recovery.mjs';
import { prepareFrozenLegacyController } from '../lib/legacy-controller-bundle.mjs';
import { pathToFileURL } from 'node:url';

const test = process.platform === 'win32' && process.arch === 'x64' ? nodeTest : nodeTest.skip;
const sha = bytes => createHash('sha256').update(bytes).digest('hex');

test('qualification reruns reject outside or occupied output folders without replacing old evidence',()=>{
 const originals=['data/relay-retained-startup-qualification.json','data/relay-retained-startup-child.log','data/native-retained-startup-qualification.json'];
 const before=new Map(originals.filter(existsSync).map(p=>[p,sha(readFileSync(p))]));
 for(const script of ['qualify-relay-retained-startup.py','qualify-native-retained-startup.py']){
  const outside=realpathSync.native(mkdtempSync(join(tmpdir(),'mesh-qualification-outside-')));
  const occupied=realpathSync.native(mkdtempSync(join(resolve('data'),'mesh-qualification-occupied-')));
  writeFileSync(join(occupied,'preserve.txt'),'preserve existing evidence');
  for(const output of [outside,occupied]){
   const result=spawnSync('python',['-B',join('integrations',script),'--output-dir',output],{encoding:'utf8',windowsHide:true,timeout:10000});
   assert.equal(result.error,undefined);assert.notEqual(result.status,0);assert.match(result.stderr,/fresh, empty directory inside workspace data/);
  }
  assert.equal(readFileSync(join(occupied,'preserve.txt'),'utf8'),'preserve existing evidence');
 }
 for(const [p,digest] of before)assert.equal(sha(readFileSync(p)),digest);
});

async function fixture() {
  const dir = realpathSync.native(mkdtempSync(join(tmpdir(), 'mesh-operator-')));
  const databasePath = join(dir, 'tasks.sqlite'), store = openTaskStore(databasePath), db = new DatabaseSync(databasePath);
  const task = store.create({ title: 'Synthetic old requests', description: 'Disposable operator qualification only.' });
  const bindings = [];
  const relayPath = join(dir, 'relay.sqlite'), relay = new DatabaseSync(relayPath);
  relay.exec('CREATE TABLE outbox(idem_key TEXT,agent_id TEXT,session_id TEXT,state TEXT,transport_ref TEXT,content TEXT);');
  const hermesPath = join(dir, 'hermes.sqlite'), hermes = new DatabaseSync(hermesPath);
  hermes.exec('CREATE TABLE session_admissions(admission_id TEXT,request_id TEXT,target_session_id TEXT,payload_digest TEXT,status TEXT,outcome TEXT,owner_epoch INTEGER,generation INTEGER,payload_json TEXT);');
  const tasks = [];
  for (let n = 0; n < 8; n++) {
    const sendId = 'send-' + n, agentId = n < 6 ? 'echo' : 'dsh', conversationId = 'fixture-session', delivery = 'Synthetic delivery ' + n;
    db.prepare(`INSERT INTO workroom_sends(id,taskId,agentId,conversationId,text,fingerprint,state,at,payload,basis,phase)
      VALUES(?,?,?,?,?,?,'accepted',?,?,?,'work')`).run(sendId, task.id, agentId, conversationId, 'Synthetic request', 'a'.repeat(64), '2020-01-01T00:00:00Z', delivery, '{}');
    relay.prepare('INSERT INTO outbox VALUES(?,?,?,?,NULL,?)').run(sendId, agentId, conversationId, 'accepted', delivery);
    const binding = { sendId, agentId, conversationId };
    if (n < 6) {
      const record = { admission_id: 'admission-' + n, request_id: 'request-' + n, target_session_id: conversationId,
        payload_digest: sha(delivery), status: 'terminal', outcome: 'completed', owner_epoch: 1, generation: n + 1 };
      hermes.prepare('INSERT INTO session_admissions VALUES(?,?,?,?,?,?,?,?,?)').run(...Object.values(record), JSON.stringify({ text: delivery }));
      Object.assign(binding, { admissionId: record.admission_id, nativeFingerprint: hash(record) });
    } else {
      const record = { id: 'native-' + n, contextId: conversationId, status: { state: 3, timestamp: '2020-01-01T00:00:00Z' } };
      const origin = { role: 1, messageId: 'origin-' + n, taskId: '', contextId: 'original-client-context',
        parts: [{ content: { $case: 'text', value: delivery } }] };
      const history = [origin];
      if (n === 7) history.push({ role: 2, messageId: 'response-7', parts: [] },
        { role: 1, messageId: 'followup-7', taskId: record.id, contextId: origin.contextId,
          parts: [{ content: { $case: 'text', value: 'A different later request' } }] });
      tasks.push({ ...record, history });
      Object.assign(binding, { nativeTaskId: record.id, nativeFingerprint: hash(record),
        originMessageId: origin.messageId, originFingerprint: hash(origin) });
      relay.prepare('UPDATE outbox SET transport_ref=? WHERE idem_key=?').run('a2a:'+record.id,sendId);
    }
    binding.relayReceiptFingerprint=hash(relay.prepare('SELECT idem_key,agent_id,session_id,state,transport_ref,content FROM outbox WHERE idem_key=?').get(sendId));
    bindings.push(binding);
  }
  const dshPath = join(dir, 'dsh.json'); writeFileSync(dshPath, JSON.stringify(tasks));
  const originalDir = join(dir, 'Start Menu', 'Programs', 'Startup'); mkdirSync(originalDir, { recursive: true });
  const taskObservations = ['Hermes_Gateway', 'Onoes Deep Watchdog', 'ONOes Mesh Workroom Recovery', 'DSH Local Model Supervisor', 'Hermes_Gateway_Guardian'].map(name => ({ name, path: '\\', enabled: false, state: 'Disabled',
    actions: [{ Execute: 'synthetic.exe', Arguments: '', WorkingDirectory: '' }], principal: { UserId: 'SYNTHETIC', LogonType: 'Interactive', RunLevel: 'Limited' } }));
  const shortcuts = ['Onoes Deep (DSH A2A).lnk', 'Onoes DeepSeek Harness Web.lnk', 'Onoes Relay.lnk'].map((name, i) => {
    const parked = join(dir, 'parked-' + i + '.lnk'); writeFileSync(parked, 'Synthetic shortcut ' + i);
    return { original: join(originalDir, name), parked, sha256: sha(readFileSync(parked)) };
  });
  const ports = [];
  while (ports.length < 4) {
    const seed = createServer(); await new Promise(resolve => seed.listen(0, '127.0.0.1', resolve));
    const port = seed.address().port; await new Promise(resolve => seed.close(resolve));
    assert.ok(![3081, 4123, 4320, 8452, 8453, 8642, 8787].includes(port));
    if (!ports.includes(port)) ports.push(port);
  }
  const lock = join(dir, 'gateway.lock'); writeFileSync(lock, 'Synthetic lock');
  const scope = { schema: 'mesh/legacy-operator-scope/v3', containment: 'worker_services_offline', owner: 'Eddie', locality: 'desktop_echo_dsh_only',
    workspace: realpathSync.native(process.cwd()), databasePath, databaseIdentity: databaseFileIdentity(databasePath),
    relay: { path: relayPath, identity: databaseFileIdentity(relayPath) }, hermes: { path: hermesPath, identity: databaseFileIdentity(hermesPath) },
    dsh: { path: dshPath, sha256: sha(readFileSync(dshPath)) }, bindings, nativeResources: { profileLocks: [lock], endpoints: ports.flatMap(port => [['127.0.0.1', port], ['::1', port]]),workerRuntimeNames:['mesh-operator-'+dir.split(/[\\/]/).at(-1)+'.exe'] },
    startup: { tasks: taskObservations.map(({ name, path, actions, principal }) => ({ name, path, definitionFingerprint: hash({ actions, principal }) })), shortcuts } };
  const scopePath = join(dir, 'scope.json'); writeFileSync(scopePath, JSON.stringify(scope));
  const options = { scopePath, scopeSha256: sha(readFileSync(scopePath)), planPath: join(dir, 'plan.json') };
  const barrier = createDispatchBarrier(db); barrier.pause();
  const preparedAt = new Date(Date.now() - 120000).toISOString(), laterBoot = new Date(Date.now() - 60000).toISOString();
  let afterBoot = false;
  const runtime = { validateDeployment: candidate => assert.equal(candidate.databasePath, databasePath),
    startupReader: () => structuredClone(taskObservations), collect: async ({ sourceFiles }) => ({
    workspace: scope.workspace, databasePath, databaseIdentity: databaseFileIdentity(databasePath), host: 'SYNTHETIC', machineIdentity: '1'.repeat(64),
    bootedAt: afterBoot ? laterBoot : '2020-01-01T00:00:00Z', observedAt: afterBoot ? new Date().toISOString() : preparedAt,
    sources: { ...Object.fromEntries(Object.entries(sourceFiles).map(([name, path]) => [name, sha(readFileSync(path))])),
      nativeResourceScope: nativeResourceFingerprint(scope.nativeResources) }, ...readLegacyRows(databasePath, bindings.map(b => b.sendId)),
  }) };
  // An offline fixture must not keep external writable SQLite handles open.
  // Every inspection opens read-only; deliberate mutations open/close explicitly.
  relay.close();hermes.close();
  const external=path=>({
    prepare(sql){return Object.fromEntries(['run','get','all'].map(method=>[method,(...args)=>{
      const handle=new DatabaseSync(path,{readOnly:method!=='run'});
      try{return handle.prepare(sql)[method](...args);}finally{handle.close();}
    }]));},
    exec(sql){const handle=new DatabaseSync(path);try{return handle.exec(sql);}finally{handle.close();}},
  });
  return { dir, scope, options, db, relay:external(relayPath), hermes:external(hermesPath), barrier, runtime, taskObservations, tasks,
    targets: () => readLegacyRows(databasePath, bindings.map(b => b.sendId)).targets,
    boot() { afterBoot = true; },
    authorize() {
      const plan = JSON.parse(readFileSync(options.planPath, 'utf8')), path = join(dir, 'approval.json');
      writeFileSync(path, JSON.stringify({ schema: 'mesh/legacy-recovery-authorization/v1', owner: 'Eddie', decision: 'apply_exact_eight',
        maintenanceMode:'worker_services_offline',quietWorkspaceConfirmed:true,planHash: plan.planHash, host: 'SYNTHETIC', bootedAt: laterBoot, authorizedAt: new Date(Date.now() - 1000).toISOString(), expiresAt: new Date(Date.now() + 60000).toISOString() }));
      return { authorizationPath: path, authorizationSha256: sha(readFileSync(path)) };
    },
    close() { db.close(); store.close(); } };
}

test('current-boot operator pins the old witness and needs new authority plus unchanged offline fences',async()=>{
  const f=await fixture();
  try{
    await runLegacyOperator({...f.options,action:'prepare'},f.runtime);
    const historicalWitnessPath=f.options.planPath,historicalWitnessSha256=sha(readFileSync(historicalWitnessPath));
    f.boot();const oldAuthority=f.authorize();
    f.db.prepare('UPDATE tasks SET title=?').run('Legitimate postboot board edit');
    const original=f.db.prepare('SELECT * FROM workroom_sends ORDER BY id').all();
    f.options.planPath=join(f.dir,'current-boot-plan.json');
    await assert.rejects(runLegacyOperator({...f.options,action:'prepare-current-boot',historicalWitnessPath,historicalWitnessSha256},f.runtime),/already be pinned/);
    assert.equal(existsSync(f.options.planPath),false);
    f.scope.additionalSources={legacyRetirementWitness:historicalWitnessPath};
    writeFileSync(f.options.scopePath,JSON.stringify(f.scope));f.options.scopeSha256=sha(readFileSync(f.options.scopePath));
    const prepared=await runLegacyOperator({...f.options,action:'prepare-current-boot',historicalWitnessPath,historicalWitnessSha256},f.runtime);
    assert.equal(prepared.canRelease,false);
    const plan=JSON.parse(readFileSync(f.options.planPath,'utf8'));
    assert.equal(plan.schema,'mesh/legacy-recovery-plan/v3');
    assert.equal(plan.retirementWitness.sha256,historicalWitnessSha256);
    assert.equal((await runLegacyOperator({...f.options,action:'inspect'},f.runtime)).status,'ready_for_operator_review');
    await assert.rejects(runLegacyOperator({...f.options,action:'apply',...oldAuthority},f.runtime),/authorization|owner|plan/i);
    const receipt=await runLegacyOperator({...f.options,action:'apply',...f.authorize()},f.runtime);
    assert.equal(receipt.disposition,'historical_outcome_unknown');assert.equal(receipt.dispatchRemainsPaused,true);
    assert.deepEqual(f.db.prepare('SELECT * FROM workroom_sends ORDER BY id').all(),original);
    assert.equal(f.db.prepare('SELECT title FROM tasks').get().title,'Legitimate postboot board edit');
    assert.equal(f.db.prepare('SELECT COUNT(*) AS n FROM workroom_legacy_recovery_sends').get().n,8);
  }finally{f.close();}
});

test('the frozen console drives the complete current-boot recovery in disposable stores',async()=>{
 const f=await fixture();
 try{
  retainedFixture(f);
  const root=join(resolve('data'),'mesh-legacy-controller-operator-'+f.dir.split(/[\\/]/).at(-1));
  const bundle=prepareFrozenLegacyController({sourceRoot:realpathSync.native(process.cwd()),destinationRoot:root});
  const frozen=await import(pathToFileURL(bundle.entry));
  const {runLegacyRecoveryConsole}=await import(pathToFileURL(join(root,'lib','workroom-legacy-console.mjs')));
  await assert.rejects(frozen.runLegacyOperator({...f.options,action:'prepare'},f.runtime),/external controller/);
  f.scope.controllerBundle=bundle.descriptor;
  writeFileSync(f.options.scopePath,JSON.stringify(f.scope));f.options.scopeSha256=sha(readFileSync(f.options.scopePath));
  await frozen.runLegacyOperator({...f.options,action:'prepare'},f.runtime);
  const historicalWitnessPath=f.options.planPath,historicalWitnessSha256=sha(readFileSync(historicalWitnessPath));f.boot();
  f.scope.additionalSources={legacyRetirementWitness:historicalWitnessPath};
  writeFileSync(f.options.scopePath,JSON.stringify(f.scope));f.options.scopeSha256=sha(readFileSync(f.options.scopePath));
  f.options.planPath=join(f.dir,'frozen-current-boot-plan.json');
  await frozen.runLegacyOperator({...f.options,action:'prepare-current-boot',historicalWitnessPath,historicalWitnessSha256},f.runtime);
  const plan=JSON.parse(readFileSync(f.options.planPath,'utf8'));
  assert.ok(Object.keys(plan.sources).some(k=>k.startsWith('frozenControllerFile')));
  const original=f.db.prepare('SELECT * FROM workroom_sends ORDER BY id').all();
  const receiptWorkspace=join(f.dir,'console');
  mkdirSync(join(receiptWorkspace,'data'),{recursive:true});
  const result=await runLegacyRecoveryConsole({
    scope:{...f.scope,workspace:receiptWorkspace},plan,
    inspect:()=>frozen.runLegacyOperator({...f.options,action:'inspect'},f.runtime),
    observe:()=>f.runtime.collect(frozen.loadOperatorScope(f.options.scopePath,f.options.scopeSha256)),
    confirm:async({phrase})=>phrase,
    apply:authority=>frozen.runLegacyOperator({...f.options,action:'apply',...authority},f.runtime),
  });
  assert.equal(result.status,'operator_returned');
  const receipt=result.result;
  assert.equal(receipt.disposition,'historical_outcome_unknown');assert.equal(receipt.dispatchRemainsPaused,true);
  assert.deepEqual(f.db.prepare('SELECT * FROM workroom_sends ORDER BY id').all(),original);
  assert.equal(f.db.prepare('SELECT COUNT(*) AS n FROM workroom_legacy_recovery_sends').get().n,8);
 }finally{f.close();}
});

test('the assembled operator prepares, denies same-boot apply, commits only after the fixture boot and exact approval, and stays paused', async () => {
  const f = await fixture();
  try {
    const originals = f.db.prepare('SELECT * FROM workroom_sends ORDER BY id').all();
    const prepared = await runLegacyOperator({ ...f.options, action: 'prepare' }, f.runtime);
    assert.equal(prepared.canRelease, false);
    assert.equal((await runLegacyOperator({ ...f.options, action: 'inspect' }, f.runtime)).status, 'blocked');
    await assert.rejects(runLegacyOperator({ ...f.options, action: 'apply', ...f.authorize() }, f.runtime), /later_pc_boot/);
    f.boot();
    const receipt = await runLegacyOperator({ ...f.options, action: 'apply', ...f.authorize() }, f.runtime);
    assert.equal(receipt.disposition, 'historical_outcome_unknown'); assert.equal(receipt.dispatchRemainsPaused, true);
    assert.equal(f.barrier.status().state, 'paused'); assert.equal(f.barrier.status().held, false);
    assert.deepEqual(f.db.prepare('SELECT * FROM workroom_sends ORDER BY id').all(), originals);
    assert.equal(f.db.prepare('SELECT COUNT(*) AS n FROM workroom_legacy_recovery_sends').get().n, 8);
    const target=f.targets()[0],record=createLegacyRecoveryStore(f.db).read(target.taskId,target.sendId);assert.equal(record.workerRetirementEstablished,false);
    const saved=JSON.parse(f.db.prepare('SELECT evidence FROM workroom_legacy_recoveries').get().evidence);
    assert.equal(saved.boundary.schema,'mesh/legacy-local-fence/v2');assert.equal(saved.boundary.coverageScope,'reviewed_runtime_entrypoints_only');
    assert.equal(saved.nativeHold.workerRuntimeObservation.outsideRuntimeCount,0);assert.equal(saved.nativeHold.workerRuntimeObservation.continuousExecutionExcluded,false);
    const plan=JSON.parse(readFileSync(f.options.planPath,'utf8'));
    const ledgerBefore=hash(f.db.prepare('SELECT * FROM workroom_legacy_recovery_sends ORDER BY sendId').all());
    const readback=readMaintenanceRecovery(f.scope,plan);
    assert.equal(readback.status,'eight_recoveries_read_back');assert.equal(readback.readOnly,true);
    assert.equal(readback.workerRetirementEstablished,false);assert.equal(readback.dispatchRemainsPaused,true);
    assert.equal(hash(f.db.prepare('SELECT * FROM workroom_legacy_recovery_sends ORDER BY sendId').all()),ledgerBefore);
    assert.deepEqual(f.db.prepare('SELECT * FROM workroom_sends ORDER BY id').all(),originals);
    f.db.prepare('UPDATE workroom_legacy_recovery_sends SET fingerprint=? WHERE sendId=?').run('0'.repeat(64),plan.targets[0].sendId);
    assert.throws(()=>readMaintenanceRecovery(f.scope,plan),/did not read back/);
    assert.equal(f.db.prepare('SELECT fingerprint FROM workroom_legacy_recovery_sends WHERE sendId=?').get(plan.targets[0].sendId).fingerprint,'0'.repeat(64));
  } finally { f.close(); }
});

test('standalone readback refuses an unrecorded ledger and changed database identity without creating recovery tables',async()=>{
  const f=await fixture();
  try{
    await runLegacyOperator({...f.options,action:'prepare'},f.runtime);
    const plan=JSON.parse(readFileSync(f.options.planPath,'utf8'));
    assert.throws(()=>readMaintenanceRecovery(f.scope,plan),/did not read back/);
    assert.equal(f.db.prepare("SELECT count(*) n FROM sqlite_master WHERE name LIKE 'workroom_legacy_recover%'").get().n,0);
    assert.throws(()=>readMaintenanceRecovery({...f.scope,databaseIdentity:'0'.repeat(64)},plan),/database identity/);
  }finally{f.close();}
});

test('deployed-shaped accepted receipts preserve six null Echo refs and two exact DSH task refs',async()=>{
  const f=await fixture();
  try {
    const before=hash(f.relay.prepare('SELECT * FROM outbox ORDER BY idem_key').all());
    assert.equal(f.relay.prepare('SELECT COUNT(*) AS n FROM outbox WHERE agent_id=\'echo\' AND transport_ref IS NULL').get().n,6);
    assert.equal(f.relay.prepare('SELECT COUNT(*) AS n FROM outbox WHERE agent_id=\'dsh\' AND transport_ref IS NOT NULL').get().n,2);
    assert.equal(verifyReplayRecords(f.scope,f.targets()).exactAcceptedSends,8);
    assert.equal(hash(f.relay.prepare('SELECT * FROM outbox ORDER BY idem_key').all()),before);
  } finally {f.close();}
});

test('missing receipt pins and substituted references refuse even when a changed receipt is repinned',async()=>{
  const f=await fixture();
  try {
    const missing=structuredClone(f.scope);delete missing.bindings[0].relayReceiptFingerprint;
    assert.throws(()=>verifyReplayRecords(missing,f.targets()),/pinned Relay receipt/);
    const dsh=f.scope.bindings.find(b=>b.agentId==='dsh');
    f.relay.prepare('UPDATE outbox SET transport_ref=? WHERE idem_key=?').run('a2a:other-task',dsh.sendId);
    const changed=structuredClone(f.scope);
    changed.bindings.find(b=>b.sendId===dsh.sendId).relayReceiptFingerprint=hash(f.relay.prepare('SELECT idem_key,agent_id,session_id,state,transport_ref,content FROM outbox WHERE idem_key=?').get(dsh.sendId));
    assert.throws(()=>verifyReplayRecords(changed,f.targets()),/Relay receipt changed/);
    f.relay.prepare('UPDATE outbox SET transport_ref=? WHERE idem_key=?').run('a2a:'+dsh.nativeTaskId,dsh.sendId);
    const echo=changed.bindings.find(b=>b.agentId==='echo');
    f.relay.prepare('UPDATE outbox SET transport_ref=? WHERE idem_key=?').run('a2a:'+dsh.nativeTaskId,echo.sendId);
    echo.relayReceiptFingerprint=hash(f.relay.prepare('SELECT idem_key,agent_id,session_id,state,transport_ref,content FROM outbox WHERE idem_key=?').get(echo.sendId));
    assert.throws(()=>verifyReplayRecords(changed,f.targets()),/Relay receipt changed/);
    f.relay.prepare('UPDATE outbox SET transport_ref=NULL WHERE idem_key=?').run(echo.sendId);
    const badPin=structuredClone(f.scope);badPin.bindings[0].relayReceiptFingerprint='0'.repeat(64);
    assert.throws(()=>verifyReplayRecords(badPin,f.targets()),/receipt fingerprint changed/);
  } finally {f.close();}
});

test('the production entry refuses disposable or narrowed service coverage even with a pinned scope', async () => {
  const f = await fixture();
  try {
    const { validateDeployment, ...runtime } = f.runtime;
    await assert.rejects(runLegacyOperator({ ...f.options, action: 'prepare' }, runtime), /deployed service\/database layout/);
    assert.equal(existsSync(f.options.planPath), false);
  } finally { f.close(); }
});

test('replay checks reject queued Relay deliveries, unknown native admissions, changed exact receipts and incomplete native coverage', async () => {
  const f = await fixture();
  try {
    assert.equal(verifyReplayRecords(f.scope, f.targets()).exactAcceptedSends, 8);
    f.relay.prepare("INSERT INTO outbox VALUES('other','echo','other','retrying',NULL,'Other')").run();
    assert.equal(inspectReplayQueues(f.scope).relay.find(r => r.state === 'retrying').count, 1);
    assert.throws(() => verifyReplayRecords(f.scope, f.targets()), /unresolved queued/);
    f.relay.prepare("DELETE FROM outbox WHERE idem_key='other'").run();
    f.hermes.prepare("UPDATE session_admissions SET status='unknown' WHERE admission_id='admission-0'").run();
    assert.throws(() => verifyReplayRecords(f.scope, f.targets()), /unresolved native/);
    f.hermes.prepare("UPDATE session_admissions SET status='terminal',generation=99 WHERE admission_id='admission-0'").run();
    assert.throws(() => verifyReplayRecords(f.scope, f.targets()), /Echo admission changed/);
    f.hermes.prepare("UPDATE session_admissions SET generation=1 WHERE admission_id='admission-0'").run();
    const changed = structuredClone(f.scope); changed.bindings.pop();
    assert.throws(() => verifyReplayRecords(changed, f.targets()), /exactly the eight/);
    f.tasks[0].status.state = 1; writeFileSync(f.scope.dsh.path, JSON.stringify(f.tasks));
    assert.throws(() => verifyReplayRecords(f.scope, f.targets()), /reviewed hash/);
    const deliveries = new Map(f.scope.bindings.filter(b => b.agentId === 'dsh').map(b => [b.sendId,
      f.db.prepare('SELECT payload FROM workroom_sends WHERE id=?').get(b.sendId).payload]));
    assert.throws(() => verifyDshOrigins(f.tasks, f.scope.bindings, deliveries), /replayable/);
  } finally { f.close(); }
});

test('startup checks reject enabled or changed tasks, active login shortcuts, changed parked bytes, and replacement scope', async () => {
  const f = await fixture();
  try {
    verifyStartupControls(f.scope, f.taskObservations);
    const enabled = structuredClone(f.taskObservations); enabled[0].enabled = true;
    assert.throws(() => verifyStartupControls(f.scope, enabled), /restart owner/);
    const changed = structuredClone(f.taskObservations); changed[0].actions[0].Arguments = 'different';
    assert.throws(() => verifyStartupControls(f.scope, changed), /restart owner/);
    writeFileSync(f.scope.startup.shortcuts[0].original, 'Active');
    assert.throws(() => verifyStartupControls(f.scope, f.taskObservations), /shortcut remains active/);
    assert.equal(existsSync(f.scope.startup.shortcuts[0].parked), true);
    loadOperatorScope(f.options.scopePath, f.options.scopeSha256);
    writeFileSync(f.options.scopePath, readFileSync(f.options.scopePath, 'utf8') + ' ');
    assert.throws(() => loadOperatorScope(f.options.scopePath, f.options.scopeSha256), /reviewed hash/);
  } finally { f.close(); }
});

test('the final composed guard rolls back when replay becomes uncertain or its exact input changes before commit', async () => {
  for (const corruption of ['status', 'echoText', 'dshSnapshot', 'relayShortcut']) {
  const f = await fixture();
  try {
    await runLegacyOperator({ ...f.options, action: 'prepare' }, f.runtime); f.boot();
    let checks = 0;
    const runtime = { ...f.runtime, startupReader() {
      if (++checks === 4) {
        if (corruption === 'dshSnapshot') writeFileSync(f.scope.dsh.path, JSON.stringify([...f.tasks, { id: 'unreviewed-task', history: [] }]));
        else if (corruption === 'relayShortcut') writeFileSync(f.scope.startup.shortcuts[2].original, readFileSync(f.scope.startup.shortcuts[2].parked));
        else if (corruption === 'echoText') f.hermes.prepare("UPDATE session_admissions SET payload_json=? WHERE admission_id='admission-0'").run(JSON.stringify({ text: 'Different original' }));
        else f.hermes.prepare("UPDATE session_admissions SET status='unknown' WHERE admission_id='admission-0'").run();
      }
      return structuredClone(f.taskObservations);
    } };
    await assert.rejects(runLegacyOperator({ ...f.options, action: 'apply', ...f.authorize() }, runtime),
      corruption === 'relayShortcut' ? /login shortcut remains active/ : corruption === 'dshSnapshot' ? /EACCES|EPERM|EBUSY/ : /readonly database/);
    assert.equal(f.db.prepare("SELECT COUNT(*) AS n FROM sqlite_master WHERE name LIKE 'workroom_legacy_recover%'").get().n, 0);
    assert.equal(f.db.prepare("SELECT COUNT(*) AS n FROM workroom_events WHERE kind='legacy_recovery_recorded'").get().n, 0);
    assert.equal(f.barrier.status().state, 'paused'); assert.equal(f.barrier.status().held, false);
  } finally { f.close(); }
  }
});


test('exact native receipts cannot substitute another request with the same completed status and conversation', async () => {
  const f = await fixture();
  try {
    f.relay.prepare("UPDATE outbox SET content='Different request' WHERE idem_key='send-0'").run();
    assert.throws(() => verifyReplayRecords(f.scope, f.targets()), /original delivery payload/);
    f.relay.prepare("UPDATE outbox SET content='Synthetic delivery 0' WHERE idem_key='send-0'").run();
    f.hermes.prepare("UPDATE session_admissions SET payload_json=? WHERE admission_id='admission-0'").run(JSON.stringify({text:'Different request'}));
    assert.throws(() => verifyReplayRecords(f.scope, f.targets()), /Echo request text/);
    f.hermes.prepare("UPDATE session_admissions SET payload_json=? WHERE admission_id='admission-0'").run(JSON.stringify({text:'Synthetic delivery 0'}));
    const other = structuredClone(f.scope); other.bindings[0].conversationId = 'another-conversation';
    f.relay.prepare("UPDATE outbox SET session_id='another-conversation' WHERE idem_key='send-0'").run();
    assert.throws(() => verifyReplayRecords(other, f.targets()), /original Workroom delivery/);
    f.relay.prepare("UPDATE outbox SET session_id='fixture-session' WHERE idem_key='send-0'").run();
    const swapped = structuredClone(f.scope), a = swapped.bindings[6], b = swapped.bindings[7];
    [a.nativeTaskId, b.nativeTaskId] = [b.nativeTaskId, a.nativeTaskId];
    [a.nativeFingerprint, b.nativeFingerprint] = [b.nativeFingerprint, a.nativeFingerprint];
    [a.originMessageId, b.originMessageId] = [b.originMessageId, a.originMessageId];
    [a.originFingerprint, b.originFingerprint] = [b.originFingerprint, a.originFingerprint];
    assert.throws(() => verifyReplayRecords(swapped, f.targets()), /Relay receipt changed/);
    const originalDeliveries=new Map(f.scope.bindings.filter(binding=>binding.agentId==='dsh').map(binding=>
      [binding.sendId,f.db.prepare('SELECT payload FROM workroom_sends WHERE id=?').get(binding.sendId).payload]));
    assert.throws(() => verifyDshOrigins(f.tasks,swapped.bindings,originalDeliveries), /DSH request text/);
    assert.equal(verifyReplayRecords(f.scope, f.targets()).exactAcceptedSends, 8);
  } finally { f.close(); }
});

test('delivery normalization matches Python strip, including Unicode boundaries and preserved interior whitespace', async () => {
  const f = await fixture();
  try {
    const inputs = ['\u0085Synthetic delivery 0\u001c', '\u001f\t Synthetic delivery 0\u3000',
      '\ufeffSynthetic delivery 0\ufeff', ' \tSynthetic  delivery\n0\r ', '\u200bSynthetic delivery 0\u200b'];
    const expected = JSON.parse(execFileSync('python', ['-X', 'utf8', '-c',
      'import json,sys;print(json.dumps([v.strip() for v in json.load(sys.stdin)]))'],
    { input: JSON.stringify(inputs), encoding: 'utf8', windowsHide: true, timeout: 10000 }));
    for (let n = 0; n < inputs.length; n++) {
      f.db.prepare("UPDATE workroom_sends SET payload=? WHERE id='send-0'").run(inputs[n]);
      f.relay.prepare("UPDATE outbox SET content=? WHERE idem_key='send-0'").run(expected[n]);
      f.hermes.prepare("UPDATE session_admissions SET payload_json=?,payload_digest=? WHERE admission_id='admission-0'")
        .run(JSON.stringify({ text: expected[n] }), sha(expected[n]));
      const receipt = f.hermes.prepare("SELECT admission_id,request_id,target_session_id,payload_digest,status,outcome,owner_epoch,generation FROM session_admissions WHERE admission_id='admission-0'").get();
      f.scope.bindings[0].nativeFingerprint = hash(receipt);
      f.scope.bindings[0].relayReceiptFingerprint = hash(f.relay.prepare("SELECT idem_key,agent_id,session_id,state,transport_ref,content FROM outbox WHERE idem_key='send-0'").get());
      assert.doesNotThrow(() => verifyReplayRecords(f.scope, f.targets()), 'Python-normalized delivery case ' + n);
    }
  } finally { f.close(); }
});

test('the boundary classifier matches Python across every Unicode codepoint and preserves interior whitespace', () => {
  const pythonWhitespace = JSON.parse(execFileSync('python', ['-X', 'utf8', '-c',
    'import json;print(json.dumps([n for n in range(0x110000) if chr(n).isspace()]))'],
  { encoding: 'utf8', windowsHide: true, timeout: 10000 }));
  const stripped = new Set(pythonWhitespace);
  for (let n = 0; n < 0x110000; n++) {
    const character = String.fromCodePoint(n), input = character + 'anchor' + character;
    assert.equal(normalizeRelayDelivery(input), stripped.has(n) ? 'anchor' : input, 'Boundary codepoint ' + n);
  }
  for (const n of stripped) {
    const input = 'left' + String.fromCodePoint(n) + 'right';
    assert.equal(normalizeRelayDelivery(input), input, 'Interior codepoint ' + n);
  }
});

test('DSH binds the pinned origin message and supports later follow-up history without inferring original success', async () => {
  const f = await fixture();
  try {
    const followup = f.tasks[1].history.at(-1);
    assert.equal(verifyReplayRecords(f.scope, f.targets()).completedDshTasks, 2);
    const wrong = structuredClone(f.scope); wrong.bindings[7].originMessageId = followup.messageId;
    wrong.bindings[7].originFingerprint = hash(followup);
    assert.throws(() => verifyReplayRecords(wrong, f.targets()), /DSH origin/);
    f.tasks[1].history.unshift({ ...followup, taskId: '', messageId: 'unrelated-origin' });
    writeFileSync(f.scope.dsh.path, JSON.stringify(f.tasks));
    assert.throws(() => verifyReplayRecords(f.scope, f.targets()), /reviewed hash/);
    const deliveries = new Map(f.scope.bindings.filter(b => b.agentId === 'dsh').map(b => [b.sendId,
      f.db.prepare('SELECT payload FROM workroom_sends WHERE id=?').get(b.sendId).payload]));
    assert.throws(() => verifyDshOrigins(f.tasks, f.scope.bindings, deliveries), /DSH origin/);
    f.tasks[1].history.shift();
    const duplicate = structuredClone(f.tasks[1]); duplicate.id = 'unrelated-task';
    writeFileSync(f.scope.dsh.path, JSON.stringify([...f.tasks, duplicate]));
    assert.throws(() => verifyReplayRecords(f.scope, f.targets()), /reviewed hash/);
    assert.throws(() => verifyDshOrigins([...f.tasks, duplicate], f.scope.bindings, deliveries), /DSH origin/);
  } finally { f.close(); }
});

test('the reviewed DSH snapshot rejects changes outside selected receipts instead of trusting origin placement alone', async () => {
  const f = await fixture();
  try {
    f.tasks.push({ id: 'unreviewed-task', contextId: 'elsewhere', status: { state: 2 }, history: [] });
    writeFileSync(f.scope.dsh.path, JSON.stringify(f.tasks));
    assert.throws(() => verifyReplayRecords(f.scope, f.targets()), /reviewed hash/);
  } finally { f.close(); }
});

test('retained-record diagnostics show exact links and private row digests without exposing content or deciding writer scope', async () => {
  const f = await fixture();
  try {
    f.scope.relay.extraSecret = 'SCOPE_SECRET_DO_NOT_EMIT';
    f.relay.prepare("INSERT INTO outbox VALUES('old-delivery','echo','fixture-session','retrying',NULL,?)").run('PRIVATE_BODY_DO_NOT_EMIT');
    f.relay.prepare("UPDATE outbox SET state='retrying' WHERE idem_key='send-0'").run();
    f.hermes.exec('ALTER TABLE session_admissions ADD COLUMN principal_id TEXT;');
    f.hermes.prepare(`INSERT INTO session_admissions(admission_id,request_id,target_session_id,payload_digest,status,outcome,owner_epoch,generation,payload_json,principal_id)
      VALUES('unbound-admission','old-native','another-session','digest','unknown',NULL,1,1,?,?)`)
      .run(JSON.stringify({ native_text_v1: { text: 'PRIVATE_BODY_DO_NOT_EMIT' } }), 'messaging:telegram:PRIVATE_PRINCIPAL_DO_NOT_EMIT');
    const snapshot = () => hash({ sends: f.db.prepare('SELECT * FROM workroom_sends').all(), relay: f.relay.prepare('SELECT * FROM outbox').all(),
      native: f.hermes.prepare('SELECT * FROM session_admissions').all(), tables: f.db.prepare("SELECT name FROM sqlite_master ORDER BY name").all() });
    const before = snapshot(), report = inspectRetainedRecords(f.scope), serialized = JSON.stringify(report);
    assert.equal(snapshot(), before);
    assert.equal(report.records.length, 3); assert.equal(report.canRelease, false);
    for (const privateValue of ['PRIVATE_BODY_DO_NOT_EMIT', 'PRIVATE_PRINCIPAL_DO_NOT_EMIT', 'SCOPE_SECRET_DO_NOT_EMIT'])
      assert.ok(!serialized.includes(privateValue), 'Diagnostic exposed ' + privateValue);
    const old = report.records.find(record => record.recordId === 'old-delivery');
    assert.deepEqual(old.directWorkroomTaskIds, []); assert.equal(old.sharedConversationTaskIds.length, 1);
    const linked = report.records.find(record => record.recordId === 'send-0'); assert.equal(linked.directWorkroomTaskIds.length, 1);
    const native = report.records.find(record => record.recordId === 'unbound-admission');
    assert.equal(native.principalClass, 'telegram'); assert.deepEqual(native.directWorkroomTaskIds, []);
    for (const record of report.records) {
      assert.match(record.recordFingerprint, /^[a-f0-9]{64}$/); assert.equal(record.decision, 'unresolved_do_not_release');
    }
    f.relay.prepare("UPDATE outbox SET content='Changed private request' WHERE idem_key='old-delivery'").run();
    assert.notEqual(inspectRetainedRecords(f.scope).records.find(record => record.recordId === 'old-delivery').recordFingerprint, old.recordFingerprint);
  } finally { f.close(); }
});

test('inspect explains unmatched records while the same apply path still refuses them', async () => {
  const f = await fixture();
  try {
    await runLegacyOperator({ ...f.options, action: 'prepare' }, f.runtime); f.boot();
    f.relay.prepare("INSERT INTO outbox VALUES('old-delivery','echo','elsewhere','retrying',NULL,'Private fixture')").run();
    const result = await runLegacyOperator({ ...f.options, action: 'inspect' }, f.runtime);
    assert.equal(result.controls.status, 'blocked'); assert.equal(result.canRelease, false);
    assert.equal(result.retainedRecords.records[0].recordId, 'old-delivery');
    await assert.rejects(runLegacyOperator({ ...f.options, action: 'apply', ...f.authorize() }, f.runtime), /unresolved queued/);
    assert.equal(f.db.prepare("SELECT COUNT(*) AS n FROM sqlite_master WHERE name LIKE 'workroom_legacy_recover%'").get().n, 0);
  } finally { f.close(); }
});

test('diagnose refuses file overrides and an unrelated current directory before opening native data', async () => {
  const f = await fixture();
  try {
    const script = resolve('integrations/legacy-recovery-operator.mjs');
    const override = spawnSync(process.execPath, [script, 'diagnose', '--ignore-holds'], { cwd: f.dir, windowsHide: true, encoding: 'utf8' });
    assert.equal(override.status, 1); assert.match(override.stderr, /no scope, overrides or approval/);
    const elsewhere = spawnSync(process.execPath, [script, 'diagnose'], { cwd: f.dir, windowsHide: true, encoding: 'utf8' });
    assert.equal(elsewhere.status, 1); assert.match(elsewhere.stderr, /from its Mesh workspace/);
    assert.equal(override.stdout, ''); assert.equal(elsewhere.stdout, '');
  } finally { f.close(); }
});

// Qualification metadata is synthetic here; files are hashed, not executed.
// Real startup execution is qualified separately by the committed helper scripts.
function retainedFixture(f) {
  f.relay.prepare("INSERT INTO outbox VALUES('old-dsh','dsh','fixture-session','retrying',NULL,'Synthetic private request')").run();
  f.relay.prepare("INSERT INTO outbox VALUES('old-cyony','cyony','elsewhere','retrying',NULL,'Synthetic other request')").run();
  f.hermes.exec('ALTER TABLE session_admissions ADD COLUMN principal_id TEXT;');
  f.hermes.prepare(`INSERT INTO session_admissions(admission_id,request_id,target_session_id,payload_digest,status,outcome,owner_epoch,generation,payload_json,principal_id)
    VALUES('old-unknown','old-input','elsewhere','digest','unknown',NULL,1,1,?,'messaging:telegram:synthetic')`)
    .run(JSON.stringify({ native_text_v1: { text: 'Synthetic request' } }));
  const hashFiles = files => Object.fromEntries(files.map(([name, file]) => [name, sha(readFileSync(file))]));
  const relayNames = ['relay_server.py','relay_a2a.py','relay_a2a_reconcile.py','relay_auth.py','relay_budget.py','relay_channels.py',
    'relay_config.py','relay_db.py','relay_hermes.py','relay_inbox.py','relay_mcp.py','relay_native_receipts.py','relay_notify.py','relay_openclaw.py','relay_sessions.py','relay_webpush.py'];
  const relay = { schema: 'mesh/relay-retained-startup-qualification/v1', liveStoreOpened: false, liveDeploymentChanged: false,
    networkOrProcessAttempts: 0, boundaryRejectionControlsPassed: 3,
    cases: [1,2].map(boot => ({ boot, startupTransportCalls: 0, duplicateTransportCalls: 0, freshRequestTransportCalls: 1, retainedRowsUnchanged: true })),
    sourceSha256: hashFiles(relayNames.map(name => [name, resolve('D:/Dev/Onoes-Relay',name)])),
    qualificationHelperSha256: sha(readFileSync('integrations/qualify-relay-retained-startup.py')) };
  const nativeRoot = resolve(homedir(), 'AppData/Local/hermes/hermes-agent');
  const native = { schema: 'mesh/native-retained-startup-qualification/v1', liveStoreOpened: false, liveServiceRestarted: false,
    originalWorkerRetirementEstablished: false, coordinatorIsPrimaryRecovery: true,
    recoveries: [1,2].map(startup => ({ startup, syntheticModelCalls: startup === 1 ? 1 : 0, unknownRemainedPaused: true,
      blockedFollowerRemainedQueued: true, safeRequestCompleted: true, gatewayCoordinatorPreservedRows: true })),
    sourceSha256: hashFiles(Object.entries(legacyRecoverySources(process.cwd())).filter(([name]) => name.startsWith('hermesRecovery'))
      .map(([,file]) => [relative(nativeRoot,file).split('\\').join('/'),file])),
    helperSha256: hashFiles(['qualify-native-retained-startup.py','qualify-native-retained-peer.py','qualify-native-retained-recovery.py']
      .map(name => [name,resolve('integrations',name)])) };
  const save = (name, data) => { const path = join(f.dir,name); writeFileSync(path,JSON.stringify(data));return { path, sha256:sha(readFileSync(path)) }; };
  const actual = inspectRetainedRecords(f.scope);
  const review = { schema: 'mesh/retained-record-review/v1', owner:'Eddie', decision:'preserve_without_retry_or_retirement',
    writerScope:'confirmed_desktop_only', selectedSendIds:f.scope.bindings.map(binding=>binding.sendId),
    records:actual.records, sources:actual.sources, qualifications:{ relay:save('relay-proof.json',relay),native:save('native-proof.json',native) } };
  function seal() {
    f.scope.retainedReview=save('retained-review.json',review);
    writeFileSync(f.options.scopePath,JSON.stringify(f.scope));f.options.scopeSha256=sha(readFileSync(f.options.scopePath));
  }
  seal();return { review, relay, native, save, seal };
}

test('a matching retained review cannot replace later-boot and exact quiet-window authority', async () => {
  const f = await fixture();
  try {
    retainedFixture(f);
    await runLegacyOperator({ ...f.options,action:'prepare' },f.runtime);
    await assert.rejects(runLegacyOperator({...f.options,action:'apply',...f.authorize()},f.runtime),/later_pc_boot/);
    f.boot();
    const rows=()=>hash({relay:f.relay.prepare('SELECT * FROM outbox').all(),native:f.hermes.prepare('SELECT * FROM session_admissions').all()});
    const before=rows(), result=verifyRetainedReview(f.scope);
    assert.equal(result.status,'matched_review_only');assert.equal(result.canRelease,false);assert.equal(result.workerRetirementEstablished,false);
    assert.equal(rows(),before);
    const inspected=await runLegacyOperator({...f.options,action:'inspect'},f.runtime);
    assert.equal(inspected.retainedReview.status,'matched_review_only');assert.equal(inspected.controls.status,'verified');assert.equal(inspected.canRelease,false);
    await assert.rejects(runLegacyOperator({...f.options,action:'apply',...f.authorize()},f.runtime),/quiet-window authority/);
    assert.equal(f.db.prepare("SELECT COUNT(*) AS n FROM sqlite_master WHERE name LIKE 'workroom_legacy_recover%'").get().n,0);
    assert.equal(rows(),before);
  } finally {f.close();}
});

test('retained reviews reject row/link/schema drift, new work and missing owner scope without using absence of task IDs as scope proof',async()=>{
  for(const change of ['row','link','schema','newWork','ownerScope','selectedSend','automation','nativeNull']) {
    const f=await fixture();
    try {
      const r=retainedFixture(f);
      if(change==='row')f.relay.prepare("UPDATE outbox SET content='Changed' WHERE idem_key='old-dsh'").run();
      if(change==='link'){
        f.db.prepare("UPDATE workroom_sends SET conversationId='moved-conversation' WHERE conversationId='fixture-session'").run();
        assert.equal(inspectRetainedRecords(f.scope).records.find(record=>record.recordId==='old-dsh').recordFingerprint,
          r.review.records.find(record=>record.recordId==='old-dsh').recordFingerprint);
      }
      if(change==='schema')f.relay.exec('ALTER TABLE outbox ADD COLUMN extra TEXT');
      if(change==='newWork')f.relay.prepare("INSERT INTO outbox VALUES('new','dsh','elsewhere','queued',NULL,'New')").run();
      if(change==='ownerScope'){r.review.writerScope='pending';r.seal();}
      if(change==='selectedSend'){r.review.selectedSendIds.pop();r.seal();}
      if(change==='automation'||change==='nativeNull'){
        f.hermes.prepare("UPDATE session_admissions SET payload_json=? WHERE admission_id='old-unknown'").run(JSON.stringify(change==='automation'?{local_automation_v1:{}}:{native_text_v1:null}));
        r.review.records=inspectRetainedRecords(f.scope).records;r.seal();
      }
      assert.throws(()=>verifyRetainedReview(f.scope));
    }finally{f.close();}
  }
});

test('retained reviews require exact pinned proofs, complete source sets, current qualifier bytes and full coordinator evidence',async()=>{
  for(const change of ['nativeSource','relaySourceSet','helper','coordinator','proofBytes','reviewBytes','malformed']) {
    const f=await fixture();
    try {
      const r=retainedFixture(f);
      if(change==='nativeSource')r.native.sourceSha256['gateway/session_authority.py']='0'.repeat(64);
      if(change==='relaySourceSet')delete r.relay.sourceSha256['relay_a2a.py'];
      if(change==='helper')r.native.helperSha256['qualify-native-retained-peer.py']='0'.repeat(64);
      if(change==='coordinator')r.native.coordinatorIsPrimaryRecovery=false;
      if(['nativeSource','helper','coordinator'].includes(change)){r.review.qualifications.native=r.save('native-proof.json',r.native);r.seal();}
      if(change==='relaySourceSet'){r.review.qualifications.relay=r.save('relay-proof.json',r.relay);r.seal();}
      if(change==='proofBytes')writeFileSync(r.review.qualifications.native.path,'{}');
      if(change==='reviewBytes')writeFileSync(f.scope.retainedReview.path,'{}');
      if(change==='malformed'){writeFileSync(f.scope.retainedReview.path,'PRIVATE_BAD_JSON');f.scope.retainedReview.sha256=sha(readFileSync(f.scope.retainedReview.path));}
      assert.throws(()=>verifyRetainedReview(f.scope),change==='malformed'?/not valid JSON/:undefined);
    }finally{f.close();}
  }
});

test('offline v3 refuses the old layout, an active Relay login entry, or missing Relay socket coverage', async()=>{
  const f=await fixture();
  try{
    const save=()=>{writeFileSync(f.options.scopePath,JSON.stringify(f.scope));f.options.scopeSha256=sha(readFileSync(f.options.scopePath));};
    f.scope.schema='mesh/legacy-operator-scope/v1';save();assert.throws(()=>loadOperatorScope(f.options.scopePath,f.options.scopeSha256),/offline v3/);
    f.scope.schema='mesh/legacy-operator-scope/v3';const link=f.scope.startup.shortcuts.pop();save();assert.throws(()=>loadOperatorScope(f.options.scopePath,f.options.scopeSha256),/startup owners/);
    f.scope.startup.shortcuts.push(link);save();verifyStartupControls(f.scope,f.taskObservations);
    writeFileSync(link.original,readFileSync(link.parked));assert.throws(()=>verifyStartupControls(f.scope,f.taskObservations),/login shortcut remains active/);
    const production=structuredClone(f.scope),at=suffix=>resolve(homedir(),suffix);
    production.databasePath=resolve(production.workspace,'data/workroom-preview/tasks.sqlite');
    production.relay.path=resolve('D:/Dev/Onoes-Relay/.private/relay.sqlite3');production.hermes.path=at('AppData/Local/hermes/state.db');production.dsh.path=at('.dsh/a2a/runtime/tasks/a2a-tasks.json');
    production.nativeResources={profileLocks:[at('AppData/Local/hermes/gateway.lock')],endpoints:[3081,4123,8642,8787].flatMap(port=>[['127.0.0.1',port],['::1',port]]),workerRuntimeNames:[...productionWorkerRuntimeNames]};
    production.startup.shortcuts=production.startup.shortcuts.map(item=>({...item,original:at('AppData/Roaming/Microsoft/Windows/Start Menu/Programs/Startup/'+item.original.split(/[\\/]/).at(-1))}));
    verifyDeploymentScope(production);
    production.nativeResources.workerRuntimeNames=['node.exe'];assert.throws(()=>verifyDeploymentScope(production),/complete deployed worker runtime/);
    production.nativeResources.workerRuntimeNames=[...productionWorkerRuntimeNames];
    production.nativeResources.endpoints=production.nativeResources.endpoints.filter(([,port])=>port!==8787);
    assert.throws(()=>verifyDeploymentScope(production),/eight worker loopback/);
  }finally{f.close();}
});

test('a worker listener on the fourth offline socket prevents recovery and partial leases are released',async()=>{
  const f=await fixture();let contender;
  try{
    await runLegacyOperator({...f.options,action:'prepare'},f.runtime);f.boot();
    const [host,port]=f.scope.nativeResources.endpoints[6];contender=createServer();await new Promise(done=>contender.listen(port,host,done));
    await assert.rejects(runLegacyOperator({...f.options,action:'apply',...f.authorize()},f.runtime));
    assert.equal(f.db.prepare("SELECT COUNT(*) AS n FROM sqlite_master WHERE name LIKE 'workroom_legacy_recover%'").get().n,0);
    assert.equal(f.barrier.status().held,false);
    await new Promise(done=>contender.close(done));contender=null;
    const result=await runLegacyOperator({...f.options,action:'apply',...f.authorize()},f.runtime);
    assert.equal(result.dispatchRemainsPaused,true);assert.equal(f.barrier.status().held,false);
  }finally{if(contender)await new Promise(done=>contender.close(done));f.close();}
});


function retainedAuthority(f, changes = {}) {
  const approval=f.authorize();const record=JSON.parse(readFileSync(approval.authorizationPath,'utf8'));
  Object.assign(record,{maintenanceMode:'worker_services_offline',quietWorkspaceConfirmed:true,
    retainedReviewSha256:f.scope.retainedReview.sha256},changes);
  writeFileSync(approval.authorizationPath,JSON.stringify(record));
  approval.authorizationSha256=sha(readFileSync(approval.authorizationPath));return approval;
}

test('offline recovery preserves all retained rows and original sends under exact later-boot quiet-window authority',async()=>{
  const f=await fixture();
  try{
    retainedFixture(f);
    const originals=()=>hash({sends:f.db.prepare('SELECT * FROM workroom_sends ORDER BY id').all(),
      relay:f.relay.prepare('SELECT * FROM outbox ORDER BY idem_key').all(),native:f.hermes.prepare('SELECT * FROM session_admissions ORDER BY admission_id').all()});
    const before=originals();await runLegacyOperator({...f.options,action:'prepare'},f.runtime);f.boot();
    const result=await runLegacyOperator({...f.options,action:'apply',...retainedAuthority(f)},f.runtime);
    assert.equal(result.disposition,'historical_outcome_unknown');assert.equal(result.dispatchRemainsPaused,true);
    assert.equal(originals(),before);assert.equal(f.db.prepare('SELECT COUNT(*) AS n FROM workroom_legacy_recovery_sends').get().n,8);
    assert.equal(f.barrier.status().state,'paused');assert.equal(f.barrier.status().held,false);
  }finally{f.close();}
});

test('retained offline authority cannot omit its exact review hash or replace a quiet-window confirmation',async()=>{
  for(const changes of [{quietWorkspaceConfirmed:false},{quietWorkspaceConfirmed:'true'},
    {maintenanceMode:'online'},{retainedReviewSha256:'0'.repeat(64)}]){
    const f=await fixture();
    try{
      retainedFixture(f);await runLegacyOperator({...f.options,action:'prepare'},f.runtime);f.boot();
      await assert.rejects(runLegacyOperator({...f.options,action:'apply',...retainedAuthority(f,changes)},f.runtime),/quiet-window authority/);
      assert.equal(f.db.prepare("SELECT COUNT(*) AS n FROM sqlite_master WHERE name LIKE 'workroom_legacy_recover%'").get().n,0);
      assert.equal(f.barrier.status().held,false);
    }finally{f.close();}
  }
});

test('retained row or proof drift at the final offline boundary rolls back the entire recovery',async()=>{
  for(const change of ['row','proof','shortcut']){
    const f=await fixture();
    try{
      const r=retainedFixture(f);await runLegacyOperator({...f.options,action:'prepare'},f.runtime);f.boot();
      let checks=0;const runtime={...f.runtime,startupReader(){
        if(++checks===4){
          if(change==='row')f.relay.prepare("UPDATE outbox SET content='Changed during recovery' WHERE idem_key='old-dsh'").run();
          if(change==='proof')writeFileSync(r.review.qualifications.native.path,'{}');
          if(change==='shortcut')writeFileSync(f.scope.startup.shortcuts[2].original,readFileSync(f.scope.startup.shortcuts[2].parked));
        }
        return structuredClone(f.taskObservations);
      }};
      await assert.rejects(runLegacyOperator({...f.options,action:'apply',...retainedAuthority(f)},runtime));
      assert.equal(f.db.prepare("SELECT COUNT(*) AS n FROM sqlite_master WHERE name LIKE 'workroom_legacy_recover%'").get().n,0);
      assert.equal(f.db.prepare("SELECT COUNT(*) AS n FROM workroom_events WHERE kind='legacy_recovery_recorded'").get().n,0);
      assert.equal(f.barrier.status().state,'paused');assert.equal(f.barrier.status().held,false);
    }finally{f.close();}
  }
});


test('offline apply refuses an existing external writable handle without releasing the original hold',async()=>{
  const f=await fixture();let writer;
  try{
    await runLegacyOperator({...f.options,action:'prepare'},f.runtime);f.boot();writer=openSync(f.scope.relay.path,'r+');
    await assert.rejects(runLegacyOperator({...f.options,action:'apply',...f.authorize()},f.runtime),/File read barrier refused/);
    assert.equal(f.db.prepare("SELECT COUNT(*) AS n FROM sqlite_master WHERE name LIKE 'workroom_legacy_recover%'").get().n,0);
    assert.equal(f.barrier.status().state,'paused');assert.equal(f.barrier.status().held,false);
    closeSync(writer);writer=undefined;
    const result=await runLegacyOperator({...f.options,action:'apply',...f.authorize()},f.runtime);assert.equal(result.dispatchRemainsPaused,true);
  }finally{if(writer!==undefined)closeSync(writer);f.close();}
});

test('reviewed source cannot be replaced by a late writer during the actual recovery commit path',async()=>{
  const f=await fixture();
  try{
    const source=join(f.dir,'pinned-source.mjs');writeFileSync(source,'Frozen module');f.scope.additionalSources={disposablePinnedSource:source};
    writeFileSync(f.options.scopePath,JSON.stringify(f.scope));f.options.scopeSha256=sha(readFileSync(f.options.scopePath));
    await runLegacyOperator({...f.options,action:'prepare'},f.runtime);f.boot();let denials=0,checks=0;
    const runtime={...f.runtime,startupReader(){if(++checks>=3){assert.throws(()=>writeFileSync(source,'Late change'),/EACCES|EPERM|EBUSY/);denials++;}return structuredClone(f.taskObservations);}};
    const result=await runLegacyOperator({...f.options,action:'apply',...f.authorize()},runtime);assert.equal(result.dispatchRemainsPaused,true);assert.ok(denials>=2);
    assert.equal(readFileSync(source,'utf8'),'Frozen module');writeFileSync(source,'Writable after the operator returns');
  }finally{f.close();}
});


test('a non-listening worker starting at the final recovery boundary rolls back every administrative write',async()=>{
  const f=await fixture();let child;
  try{
    const image=join(f.dir,f.scope.nativeResources.workerRuntimeNames[0]);copyFileSync('C:/Python314/python.exe',image);
    await runLegacyOperator({...f.options,action:'prepare'},f.runtime);f.boot();let checks=0;
    const runtime={...f.runtime,startupReader(){
      if(++checks===4){child=spawn(image,['-B','-S','-c',"import sys;print('held',flush=True);sys.stdin.readline()"],{cwd:f.dir,env:{...process.env,PYTHONHOME:'C:/Python314',PATH:'C:/Python314;'+process.env.PATH},stdio:['pipe','pipe','pipe'],windowsHide:true});assert.ok(child.pid);}
      return structuredClone(f.taskObservations);
    }};
    await assert.rejects(runLegacyOperator({...f.options,action:'apply',...f.authorize()},runtime),/Covered worker runtimes remain active/);
    assert.equal(child.exitCode,null);assert.equal(f.db.prepare("SELECT COUNT(*) AS n FROM sqlite_master WHERE name LIKE 'workroom_legacy_recover%'").get().n,0);
    assert.equal(f.db.prepare("SELECT COUNT(*) AS n FROM workroom_events WHERE kind='legacy_recovery_recorded'").get().n,0);
    assert.equal(f.barrier.status().state,'paused');assert.equal(f.barrier.status().held,false);
    const exited=once(child,'exit');child.stdin.end('done\n');assert.equal((await exited)[0],0);
  }finally{if(child&&child.exitCode===null&&child.signalCode===null){const exited=once(child,'exit');child.kill();await exited;}f.close();}
});

test('quiet-window authority is mandatory even when no retained-record exception is requested',async()=>{
  for(const change of [{quietWorkspaceConfirmed:false},{maintenanceMode:'online'}]){
    const f=await fixture();try{
      await runLegacyOperator({...f.options,action:'prepare'},f.runtime);f.boot();const approval=f.authorize();
      const record=JSON.parse(readFileSync(approval.authorizationPath,'utf8'));Object.assign(record,change);writeFileSync(approval.authorizationPath,JSON.stringify(record));approval.authorizationSha256=sha(readFileSync(approval.authorizationPath));
      await assert.rejects(runLegacyOperator({...f.options,action:'apply',...approval},f.runtime),/quiet-window authority/);
      assert.equal(f.barrier.status().held,false);assert.equal(f.db.prepare("SELECT COUNT(*) AS n FROM sqlite_master WHERE name LIKE 'workroom_legacy_recover%'").get().n,0);
    }finally{f.close();}
  }
});


test('forged saved runtime clearance is rejected even when the evidence hash is recomputed',async()=>{
  const f=await fixture();try{
    await runLegacyOperator({...f.options,action:'prepare'},f.runtime);f.boot();await runLegacyOperator({...f.options,action:'apply',...f.authorize()},f.runtime);
    const target=f.targets()[0],store=createLegacyRecoveryStore(f.db),row=f.db.prepare('SELECT * FROM workroom_legacy_recoveries').get();
    assert.ok(store.read(target.taskId,target.sendId));
    for(const mutation of [{observedRuntimeEntrypointsClear:false},{observedOutsideRuntimeCount:1},{coveredLocalWriters:true}]){
      const evidence=JSON.parse(row.evidence);Object.assign(evidence.boundary,mutation);
      f.db.prepare('UPDATE workroom_legacy_recoveries SET evidence=?,proofHash=?').run(JSON.stringify(evidence),hash(evidence));
      assert.equal(store.read(target.taskId,target.sendId),null);
    }
  }finally{f.close();}
});


test('all five known restart owners are required; a missing Mesh/model/guardian or an unrelated Windows task cannot substitute',async()=>{
  const f=await fixture();try{
    assert.deepEqual(verifyStartupControls(f.scope,f.taskObservations),{disabledTasks:5,parkedShortcuts:3});
    for(const name of ['ONOes Mesh Workroom Recovery','DSH Local Model Supervisor','Hermes_Gateway_Guardian']){
      const scope=structuredClone(f.scope);scope.startup.tasks=scope.startup.tasks.filter(task=>task.name!==name);
      assert.throws(()=>verifyStartupControls(scope,f.taskObservations),/restart owners/);
      writeFileSync(f.options.scopePath,JSON.stringify(scope));assert.throws(()=>loadOperatorScope(f.options.scopePath,sha(readFileSync(f.options.scopePath))),/startup owners/);
    }
    const scope=structuredClone(f.scope);scope.startup.tasks.find(task=>task.name==='ONOes Mesh Workroom Recovery').name='RunFullMemoryDiagnostic';
    writeFileSync(f.options.scopePath,JSON.stringify(scope));assert.throws(()=>loadOperatorScope(f.options.scopePath,sha(readFileSync(f.options.scopePath))),/startup owners/);
    assert.throws(()=>verifyStartupControls(scope,f.taskObservations),/restart owners/);
  }finally{f.close();}
});

test('re-enabled or still-running Mesh/model/guardian restart owners at the final guard roll back recovery',async()=>{
  for(const name of ['ONOes Mesh Workroom Recovery','DSH Local Model Supervisor','Hermes_Gateway_Guardian'])for(const running of [false,true]){
    const f=await fixture();try{
      await runLegacyOperator({...f.options,action:'prepare'},f.runtime);f.boot();let checks=0;
      const runtime={...f.runtime,startupReader(){
        if(++checks===4){const task=f.taskObservations.find(task=>task.name===name);task.enabled=!running;task.state=running?'Running':'Ready';}
        return structuredClone(f.taskObservations);
      }};
      await assert.rejects(runLegacyOperator({...f.options,action:'apply',...f.authorize()},runtime),/restart owner/);
      assert.equal(f.db.prepare("SELECT COUNT(*) AS n FROM sqlite_master WHERE name LIKE 'workroom_legacy_recover%'").get().n,0);
      assert.equal(f.db.prepare("SELECT COUNT(*) AS n FROM workroom_events WHERE kind='legacy_recovery_recorded'").get().n,0);
      assert.equal(f.barrier.status().state,'paused');assert.equal(f.barrier.status().held,false);
    }finally{f.close();}
  }
});
