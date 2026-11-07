import {createRelayConversation} from './relay-conversation.mjs';
import {createRelayTaskProgress} from './relay-task-progress.mjs';

const chat = document.getElementById('relay-chat');
const composer = document.getElementById('relay-text');
const form = document.getElementById('relay-form');
const errorLine = document.getElementById('relay-error');

let agentName = 'Relay';

function note(message) {
  if (!errorLine) return;
  errorLine.textContent = message;
  setTimeout(() => { if (errorLine.textContent === message) errorLine.textContent = ''; }, 2600);
}

function actionButton(label, className, onClick) {
  const button = document.createElement('button');
  button.type = 'button';
  button.className = `fcp ${className}`;
  const open = document.createElement('span');
  open.className = 'br'; open.textContent = '[';
  const word = document.createElement('span');
  word.className = 'lbl'; word.textContent = label;
  const close = document.createElement('span');
  close.className = 'br'; close.textContent = ']';
  button.append(open, word, close);
  button.addEventListener('click', (event) => { event.stopPropagation(); onClick(button); });
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
      composer.placeholder = already ? `${agentName} · type a message…`
        : `Replying to ${mine ? 'your message' : agentName}`;
      composer.focus();
    }
  }));

  actions.append(actionButton('copy', 'copy', async (button) => {
    const word = button.querySelector('.lbl');
    try {
      await navigator.clipboard.writeText(plain);
      const was = word.textContent; word.textContent = 'copied';
      setTimeout(() => { word.textContent = was; }, 1200);
    } catch {
      const was = word.textContent; word.textContent = 'failed';
      setTimeout(() => { word.textContent = was; }, 1200);
    }
  }));

  actions.append(actionButton('hide', 'del', () => {
    // Local only until a real delete is wired through Relay.
    wrap.classList.add('is-gone');
    note('Hidden locally - Relay still has this message.');
  }));

  body.append(actions);
  wrap.append(who, body);

  wrap.addEventListener('click', () => {
    if (wrap.classList.contains('is-target')) return;
    chat.querySelectorAll('.chat-msg.is-target').forEach((el) => el.classList.remove('is-target'));
    wrap.classList.add('is-target');
  });

  return wrap;
}

function paint(messages) {
  const fragment = document.createDocumentFragment();
  let previous = null;
  for (const message of messages) {
    const node = renderMessage(message);
    if (previous && previous === message.k) node.classList.add('continues');
    previous = message.k;
    fragment.append(node);
  }
  chat.replaceChildren(fragment);
}

const toBottom = () => { if (chat) chat.scrollTop = chat.scrollHeight; };

// Ordinary chat has one submit handler and uses the application's admitted request path.
export function createRelayChat({request}) {
  if(!chat || !form) return {setAvailable(){},clear(){},refresh:async()=>{}};
  const taskProgress=createRelayTaskProgress({root:document.getElementById('relay-task-progress'),button:document.getElementById('relay-task-progress-open'),request,document});
  const select=document.getElementById('relay-chat-agent');
  const current=document.getElementById('relay-chat-current');
  const refreshButton=document.getElementById('relay-chat-refresh');
  const destination=document.getElementById('relay-chat-destination');
  const status=document.getElementById('relay-chat-status');
  const send=document.getElementById('relay-send');
  const attach=document.getElementById('relay-add-files');
  let busy=false,lastPaint='',lastAgents='',lastDestination='',core;
  function draw(state) {
    agentName=state.destination?.name || 'Relay';
    const signature=JSON.stringify(state.agents);
    if(signature!==lastAgents){
      lastAgents=signature;select.replaceChildren();
      const empty=document.createElement('option');empty.value='';empty.textContent='Choose an agent…';select.append(empty);
      for(const peer of state.agents){const option=document.createElement('option');option.value=peer.id;option.textContent=`${peer.name} · ${peer.status}${peer.sessionId?'':' · no conversation'}`;option.disabled=!peer.sessionId;select.append(option);}
    }
    select.value=state.destination?.agentId || '';
    destination.textContent=state.destination ? `Destination: ${state.destination.name} (${state.destination.agentId}) · conversation ${state.destination.sessionId} · ${state.live?'current observation':'not confirmed current'}${state.observedAt?' · checked '+state.observedAt:''}` : 'Choose a destination. No agent is selected automatically.';
    status.textContent=state.note;
    if(composer.value!==state.draft)composer.value=state.draft;
    composer.placeholder=state.destination?`${agentName} · type a message…`:'Choose an agent before writing a message';
    composer.disabled=busy||!state.available||state.initializing||state.sending||!state.destination;
    send.disabled=busy||!state.canSend||!state.draft.trim();
    select.disabled=busy||!state.available||state.initializing||state.sending;
    current.disabled=select.disabled||!state.destination;
    refreshButton.disabled=busy||!state.available||state.initializing||state.sending;
    attach.disabled=true;
    const legacyId=document.getElementById('relay-message-id');if(legacyId)legacyId.disabled=true;
    const painted=JSON.stringify([state.destination,state.messages]);
    if(painted!==lastPaint){
      const target=JSON.stringify(state.destination && [state.destination.agentId,state.destination.sessionId]);
      const follow=target!==lastDestination || chat.scrollHeight-chat.clientHeight-chat.scrollTop<=32;
      const position=chat.scrollTop;
      lastPaint=painted;lastDestination=target;paint(state.messages);
      if(follow)toBottom();else chat.scrollTop=position;
    }
  }
  let storage;try{storage=sessionStorage;}catch{storage={getItem(){return null;},setItem(){throw Error('Browser retry storage unavailable. Nothing was sent.');},removeItem(){}};}
  core=createRelayConversation({request,storage,onChange:draw});
  composer.addEventListener('input',()=>core.setDraft(composer.value));
  select.addEventListener('change',()=>{if(!busy)core.select(select.value);});
  current.addEventListener('click',()=>{if(!busy&&core.state().destination)core.select(core.state().destination.agentId);});
  refreshButton.addEventListener('click',()=>{if(!busy)core.refresh();});
  form.addEventListener('submit',async event=>{event.preventDefault();if(busy)return;await core.send();});
  const panel=document.getElementById('panel-relay');
  const refresh=()=>{if(!panel?.hidden&&!document.hidden&&!busy){taskProgress.refresh();return core.refresh();}};
  setInterval(refresh,5000);
  if(panel)new MutationObserver(()=>{if(!panel.hidden){toBottom();refresh();}}).observe(panel,{attributes:true,attributeFilter:['hidden']});
  draw(core.state());
  return {refresh,setAvailable(value,isBusy=false){busy=isBusy;taskProgress.setAvailable(value,isBusy);core.setAvailable(value);draw(core.state());},clear(){taskProgress.clear();core.setAvailable(false);draw(core.state());}};
}
// --- chat chrome ------------------------------------------------------------------
// Two things the conversation needs to be usable: a width you can drag, and a scroll
// rail that is not the operating system's scrollbar. Both are re-attached here because
// the module was rewritten for live data and dropped the originals.
const railPanel = document.getElementById('panel-relay');
const grip = document.getElementById('chat-grip');
const WIDTH_KEY = 'mesh-chat-max';
const MIN_WIDTH = 420;

function setChatWidth(px) {
  if (!railPanel) return;
  const panelWidth = railPanel.getBoundingClientRect().width || window.innerWidth;
  const max = Math.max(MIN_WIDTH, panelWidth - 48);
  const width = Math.min(max, Math.max(MIN_WIDTH, Math.round(px)));
  document.documentElement.style.setProperty('--chat-max', `${width}px`);
  return width;
}

if (grip && railPanel) {
  const stored = Number(localStorage.getItem(WIDTH_KEY));
  if (Number.isFinite(stored) && stored > 0) setChatWidth(stored);

  let resizing = false;
  const fromPointer = (event) => {
    // The grip rides the chat's RIGHT edge, so the column is symmetric about the panel
    // centre: width = 2 x (pointer - centre). Dragging right widens, left narrows.
    const box = railPanel.getBoundingClientRect();
    const centre = box.left + box.width / 2;
    return 2 * (event.clientX - centre);
  };

  grip.addEventListener('pointerdown', (event) => {
    resizing = true;
    grip.setPointerCapture(event.pointerId);
    document.body.classList.add('resizing');
    event.preventDefault();
  });
  grip.addEventListener('pointermove', (event) => {
    if (!resizing) return;
    setChatWidth(fromPointer(event));
  });
  const stopResize = () => {
    if (!resizing) return;
    resizing = false;
    document.body.classList.remove('resizing');
    const current = getComputedStyle(document.documentElement).getPropertyValue('--chat-max').trim();
    if (current) localStorage.setItem(WIDTH_KEY, String(parseFloat(current) || ''));
  };
  grip.addEventListener('pointerup', stopResize);
  grip.addEventListener('pointercancel', stopResize);

  // A separator that only answers to a mouse is not a separator for everyone.
  grip.addEventListener('keydown', (event) => {
    const box = railPanel.getBoundingClientRect();
    const current = parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--chat-max')) || box.width;
    if (event.key === 'ArrowLeft') { setChatWidth(current - 24); event.preventDefault(); }
    if (event.key === 'ArrowRight') { setChatWidth(current + 24); event.preventDefault(); }
  });
}

if (chat && railPanel) {
  const TICKS = 36;
  const seek = document.createElement('div');
  seek.className = 'chat-seek';
  seek.tabIndex = 0;
  seek.setAttribute('role', 'scrollbar');
  seek.setAttribute('aria-label', 'conversation position');
  seek.setAttribute('aria-controls', 'relay-chat');
  const ticks = [];
  for (let index = 0; index < TICKS; index += 1) {
    const tick = document.createElement('i');
    seek.append(tick);
    ticks.push(tick);
  }
  railPanel.append(seek);

  const jump = document.createElement('button');
  jump.type = 'button';
  jump.className = 'chat-jump';
  jump.textContent = 'jump to latest';
  railPanel.append(jump);

  let hotIndex = -1;

  const place = () => {
    const panelBox = railPanel.getBoundingClientRect();
    const chatBox = chat.getBoundingClientRect();
    if (!chatBox.height) return;
    seek.style.top = `${Math.round(chatBox.top - panelBox.top)}px`;
    seek.style.height = `${Math.round(chatBox.height)}px`;
    // Sit just OUTSIDE the chat's right edge: the rail is 10px wide, so subtracting 22
    // leaves a 12px gutter. Adding it puts the rail on top of the text.
    const gutter = Math.round(panelBox.right - chatBox.right) - 22;
    seek.style.right = `${gutter}px`;
    jump.style.top = `${Math.round(chatBox.bottom - panelBox.top) - 34}px`;
    jump.style.right = `${gutter}px`;
  };

  const paintRail = () => {
    const max = chat.scrollHeight - chat.clientHeight;
    const ratio = max > 0 ? chat.scrollTop / max : 1;
    const visible = chat.scrollHeight > 0 ? chat.clientHeight / chat.scrollHeight : 1;
    const count = Math.max(1, Math.round(visible * TICKS));
    const start = Math.round(ratio * (TICKS - count));
    ticks.forEach((tick, index) => {
      const inView = index >= start && index < start + count;
      const read = index < start;
      tick.className = index === hotIndex ? 'hot' : inView ? 'view' : read ? 'read' : '';
    });
    seek.setAttribute('aria-valuenow', String(Math.round(ratio * 100)));
    const atBottom = max <= 8 || chat.scrollTop >= max - 24;
    jump.dataset.show = atBottom ? 'false' : 'true';
    place();
  };

  const scrubTo = (event) => {
    const box = seek.getBoundingClientRect();
    const ratio = Math.min(1, Math.max(0, (event.clientY - box.top) / box.height));
    const max = chat.scrollHeight - chat.clientHeight;
    if (max > 0) chat.scrollTop = ratio * max;
    paintRail();
  };

  seek.addEventListener('pointerdown', (event) => {
    seek.setPointerCapture(event.pointerId);
    seek.classList.add('is-active');
    scrubTo(event);
    event.preventDefault();
  });
  seek.addEventListener('pointermove', (event) => {
    if (seek.hasPointerCapture(event.pointerId)) { scrubTo(event); return; }
    const box = seek.getBoundingClientRect();
    hotIndex = Math.min(TICKS - 1, Math.max(0, Math.floor(((event.clientY - box.top) / box.height) * TICKS)));
    paintRail();
  });
  seek.addEventListener('pointerleave', () => { hotIndex = -1; paintRail(); });
  const endScrub = (event) => {
    if (seek.hasPointerCapture(event.pointerId)) seek.releasePointerCapture(event.pointerId);
    seek.classList.remove('is-active');
  };
  seek.addEventListener('pointerup', endScrub);
  seek.addEventListener('pointercancel', endScrub);
  seek.addEventListener('keydown', (event) => {
    const step = chat.clientHeight * 0.9;
    if (event.key === 'ArrowUp') { chat.scrollTop -= step; event.preventDefault(); }
    if (event.key === 'ArrowDown') { chat.scrollTop += step; event.preventDefault(); }
    if (event.key === 'Home') { chat.scrollTop = 0; event.preventDefault(); }
    if (event.key === 'End') { chat.scrollTop = chat.scrollHeight; event.preventDefault(); }
  });

  jump.addEventListener('click', () => {
    chat.scrollTo({ top: chat.scrollHeight, behavior: 'smooth' });
  });

  chat.addEventListener('scroll', paintRail, { passive: true });
  window.addEventListener('resize', paintRail);
  if (typeof ResizeObserver === 'function') new ResizeObserver(paintRail).observe(chat);
  new MutationObserver(paintRail).observe(chat, { childList: true });
  paintRail();
  requestAnimationFrame(paintRail);
}
