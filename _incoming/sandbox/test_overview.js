const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {test} = require('node:test');

const source = fs.readFileSync(path.join(__dirname, 'app.js'), 'utf8');
const html = fs.readFileSync(path.join(__dirname, 'index.html'), 'utf8');
const metrics = {
  cpu: {load_available: true, load_percent: 25, temperature_c: null, fan_percent: null, power_w: null},
  gpu: {available: true, gpu: {utilization_gpu_percent: 0, utilization_memory_percent: 93,
    vram_percent: 50, vram_used_bytes: 8 * 1024 ** 3, vram_total_bytes: 16 * 1024 ** 3,
    temperature_c: 32, fan_percent: 41, power_w: 20}},
  memory: {available: true, percent_used: 75, used_bytes: 48 * 1024 ** 3, total_bytes: 64 * 1024 ** 3},
  drives: [{letter: 'C', available: true, percent_used: 70, free_bytes: 300, total_bytes: 1000},
    {letter: 'D', available: true, percent_used: 79, free_bytes: 210, total_bytes: 1000}],
  llm: [{engine: 'strata', status: 'loaded', model_id: 'verified-model', context: 196608}]
};
function block(start, end) {
  const first = source.indexOf(start), last = source.indexOf(end, first);
  assert.ok(first >= 0 && last > first);
  return source.slice(first, last);
}
function element(tag, attrs) {
  const decode = text => text.replace(/&(amp|lt|gt|quot|#39);/g, (_, entity) => ({amp: '&', lt: '<', gt: '>', quot: '"', '#39': "'"}[entity]));
  const attributes = Object.fromEntries([...attrs.matchAll(/([\w-]+)="([^"]*)"/g)].map(m => [m[1], decode(m[2])]));
  return {
    tagName: tag.toUpperCase(), attributes, id: attributes.id,
    hidden: /(?:^|\s)hidden(?:\s|$)/.test(attrs), innerHTML: '', value: '', handlers: {},
    dataset: Object.fromEntries(Object.entries(attributes).filter(([key]) => key.startsWith('data-'))
      .map(([key, value]) => [key.slice(5).replace(/-([a-z])/g, (_, letter) => letter.toUpperCase()), value])),
    classList: {toggle() {}},
    addEventListener(name, fn) { this.handlers[name] = fn; },
    setAttribute(name, value) { this.attributes[name] = value; },
    getAttribute(name) { return this.attributes[name]; },
    removeAttribute(name) { delete this.attributes[name]; },
    closest(selector) {
      if (selector === '[data-overview-status]') return this.dataset.overviewStatus === undefined ? null : this;
      return {focus() {}};
    }
  };
}
function markupNodes(markup) {
  const nodes = [], stack = [];
  for (const match of markup.matchAll(/<(\/?)([a-z][\w-]*)\b([^>]*)>/gi)) {
    const [, closing, tag, attrs] = match;
    if (closing) { stack.pop(); continue; }
    const node = element(tag, attrs);
    node.parentElement = stack.at(-1) || null;
    nodes.push(node);
    if (!/^(area|base|br|col|embed|hr|img|input|link|meta|param|source|track|wbr)$/i.test(tag) && !/\/$/.test(attrs)) stack.push(node);
  }
  return nodes;
}
function inside(node, ancestor) {
  for (let parent = node.parentElement; parent; parent = parent.parentElement) if (parent === ancestor) return true;
  return false;
}
// Use the actual page IDs, button attributes, navigation function and boot call.
// No server or browser process is started.
function fixture(hash = '', fetcher = async () => ({ok: true, json: async () => metrics}), overview = {
  handoff: {state: 'none'}, cards: [{id: 'real', title: 'Now card', line: 'open', state: 'idle'}]
}) {
  const nodes = new Map(markupNodes(html).filter(node => node.id).map(node => [node.id, node]));
  const $ = id => { assert.ok(nodes.has(id), `real markup contains ${id}`); return nodes.get(id); };
  const navs = [...nodes.values()].filter(node => node.dataset.section);
  const document = {hidden: false, body: {classList: {toggle() {}}}, handlers: {},
    querySelector(selector) { return navs.find(node => selector === `[data-section="${node.dataset.section}"]`); },
    querySelectorAll(selector) {
      if (selector === '[data-section]') return navs;
      if (selector === '.page') return [...nodes.values()].filter(node => /(?:^|\s)page(?:\s|$)/.test(node.attributes.class || ''));
      throw new Error(selector);
    },
    addEventListener(name, fn) { this.handlers[name] = fn; }
  };
  const window = {handlers: {}, addEventListener(name, fn) { this.handlers[name] = fn; }};
  const calls = [], requests = [], historyRooms = [], toasts = [], timers = new Map(); let nextTimer = 0;
  const context = vm.createContext({$, document, window, location: {hash}, AbortController,
    fetch: async (url, options) => {
      requests.push({url, options});
      if (url === '/api/system/metrics') { calls.push({url, options}); return fetcher(url, options); }
      if (url === '/api/handoff') return {ok: true, json: async () => overview.handoff};
      if (url === '/api/state') return {ok: true, json: async () => ({cards: overview.cards})};
      throw new Error('Unexpected request: ' + url);
    },
    placeToast() {}, setAdd() {}, openPanel() {},
    loadHistory() { historyRooms.push(vm.runInContext('chatRoom()', context)); },
    startProactive() {}, stopProactive() {}, fitDraft() {},
    toast(message) { toasts.push(message); },
    setTimeout(fn, ms) { const id = ++nextTimer; timers.set(id, {fn, ms}); return id; },
    clearTimeout(id) { timers.delete(id); }
  });
  const uiLine = source.match(/^const ui = .*$/m)[0];
  const escapeLine = source.match(/^function escapeHtml\(.*$/m)[0];
  const boot = source.match(/^showSection\(location\.hash.*$/m)[0];
  const capLine = source.match(/^const BOX_CAP = .*$/m)[0];
  vm.runInContext([uiLine, escapeLine, capLine, block('async function request(', 'function escapeHtml('),
    block('let selectedRelayRoom =', "let historyRoom ="),
    "let standingGoal = {status: 'active', goal: 'Keep the existing goal'};",
    block('function showSection(', 'let standingGoal ='), boot].join('\n'), context);
  return {context, $, document, window, calls, requests, historyRooms, toasts, timers,
    statusButtons() { return markupNodes($('overview-cards').innerHTML).filter(node => node.dataset.overviewStatus !== undefined); },
    tapStatus(button = this.statusButtons()[0]) { $('overview-cards').handlers.click({target: button}); },
    run(code) { return vm.runInContext(code, context); },
    fireTimer() {
      assert.equal(timers.size, 1);
      const [id, timer] = timers.entries().next().value;
      timers.delete(id); return timer.fn();
    }
  };
}
const settle = () => new Promise(resolve => setImmediate(resolve));
const lines = node => [...node.innerHTML.matchAll(/<div class="overview-line">(.*?)<\/div>/g)].map(m => m[1]);

test('no-hash landing opens Overview', async () => {
  const f = fixture(); await settle();
  assert.equal(f.run('ui.section'), 'overview');
  assert.equal(f.$('page-overview').hidden, false);
  assert.equal(f.$('stage').hidden, true);
  assert.equal(f.calls.length, 1);
});
test('explicit relay, todo and log hashes win, including hash changes', async () => {
  for (const section of ['relay', 'todo', 'log']) {
    const f = fixture('#' + section); await settle();
    assert.equal(f.run('ui.section'), section);
    assert.equal(f.calls.length, 0);
    f.context.location.hash = '';
    f.window.handlers.hashchange(); await settle();
    assert.equal(f.run('ui.section'), 'overview');
    f.context.location.hash = '#' + section;
    f.window.handlers.hashchange();
    assert.equal(f.run('ui.section'), section);
    assert.equal(f.timers.size, 0);
  }
});
test('PC and more are real buttons; PC starts open and more starts closed on every arrival', async () => {
  const f = fixture(); await settle();
  for (const name of ['pc', 'more']) {
    const button = f.$(`overview-${name}-toggle`);
    assert.equal(button.tagName, 'BUTTON');
    assert.equal(button.getAttribute('type'), 'button');
    assert.equal(button.getAttribute('aria-controls'), `overview-${name}`);
  }
  assert.equal(f.$('overview-pc').hidden, false);
  assert.equal(f.$('overview-more').hidden, true);
  f.$('overview-more-toggle').handlers.click();
  f.$('overview-pc-toggle').handlers.click();
  assert.equal(f.$('overview-pc').hidden, true);
  assert.equal(f.$('overview-pc-toggle').getAttribute('aria-expanded'), 'false');
  assert.equal(f.$('overview-more').hidden, false);
  f.run("showSection('todo'); showSection('overview');"); await settle();
  assert.equal(f.$('overview-pc').hidden, false);
  assert.equal(f.$('overview-pc-toggle').getAttribute('aria-expanded'), 'true');
  assert.equal(f.$('overview-more').hidden, true);
  assert.equal(f.$('overview-more-toggle').getAttribute('aria-expanded'), 'false');
});
test('front displays CPU, nvidia GPU utilization, RAM, VRAM and percent-full drives in order', async () => {
  const f = fixture(); await settle();
  const rows = lines(f.$('overview-pc-metrics'));
  assert.match(rows[0], /^CPU load 25%$/);
  assert.match(rows[1], /^GPU load 0%$/);
  assert.match(rows[2], /^RAM 75% .*48\.0 GiB \/ 64\.0 GiB$/);
  assert.match(rows[3], /^VRAM 50% .*8\.0 GiB \/ 16\.0 GiB$/);
  assert.equal(rows[4], 'C 70%');
  assert.equal(rows[5], 'D 79%');
  assert.doesNotMatch(rows.slice(4).join(' '), /free|bytes|GiB|total|1000|300/i);
});
test('failed CPU probe displays unavailable and no percent even if a stale number exists', async () => {
  const f = fixture('', async () => ({ok: true, json: async () => ({...metrics, cpu: {load_available: false, load_percent: 84}})}));
  await settle();
  const row = lines(f.$('overview-pc-metrics'))[0];
  assert.equal(row, 'CPU load unavailable');
  assert.doesNotMatch(row, /%|84/);
});
test('more contains unavailable CPU sensors, GPU sensors and Strata; holds contains existing cards', async () => {
  const f = fixture(); await settle();
  assert.deepEqual(lines(f.$('overview-extra')), ['CPU temperature unavailable', 'CPU fan unavailable', 'CPU power unavailable',
    'GPU temperature 32\u00b0C', 'GPU fan 41%', 'GPU power 20 W', 'Strata loaded \u00b7 verified-model \u00b7 context 196608']);
  assert.match(f.$('overview-cards').innerHTML, /Now card/);
  assert.equal(inside(f.$('overview-extra'), f.$('overview-more')), true);
  assert.equal(inside(f.$('overview-cards'), f.$('overview-more')), false);
  assert.equal(inside(f.$('overview-cards'), f.$('overview-holds')), true);
});
test('polling uses GET with no-store, keeps toggle state, and stops when leaving Overview', async () => {
  const f = fixture(); await settle();
  assert.equal(f.calls[0].url, '/api/system/metrics');
  assert.equal(f.calls[0].options.method, undefined);
  assert.equal(f.calls[0].options.cache, 'no-store');
  assert.equal([...f.timers.values()][0].ms, 5000);
  f.$('overview-more-toggle').handlers.click();
  f.$('overview-pc-toggle').handlers.click();
  f.$('overview-holds-toggle').handlers.click();
  await f.fireTimer();
  assert.equal(f.calls.length, 2);
  assert.equal(f.$('overview-pc').hidden, true);
  assert.equal(f.$('overview-more').hidden, false);
  assert.equal(f.$('overview-holds').hidden, false);
  f.run("showSection('relay')");
  assert.equal(f.timers.size, 0);
  f.window.handlers.focus(); await settle();
  assert.equal(f.calls.length, 2);
});
test('leaving aborts in-flight metrics and rejects late updates without rescheduling', async () => {
  let resolve;
  const f = fixture('', () => new Promise(done => { resolve = done; }));
  f.run("showSection('todo')");
  assert.equal(f.calls[0].options.signal.aborted, true);
  const before = f.$('overview-pc-metrics').innerHTML;
  resolve({ok: true, json: async () => metrics}); await settle();
  assert.equal(f.$('overview-pc-metrics').innerHTML, before);
  assert.equal(f.timers.size, 0);
});
test('hidden document stops polling and visibility arrival resets disclosures', async () => {
  const f = fixture(); await settle();
  f.$('overview-pc-toggle').handlers.click();
  f.$('overview-more-toggle').handlers.click();
  f.$('overview-holds-toggle').handlers.click();
  f.document.hidden = true; f.document.handlers.visibilitychange();
  assert.equal(f.timers.size, 0);
  f.document.hidden = false; f.document.handlers.visibilitychange(); await settle();
  assert.equal(f.calls.length, 2);
  assert.equal(f.$('overview-pc').hidden, false);
  assert.equal(f.$('overview-more').hidden, true);
  assert.equal(f.$('overview-holds').hidden, true);
  assert.equal(f.$('overview-holds-toggle').getAttribute('aria-expanded'), 'false');
});
test('failed metrics request clears old numbers and polls again', async () => {
  let failing = false;
  const f = fixture('', async () => { if (failing) throw new Error('probe failed'); return {ok: true, json: async () => metrics}; });
  await settle(); failing = true;
  await f.fireTimer();
  assert.equal(lines(f.$('overview-pc-metrics'))[0], 'CPU load unavailable');
  assert.equal(lines(f.$('overview-pc-metrics'))[4], 'C unavailable');
  assert.equal(f.timers.size, 1);
});


test('holds is a sibling card outside PC, starts closed, toggles and resets on arrival', async () => {
  const f = fixture(); await settle();
  const button = f.$('overview-holds-toggle'), pane = f.$('overview-holds');
  assert.equal(button.tagName, 'BUTTON');
  assert.equal(button.getAttribute('type'), 'button');
  assert.equal(button.getAttribute('aria-controls'), pane.id);
  assert.equal(button.getAttribute('aria-expanded'), 'false');
  assert.equal(pane.hidden, true);
  assert.equal(inside(button, f.$('overview-pc')), false);
  assert.equal(inside(pane, f.$('overview-pc')), false);
  assert.equal(pane.parentElement.parentElement, f.$('overview-pc').parentElement.parentElement);
  button.handlers.click();
  assert.equal(pane.hidden, false);
  assert.equal(button.getAttribute('aria-expanded'), 'true');
  button.handlers.click();
  assert.equal(pane.hidden, true);
  button.handlers.click();
  f.run("showSection('todo'); showSection('overview');"); await settle();
  assert.equal(pane.hidden, true);
  assert.equal(button.getAttribute('aria-expanded'), 'false');
  button.handlers.click();
  f.window.handlers.focus(); await settle();
  assert.equal(pane.hidden, true);
  assert.equal(button.getAttribute('aria-expanded'), 'false');
  assert.match(html, /<script src="\/app\.js\?v=overview-holds1" defer><\/script>/);
});

test('holds shows the held card once and other open cards, without samples, trash or finished cards', async () => {
  const f = fixture('', undefined, {handoff: {id: 'held', title: 'Held <card>', state: 'paused'}, cards: [
    {id: 'held', title: 'Held <card>', state: 'paused', line: 'held line'},
    {id: 'other', title: 'Other "card" & details', state: 'idle'},
    {id: 'sample', title: 'Hidden sample', state: 'ready', sample: true},
    {id: 'trash', title: 'Hidden trash', state: 'trash'},
    {id: 'finished', title: 'Hidden finished', state: 'finished'}
  ]}); await settle();
  const markup = f.$('overview-cards').innerHTML;
  assert.doesNotMatch(markup, /Hidden sample|Hidden trash|Hidden finished/);
  assert.equal((markup.match(/<article\b/g) || []).length, 2);
  const buttons = f.statusButtons();
  assert.deepEqual(buttons.map(button => button.dataset.overviewStatus), ['Held <card>', 'Other "card" & details']);
  for (const button of buttons) {
    assert.equal(button.tagName, 'BUTTON');
    assert.equal(button.getAttribute('type'), 'button');
  }
  f.tapStatus(buttons[1]);
  assert.equal(f.$('draft').value, 'Status on: Other "card" & details');
});

test('status stages an empty draft and opens Relay in the same room on repeated taps without sending', async () => {
  for (const room of ['', 'existing-room']) {
    const f = fixture(); await settle();
    f.run(`selectedRelayRoom = ${JSON.stringify(room)}`);
    const currentRoom = f.run('chatRoom()');
    const beforeGoal = f.run('JSON.stringify(standingGoal)');
    const beforeRequests = f.requests.length;
    const beforeArm = f.$('goal-arm').getAttribute('aria-pressed');
    f.$('overview-holds-toggle').handlers.click();
    f.tapStatus(); await settle();
    assert.equal(f.$('draft').value, 'Status on: Now card');
    assert.equal(f.run('ui.section'), 'relay');
    assert.equal(f.$('page-relay').hidden, false);
    assert.equal(f.context.location.hash, 'relay');
    assert.equal(f.run('chatRoom()'), currentRoom);
    assert.equal(f.run('selectedRelayRoom'), room);
    assert.deepEqual(f.historyRooms, [currentRoom]);
    assert.deepEqual(f.requests.slice(beforeRequests), []);
    assert.equal(f.run('JSON.stringify(standingGoal)'), beforeGoal);
    assert.equal(f.$('goal-arm').getAttribute('aria-pressed'), beforeArm);
    f.tapStatus();
    assert.equal(f.$('draft').value, 'Status on: Now card');
    assert.match(f.toasts.at(-1), /composer has text/i);
    f.$('draft').value = '';
    f.tapStatus(); await settle();
    assert.equal(f.$('draft').value, 'Status on: Now card');
    assert.deepEqual(f.historyRooms, [currentRoom, currentRoom]);
    assert.equal(f.run('selectedRelayRoom'), room);
    assert.equal(f.run('JSON.stringify(standingGoal)'), beforeGoal);
    assert.deepEqual(f.requests.slice(beforeRequests), []);
  }
});

test('status preserves existing composer text and room without opening Relay or making requests', async () => {
  for (const text of ['Unsent message', '   ', '/new']) {
    const f = fixture(); await settle();
    f.run("selectedRelayRoom = 'keep-this-room'");
    f.$('draft').value = text;
    const beforeRequests = f.requests.length;
    f.tapStatus(); await settle();
    assert.equal(f.$('draft').value, text);
    assert.equal(f.run('chatRoom()'), 'keep-this-room');
    assert.equal(f.run('selectedRelayRoom'), 'keep-this-room');
    assert.equal(f.run('ui.section'), 'overview');
    assert.equal(f.context.location.hash, '');
    assert.deepEqual(f.historyRooms, []);
    assert.deepEqual(f.requests.slice(beforeRequests), []);
    assert.match(f.toasts.at(-1), /composer has text/i);
  }
});

test('status trims staged text to the existing 1000 character box', async () => {
  const title = 'Long title '.repeat(150);
  const f = fixture('', undefined, {handoff: {state: 'none'}, cards: [{id: 'long', title, state: 'idle'}]});
  await settle(); f.tapStatus();
  assert.equal(f.$('draft').value, ('Status on: ' + title).slice(0, 1000));
  assert.equal(f.$('draft').value.length, 1000);
});
