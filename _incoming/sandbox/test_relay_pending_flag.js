const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {test} = require('node:test');

const source = fs.readFileSync(path.join(__dirname, 'app.js'), 'utf8');
const helperStart = source.indexOf('function relayReloadDecision(');
const loaderStart = source.indexOf('async function loadHistoryOnce()', helperStart);
const loaderEnd = source.indexOf('function slashToken()', loaderStart);
assert.ok(helperStart >= 0 && loaderStart > helperStart && loaderEnd > loaderStart);
const context = vm.createContext({});
vm.runInContext(source.slice(helperStart, loaderStart), context);
const decide = context.relayReloadDecision;
const sentAt = Date.parse('2026-10-17T12:00:00.500Z');
const pendingValue = `relay-${sentAt}-test`;
const turn = (who, offset, extra = {}) => ({
  id: `msg-h-${who}-${offset}`,
  who,
  created_at: new Date(sentAt + offset).toISOString(),
  ...extra,
});
const completed = [turn('Eddie', 1), turn('Echo', 2)];

for (const state of ['running', 'pending', 'decision_blocked', 'waiting_for_approval', 'started']) {
  test(`in-flight ${state} recovers without warning`, () => {
    assert.equal(decide(pendingValue, {run_id: 'run-test', state}, [], null), 'recover');
    assert.equal(decide(pendingValue, {run_id: 'run-test', state}, completed, null), 'recover');
  });
}

test('completed user turn followed by Echo clears an older pending flag', () => {
  assert.equal(decide(pendingValue, {}, completed, null), 'clear');
});

test('pending flag newer than every saved turn warns', () => {
  assert.equal(decide(pendingValue, {}, [turn('Eddie', -2), turn('Echo', -1)], null), 'warn');
});

test('older Echo reply cannot complete a newer user send', () => {
  assert.equal(decide(pendingValue, {}, [turn('Eddie', -3), turn('Echo', -2), turn('Eddie', 1)], null), 'warn');
});

test('both turns must meet the timestamp and Echo must follow the user', () => {
  assert.equal(decide(pendingValue, {}, [turn('Eddie', -1), turn('Echo', 1)], null), 'warn');
  assert.equal(decide(pendingValue, {}, [turn('Echo', 1), turn('Eddie', 2)], null), 'warn');
  assert.equal(decide(pendingValue, {}, [turn('Eddie', 0), turn('Echo', 0)], null), 'clear');
});

test('proactive Echo messages and missing timestamps do not prove completion', () => {
  assert.equal(decide(pendingValue, {}, [turn('Eddie', 1), turn('Echo', 2, {proactive: true})], null), 'warn');
  assert.equal(decide(pendingValue, {}, [turn('Eddie', 1), {who: 'Echo'}], null), 'warn');
});

test('absent flag and existing run need no reload action; malformed flag stays uncertain', () => {
  assert.equal(decide(null, {}, completed, null), 'none');
  assert.equal(decide(pendingValue, {}, completed, 'run-test'), 'none');
  assert.equal(decide('invalid', {}, completed, null), 'warn');
});

async function reload(turns, decisions = {}) {
  const room = 'test-room';
  const key = 'relay-send-pending:' + room;
  const storage = new Map([[key, pendingValue]]);
  const cards = [];
  const notes = [];
  const polls = [];
  const requests = [];
  const fixture = vm.createContext({
    roomBootstrap: Promise.resolve(),
    chatRoom: () => room,
    historyRoom: '', historyGeneration: 0, chatRun: null,
    proactiveSeq: 0,
    localStorage: {
      getItem: key => storage.get(key) || null,
      removeItem: key => storage.delete(key),
    },
    sessionStorage: {setItem() {}},
    clearThreadMessages() {},
    chatCard(who, text, tag) {
      cards.push({who, text, tag});
      return {querySelector: () => ({})};
    },
    $: () => ({querySelectorAll: () => [], lastElementChild: null}),
    noteMesh: (...args) => notes.push(args),
    pollRun: (...args) => polls.push(args),
    toast: () => assert.fail('reload failed'),
    request: async url => {
      requests.push(url);
      if (url.startsWith('/api/relay/history?')) return {turns};
      if (url.startsWith('/api/relay/decisions?')) return decisions;
      assert.fail('unexpected request');
    },
  });
  vm.runInContext(source.slice(helperStart, loaderEnd), fixture);
  await fixture.loadHistoryOnce();
  assert.equal(requests.length, 2);
  assert.ok(requests.every(url => !url.includes('/api/relay/send')));
  return {storage, key, cards, notes, polls, fixture};
}

test('reload clears a completed send without warning, logging or resending', async () => {
  const result = await reload(completed);
  assert.equal(result.storage.has(result.key), false);
  assert.equal(result.cards.length, completed.length);
  assert.equal(result.notes.length, 0);
  assert.equal(result.polls.length, 0);
  assert.equal(result.fixture.chatRun, null);
});

test('reload retains uncertainty warning, flag and exact mesh note for incomplete send', async () => {
  const result = await reload([turn('Eddie', -2), turn('Echo', -1)]);
  assert.equal(result.storage.get(result.key), pendingValue);
  assert.equal(result.cards.at(-1).text, 'Earlier delivery is uncertain. Do not resend it; recovery needs checking.');
  assert.deepEqual(result.notes, [['relay', 'flag', 'delivery-uncertain', 'reload-pending-flag']]);
  assert.equal(result.fixture.chatRun, 'uncertain');
});

test('reload recovers an in-flight run without uncertainty warning', async () => {
  const result = await reload([], {run_id: 'run-test', state: 'running'});
  assert.equal(result.storage.has(result.key), false);
  assert.equal(result.cards.at(-1).text, 'Recovering your unfinished reply.');
  assert.equal(result.polls[0][0], 'run-test');
  assert.equal(result.notes.length, 0);
  assert.equal(result.fixture.chatRun, 'run-test');
});
