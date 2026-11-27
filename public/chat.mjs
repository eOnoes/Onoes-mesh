import {createNimsChatReader} from './nims-chat.mjs';
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
  const nativeReader=createNimsChatReader({root:document.getElementById('relay-nims-chats'),request});
  const taskProgress=createRelayTaskProgress({root:document.getElementById('relay-task-progress'),button:document.getElementById('relay-task-progress-open'),request,document});
  const select=document.getElementById('relay-chat-agent');
  const current=document.getElementById('relay-chat-current');
  const refreshButton=document.getElementById('relay-chat-refresh');
  const olderButton=document.getElementById('relay-chat-older');
  const destination=document.getElementById('relay-chat-destination');
  const status=document.getElementById('relay-chat-status');
  const send=document.getElementById('relay-send');
  const attach=document.getElementById('relay-add-files');
  let busy=false,lastPaint='',lastAgents='',lastDestination='',lastTarget='',lastFirst=null,core;
  function draw(state) {
    agentName=state.destination?.name || 'Relay';
    const signature=JSON.stringify(state.agents);
    if(signature!==lastAgents){
      lastAgents=signature;select.replaceChildren();
      const empty=document.createElement('option');empty.value='';empty.textContent='Choose an agent…';select.append(empty);
      for(const peer of state.agents){const option=document.createElement('option');option.value=peer.id;if(peer.id==='nims'){option.textContent='Nims · use project chats above';option.disabled=true;}else{option.textContent=`${peer.name} · ${peer.status}${peer.sessionId?'':' · no conversation'}`;option.disabled=!peer.sessionId;}select.append(option);}
    }
    const legacyNims=state.destination?.agentId==='nims';
    select.value=state.destination?.agentId || '';
    destination.textContent=state.destination ? `Destination: ${state.destination.name} (${state.destination.agentId}) · conversation ${state.destination.sessionId} · ${state.live?'current observation':'not confirmed current'}${state.observedAt?' · checked '+state.observedAt:''}` : 'Choose a destination. No agent is selected automatically.';
    status.textContent=legacyNims?'For Nims, use project chats above. This older Relay conversation is read-only.':state.note;
    if(composer.value!==state.draft)composer.value=state.draft;
    composer.placeholder=legacyNims?'Open Nims project chats above to message Nims':state.destination?`${agentName} · type a message…`:'Choose an agent before writing a message';
    composer.disabled=busy||!state.available||state.initializing||state.sending||!state.destination||legacyNims;
    send.disabled=busy||!state.canSend||!state.draft.trim()||legacyNims;
    select.disabled=busy||!state.available||state.initializing||state.sending;
    current.disabled=select.disabled||!state.destination||legacyNims;
    refreshButton.disabled=busy||!state.available||state.initializing||state.sending;
    if(olderButton){olderButton.hidden=!state.hasOlder;olderButton.disabled=busy||!state.available||state.loadingOlder||state.sending;olderButton.textContent=state.loadingOlder?'Loading older messages…':'Load older messages';}
    attach.disabled=true;
    const legacyId=document.getElementById('relay-message-id');if(legacyId)legacyId.disabled=true;
    const painted=JSON.stringify([state.destination,state.messages]);
    if(painted!==lastPaint){
      const target=JSON.stringify(state.destination && [state.destination.agentId,state.destination.sessionId]);
      const follow=target!==lastDestination || chat.scrollHeight-chat.clientHeight-chat.scrollTop<=32;
      const position=chat.scrollTop,height=chat.scrollHeight;
      const prepended=state.messages.length&&lastFirst&&state.messages[0].id!==lastFirst&&state.messages.some(m=>m.id===lastFirst);
      lastPaint=painted;lastDestination=target;paint(state.messages);
      lastFirst=state.messages[0]?.id;
      if(prepended&&target===lastTarget)chat.scrollTop=position+chat.scrollHeight-height;
      else if(follow)toBottom();else chat.scrollTop=position;
      lastTarget=target;
    }
  }
  let storage;try{storage=sessionStorage;}catch{storage={getItem(){return null;},setItem(){throw Error('Browser retry storage unavailable. Nothing was sent.');},removeItem(){}};}
  core=createRelayConversation({request,storage,onChange:draw});
  composer.addEventListener('input',()=>core.setDraft(composer.value));
  select.addEventListener('change',()=>{if(!busy)core.select(select.value);});
  current.addEventListener('click',()=>{if(!busy&&core.state().destination)core.select(core.state().destination.agentId);});
  refreshButton.addEventListener('click',()=>{if(!busy)core.refresh();});
  olderButton?.addEventListener('click',()=>{if(!busy)core.loadOlder();});
  form.addEventListener('submit',async event=>{event.preventDefault();if(busy)return;await core.send();});
  const panel=document.getElementById('panel-relay');
  const refresh=()=>{if(!panel?.hidden&&!document.hidden&&!busy){taskProgress.refresh();return core.refresh();}};
  setInterval(refresh,5000);
  if(panel)new MutationObserver(()=>{if(!panel.hidden){toBottom();refresh();}}).observe(panel,{attributes:true,attributeFilter:['hidden']});
  draw(core.state());
  const messenger=createRelayMessenger({document});
  return {refresh,setAvailable(value,isBusy=false){busy=isBusy;nativeReader.setAvailable(value);taskProgress.setAvailable(value,isBusy);core.setAvailable(value);draw(core.state());messenger.setAvailable(value);},clear(){nativeReader.clear();taskProgress.clear();core.setAvailable(false);draw(core.state());messenger.setAvailable(false);}};
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

// Relay messaging shell: DOM presentation only. It MOVES the existing nodes (forms,
// controls, IDs and captured listeners stay intact) into a frame with a header and two
// native sliding dialogs. It never clones, never renders messages, never sends, never
// polls, and does no work at module top level.
export function createRelayMessenger({document}) {
  const panel = document.getElementById && document.getElementById('panel-relay');
  if (!panel || typeof panel.querySelector !== 'function') return {setAvailable(){}};
  if (!document.defaultView || typeof document.defaultView.getComputedStyle !== 'function') return {setAvailable(){}};
  const win = document.defaultView;
  let available = false;
  let availabilityInitialized = false;
  let pickerSignature = '';

  const nativeRoot = document.getElementById('relay-nims-chats');
  const select = document.getElementById('relay-chat-agent');
  const historyEl = document.getElementById('relay-chat');
  const chatStatus = document.getElementById('relay-chat-status');
  const sendForm = document.getElementById('relay-form');
  const box = select ? select.closest('.box') : null;
  const rook = document.getElementById('rook-notices');
  const overviewTab = document.getElementById('tab-overview');

  // Progressive support: without a core agent select there is nothing to mirror.
  if (!select) return {setAvailable(){}};

  const frame = document.createElement('section');
  frame.className = 'relay-messenger';
  const header = document.createElement('div');
  header.className = 'relay-messenger-header';
  const historyToggle = document.createElement('button');
  historyToggle.type = 'button'; historyToggle.id = 'relay-history-toggle';
  historyToggle.textContent = '≡'; historyToggle.setAttribute('aria-label', 'Chats and projects');
  historyToggle.setAttribute('aria-haspopup', 'dialog'); historyToggle.setAttribute('aria-expanded', 'false');
  const title = document.createElement('span');
  title.className = 'relay-messenger-title'; title.textContent = 'Relay';
  const agentToggle = document.createElement('button');
  agentToggle.type = 'button'; agentToggle.id = 'relay-agent-toggle';
  agentToggle.textContent = 'Choose agent'; agentToggle.setAttribute('aria-haspopup', 'dialog');
  agentToggle.setAttribute('aria-expanded', 'false'); agentToggle.dataset.agentId = '';
  header.append(historyToggle, title, agentToggle);

  const ordinaryBody = document.createElement('div');
  ordinaryBody.className = 'relay-messenger-body';
  ordinaryBody.append(historyEl, chatStatus, sendForm);
  const nativeBody = document.createElement('div');
  nativeBody.className = 'relay-messenger-body relay-messenger-native';
  nativeBody.hidden = true;

  function makeDrawer(id, label, opener) {
    const dialog = document.createElement('dialog');
    dialog.id = id; dialog.className = 'relay-messenger-drawer';
    dialog.setAttribute('aria-label', label);
    const bar = document.createElement('div');
    bar.className = 'relay-messenger-drawer-bar';
    const close = document.createElement('button');
    close.type = 'button'; close.className = 'relay-messenger-drawer-close';
    close.textContent = 'Close'; close.setAttribute('aria-label', 'Close ' + label);
    bar.append(close);
    const content = document.createElement('div');
    content.className = 'relay-messenger-drawer-content';
    dialog.append(bar, content);
    close.addEventListener('click', () => dialog.close());
    dialog.addEventListener('click', (event) => { if (event.target === dialog) dialog.close(); });
    // Native close (button, Escape, backdrop): reflect state on the opener and return
    // focus to it. No focus-set tracking; the opener is the only focus target.
    dialog.addEventListener('close', () => {
      opener.setAttribute('aria-expanded', 'false');
      if (available && typeof opener.focus === 'function') {
        try { opener.focus({ preventScroll: true }); } catch { opener.focus(); }
      }
    });
    return {dialog,content,close};
  }
  const agentDrawer = makeDrawer('relay-agent-drawer', 'Choose agent', agentToggle);
  const historyDrawer = makeDrawer('relay-history-drawer', 'Chats and projects', historyToggle);

  const agents = document.createElement('div');
  agents.className = 'relay-messenger-agents';
  agentDrawer.content.append(agents);

  const nativeNav = document.createElement('div');
  nativeNav.className = 'relay-messenger-native-nav';
  nativeNav.hidden = true;
  const ordinaryNav = document.createElement('div');
  ordinaryNav.className = 'relay-messenger-ordinary-nav';
  const back = document.createElement('button');
  back.type = 'button'; back.className = 'relay-messenger-back';
  back.textContent = 'Back to Mesh';
  back.addEventListener('click', () => {
    historyDrawer.dialog.close();
    if (overviewTab && typeof overviewTab.click === 'function') overviewTab.click();
  });
  historyDrawer.content.append(nativeNav, ordinaryNav, back);

  const more = document.createElement('details');
  more.className = 'relay-messenger-more';
  const moreSummary = document.createElement('summary');
  moreSummary.textContent = 'More';
  more.append(moreSummary);
  ordinaryNav.append(more);

  // Move EXISTING nodes only. The native details root keeps its identity; its summary
  // stays in the root, other native controls move into the Chats dialog nav AFTER the
  // native reader initialized them, so captured refs/listeners survive.
  const nativeNavNodes = [];
  if (nativeRoot) {
    for (const child of Array.from(nativeRoot.children)) {
      if (child.tagName === 'SUMMARY') continue;
      if (child.matches?.('[data-nims-history],[data-nims-compose],[data-nims-new-form],[data-nims-send-note],[data-nims-status]')) continue;
      nativeNavNodes.push(child);
    }
    // Move nav nodes immediately, BEFORE mounting the frame: the reader is already
    // initialized above, so captured references and listeners survive the move.
    if (nativeNavNodes.length) nativeNav.append(...nativeNavNodes);
    nativeBody.append(nativeRoot);
    nativeRoot.open = false;
  }
  if (box) ordinaryNav.prepend(box);
  for (const node of [document.getElementById('relay-task-progress-open'),document.querySelector('.relay-conversation-details')]) if (node) more.append(node);
  if (rook) more.append(rook);

  frame.append(header, ordinaryBody, nativeBody, agentDrawer.dialog, historyDrawer.dialog);
  panel.append(frame);

  const nativeVisible = () => !!(nativeRoot && !nativeBody.hidden);
  // Captured before any node moves: the transcript actually on screen.
  const nativeHistory = nativeRoot ? nativeRoot.querySelector('[data-nims-history]') : null;
  const activeTranscript = () => nativeVisible() ? nativeHistory : historyEl;
  // Preserve the native reader's captured controls while using a direct flex viewport.
  for (const selector of ['[data-nims-history]','[data-nims-status]','[data-nims-send-note]','[data-nims-compose]','[data-nims-new-form]']) {
    const node = document.querySelector(selector);
    if (node) nativeBody.append(node);
  }
  if (nativeRoot) nativeRoot.hidden = true;
  const nativeSend = document.querySelector('[data-nims-send]');
  if (nativeSend) {
    nativeSend.setAttribute('aria-label','Send to Nims');
    nativeSend.textContent = '↑';
  }
  const composerInputs = [document.getElementById('relay-text'),document.getElementById('nims-message')].filter(Boolean);
  function sizeInput(input) {
    input.style.height = 'auto';
    input.style.height = Math.min(120,Math.max(44,input.scrollHeight))+'px';
  }
  for (const input of composerInputs) {
    input.rows = 1;
    input.style.height = '44px';
    input.addEventListener('input',()=>sizeInput(input));
  }

  function showOrdinary() {
    nativeBody.hidden = true; if (nativeRoot) nativeRoot.open = false; ordinaryBody.hidden = false;
    // Presentation only: never scroll, read or send here.
    updateDrawerNav(); measureComposer(); syncLatest();
  }
  function showNative() {
    ordinaryBody.hidden = true; nativeBody.hidden = false; if (nativeRoot) nativeRoot.open = true;
    updateDrawerNav(); measureComposer(); syncLatest();
  }

  function syncNativeNav() {
    if (!nativeRoot) return;
    for (const child of Array.from(nativeRoot.children)) {
      if (child.tagName === 'SUMMARY') continue;
      if (nativeNavNodes.includes(child)) nativeNav.append(child);
    }
  }

  function setBadge(id, label) {
    agentToggle.textContent = label;
    agentToggle.dataset.agentId = id || '';
  }

  function optionDisabled(option) {
    return !available || !!select.disabled || !!option.disabled;
  }

  function rebuildAgents() {
    const signature = JSON.stringify([available,select.disabled,Array.from(select.options || [],o=>[o.value,o.textContent,o.disabled])]);
    if (available && signature === pickerSignature) return;
    pickerSignature = signature;
    agents.replaceChildren();
    if (!available) return;
    for (const option of Array.from(select.options || [])) {
      const value = option.value;
      if (!value) continue;
      if (value === 'nims') continue; // legacy option: skip entirely, never drives the native button
      const button = document.createElement('button');
      button.type = 'button'; button.className = 'relay-messenger-agent';
      button.dataset.agentId = value;
      const name = (option.textContent || '').split(' · ')[0].trim();
      button.textContent = name;
      button.disabled = optionDisabled(option);
      button.addEventListener('click', () => {
        if (button.disabled) return;
        showOrdinary();
        if (select.value !== value) {
          select.value = value;
          if (win.Event) select.dispatchEvent(new win.Event('change')); // the existing handler reads; it does not send
        }
        setBadge(value, name);
        agentDrawer.dialog.close();
      });
      agents.append(button);
    }
    if (nativeRoot) {
      const button = document.createElement('button');
      button.type = 'button'; button.className = 'relay-messenger-agent';
      button.dataset.agentId = 'nims';
      button.textContent = 'Nims'; // canonical spelling; independent of the legacy option
      button.disabled = !available; // native root presence, not the select, gates Nims
      button.addEventListener('click', () => {
        if (button.disabled) return;
        showNative();
        setBadge('nims', 'Nims');
        agentDrawer.dialog.close();
      });
      agents.append(button);
    }
  }

  function syncLatest() {
    const transcript = activeTranscript();
    if (!available || !transcript || !agentToggle.dataset.agentId) { latest.hidden = true; return; }
    const overflow = transcript.scrollHeight - transcript.clientHeight - transcript.scrollTop;
    latest.hidden = !(overflow > 120);
  }

  const latest = document.createElement('button');
  latest.type = 'button'; latest.id = 'relay-messenger-latest';
  latest.textContent = '↓'; latest.setAttribute('aria-label', 'Jump to latest message');
  latest.hidden = true;
  latest.addEventListener('click', () => {
    const transcript = activeTranscript();
    if (!available || !transcript || !agentToggle.dataset.agentId) return;
    transcript.scrollTop = transcript.scrollHeight;
    latest.hidden = true;
  });
  frame.append(latest);

  function measureComposer() {
    try {
      let total = 0;
      let measured = false;
      if (!ordinaryBody.hidden) {
        for (const node of [sendForm, chatStatus]) {
          if (!node || node.hidden) continue;
          const height = node.getBoundingClientRect().height;
          if (Number.isFinite(height)) { total += height; measured = true; }
        }
      } else if (nativeRoot) {
        const newForm = document.querySelector('[data-nims-new-form]');
        const formTarget = (newForm && !newForm.hidden) ? newForm : document.querySelector('[data-nims-compose]');
        if (formTarget && !formTarget.hidden) {
          const height = formTarget.getBoundingClientRect().height;
          if (Number.isFinite(height)) { total += height; measured = true; }
        }
        for (const sel of ['[data-nims-send-note]', '[data-nims-status]']) {
          const node = document.querySelector(sel);
          if (!node || node.hidden) continue;
          const height = node.getBoundingClientRect().height;
          if (Number.isFinite(height)) { total += height; measured = true; }
        }
      }
      if (measured) latest.style.bottom = Math.round(total + 16)+'px';
    } catch { /* safe fallback: CSS default */ }
  }

  if (win.MutationObserver) {
    // Observe the AUTHORITATIVE select subtree (never the generated button list) so the
    // drawer buttons track real option/disabled changes without observer loops.
    new win.MutationObserver(rebuildAgents).observe(select, { childList: true, attributes: true, attributeFilter: ['disabled'] });
    if (nativeRoot) new win.MutationObserver(syncNativeNav).observe(nativeRoot, { childList: true });
    // Scroll/content observers on BOTH transcripts: they only update the arrow and
    // re-measure; they never jump the scroll position.
    for (const transcript of [historyEl, nativeHistory]) {
      if (!transcript) continue;
      transcript.addEventListener('scroll', syncLatest, { passive: true });
      new win.MutationObserver(() => { syncLatest(); measureComposer(); })
        .observe(transcript, { childList: true, subtree: true });
    }
  }
  if (win.ResizeObserver) {
    // Observe both actual active forms and status/note nodes, not the textarea alone.
    const observer = new win.ResizeObserver(() => { measureComposer(); syncLatest(); });
    const watched = [sendForm, chatStatus];
    if (nativeRoot) {
      watched.push(document.querySelector('[data-nims-compose]'));
      watched.push(document.querySelector('[data-nims-new-form]'));
      watched.push(document.querySelector('[data-nims-send-note]'));
      watched.push(document.querySelector('[data-nims-status]'));
    }
    for (const node of watched) if (node) observer.observe(node);
  }
  measureComposer();

  function updateDrawerNav() {
    nativeNav.hidden = !available || !nativeVisible();
    ordinaryNav.hidden = !available || nativeVisible();
  }
  if (nativeRoot && win.MutationObserver) {
    new win.MutationObserver(updateDrawerNav).observe(nativeRoot, { attributes: true, attributeFilter: ['open'] });
  }
  // Existing native selection closes the Chats drawer; the existing reader handles it.
  const nativeSelect = document.getElementById('nims-native-conversation');
  nativeSelect?.addEventListener('change', () => historyDrawer.dialog.close());
  // The existing native New chat button keeps its own handler; this only closes the drawer.
  document.querySelector('[data-nims-new]')?.addEventListener('click', () => historyDrawer.dialog.close());

  // Lock workspace: presentation-only button in the Chats drawer; it delegates to the
  // existing demo-end control. No new endpoint, auth or state policy.
  const lockButton = document.createElement('button');
  lockButton.type = 'button'; lockButton.id = 'relay-messenger-lock';
  lockButton.textContent = 'Lock workspace';
  lockButton.addEventListener('click', () => {
    if (!available) return;
    agentDrawer.dialog.close();
    historyDrawer.dialog.close();
    document.getElementById('demo-end')?.click();
  });
  historyDrawer.content.append(lockButton);

  historyToggle.addEventListener('click', () => {
    updateDrawerNav();
    if (!historyDrawer.dialog.open) { historyToggle.setAttribute('aria-expanded', 'true'); historyDrawer.dialog.showModal(); }
  });
  agentToggle.addEventListener('click', () => {
    if (!available) return;
    rebuildAgents();
    if (!agentDrawer.dialog.open) { agentToggle.setAttribute('aria-expanded', 'true'); agentDrawer.dialog.showModal(); }
  });

  function fitViewport(height, top) {
    for (const node of [frame,agentDrawer.dialog,historyDrawer.dialog]) {
      node.style.height = Math.round(height)+'px';
      node.style.top = Math.round(top)+'px';
      if (node !== frame) node.style.maxHeight = Math.round(height)+'px';
    }
  }
  if (win.visualViewport) {
    const setViewport = () => {
      const viewport = win.visualViewport;
      fitViewport(viewport.height,viewport.offsetTop || 0);
      measureComposer(); syncLatest();
    };
    win.visualViewport.addEventListener('resize', setViewport);
    win.visualViewport.addEventListener('scroll', setViewport);
    win.addEventListener('resize', setViewport);
    setViewport();
  } else {
    const setViewport = () => {
      fitViewport(win.innerHeight || 0,0);
      measureComposer(); syncLatest();
    };
    win.addEventListener('resize', setViewport);
    setViewport();
  }

  function setAvailable(value) {
    const next = !!value;
    if (availabilityInitialized && next === available) {
      if (available) { rebuildAgents(); measureComposer(); syncLatest(); }
      return;
    }
    availabilityInitialized = true;
    available = next;
    if (!available) {
      if (agentDrawer.dialog.open) agentDrawer.dialog.close();
      if (historyDrawer.dialog.open) historyDrawer.dialog.close();
      setBadge('', 'Choose agent');
      if (nativeRoot) {
        nativeRoot.open = false;
        const newForm = document.querySelector('[data-nims-new-form]');
        if (newForm) newForm.hidden = true; // explicit Cancel only; no auto-create
      }
      nativeBody.hidden = true;
      ordinaryBody.hidden = false;
      latest.hidden = true;
      agents.replaceChildren(); // names not retained across sign-out
      historyToggle.disabled = false;
      lockButton.disabled = true;
      nativeNav.hidden = ordinaryNav.hidden = true;
      agentToggle.disabled = true;
      historyToggle.setAttribute('aria-expanded', 'false');
      agentToggle.setAttribute('aria-expanded', 'false');
      return;
    }
    historyToggle.disabled = false;
    lockButton.disabled = false;
    agentToggle.disabled = false;
    rebuildAgents(); // rebuild from actual options only; no auto-selection, no read, no send
    measureComposer();
    syncLatest();
    updateDrawerNav();
  }

  setAvailable(false); // header starts disabled; no private option names survive the lock

  // Only the panel's hidden attribute is observed. Hidden: close drawers and close the
  // native root so its hidden polls stop. Shown: re-open nativeRoot only if available
  // AND Nims is already the selected agent — never choose an agent or send.
  if (win.MutationObserver && panel) {
    new win.MutationObserver(() => {
      if (panel.hidden) {
        if (agentDrawer.dialog.open) agentDrawer.dialog.close();
        if (historyDrawer.dialog.open) historyDrawer.dialog.close();
        if (nativeRoot) nativeRoot.open = false;
        updateDrawerNav();
      } else if (available && nativeRoot && agentToggle.dataset.agentId === 'nims') {
        nativeRoot.open = true;
        updateDrawerNav();
      }
    }).observe(panel, { attributes: true, attributeFilter: ['hidden'] });
  }
  return {setAvailable};
}
