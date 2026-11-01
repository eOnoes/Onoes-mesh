// Text size control.
//
// Relay offers three steps (small / default / large). The tokens already exist in
// shared/tokens.css and are asserted by test/check.mjs, so this file does one job:
// flip data-text-size on <html> and remember the choice.
//
// It lives apart from public/app.js on purpose - that module is executed against a
// stubbed document by four tests, and adding a control there would put localStorage
// and a new element in their path for no reason.
const KEY = 'mesh-text-size';
const STEPS = ['small', 'default', 'large'];
const root = document.documentElement;

function apply(size) {
  const next = STEPS.includes(size) ? size : 'default';
  if (next === 'default') root.removeAttribute('data-text-size');
  else root.setAttribute('data-text-size', next);
  const button = document.getElementById('text-size');
  if (button) {
    button.textContent = 'text: ' + next;
    button.setAttribute('aria-label', 'Text size is ' + next + '. Activate to change.');
  }
}

let saved = 'default';
try { saved = localStorage.getItem(KEY) || 'default'; } catch { /* storage may be blocked */ }
apply(saved);

const button = document.getElementById('text-size');
if (button) {
  button.addEventListener('click', () => {
    const current = root.getAttribute('data-text-size') || 'default';
    const next = STEPS[(STEPS.indexOf(current) + 1) % STEPS.length];
    apply(next);
    try { localStorage.setItem(KEY, next); } catch { /* storage may be blocked */ }
  });
}
// Navigation rail collapse (desktop). Same storage discipline as the text size: the
// preference is local, best-effort, and never blocks rendering if storage is refused.
const RAIL_KEY = 'mesh-rail-collapsed';
const shellEl = document.querySelector('.shell');
const railButton = document.getElementById('rail-toggle');
function applyRail(collapsed) {
  if (!shellEl) return;
  shellEl.classList.toggle('rail-collapsed', collapsed);
  if (railButton) {
    railButton.setAttribute('aria-expanded', String(!collapsed));
    railButton.textContent = collapsed ? '»' : '«';
    railButton.setAttribute('title', collapsed ? 'show navigation' : 'collapse navigation');
  }
}
let railSaved = false;
try { railSaved = localStorage.getItem(RAIL_KEY) === '1'; } catch { /* storage may be blocked */ }
applyRail(railSaved);
if (railButton) {
  railButton.addEventListener('click', () => {
    const next = !(shellEl && shellEl.classList.contains('rail-collapsed'));
    applyRail(next);
    try { localStorage.setItem(RAIL_KEY, next ? '1' : '0'); } catch { /* storage may be blocked */ }
  });
}
// Copy all: put the active panel's text on the clipboard. Relay's copy-all copies the
// whole conversation; the equivalent here is whatever panel you are looking at.
const copyButton = document.getElementById('copy-all');
if (copyButton) {
  copyButton.addEventListener('click', async () => {
    const panel = document.querySelector('[role="tabpanel"]:not([hidden])');
    const text = panel ? panel.innerText.trim() : '';
    if (!text) return;
    try {
      await navigator.clipboard.writeText(text);
      copyButton.classList.add('oky');
      copyButton.textContent = 'copied';
      setTimeout(() => { copyButton.classList.remove('oky'); copyButton.textContent = 'copy all'; }, 1400);
    } catch {
      copyButton.textContent = 'copy failed';
      setTimeout(() => { copyButton.textContent = 'copy all'; }, 1400);
    }
  });
}