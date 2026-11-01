// Light / dark theme.
//
// Copied from the reference's applyTheme(): dark is the default, anything that is not
// "light" is coerced to "dark", the choice is stored locally, and the browser's own
// color-scheme follows so scrollbars and form controls match.
const THEME_KEY = 'mesh-theme';

function applyTheme(theme, save) {
  const next = theme === 'light' ? 'light' : 'dark';
  document.documentElement.dataset.theme = next;
  const meta = document.querySelector('meta[name="theme-color"]');
  if (meta) meta.setAttribute('content', next === 'light' ? '#e7e7e9' : '#0d0d0f');
  for (const button of document.querySelectorAll('[data-theme-value]')) {
    button.setAttribute('aria-checked', String(button.dataset.themeValue === next));
  }
  if (save) {
    try { localStorage.setItem(THEME_KEY, next); } catch { /* storage may be blocked */ }
  }
}

let saved = 'dark';
try { saved = localStorage.getItem(THEME_KEY) || 'dark'; } catch { /* storage may be blocked */ }
applyTheme(saved, false);

for (const button of document.querySelectorAll('[data-theme-value]')) {
  button.addEventListener('click', () => applyTheme(button.dataset.themeValue, true));
}