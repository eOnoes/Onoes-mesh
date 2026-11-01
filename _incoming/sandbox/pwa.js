(() => {
  'use strict';
  const KEY = 'mesh-refresh-draft-v1';
  const install = document.getElementById('mesh-install');
  const refresh = document.getElementById('mesh-refresh');
  const status = document.getElementById('mesh-app-status');
  let installPrompt = null;
  const standalone = () => matchMedia('(display-mode: standalone)').matches || navigator.standalone === true;
  const say = text => { status.textContent = text; };
  function paintInstall() {
    install.textContent = standalone() ? 'installed' : (installPrompt ? 'install' : 'how to install');
    install.disabled = standalone();
  }
  window.addEventListener('beforeinstallprompt', event => {
    event.preventDefault(); installPrompt = event; paintInstall();
  });
  window.addEventListener('appinstalled', () => {
    installPrompt = null; paintInstall(); say('Mesh installed. Open it from your home screen or app list.');
  });
  install.addEventListener('click', async () => {
    if (!installPrompt) {
      say('Open this address in Chrome (not Telegram), then Chrome menu → Add to home screen → Install. On iPhone use Safari → Share → Add to Home Screen.');
      return;
    }
    const prompt = installPrompt; installPrompt = null;
    try { await prompt.prompt(); const result = await prompt.userChoice;
      say(result.outcome === 'accepted' ? 'Installation accepted. Check your home screen or app list.' : 'Installation cancelled. You can still use Mesh in Chrome.');
    } catch (_) { say('Use the browser menu to install Mesh.'); }
    paintInstall();
  });
  function unsavedWork() {
    if (busy || photoUploading || chatRun === 'pending') return 'Wait until the current send or upload finishes.';
    if (staged || stagedPhoto || replyTo) return 'Send or clear the staged attachment or reply before refreshing. Your typed text can be kept.';
    if (ui.editing || document.querySelector('#add-form:not([hidden])')) return 'Save or cancel the open To-do card before refreshing.';
    if ([...document.querySelectorAll('#settings textarea, #thread textarea, #thread input')].some(el => el.value)) return 'Finish or clear the open decision text before refreshing.';
    // A proactive poll may be in flight when the user hits refresh. Abandon the
    // in-memory cursor (the server replay reconstructs it from the durable log) and
    // refuse the refresh while a send is genuinely in flight, so the in-flight run
    // is never clobbered by a reload.
    if (chatRun === 'uncertain') return 'An earlier send is still being recovered. Wait for it to resolve before refreshing.';
    // The proactive subscription (EventSource stream and/or bounded poll) is only
    // abandoned when the refresh is actually going to run. A refused refresh (any
    // of the warnings above) leaves it untouched, so live delivery never drops
    // just because the user tried to refresh while something was in flight.
    return '';
  }
  function releaseProactiveDelivery() {
    if (typeof stopProactive === 'function') stopProactive();
    else {
      // `proactiveStream` and `proactiveTimer` are app.js free globals. If the
      // normal helper is unavailable, close the real stream directly rather than
      // only clearing a timer and leaving live delivery attached to a dead page.
      if (typeof proactiveTimer === 'number' && proactiveTimer) { clearTimeout(proactiveTimer); proactiveTimer = 0; }
      if (typeof proactiveStream !== 'undefined' && proactiveStream) { proactiveStream.close(); proactiveStream = null; }
    }
  }

  async function hardRefresh() {
    const warning = unsavedWork();
    if (warning) { say(warning); return false; }
    releaseProactiveDelivery();
    refresh.disabled = true;
    try {
      await roomBootstrap;
      const next = new URL(location.href);
      next.searchParams.set('mesh-refresh', String(Date.now()));
      const response = await fetch(next.pathname + next.search, {cache: 'reload'});
      if (!response.ok || !(response.headers.get('Content-Type') || '').includes('text/html')) throw new Error('Connection unavailable');
      sessionStorage.setItem(KEY, JSON.stringify({room: chatRoom(), text: document.getElementById('draft').value,
        goal: document.getElementById('goal-arm').getAttribute('aria-pressed') === 'true'}));
      // Do not clear localStorage, native run IDs, media or backend history.
      location.replace(next.href);
      return true;
    } catch (_) {
      say('Refresh did not run. Check Tailscale and the PC connection; your draft is still here.');
      refresh.disabled = false; return false;
    }
  }
  async function restoreDraft() {
    let saved;
    try { const raw = sessionStorage.getItem(KEY); if (!raw) return false; saved = JSON.parse(raw);
      await roomBootstrap;
      if (saved.room !== chatRoom()) { say('An unsent draft is saved for another room. Select that room to restore it.'); return false; }
      const box = document.getElementById('draft');
      if (box.value) { say('A previous refresh draft is saved; clear the composer to restore it.'); return false; }
      box.value = typeof saved.text === 'string' ? saved.text : '';
      armGoal(saved.goal === true); fitDraft(); paintSlash();
      sessionStorage.removeItem(KEY); say('Latest page loaded. Your text draft was restored.'); return true;
    } catch (_) { say('A saved draft could not be restored yet. It has not been removed.'); return false; }
  }
  refresh.addEventListener('click', hardRefresh);
  document.addEventListener('mesh-room-restored', restoreDraft);
  paintInstall();
  if (isSecureContext && 'serviceWorker' in navigator) {
    navigator.serviceWorker.register('/mesh-sw.js', {scope: '/', updateViaCache: 'none'})
      .catch(() => say('App registration unavailable. You can still use Mesh in the browser.'));
  }
  restoreDraft();
  window.meshPwa = {hardRefresh, restoreDraft};
})();
