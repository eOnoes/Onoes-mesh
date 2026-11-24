import {pixelReading} from '../public/control-models.mjs';
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import vm from 'node:vm';
import { controlledProbe } from './m5-nodes-fixture.mjs';
import { createNodeProbeReader } from '../lib/node-probes.mjs';

const source = await readFile(new URL('../public/app.js', import.meta.url), 'utf8');
const renderer = source.slice(source.indexOf('function shortOllamaName('),
  source.indexOf('\nasync function refreshNodeProbes(')).replace('export function renderNodeProbes(', 'function renderNodeProbes(').trim();
assert.ok(renderer.endsWith('}'), 'load exactly the production renderer');
class Element {
  constructor(tag) { this.tagName = tag.toUpperCase(); this.children = []; this.className = ''; this.attributes = {}; }
  append(...children) { this.children.push(...children); }
  replaceChildren(...children) { this.children = children; }
  removeChild(child) { this.children.splice(this.children.indexOf(child), 1); }
  get firstElementChild() { return this.children[0]; }
  get lastElementChild() { return this.children.at(-1); }
  getAttribute(key) { return this.attributes[key]; }
  setAttribute(key, value) { this.attributes[key] = value; }
  set textContent(text) { this.children = [text]; }
  get textContent() { return this.children.map(c => typeof c === 'string' ? c : c.textContent).join(''); }
}
function ui() {
  const box = new Element('div');
  const context = vm.createContext({ pixelReading, document: { createElement: tag => new Element(tag) },
    $: () => box, tick: 0, busy: true, nodeProbeSnapshot: null, nodeProbeReceivedAt: 0 });
  vm.runInContext(`const probeTick = () => tick;
    function paragraph(parent, text) {
      const el = document.createElement('p'); el.textContent = text; parent.append(el); return el;
    }
    ${renderer}`, context);
  return { box, context, probes(...args) { return this.render(...args).filter(row => row.card.getAttribute('data-node-id') !== 'tripp-pc'); }, render(snapshot, elapsed = 0) {
    context.snapshot = snapshot; context.tick = elapsed;
    vm.runInContext('renderNodeProbes(snapshot, 0)', context);
    return box.children.map(card => ({ card, line: card.children[1]?.children[0], word: card.children[1]?.children[0]?.children?.[1] }));
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
  view.probes(initial).forEach(row=>{
    check(row,'Not checked','neutral');
    assert.match(row.line.textContent,/^Connection: Not checked$/);
    assert.doesNotMatch(row.card.textContent,/Offline|observation_expired/);
  });
  view.probes(initial,initial.limits.staleGraceMs*10).forEach(row=>check(row,'Not checked','neutral'));
  assert.equal(tx.calls.length,0);assert.equal(JSON.stringify(initial),before);
  tx.fail();const failed=await reader.refresh();
  assert.ok(failed.nodes.every(n=>n.tailscaleOnline===null));
  view.probes(failed).forEach(row=>{
    check(row,'Unavailable','neutral');
    assert.doesNotMatch(row.line.textContent,/cached status|Offline/);
  });
});
function check(row, label, state) {
  assert.equal(row.word.tagName, 'SPAN');
  assert.equal(row.word.textContent, label);
  assert.equal(row.word.className, 'node-status node-status--' + state);
  assert.equal(row.line.className, '', 'color applies to the status word only');
  assert.match(row.card.textContent, /Packet reachability: unknown · Inference readiness: unknown · Model readiness: unknown/);
}

test('fresh ready is Online; cached Online and global UI busy cannot make stale/offline green or Busy', async () => {
  const { snapshot } = await ready(), view = ui(), original = JSON.stringify(snapshot);
  view.probes(snapshot).forEach(row => check(row, 'Online', 'online'));
  view.probes(snapshot, snapshot.limits.freshMs).forEach(row => {
    check(row, 'Stale', 'stale');
    assert.match(row.line.textContent, /^Connection: Stale$/);
    assert.match(row.card.textContent, /observation_expired/);
  });
  view.probes(snapshot, snapshot.limits.staleGraceMs).forEach(row => check(row, 'Check expired', 'stale'));
  assert.equal(JSON.stringify(snapshot), original, 'renderer never changes cached fields, timestamps or provenance');
});

test('real controlled offline versus unavailable reads retain distinct wording and neutral cached status', async () => {
  const { tx, reader, snapshot } = await ready(), view = ui();
  tx.offline(); tx.advance(snapshot.limits.staleGraceMs);
  view.probes(await reader.refresh()).forEach(row => check(row, 'Offline', 'offline'));
  tx.fail();
  view.probes(await reader.refresh()).forEach(row => {
    check(row, 'Offline', 'neutral');
    assert.equal(row.line.textContent, 'Last known connection: Offline');
  });
  for (const status of ['ready', 'stale', 'offline', 'busy', 'unavailable', 'unknown', 'not_configured']) {
    const cached = structuredClone(snapshot);
    cached.nodes.forEach(n => { n.status = status; n.observationAvailability = 'unavailable'; });
    view.probes(cached).forEach(row => {
      assert.equal(row.word.className, 'node-status node-status--neutral');
      assert.match(row.line.textContent, /^Last known connection: /);
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
    view.probes(supplied).forEach(row => check(row, label, state));
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

test('the rebuilt PC never inherits the former laptop identity, connection or sensors', async () => {
  const {snapshot} = await ready(), view = ui(), laptop = snapshot.nodes[1];
  laptop.hardwareObservedAt = snapshot.observedAt;
  laptop.hardware = {ramPct:22,cpuPct:0,gpuPct:5,gpuTempC:39,cpuTempC:null};
  for (const elapsed of [0, 30001]) {
    const card = view.render(snapshot,elapsed)[1].card;
    assert.equal(card.getAttribute('data-node-id'),'tripp-pc');
    assert.match(card.textContent,/Ollama: Status unavailable/);
    assert.match(card.textContent,/TEMP.*LAN · Status unavailable/);
    assert.match(card.textContent,/Temperature unavailable/);
    for (const old of [laptop.dnsName,laptop.tailscaleIp,'Online','Offline','39 °C','ChatGPT','Claude'])
      assert.ok(!card.textContent.includes(old));
  }
});

test('TEMP shows independent CPU and GPU readings only while the desktop observation is fresh', async () => {
  const {snapshot} = await ready(), view = ui();
  snapshot.trippDesktop = {source:'lan_ssh',state:'online',ageMs:1000,cpuTempC:51,gpuTempC:null,ollamaModels:['demo:small'],strataHealth:'ready'};
  const card = () => view.render(snapshot)[1].card;
  assert.match(card().textContent,/LAN · OnlineCPU51 °CGPUTemperature unavailable/);
  assert.match(card().textContent,/Ollama: demo:small/);
  assert.match(card().textContent,/Strata IK2: Ready · Model unverified/);
  assert.match(view.render(snapshot,28999)[1].card.textContent,/LAN · Online/);
  const expired = view.render(snapshot,29000)[1].card.textContent;
  assert.match(expired,/LAN · Check expired\. Tap Check machine status to refresh\./);
  assert.match(expired,/Strata IK2: Status unavailable/);
  assert.doesNotMatch(expired,/51 °C|demo:small/);
  delete snapshot.trippDesktop.source;
  assert.doesNotMatch(card().textContent,/Check expired|51 °C|demo:small/);
  snapshot.trippDesktop = {source:'lan_ssh',state:'expired'};
  assert.match(card().textContent,/LAN · Check expired\. Tap Check machine status to refresh\./);
  assert.doesNotMatch(card().textContent,/51 °C|demo:small/);
  snapshot.trippDesktop = {source:'lan_ssh',state:'offline',ageMs:0,cpuTempC:51};
  assert.match(card().textContent,/LAN · OfflineCPUTemperature unavailable/);
});

test('three-machine view keeps Echo and Tripp visible when the AI box is unavailable', async () => {
  const {snapshot} = await ready(), view = ui();
  const box = {...snapshot.nodes[1],id:'ai-box',label:'AI box',dnsName:'test-box.tail8c4a75.ts.net',
    tailscaleIp:'100.64.0.23',observationAvailability:'unavailable',tailscaleOnline:null,lastSuccessAt:null};
  const rows = view.render({...snapshot,nodes:[...snapshot.nodes,box]});
  assert.deepEqual(rows.map(row => row.card.children[0].textContent), ["Echo's PC","Tripp's PC",'AI box']);
  check(rows[0],'Online','online'); check(rows[2],'Unavailable','neutral');
  assert.match(rows[1].card.textContent,/Ollama: Status unavailable/);
  assert.match(rows[2].card.textContent,/Local model: Unknown/);
  for (const other of [rows[0],rows[2]]) assert.doesNotMatch(other.card.textContent,/Hermes|ChatGPT|Claude/);
  assert.doesNotMatch(rows[2].card.textContent,/Tripp|Echo/);
  view.render({...snapshot,configurationIssue:'ai_box_identity_invalid'});
  assert.match(view.box.textContent,/Check the AI box name and address/);
});

test('refresh keeps each machine disclosure intact and updates its readings', async () => {
  const {snapshot} = await ready(), view = ui();
  const card = view.render(snapshot)[0].card;
  const [title, readings, details] = card.children;
  assert.equal(title.textContent, "Echo's PC");
  assert.equal(details.tagName, 'DETAILS');
  assert.equal(details.children[0].textContent, 'Connection details');
  assert.match(details.textContent, /Last probe:/);
  assert.doesNotMatch(readings.textContent, /Last probe:|reachability|tail8c4a75/);
  details.open = true;
  const updated = view.render(snapshot, snapshot.limits.freshMs)[0].card;
  assert.equal(updated.children[2], details);
  assert.equal(details.open, true);
  assert.match(readings.textContent, /Connection: Stale/);
  assert.match(details.textContent, /observation_expired/);
});
