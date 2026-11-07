// Which rail is showing.
//
// One rail at a time, and the default depends on the tab:
//
//   Relay tab     sessions   (what you were talking to)
//   Control tab   control    (overview / throughput / logs)
//   every other   menu       (the workspace tabs)
//
// [menu] always swaps to the tabs. On the Relay and Control tabs it swaps back to that
// tab's own rail, so closing the menu never leaves you without navigation.
const shell = document.querySelector('.shell');
const menuLink = document.getElementById('rail-menu');
const sessionsLink = document.getElementById('rail-sessions-toggle');
const relayTab = document.getElementById('tab-relay');
const controlTab = document.getElementById('tab-control');
const sessionsPanel = document.getElementById('rail-sessions');
const scopedConversation = Boolean(document.getElementById('relay-chat-agent'));

const isRelay = () => relayTab?.getAttribute('aria-selected') === 'true';
const isControl = () => controlTab?.getAttribute('aria-selected') === 'true';
const defaultView = () => (isRelay() && !scopedConversation ? 'sessions' : isControl() ? 'control' : 'menu');

function setRail(view) {
  if (!shell) return;
  shell.dataset.rail = view;
  if (menuLink) menuLink.setAttribute('aria-expanded', String(view === 'menu'));
  if (sessionsLink) sessionsLink.setAttribute('aria-expanded', String(view === 'sessions'));
}

// Sessions only exists on the Relay tab - hide the link everywhere else.
function syncSessionsLink() {
  if (!sessionsLink) return;
  sessionsLink.hidden = !isRelay() || scopedConversation;
  if (sessionsPanel) sessionsPanel.hidden = scopedConversation || !isRelay() || shell?.dataset.rail !== 'sessions';
}

function applyTabDefault() {
  setRail(defaultView());
  syncSessionsLink();
}

if (menuLink) {
  menuLink.addEventListener('click', () => {
    const view = shell?.dataset.rail;
    // on a tab that owns a rail of its own, [menu] toggles between the two
    if (isRelay() || isControl()) setRail(view === 'menu' ? defaultView() : 'menu');
    else setRail(view === 'menu' ? 'none' : 'menu');
    syncSessionsLink();
  });
}
if (sessionsLink) {
  sessionsLink.addEventListener('click', () => {
    setRail(shell?.dataset.rail === 'sessions' ? 'none' : 'sessions');
    syncSessionsLink();
  });
}

for (const tab of [relayTab, controlTab]) {
  if (tab) {
    new MutationObserver(applyTabDefault)
      .observe(tab, { attributes: true, attributeFilter: ['aria-selected'] });
  }
}

applyTabDefault();

// The sessions list: the conversation the snapshot actually holds.
if (!scopedConversation) fetch('/chat.json', { cache: 'no-store' })
  .then((r) => (r.ok ? r.json() : null))
  .then((data) => {
    const list = document.getElementById('sessions-list');
    if (!data || !list) return;
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'rail-session';
    button.setAttribute('aria-current', 'true');
    button.textContent = data.agent?.name || 'Relay';
    const count = document.createElement('small');
    count.textContent = `${data.count ?? 0} messages`;
    button.append(count);
    list.replaceChildren(button);
  })
  .catch(() => { /* leave the list empty */ });

// ---------------------------------------------------------------------------------
// The picker.
//
// On a phone the top bar cannot hold a pill strip and the status line at once, so the
// strip collapses into one control that names the current agent (Relay) or machine
// (Control) and draws a menu when opened. It mirrors the strips rather than fetching
// its own data, so there is one source of truth.
// ---------------------------------------------------------------------------------
const picker = document.getElementById('picker');
const pickerLabel = document.getElementById('picker-label');
const pickerPanel = document.getElementById('picker-panel');

function pickerSource() {
  if (isRelay() && !scopedConversation) return document.getElementById('agent-tabs');
  if (isControl()) return document.getElementById('machine-tabs');
  return null;
}

function closePicker() {
  if (!picker || !pickerPanel) return;
  pickerPanel.hidden = true;
  picker.setAttribute('aria-expanded', 'false');
}

function buildPicker() {
  if (!picker || !pickerPanel) return;
  const source = pickerSource();
  const items = source ? [...source.querySelectorAll('button')] : [];
  if (!items.length) {
    picker.hidden = true;
    closePicker();
    return;
  }
  picker.hidden = false;

  const current = items.find((b) => b.getAttribute('aria-pressed') === 'true') || items[0];
  if (pickerLabel) pickerLabel.textContent = (current.textContent || '').trim();

  pickerPanel.replaceChildren();

  // one prompt line, naming the command that would list this set
  const prompt = document.createElement('div');
  prompt.className = 'picker-prompt';
  const ps1 = document.createElement('span');
  ps1.className = 'ps1';
  ps1.textContent = isControl() ? '~ $' : '~ $';
  prompt.append(ps1, document.createTextNode(isControl() ? ' ssh -l echo' : ' cd agents'));
  pickerPanel.append(prompt);

  for (const item of items) {
    const option = document.createElement('button');
    option.type = 'button';
    option.setAttribute('role', 'option');
    option.setAttribute('aria-selected', String(item === current));
    const dot = item.querySelector('.tdot');
    if (dot) option.append(dot.cloneNode());
    const label = document.createElement('span');
    label.textContent = (item.textContent || '').trim();
    option.append(label);
    option.addEventListener('click', () => {
      item.click();
      if (pickerLabel) pickerLabel.textContent = (item.textContent || '').trim();
      closePicker();
    });
    pickerPanel.append(option);
  }
}

if (picker) {
  picker.addEventListener('click', (event) => {
    event.stopPropagation();
    buildPicker();
    pickerPanel.hidden = !pickerPanel.hidden;
    picker.setAttribute('aria-expanded', String(!pickerPanel.hidden));
  });
  document.addEventListener('click', (event) => {
    if (pickerPanel.hidden) return;
    if (pickerPanel.contains(event.target) || picker.contains(event.target)) return;
    closePicker();
  });
  document.addEventListener('keydown', (event) => { if (event.key === 'Escape') closePicker(); });
}

// keep it in step with the tab and with whatever populated the strips
for (const tab of [relayTab, controlTab]) {
  if (tab) new MutationObserver(buildPicker).observe(tab, { attributes: true, attributeFilter: ['aria-selected'] });
}
const agentStrip = document.getElementById('agent-tabs');
if (scopedConversation && agentStrip) agentStrip.style.setProperty('display','none','important');
if (agentStrip) new MutationObserver(buildPicker).observe(agentStrip, { childList: true });
const machineStrip = document.getElementById('machine-tabs');
if (machineStrip) new MutationObserver(buildPicker).observe(machineStrip, { childList: true });
buildPicker();
// ---------------------------------------------------------------------------------
// Mobile sheets.
//
// Below 760px the navigation and the picker stop being inline chrome and become
// over-panels: nav slides in from the left at 2/3 width, the picker from the top-right
// corner at 2/3 width by 2/5 height. One scrim sits behind whichever is open, blurs the
// content, and closes on tap. Either closes on selection.
// ---------------------------------------------------------------------------------
const sheetScrim = document.getElementById('sheet-scrim');
const isMobile = () => window.matchMedia('(max-width: 759px)').matches;

function openSheet(kind) {
  document.body.dataset.sheet = kind;
  if (sheetScrim) sheetScrim.hidden = false;
}

function closeSheets() {
  delete document.body.dataset.sheet;
  if (sheetScrim) sheetScrim.hidden = true;
  if (pickerPanel) pickerPanel.hidden = true;
  if (picker) picker.setAttribute('aria-expanded', 'false');
}

if (sheetScrim) sheetScrim.addEventListener('click', closeSheets);

// [menu] opens the nav sheet on a phone, and toggles the rail on desktop
if (menuLink) {
  menuLink.addEventListener('click', (event) => {
    if (!isMobile()) return;
    // stop the same click reaching the outside-click handler below, which would
    // otherwise open the sheet and shut it again in one gesture
    event.stopPropagation();
    const open = document.body.dataset.sheet === 'nav';
    if (open) { closeSheets(); return; }
    setRail('menu');
    syncSessionsLink();
    openSheet('nav');
  });
}

// the picker opens its corner sheet on a phone, or the popover on desktop
if (picker) {
  picker.addEventListener('click', (event) => {
    if (!isMobile()) return;
    event.stopPropagation();
    buildPicker();
    const open = document.body.dataset.sheet === 'picker';
    if (open) { closeSheets(); return; }
    if (pickerPanel) pickerPanel.hidden = false;
    picker.setAttribute('aria-expanded', 'true');
    openSheet('picker');
  }, true);
}

// choosing a tab or an option closes whatever is open
document.addEventListener('click', (event) => {
  if (!isMobile()) return;
  if (!document.body.dataset.sheet) return;
  // a choice always closes the sheet - checked BEFORE the "inside" test, because the
  // picker panel lives inside .tbar and an earlier version of this guard bailed out
  // there, leaving the scrim stuck over the page after a selection
  if (event.target.closest('.picker-panel button') || event.target.closest('[role="tab"]')) {
    setTimeout(closeSheets, 0);
    return;
  }
  if (event.target.closest('.nav-rail, .picker-panel, #sheet-scrim')) return;
  closeSheets();
});
document.addEventListener('keydown', (event) => { if (event.key === 'Escape') closeSheets(); });
