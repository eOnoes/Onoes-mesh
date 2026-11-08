import {TaskError} from './task-store.mjs';
import {normalizeWriterObservation} from './native-writer-observation.mjs';

const runId = value => typeof value === 'string' && /^run_[A-Za-z0-9_-]{1,128}$/.test(value);
const statuses = new Set(['queued','running','waiting_for_approval','completed','failed','cancelled','interrupted','expired','unknown']);
const terminal = new Set(['completed','failed','cancelled','interrupted','expired']);

export function createNativeReceiptStore(db) {
  db.exec(`CREATE TABLE IF NOT EXISTS workroom_native_receipts (
    sendId TEXT PRIMARY KEY REFERENCES workroom_sends(id), taskId TEXT NOT NULL REFERENCES tasks(id),
    runId TEXT, ownerId TEXT, generation TEXT, receipt TEXT,
    observationState TEXT NOT NULL, revision INTEGER NOT NULL, lastCheckedAt TEXT NOT NULL)`);
  function read(taskId, sendId) {
    const row = db.prepare('SELECT * FROM workroom_native_receipts WHERE taskId=? AND sendId=?').get(taskId,sendId);
    if (!row) return null;
    let receipt = null;
    try { receipt = row.receipt ? JSON.parse(row.receipt) : null; } catch {}
    return {runId:row.runId, ownerId:row.ownerId, generation:row.generation, receipt,
      observationState:row.receipt && !receipt ? 'unavailable' : row.observationState,
      revision:row.revision, lastCheckedAt:row.lastCheckedAt, writerQuiescence:false};
  }
  function binding(taskId, sendId) {
    const send = db.prepare('SELECT id,agentId,conversationId,state FROM workroom_sends WHERE taskId=? AND id=?').get(taskId,sendId);
    if (!send || send.agentId !== 'echo' || !['accepted','prepared','unknown'].includes(send.state)) {
      throw new TaskError(409,'Only this task’s saved Echo send can be observed.');
    }
    const previous = read(taskId,sendId);
    return {agentId:send.agentId,sendId:send.id,conversationId:send.conversationId,
      revision:previous?.revision ?? 0, ...(previous?.runId ? {expectedRunId:previous.runId} : {}),
      ...(previous?.ownerId ? {expectedWriterOwnerId:previous.ownerId,expectedWriterGeneration:previous.generation} : {})};
  }
  function mutate(taskId,sendId,revision,receipt) {
    db.exec('BEGIN IMMEDIATE');
    try {
      const bound = binding(taskId,sendId), previous = read(taskId,sendId);
      if (!Number.isSafeInteger(revision) || revision !== bound.revision) throw new TaskError(409,'A newer native observation is already saved.');
      let next = null;
      if (receipt !== null) {
        if (!receipt || receipt.agentId !== bound.agentId || receipt.sendId !== sendId
            || receipt.conversationId !== bound.conversationId || receipt.writerQuiescence !== false
            || !statuses.has(receipt.status) || !['observed','unknown'].includes(receipt.observation)
            || (receipt.runId !== null && !runId(receipt.runId))
            || (bound.expectedRunId && receipt.runId !== bound.expectedRunId)
            || (receipt.observation === 'unknown' && (receipt.status !== 'unknown' || receipt.terminal !== false))
            || (receipt.observation === 'observed' && (!runId(receipt.runId) || typeof receipt.nativeSessionId !== 'string'
              || !receipt.nativeSessionId || receipt.nativeSessionId.length > 256 || receipt.terminal !== terminal.has(receipt.status)))) {
          throw new TaskError(409,'Native receipt does not match this saved send.');
        }
        let lifecycle;
        if (receipt.writerLifecycle !== undefined || bound.expectedWriterOwnerId) {
          try { lifecycle = normalizeWriterObservation(receipt.writerLifecycle,receipt.runId,bound.expectedWriterOwnerId,bound.expectedWriterGeneration); }
          catch { throw new TaskError(409,'Native writer identity is not the saved assignment.'); }
          if (lifecycle.state === 'observed' && receipt.observation !== 'observed') throw new TaskError(409,'Native writer has no verified receipt.');
        }
        next = {agentId:bound.agentId,sendId,conversationId:bound.conversationId,runId:receipt.runId,
          nativeSessionId:receipt.observation === 'observed' ? receipt.nativeSessionId : null,
          status:receipt.status,observation:receipt.observation,terminal:receipt.terminal,writerQuiescence:false,
          observedAt:new Date().toISOString(),...(lifecycle ? {writerLifecycle:lifecycle} : {})};
      }
      const stamp = new Date().toISOString(), lifecycle = next?.writerLifecycle;
      db.prepare(`INSERT INTO workroom_native_receipts VALUES(?,?,?,?,?,?,?,?,?)
        ON CONFLICT(sendId) DO UPDATE SET runId=excluded.runId,ownerId=excluded.ownerId,generation=excluded.generation,
          receipt=excluded.receipt,observationState=excluded.observationState,revision=excluded.revision,lastCheckedAt=excluded.lastCheckedAt`)
        .run(sendId,taskId,previous?.runId ?? next?.runId ?? null,
          previous?.ownerId ?? lifecycle?.ownerId ?? null,previous?.generation ?? lifecycle?.generation ?? null,
          next ? JSON.stringify(next) : previous?.receipt ? JSON.stringify(previous.receipt) : null,
          next ? next.observation : 'unavailable',revision+1,stamp);
      db.exec('COMMIT');
      return read(taskId,sendId);
    } catch (error) { db.exec('ROLLBACK'); throw error; }
  }
  return {read,binding,save:(taskId,sendId,revision,receipt)=>mutate(taskId,sendId,revision,receipt),
    unavailable:(taskId,sendId,revision)=>mutate(taskId,sendId,revision,null)};
}
