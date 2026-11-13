import { randomUUID } from 'node:crypto';
import { TaskError } from './task-store.mjs';
import { databaseFileIdentity, databasePathKey } from './database-identity.mjs';

const holds = new WeakMap();
export function assertDispatchHold(lease, expectedDatabase) {
  const check = holds.get(lease);
  if (!check) throw new TaskError(503, 'An authentic held dispatch barrier is required.');
  if (!expectedDatabase || typeof expectedDatabase.databasePath !== 'string' ||
      !/^[a-f0-9]{64}$/.test(expectedDatabase.databaseIdentity || '')) throw new TaskError(503, 'The exact recovery database binding is required.');
  return check(expectedDatabase);
}

// Trusted operator API only; no HTTP pause/resume control or automatic expiry.
// This fences Mesh admissions, not existing workers or other apps on this PC.
export function createDispatchBarrier(db) {
  const instance = randomUUID();
  function present() {
    const count = db.prepare("SELECT COUNT(*) AS n FROM sqlite_master WHERE type='table' AND name IN ('workroom_dispatch_gate','workroom_dispatch_admissions')").get().n;
    if (count === 1) throw new TaskError(503, 'Dispatch maintenance state is incomplete.');
    return count === 2;
  }
  function status() {
    if (!present()) return { state: 'open', generation: 0, activeAdmissions: 0, held: false };
    const row = db.prepare('SELECT * FROM workroom_dispatch_gate WHERE id=1').get();
    if (!row || !['open','paused'].includes(row.state) || !Number.isSafeInteger(row.generation) || row.generation < 0 ||
        (row.state === 'open' && row.holder)) throw new TaskError(503, 'Dispatch maintenance state is invalid.');
    return { state: row.state, generation: row.generation, held: Boolean(row.holder),
      activeAdmissions: db.prepare("SELECT COUNT(*) AS n FROM workroom_dispatch_admissions WHERE state!='finished'").get().n };
  }
  function initialize() {
    if (present()) return;
    db.exec(`CREATE TABLE workroom_dispatch_gate(id INTEGER PRIMARY KEY CHECK(id=1),state TEXT NOT NULL,generation INTEGER NOT NULL,holder TEXT);
      INSERT INTO workroom_dispatch_gate VALUES(1,'open',0,NULL);
      CREATE TABLE workroom_dispatch_admissions(id TEXT PRIMARY KEY,instance TEXT NOT NULL,pid INTEGER NOT NULL,state TEXT NOT NULL,openedAt TEXT NOT NULL,finishedAt TEXT);`);
  }
  function mutate(action) {
    if (db.isTransaction) throw new TaskError(409, 'Dispatch controls cannot change inside another transaction.');
    db.exec('BEGIN IMMEDIATE;');
    try { initialize(); const result = action(); db.exec('COMMIT;'); return result; }
    catch (error) { db.exec('ROLLBACK;'); throw error; }
  }
  function assertOpen() {
    if (status().state !== 'open') throw new TaskError(503, 'Mesh is paused for maintenance. Your saved card is unchanged.');
    if (present() && db.prepare("SELECT id FROM workroom_dispatch_admissions WHERE state!='finished' AND instance!=? LIMIT 1").get(instance)) {
      throw new TaskError(503, 'An earlier dispatch requires reconciliation before starting another request.');
    }
  }
  async function run(action) {
    if (typeof action !== 'function') throw new TaskError(400, 'A dispatch action is required.');
    const id = mutate(() => {
      assertOpen(); const id = randomUUID();
      db.prepare("INSERT INTO workroom_dispatch_admissions VALUES(?,?,?,'admitted',?,NULL)")
        .run(id, instance, process.pid, new Date().toISOString());
      return id;
    });
    try { return await action(); }
    finally {
      // Retry only this exact local bookkeeping update, never the agent action.
      for (let attempt = 0; ; attempt++) {
        try {
          mutate(() => {
            const changed = db.prepare("UPDATE workroom_dispatch_admissions SET state='finished',finishedAt=? WHERE id=? AND instance=? AND state='admitted'")
              .run(new Date().toISOString(), id, instance).changes;
            if (changed !== 1) throw new TaskError(503, 'The original dispatch admission requires reconciliation.');
          });
          break;
        } catch (error) {
          if (attempt >= 19 || ![5,6].includes(error.errcode)) throw error;
          await new Promise(resolve => setTimeout(resolve,20));
        }
      }
    }
  }
  function pause() {
    return mutate(() => {
      if (status().state === 'open') db.prepare("UPDATE workroom_dispatch_gate SET state='paused',generation=generation+1 WHERE id=1").run();
      return status();
    });
  }
  function hold() {
    const holder = randomUUID();
    let database;
    const generation = mutate(() => {
      const current = status();
      if (current.state !== 'paused' || current.held || current.activeAdmissions) throw new TaskError(409, 'Pause dispatch and reconcile or drain original admissions before holding maintenance.');
      const file = db.prepare('PRAGMA database_list').all().find(row => row.name === 'main')?.file;
      if (!file) throw new TaskError(503, 'A persistent database is required for a maintenance hold.');
      database = { databasePath: databasePathKey(file), databaseIdentity: databaseFileIdentity(file) };
      db.prepare('UPDATE workroom_dispatch_gate SET holder=? WHERE id=1').run(holder);
      return current.generation;
    });
    let released = false;
    const check = expectedDatabase => {
      const file = db.prepare('PRAGMA database_list').all().find(row => row.name === 'main')?.file;
      if (!file || databasePathKey(file) !== database.databasePath || databaseFileIdentity(file) !== database.databaseIdentity ||
          (expectedDatabase && (databasePathKey(expectedDatabase.databasePath) !== database.databasePath ||
            expectedDatabase.databaseIdentity !== database.databaseIdentity))) throw new TaskError(503, 'The held dispatch database does not match recovery.');
      const current = status(), row = db.prepare('SELECT holder FROM workroom_dispatch_gate WHERE id=1').get();
      if (released || current.state !== 'paused' || current.generation !== generation || current.activeAdmissions || row?.holder !== holder)
        throw new TaskError(409, 'The dispatch maintenance hold is no longer current.');
      return { schema: 'mesh-dispatch-hold/v1', scope: 'mesh_admissions_only', generation, dispatchPaused: true, ...database };
    };
    const lease = Object.freeze({ release() {
      mutate(() => { check(); db.prepare('UPDATE workroom_dispatch_gate SET holder=NULL WHERE id=1').run(); });
      released = true;
    } });
    holds.set(lease, check);
    return lease;
  }
  function resume(generation) {
    return mutate(() => {
      const current = status();
      if (!Number.isSafeInteger(generation) || current.generation !== generation || current.state !== 'paused' || current.held || current.activeAdmissions)
        throw new TaskError(409, 'The exact paused generation must be unheld and drained before resuming.');
      db.prepare("UPDATE workroom_dispatch_gate SET state='open',generation=generation+1 WHERE id=1").run();
      return status();
    });
  }
  return Object.freeze({ status, assertOpen, run, pause, hold, resume });
}

export function runDispatchRequest(barrier, method, action) {
  if (['GET','HEAD'].includes(method)) return action();
  if (typeof barrier?.run !== 'function') throw new TaskError(503, 'Dispatch persistence is unavailable.');
  return barrier.run(action);
}
