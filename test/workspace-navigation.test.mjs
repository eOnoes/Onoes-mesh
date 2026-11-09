import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';

// Execute the actual navigation block without starting sessions or other app work.
const app = readFileSync(new URL('../public/app.js', import.meta.url), 'utf8');
const navigation = app.slice(app.indexOf('let clearWorkroom ='), app.indexOf('const menuMedia ='));
const names = ['overview', 'relay', 'inference', 'workroom', 'agent', 'mind', 'control'];
function browser(hash = '#inference', {historyFails = false} = {}) {
  const panels = Object.fromEntries(names.map(name => ['panel-' + name, {hidden: name !== 'overview'}]));
  const tabs = names.map(name => ({
    id: 'tab-' + name, events: {}, attributes: {'aria-controls': 'panel-' + name, 'aria-selected': String(name === 'overview')},
    setAttribute(key, value) { this.attributes[key] = value; },
    getAttribute(key) { return this.attributes[key]; },
    addEventListener(type, listener) { this.events[type] = listener; },
    focus() { this.focused = true; },
  }));
  const draft = {value: 'unsaved goal remains here'}, writes = [], events = {};
  let networkCalls = 0;
  const location = new URL('https://mesh.example/mesh?card=existing' + hash);
  const state = {kept: 'existing browser state'};
  const window = {location, history: {state, replaceState(nextState, title, fragment) {
    if (historyFails) throw Error('history unavailable');
    writes.push({nextState, title, fragment});
    location.href = new URL(fragment, location).href;
  }}, addEventListener(type, listener) { events[type] = listener; }};
  const document = {
    getElementById(id) { return tabs.find(tab => tab.id === id) ?? panels[id] ?? draft; },
    querySelectorAll(selector) { assert.equal(selector, '[role=tab]'); return tabs; },
  };
  vm.runInNewContext(navigation, {window, document, fetch() { networkCalls++; throw Error('no network in navigation'); }});
  return {tabs, panels, draft, writes, window, events, networkCalls: () => networkCalls,
    tab: name => tabs.find(tab => tab.id === 'tab-' + name)};
}

test('clicking a workspace updates the reload link without navigating away or losing drafts', () => {
  const b = browser();
  b.tab('control').events.click();
  assert.equal(b.window.location.hash, '#control');
  assert.equal(b.window.location.pathname, '/mesh');
  assert.equal(b.window.location.search, '?card=existing');
  assert.equal(b.panels['panel-control'].hidden, false);
  assert.equal(b.panels['panel-inference'].hidden, true);
  assert.equal(b.writes.length, 1);
  assert.equal(b.writes[0].nextState, b.window.history.state);
  assert.equal(b.draft.value, 'unsaved goal remains here');
  assert.equal(b.networkCalls(), 0);
  const reloaded = browser(b.window.location.hash);
  assert.equal(reloaded.panels['panel-control'].hidden, false);
  assert.equal(reloaded.writes.length, 0);
});

test('keyboard tab navigation keeps focus and the reload link on the selected workspace', () => {
  const b = browser();
  let prevented = false;
  b.tab('inference').events.keydown({key: 'ArrowRight', preventDefault() { prevented = true; }});
  assert.equal(prevented, true);
  assert.equal(b.window.location.hash, '#workroom');
  assert.equal(b.tab('workroom').focused, true);
  b.tab('workroom').events.keydown({key: 'End', preventDefault() {}});
  assert.equal(b.window.location.hash, '#control');
  assert.equal(b.networkCalls(), 0);
});

test('external workspace hashes remain read-only selections without a history loop', () => {
  const b = browser();
  b.window.location.hash = '#relay';
  b.events.hashchange();
  assert.equal(b.panels['panel-relay'].hidden, false);
  assert.equal(b.writes.length, 0);
  assert.equal(b.networkCalls(), 0);
});

test('history failures do not blank the selected workspace or start network work', () => {
  const b = browser('#inference', {historyFails: true});
  b.tab('control').events.click();
  assert.equal(b.panels['panel-control'].hidden, false);
  assert.equal(b.networkCalls(), 0);
});
