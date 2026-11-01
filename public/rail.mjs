// Which rail is showing.
//
// One rail at a time, and the default depends on the tab: the Relay tab opens sessions,
// every other tab opens the menu. On the Relay tab [menu] swaps sessions out and back
// again; elsewhere [menu] simply shows or hides the tabs, and [sessions] is not offered.
const shell = document.querySelector('.shell');
const menuLink = document.getElementById('rail-menu');
const sessionsLink = document.getElementById('rail-sessions-toggle');
const relayTab = document.getElementById('tab-relay');
const sessionsPanel = document.getElementById('rail-sessions');

const isRelay = () => relayTab?.getAttribute('aria-selected') === 'true';

function setRail(view) {
  if (!shell) return;
  shell.dataset.rail = view;
  if (menuLink) menuLink.setAttribute('aria-expanded', String(view === 'menu'));
  if (sessionsLink) sessionsLink.setAttribute('aria-expanded', String(view === 'sessions'));
}

// Sessions only exists on the Relay tab - hide the link everywhere else.
function syncSessionsLink() {
  if (!sessionsLink) return;
  sessionsLink.hidden = !isRelay();
  if (sessionsPanel) sessionsPanel.hidden = !isRelay() || shell?.dataset.rail !== 'sessions';
}

function applyTabDefault() {
  setRail(isRelay() ? 'sessions' : 'menu');
  syncSessionsLink();
}

if (menuLink) {
  menuLink.addEventListener('click', () => {
    const view = shell?.dataset.rail;
    if (isRelay()) setRail(view === 'menu' ? 'sessions' : 'menu');
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

if (relayTab) {
  new MutationObserver(applyTabDefault)
    .observe(relayTab, { attributes: true, attributeFilter: ['aria-selected'] });
}

applyTabDefault();

// The sessions list: the conversation the snapshot actually holds.
fetch('/chat.json', { cache: 'no-store' })
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