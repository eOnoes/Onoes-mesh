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