let data = {headers: [], cards: []};
const ui = {section: 'overview', filter: 'open', openHeader: 'app', openCard: 'shape', editing: null, showFinished: true, showTrash: false};
const $ = id => document.getElementById(id);
let busy = false;
function toast(text) {
  placeToast();
  $('toast').hidden = false;
  $('toast').textContent = text;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => { $('toast').hidden = true; }, 4000);
}
function placeToast() {
  const el = $('toast');
  if (document.body.classList.contains('on-relay')) {
    const dock = document.querySelector('#page-relay .relay-dock');
    const anchor = $('slash-menu');
    if (dock && anchor && el.parentElement !== dock) dock.insertBefore(el, anchor);
    return;
  }
  const home = document.querySelector('.column');
  if (home && el.parentElement !== home) home.append(el);
}
async function request(path, body) {
  const response = await fetch(path, body === undefined ? {} : {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)});
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || 'Could not save.');
  return result;
}
function escapeHtml(s) { return String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;', "'":'&#39;'}[c])); }
function visible(card) {
  if (card.sample) return false;
  const q = $('search').value.trim().toLowerCase();
  if (q && !(card.title + ' ' + card.note).toLowerCase().includes(q)) return false;
  if (ui.filter === 'trash') return card.state === 'trash';
  if (card.state === 'trash') return ui.showTrash;
  return true;
}
function cardHtml(card) {
  const shown = ui.openCard === card.id;
  const held = !card.sample && (card.state === 'ready' || card.state === 'paused');
  const holder = held ? (card.holder || 'Echo') : '';
  if (ui.editing === card.id && !card.sample) {
    return `<article class="glass todo-card editing"><form class="card-edit" action="#"><input id="edit-title" maxlength="40" aria-label="Card title" value="${escapeHtml(card.title)}" autocomplete="off" required><textarea id="edit-note" aria-label="Card details" maxlength="1000" rows="2">${escapeHtml(card.note || '')}</textarea><div class="actions"><button class="act" type="button" data-save="${card.id}">Save</button><button class="act" type="button" data-cancel="${card.id}">Cancel</button></div></form></article>`;
  }
  const slot = card.sample
    ? `<button class="act" type="button" disabled>play</button>`
    : held
      ? `<button class="act" type="button" data-pause="${card.id}"${card.state === 'ready' ? '' : ' disabled'}>pause</button>`
      : card.state === 'idle'
        ? `<button class="act" type="button" data-play="${card.id}">play</button>`
        : '';
  const trash = card.state === 'trash' ? `<button class="act" type="button" data-restore="${card.id}"${card.sample ? ' disabled' : ''}>recover</button>` : `<button class="act" type="button" data-trash="${card.id}"${card.sample ? ' disabled' : ''}>trash</button>`;
  const edit = card.sample ? '' : `<button class="act edit" type="button" data-edit="${card.id}" aria-label="Edit card">edit</button>`;
  const bits = [edit, slot, trash].filter(Boolean);
  const opts = `<div class="opts" aria-label="Local card controls"><span class="br">[ </span>${bits.join('<span class="sep"> - </span>')}<span class="br"> ]</span></div>`;
  const stamp = new Date(card.added).toLocaleString(undefined, {month:'short', day:'numeric', hour:'numeric', minute:'2-digit'});
  const line = card.sample ? 'fixture · sample only' : `local card · ${card.line}`;
  const badge = holder ? `<span class="tag">held by ${escapeHtml(holder)}</span>` : '';
  const extra = shown ? `<p class="note" id="note-${card.id}">${escapeHtml(card.note || card.title)}</p><div class="tag">${escapeHtml(card.who)} · ${stamp} · ${escapeHtml(line)}</div>` : `<p class="note" id="note-${card.id}" hidden>${escapeHtml(card.note || card.title)}</p>`;
  return `<article class="glass todo-card${shown ? ' open' : ''}"><div class="cardline"><h3><button class="card-title" type="button" data-card="${card.id}" aria-expanded="${shown}" aria-controls="note-${card.id}"><span class="br">[</span> ${escapeHtml(card.title)} <span class="br">]</span></button></h3></div>${extra}<div class="cardfoot">${badge}${opts}</div></article>`;
}
function render() {
  const cards = data.cards.filter(visible).sort((a,b) => new Date(b.added) - new Date(a.added));
  $('list').innerHTML = cards.length
    ? `<div class="cards">${cards.map(cardHtml).join('')}</div>`
    : `<p class="meta">${ui.filter === 'trash' ? 'Trash is empty.' : 'Nothing on the list.'}</p>`;
  document.querySelectorAll('[data-filter]').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.filter === ui.filter)));
}
async function mutate(path, body, after) {
  if (busy) return;
  busy = true;
  try { data = await request(path, body); if (after) after(); render(); }
  catch (error) { toast(error.message); }
  finally { busy = false; }
}
$('list').addEventListener('submit', e => {
  if (!e.target.classList.contains('card-edit')) return;
  e.preventDefault();
  const save = e.target.querySelector('[data-save]');
  if (save) save.click();
});
$('list').addEventListener('click', e => {
  const t = e.target.closest('button');
  if (!t || t.disabled || busy) return;
  if (t.dataset.header) { ui.openHeader = ui.openHeader === t.dataset.header ? null : t.dataset.header; ui.openCard = null; render(); return; }
  if (t.dataset.card) { ui.editing = null; ui.openCard = ui.openCard === t.dataset.card ? null : t.dataset.card; render(); return; }
  if (t.dataset.edit) { ui.editing = t.dataset.edit; ui.openCard = t.dataset.edit; render(); const input = $('edit-title'); if (input) { input.focus(); input.select(); } return; }
  if (t.dataset.cancel) { ui.editing = null; render(); return; }
  if (t.dataset.save) {
    const title = $('edit-title').value.trim();
    const note = $('edit-note').value.trim();
    if (!title) { toast('Enter a short title.'); return; }
    mutate(`/api/cards/${t.dataset.save}/edit`, {title, note}, () => { ui.editing = null; toast('Saved.'); });
    return;
  }
  for (const action of ['play','pause','trash','restore']) if (t.dataset[action]) {
    mutate(`/api/cards/${t.dataset[action]}/${action}`, {}, () => {
      if (action === 'play') toast(data.line);
      if (action === 'pause') toast('Paused. Card kept on disk.');
      if (action === 'trash') toast('In local trash. Recover it in config.');
    });
    break;
  }
});
function setAdd(open) {
  const onTodo = document.body.classList.contains('on-todo');
  $('add-form').hidden = !open;
  $('add-plus').hidden = open || !onTodo;
  $('add-plus').setAttribute('aria-expanded', String(open));
  if (open) $('add-title').focus();
}
$('add-plus').addEventListener('click', () => setAdd(true));
$('add-cancel').addEventListener('click', () => { $('add-form').reset(); setAdd(false); });
$('add-form').addEventListener('submit', e => {
  e.preventDefault();
  const title = $('add-title').value.trim();
  const note = $('add-note').value.trim();
  if (!title) { toast('Enter a short title.'); return; }
  mutate('/api/cards', {title,note}, () => {
    const card = data.cards[data.cards.length - 1];
    ui.openCard = card.id; ui.filter = 'open';
    $('search').value = ''; e.target.reset(); setAdd(false); openPanel(null);
    toast('Kept on the list.');
  });
});
$('search').addEventListener('input', render);
document.querySelectorAll('[data-filter]').forEach(b => b.addEventListener('click', () => {
  ui.filter = b.dataset.filter; ui.openHeader = ui.filter === 'trash' ? 'trash' : 'app'; ui.openCard = null; render();
}));
function openPanel(which) {
  if (which) setAdd(false);
  const menu = which === 'menu', settings = which === 'settings';
  $('menu').classList.toggle('open', menu); $('settings').classList.toggle('open', settings);
  $('backdrop').hidden = !(menu || settings); $('backdrop').classList.toggle('on', menu || settings);
  $('open-menu').setAttribute('aria-expanded', String(menu)); $('open-set').setAttribute('aria-expanded', String(settings));
  $('settings').inert = !settings;
  $('menu').inert = !menu && window.innerWidth < 960;
  if (settings) (ui.section === 'todo' ? $('search') : $('tog-tags')).focus();
}
$('open-menu').addEventListener('click', () => openPanel('menu'));
$('open-set').addEventListener('click', () => openPanel('settings'));
$('close-menu').addEventListener('click', () => openPanel(null));
$('close-set').addEventListener('click', () => openPanel(null));
$('backdrop').addEventListener('click', () => openPanel(null));
document.addEventListener('keydown', e => {
  if (e.key !== 'Escape') return;
  if (!$('add-form').hidden) { $('add-form').reset(); setAdd(false); return; }
  openPanel(null);
});
window.addEventListener('resize', () => { $('menu').inert = !$('menu').classList.contains('open') && window.innerWidth < 960; });
function showSection(section, focus = false) {
  const row = document.querySelector(`[data-section="${section}"]`);
  if (!row) {
    if (section !== 'todo') showSection('todo', focus);
    return;
  }
  ui.section = section;
  const todo = section === 'todo';
  document.querySelectorAll('[data-section]').forEach(b => {
    const selected = b === row;
    b.setAttribute('aria-selected', String(selected));
    if (selected) b.setAttribute('aria-current', 'page'); else b.removeAttribute('aria-current');
  });
  document.querySelectorAll('.page').forEach(page => { page.hidden = page.id !== `page-${section}`; });
  $('stage').hidden = !todo; $('pages').hidden = todo;
  $('crumb').textContent = section === 'relay' ? 'Relay/Echo' : row.dataset.label;
  document.title = `Mesh · ${row.dataset.label}`;
  $('todo-settings').hidden = !todo; $('page-settings').hidden = todo;
  $('settings-title').textContent = `${row.dataset.label} settings`;
  $('settings').setAttribute('aria-label', `${row.dataset.label} settings`);
  document.body.classList.toggle('on-todo', todo);
  document.body.classList.toggle('on-relay', section === 'relay');
  placeToast();
  setAdd(false);
  openPanel(null);
  if (section === 'overview') arriveOverview(); else stopOverviewPolling();
  if (section === 'relay') { loadHistory(); startProactive(); } else stopProactive();
  if (focus) { const heading = $('crumb').closest('h1'); heading.tabIndex = -1; heading.focus(); }
}
$('menu').addEventListener('click', e => {
  const row = e.target.closest('[data-section]'); if (!row) return;
  showSection(row.dataset.section, true);
  if (location.hash !== `#${row.dataset.section}`) location.hash = row.dataset.section;
});
window.addEventListener('hashchange', () => {
  const section = location.hash.slice(1) || 'overview';
  if (section !== ui.section) showSection(section);
});
let overviewRead = 0;
let overviewMetricsRead = 0;
let overviewTimer = null;
let overviewController = null;
function overviewDisclosure(name, open) {
  $(`overview-${name}`).hidden = !open;
  $(`overview-${name}-toggle`).setAttribute('aria-expanded', String(open));
}
for (const name of ['pc', 'more', 'holds']) {
  $(`overview-${name}-toggle`).addEventListener('click', () => {
    overviewDisclosure(name, $(`overview-${name}`).hidden);
  });
}
function overviewValue(value, suffix) {
  return typeof value === 'number' && Number.isFinite(value) ? `${value}${suffix}` : 'unavailable';
}
function overviewBytes(value) {
  return typeof value === 'number' && Number.isFinite(value)
    ? `${(value / (1024 ** 3)).toFixed(1)} GiB` : 'unavailable';
}
function overviewDrive(drive) {
  const percent = drive && drive.available && typeof drive.percent_used === 'number' && Number.isFinite(drive.percent_used)
    ? `${Math.round(drive.percent_used)}%` : 'unavailable';
  return `${drive.letter} ${percent}`;
}
function overviewLines(lines) {
  return lines.map(line => `<div class="overview-line">${escapeHtml(line)}</div>`).join('');
}
function renderOverviewMetrics(metrics = {}) {
  const cpu = metrics.cpu || {};
  const gpu = metrics.gpu && metrics.gpu.available ? (metrics.gpu.gpu || {}) : {};
  const memory = metrics.memory && metrics.memory.available ? metrics.memory : {};
  const drives = metrics.drives || [];
  $('overview-pc-metrics').innerHTML = overviewLines([
    `CPU load ${overviewValue(cpu.load_available ? cpu.load_percent : null, '%')}`,
    `GPU load ${overviewValue(gpu.utilization_gpu_percent, '%')}`,
    `RAM ${overviewValue(memory.percent_used, '%')} · ${overviewBytes(memory.used_bytes)} / ${overviewBytes(memory.total_bytes)}`,
    `VRAM ${overviewValue(gpu.vram_percent, '%')} · ${overviewBytes(gpu.vram_used_bytes)} / ${overviewBytes(gpu.vram_total_bytes)}`,
    ...['C', 'D'].map(letter => overviewDrive(drives.find(drive => drive.letter === letter) || {letter}))
  ]);
  const strata = (metrics.llm || []).find(item => item.engine === 'strata');
  const strataLine = strata ? [strata.status || 'unavailable', strata.model_id,
    strata.context == null ? null : `context ${strata.context}`, strata.version].filter(Boolean).join(' · ') : 'unavailable';
  $('overview-extra').innerHTML = overviewLines([
    'CPU temperature unavailable', 'CPU fan unavailable', 'CPU power unavailable',
    `GPU temperature ${overviewValue(gpu.temperature_c, '°C')}`,
    `GPU fan ${overviewValue(gpu.fan_percent, '%')}`,
    `GPU power ${overviewValue(gpu.power_w, ' W')}`,
    `Strata ${strataLine}`
  ]);
}
function stopOverviewPolling() {
  clearTimeout(overviewTimer);
  overviewTimer = null;
  if (overviewController) overviewController.abort();
  overviewController = null;
  overviewMetricsRead++;
  overviewRead++;
}
async function pollOverviewMetrics() {
  if (ui.section !== 'overview' || document.hidden) return;
  const read = overviewMetricsRead;
  const controller = new AbortController();
  overviewController = controller;
  try {
    const response = await fetch('/api/system/metrics', {cache: 'no-store', signal: controller.signal});
    if (!response.ok) throw new Error('PC metrics unavailable');
    const metrics = await response.json();
    if (read === overviewMetricsRead && ui.section === 'overview' && !document.hidden) renderOverviewMetrics(metrics);
  } catch (error) {
    if (read === overviewMetricsRead && ui.section === 'overview' && !document.hidden) renderOverviewMetrics();
  } finally {
    if (read === overviewMetricsRead && ui.section === 'overview' && !document.hidden) {
      overviewController = null;
      overviewTimer = setTimeout(pollOverviewMetrics, 5000);
    }
  }
}
function arriveOverview() {
  stopOverviewPolling();
  overviewDisclosure('pc', true);
  overviewDisclosure('more', false);
  overviewDisclosure('holds', false);
  renderOverviewMetrics();
  loadOverview();
  pollOverviewMetrics();
}
function overviewArticle(title, lines, tag, statusTitle = null) {
  const body = (lines || []).map(line => `<div class="overview-line">${escapeHtml(line)}</div>`).join('');
  const mark = tag ? `<span class="tag">${escapeHtml(tag)}</span>` : '';
  const status = statusTitle === null ? '' : `<button type="button" data-overview-status="${escapeHtml(statusTitle)}"><span class="br">[</span> status <span class="br">]</span></button>`;
  return `<article class="glass"><h3><span class="br">[</span> ${escapeHtml(title)} <span class="br">]</span></h3>${body}${mark}${status}</article>`;
}
$('overview-cards').addEventListener('click', event => {
  const button = event.target.closest('[data-overview-status]');
  if (!button) return;
  const draft = $('draft');
  if (draft.value) { toast('The composer has text.'); return; }
  draft.value = ('Status on: ' + button.dataset.overviewStatus).slice(0, BOX_CAP);
  showSection('relay');
  if (location.hash !== '#relay') location.hash = 'relay';
  fitDraft();
});
async function loadOverview() {
  const read = ++overviewRead;
  const box = $('overview-cards');
  if (!box) return;
  try {
    const [handoff, state] = await Promise.all([request('/api/handoff'), request('/api/state')]);
    if (read !== overviewRead) return;
    const held = handoff.state === 'ready' || handoff.state === 'paused';
    const heldTitle = held ? (handoff.title || 'Untitled') : 'Nothing held.';
    const heldTag = held ? (handoff.state === 'paused' ? 'paused · held by Echo' : 'held by Echo') : 'local read';
    const open = (state.cards || []).filter(card => card && !card.sample && card.state !== 'trash' && card.state !== 'finished');
    const heldCard = held ? open.find(card => card.id === handoff.id) : null;
    const heldLine = heldCard && heldCard.line ? heldCard.line : '';
    const others = open.filter(card => !heldCard || card.id !== heldCard.id)
      .sort((a, b) => new Date(b.added) - new Date(a.added));
    const nowLines = held ? (heldLine ? [heldLine] : []) : ['Nothing is in the hold file.'];
    box.innerHTML = overviewArticle(heldTitle, nowLines, heldTag, held ? heldTitle : null)
      + others.map(card => overviewArticle(card.title, [card.line || card.state || 'open'], 'open', card.title)).join('');
  } catch (error) {
    if (read !== overviewRead) return;
    box.innerHTML = overviewArticle('Could not read the list.', [], 'local read');
    toast(error.message);
  }
}
window.addEventListener('focus', () => {
  if (ui.section === 'overview' && !document.hidden) arriveOverview();
});
document.addEventListener('visibilitychange', () => {
  if (document.hidden) { stopOverviewPolling(); return; }
  if (ui.section === 'overview') arriveOverview();
});
let standingGoal = {status: 'none', goal: ''};
function showGoal(goal) {
  standingGoal = goal && goal.status && goal.status !== 'none' ? goal : {status: 'none', goal: ''};
  const bar = $('goal-bar');
  if (standingGoal.status === 'none') {
    bar.hidden = true;
    setGoalOpen(false);
    return;
  }
  bar.hidden = false;
  bar.classList.remove('is-pursued', 'is-decision', 'is-stopped');
  const stopped = standingGoal.status === 'paused' || standingGoal.last_verdict === 'blocked';
  const decision = !stopped && (standingGoal.waiting || standingGoal.last_verdict === 'wait');
  if (stopped) bar.classList.add('is-stopped');
  else if (decision) bar.classList.add('is-decision');
  $('goal-state').textContent = standingGoal.status === 'paused' ? 'Goal paused' : (decision ? 'Goal stalled' : 'Goal active');
  $('goal-text').textContent = standingGoal.goal || '';
  $('goal-pause').textContent = standingGoal.status === 'paused' ? 'resume' : 'pause';
}
function setGoalOpen(open) {
  $('goal-bar').classList.toggle('is-open', open);
  const text = $('goal-text');
  text.style.gridColumn = open ? '1 / -1' : '';
  text.style.gridRow = open ? '2' : '';
  text.style.whiteSpace = open ? 'normal' : '';
  text.style.height = open ? 'auto' : '';
  text.style.lineHeight = open ? '1.45' : '';
  text.setAttribute('aria-expanded', String(open));
  text.setAttribute('aria-label', open ? 'Hide the rest of the goal' : 'Show the whole goal');
}
function fitDraft() {
  const box = $('draft');
  const actions = document.querySelector('.relay-actions');
  const floor = Math.round(actions.getBoundingClientRect().height);
  box.style.height = floor + 'px';
  box.style.maxHeight = floor + 'px';
  box.style.overflowY = box.scrollHeight > floor + 1 ? 'auto' : 'hidden';
}
function armGoal(on) {
  $('goal-arm').setAttribute('aria-pressed', String(on));
  $('draft').placeholder = on ? 'goal' : 'message';
}
async function loadGoal() {
  try { showGoal(await request('/api/relay/goal')); }
  catch (error) { $('goal-state').textContent = 'Goal could not be read.'; toast(error.message); }
}
$('goal-arm').addEventListener('click', () => {
  armGoal($('goal-arm').getAttribute('aria-pressed') !== 'true');
  $('draft').focus();
});
$('goal-text').addEventListener('click', e => {
  e.stopPropagation();
  setGoalOpen(!$('goal-bar').classList.contains('is-open'));
});
document.addEventListener('click', () => {
  if ($('goal-bar').classList.contains('is-open')) setGoalOpen(false);
});
$('goal-pause').addEventListener('click', async () => {
  const action = standingGoal.status === 'paused' ? 'resume' : 'pause';
  try { showGoal(await request('/api/relay/goal', {action, text: ''})); toast(action === 'pause' ? 'Goal paused.' : 'Goal resumed.'); }
  catch (error) { toast(error.message); }
});
$('goal-edit').addEventListener('click', () => {
  if (!standingGoal.goal) return;
  $('draft').value = standingGoal.goal;
  fitDraft();
  armGoal(true);
  $('draft').focus();
  toast('Edit it, then send.');
});
$('goal-trash').addEventListener('click', async () => {
  try { showGoal(await request('/api/relay/goal', {action: 'clear', text: ''})); armGoal(false); toast('Goal cleared.'); }
  catch (error) { toast(error.message); }
});
function paintDoc(text) {
  return text.split('\n').map((line, i) => {
    const safe = line.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    const painted = safe.replace(/(\d+|[^\w\s]+)/g, '<span class="tok">$1</span>');
    return `<span class="${i % 2 ? 'quiet' : 'bright'}">${painted || ' '}</span>`;
  }).join('\n');
}

function placeSlot(box) {
  const head = document.querySelector('.head').getBoundingClientRect();
  const dock = document.querySelector('.relay-dock').getBoundingClientRect();
  box.style.top = Math.round(head.bottom + 8) + 'px';
  box.style.left = '12px';
  box.style.right = '12px';
  box.style.bottom = Math.round(window.innerHeight - dock.top + 8) + 'px';
}
function placeReader() { placeSlot($('reader')); }

let openText = '';
function openReader(text) {
  openText = typeof text === 'string' ? text : '';
  closePhoto();
  placeReader();
  $('reader-name').textContent = 'paper';
  $('reader-stage').innerHTML = paintDoc(openText);
  $('reader').hidden = false;
  fitReader();
}

function closeReader() {
  $('reader').hidden = true;
}

function jumpLatest() {
  $('thread').scrollTop = $('thread').scrollHeight;
}

function onPrompt() {
  if (!$('reader').hidden) closeReader();
  if (!$('photo').hidden) closePhoto();
  jumpLatest();
}

let readerScale = 1;
let readerX = 0;
let readerY = 0;
const readerPointers = new Map();
function paintReader() {
  $('reader-stage').style.transform = `translate(${readerX}px, ${readerY}px) scale(${readerScale})`;
}
function clampReader() {
  const view = $('reader-body');
  const stage = $('reader-stage');
  const minX = Math.min(0, view.clientWidth - stage.offsetWidth * readerScale);
  const minY = Math.min(0, view.clientHeight - stage.offsetHeight * readerScale);
  readerX = Math.min(0, Math.max(minX, readerX));
  readerY = Math.min(0, Math.max(minY, readerY));
}
function fitReader() {
  readerScale = 1;
  readerX = 0;
  readerY = 0;
  paintReader();
}
let readerTap = 0;
let readerMoved = false;
const readerBody = $('reader-body');
readerBody.addEventListener('pointerdown', event => {
  if (readerPointers.size === 0) readerMoved = false;
  readerBody.setPointerCapture(event.pointerId);
  readerPointers.set(event.pointerId, {x: event.clientX, y: event.clientY, sx: event.clientX, sy: event.clientY});
});
readerBody.addEventListener('pointermove', event => {
  const prev = readerPointers.get(event.pointerId);
  if (!prev) return;
  if (Math.hypot(event.clientX - prev.sx, event.clientY - prev.sy) > 10) readerMoved = true;
  if (readerPointers.size < 2) {
    readerX += event.clientX - prev.x;
    readerY += event.clientY - prev.y;
  } else {
    const other = [...readerPointers.entries()].find(([id]) => id !== event.pointerId)[1];
    const before = Math.hypot(prev.x - other.x, prev.y - other.y) || 1;
    const after = Math.hypot(event.clientX - other.x, event.clientY - other.y) || 1;
    const rect = readerBody.getBoundingClientRect();
    const cx = ((event.clientX + other.x) / 2) - rect.left;
    const cy = ((event.clientY + other.y) / 2) - rect.top;
    const next = Math.min(4, Math.max(1, readerScale * (after / before)));
    const ratio = next / readerScale;
    readerX = cx - (cx - readerX) * ratio;
    readerY = cy - (cy - readerY) * ratio;
    readerScale = next;
  }
  readerPointers.set(event.pointerId, {x: event.clientX, y: event.clientY, sx: prev.sx, sy: prev.sy});
  clampReader();
  paintReader();
});
function dropReaderPointer(event) {
  const alone = readerPointers.size <= 1;
  readerPointers.delete(event.pointerId);
  if (!alone || readerMoved) return;
  const now = Date.now();
  if (now - readerTap < 320) {
    readerTap = 0;
    fitReader();
    return;
  }
  readerTap = now;
}
readerBody.addEventListener('pointerup', dropReaderPointer);
readerBody.addEventListener('pointercancel', dropReaderPointer);
readerBody.addEventListener('wheel', event => {
  event.preventDefault();
  const next = Math.min(4, Math.max(1, readerScale * (event.deltaY < 0 ? 1.12 : 0.9)));
  const ratio = next / readerScale;
  const rect = readerBody.getBoundingClientRect();
  const cx = event.clientX - rect.left;
  const cy = event.clientY - rect.top;
  readerX = cx - (cx - readerX) * ratio;
  readerY = cy - (cy - readerY) * ratio;
  readerScale = next;
  clampReader();
  paintReader();
}, {passive: false});
$('reader-close').addEventListener('click', closeReader);
$('reader-copy').addEventListener('click', copyDoc);
document.addEventListener('click', e => {
  if (!$('reader').hidden && !e.target.closest('#reader')) closeReader();
  if (!$('photo').hidden && !e.target.closest('#photo')) closePhoto();
});
document.addEventListener('keydown', e => { if (e.key === 'Escape') { closeReader(); closePhoto(); $('slash-menu').hidden = true; clearPick(); } });
$('draft').addEventListener('focus', onPrompt);
addEventListener('resize', () => {
  if (!$('reader').hidden) placeReader();
  if (!$('photo').hidden) placeSlot($('photo'));
});

function pinKeyboard() {
  const vv = window.visualViewport;
  const overlap = vv ? Math.max(0, window.innerHeight - vv.height - vv.offsetTop) : 0;
  document.documentElement.style.setProperty('--kb', overlap + 'px');
  if (!$('reader').hidden) placeReader();
  if (!$('photo').hidden) placeSlot($('photo'));
}
if (window.visualViewport) {
  visualViewport.addEventListener('resize', pinKeyboard);
  visualViewport.addEventListener('scroll', pinKeyboard);
  pinKeyboard();
}

let photoScale = 1;
let photoWidth = 112;
let photoHeight = 84;
let photoX = 0;
let photoY = 0;
const photoPointers = new Map();
function paintPhoto() {
  $('photo-stage').style.transform = `translate(calc(-50% + ${photoX}px), calc(-50% + ${photoY}px)) scale(${photoScale})`;
}
function clampPhoto() {
  const view = $('photo-view');
  const maxX = Math.max(40, (photoWidth * photoScale - view.clientWidth) / 2 + 40);
  const maxY = Math.max(40, (photoHeight * photoScale - view.clientHeight) / 2 + 40);
  photoX = Math.min(maxX, Math.max(-maxX, photoX));
  photoY = Math.min(maxY, Math.max(-maxY, photoY));
}
let photoFitScale = 1;
function zoomPhoto(factor) {
  photoScale = Math.min(photoFitScale * 8, Math.max(photoFitScale, photoScale * factor));
  clampPhoto();
  paintPhoto();
}
function fitPhoto() {
  const view = $('photo-view');
  photoScale = Math.max(0.01, Math.min(view.clientWidth / photoWidth, view.clientHeight / photoHeight));
  photoFitScale = photoScale;
  photoX = 0;
  photoY = 0;
  paintPhoto();
}
function openPhoto(node) {
  closeReader();
  const image = node.cloneNode(true);
  const stage = $('photo-stage');
  stage.replaceChildren(image);
  photoWidth = 112;
  photoHeight = 84;
  const sizeImage = () => {
    if (stage.firstChild && stage.firstChild !== image) return;
    if (image.naturalWidth && image.naturalHeight) {
      const longest = Math.max(image.naturalWidth, image.naturalHeight);
      photoWidth = 112 * image.naturalWidth / longest;
      photoHeight = 112 * image.naturalHeight / longest;
    }
    stage.style.width = photoWidth + 'px';
    stage.style.height = photoHeight + 'px';
    fitPhoto();
  };
  image.style.width = '100%';
  image.style.height = '100%';
  image.style.objectFit = 'contain';
  if (image.tagName === 'IMG') image.onload = sizeImage;
  placeSlot($('photo'));
  $('photo').hidden = false;
  sizeImage();
}
function closePhoto() {
  $('photo').hidden = true;
  photoPointers.clear();
}
$('photo-close').addEventListener('click', event => { event.stopPropagation(); closePhoto(); });
const photoView = $('photo-view');
let photoTap = 0;
let photoMoved = false;
photoView.addEventListener('pointerdown', event => {
  if (photoPointers.size === 0) photoMoved = false;
  photoView.setPointerCapture(event.pointerId);
  photoPointers.set(event.pointerId, {x: event.clientX, y: event.clientY, sx: event.clientX, sy: event.clientY});
});
photoView.addEventListener('pointermove', event => {
  const prev = photoPointers.get(event.pointerId);
  if (!prev) return;
  if (Math.hypot(event.clientX - prev.sx, event.clientY - prev.sy) > 10) photoMoved = true;
  if (photoPointers.size < 2) {
    photoX += event.clientX - prev.x;
    photoY += event.clientY - prev.y;
  } else {
    const other = [...photoPointers.entries()].find(([id]) => id !== event.pointerId)[1];
    const before = Math.hypot(prev.x - other.x, prev.y - other.y) || 1;
    const after = Math.hypot(event.clientX - other.x, event.clientY - other.y) || 1;
    zoomPhoto(after / before);
  }
  photoPointers.set(event.pointerId, {x: event.clientX, y: event.clientY, sx: prev.sx, sy: prev.sy});
  clampPhoto();
  paintPhoto();
});
function dropPhotoPointer(event) {
  const alone = photoPointers.size <= 1;
  photoPointers.delete(event.pointerId);
  if (!alone || photoMoved) return;
  const now = Date.now();
  if (now - photoTap < 320) {
    photoTap = 0;
    fitPhoto();
    return;
  }
  photoTap = now;
}
photoView.addEventListener('pointerup', dropPhotoPointer);
photoView.addEventListener('pointercancel', dropPhotoPointer);
photoView.addEventListener('wheel', event => {
  event.preventDefault();
  zoomPhoto(event.deltaY < 0 ? 1.12 : 0.9);
}, {passive: false});

async function copyDoc() {
  try {
    await navigator.clipboard.writeText(openText);
    toast('Copied.');
  } catch (error) {
    const body = $('reader-body');
    const range = document.createRange();
    range.selectNodeContents(body);
    const sel = getSelection();
    sel.removeAllRanges();
    sel.addRange(range);
    toast('Clipboard blocked. The text is selected.');
  }
}

loadGoal();
function paperButton(text) {
  const button = document.createElement('button');
  button.type = 'button';
  button.className = 'doc';
  button.setAttribute('aria-label', 'Open paper');
  button.innerHTML = '<svg viewBox="0 0 28 32" aria-hidden="true"><rect x="1.5" y="1.5" width="25" height="29" fill="none" stroke="currentColor" stroke-width="1.4"/><path d="M6 9h14M6 14h9M6 19h12" fill="none" stroke="currentColor" stroke-width="1.2"/></svg><span class="name">paper</span>';
  button.addEventListener('click', event => { event.stopPropagation(); openReader(text); });
  return button;
}
const BOX_CAP = 1000;
let staged = null;
let pasteLanded = false;
function stagePaper(text) {
  staged = text;
  $('staged-doc').hidden = false;
  toast('Staged as paper.');
}
$('staged-doc').addEventListener('click', event => { event.stopPropagation(); if (staged) openReader(staged); });
$('draft').addEventListener('paste', event => {
  const text = event.clipboardData && event.clipboardData.getData('text');
  if (text && text.length > BOX_CAP) {
    event.preventDefault();
    if ($('goal-arm').getAttribute('aria-pressed') === 'true') {
      toast('A long paste is a paper, not a goal.');
      return;
    }
    stagePaper(text);
    return;
  }
  pasteLanded = true;
});
$('draft').addEventListener('input', () => {
  if (!pasteLanded) {
    if ($('draft').value.length > BOX_CAP) {
      $('draft').value = $('draft').value.slice(0, BOX_CAP);
      toast('The box stops at 1000. Paste the long one.');
    }
    return;
  }
  pasteLanded = false;
  const text = $('draft').value;
  if (text.length <= BOX_CAP) return;
  $('draft').value = '';
  fitDraft();
  if ($('goal-arm').getAttribute('aria-pressed') === 'true') {
    toast('A long paste is a paper, not a goal.');
    return;
  }
  stagePaper(text);
});
let stagedPhoto = null;
let photoUploading = false;
function appendPhoto(card, fileId, room) {
  const button = document.createElement('button'); button.type = 'button'; button.className = 'shot'; button.setAttribute('aria-label', 'Open attached photo');
  const image = document.createElement('img'); image.alt = 'Attached photo'; image.style.cssText = 'width:112px;height:84px;object-fit:cover;display:block';
  image.src = '/api/relay/media/file?id=' + encodeURIComponent(fileId) + '&session=' + encodeURIComponent(room);
  button.append(image); card.append(button);
  button.addEventListener('click', event => { event.stopPropagation(); openPhoto(image); });
}
const photoInput = document.createElement('input'); photoInput.type = 'file'; photoInput.accept = 'image/png,image/jpeg,image/webp,image/gif'; photoInput.hidden = true; photoInput.id = 'relay-photo-input';
const photoButton = document.createElement('button'); photoButton.type = 'button'; photoButton.textContent = 'photo'; photoButton.id = 'relay-photo-add'; photoButton.setAttribute('aria-label', 'Attach a photo');
photoButton.style.cssText = 'background:transparent;color:var(--off);border:0;font:inherit;padding:4px';
$('composer').prepend(photoButton, photoInput);
const photoStage = document.createElement('div'); photoStage.id = 'relay-photo-stage'; photoStage.hidden = true;
const photoLabel = document.createElement('span'); const photoClear = document.createElement('button'); photoClear.type = 'button'; photoClear.textContent = 'clear';
photoStage.append(photoLabel,photoClear); $('composer').before(photoStage);
photoClear.addEventListener('click', () => { stagedPhoto = null; photoStage.hidden = true; photoInput.value = ''; });
photoButton.addEventListener('click', () => { if (chatRun || photoUploading) { toast('Wait for the current operation.'); return; } photoInput.click(); });
photoInput.addEventListener('change', async () => {
  const file = photoInput.files[0]; if (!file) return;
  if (file.size > 6 * 1024 * 1024) { toast('Choose a photo under 6 MB.'); return; }
  photoUploading = true; photoButton.disabled = true;
  try {
    await roomBootstrap;
    const bytes = new Uint8Array(await file.arrayBuffer()); let binary = '';
    for (let i=0;i<bytes.length;i+=32768) binary += String.fromCharCode(...bytes.subarray(i,i+32768));
    const media = await request('/api/relay/media/upload', {data:btoa(binary),name:file.name,session_id:chatRoom()});
    stagedPhoto = media; photoLabel.textContent = file.name + ' — photos do not support approval cards or stopping yet '; photoStage.hidden = false;
  } catch (error) { toast(error.message); } finally { photoUploading = false; photoButton.disabled = false; }
});
function chatCard(who, text, tag, paper, link, scroll = true) {
  const message = document.createElement('article');
  message.className = 'msg ' + (who === 'Eddie' ? 'you' : 'echo') + ' glass';
  message.id = 'msg-' + (++msgSeq);
  const title = document.createElement('h3');
  title.innerHTML = '<span class="br">[</span> ' + who + ' <span class="br">]</span>';
  message.append(title);
  if (link) message.append(quoteChip(link));
  const body = document.createElement('p');
  body.textContent = text;
  message.append(body);
  if (paper) message.append(paperButton(paper));
  if (tag) {
    const mark = document.createElement('span');
    mark.className = 'tag';
    mark.textContent = tag;
    message.append(mark);
  }
  $('thread').append(message);
  if (scroll) message.scrollIntoView({block: 'nearest'});
  return message;
}
let msgSeq = 0;
let replyTo = null;
// Proactive contact: Echo-originated messages pushed to Eddie. The cursor is the
// highest seq this document has actually rendered, so a reconnect replays anything
// it missed and skips anything it already drew. `proactiveGap` means the server's
// retained window no longer reaches back to this cursor; the history read is the
// reconciliation path, and no message is dropped silently.
let proactiveSeq = -1;
let proactiveGap = false;
let proactiveTimer = 0;
let proactiveBackoff = 1000;
let proactiveSeen = new Set();
let proactiveStream = null;
let proactiveStreamRoom = '';
const PROACTIVE_ROOM = 'relay-eddie-echo-chat';
const PROACTIVE_POLL_MS = 12000;
// EventSource is the *primary* live delivery path; the bounded poll below is the
// catch-up/reconciliation fallback for the rare case the stream cannot open.
const PROACTIVE_STREAM_PATH = '/api/relay/proactive/stream';
function proactiveCard(event) {
  const card = chatCard('Echo', event.text || '', 'proactive', null, null);
  if (event.id) card.id = event.id;
  card.dataset.proactiveSeq = String(event.seq);
  card.dataset.proactiveId = event.message_id || '';
  return card;
}
// Renders one event (or a replay window) and returns how many cards were added.
// Dedupe is by stable `message_id`, so a restored history card, a live event, and
// a reconnect replay can never double-draw the same message. The cursor only
// advances past a seq whose card was actually appended here.
function renderProactiveEvent(event) {
  if (!event || event.session_id !== PROACTIVE_ROOM) return 0;
  if (proactiveSeen.has(event.message_id)) return 0;
  const seq = Number(event.seq);
  if (!Number.isFinite(seq)) return 0;
  // Room-scoped: never draw a proactive card into a different room's thread, and
  // never let a stale async callback (from before a room switch) draw anything.
  if (chatRoom() !== PROACTIVE_ROOM) return 0;
  proactiveSeen.add(event.message_id);
  proactiveCard(event);
  if (seq > proactiveSeq) proactiveSeq = seq;
  return 1;
}
function renderProactive(state) {
  if (!state || state.session_id !== PROACTIVE_ROOM) return 0;
  let drawn = 0;
  if (Array.isArray(state.events)) {
    if (state.gap) proactiveGap = true;
    state.events.forEach(event => { drawn += renderProactiveEvent(event); });
  }
  if (Number.isFinite(Number(state.last_seq))) proactiveSeq = Math.max(proactiveSeq, Number(state.last_seq));
  return drawn;
}
async function pollProactive() {
  if (ui.section !== 'relay') return;
  try {
    const state = await request('/api/relay/proactive?last_seq=' + encodeURIComponent(proactiveSeq) + '&limit=200');
    renderProactive(state);
    proactiveBackoff = 1000;
  } catch (_) {
    // Bounded backoff, never a tight loop, and never a full page/thread refresh.
    proactiveBackoff = Math.min(60000, proactiveBackoff * 2);
  }
}
function stopProactiveStream() {
  if (proactiveStream) { proactiveStream.close(); proactiveStream = null; }
  proactiveStreamRoom = '';
}
// The primary live path: a real GET SSE connection scoped to the authorized room.
// EventSource reconnects on its own and sends `Last-Event-ID` (the stable
// message_id) automatically, so a dropped connection resumes without loss and
// without duplicates. The bounded poll stays only as a catch-up fallback.
function startProactiveStream() {
  if (ui.section !== 'relay') return;
  if (typeof EventSource === 'undefined') { startProactivePoll(); return; }
  if (proactiveStream && proactiveStreamRoom === PROACTIVE_ROOM) return;
  stopProactiveStream();
  const url = PROACTIVE_STREAM_PATH + '?session=' + encodeURIComponent(PROACTIVE_ROOM) +
    '&last_seq=' + encodeURIComponent(proactiveSeq);
  const stream = new EventSource(url);
  proactiveStream = stream;
  proactiveStreamRoom = PROACTIVE_ROOM;
  stream.addEventListener('message', event => {
    // A stale callback from a previous room (or a previous stream) must never
    // draw into the current thread: check both the room and the stream identity.
    if (proactiveStream !== stream || chatRoom() !== PROACTIVE_ROOM) return;
    let payload = null;
    try { payload = JSON.parse(event.data); } catch (_) { return; }
    renderProactiveEvent(payload);
  });
  stream.addEventListener('gap', () => {
    if (proactiveStream !== stream) return;
    // The server's retained window no longer reaches back to our cursor. The
    // history read is the reconciliation path, and it preserves the composer
    // state (no whole-thread reload) — see loadHistoryOnce.
    proactiveGap = true;
    loadHistory();
  });
  stream.onerror = () => {
    // EventSource reconnects on its own; keep the cursor as-is (it is derived
    // from cards actually rendered) and let the bounded poll catch up meanwhile.
    if (proactiveStream === stream) startProactivePoll();
  };
}
function startProactivePoll() {
  clearTimeout(proactiveTimer);
  const tick = () => { pollProactive().finally(() => { proactiveTimer = setTimeout(tick, Math.max(PROACTIVE_POLL_MS, proactiveBackoff)); }); };
  tick();
}
function startProactive() {
  // The SSE stream is the primary delivery path; the bounded poll stays only as
  // a catch-up fallback (it starts only when the stream cannot open, via
  // startProactiveStream's EventSource-absent or onerror path, or immediately
  // for one reconciliation read so a message published while the tab was closed
  // is picked up without waiting for the first stream frame).
  startProactiveStream();
  pollProactive();
}
function stopProactive() {
  clearTimeout(proactiveTimer);
  proactiveTimer = 0;
  stopProactiveStream();
}
function quoteChip(link) {
  const button = document.createElement('button');
  button.type = 'button';
  button.className = 'reply-link ' + (link.who === 'Eddie' ? 'you' : 'echo');
  const name = document.createElement('span');
  name.className = 'who';
  name.textContent = link.who;
  const snip = document.createElement('span');
  snip.className = 'snip';
  snip.textContent = link.text.replace(/\s+/g, ' ');
  button.append(name, snip);
  button.addEventListener('click', event => {
    event.preventDefault();
    event.stopPropagation();
    jumpCard(link.id);
  });
  return button;
}
function jumpCard(id) {
  const target = id && document.getElementById(id);
  if (!target) { toast('That card is not on this page.'); return; }
  target.scrollIntoView({block: 'nearest'});
  target.classList.add('jumped');
  setTimeout(() => target.classList.remove('jumped'), 1200);
}
function clearReply() {
  replyTo = null;
  const bar = $('reply-bar');
  if (bar) bar.hidden = true;
}
function setReply(card) {
  const words = cardWords(card);
  if (!words.text) { toast('Nothing to reply to.'); return; }
  if (!card.id) card.id = 'msg-' + (++msgSeq);
  replyTo = {id: card.id, who: words.who, text: words.text};
  $('reply-who').textContent = 'Reply to ' + words.who;
  $('reply-snip').textContent = words.text.replace(/\s+/g, ' ');
  $('reply-jump').className = 'reply-link ' + (words.who === 'Eddie' ? 'you' : 'echo');
  $('reply-bar').hidden = false;
  clearPick();
  $('draft').focus();
}
let pickTimer = 0;
let pickStart = null;
let suppressUp = null;
function clearHold() {
  clearTimeout(pickTimer);
  pickTimer = 0;
  pickStart = null;
}
function pickedCards() {
  return [...document.querySelectorAll('#thread article.msg.picked')];
}
function clearPick() {
  pickedCards().forEach(card => card.classList.remove('picked'));
  const bar = $('pick-bar');
  if (bar) bar.hidden = true;
}
function cardWords(card) {
  const body = card.querySelector('p');
  const who = (card.querySelector('h3') ? card.querySelector('h3').textContent : '').replace(/[\[\]]/g, '').trim() || 'Echo';
  const text = body ? body.textContent : '';
  return {who, text, quote: '[' + who + ']\n' + text};
}
function showPickBar() {
  const count = pickedCards().length;
  $('slash-menu').hidden = true;
  $('pick-bar').hidden = count === 0;
  const many = count > 1;
  $('pick-reply').hidden = many;
  $('pick-reply-sep').hidden = many;
  if (many) clearReply();
}
function pickCard(card) {
  if (!card.querySelector('p')) return;
  card.classList.add('picked');
  showPickBar();
  if (navigator.vibrate) navigator.vibrate(12);
}
function togglePick(card) {
  if (!card.querySelector('p')) return;
  card.classList.toggle('picked');
  if (!pickedCards().length) clearPick();
  else showPickBar();
}
async function copyPicked() {
  const cards = pickedCards();
  if (!cards.length) return;
  const text = cards.length === 1 ? cardWords(cards[0]).text : cards.map(card => cardWords(card).quote).join('\n\n');
  if (!text.trim()) { toast('Nothing to copy.'); return; }
  try {
    await navigator.clipboard.writeText(text);
    toast(cards.length === 1 ? 'Copied.' : 'Copied ' + cards.length + '.');
  } catch (error) {
    if (cards.length === 1) {
      const body = cards[0].querySelector('p');
      const range = document.createRange();
      range.selectNodeContents(body);
      const sel = getSelection();
      sel.removeAllRanges();
      sel.addRange(range);
    }
    toast('Clipboard blocked. The text is selected.');
  }
}
function replyPicked() {
  const cards = pickedCards();
  if (cards.length !== 1) { toast('Reply is one card.'); return; }
  setReply(cards[0]);
}
function showTyping() {
  let row = $('typing');
  if (!row) {
    row = document.createElement('p');
    row.id = 'typing';
    row.className = 'typing';
    row.setAttribute('aria-label', 'Echo is replying');
    row.innerHTML = '<span></span><span></span><span></span>';
  }
  $('thread').append(row);
  row.hidden = false;
  row.scrollIntoView({block: 'nearest'});
}
function hideTyping() {
  const row = $('typing');
  if (row) row.remove();
}
let chatRun = null;
let chatMark = null;
let stoppedRun = null;
let pendingDecision = null;
let decisionTimer = 0;
let decisionSequence = 0;

function decisionCard() {
  return document.getElementById('decision-card');
}
function renderDecision(decision) {
  const card = decisionCard();
  if (!card) return;
  const changed = !pendingDecision || !decision || pendingDecision.run_id !== decision.run_id || pendingDecision.request_id !== decision.request_id;
  pendingDecision = decision || null;
  const show = decision && decision.kind === 'approval';
  card.hidden = !show;
  if (!show) return;
  card.dataset.run = decision.run_id || '';
  card.dataset.request = decision.request_id || '';
  const choices = Array.isArray(decision.choices) ? decision.choices : [];
  const label = {once: 'Allow once', always: 'Always allow', deny: 'Deny', deny_reason: 'Deny with a reason'};
  card.querySelectorAll('button[data-decision-choice]').forEach(button => {
    const choice = button.dataset.decisionChoice;
    button.hidden = choice === 'always' ? choices.indexOf('always') < 0 : choices.indexOf(choice === 'deny_reason' ? 'deny' : choice) < 0;
    if (choice === 'deny_reason') { button.disabled = !relayCapability.approval_reason_native; button.title = button.disabled ? 'Backend reason delivery is not enabled yet' : ''; }
  });
  $('decision-action').textContent = decision.command || '';
  $('decision-description').textContent = decision.description || '';
  $('decision-scope').textContent = decision.scope || 'exact flagged action';
  $('decision-identity').textContent = decision.request_id || '';
  $('decision-always-scope').textContent = decision.pattern_key ? ('Always allow remembers only: ' + decision.pattern_key) : '';
  $('decision-always-scope').hidden = choices.indexOf('always') < 0;
  if (changed) { $('deny-reason-form').hidden = true; $('deny-reason').hidden = true; $('deny-reason').value = ''; }
}
function stopDecisionPoll() {
  clearTimeout(decisionTimer);
  decisionTimer = 0;
  decisionSequence++;
}
async function pollDecision(runId, mark) {
  const sequence = ++decisionSequence;
  while (runId && sequence === decisionSequence) {
    try {
      const state = await request('/api/relay/run?id=' + encodeURIComponent(runId));
      if (sequence !== decisionSequence) return;
      if (state.decision_blocked) {
      renderDecision(state.decision || null);
      if (mark) mark.textContent = 'decision blocked';
      hideTyping();
      return;
      }
      if (state.done) {
      renderDecision(null);
      sessionStorage.removeItem('relay-run');
      chatRun = null;
      hideTyping();
      if (state.status === 'completed' && stoppedRun !== runId) {
        if (mark) mark.textContent = 'sent';
        const answerCard = chatCard('Echo', state.output || '(no reply text)');
        answerCard.id = 'msg-a-' + runId;
      } else if (stoppedRun === runId || state.status === 'cancelled' || state.status === 'interrupted') {
        if (mark) mark.textContent = 'stopped';
        stoppedRun = null;
      } else {
        if (mark) mark.textContent = 'failed';
        toast(state.error || 'The turn failed.');
      }
      return;
      }
    } catch (error) {
      if (sequence !== decisionSequence) return;
      if (mark) mark.textContent = 'retrying decision';
    }
    decisionTimer = setTimeout(() => pollDecision(runId, mark), 2000);
    return;
  }
}
async function resolveDecision(choice) {
  const card = decisionCard();
  const decision = pendingDecision;
  if (!decision || !card || card.hidden || decision.run_id !== card.dataset.run || decision.request_id !== card.dataset.request) {
    toast('That decision is no longer on this card.');
    return;
  }
  const reason = $('deny-reason').hidden ? '' : $('deny-reason').value.trim();
  if (choice === 'deny' && $('deny-reason').hidden === false && !reason) {
    toast('Type the reason or cancel.');
    return;
  }
  const buttons = card.querySelectorAll('button');
  buttons.forEach(button => { button.disabled = true; });
  try {
    await request('/api/relay/decisions', {
      action: 'resolve', run_id: decision.run_id, request_id: decision.request_id,
      choice, reason: choice === 'deny' ? reason : '', allow_reason: choice === 'deny' && !$('deny-reason').hidden
    });
    renderDecision(null);
    stopDecisionPoll();
    if (choice === 'deny') toast('Denied. The exact request will not run.');
    else if (choice === 'always') toast('Always allow sent for the exact pattern shown.');
    else toast('Allowed once.');
    const mark = chatMark;
    if (mark) mark.textContent = 'decision sent';
    pollRun(decision.run_id, mark);
  } catch (error) {
    toast(error.message);
  } finally {
    buttons.forEach(button => { button.disabled = button.dataset.decisionChoice === 'deny_reason' && !relayCapability.approval_reason_native; });
  }
}
function pendingDecisionMarkup() {
  return `<section id="decision-card" class="glass decision-card" hidden aria-label="Approval decision">
    <h3><span class="br">[</span> decision <span class="br">]</span></h3>
    <p class="meta" id="decision-action"></p>
    <p id="decision-description"></p>
    <p class="meta" id="decision-scope"></p>
    <p class="meta" id="decision-identity"></p>
    <p class="meta" id="decision-always-scope"></p>
    <div class="decision-actions">
      <button type="button" data-decision-choice="once">Allow once</button>
      <button type="button" data-decision-choice="always">Always allow</button>
      <button type="button" data-decision-choice="deny">Deny</button>
      <button type="button" data-decision-choice="deny_reason">Deny with a reason</button>
    </div>
    <form id="deny-reason-form" hidden>
      <label for="deny-reason">reason</label>
      <textarea id="deny-reason" maxlength="280" rows="2" spellcheck="false"></textarea>
      <p id="deny-reason-limited">A denial reason is delivered to Echo only when the live backend supports it.</p>
      <div class="decision-actions">
        <button type="submit">send</button>
        <button type="button" id="deny-reason-cancel">cancel</button>
      </div>
    </form>
  </section>`;
}
document.getElementById('thread').insertAdjacentHTML('beforeend', pendingDecisionMarkup());
$('decision-card').addEventListener('click', event => {
  const button = event.target.closest('button[data-decision-choice]');
  if (!button || button.disabled) return;
  event.stopPropagation();
  const choice = button.dataset.decisionChoice;
  if (choice === 'deny_reason') {
    if (!relayCapability.approval_reason_native) { toast('Typed denial reasons are not enabled yet. Plain Deny still works.'); return; }
    $('deny-reason-form').hidden = false;
    $('deny-reason').hidden = false;
    $('deny-reason').focus();
    return;
  }
  resolveDecision(choice);
});
$('deny-reason-cancel').addEventListener('click', event => {
  event.stopPropagation();
  $('deny-reason').hidden = true;
  $('deny-reason').value = '';
  $('deny-reason-form').hidden = true;
});
$('deny-reason-form').addEventListener('submit', event => {
  event.preventDefault();
  event.stopPropagation();
  resolveDecision('deny');
});
let runWatchGeneration = 0;
async function pollRun(runId, mark) {
  const generation = ++runWatchGeneration;
  const room = chatRoom();
  let delay = 1000;
  showTyping();
  while (generation === runWatchGeneration && chatRun === runId) {
    await new Promise(resolve => setTimeout(resolve, delay));
    try {
      const state = await request('/api/relay/run?id=' + encodeURIComponent(runId) + '&session=' + encodeURIComponent(room));
      if (generation !== runWatchGeneration || chatRun !== runId) return;
      delay = 2000;
      if (state.decision_blocked) {
        renderDecision(state.decision || null);
        if (mark) mark.textContent = 'waiting for your decision';
        hideTyping();
        continue;
      }
      renderDecision(null);
      if (!state.done) { showTyping(); if (mark) mark.textContent = state.error ? 'reconnecting' : 'with Echo'; continue; }
      sessionStorage.removeItem('relay-run');
      chatRun = null;
      hideTyping();
      if (state.status === 'completed' && stoppedRun !== runId) {
        if (mark) mark.textContent = 'sent';
        const answerCard = chatCard('Echo', state.output || '(no reply text)');
        answerCard.id = 'msg-a-' + runId;
      } else if (stoppedRun === runId || state.status === 'cancelled' || state.status === 'interrupted') {
        if (mark) mark.textContent = 'stopped';
        stoppedRun = null;
      } else {
        if (mark) mark.textContent = 'failed';
        toast(state.error || 'The turn failed.');
      }
      return;
    } catch (error) {
      if (generation !== runWatchGeneration || chatRun !== runId) return;
      delay = Math.min(15000, delay * 2);
      if (mark) mark.textContent = 'reconnecting';
      hideTyping();
    }
  }
}
const SLASH = [
  {name: 'help', line: 'show these commands'},
  {name: 'new', line: 'fresh room. the old one stays'},
  {name: 'stop', line: 'stop the reply in flight'}
];
let selectedRelayRoom = '';
let relayCapability = {approval_reason_native: false};
let roomBootstrap;
function chatRoom() { return selectedRelayRoom || 'relay-eddie-echo-chat'; }
let historyRoom = '';
let historyGeneration = 0;
function clearThreadMessages() {
  document.querySelectorAll('#thread article.msg').forEach(card => card.remove());
  clearReply(); clearPick();
}
function paintRooms(rooms) {
  let select = $('relay-room-select');
  if (!select) {
    const row = document.createElement('div'); row.className = 'opt';
    const label = document.createElement('label'); label.htmlFor = 'relay-room-select'; label.textContent = 'room';
    select = document.createElement('select'); select.id = 'relay-room-select';
    select.style.cssText = 'max-width:65%;background:#171a19;color:#ddd;border:1px solid #444;font:inherit';
    row.append(label, select); $('page-settings').prepend(row);
    select.addEventListener('change', async () => {
      if (chatRun && chatRun !== 'uncertain') { select.value = chatRoom(); toast('Stop or finish this reply before switching rooms.'); return; }
      try {
        const result = await request('/api/relay/room', {session_id: select.value});
        selectedRelayRoom = result.session_id; sessionStorage.setItem('relay-session', selectedRelayRoom);
        chatRun = null; chatMark = null; sessionStorage.removeItem('relay-run');
        runWatchGeneration++; clearThreadMessages(); historyRoom = ''; paintRooms(result.rooms || []);
        await loadHistory();
        document.dispatchEvent(new Event('mesh-room-restored'));
      } catch (error) { select.value = chatRoom(); toast(error.message); }
    });
  }
  select.replaceChildren();
  (rooms || []).forEach(room => { const option = document.createElement('option'); option.value = room.session_id; option.textContent = room.title || room.session_id; select.append(option); });
  select.value = chatRoom();
}
function noteMesh(surface, kind, code, trigger) {
  fetch('/api/mesh/log', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({surface, kind, code, trigger})}).catch(() => {});
}
roomBootstrap = (async () => {
  try {
    const state = await request('/api/relay/state');
    selectedRelayRoom = state.session_id || 'relay-eddie-echo-chat';
    sessionStorage.setItem('relay-session', selectedRelayRoom); paintRooms(state.rooms || []);
    try { relayCapability = await request('/api/relay/capability'); } catch (_) {}
  } catch (error) { noteMesh('relay', 'error', 'room-recovery-unavailable', 'room-bootstrap-failed'); toast('Room recovery unavailable: ' + error.message); throw error; }
})();
let historyLoading = null;
let historyLoadingRoom = "";
async function loadHistory() {
  try { await roomBootstrap; } catch (_) { return; }
  const room = chatRoom();
  if (historyLoading && historyLoadingRoom === room) return historyLoading;
  historyLoadingRoom = room;
  const task = loadHistoryOnce();
  historyLoading = task;
  try { return await task; } finally { if (historyLoading === task) historyLoading = null; }
}
function relayReloadDecision(pendingValue, decisions, turns, currentRun) {
  if (currentRun) return 'none';
  if (decisions.run_id && ['running','pending','decision_blocked','waiting_for_approval','started'].includes(decisions.state)) return 'recover';
  if (!pendingValue) return 'none';
  const match = /^relay-(\d+)-.+$/.exec(pendingValue);
  const sentAt = match ? Number(match[1]) : NaN;
  if (Number.isSafeInteger(sentAt)) {
    let hasUser = false;
    // History is ordered; proactive Echo messages are not replies to a send.
    for (const turn of turns || []) {
      if (!(Date.parse(turn.created_at) >= sentAt)) continue;
      if (turn.who === 'Eddie') hasUser = true;
      else if (hasUser && turn.who === 'Echo' && !turn.proactive) return 'clear';
    }
  }
  return 'warn';
}
async function loadHistoryOnce() {
  try { await roomBootstrap; } catch (_) { return; }
  const room = chatRoom();
  if (historyRoom === room) return;
  historyRoom = room;
  const generation = ++historyGeneration;
  try {
    const state = await request('/api/relay/history?session=' + encodeURIComponent(room));
    if (generation !== historyGeneration || room !== chatRoom()) return;
    clearThreadMessages();
    (state.turns || []).forEach(turn => {
      const card = chatCard(turn.who, turn.text, null, turn.paper || null, turn.reply || null, false);
      if (turn.id) card.id = turn.id;
      (turn.files || []).forEach(file => appendPhoto(card, typeof file === "string" ? file : file.file_id, room));
    });
    // Reconcile the proactive cursor against what actually rendered, not against a
    // bare max-seq, so a message the server has but this document did not draw
    // (wrong room, capped turn window) is still picked up on the next replay.
    const proactiveCards = [...$('thread').querySelectorAll('article.msg[data-proactive-seq]')]
      .map(card => Number(card.dataset.proactiveSeq)).filter(Number.isFinite);
    if (proactiveCards.length) proactiveSeq = Math.max(proactiveSeq, ...proactiveCards);
    proactiveGap = !!state.proactive_gap;
    const pending = await request('/api/relay/decisions?session=' + encodeURIComponent(room));
    if (generation !== historyGeneration || room !== chatRoom()) return;
    const runId = pending.run_id;
    const reloadDecision = relayReloadDecision(localStorage.getItem('relay-send-pending:' + room), pending, state.turns, chatRun);
    if (reloadDecision === 'recover') {
      chatRun = runId; sessionStorage.setItem('relay-run', runId);
      chatMark = chatCard('Echo', 'Recovering your unfinished reply.', 'with Echo').querySelector('.tag');
      localStorage.removeItem('relay-send-pending:' + room);
      pollRun(runId, chatMark);
    } else if (reloadDecision === 'clear') {
      localStorage.removeItem('relay-send-pending:' + room);
    } else if (reloadDecision === 'warn') {
      chatRun = 'uncertain';
      chatMark = chatCard('Echo', 'Earlier delivery is uncertain. Do not resend it; recovery needs checking.', 'delivery uncertain').querySelector('.tag');
      noteMesh('relay', 'flag', 'delivery-uncertain', 'reload-pending-flag');
    }
    const last = $('thread').lastElementChild;
    if (last) last.scrollIntoView({block: 'nearest'});
  } catch (error) {
    historyRoom = ''; toast(error.message);
  }
}
function slashToken() {
  const text = $('draft').value;
  if (!text.startsWith('/')) return null;
  return text.slice(1).split(/\s/, 1)[0].toLowerCase();
}
function paintSlash() {
  const menu = $('slash-menu');
  const token = slashToken();
  menu.replaceChildren();
  if (token === null) { menu.hidden = true; return; }
  SLASH.filter(cmd => cmd.name.startsWith(token)).forEach(cmd => {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'slash-row';
    button.dataset.cmd = cmd.name;
    button.innerHTML = '<span class="tok">/' + cmd.name + '</span> ' + cmd.line;
    menu.append(button);
  });
  menu.hidden = !menu.childElementCount;
}
async function runSlash(name) {
  $('slash-menu').hidden = true;
  $('draft').value = '';
  fitDraft();
  if (name === 'help') {
    chatCard('Echo', 'Commands: /help, /new, /stop. Compress is not on this door.');
    return;
  }
  if (name === 'stop') {
    if (!chatRun || chatRun === 'pending') { toast('Nothing to stop.'); return; }
    const runId = chatRun;
    const room = chatRoom();
    if (runId !== 'uncertain') stoppedRun = runId;
    try {
      if (runId !== 'uncertain') await request('/api/relay/stop', {run_id: runId});
      localStorage.removeItem('relay-send-pending:' + room);
      sessionStorage.removeItem('relay-run');
      runWatchGeneration++; stopDecisionPoll();
      if (chatRun === runId) chatRun = null;
      hideTyping();
      if (chatMark) {
        if (runId === 'uncertain') {
          const warning = chatMark.closest('article.msg.echo');
          if (warning) warning.querySelector('p').textContent = 'Stopped.';
        }
        chatMark.textContent = 'stopped';
      }
      toast('Stopped.');
    } catch (error) {
      if (stoppedRun === runId) stoppedRun = null;
      toast(error.message);
    }
    return;
  }
  if (name === 'new') {
    if (chatRun) { toast('Stop the reply first.'); return; }
    try {
      const made = await request('/api/relay/new', {});
      selectedRelayRoom = made.session_id;
      sessionStorage.setItem('relay-session', made.session_id);
      paintRooms(made.rooms || []);
      clearThreadMessages();
      historyRoom = '';
      loadHistory();
      toast('New room. The old one is still there.');
    } catch (error) { toast(error.message); }
  }
}
async function submitDraft() {
  try { await roomBootstrap; } catch (_) { toast('Reconnect before sending.'); return; }
  const token = slashToken();
  if (token !== null) {
    const cmd = SLASH.find(row => row.name === token);
    if (!cmd) { toast('That command is not on this door.'); return; }
    runSlash(cmd.name);
    return;
  }
  const draft = $('draft').value.trim();
  const paper = staged;
  const photo = stagedPhoto;
  if (photoUploading) { toast('Wait for photo upload.'); return; }
  if (!draft && !paper && !photo) return;
  if ($('goal-arm').getAttribute('aria-pressed') === 'true') {
    if (!draft) { toast('Type the goal. A paper is not a goal.'); return; }
    if (draft.length > 500) { toast('Use 1 to 500 characters.'); return; }
    try {
      const wasNone = standingGoal.status === 'none';
      showGoal(await request('/api/relay/goal', {action: 'set', text: draft}));
      $('draft').value = '';
      fitDraft();
      armGoal(false);
      toast(wasNone ? 'Goal set.' : 'Goal replaced.');
    } catch (error) { toast(error.message); }
    return;
  }
  if (chatRun) { toast('Still working on the last send.'); return; }
  const link = replyTo;
  chatRun = 'pending';
  const message = chatCard('Eddie', draft || (paper ? 'Pasted prompt.' : 'Photo.'), 'sending', paper, link);
  if (photo) appendPhoto(message, photo.file_id, chatRoom());
  const mark = message.querySelector('.tag');
  chatMark = mark;
  $('draft').value = '';
  fitDraft();
  clearReply();
  try {
    const room = chatRoom();
    let sentText = draft;
    if (link) {
      const clip = link.text.replace(/\s+/g, ' ');
      const head = '[reply to ' + link.who + '] ' + clip;
      const roomForNote = Math.max(0, 1000 - draft.length - 2);
      sentText = (head.slice(0, roomForNote) + '\n\n' + draft).trim().slice(0, 1000);
    }
    const idempotencyKey = 'relay-' + Date.now() + '-' + Math.random().toString(36).slice(2, 10);
    const payload = paper ? {text: sentText || draft || 'Pasted prompt.', attachment: paper} : {text: sentText || (photo ? 'Photo.' : '')};
    if (photo) payload.files = [photo.file_id];
    if (room) payload.session_id = room;
    if (link) payload.reply = link;
    localStorage.setItem('relay-send-pending:' + room, idempotencyKey);
    const sentResponse = await fetch('/api/relay/send', {method: 'POST', headers: {'Content-Type': 'application/json', 'Idempotency-Key': idempotencyKey}, body: JSON.stringify(payload)});
    const sentBody = await sentResponse.json();
    if (!sentResponse.ok) { const failure = new Error(sentBody.error || 'Could not save.'); failure.definite = sentResponse.status >= 400 && sentResponse.status < 500 && sentResponse.status !== 409; throw failure; }
    localStorage.removeItem('relay-send-pending:' + room);
    const sent = sentBody;
    staged = null;
    stagedPhoto = null; photoStage.hidden = true; photoInput.value = '';
    $('staged-doc').hidden = true;
    chatRun = sent.run_id;
    message.id = "msg-u-" + sent.run_id;
    sessionStorage.setItem('relay-run', sent.run_id);
    mark.textContent = sent.replayed ? 'already sent' : 'with Echo';
    pollRun(sent.run_id, mark);
  } catch (error) {
    chatRun = error.definite ? null : 'uncertain';
    if (error.definite) { localStorage.removeItem('relay-send-pending:' + chatRoom()); $('draft').value = draft; fitDraft(); }
    mark.textContent = error.definite ? 'not sent' : 'delivery uncertain';
    if (!error.definite) noteMesh('relay', 'flag', 'send-uncertain', 'send-connection-lost');
    hideTyping();
    toast(error.definite ? error.message : 'Connection lost while sending. Reload to recover; do not resend.');
  }
}
// Recovery is driven by the server-backed room/run snapshot in loadHistory.

$('composer').addEventListener('submit', e => { e.preventDefault(); submitDraft(); });
$('draft-send').addEventListener('click', e => { e.preventDefault(); submitDraft(); });
$('slash-menu').addEventListener('click', event => {
  const row = event.target.closest('.slash-row');
  if (!row) return;
  event.preventDefault();
  event.stopPropagation();
  runSlash(row.dataset.cmd);
});
$('thread').addEventListener('pointerdown', event => {
  if (event.button) return;
  const card = event.target.closest('article.msg');
  if (!card || !card.querySelector('p') || event.target.closest('button, a')) return;
  pickStart = {x: event.clientX, y: event.clientY, card, id: event.pointerId};
  pickTimer = setTimeout(() => {
    const held = pickStart && pickStart.card;
    suppressUp = pickStart && pickStart.id;
    clearHold();
    if (held) pickCard(held);
  }, 480);
});
$('thread').addEventListener('pointermove', event => {
  if (!pickStart || event.pointerId !== pickStart.id) return;
  if (Math.hypot(event.clientX - pickStart.x, event.clientY - pickStart.y) > 10) clearHold();
});
$('thread').addEventListener('pointerup', event => {
  const start = pickStart;
  const heldId = suppressUp;
  clearHold();
  if (heldId !== null && event.pointerId === heldId) { suppressUp = null; return; }
  if ($('pick-bar').hidden) return;
  const card = event.target.closest('article.msg');
  if (!card || !card.querySelector('p') || event.target.closest('button, a')) return;
  if (start && Math.hypot(event.clientX - start.x, event.clientY - start.y) > 10) return;
  togglePick(card);
});
$('thread').addEventListener('pointercancel', clearHold);
$('thread').addEventListener('contextmenu', event => {
  if (event.target.closest('article.msg p')) event.preventDefault();
});
document.addEventListener('pointerup', event => {
  if (!$('pick-bar') || $('pick-bar').hidden) return;
  if (event.target.closest('#pick-bar, article.msg')) return;
  clearPick();
});
$('pick-copy').addEventListener('click', event => { event.preventDefault(); event.stopPropagation(); copyPicked(); });
$('pick-reply').addEventListener('click', event => { event.preventDefault(); event.stopPropagation(); replyPicked(); });
$('reply-clear').addEventListener('click', event => { event.preventDefault(); event.stopPropagation(); clearReply(); });
$('reply-jump').addEventListener('click', event => { event.preventDefault(); event.stopPropagation(); if (replyTo) jumpCard(replyTo.id); });
$('draft').addEventListener('input', () => { fitDraft(); paintSlash(); });
fitDraft();
$('draft').addEventListener('keydown', e => {
  if (e.key !== 'Enter' || e.shiftKey) return;
  if (e.ctrlKey || e.metaKey) {
    e.preventDefault();
    submitDraft();
  }
});
document.querySelectorAll('[data-live="off"]').forEach(button => button.addEventListener('click', () => toast('Sample only. Nothing is connected.')));
$('tog-tags').addEventListener('click', () => {
  const on = $('tog-tags').dataset.state !== 'on';
  $('tog-tags').dataset.state = on ? 'on' : 'off'; $('tog-tags').textContent = on ? 'on' : 'off';
  $('tog-tags').setAttribute('aria-pressed', String(on));
  document.querySelectorAll('.page .tag').forEach(tag => { tag.hidden = !on; });
});
$('tog-compact').addEventListener('click', () => {
  const on = document.body.classList.toggle('compact');
  $('tog-compact').dataset.state = on ? 'on' : 'off'; $('tog-compact').textContent = on ? 'on' : 'off';
  $('tog-compact').setAttribute('aria-pressed', String(on));
});
for (const [id,key] of [['tog-finished','showFinished'],['tog-trash','showTrash']]) $(id).addEventListener('click', e => {
  ui[key] = !ui[key]; e.target.dataset.state = ui[key] ? 'on' : 'off'; e.target.textContent = e.target.dataset.state; render();
});
showSection(location.hash.slice(1) || 'overview');
request('/api/state').then(result => {
  data = result;
  render();
}).catch(error => { $('list').textContent = 'Could not load cards from disk.'; toast(error.message); });
(function railRain() {
  const rail = document.getElementById('menu');
  if (!rail || matchMedia('(prefers-reduced-motion: reduce)').matches) return;
  const canvas = document.createElement('canvas');
  canvas.id = 'rail-rain';
  canvas.setAttribute('aria-hidden', 'true');
  rail.prepend(canvas);
  const ctx = canvas.getContext('2d');
  const katakana = 'アァカサタナハマヤャラワガザダバパイィキシチニヒミリヰギジヂビピウゥクスツヌフムユュルグズブヅプエェケセテネヘメレヱゲゼデベペオォコソトノホモヨョロヲゴゾドボポヴッン';
  const alphabet = katakana + 'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789';
  const fontSize = 16;
  const trail = 14;
  let drops = [];
  let mates = [];
  let cells = [];
  function size() {
    const box = rail.getBoundingClientRect();
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    canvas.width = Math.max(1, Math.floor(box.width * dpr));
    canvas.height = Math.max(1, Math.floor(box.height * dpr));
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    const columns = Math.max(1, Math.ceil(box.width / fontSize));
    const rows = Math.max(1, Math.ceil(box.height / fontSize) + trail);
    const gap = Math.max(trail + 2, Math.floor(rows / 2));
    drops = Array.from({length: columns}, () => Math.floor(Math.random() * rows));
    mates = drops.map(head => head + gap);
    cells = Array.from({length: columns}, () => Array.from({length: rows + gap}, () => alphabet.charAt(Math.floor(Math.random() * alphabet.length))));
  }
  function draw() {
    const box = rail.getBoundingClientRect();
    ctx.clearRect(0, 0, box.width, box.height);
    ctx.font = '700 ' + fontSize + 'px Cascadia Mono, Consolas, monospace';
    for (let i = 0; i < drops.length; i++) {
      const rowCount = cells[i].length;
      for (const head of [drops[i], mates[i]]) {
        cells[i][((head % rowCount) + rowCount) % rowCount] = alphabet.charAt(Math.floor(Math.random() * alphabet.length));
        for (let t = 0; t < trail; t++) {
          const row = head - t;
          if (row < 0) continue;
          const x = i * fontSize;
          const y = row * fontSize;
          if (y > box.height) continue;
          const fade = 1 - t / trail;
          const edge = Math.max(0, 1 - x / 64);
          const high = Math.max(0, 1 - y / Math.max(box.height, 1));
          const r = Math.round(186 * edge + 61 * high * (1 - edge) + 22 * (1 - edge) * (1 - high));
          const g = Math.round(194 * edge + 220 * high * (1 - edge) + 24 * (1 - edge) * (1 - high));
          const b = Math.round(202 * edge + 255 * high * (1 - edge) + 28 * (1 - edge) * (1 - high));
          const alpha = (0.08 + edge * 0.28 + high * 0.06) * fade;
          ctx.fillStyle = `rgba(${r},${g},${b},${alpha.toFixed(3)})`;
          const text = cells[i][((row % rowCount) + rowCount) % rowCount];
          ctx.fillText(text, x, y);
          ctx.fillText(text, x + 1, y);
        }
      }
      const step = head => (head * fontSize > box.height && Math.random() > 0.975) ? 0 : head + 1;
      drops[i] = step(drops[i]);
      mates[i] = step(mates[i]);
    }
  }
  size();
  addEventListener('resize', size);
  setInterval(draw, 45);
})();
