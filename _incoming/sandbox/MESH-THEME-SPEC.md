# Mesh Theme and Terminal Layout Specification

## Purpose

Mesh should feel like a private, industrial terminal: calm, dense, readable, practical, and built for operating a local machine. It should not look like a glossy SaaS dashboard or a generic mobile chat app.

The existing Mesh PWA remains the working surface. Preserve its behavior and layout. This specification defines the visual system and the light/dark theme toggle.

## Design principles

- Dark mode is the default.
- Prefer information density over decoration.
- Use hard edges and restrained borders instead of large shadows or rounded cards.
- Keep the main experience narrow, centered, and phone-safe.
- Make state obvious through semantic color, not constant animation.
- Use monospace typography for technical data and system output.
- Use ordinary system sans-serif typography for human-readable chat and descriptions.
- Do not introduce a frontend framework or bundler. Mesh remains vanilla HTML/CSS/JavaScript.
- Do not duplicate content to create expanded views.
- Do not make the page wider than the phone viewport.

## Dark theme palette

```css
:root,
[data-theme="dark"] {
  --bg: #070708;
  --surface: #0d0d0f;
  --surface-raised: #161618;
  --surface-active: #1d1d21;
  --line: #2a2a2e;
  --line-strong: #3b3b42;

  --text: #f2f2f2;
  --text-muted: #9a9aa3;
  --text-dim: #6e6e76;

  --user: #7ec8ff;
  --agent: #c1c1c8;
  --cyan: #3ddcff;
  --lime: #39ff14;
  --amber: #e0b85a;
  --yellow: #e6c200;
  --red: #d64545;
  --focus: #7ec8ff;

  --shadow: none;
  --radius: 0px;
}
```

### Semantic color rules

- **User/Eddie content:** cyan or pale blue. Use `--user`.
- **Echo/agent content:** neutral light gray. Use `--agent`; do not make ordinary agent messages bright green.
- **Running/active:** acid lime. Use `--lime` only when work is actually running.
- **Waiting/decision required:** amber or yellow.
- **Stopped/failed/blocked:** restrained red.
- **Technical symbols, numbers, IDs, and selected accents:** cyan.
- **Disabled/unavailable:** dim gray, never ambiguous green.

Color must communicate state. Do not use lime for an idle goal, a merely configured card, or a successful historical result.

## Light theme palette

```css
[data-theme="light"] {
  --bg: #f0f1f3;
  --surface: #f8f9fa;
  --surface-raised: #ffffff;
  --surface-active: #e8ebef;
  --line: #c8ccd2;
  --line-strong: #9ea5ae;

  --text: #1a1c20;
  --text-muted: #555b64;
  --text-dim: #777e88;

  --user: #056b9c;
  --agent: #4b5058;
  --cyan: #007da8;
  --lime: #208a16;
  --amber: #9a6500;
  --yellow: #856d00;
  --red: #b32626;
  --focus: #056b9c;

  --shadow: none;
  --radius: 0px;
}
```

Light mode is a real readable theme, not a simple color inversion. Preserve the semantic meaning of cyan, lime, amber, yellow, and red while adjusting them for contrast against light surfaces.

## Typography

- **Ordinary interface and chat:** system sans-serif, such as `Segoe UI, system-ui, sans-serif`.
- **Technical output:** `Cascadia Mono, Consolas, ui-monospace, monospace`.
- Use monospace for:
  - logs
  - model names and engine names
  - PIDs, ports, IDs, timestamps, counters, and percentages
  - status lines and diagnostic values
  - terminal-style dashboard readouts
- Keep body text readable and not artificially condensed.
- Avoid all-caps paragraphs. Small uppercase labels are acceptable for section headers.

## Terminal layout

### Overall shell

- Full-height application shell.
- Narrow centered column on desktop.
- Full-width column on phones with safe-area padding.
- Fixed/simple header and navigation.
- Main content scrolls independently.
- Composer or primary action area stays at the bottom of the active pane.
- No horizontal scrolling.

### Cards and panes

- Use compact rectangular cards with hard edges.
- Borders should be thin and visible but not bright.
- Avoid large drop shadows, excessive gradients, glossy glass effects, and pill-shaped controls.
- Technical panes may use a slightly raised surface and monospace text.
- Long text scrolls within its own pane instead of expanding the whole page.
- Image and document viewers remain inside the Mesh content column, not full-browser overlays.

### Controls

Keep controls on their own line and preserve the bracketed terminal style:

```text
[ edit - play - trash ]
```

- The title owns the top line.
- Controls sit below or at the bottom-right of the card.
- Do not let controls push the title or important text off-screen.
- Keep touch targets at least 44px high.
- Use visible keyboard focus in both themes.
- Do not add a control merely for visual completeness; every control must have a verified backend effect.

### System dashboard style

Use a compact readout such as:

```text
MESH / SYSTEM
────────────────────────────────────────
GPU   62°C   145W   fan 45%   VRAM 72%
CPU   48°C    30W   fan 30%   RAM 68%
C:    74% free 412 GB
D:    41% free 1.8 TB

LOCAL LLM
────────────────────────────────────────
STRATA  Qwen3.8-Flash-Next IQ3_S  loaded
        ctx 196608   GPU/RAM   [open]
```

Use Unicode box drawing sparingly. The dashboard should feel like a modern terminal, not a literal DOS screen.

## Light/dark toggle

### Behavior

- Add a compact accessible Light/Dark toggle to the Mesh configuration or system-dashboard header.
- Dark mode is the default when no preference exists.
- Do not let the browser or OS preference override the first-launch default.
- Persist the user’s choice in `localStorage`, for example:

```text
mesh-theme = dark | light
```

- Restore the choice before the first paint when possible to avoid a flash of the wrong theme.
- Switching themes must not reload the page.
- Switching themes must preserve:
  - drafts
  - cards
  - navigation section
  - open card
  - scroll position
  - pending read-only metric stream
- Do not store chat content, approvals, attachments, or credentials in the theme preference.
- The toggle must work on desktop and phone widths.

### Implementation shape

Use one markup tree and CSS variables:

```html
<button id="theme-toggle" type="button" aria-label="Switch to light theme">
  <span class="theme-icon" aria-hidden="true">☾</span>
  <span class="theme-label">Dark</span>
</button>
```

```js
const saved = localStorage.getItem('mesh-theme');
const theme = saved === 'light' ? 'light' : 'dark';
document.documentElement.dataset.theme = theme;

function setTheme(next) {
  const theme = next === 'light' ? 'light' : 'dark';
  document.documentElement.dataset.theme = theme;
  localStorage.setItem('mesh-theme', theme);
}
```

Update the accessible label and visible label after each change. Keep the default deterministic: no saved value means dark.

## Acceptance checks

- First launch without `mesh-theme` is dark.
- Selecting light changes the complete interface without a reload.
- Reload restores light mode.
- Removing the preference returns to dark mode.
- Theme changes do not clear drafts, cards, or navigation state.
- Dark mode has readable focus indicators and muted borders.
- Light mode has readable text and semantic status colors.
- The system dashboard fits at phone width without horizontal scrolling.
- Technical values use the terminal font.
- The existing Mesh PWA behavior remains unchanged.
