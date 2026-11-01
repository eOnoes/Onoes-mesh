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

const isRelay = () => relayTab?.getAttribute('aria-selected') === 'true';
const isControl = () => controlTab?.getAttribute('aria-selected') === 'true';
const defaultView = () => (isRelay() ? 'sessions' : isControl() ? 'control' : 'menu');

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
