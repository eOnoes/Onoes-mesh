const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {test} = require('node:test');

const source = fs.readFileSync(path.join(__dirname, 'app.js'), 'utf8');
const html = fs.readFileSync(path.join(__dirname, 'index.html'), 'utf8');
function block(start, end) {
  const first = source.indexOf(start);
  const last = source.indexOf(end, first);
  assert.ok(first >= 0 && last > first, `source block: ${start}`);
  return source.slice(first, last);
}

// Parse the real body markup into a small DOM fixture; no server or browser process.
class Element {
  constructor(tag, attrs = '') {
    this.tagName = tag.toUpperCase();
    this.children = []; this.style = {}; this.handlers = {}; this.dataset = {};
    this.id = /\bid="([^"]+)"/.exec(attrs)?.[1] || '';
    this.className = /\bclass="([^"]+)"/.exec(attrs)?.[1] || '';
    this.hidden = /\bhidden\b/.test(attrs);
    this.clientWidth = 320; this.clientHeight = 240;
  }
  append(...nodes) { for (const node of nodes) { node.parent = this; this.children.push(node); } }
  prepend(...nodes) { this.append(...nodes); this.children.unshift(...this.children.splice(-nodes.length)); }
  replaceChildren(...nodes) { this.children = []; this.append(...nodes); }
  remove() { this.parent.children.splice(this.parent.children.indexOf(this), 1); this.parent = null; }
  addEventListener(name, handler) { this.handlers[name] = handler; }
  setAttribute(name, value) { this[name] = value; }
  getAttribute(name) { return this[name] ?? null; }
  matches(selector) {
    const id = /#([\w-]+)/.exec(selector)?.[1];
    const tag = /^[\w-]+/.exec(selector)?.[0];
    const classes = [...selector.matchAll(/\.([\w-]+)/g)].map(match => match[1]);
    return (!id || this.id === id) && (!tag || this.tagName === tag.toUpperCase()) &&
      classes.every(name => this.className.split(/\s+/).includes(name)) &&
      (!selector.includes('[data-proactive-seq]') || this.dataset.proactiveSeq !== undefined);
  }
  querySelectorAll(selector) {
    const selectors = selector.split(',').map(part => part.trim().split(/\s+/));
    const found = [];
    const visit = node => {
      for (const parts of selectors) {
        if (!node.matches(parts.at(-1))) continue;
        let ancestor = node.parent;
        let index = parts.length - 2;
        while (ancestor && index >= 0) { if (ancestor.matches(parts[index])) index--; ancestor = ancestor.parent; }
        if (index < 0) { found.push(node); break; }
      }
      node.children.forEach(visit);
    };
    this.children.forEach(visit);
    return found;
  }
  querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
  closest(selector) { return this.matches(selector) ? this : this.parent?.closest(selector) || null; }
  cloneNode() {
    const clone = new Element(this.tagName);
    clone.src = this.src;
    return clone;
  }
  scrollIntoView() {}
  get firstChild() { return this.children[0]; }
  get lastElementChild() { return this.children.at(-1); }
  click() {
    let stopped = false;
    this.handlers.click({currentTarget: this, stopPropagation() { stopped = true; }});
    assert.equal(stopped, true, 'attachment click must not bubble to pane dismissal');
  }
}
function parseBody() {
  const root = new Element('document');
  const stack = [root];
  const body = html.slice(html.indexOf('<body'), html.indexOf('<script'));
  const voidTags = new Set(['input', 'img', 'br', 'hr', 'meta', 'link']);
  for (const match of body.matchAll(/<(\/)?([\w-]+)\b([^>]*)>/g)) {
    const [, closing, tag, attrs] = match;
    if (closing) { assert.equal(stack.pop().tagName, tag.toUpperCase()); continue; }
    const node = new Element(tag, attrs);
    stack.at(-1).append(node);
    if (!voidTags.has(tag) && !attrs.endsWith('/')) stack.push(node);
  }
  return root;
}
const savedRoom = 'relay-eddie-echo-chat';
const savedTurns = [{id: 'saved-user', who: 'Eddie', text: 'Saved question.'},
  {id: 'saved-echo', who: 'Echo', text: 'Saved answer.'}];
function fixture(room = savedRoom) {
  const document = parseBody();
  document.createElement = tag => new Element(tag);
  document.dispatchEvent = () => {};
  const $ = id => document.querySelector('#' + id);
  const histories = {[savedRoom]: savedTurns, 'empty-room': [], 'new-room': []};
  const requests = [];
  const context = vm.createContext({
    document, $, Event: class {}, addEventListener() {},
    roomBootstrap: Promise.resolve(), selectedRelayRoom: room,
    historyRoom: '', historyGeneration: 0, historyLoading: null, historyLoadingRoom: '',
    chatRun: null, chatMark: null, runWatchGeneration: 0, proactiveSeq: 0,
    chatRoom: () => context.selectedRelayRoom,
    localStorage: {getItem: () => null}, sessionStorage: {setItem() {}, removeItem() {}},
    clearReply() {}, clearPick() {}, fitDraft() {}, fitReader() {}, placeReader() {}, placeSlot() {},
    toast: message => { assert.ok(!/Error|undefined|not a function/.test(message), message); },
    chatCard(who, text) {
      const card = new Element('article', 'class="msg"');
      card.who = who; card.textContent = text; $('thread').append(card); return card;
    },
    request: async (url, body) => {
      requests.push({url, body});
      if (url === '/api/relay/new') return {session_id: 'new-room', rooms: rooms()};
      if (url === '/api/relay/room') return {session_id: body.session_id, rooms: rooms()};
      if (url.startsWith('/api/relay/history?')) {
        const session = new URL(url, 'http://fixture.invalid').searchParams.get('session');
        assert.ok(Object.hasOwn(histories, session));
        return {turns: histories[session]};
      }
      if (url.startsWith('/api/relay/decisions?')) return {};
      assert.fail(`unexpected request: ${url}`);
    },
  });
  function rooms() { return Object.keys(histories).map(session_id => ({session_id})); }
  vm.runInContext([
    block('function clearThreadMessages()', 'function noteMesh('),
    block('async function loadHistory()', 'function slashToken()'),
    block('async function runSlash(', 'async function submitDraft()'),
    block('function paintDoc(', 'function placeSlot('),
    block("let openText = '';", 'let readerScale = 1;'),
    block('let readerScale = 1;', 'function pinKeyboard()'),
    block('let photoScale = 1;', 'async function copyDoc()'),
    block('async function copyDoc()', 'loadGoal();'),
    block('function paperButton(', 'let stagedPhoto ='),
    block('function appendPhoto(', 'const photoInput ='),
  ].join('\n'), context);
  context.paintRooms(rooms());
  const cards = () => document.querySelectorAll('#thread article.msg');
  async function switchRoom(session) {
    const select = $('relay-room-select'); select.value = session;
    await select.handlers.change();
  }
  return {context, document, $, cards, switchRoom, requests};
}
function assertNoSampleDoors(f) {
  assert.equal(f.document.querySelector('.relay-doors'), null);
  for (const id of ['open-doc', 'open-shot']) assert.equal(f.$(id), null, `${id} is removed`);
  assert.ok(f.$('staged-doc'), 'real staged paper path remains');
  assert.ok(f.$('reader'), 'reader remains');
  assert.ok(f.$('photo'), 'photo pane remains');
}

test('initial empty room has no message cards or sample doors', async () => {
  const f = fixture('empty-room');
  assert.equal(f.cards().length, 0);
  await f.context.loadHistory();
  assert.equal(f.cards().length, 0);
  assertNoSampleDoors(f);
  assert.equal(f.$('thread').children.length, 0);
  assert.equal(f.$('staged-doc').hidden, true);
  assert.equal(f.$('reader').hidden, true);
  assert.equal(f.$('photo').hidden, true);
  assert.doesNotMatch(html, /prompt\.txt|open-doc|open-shot|relay-doors/);
  assert.doesNotMatch(source, /prompt\.txt|open-doc|open-shot|SAMPLE_DOC|sample\. not a real file/);
  assert.match(html, /app\.js\?v=relay-no-sample1/);
});

test('/new empties the thread; room switching restores only saved turns', async () => {
  const f = fixture();
  await f.context.loadHistory();
  assert.deepEqual(f.cards().map(card => card.id), savedTurns.map(turn => turn.id));
  await f.context.runSlash('new');
  await f.context.loadHistory();
  assert.equal(f.context.selectedRelayRoom, 'new-room');
  assert.equal(f.cards().length, 0);
  assertNoSampleDoors(f);
  await f.switchRoom(savedRoom);
  assert.deepEqual(f.cards().map(card => [card.id, card.who, card.textContent]),
    savedTurns.map(turn => [turn.id, turn.who, turn.text]));
  await f.switchRoom('empty-room');
  assert.equal(f.cards().length, 0);
  assertNoSampleDoors(f);
  assert.ok(f.requests.every(({url}) => url !== '/api/relay/send'));
});

test('clearing removes every message card without leaving sample doors', async () => {
  const f = fixture();
  await f.context.loadHistory();
  f.context.clearThreadMessages();
  assert.equal(f.cards().length, 0);
  assertNoSampleDoors(f);
});

test('pasted paper and real photo cards still open their own panes', () => {
  const f = fixture('empty-room');
  const paper = 'Actual pasted document.\n'.repeat(60).trimEnd();
  let prevented = false;
  f.$('draft').handlers.paste({
    clipboardData: {getData: () => paper},
    preventDefault() { prevented = true; },
  });
  assert.equal(prevented, true);
  assert.equal(f.$('staged-doc').hidden, false);
  f.$('staged-doc').click();
  assert.equal(f.$('reader').hidden, false);
  assert.equal(f.$('reader-name').textContent, 'paper');
  assert.equal(f.$('reader-stage').innerHTML.replace(/<[^>]+>/g, ''), paper);
  assert.equal(f.cards().length, 0, 'staging and reading paper never creates messages');

  const card = f.context.chatCard('Eddie', 'Actual photo.');
  f.context.appendPhoto(card, 'real-photo-id', 'empty-room');
  const thumbnail = card.querySelector('button.shot');
  assert.ok(thumbnail);
  thumbnail.click();
  assert.equal(f.$('reader').hidden, true);
  assert.equal(f.$('photo').hidden, false);
  const image = f.$('photo-stage').firstChild;
  assert.equal(image.tagName, 'IMG');
  assert.equal(image.src, '/api/relay/media/file?id=real-photo-id&session=empty-room');

  const savedPaper = f.context.paperButton(paper);
  card.append(savedPaper);
  savedPaper.click();
  assert.equal(f.$('reader').hidden, false);
  assert.equal(f.$('photo').hidden, true);
  assert.equal(f.$('reader-stage').innerHTML.replace(/<[^>]+>/g, ''), paper);
  assert.equal(f.cards().length, 1, 'opening attachments never creates extra messages');
  assertNoSampleDoors(f);
});
