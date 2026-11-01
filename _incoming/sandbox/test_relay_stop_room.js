const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {test} = require('node:test');

const source = fs.readFileSync(path.join(__dirname, 'app.js'), 'utf8');
function block(start, end) {
  const first = source.indexOf(start);
  const last = source.indexOf(end, first);
  assert.ok(first >= 0 && last > first, `source block: ${start}`);
  return source.slice(first, last);
}
const code = [
  block('function clearThreadMessages()', 'function noteMesh('),
  block('async function loadHistory()', 'function slashToken()'),
  block('function stopDecisionPoll()', 'async function resolveDecision('),
  block('async function pollRun(', 'const SLASH ='),
  block('async function runSlash(', 'async function submitDraft()'),
].join('\n');
const warning = 'Earlier delivery is uncertain. Do not resend it; recovery needs checking.';
const roomA = 'room-a';
const roomB = 'room-b';
const key = room => 'relay-send-pending:' + room;
const savedTurns = {
  [roomA]: [{id: 'a-user', who: 'Eddie', text: 'First room question.'},
    {id: 'a-echo', who: 'Echo', text: 'First room answer.'}],
  [roomB]: [{id: 'b-user', who: 'Eddie', text: 'Second room question.'},
    {id: 'b-echo', who: 'Echo', text: 'Second room answer.'}],
};
function deferred() {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return {promise, resolve, reject};
}
function fixture({storage = new Map(), decisions = {}, onStop, onRun, onRoom} = {}) {
  const nodes = new Map();
  const cards = [];
  const requests = [];
  const toasts = [];
  const notes = [];
  const events = [];
  const sessions = new Map();
  const histories = JSON.parse(JSON.stringify(savedTurns));
  class Element {
    constructor() { this.children = []; this.style = {}; this.handlers = {}; }
    append(...children) { this.children.push(...children); }
    prepend(...children) { this.children.unshift(...children); }
    replaceChildren() { this.children = []; }
    addEventListener(name, handler) { this.handlers[name] = handler; }
    set id(value) { this._id = value; nodes.set(value, this); }
    get id() { return this._id; }
  }
  for (const id of ['slash-menu', 'draft', 'page-settings', 'thread']) {
    const element = new Element();
    element.id = id;
  }
  nodes.get('thread').querySelectorAll = () => [];
  Object.defineProperty(nodes.get('thread'), 'lastElementChild', {get: () => cards.at(-1)});
  const context = vm.createContext({
    roomBootstrap: Promise.resolve(), selectedRelayRoom: roomA,
    historyRoom: '', historyGeneration: 0, historyLoading: null, historyLoadingRoom: '',
    chatRun: null, chatMark: null, stoppedRun: null, runWatchGeneration: 0,
    decisionTimer: 0, decisionSequence: 0, proactiveSeq: 0,
    chatRoom: () => context.selectedRelayRoom,
    localStorage: {
      getItem: k => storage.get(k) || null,
      removeItem: k => storage.delete(k),
    },
    sessionStorage: {setItem: (k, v) => sessions.set(k, v), removeItem: k => sessions.delete(k)},
    $: id => nodes.get(id),
    document: {
      createElement: () => new Element(),
      querySelectorAll: selector => {
        assert.equal(selector, '#thread article.msg');
        return cards.slice();
      },
      dispatchEvent: event => events.push(event.type),
    },
    Event: class { constructor(type) { this.type = type; } },
    chatCard(who, text, tag) {
      const body = {textContent: text};
      const card = {
        who, body, id: '',
        querySelector: selector => selector === '.tag' ? card.mark : selector === 'p' ? body : null,
        remove: () => cards.splice(cards.indexOf(card), 1),
        scrollIntoView() {},
      };
      card.mark = {textContent: tag, closest: selector => {
        assert.equal(selector, 'article.msg.echo');
        return who === 'Echo' ? card : null;
      }};
      cards.push(card);
      return card;
    },
    clearReply() {}, clearPick() {}, fitDraft() {}, hideTyping() {}, showTyping() {}, renderDecision() {},
    appendPhoto() { assert.fail('no photos in fixture'); },
    noteMesh: (...args) => notes.push(args),
    toast: text => toasts.push(text),
    setTimeout: callback => { callback(); return 0; }, clearTimeout() {},
    request: async (url, body) => {
      requests.push({url, body: body && JSON.parse(JSON.stringify(body))});
      assert.notEqual(url, '/api/relay/send', 'stop and switch must never send');
      if (url === '/api/relay/stop') return onStop ? onStop(body) : {};
      if (url === '/api/relay/room') {
        if (onRoom) return onRoom(body);
        return {session_id: body.session_id, rooms: Object.keys(histories).map(session_id => ({session_id}))};
      }
      if (url.startsWith('/api/relay/history?')) {
        const room = new URL(url, 'http://fixture.invalid').searchParams.get('session');
        assert.ok(histories[room]);
        return {turns: JSON.parse(JSON.stringify(histories[room]))};
      }
      if (url.startsWith('/api/relay/decisions?')) {
        const room = new URL(url, 'http://fixture.invalid').searchParams.get('session');
        return decisions[room] || {};
      }
      if (url.startsWith('/api/relay/run?')) {
        assert.ok(onRun, 'unexpected run poll');
        return onRun();
      }
      assert.fail(`unexpected request: ${url}`);
    },
  });
  vm.runInContext(code, context);
  context.paintRooms(Object.keys(histories).map(session_id => ({session_id})));
  async function switchRoom(room) {
    const select = nodes.get('relay-room-select');
    select.value = room;
    await select.handlers.change();
  }
  function markRun(runId, who = 'Eddie', text = 'Question.') {
    context.chatRun = runId;
    context.chatMark = context.chatCard(who, text, 'delivery uncertain').querySelector('.tag');
    return context.chatMark;
  }
  return {context, storage, sessions, cards, requests, toasts, notes, events, histories, nodes, switchRoom, markRun};
}
function assertNoWarning(f) {
  assert.ok(f.cards.every(card => card.body.textContent !== warning));
  assert.ok(f.cards.every(card => card.mark.textContent !== 'delivery uncertain'));
  assert.equal(f.notes.length, 0);
}

test('successful real stop clears only its room flag; fresh reload never warns or resends', async () => {
  const storage = new Map([[key(roomA), 'pending-a'], [key(roomB), 'pending-b']]);
  const f = fixture({storage});
  const mark = f.markRun('run-one');
  f.sessions.set('relay-run', 'run-one');
  await f.context.runSlash('stop');
  assert.deepEqual(f.requests, [{url: '/api/relay/stop', body: {run_id: 'run-one'}}]);
  assert.equal(storage.has(key(roomA)), false);
  assert.equal(storage.get(key(roomB)), 'pending-b');
  assert.equal(f.sessions.has('relay-run'), false);
  assert.equal(f.context.chatRun, null);
  assert.equal(mark.textContent, 'stopped');
  assert.deepEqual(f.toasts, ['Stopped.']);
  const reloaded = fixture({storage, decisions: {[roomA]: {run_id: 'run-one', state: 'cancelled'}}});
  await reloaded.context.loadHistory();
  assertNoWarning(reloaded);
  assert.equal(reloaded.context.chatRun, null);
  assert.deepEqual(reloaded.cards.map(card => card.id), ['a-user', 'a-echo']);
});

test('reload with no in-flight run or pending flag paints only saved turns', async () => {
  const f = fixture();
  await f.context.loadHistory();
  assertNoWarning(f);
  assert.equal(f.context.chatRun, null);
  assert.equal(f.cards.length, 2);
});

test('stop clears the painted reload warning and pending flag without a stop POST', async () => {
  const f = fixture({storage: new Map([[key(roomA), 'unknown-send']])});
  await f.context.loadHistory();
  assert.equal(f.cards.at(-1).body.textContent, warning);
  assert.equal(f.context.chatRun, 'uncertain');
  const mark = f.context.chatMark;
  f.requests.length = 0;
  await f.context.runSlash('stop');
  assert.deepEqual(f.requests, []);
  assert.equal(f.storage.has(key(roomA)), false);
  assert.equal(f.context.chatRun, null);
  assert.equal(f.context.stoppedRun, null);
  assert.equal(mark.textContent, 'stopped');
  assert.equal(f.cards.at(-1).body.textContent, 'Stopped.');
  assert.deepEqual(f.toasts, ['Stopped.']);
  const reloaded = fixture({storage: f.storage});
  await reloaded.context.loadHistory();
  assertNoWarning(reloaded);
});

test('stop from send uncertainty preserves the user message and makes no request', async () => {
  const f = fixture({storage: new Map([[key(roomA), 'unknown-send']])});
  const mark = f.markRun('uncertain');
  await f.context.runSlash('stop');
  assert.deepEqual(f.requests, []);
  assert.equal(f.cards[0].body.textContent, 'Question.');
  assert.equal(mark.textContent, 'stopped');
  assert.equal(f.storage.has(key(roomA)), false);
  assert.equal(f.context.chatRun, null);
});

test('uncertain permits switching; switching back restores saved turns and unresolved warning', async () => {
  const f = fixture({storage: new Map([[key(roomA), 'unknown-send']])});
  await f.context.loadHistory();
  assert.equal(f.context.chatRun, 'uncertain');
  f.requests.length = 0;
  await f.switchRoom(roomB);
  assert.deepEqual(f.requests, [
    {url: '/api/relay/room', body: {session_id: roomB}},
    {url: '/api/relay/history?session=' + roomB, body: undefined},
    {url: '/api/relay/decisions?session=' + roomB, body: undefined},
  ]);
  assert.equal(f.context.chatRun, null);
  assert.equal(f.context.chatMark, null);
  assert.deepEqual(f.cards.map(card => card.id), ['b-user', 'b-echo']);
  await f.switchRoom(roomA);
  assert.deepEqual(f.cards.slice(0, 2).map(card => card.body.textContent), savedTurns[roomA].map(turn => turn.text));
  assert.equal(f.cards.at(-1).body.textContent, warning);
  assert.equal(f.context.chatRun, 'uncertain');
  assert.deepEqual(f.histories, savedTurns);
  assert.deepEqual(f.toasts, []);
  assert.deepEqual(f.events, ['mesh-room-restored', 'mesh-room-restored']);
});

test('idle room round trip restores both histories without mutation or sending', async () => {
  const f = fixture();
  await f.context.loadHistory();
  await f.switchRoom(roomB);
  assert.deepEqual(f.cards.map(card => card.id), ['b-user', 'b-echo']);
  await f.switchRoom(roomA);
  assert.deepEqual(f.cards.map(card => card.id), ['a-user', 'a-echo']);
  assert.deepEqual(f.histories, savedTurns);
  assert.equal(f.sessions.get('relay-session'), roomA);
  assert.deepEqual(f.requests.filter(r => r.body).map(r => r.url), ['/api/relay/room', '/api/relay/room']);
});

for (const runId of ['run-one', 'pending']) {
  test(`room switch refuses ${runId} with the existing toast`, async () => {
    const f = fixture();
    f.markRun(runId);
    await f.switchRoom(roomB);
    assert.deepEqual(f.requests, []);
    assert.equal(f.context.selectedRelayRoom, roomA);
    assert.equal(f.nodes.get('relay-room-select').value, roomA);
    assert.deepEqual(f.toasts, ['Stop or finish this reply before switching rooms.']);
  });
}

test('failed room switch keeps uncertainty and pending flag in the original room', async () => {
  const f = fixture({storage: new Map([[key(roomA), 'unknown-send']]),
    onRoom: async () => { throw new Error('Room unavailable.'); }});
  const mark = f.markRun('uncertain');
  await f.switchRoom(roomB);
  assert.equal(f.context.selectedRelayRoom, roomA);
  assert.equal(f.context.chatRun, 'uncertain');
  assert.equal(f.context.chatMark, mark);
  assert.equal(f.storage.get(key(roomA)), 'unknown-send');
  assert.equal(f.nodes.get('relay-room-select').value, roomA);
  assert.deepEqual(f.toasts, ['Room unavailable.']);
});

for (const watcher of ['pollRun', 'pollDecision']) {
  for (const pollFinishesFirst of [true, false]) {
    test(`real stop stays stopped with ${watcher} finishing ${pollFinishesFirst ? 'before' : 'after'} stop response`, async () => {
      const stop = deferred();
      const run = deferred();
      const f = fixture({storage: new Map([[key(roomA), 'unknown-send']]),
        onStop: () => stop.promise, onRun: () => run.promise});
      const mark = f.markRun('run-one');
      const polling = f.context[watcher]('run-one', mark);
      // Let pollRun pass its timer and enter the outstanding request.
      await Promise.resolve();
      assert.ok(f.requests.some(r => r.url.startsWith('/api/relay/run?')));
      const stopping = f.context.runSlash('stop');
      assert.deepEqual(f.requests.at(-1), {url: '/api/relay/stop', body: {run_id: 'run-one'}});
      assert.equal(f.storage.has(key(roomA)), true, 'retain pending until stop succeeds');
      if (pollFinishesFirst) {
        run.resolve({done: true, status: 'failed', error: 'Cancelled worker.'});
        await polling;
        assert.equal(mark.textContent, 'stopped');
      }
      stop.resolve({});
      await stopping;
      if (!pollFinishesFirst) {
        run.resolve({done: true, status: 'failed', error: 'Cancelled worker.'});
        await polling;
      }
      assert.equal(mark.textContent, 'stopped');
      assert.equal(f.context.chatRun, null);
      assert.equal(f.storage.has(key(roomA)), false);
      assert.deepEqual(f.toasts, ['Stopped.']);
    });
  }
}

test('failed real stop retains pending flag and run for recovery', async () => {
  const f = fixture({storage: new Map([[key(roomA), 'unknown-send']]),
    onStop: async () => { throw new Error('Stop unavailable.'); }});
  f.markRun('run-one');
  await f.context.runSlash('stop');
  assert.equal(f.storage.get(key(roomA)), 'unknown-send');
  assert.equal(f.context.chatRun, 'run-one');
  assert.equal(f.context.stoppedRun, null);
  assert.deepEqual(f.toasts, ['Stop unavailable.']);
});
