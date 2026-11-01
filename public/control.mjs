// Control tab: Echo's PC inference readout.
//
// Reads public/inference.json, a snapshot written by tools/sync-inference.ps1 from the
// Strata API and nvidia-smi. Mesh's server only serves static files, so there is no live
// polling endpoint - re-run the collector to refresh.
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

function section(title) {
  const wrap = el('div', 'ctl-section');
  wrap.append(el('h2', null, title));
  return wrap;
}

function row(label, value, note) {
  const wrap = el('div', 'ctl-row');
  wrap.append(el('span', 'ctl-k', label));
  const v = el('span', 'ctl-v', value === null || value === undefined ? '—' : String(value));
  if (note) v.append(el('small', null, note));
  wrap.append(v);
  return wrap;
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

function render() {
  if (!root) return;
  root.replaceChildren();
  if (!data) {
    root.append(el('p', 'fine', 'No telemetry snapshot yet. Run tools/sync-inference.ps1.'));
    return;
  }

  const head = el('div', 'ctl-head');
  head.append(el('span', 'eyebrow', data.host || 'this PC'));
  const when = data.generatedAt ? new Date(data.generatedAt) : null;
  head.append(el('span', 'ctl-updated', when ? `updated ${when.toLocaleTimeString()}` : 'unknown age'));
  root.append(head);

  const engine = data.engine || {};
  const gpu = data.gpu || {};
  const ram = data.ram || {};

  if (view === 'overview' || view === 'throughput') {
    const s = section('engine');
    s.append(row('engine', engine.name, engine.transport === 'http' ? `:${engine.port}` : 'stdio'));
    s.append(row('model', engine.modelShort || engine.modelAlias, engine.modelAlias));
    s.append(row('context', engine.contextMax, engine.contextLength ? `of ${engine.contextLength}` : null));
    s.append(row('state', engine.busy === true ? 'generating' : engine.busy === false ? 'idle' : 'unknown',
      engine.loaded === false ? 'not loaded' : null));
    if (engine.buildInfo) s.append(row('build', engine.buildInfo));
    root.append(s);
  }

  if (view === 'overview') {
    const s = section('resources');
    s.append(meter('gpu vram', gpu.vramPct, `${gpu.vramUsedMiB ?? '—'} / ${gpu.vramTotalMiB ?? '—'} MiB`));
    s.append(meter('system ram', ram.usedPct, `${ram.usedGB ?? '—'} / ${ram.totalGB ?? '—'} GB`));
    for (const disk of data.disks || []) {
      s.append(meter(disk.name, disk.usedPct, `${disk.usedGB} / ${disk.totalGB} GB`));
    }
    root.append(s);

    const g = section('gpu');
    g.append(meter('utilisation', gpu.utilPct, `${gpu.utilPct ?? '—'}%`));
    g.append(meter('power', gpu.powerLimitW ? (100 * gpu.powerW) / gpu.powerLimitW : null,
      `${gpu.powerW ?? '—'} / ${gpu.powerLimitW ?? '—'} W`));
    g.append(meter('temperature', gpu.tempC, `${gpu.tempC ?? '—'} \u00b0C`, TEMP_LEVELS));
    root.append(g);
  }

  if (view === 'throughput') {
    const t = data.throughput || {};
    const c = data.cost || {};
    const s = section('throughput');
    s.append(row('tps', t.tps));
    s.append(row('pps', t.pps));
    s.append(row('context used', t.contextUsed, t.contextPct ? `${t.contextPct}%` : null));
    if (!t.tps) s.append(el('p', 'fine ctl-muted', t.reason || 'no measurement available'));
    root.append(s);

    const cs = section('cost');
    cs.append(row('simulated', c.simulatedUsd === null || c.simulatedUsd === undefined
      ? null : `$${c.simulatedUsd}`));
    if (c.reason) cs.append(el('p', 'fine ctl-muted', c.reason));
    root.append(cs);
  }

  if (view === 'logs') {
    const s = section('snapshot');
    const pre = el('pre', 'ctl-v');
    pre.style.whiteSpace = 'pre-wrap';
    pre.textContent = JSON.stringify(data, null, 2);
    s.append(pre);
    root.append(s);
  }
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

fetch('/inference.json', { cache: 'no-store' })
  .then((r) => (r.ok ? r.json() : null))
  .then((json) => {
    data = json;
    // machine selector: one machine today, but the shape is already a list
    if (machineSlot && data) {
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'tab';
      button.setAttribute('aria-pressed', 'true');
      button.textContent = data.host || 'this PC';
      machineSlot.replaceChildren(button);
    }
    render();
  })
  .catch(() => render());

// The machine strip only belongs on the Control tab, like agent pills belong to Relay.
const controlTab = document.getElementById(CONTROL_TAB);
if (controlTab && machineSlot) {
  const sync = () => { machineSlot.hidden = controlTab.getAttribute('aria-selected') !== 'true'; };
  new MutationObserver(sync).observe(controlTab, { attributes: true, attributeFilter: ['aria-selected'] });
  sync();
}
