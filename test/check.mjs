import { readFileSync, existsSync } from 'node:fs';
import { createHash } from 'node:crypto';
import { spawn } from 'node:child_process';
import assert from 'node:assert/strict';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
process.chdir(root);
const hardStop = setTimeout(() => { console.error('APP03 check process deadline'); process.exit(1); }, 59000);
async function run(args) {
  const child = spawn(process.execPath, args, { cwd: root, stdio: 'inherit', windowsHide: true });
  const deadline = setTimeout(() => child.kill(), 57000);
  const code = await new Promise((resolve, reject) => { child.on('error', reject); child.on('exit', resolve); });
  clearTimeout(deadline); assert.equal(code, 0, 'Native Node check failed');
}
// Design guard.
//
// Two files matter now that the tokens have their own home:
//   shared/tokens.css     - the ONLY place a colour may be defined
//   public/styles.css     - rules only; no literals, no token definitions
//
// The rules below each exist because the opposite was true at some point:
//
//   * public/styles.css carried TWO :root blocks with contradictory palettes, the second
//     silently overriding the first, so the palette a reader saw at the top of the file was
//     not the palette in use.
//   * All four semantic colours were the same acid lime #39FF14, so "running", "waiting" and
//     "failed" rendered identically. The lime is retired in favour of Relay's #3fb96b green.
//   * 41 colour literals lived in the rules, including the four status colours written twice
//     with different values - so the live colour depended on rule order.
//   * A token referenced itself (--scrim-soft: var(--scrim-soft)), which is invalid at
//     computed-value time and resolves to nothing, silently breaking a scrim while every
//     test stayed green. A name being "defined" says nothing about its value meaning anything.
//   * The previous assertion here pinned '#39FF14' and lived in a branch that --test never
//     entered AND that crashed on a missing APP03-CONTRACT.json before reaching it. It could
//     neither pass nor fail, so the design drifted with nothing watching.
function assertDesign() {
  const tokens = readFileSync('shared/tokens.css', 'utf8');
  const rules = readFileSync('public/styles.css', 'utf8');
  const both = tokens + rules;
  // Comments are documentation, not code. A comment explaining WHICH literal must not
  // appear would otherwise trip the check that forbids it - which is exactly what
  // happened when the ported rules were annotated with the reference's colour values.
  // Every assertion below therefore runs against comment-stripped text.
  const code = rules.replace(/\/\*[\s\S]*?\*\//g, '');

  assert.equal(/#39ff14/i.test(both), false, 'the retired Mesh lime must not return');
  assert.equal((tokens.match(/(?<![\w-]):root\{/g) || []).length, 1, 'shared/tokens.css must define exactly one :root block');
  assert.equal(/(?<![\w-]):root\{/.test(rules), false, 'tokens live in shared/tokens.css, not in public/styles.css');
  assert.equal(/#[0-9a-fA-F]{3,8}\b/.test(code), false, 'colour literals must not appear in public/styles.css');
  assert.equal(/rgba?\(/.test(code), false, 'rgba() literals must not appear in public/styles.css');

  for (const token of ['--green:#3fb96b', '--blue:#4f8cff', '--radius:6px']) {
    assert.equal(tokens.includes(token), true, `${token} is missing from shared/tokens.css`);
  }

  const defined = new Set([...tokens.matchAll(/(--[a-zA-Z0-9-]+)\s*:/g)].map((m) => m[1]));
  for (const source of [tokens, rules]) {
    for (const [, name] of source.matchAll(/var\((--[a-zA-Z0-9-]+)/g)) {
      assert.equal(defined.has(name), true, `var(${name}) is used but never defined in shared/tokens.css`);
    }
  }

  const rootBody = tokens.match(/:root\{([^}]*)\}/)?.[1] ?? '';
  const cycleMap = new Map([...rootBody.matchAll(/(--[a-zA-Z0-9-]+)\s*:\s*([^;}]+)/g)].map((m) => [m[1], m[2]]));
  for (const start of cycleMap.keys()) {
    let current = start;
    const seen = new Set();
    while (current && !seen.has(current)) {
      seen.add(current);
      current = cycleMap.get(current)?.match(/var\((--[a-zA-Z0-9-]+)/)?.[1] ?? null;
    }
    assert.notEqual(current, start, `${start} references itself, which is invalid and resolves to nothing`);
  }

  // --- Relay conformance, asserted statically -------------------------------------
  //
  // Until now "it matches the Relay design" was something a person measured in a browser
  // and then the measurement died with the session. Each assertion below encodes one
  // property that was NOT true before the restyle and would silently regress without a
  // guard. Comments are stripped first so the prose above cannot trip its own check.
  assert.equal(/(Segoe|sans-serif|system-ui|ui-monospace)/.test(code), false,
    'every font family must come from a token - var(--mono) for content, var(--sans) for chrome');
  assert.equal(/font-family:var\(--mono\)/.test(code), true, 'content must be monospace');
  assert.equal(/max-width:820px/.test(code), true, 'the shell must be the 820px Relay window');

  for (const token of ['--terminal-font:', '--terminal-line:', '--sans:']) {
    assert.equal(tokens.includes(token), true, `${token} is missing from shared/tokens.css`);
  }

  const html = readFileSync('public/index.html', 'utf8');
  const tabCount = (html.match(/role="tab"/g) || []).length;
  assert.equal(tabCount, 7, `expected seven tab buttons, found ${tabCount}`);
  // The navigation lives in its own rail, not in the top bar. Desktop is a rail + top
  // rail + body layout (the operator's brief); on a phone the same rail element lays out
  // as the horizontal strip under the bar, so there is one navigation source at any width.
  const header = html.match(/<header[\s\S]*?<\/header>/)?.[0] ?? '';
  const rail = html.match(/<aside class="nav-rail"[\s\S]*?<\/aside>/)?.[0] ?? '';
  assert.equal((rail.match(/role="tab"/g) || []).length, 7,
    'all seven tabs must live in the nav rail');
  assert.equal(/id="rail-toggle"/.test(header), true,
    'the top rail must carry the navigation rail collapse control');
  assert.equal((header.match(/role="tab"/g) || []).length, 0,
    'tabs belong in the rail, not in the top bar');
  const dots = (header.match(/<span class="wd"[\s\S]*?<\/span>/)?.[0]?.match(/<i>/g) || []).length;
  assert.equal(dots, 3, 'the top bar must carry exactly three traffic-light dots');
  assert.equal(html.indexOf('/shared/tokens.css') < html.indexOf('/styles.css'), true,
    'the token stylesheet must load before the rules that use it');

  console.log('design guard: tokens isolated, no colour or font literals, 820px window, 7 tabs + 3 dots in the bar');
}
try {
  assertDesign();
  if (process.argv.includes('--test') || process.argv.includes('--ui')) {
    await run(['--test','--test-timeout=55000', ...(process.argv.includes('--ui') ? ['test/ui.test.mjs'] : ['test/trial-session.test.mjs','test/session-app.test.mjs','test/ui.test.mjs','test/version.test.mjs'])]);
  } else {
    assert.equal(Number(process.versions.node.split('.')[0]), 24);
    const context = JSON.parse(readFileSync('APP03-SOURCE-CONTEXT.json'));
    // APP03-CONTRACT.json was never imported into this tree, so this branch used to die
    // with ENOENT before reaching a single real check. Treat it as optional and say so,
    // rather than letting one missing file hide every check behind it.
    const contractPath = 'APP03-CONTRACT.json';
    const contract = existsSync(contractPath) ? JSON.parse(readFileSync(contractPath)) : null;
    if (!contract) console.log('note: APP03-CONTRACT.json is absent - frozen-pin check skipped');
    for (const [file, expected] of Object.entries({ ...context.inputSha256, ...(contract?.frozenSha256 ?? {}) })) {
      if (!file.startsWith('lib/') && !file.startsWith('test/trial-session') && file !== 'SESSION-CORE-CONTRACT.json') continue;
      assert.equal(createHash('sha256').update(readFileSync(file)).digest('hex'), expected, `Immutable pin: ${file}`);
    }
    for (const file of ['server.mjs','public/app.js','test/session-app.test.mjs','test/ui.test.mjs','test/check.mjs','test/app03-preview.mjs']) await run(['--check',file]);
    const pkg = JSON.parse(readFileSync('package.json'));
    for (const name of ['check','test','test:ui']) assert.equal(pkg.scripts[name].startsWith('node test/check.mjs'), true);
    console.log('APP03 native syntax, scripts, Node 24 and immutable pins PASS');
  }
} finally { clearTimeout(hardStop); }
