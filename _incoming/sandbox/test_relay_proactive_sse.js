const fs = require('fs'), vm = require('vm'), assert = require('assert');
const source = fs.readFileSync('app.js', 'utf8');

function makeEl(id) {
  return { id, value: '', textContent: '', hidden: false, disabled: false, tabIndex: 0,
    dataset: {}, style: {}, classList: { add(){}, remove(){}, toggle(){}, contains(){return false;} },
    handlers: {}, attributes: {}, children: [],
    addEventListener(n, fn) { this.handlers[n] = fn; },
    removeEventListener(){}, append(...els){ this.children.push(...els); }, prepend(){}, replaceChildren(){}, remove(){},
    before(){}, after(){}, insertAdjacentHTML(){}, insertAdjacentElement(){},
    setAttribute(k, v) { this.attributes[k] = v; }, getAttribute(k) { return this.attributes[k] || null; },
    querySelector(){ return null; }, querySelectorAll(){ return []; }, closest(){ return null; },
    focus(){}, scrollIntoView(){}, getBoundingClientRect(){ return {x:0,y:0,width:100,height:100,top:0,left:0,right:100,bottom:100}; },
    insertBefore(){}, appendChild(){}, contains(){ return false; },
  };
}

function setVmState(c, assignments) {
  vm.runInContext(assignments, c);
}

function fixture() {
  const els = {};
  const ids = ['thread','draft','toast','menu','crumb','search','list','settings','reply-bar','reply-who','reply-snip','reply-jump','pick-bar','pick-copy','pick-reply','pick-reply-sep','slash-menu','typing','decision-card','decision-action','decision-description','decision-scope','decision-identity','decision-always-scope','deny-reason','deny-reason-form','deny-reason-cancel','deny-reason-limited','photo-stage','photo-input','staged-doc','draft-send','composer','goal-arm','tog-tags','tog-compact','tog-finished','tog-trash','page-settings','page-relay','relay-room-select','mesh-install','mesh-refresh','mesh-app-status'];
  for (const id of ids) els[id] = makeEl(id);
  const thread = els['thread'];
  Object.defineProperty(thread, 'lastElementChild', { get(){ const c = this.children || []; return c.length ? c[c.length-1] : null; } });
  thread.querySelectorAll = function(sel){
    const c = this.children || [];
    if (sel === 'article.msg') return c.filter(x => x.tagName === 'ARTICLE');
    if (sel === 'article.msg[data-proactive-seq]') return c.filter(x => x.tagName === 'ARTICLE' && x.dataset && x.dataset.proactiveSeq !== undefined);
    return [];
  };
  // `fitDraft` reads a composer-actions element's height; give the document
  // querySelector a real element for any selector app.js asks about.
  const actionsEl = makeEl('composer-actions');
  const composerEl = makeEl('composer');
  els['composer'] = composerEl;
  const doc = {
    getElementById: id => els[id] || (els[id] = makeEl(id)),
    createElement: tag => {
      const el = makeEl('');
      el.tagName = String(tag).toUpperCase();
      if (el.tagName === 'CANVAS') {
        el.getContext = () => ({
          clearRect(){}, fillText(){}, setTransform(){}, save(){}, restore(){},
          get font(){ return ''; }, set font(v){}, get fillStyle(){ return ''; }, set fillStyle(v){},
          get globalAlpha(){ return 1; }, set globalAlpha(v){}, get imageSmoothingEnabled(){ return false; }, set imageSmoothingEnabled(v){},
        });
      }
      return el;
    },
    querySelector: sel => {
      if (String(sel).includes('relay-actions')) return actionsEl;
      if (String(sel).includes('composer')) return composerEl;
      return null;
    },
    querySelectorAll: () => [],
    addEventListener(){}, dispatchEvent(){}, body: { classList: { contains(){return false;}, add(){}, remove(){}, toggle(){} } },
  };
  // `railRain` builds a canvas and reads a 2D context; give it a no-op one so
  // the rest of app.js can initialize without a real browser.
  const canvasEl = makeEl('rail-rain');
  canvasEl.getContext = () => ({
    clearRect(){}, fillText(){}, setTransform(){}, save(){}, restore(){},
    get font(){ return ''; }, set font(v){}, get fillStyle(){ return ''; }, set fillStyle(v){},
    get globalAlpha(){ return 1; }, set globalAlpha(v){}, get imageSmoothingEnabled(){ return false; }, set imageSmoothingEnabled(v){},
  });
  els['rail-rain'] = canvasEl;

  const storage = new Map();
  const localStore = new Map();
  const c = {
    document: doc,
    navigator: { vibrate(){}, clipboard: { writeText: async()=>{} } },
    location: { hash: '#relay', href: 'https://mesh.example/#relay', pathname: '/', search: '', replace(){} },
    matchMedia: () => ({ matches: false }),
    sessionStorage: { getItem: k => storage.has(k) ? storage.get(k) : null, setItem: (k,v) => storage.set(k,v), removeItem: k => storage.delete(k) },
    localStorage: { getItem: k => localStore.has(k) ? localStore.get(k) : null, setItem: (k,v) => localStore.set(k,v), removeItem: k => localStore.delete(k) },
    fetch: async () => ({ ok: true, json: async () => ({}) }),
    setTimeout, clearTimeout, setInterval: () => 0, clearInterval(){}, console, URL, Date, Math, JSON, encodeURIComponent, decodeURIComponent, Promise, Number, String, Array, Object, Set, Map, Error, isFinite, isNaN, parseFloat, parseInt,
    getSelection: () => ({ removeAllRanges(){}, addRange(){} }),
    addEventListener(){}, removeEventListener(){},
    isSecureContext: true,
    armGoal(){}, fitDraft(){}, paintSlash(){},
    roomBootstrap: Promise.resolve(),
    chatRoom(){ return this.selectedRelayRoom || 'relay-eddie-echo-chat'; },
  };
  c.selectedRelayRoom = '';
  c.window = c;
  // Timer bindings must be shared between the Node fixture and app.js's VM
  // global scope; otherwise pwa.js reads an app.js `let proactiveTimer` while
  // the test drives an unrelated context side-property.
  c.setTimeout = (fn, ms) => setTimeout(fn, ms);
  c.clearTimeout = id => clearTimeout(id);
  vm.createContext(c);
  vm.runInContext(source, c);
  // app.js defaults to the todo section; the proactive stream/poll only run on
  // the relay section, so put the fixture there before tests drive it. `ui` is a
  // const inside app.js, so it is not on the context object itself — reach it
  // through a tiny eval instead.
  vm.runInContext("ui.section = 'relay';", c);
  const fixtureApi = { c, els, storage, localStore };
  fixtureApi.setVmState = assignments => setVmState(c, assignments);
  return fixtureApi;
}

// Fake EventSource: records every instance so tests can drive events by hand.
class FakeEventSource {
  constructor(url) { this.url = url; this.listeners = {}; this.onerror = null; this.closed = false; FakeEventSource.instances.push(this); }
  addEventListener(n, fn) { (this.listeners[n] = this.listeners[n] || []).push(fn); }
  close() { this.closed = true; }
  emit(n, data) { (this.listeners[n] || []).forEach(fn => fn(typeof data === 'string' ? { data } : data)); }
}
FakeEventSource.instances = [];

function articleCards(c) {
  return (c.document.getElementById('thread').children || []).filter(x => x.tagName === 'ARTICLE');
}

// pwa.js reads the free identifiers below, which in the real page resolve to
// app.js's globals. In this fixture they are already properties of the shared
// vm context object (`busy`, `chatRun`, `ui`, ...), so no redeclaration is
// needed — only the few that are NOT already context properties are set here.
const PWA_GLOBALS = `
  if (typeof location === 'undefined') var location = this.location;
  if (typeof isSecureContext === 'undefined') var isSecureContext = this.isSecureContext;
`;
function pwaFixture() {
  const base = fixture();
  const c = base.c;
  c.EventSource = FakeEventSource;
  vm.runInContext("delete stopProactive;", c);
  c.proactiveTimer = 0;
  // A denied refresh should leave the product subscription open. The fixture
  // supplies the *same* stream binding that pwa.js resolves in the real page:
  // `proactiveStream`, not a test-only `c.proactiveStream` side property.
  c.syncProactiveStream = () => { c.proactiveStream = vm.runInContext("typeof proactiveStream === 'undefined' ? null : proactiveStream", c); };
  // pwa.js's free identifiers resolve to these context properties directly.
  // `busy`, `chatRun`, and `ui` are real `let` bindings in app.js. Defining
  // context side-properties would be shadowed by those declarations, so drive
  // their product values through the same VM global scope.
  c.photoUploading = false;
  c.staged = null; c.stagedPhoto = null; c.replyTo = null;
  c.setUnsavedState = state => {
    const {busy = false, chatRun = null, editing = null} = state || {};
    setVmState(c, `busy = ${JSON.stringify(busy)}; chatRun = ${JSON.stringify(chatRun)}; ui.editing = ${JSON.stringify(editing)};`);
  };
  c.roomBootstrap = Promise.resolve();
  c.chatRoom = () => 'relay-eddie-echo-chat';
  c.proactiveTimer = 0;
  c.armGoal = () => {}; c.fitDraft = () => {}; c.paintSlash = () => {};
  c.fetch = async () => ({ ok: true, headers: { get: () => 'text/html' }, json: async () => ({}) });
  vm.runInContext(fs.readFileSync('pwa.js', 'utf8'), c);
  base.syncProactiveStream = c.syncProactiveStream;
  base.setUnsavedState = c.setUnsavedState;
  return base;
}

(async () => {
  // 1. EventSource is the primary delivery path, room-scoped.
  let f = fixture();
  f.c.EventSource = FakeEventSource;
  f.c.startProactive();
  assert.equal(FakeEventSource.instances.length, 1, 'EventSource opened');
  const es = FakeEventSource.instances[0];
  assert(es.url.includes('/api/relay/proactive/stream'), 'SSE path used');
  assert(es.url.includes('session=relay-eddie-echo-chat'), 'room scoped');
  es.emit('message', JSON.stringify({ session_id: 'relay-eddie-echo-chat', seq: 1, id: 'msg-p-1', message_id: 'msg-p-1', author: 'Echo', recipient: 'Eddie', text: 'hello', created_at: '2026-01-01T00:00:00Z', replayed: false }));
  assert.equal(articleCards(f.c).length, 1, 'one card drawn');
  assert.equal(articleCards(f.c)[0].dataset.proactiveId, 'msg-p-1');

  // 2. Dedupe: same message_id twice -> still one card (restored history + live event + replay cannot double-draw).
  es.emit('message', JSON.stringify({ session_id: 'relay-eddie-echo-chat', seq: 1, id: 'msg-p-1', message_id: 'msg-p-1', text: 'hello', created_at: '2026-01-01T00:00:00Z', replayed: false }));
  assert.equal(articleCards(f.c).length, 1, 'deduped by stable message_id');

  // 3. Cross-room stale callback: an event delivered after a room switch draws nothing.
  // `chatRoom()` is a function inside app.js, not a context object property, so
  // drive the room switch through a small eval rather than mutating a global.
  let f2 = fixture();
  f2.c.EventSource = FakeEventSource;
  f2.c.startProactive();
  const es2 = FakeEventSource.instances[FakeEventSource.instances.length - 1];
  vm.runInContext("selectedRelayRoom = 'relay-eddie-echo-other';", f2.c);
  es2.emit('message', JSON.stringify({ session_id: 'relay-eddie-echo-chat', seq: 5, id: 'msg-p-5', message_id: 'msg-p-5', text: 'stale', created_at: 'x', replayed: false }));
  assert.equal(articleCards(f2.c).length, 0, 'stale cross-room callback drew nothing');
  // ...and switching *back* lets the same live event draw normally.
  vm.runInContext("selectedRelayRoom = '';", f2.c);
  es2.emit('message', JSON.stringify({ session_id: 'relay-eddie-echo-chat', seq: 5, id: 'msg-p-5', message_id: 'msg-p-5', text: 'stale', created_at: 'x', replayed: false }));
  assert.equal(articleCards(f2.c).length, 1, 'same event draws once the room is the authorized one again');

  // 4. Draft/composer preservation: a live proactive delivery never touches the composer.
  let f3 = fixture();
  f3.c.EventSource = FakeEventSource;
  f3.els['draft'].value = 'my typed draft';
  f3.c.startProactive();
  const es3 = FakeEventSource.instances[FakeEventSource.instances.length - 1];
  es3.emit('message', JSON.stringify({ session_id: 'relay-eddie-echo-chat', seq: 9, id: 'msg-p-9', message_id: 'msg-p-9', text: 'ping', created_at: 'x', replayed: false }));
  assert.equal(f3.els['draft'].value, 'my typed draft', 'draft preserved across a live proactive delivery');

  // 5. Denied hard refresh keeps the subscription (a send is in flight).
  let pf = pwaFixture();
  pf.setUnsavedState({busy: true});
    setVmState(pf.c, 'proactiveTimer = setTimeout(() => {}, 60000);');   // a live bounded poll
  pf.c.startProactive();
  pf.syncProactiveStream();                                 // opens the EventSource too
  const esP = FakeEventSource.instances[FakeEventSource.instances.length - 1];
  assert.equal(esP.closed, false, 'stream open before refresh attempt');
  const refused = await pf.c.meshPwa.hardRefresh();
  assert.strictEqual(typeof refused, 'boolean', 'hard refresh returns its own boolean, not a cross-realm Promise');
  assert.strictEqual(refused, false, 'hard refresh refused while a send is in flight');
  assert.equal(esP.closed, false, 'denied hard refresh kept the subscription open');

  // 6. Denied hard refresh keeps the subscription (delivery uncertain).
  let pf2 = pwaFixture();
  pf2.setUnsavedState({chatRun: 'uncertain'});
  setVmState(pf2.c, 'proactiveTimer = setTimeout(() => {}, 60000);');
  pf2.c.startProactive();
  pf2.syncProactiveStream();
  const esP2 = FakeEventSource.instances[FakeEventSource.instances.length - 1];
  assert.equal(esP2.closed, false, 'stream open');
  const refused2 = await pf2.c.meshPwa.hardRefresh();
  assert.strictEqual(refused2, false, 'hard refresh refused while delivery is uncertain');
  assert.equal(esP2.closed, false, 'denied hard refresh (uncertain path) kept the subscription open');

  // 7. An *allowed* hard refresh closes the stream (the one case pwa may stop it).
  let pf3 = pwaFixture();
  setVmState(pf3.c, 'proactiveTimer = setTimeout(() => {}, 60000);');
  pf3.c.startProactive();
  pf3.syncProactiveStream();
  const esP3 = FakeEventSource.instances[FakeEventSource.instances.length - 1];
  const allowed = await pf3.c.meshPwa.hardRefresh();
  assert.strictEqual(allowed, true, 'clean hard refresh allowed');
  assert.equal(esP3.closed, true, 'an allowed hard refresh closes the stream before reload');

  // pwa.js's own no-stopProactive fallback must close app.js's real stream, too.
  let pf4 = pwaFixture();
  vm.runInContext("delete stopProactive;", pf4.c);
  setVmState(pf4.c, 'proactiveTimer = setTimeout(() => {}, 60000);');
  pf4.c.startProactive();
  pf4.syncProactiveStream();
  const esP4 = FakeEventSource.instances[FakeEventSource.instances.length - 1];
  const allowed4 = await pf4.c.meshPwa.hardRefresh();
  assert.strictEqual(allowed4, true, 'clean hard refresh allowed through pwa fallback');
  assert.equal(esP4.closed, true, 'pwa no-stopProactive fallback closes stream before reload');
  assert.strictEqual(vm.runInContext('proactiveTimer', pf4.c), 0, 'pwa fallback clears the bounded timer');

  // 8. Reconnect/visibility catch-up: after the stream is closed (e.g. tab hidden then
  // re-shown via stopProactive/startProactive), a fresh connection is opened and the
  // cursor still derives from what was actually rendered.
  let f4 = fixture();
  f4.c.EventSource = FakeEventSource;
  f4.c.startProactive();
  const esA = FakeEventSource.instances[FakeEventSource.instances.length - 1];
  esA.emit('message', JSON.stringify({ session_id: 'relay-eddie-echo-chat', seq: 3, id: 'msg-p-3', message_id: 'msg-p-3', text: 'first', created_at: 'x', replayed: false }));
  f4.c.stopProactive();
  assert.equal(esA.closed, true, 'stopProactive closed the stream');
  f4.c.startProactive();
  const esB = FakeEventSource.instances[FakeEventSource.instances.length - 1];
  assert(esB !== esA, 'a fresh EventSource is opened on reconnect');
  assert(esB.url.includes('last_seq=3'), 'the reconnect resumes from the rendered cursor');
  // The already-seen message is not double-drawn after the reconnect.
  esB.emit('message', JSON.stringify({ session_id: 'relay-eddie-echo-chat', seq: 3, id: 'msg-p-3', message_id: 'msg-p-3', text: 'first', created_at: 'x', replayed: false }));
  assert.equal(articleCards(f4.c).length, 1, 'reconnect replay did not double-draw');
  // A genuinely new message after reconnect is drawn and advances the cursor.
  esB.emit('message', JSON.stringify({ session_id: 'relay-eddie-echo-chat', seq: 4, id: 'msg-p-4', message_id: 'msg-p-4', text: 'second', created_at: 'x', replayed: false }));
  assert.equal(articleCards(f4.c).length, 2, 'new post-reconnect message drawn');

  console.log('PASS SSE slice: EventSource primary delivery, dedupe, cross-room stale callback, draft preservation, denied hard-refresh keeps subscription, allowed refresh closes stream, reconnect resumes from rendered cursor without double-draw');
})().catch(e => { console.error(e); process.exit(1); });
