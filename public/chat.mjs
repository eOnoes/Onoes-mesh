// Render the Relay conversation.
//
// The data comes from public/chat.json, a snapshot written by
// tools/sync-relay-chat.mjs. Mesh's server refuses live connections on purpose, so this
// file only paints what the snapshot contains.
//
// The markup it builds is the reference's own: .chat-msg / .chat-who / .chat-body with
// the [copy] affordance on its own line, and .chat-files for delivered artefacts.
const chat = document.getElementById('relay-chat');
const empty = document.getElementById('relay-empty');

function copyButton(text) {
  const button = document.createElement('button');
  button.type = 'button';
  button.className = 'fcp';
  button.textContent = '[copy]';
  button.addEventListener('click', async () => {
    try {
      await navigator.clipboard.writeText(text);
      button.classList.add('oky');
      button.textContent = '[copied]';
      setTimeout(() => { button.classList.remove('oky'); button.textContent = '[copy]'; }, 1200);
    } catch {
      button.textContent = '[failed]';
      setTimeout(() => { button.textContent = '[copy]'; }, 1200);
    }
  });
  return button;
}

function renderMessage(message, agentName) {
  const wrap = document.createElement('div');
  const mine = message.k === 'you';
  wrap.className = mine ? 'chat-msg you' : 'chat-msg agent' + (message.k === 'ag' ? ' echo' : '');

  const who = document.createElement('div');
  who.className = mine ? 'chat-who you-who' : 'chat-who agent-who';
  who.textContent = mine ? 'You' : agentName;

  const body = document.createElement('div');
  body.className = 'chat-body';

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

  body.append(copyButton(message.t || message.files.map((f) => f.name).join(' ')));
  wrap.append(who, body);
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

  const agentName = data.agent?.name || 'Relay';
  const composer = document.getElementById('relay-text');
  if (composer) composer.placeholder = `${agentName} · type a message…`;

  const fragment = document.createDocumentFragment();
  for (const message of messages) fragment.append(renderMessage(message, agentName));
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
