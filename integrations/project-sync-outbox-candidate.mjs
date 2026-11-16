// Disconnected candidate. No imports into Mesh runtime, listener or scheduler.
import { createHash, randomUUID } from 'node:crypto';

const schema = 'onoes-mind-project-event/v1';
const receiptSchema = 'onoes-mind-project-receipt/v1';
const absenceSchema = 'onoes-mind-project-absence/v1';
const principal = 'mesh-project-sync';
const scope = 'project/onoes-mind/shared';
const id = value => typeof value === 'string' && /^[A-Za-z0-9_-]{1,100}$/.test(value);
const exact = (object, keys) => object?.constructor === Object &&
  Object.keys(object).sort().join(',') === [...keys].sort().join(',');
const require = (condition, message) => { if (!condition) throw new Error(message); };
const validText = (value, limit) => typeof value === 'string' &&
  [...value].length <= limit && !/[\u0000\uD800-\uDFFF]/u.test(value);

export function canonicalProjectEvent(value) {
  if (Array.isArray(value)) return `[${value.map(canonicalProjectEvent).join(',')}]`;
  if (value?.constructor === Object) return `{${Object.keys(value).sort()
    .map(k => `${JSON.stringify(k)}:${canonicalProjectEvent(value[k])}`).join(',')}}`;
  require(value === null || typeof value === 'string' || typeof value === 'boolean' ||
    Number.isSafeInteger(value), 'Unsupported canonical value.');
  return JSON.stringify(value);
}

export function validateProjectEvent(event) {
  require(exact(event, ['schema','eventId','cardId','projectId','sequence','kind',
    'revisions','snapshot','evidence']) && event.schema === schema, 'Invalid project event.');
  require(['eventId','cardId','projectId'].every(k => id(event[k])) &&
    Number.isSafeInteger(event.sequence) && event.sequence > 0, 'Invalid event identity.');
  require(['created','assigned','stage_changed','progress','blocked','completed'].includes(event.kind),
    'Invalid event kind.');
  require(exact(event.revisions, ['task','brief','progress']) &&
    Object.values(event.revisions).every(v => Number.isSafeInteger(v) && v >= 0) &&
    event.revisions.task > 0, 'Invalid source revisions.');
  const limits = {title:300, goal:2000, owner:100, stage:20, result:4000, blocker:1000};
  require(exact(event.snapshot, Object.keys(limits)) &&
    Object.entries(limits).every(([k,n]) => validText(event.snapshot[k],n)) &&
    event.snapshot.title.trim() && ['backlog','ready','working','needs_you','done'].includes(event.snapshot.stage),
    'Invalid shared snapshot.');
  require(event.kind !== 'completed' || event.snapshot.stage === 'done', 'Invalid completion.');
  require(Array.isArray(event.evidence) && event.evidence.length <= 12 && event.evidence.every(ref =>
    exact(ref, ['type','ref','content_hash']) && [['type',50],['ref',500],['content_hash',100]].every(
      ([k,n]) => validText(ref[k],n) && ref[k].trim())), 'Invalid evidence.');
  const payload = canonicalProjectEvent(event);
  require(Buffer.byteLength(payload) <= 16384, 'Event too large.');
  return {payload, hash:createHash('sha256').update(payload).digest('hex')};
}

export function initializeProjectOutbox(db) {
  require(!db.isTransaction, 'Initialize outside card transactions.');
  db.exec('BEGIN IMMEDIATE');
  try {
    db.exec(`CREATE TABLE mind_project_links(
      cardId TEXT PRIMARY KEY REFERENCES tasks(id), projectId TEXT NOT NULL,
      storeId TEXT NOT NULL, approvalRef TEXT NOT NULL,
      active INTEGER NOT NULL CHECK(active IN (0,1)), sequence INTEGER NOT NULL DEFAULT 0);
      CREATE TABLE mind_project_outbox(
      eventId TEXT PRIMARY KEY, cardId TEXT NOT NULL REFERENCES mind_project_links(cardId),
      sequence INTEGER NOT NULL, payload TEXT NOT NULL, payloadHash TEXT NOT NULL,
      state TEXT NOT NULL CHECK(state IN ('pending','uncertain','saved','held')),
      reason TEXT NOT NULL DEFAULT '', receipt TEXT,
      UNIQUE(cardId,sequence));`);
    db.exec('COMMIT');
  } catch (error) { db.exec('ROLLBACK'); throw error; }
}

export class ProjectOutboxCandidate {
  constructor(db, {storeId, readSnapshot}) {
    require(id(storeId) && typeof readSnapshot === 'function', 'Explicit store and server snapshot reader required.');
    this.db = db; this.storeId = storeId; this.readSnapshot = readSnapshot;
    this.inFlight = false;
    require(!db.prepare('SELECT 1 FROM mind_project_links WHERE storeId<>?').get(storeId),
      'Outbox store binding mismatch.');
  }

  linkCard(cardId, projectId, approvalRef) {
    require(this.db.isTransaction, 'Link within the approved card transaction.');
    require(id(cardId) && id(projectId) && validText(approvalRef,300) && approvalRef.trim(),
      'Explicit approved project link required.');
    this.db.prepare('INSERT INTO mind_project_links(cardId,projectId,storeId,approvalRef,active) VALUES(?,?,?,?,1)')
      .run(cardId,projectId,this.storeId,approvalRef);
  }

  capture(cardId, kind) {
    require(this.db.isTransaction, 'Capture must share the card mutation transaction.');
    const link = this.db.prepare('SELECT * FROM mind_project_links WHERE cardId=? AND active=1 AND storeId=?')
      .get(cardId,this.storeId);
    require(link, 'Card is not approved for sharing.');
    const snapshot = this.readSnapshot(cardId);
    require(this.db.isTransaction, 'Snapshot reader ended the card transaction.');
    require(exact(snapshot,['revisions','snapshot','evidence']), 'Invalid server snapshot.');
    const event = {schema,eventId:randomUUID(),cardId,projectId:link.projectId,
      sequence:link.sequence+1,kind,...snapshot};
    const {payload,hash} = validateProjectEvent(event);
    require(link.sequence === 0 ? kind === 'created' : kind !== 'created',
      'Initial snapshot must precede later changes.');
    if (link.sequence > 0) {
      const prior = JSON.parse(this.db.prepare('SELECT payload FROM mind_project_outbox WHERE cardId=? AND sequence=?')
        .get(cardId,link.sequence).payload).revisions;
      require(Object.keys(prior).every(k => event.revisions[k] >= prior[k]) &&
        Object.keys(prior).some(k => event.revisions[k] > prior[k]), 'Source revision did not advance.');
    }
    this.db.prepare('INSERT INTO mind_project_outbox(eventId,cardId,sequence,payload,payloadHash,state) VALUES(?,?,?,?,?,\'pending\')')
      .run(event.eventId,cardId,event.sequence,payload,hash);
    this.db.prepare('UPDATE mind_project_links SET sequence=? WHERE cardId=?').run(event.sequence,cardId);
    return event.eventId;
  }

  withdraw(cardId) {
    require(this.db.isTransaction, 'Withdraw within an owner transaction.');
    this.db.prepare('UPDATE mind_project_links SET active=0 WHERE cardId=?').run(cardId);
    this.db.prepare("UPDATE mind_project_outbox SET state='held',reason='sharing_withdrawn' WHERE cardId=? AND state<>'saved'").run(cardId);
  }

  status(cardId) {
    return this.db.prepare('SELECT eventId,sequence,state,reason FROM mind_project_outbox WHERE cardId=? ORDER BY sequence').all(cardId);
  }

  _current(row) {
    return this.db.prepare(`SELECT 1 FROM mind_project_outbox o JOIN mind_project_links l USING(cardId)
      WHERE o.eventId=? AND o.payloadHash=? AND o.state='uncertain' AND l.active=1 AND l.storeId=?`)
      .get(row.eventId,row.payloadHash,this.storeId);
  }

  _observed(row) {
    return {state:this.db.prepare('SELECT state FROM mind_project_outbox WHERE eventId=?')
      .get(row.eventId)?.state ?? 'held',eventId:row.eventId};
  }

  _absence(value, event) {
    return exact(value,['schema','storeId','principal','scope','projectId','eventId','found']) &&
      value.schema === absenceSchema && value.storeId === this.storeId &&
      value.principal === principal && value.scope === scope &&
      value.projectId === event.projectId && value.eventId === event.eventId && value.found === false;
  }

  _receipt(value, event, hash) {
    return exact(value,['schema','storeId','scope','principal','eventId','cardId','projectId',
      'sequence','payloadHash','receiptId','durable','recordState']) &&
      value.schema === receiptSchema && value.storeId === this.storeId &&
      value.principal === principal && value.scope === scope && value.eventId === event.eventId &&
      value.cardId === event.cardId && value.projectId === event.projectId &&
      value.sequence === event.sequence && value.payloadHash === hash && id(value.receiptId) &&
      value.durable === true && ['active','superseded','purged','project_deleted'].includes(value.recordState);
  }

  async drainOne(transport) {
    require(!this.db.isTransaction, 'Never await transport inside a card transaction.');
    require(transport && typeof transport.lookup === 'function' && typeof transport.submit === 'function',
      'Explicit receipt lookup and submit transport required.');
    if (this.inFlight) return {state:'busy'};
    this.inFlight = true;
    let row;
    try {
      // A held earlier event blocks the rest of that card; other cards may progress.
      this.db.exec('BEGIN IMMEDIATE');
      try {
        row = this.db.prepare(`SELECT o.*,l.projectId AS linkedProject FROM mind_project_outbox o JOIN mind_project_links l USING(cardId)
          WHERE o.state IN ('pending','uncertain') AND l.active=1 AND l.storeId=? AND NOT EXISTS(
            SELECT 1 FROM mind_project_outbox prior WHERE prior.cardId=o.cardId AND prior.sequence<o.sequence AND prior.state<>'saved')
          ORDER BY o.rowid LIMIT 1`).get(this.storeId);
        if (row) this.db.prepare("UPDATE mind_project_outbox SET state='uncertain',reason='awaiting_exact_receipt' WHERE eventId=?").run(row.eventId);
        this.db.exec('COMMIT');
      } catch (error) {this.db.exec('ROLLBACK'); throw error;}
      if (!row) return {state:'idle'};
      let event;
      try {
        event = JSON.parse(row.payload);
        require(validateProjectEvent(event).hash === row.payloadHash &&
          event.eventId === row.eventId && event.cardId === row.cardId && event.projectId === row.linkedProject &&
          event.sequence === row.sequence, 'Local event binding changed.');
      } catch {
        this.db.prepare("UPDATE mind_project_outbox SET state='held',reason='invalid_local_event' WHERE eventId=? AND state='uncertain'").run(row.eventId);
        return {state:'held',eventId:row.eventId};
      }
      let receipt = await transport.lookup({projectId:event.projectId,eventId:event.eventId});
      if (!this._current(row)) return this._observed(row);
      if (this._absence(receipt,event)) {
        receipt = await transport.submit(event);
      }
      if (!this._receipt(receipt,event,row.payloadHash)) {
        this.db.prepare("UPDATE mind_project_outbox SET state='held',reason='invalid_receipt' WHERE eventId=? AND state='uncertain'").run(row.eventId);
        return {state:'held',eventId:row.eventId};
      }
      // Withdrawn sharing never turns into a success indication after an await.
      if (!this._current(row)) return this._observed(row);
      const removed = ['purged','project_deleted'].includes(receipt.recordState);
      const state = removed ? 'held' : 'saved';
      this.db.prepare('UPDATE mind_project_outbox SET state=?,reason=?,receipt=? WHERE eventId=? AND state=\'uncertain\'')
        .run(state,removed?'record_removed':'receipt_confirmed',JSON.stringify(receipt),row.eventId);
      return {state,eventId:row.eventId};
    } catch(error) {
      // Unknown delivery remains persisted for exact-ID lookup, with no raw error/data log.
      if(row&&(error?.projectSyncHeld===true||error?.projectSyncLocalBinding===true))this.db.prepare("UPDATE mind_project_outbox SET state='held',reason=? WHERE eventId=? AND state='uncertain'")
        .run(error?.projectSyncLocalBinding===true?'local_binding_changed':'remote_refused',row.eventId);
      return row?this._observed(row):{state:'unavailable'};
    } finally {this.inFlight=false;}
  }
}
