import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import vm from 'node:vm';
import { controlledProbe } from './m5-nodes-fixture.mjs';
import { createNodeProbeReader } from '../lib/node-probes.mjs';

const source = await readFile(new URL('../public/app.js', import.meta.url), 'utf8');
const renderer = source.slice(source.indexOf('function renderNodeProbes('),
  source.indexOf('\nasync function refreshNodeProbes(')).trim();
assert.ok(renderer.endsWith('}'), 'load exactly the production renderer');
class Element {
  constructor(tag) { this.tagName = tag; this.children = []; this.className = ''; this.attributes = {}; }
  append(...children) { this.children.push(...children); }
  replaceChildren(...children) { this.children = children; }
  setAttribute(key, value) { this.attributes[key] = value; }
  set textContent(text) { this.children = [text]; }
  get textContent() { return this.children.map(c => typeof c === 'string' ? c : c.textContent).join(''); }
}
function ui() {
  const box = new Element('div');
  const context = vm.createContext({ document: { createElement: tag => new Element(tag) },
    $: () => box, tick: 0, busy: true, nodeProbeSnapshot: null, nodeProbeReceivedAt: 0 });
  vm.runInContext(`const probeTick = () => tick;
    function paragraph(parent, text) {
      const el = document.createElement('p'); el.textContent = text; parent.append(el); return el;
    }
    ${renderer}`, context);
  return { box, context, render(snapshot, elapsed = 0) {
    context.snapshot = snapshot; context.tick = elapsed;
    vm.runInContext('renderNodeProbes(snapshot, 0)', context);
    return box.children.map(card => ({ card, line: card.children[2], word: card.children[2]?.children[1] }));
  } };
}
async function ready() {
  const tx = controlledProbe();
  const reader = createNodeProbeReader(tx.options);
  return { tx, reader, snapshot: await reader.refresh() };
}
test('never checked and unsuccessful first observation never imply Offline',async()=>{
  const tx=controlledProbe(),reader=createNodeProbeReader(tx.options),view=ui();
  const initial=reader.snapshot(),before=JSON.stringify(initial);
  view.render(initial).forEach(row=>{
    check(row,'Not checked','neutral');
    assert.match(row.line.textContent,/no machine status result available/);
    assert.doesNotMatch(row.card.textContent,/Offline|observation_expired/);
  });
  view.render(initial,initial.limits.staleGraceMs*10).forEach(row=>check(row,'Not checked','neutral'));
  assert.equal(tx.calls.length,0);assert.equal(JSON.stringify(initial),before);
  tx.fail();const failed=await reader.refresh();
  assert.ok(failed.nodes.every(n=>n.tailscaleOnline===null));
  view.render(failed).forEach(row=>{
    check(row,'Unavailable','neutral');
    assert.doesNotMatch(row.line.textContent,/cached status|Offline/);
  });
});
function check(row, label, state) {
  assert.equal(row.word.tagName, 'span');
  assert.equal(row.word.textContent, label);
  assert.equal(row.word.className, 'node-status node-status--' + state);
  assert.equal(row.line.className, '', 'color applies to the status word only');
  assert.match(row.card.textContent, /Packet reachability: unknown · Inference readiness: unknown · Model readiness: unknown/);
}

test('fresh ready is Online; cached Online and global UI busy cannot make stale/offline green or Busy', async () => {
  const { snapshot } = await ready(), view = ui(), original = JSON.stringify(snapshot);
  view.render(snapshot).forEach(row => check(row, 'Online', 'online'));
  view.render(snapshot, snapshot.limits.freshMs).forEach(row => {
    check(row, 'Stale', 'stale');
    assert.match(row.line.textContent, /cached Tailscale Online: true/);
    assert.match(row.card.textContent, /observation_expired/);
  });
  view.render(snapshot, snapshot.limits.staleGraceMs).forEach(row => check(row, 'Check expired', 'stale'));
  assert.equal(JSON.stringify(snapshot), original, 'renderer never changes cached fields, timestamps or provenance');
});

test('real controlled offline versus unavailable reads retain distinct wording and neutral cached status', async () => {
  const { tx, reader, snapshot } = await ready(), view = ui();
  tx.offline(); tx.advance(snapshot.limits.staleGraceMs);
  view.render(await reader.refresh()).forEach(row => check(row, 'Offline', 'offline'));
  tx.fail();
  view.render(await reader.refresh()).forEach(row => {
    check(row, 'Offline', 'neutral');
    assert.equal(row.line.textContent, 'Observation unavailable · cached status: Offline · offline not established by this read');
  });
  for (const status of ['ready', 'stale', 'offline', 'busy', 'unavailable', 'unknown', 'not_configured']) {
    const cached = structuredClone(snapshot);
    cached.nodes.forEach(n => { n.status = status; n.observationAvailability = 'unavailable'; });
    view.render(cached).forEach(row => {
      assert.equal(row.word.className, 'node-status node-status--neutral');
      assert.match(row.line.textContent, /Observation unavailable · cached status: .* · offline not established by this read/);
    });
  }
});

test('explicit Busy presentation only; unknown/unavailable/not_configured stay neutral and text remains safe', async () => {
  const { snapshot } = await ready(), view = ui();
  for (const [status, label, state] of [['busy', 'Busy', 'busy'], ['unavailable', 'Unavailable', 'neutral'],
    ['unknown', 'unknown', 'neutral'], ['not_configured', 'not_configured', 'neutral'],
    ['toString', 'toString', 'neutral'],
    ['<img src=x onerror=alert(1)>', '<img src=x onerror=alert(1)>', 'neutral']]) {
    const supplied = structuredClone(snapshot);
    supplied.nodes.forEach(n => { n.status = status; });
    view.render(supplied).forEach(row => check(row, label, state));
  }
  // Synthetic explicit busy above tests the mapping; v1 currently supplies no workload telemetry.
  assert.ok(snapshot.nodes.every(n => n.status === 'ready'));
  view.render({ schemaVersion: 'mesh-node-probes/v1', status: 'not_configured', source: 'none', nodes: [] });
  assert.equal(view.box.textContent, 'Node observation is not configured in standalone mode. No tailnet probes run.');
  view.render(null);
  assert.equal(view.box.textContent, 'Node observation unavailable. No online or offline result established.');
});

test('status CSS uses scoped theme tokens without changing the global palette', async () => {
  const css = await readFile(new URL('../public/styles.css', import.meta.url), 'utf8');
  for (const [state, token] of [['online', '--green'], ['offline', '--danger'], ['busy', '--amber'], ['stale', '--quiet']]) {
    assert.ok(css.includes(`.node-observation .node-status--${state}{color:var(${token})}`));
  }
  assert.ok(!/\.node-status--neutral\s*\{[^}]*color:/i.test(css), 'neutral status inherits the existing paragraph color');
});
