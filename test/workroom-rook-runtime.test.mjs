import test from 'node:test';
import assert from 'node:assert/strict';
import {DatabaseSync} from 'node:sqlite';
import {createRookStore, createRookRuntime} from '../lib/workroom-rook.mjs';
import {mkdirSync} from 'node:fs';
import {randomUUID} from 'node:crypto';
import {join} from 'node:path';
import {startApp} from '../server.mjs';

function fixture(extra = {}) {
  const db = new DatabaseSync(':memory:');
  const store = createRookStore(db);
  let at = Date.parse('2026-11-08T20:00:00Z'), sweeps = 0, verified = true;
  const timers = new Map(), sent = [];
  const options = {store, flow: {scheduledSweep: () => { sweeps++; return {status: 'empty'}; }},
    board: () => [], enabled: true, identity: {id: 'rook', approvalRef: 'fixture-only'},
    verifyIdentity: () => verified, now: () => at,
    schedule: fn => { const id = Symbol(); timers.set(id, fn); return id; }, cancel: id => timers.delete(id),
    transport: {send: async report => {sent.push(report); return {id: report.id, accepted: true};},
      lookup: async id => ({id, accepted: true})}, ...extra};
  const runtime = createRookRuntime(options);
  return {db, store, runtime, options, timers, sent, sweeps: () => sweeps,
    advance: ms => {at += ms;}, revoke: () => {verified = false;},
    close: async () => {await runtime.close(); db.close();}};
}

test('unverified and disabled runtimes install no timer and claim nothing', async () => {
  for (const extra of [{identity: null}, {enabled: false}, {transport: null}]) {
    const f = fixture(extra);
    try {f.runtime.start(); await f.runtime.tick(); assert.equal(f.timers.size, 0); assert.equal(f.sweeps(), 0);}
    finally {await f.close();}
  }
});

test('one durable scheduler owner; pause preserves reports and permits a new owner', async () => {
  const f = fixture(); const other = createRookRuntime(f.options);
  try {
    f.runtime.start(); f.runtime.start(); assert.equal(f.timers.size, 1);
    assert.equal(other.start().status, 'failing'); assert.equal(f.timers.size, 1);
    f.store.enqueue('keep', {kind: 'needs_input'}, Date.now());
    await f.runtime.pause(); assert.equal(f.timers.size, 0); assert.equal(f.store.reports().length, 1);
    assert.equal(other.start().status, 'running'); assert.equal(f.timers.size, 1);
  } finally {await other.close(); await f.close();}
});

test('overlapping ticks share a flight; pause waits and prevents post-pause reporting', async () => {
  let release; const board = new Promise(resolve => {release = resolve;});
  const f = fixture({board: () => board});
  try {
    f.runtime.start(); const first = f.runtime.tick(); assert.equal(f.runtime.tick(), first);
    await Promise.resolve(); const paused = f.runtime.pause();
    release([{id: 'a', title: 'Example', flow: {claim: {claimId: 'claim'}}}]);
    await Promise.all([first, paused]); assert.equal(f.sweeps(), 1);
    assert.equal(f.sent.length, 0); assert.equal(f.runtime.status().status, 'paused');
  } finally {await f.close();}
});

test('lost acknowledgement is looked up after restart and never resent', async () => {
  let sends = 0, lookups = 0;
  const f = fixture({board: () => [{id: 'a', title: 'Example', flow: {claim: {claimId: 'c'}}}],
    transport: {send: async () => {sends++; throw Error('secret must not escape');},
      lookup: async id => {lookups++; return {id, accepted: true};}}});
  let second;
  try {
    f.runtime.start(); assert.equal((await f.runtime.tick()).status, 'failed');
    assert.equal(f.store.reports()[0].state, 'unknown'); assert.equal(f.runtime.status().status, 'failing');
    await f.runtime.close();
    second = createRookRuntime({...f.options, transport: {
      send: async report => ({id: report.id, accepted: true}),
      lookup: f.options.transport.lookup}});
    second.start(); await second.tick(); await second.tick();
    assert.equal(sends, 1); assert.equal(lookups, 1);
    assert.equal(f.store.reports().filter(r => r.kind === 'claim_saved').length, 1);
    assert.equal(f.store.reports().filter(r => r.kind === 'watcher_recovered').length, 1);
    assert.equal(JSON.stringify(second.status()).includes('secret'), false);
  } finally {await second?.close(); await f.close();}
});

test('revocation stops sweeping; stale health is not reported as running', async () => {
  const f = fixture();
  try {
    f.runtime.start(); f.advance(120001); assert.equal(f.runtime.status().status, 'unavailable');
    f.revoke(); await f.runtime.tick(); assert.equal(f.sweeps(), 0); assert.equal(f.timers.size, 0);
    assert.equal(f.runtime.status().status, 'not_configured');
  } finally {await f.close();}
});

test('board errors remain contained and unreviewed Done never produces a success report', async () => {
  let fail = true;
  const f = fixture({board: () => {if (fail) throw Error('private detail');
    return [{id: 'a', workroom: {stage: 'done'}, progress: {decision: 'pending', revision: 1}}];}});
  try {
    f.runtime.start(); await f.runtime.tick(); assert.equal(f.runtime.status().reason, 'ROOK_BOARD_UNAVAILABLE');
    fail = false; await f.runtime.tick(); assert.equal(f.runtime.status().status, 'running');
    assert.equal(f.sent.some(r => r.kind === 'ready_for_review'), false);
  } finally {await f.close();}
});

test('actual admitted Mesh endpoint exposes fixture runtime health and shutdown releases its lease', async () => {
  const oldStandalone = process.env.MESH_STANDALONE, oldFlow = process.env.MESH_SIMPLE_FLOW;
  process.env.MESH_STANDALONE = '1'; process.env.MESH_SIMPLE_FLOW = '1';
  const directory = 'data/rook-runtime-' + randomUUID();
  mkdirSync(directory, {recursive: true});
  let app;
  try {
    app = await startApp({dataDir: directory, rookRuntimeTestOptions: {
      source: 'disposable_fixture', enabled: true, identity: {id: 'rook', approvalRef: 'synthetic'},
      verifyIdentity: () => true, schedule: () => 1, cancel: () => {},
      transport: {send: async r => ({id: r.id, accepted: true}), lookup: async id => ({id, accepted: true})}}});
    assert.equal((await fetch(app.url + '/api/workroom/rook')).status, 401);
    const boot = await fetch(app.url + '/api/trial-session/bootstrap', {method: 'POST',
      headers: {Origin: app.url, 'Content-Type': 'application/json'}, body: '{}'});
    assert.equal(boot.status, 201); const body = await boot.json();
    const headers = {Origin: app.url, Cookie: boot.headers.get('set-cookie').split(';')[0], 'X-Trial-CSRF': body.csrfToken};
    await app.rookRuntime.tick();
    const response = await fetch(app.url + '/api/workroom/rook', {headers});
    assert.equal(response.status, 200); const status = await response.json();
    assert.equal(status.connection.status, 'running'); assert.equal(status.sweep.schedulerEnabled, true);
    assert.equal(status.connection.writerClearance, false); assert.equal(status.connection.source, 'disposable_fixture');
    await app.close(); app = null;
    const db = new DatabaseSync(join(directory, 'tasks.sqlite'), {readOnly: true});
    try {assert.equal(db.prepare('SELECT ownerId FROM workroom_rook_runtime').get().ownerId, '');}
    finally {db.close();}
  } finally {
    await app?.close();
    if (oldStandalone === undefined) delete process.env.MESH_STANDALONE; else process.env.MESH_STANDALONE = oldStandalone;
    if (oldFlow === undefined) delete process.env.MESH_SIMPLE_FLOW; else process.env.MESH_SIMPLE_FLOW = oldFlow;
  }
});
