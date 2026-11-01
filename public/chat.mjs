// Render the Relay conversation.
//
// The data comes from public/chat.json, a snapshot written by
// tools/sync-relay-chat.mjs. Mesh's server refuses live connections on purpose, so this
// file only paints what the snapshot contains.
//
// Message actions are revealed on hover, on keyboard focus, or by clicking the message -
// phones have no hover, so tapping a message targets it and shows the same row.
const chat = document.getElementById('relay-chat');
const composer = document.getElementById('relay-text');
const errorLine = document.getElementById('relay-error');

let agentName = 'Relay';

function note(message) {
  if (!errorLine) return;
  errorLine.textContent = message;
  setTimeout(() => { if (errorLine.textContent === message) errorLine.textContent = ''; }, 2200);
}

function actionButton(label, className, onClick) {
  const button = document.createElement('button');
  button.type = 'button';
  button.className = `fcp ${className}`;
  button.textContent = `[${label}]`;
  button.addEventListener('click', (event) => {
    event.stopPropagation();
    onClick(button);
  });
  return button;
}

function renderMessage(message) {
  const wrap = document.createElement('div');
  const mine = message.k === 'you';
  wrap.className = mine ? 'chat-msg you' : 'chat-msg agent echo';

  const who = document.createElement('div');
  who.className = mine ? 'chat-who you-who' : 'chat-who agent-who';
  who.textContent = mine ? 'You' : agentName;

  const body = document.createElement('div');
  body.className = 'chat-body';

  const plain = message.t || (message.files || []).map((f) => f.name).join(' ');

  if (message.t) {
    const text = document.createElement('div');
    text.className = 'chat-text';
    text.textContent = message.t;
    body.append(text);
  }

  if (message.files && message.files.length) {
    const row = document.createElement('div');
    row.className = 'chat-files';
    for (const file of message.files) {
      const chip = document.createElement('span');
      chip.className = 'chat-file';
      chip.textContent = `[${file.name}]`;
      if (file.size) chip.title = `${file.name} · ${Math.round(file.size / 102.4) / 10} KB`;
      row.append(chip);
    }
    body.append(row);
  }

  const actions = document.createElement('div');
  actions.className = 'chat-actions';

  actions.append(actionButton('reply', 'reply', () => {
    const already = wrap.classList.contains('is-target');
    chat.querySelectorAll('.chat-msg.is-target').forEach((el) => el.classList.remove('is-target'));
    if (!already) wrap.classList.add('is-target');
    if (composer) {
      composer.placeholder = already
        ? `${agentName} · type a message…`
        : `Replying to ${mine ? 'your message' : agentName} · send is not wired yet`;
    }
  }));

  actions.append(actionButton('copy', 'copy', async (button) => {
    try {
      await navigator.clipboard.writeText(plain);
      button.textContent = '[copied]';
      setTimeout(() => { button.textContent = '[copy]'; }, 1200);
    } catch {
      button.textContent = '[failed]';
      setTimeout(() => { button.textContent = '[copy]'; }, 1200);
    }
  }));

  actions.append(actionButton('delete', 'del', () => {
    // Local only: this hides the message from this view. Relay still holds it, and
    // nothing is deleted anywhere until the write path is wired.
    wrap.classList.add('is-gone');
    note('Hidden locally - Relay still has this message.');
  }));

  body.append(actions);
  wrap.append(who, body);

  // tapping the message targets it, which is how the actions appear without a mouse
  wrap.addEventListener('click', () => {
    if (wrap.classList.contains('is-target')) return;
    chat.querySelectorAll('.chat-msg.is-target').forEach((el) => el.classList.remove('is-target'));
    wrap.classList.add('is-target');
  });

  return wrap;
}

async function main() {
  if (!chat) return;
  let data;
  try {
    const response = await fetch('/chat.json', { cache: 'no-store' });
    if (!response.ok) return;
    data = await response.json();
  } catch {
    return;
  }
  const messages = Array.isArray(data.messages) ? data.messages : [];
  if (!messages.length) return;

  agentName = data.agent?.name || 'Relay';
  if (composer) composer.placeholder = `${agentName} · type a message…`;

  const fragment = document.createDocumentFragment();
  for (const message of messages) fragment.append(renderMessage(message));
  chat.replaceChildren(fragment);

  // Start at the newest message, like any terminal transcript. The panel is hidden when
  // this runs, so scrollHeight is 0 - it has to be re-applied when the tab becomes
  // visible, which is the only moment the measurement is real.
  const toBottom = () => { chat.scrollTop = chat.scrollHeight; };
  toBottom();
  const panel = document.getElementById('panel-relay');
  if (panel) {
    new MutationObserver(() => { if (!panel.hidden) toBottom(); })
      .observe(panel, { attributes: true, attributeFilter: ['hidden'] });
  }
  const relayTab = document.getElementById('tab-relay');
  if (relayTab) {
    new MutationObserver(() => { if (relayTab.getAttribute('aria-selected') === 'true') toBottom(); })
      .observe(relayTab, { attributes: true, attributeFilter: ['aria-selected'] });
  }
}

main();
