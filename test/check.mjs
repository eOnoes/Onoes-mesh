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
// This replaces `assert styles.css includes '#39FF14'`, which pinned the RETIRED Mesh
// lime. That assertion had two faults: it guarded a colour the app no longer uses, and it
// sat in the branch that only runs without --test/--ui, so `npm test` never executed it.
// Worse, that branch died on a missing APP03-CONTRACT.json before reaching the assertion,
// so it could not fail and could not pass - it simply never ran.
//
// The lime is gone on purpose: Mesh now uses Relay's terminal palette, where running/ok is
// #3fb96b. The single-:root rule is the most important line here - public/styles.css used
// to carry TWO token blocks with contradictory palettes, the second silently overriding the
// first. That is precisely the drift a guard should catch, so this one runs in every lane.
function assertDesign() {
  const css = readFileSync('public/styles.css', 'utf8');
  assert.equal(/#39ff14/i.test(css), false, 'the retired Mesh lime must not return');
  assert.equal(css.includes('--green:#3fb96b'), true, 'Relay green token is missing');
  assert.equal(css.includes('--blue:#4f8cff'), true, 'Relay blue token is missing');
  assert.equal(css.includes('--radius:6px'), true, 'Relay radius token is missing');
  assert.equal((css.match(/:root\{/g) || []).length, 1, 'stylesheet must define exactly one token block');
  // Every colour must come from the token block. Before this rule the file carried 40
  // hard-coded literals in its rules - including the same four status colours written
  // twice with different values, so the live colour depended on rule order. Named tokens
  // make the palette changeable in one place and the duplication harmless.
  const rules = css.replace(/:root\{[^}]*\}/, '');
  assert.equal(/#[0-9a-fA-F]{3,8}\b/.test(rules), false, 'colour literals must live in :root, not in rules');
  assert.equal(/rgba?\(/.test(rules), false, 'rgba() literals must live in :root, not in rules');
  const definedTokens = new Set([...css.matchAll(/(--[a-zA-Z0-9-]+)\s*:/g)].map((m) => m[1]));
  for (const [, token] of css.matchAll(/var\((--[a-zA-Z0-9-]+)/g)) {
    assert.equal(definedTokens.has(token), true, `var(${token}) is used but never defined`);
  }
  // A token that references itself - directly or through a chain - is invalid at
  // computed-value time and resolves to nothing, silently. --scrim-soft became
  // `var(--scrim-soft)` while the literals were being tokenised and quietly broke the menu
  // scrim while every test stayed green, because a name being "defined" says nothing about
  // whether its value means anything.
  const rootBody = css.match(/:root\{([^}]*)\}/)?.[1] ?? '';
  const tokens = new Map([...rootBody.matchAll(/(--[a-zA-Z0-9-]+)\s*:\s*([^;}]+)/g)].map((m) => [m[1], m[2]]));
  for (const start of tokens.keys()) {
    let current = start;
    const seen = new Set();
    while (current && !seen.has(current)) {
      seen.add(current);
      current = tokens.get(current)?.match(/var\((--[a-zA-Z0-9-]+)/)?.[1] ?? null;
    }
    assert.notEqual(current, start, `${start} references itself, which is invalid and resolves to nothing`);
  }
  console.log('design guard: one token block, Relay tokens present, every var() defined');
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
