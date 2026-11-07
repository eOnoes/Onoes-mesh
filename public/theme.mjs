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
  if (meta) meta.setAttribute('content', next === 'light' ? '#ffffff' : '#0c0c0d');
  // the button shows the mode you would switch TO, so its label flips with the theme
  const toggle = document.getElementById('theme-toggle');
  if (toggle) {
    const other = next === 'light' ? 'dark' : 'light';
    toggle.setAttribute('aria-label', `switch to ${other}`);
    toggle.setAttribute('title', `switch to ${other}`);
    toggle.replaceChildren(document.createTextNode(next === 'light' ? '[ DARK ]' : '[ LIGHT ]'));
  }
  if (save) {
    try { localStorage.setItem(THEME_KEY, next); } catch { /* storage may be blocked */ }
  }
}

let saved = 'dark';
try { saved = localStorage.getItem(THEME_KEY) || 'dark'; } catch { /* storage may be blocked */ }
applyTheme(saved, false);

const themeToggle = document.getElementById('theme-toggle');
if (themeToggle) {
  themeToggle.addEventListener('click', () => {
    applyTheme(document.documentElement.dataset.theme === 'light' ? 'dark' : 'light', true);
  });
}

// Keep presentation navigation on the app's existing tab controls.
document.querySelectorAll('[data-open-workroom]').forEach(button=>button.addEventListener('click',()=>document.getElementById('tab-workroom')?.click()));
const shellTabs=document.getElementById('rail-tabs');
function showWorkspace(){
  const active=shellTabs?.querySelector('[aria-selected="true"]');
  const name=active?.textContent.trim()||'Overview';
  const title=document.getElementById('ttl');if(title)title.textContent='MESH / '+name.toUpperCase();
  const prompt=document.querySelector('footer>span');if(prompt)prompt.textContent='> mesh / '+name.toLowerCase();
}
if(shellTabs)new MutationObserver(showWorkspace).observe(shellTabs,{subtree:true,attributes:true,attributeFilter:['aria-selected']});
showWorkspace();
