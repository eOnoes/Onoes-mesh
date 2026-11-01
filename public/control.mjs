// Control tab: what this PC is doing.
//
// Reads /inference/summary, Mesh's live collector: Strata's API, nvidia-smi, the OS and the
// other local model services in one request. Nothing here is a snapshot from disk.
//
// Thresholds (chosen, not inherited): utilisation meters go amber at 70% and red at 90%;
// temperature goes amber at 70 C and red at 85 C.
const root = document.getElementById('ctl-root');
const loading = document.getElementById('ctl-loading');
const machineSlot = document.getElementById('machine-tabs');
const CONTROL_TAB = 'tab-control';

const LEVELS = { warn: 70, max: 90 };
const TEMP_LEVELS = { warn: 70, max: 85 };

let view = 'overview';
let data = null;

function level(pct, table = LEVELS) {
  if (pct === null || pct === undefined) return null;
  if (pct >= table.max) return 'max';
  if (pct >= table.warn) return 'warn';
  return 'ok';
}

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function section(title, wide = false) {
  const wrap = el('div', wide ? 'ctl-section is-wide' : 'ctl-section');
  wrap.append(el('h2', null, title));
  return wrap;
}

function row(key, value, note) {
  const line = el('div', 'ctl-row');
  line.append(el('span', 'ctl-k', key), el('span', 'ctl-v', value === null || value === undefined || value === '' ? 'not reported' : String(value)));
  if (note) line.append(el('span', 'ctl-note', String(note)));
  return line;
}

function meter(label, pct, text, table = LEVELS) {
  const wrap = el('div', 'ctl-meter');
  wrap.append(el('span', 'ctl-k', label));
  const bar = el('div', 'ctl-bar');
  const fill = el('i');
  fill.style.width = `${Math.max(0, Math.min(100, pct ?? 0))}%`;
  bar.append(fill);
  const lv = level(pct, table);
  if (lv && lv !== 'ok') bar.dataset.level = lv;
  wrap.append(bar);
  const num = el('span', 'ctl-num', text);
  if (lv && lv !== 'ok') num.dataset.level = lv;
  wrap.append(num);
  return wrap;
}

function hours(seconds) {
  if (!Number.isFinite(seconds)) return null;
  const days = Math.floor(seconds / 86400);
  const rest = Math.round((seconds % 86400) / 3600);
  return days > 0 ? `${days}d ${rest}h` : `${rest}h`;
}

function engineSection(engine) {
  const s = section('engine');
  if (!engine || !engine.name) {
    s.append(row('engine', 'none running'));
    s.append(el('p', 'fine ctl-muted', 'No inference server answered on 18090-18095, 8098 or 60409.'));
    return s;
  }
  s.append(row('engine', engine.name, engine.port ? `:${engine.port}` : null));
  s.append(row('model', engine.modelShort || engine.modelAlias));
  s.append(row('context', engine.contextMax));
  s.append(row('state', engine.state === 'busy' ? 'generating' : (engine.state ?? 'unknown')));
  if (engine.buildInfo) s.append(row('build', engine.buildInfo));
  return s;
}

function gpuSection(gpu) {
  const s = section('gpu');
  if (!gpu || !gpu.name) {
    s.append(row('card', 'nvidia-smi reported nothing'));
    return s;
  }
  s.append(row('card', gpu.name));
  s.append(meter('vram', gpu.vramPct, `${gpu.vramUsedMiB} / ${gpu.vramTotalMiB} MiB`));
  s.append(meter('utilisation', gpu.utilPct, `${gpu.utilPct}%`));
  s.append(meter('power', gpu.powerLimitW ? (100 * gpu.powerW) / gpu.powerLimitW : null,
    `${gpu.powerW} / ${gpu.powerLimitW} W`));
  s.append(meter('temperature', gpu.tempC, `${gpu.tempC} \u00b0C`, TEMP_LEVELS));
  if (gpu.fanPct !== null && gpu.fanPct !== undefined) s.append(meter('fan', gpu.fanPct, `${gpu.fanPct}%`));
  if (gpu.clockMHz) s.append(row('core clock', `${gpu.clockMHz} MHz`));
  if (gpu.memClockMHz) s.append(row('mem clock', `${gpu.memClockMHz} MHz`));
  return s;
}

function systemSection(system, ram) {
  const s = section('system');
  if (!system) {
    s.append(row('os', 'not reported'));
    return s;
  }
  s.append(row('cpu', (system.cpuName || '').trim() || null));
  s.append(meter('cpu load', system.cpuLoadPct, `${system.cpuLoadPct ?? '\u2014'}%`));
  s.append(row('cores', `${system.cpuCores}c / ${system.cpuThreads}t`));
  s.append(meter('memory', ram?.usedPct, `${ram?.usedGB ?? '\u2014'} / ${ram?.totalGB ?? '\u2014'} GB`));
  s.append(row('uptime', hours(system.uptimeSec)));
  s.append(row('os', `${system.os || ''} ${system.osVersion || ''}`.trim() || null));
  s.append(row('node', system.node));
  return s;
}

function diskSection(disks) {
  const s = section('storage');
  if (!disks || !disks.length) {
    s.append(row('disks', 'not reported'));
    return s;
  }
  for (const disk of disks) {
    s.append(meter(disk.name, disk.usedPct, `${disk.usedGB} / ${disk.totalGB} GB`));
  }
  return s;
}

function servicesSection(services) {
  const s = section('services');
  for (const service of services || []) {
    const line = el('div', 'ctl-svc');
    line.append(el('span', 'ctl-k', service.id));
    const up = el('span', 'ctl-up', service.reachable ? 'up' : 'down');
    up.dataset.state = service.reachable ? 'ok' : 'off';
    line.append(up);
    line.append(el('span', 'ctl-note', service.detail || service.base || ''));
    s.append(line);
  }
  return s;
}

function modelsSection(services) {
  const s = section('models', true);
  const loaded = [];
  for (const service of services || []) {
    for (const model of service.models || []) {
      loaded.push({ service: service.id, name: model.name, vramGB: model.vramGB });
    }
  }
  if (!loaded.length) {
    s.append(row('resident', 'none'));
    return s;
  }
  for (const model of loaded) {
    s.append(row(model.service, model.name, model.vramGB ? `${model.vramGB} GB VRAM` : null));
  }
  return s;
}

function hintsSection(hints) {
  const s = section('notes', true);
  if (!hints || !hints.length) {
    s.append(el('p', 'fine ctl-muted', 'Nothing needs attention.'));
    return s;
  }
  for (const hint of hints) s.append(el('p', 'ctl-hint', hint));
  return s;
}

function render() {
  if (!root) return;
  root.replaceChildren();
  if (!data) {
    root.append(el('p', 'fine', 'No telemetry yet. /inference/summary did not answer.'));
    return;
  }

  const head = el('div', 'ctl-head');
  head.append(el('span', 'eyebrow', data.host || 'this PC'));
  const when = data.generatedAt ? new Date(data.generatedAt) : null;
  head.append(el('span', 'ctl-updated', when ? `updated ${when.toLocaleTimeString()}` : 'unknown age'));
  root.append(head);

  const grid = el('div', 'ctl-grid');
  const engine = data.engine;
  const gpu = data.gpu;
  const ram = data.ram;

  if (view === 'overview') {
    grid.append(engineSection(engine));
    grid.append(gpuSection(gpu));
    grid.append(systemSection(data.system, ram));
    grid.append(diskSection(data.disks));
    grid.append(servicesSection(data.services));
    grid.append(modelsSection(data.services));
    grid.append(hintsSection(data.hints));
  }

  if (view === 'throughput') {
    const t = data.throughput || {};
    const c = data.cost || {};
    const s = section('throughput');
    s.append(row('tps', t.tps));
    s.append(row('pps', t.pps));
    s.append(row('context used', t.contextUsed, t.contextPct ? `${t.contextPct}%` : null));
    if (!t.tps) s.append(el('p', 'fine ctl-muted', t.reason || 'no measurement available'));
    grid.append(s);

    const cs = section('cost');
    cs.append(row('simulated', c.simulatedUsd === null || c.simulatedUsd === undefined ? null : `$${c.simulatedUsd}`));
    if (c.reason) cs.append(el('p', 'fine ctl-muted', c.reason));
    grid.append(cs);

    grid.append(engineSection(engine));
    grid.append(gpuSection(gpu));
  }

  if (view === 'logs') {
    const s = section('snapshot', true);
    const pre = el('pre', 'ctl-v');
    pre.style.whiteSpace = 'pre-wrap';
    pre.textContent = JSON.stringify(data, null, 2);
    s.append(pre);
    grid.append(s);
  }

  root.append(grid);
}

function setView(next) {
  view = next;
  for (const button of document.querySelectorAll('[data-ctl-view]')) {
    button.setAttribute('aria-current', String(button.dataset.ctlView === next));
  }
  render();
}

for (const button of document.querySelectorAll('[data-ctl-view]')) {
  button.addEventListener('click', () => setView(button.dataset.ctlView));
}
if (loading) loading.remove();

// Live telemetry, polled. The server memoises briefly, so several tabs cost one collection.
const MACHINE_SLOT = document.getElementById('machine-tabs');

async function load() {
  try {
    const response = await fetch('/inference/summary', { cache: 'no-store' });
    data = response.ok ? await response.json() : null;
  } catch {
    data = null;
  }
  if (MACHINE_SLOT && data) {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'tab';
    button.setAttribute('aria-pressed', 'true');
    button.textContent = data.host || 'this PC';
    MACHINE_SLOT.replaceChildren(button);
  }
  render();
}

load();
setInterval(load, 5000);

// The machine strip only belongs on the Control tab, like agent pills belong to Relay.
const controlTab = document.getElementById('tab-control');
if (controlTab && MACHINE_SLOT) {
  const sync = () => { MACHINE_SLOT.hidden = controlTab.getAttribute('aria-selected') !== 'true'; };
  new MutationObserver(sync).observe(controlTab, { attributes: true, attributeFilter: ['aria-selected'] });
  sync();
}
