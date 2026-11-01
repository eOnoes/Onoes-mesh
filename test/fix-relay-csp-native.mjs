import assert from 'node:assert/strict';
import { writeFile } from 'node:fs/promises';
import { pathToFileURL } from 'node:url';
import path from 'node:path';
import { DatabaseSync } from 'node:sqlite';
import { fixture } from './m4-link-fixture.mjs';

// Real admitted send/link path; template-only fixtures never send actions.
const baseline = process.argv.includes('--baseline');
const after = [];
const f = await fixture({ after: fn => after.push(fn) }, baseline ? 'csp-baseline' : 'csp-fixed');
const { chromium } = await import(pathToFileURL('C:/Users/eMitchell109/AppData/Local/hermes/hermes-agent/node_modules/playwright-core/index.mjs').href);
let server, browser, app;
const evidence = { baseline, viewport: { width: 390, height: 844 }, stages: [], errors: [], console: [], csp: [], requests: [] };
const inlineConsole = () => evidence.console.filter(m => /Applying inline style violates/.test(m.text));
const inlineEvents = () => evidence.csp.filter(e => e.blockedURI === 'inline' && /style-src/.test(e.effectiveDirective));
console.log('EVIDENCE ' + f.dir);
try {
  app = await f.boot();
  evidence.url = app.url;
  server = await chromium.launchServer({ executablePath: 'C:/Users/eMitchell109/AppData/Local/ms-playwright/chromium-1243/chrome-win64/chrome.exe', headless: true });
  evidence.browserPid = server.process().pid;
  evidence.browserArgs = server.process().spawnargs;
  browser = await chromium.connect(server.wsEndpoint());
  const context = await browser.newContext({ viewport: evidence.viewport });
  await context.exposeBinding('recordRelayCsp', ({ frame }, event) => evidence.csp.push({ ...event, frame: frame.url() }));
  await context.addInitScript(() => document.addEventListener('securitypolicyviolation', e => window.recordRelayCsp({
    effectiveDirective: e.effectiveDirective, violatedDirective: e.violatedDirective, blockedURI: e.blockedURI,
    sourceFile: e.sourceFile, lineNumber: e.lineNumber, columnNumber: e.columnNumber, sample: e.sample,
    disposition: e.disposition, originalPolicy: e.originalPolicy
  })));
  const page = await context.newPage();
  page.on('pageerror', e => evidence.errors.push(e.message));
  page.on('console', m => evidence.console.push({ type: m.type(), text: m.text(), location: m.location() }));
  page.on('request', r => evidence.requests.push({ path: new URL(r.url()).pathname, method: r.method() }));
  const shell = await page.goto(app.url);
  evidence.cspHeader = shell.headers()['content-security-policy'];
  assert.ok(!evidence.cspHeader.includes("'unsafe-inline'"));
  await page.locator('#demo-start').click();
  await page.waitForFunction(() => !document.getElementById('refresh').disabled);
  assert.equal(await page.locator('#tasks button').count(), 0);
  await page.locator('#tab-relay').click();
  assert.match(await page.locator('#relay-state').textContent(), /Actual isolated Relay connected/);
  await page.locator('#relay-open').click();
  const frame = page.frameLocator('#relay-terminal');
  await frame.locator('#in').fill('Native Relay inline CSP ' + (baseline ? 'baseline' : 'fixed'));
  const sent = page.waitForResponse(r => r.url().endsWith('/api/relay/message') && r.request().method() === 'POST');
  await page.locator('#relay-terminal').scrollIntoViewIfNeeded();
  await frame.locator('#snd').click();
  const reply = await sent;
  assert.equal(reply.status(), 200);
  const ref = await reply.json();
  assert.equal(ref.ok, true);
  evidence.ref = ref;
  await frame.locator('#meshTaskLink').waitFor({ state: 'visible' });
  assert.equal(await frame.locator('#meshTaskLink').getAttribute('data-task-id'), ref.taskId);
  const read = route => page.evaluate(async route => {
    const proof = JSON.parse(sessionStorage.getItem('mesh.synthetic-demo.proof.v1'));
    const r = await fetch(route, { headers: { 'X-Trial-CSRF': proof.csrfToken }, cache: 'no-store', credentials: 'same-origin' });
    if (!r.ok) throw Error('Admitted read refused: ' + r.status);
    return r.json();
  }, route);
  const canonical = (await read('/api/tasks')).tasks;
  assert.equal(canonical.length, 1);
  assert.equal(canonical[0].id, ref.taskId);
  assert.equal(canonical[0].proposal, undefined);
  evidence.canonical = canonical;
  await frame.locator('#meshTaskLink').click();
  await page.waitForFunction(id => document.getElementById('task-identity').textContent.includes(id) && !document.getElementById('refresh').disabled, ref.taskId);
  assert.equal(await page.locator('#tasks button').count(), 1);
  assert.equal(await page.locator('#edit-title').inputValue(), canonical[0].title);
  assert.match(await page.locator('#execution-result').textContent(), /Not run/);
  evidence.stages.push({ stage: 'native-handoff', taskId: ref.taskId, savedRows: 1 });
  await page.screenshot({ path: path.join(f.dir, 'native-handoff.png') });
  await page.locator('#tab-relay').click();
  await page.locator('#relay-reconnect').click();
  await page.waitForFunction(() => !document.getElementById('relay-open').disabled);
  assert.match(await page.locator('#relay-links').textContent(), new RegExp(ref.taskId));
  await page.locator('#relay-open').click();
  await frame.locator('#meshTaskLink').waitFor({ state: 'visible' });
  assert.equal(await frame.locator('#meshTaskLink').getAttribute('data-task-id'), ref.taskId);
  await page.locator('#relay-terminal').scrollIntoViewIfNeeded();
  await frame.locator('#meshTaskLink').click();
  await page.waitForFunction(id => document.getElementById('task-identity').textContent.includes(id) && !document.getElementById('refresh').disabled, ref.taskId);
  assert.equal(await page.locator('#tasks button').count(), 1);
  evidence.stages.push({ stage: 'native-reconnect-link', taskId: ref.taskId });
  await page.reload();
  await page.waitForFunction(() => !document.getElementById('refresh').disabled);
  assert.equal(await page.locator('#tasks button').count(), 1);
  await page.locator('#tab-workroom').click();
  await page.locator('#tasks button').click();
  assert.match(await page.locator('#task-identity').textContent(), new RegExp(ref.taskId));
  assert.equal(await page.locator('#edit-title').inputValue(), canonical[0].title);
  evidence.stages.push({ stage: 'reload', task: (await read('/api/tasks/' + ref.taskId)).task });
  await page.locator('#tab-relay').click();
  await page.locator('#relay-open').click();
  await frame.locator('#meshTaskLink').waitFor({ state: 'visible' });
  assert.equal(await frame.locator('#meshTaskLink').getAttribute('data-task-id'), ref.taskId);
  await page.locator('#relay-terminal').scrollIntoViewIfNeeded();
  await frame.locator('#in').waitFor({ state: 'attached' });
  await frame.locator('#in').evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
  evidence.normalPath = { inlineConsole: inlineConsole(), inlineEvents: inlineEvents(), errors: [...evidence.errors] };
  if (baseline) {
    assert.ok(inlineConsole().length > 0, 'Baseline must reproduce observed Chromium console errors');
    assert.ok(inlineEvents().length > 0, 'Baseline must capture actual inline-style CSP events');
  } else {
    assert.deepEqual(inlineConsole(), [], 'Normal send/handoff/reconnect/reload must emit zero inline-style console violations');
    assert.deepEqual(inlineEvents(), [], 'Normal path must emit zero inline-style CSP events');
    const before = evidence.requests.length;
    evidence.templates = await frame.locator('#in').evaluate(async () => {
      // Exercise actual render functions in the admitted DOM. No action handlers
      // are clicked and all network/execution entry points are tripwires here.
      const saved = { A, cur, fetch: window.fetch, post, act, controlGoal, connect };
      const forbidden = () => { throw Error('Template fixture attempted an action or network request'); };
      window.fetch = post = act = controlGoal = connect = forbidden;
      const proof = [];
      const clean = selector => {
        const attrs = [...document.querySelectorAll(selector + ' [style], ' + selector + '[style]')].map(el => el.outerHTML);
        if (attrs.length) throw Error('Inline template attributes: ' + attrs.join('\n'));
      };
      try {
        const statuses = ['working', 'stalled', 'waiting', 'stopped', 'done', 'idle', 'unknown'];
        const ids = ['echo', 'cyony', 'tripp', 'dsh', 'mesh'];
        const accents = ['rgb(240, 164, 75)', 'rgb(255, 121, 176)', 'rgb(239, 100, 97)', 'rgb(111, 211, 199)', 'rgb(217, 161, 59)'];
        A = Object.fromEntries(statuses.map((status, i) => ['fixture' + i, { id: 'fixture' + i, name: status, status }]));
        for (const [index, id] of ids.entries()) for (const view of ['mini', 'focus', 'expanded']) {
          cur = id;
          A[id] = { id, name: id, status: 'waiting', backend: 'mesh', device: 'pc', feed: [], msgs: [], meshTaskLinks: [],
            approval: { cmd: 'render-only <proposal> & text' }, goal: { text: 'render-only <goal>', turns: 1, max_turns: 4,
              native_status: 'active', controls: ['pause', 'delete'], steps: [['done', '', 'd'], ['current', '', 'a'], ['next', '', 'p']] } };
          goalViews[id] = view;
          render();
          clean('#tabs'); clean('#goalDock'); clean('#goalCards'); clean('#scr');
          const card = document.querySelector('#goalDock .goal-card');
          const color = getComputedStyle(card).borderLeftColor;
          if (color !== accents[index]) throw Error('Goal accent changed: ' + id + ' ' + color);
          if (!card.classList.contains(view)) throw Error('Goal view changed');
          const proposal = [...document.querySelectorAll('#scr .you')];
          if (proposal.length !== 2 || proposal[1].textContent !== '$ render-only <proposal> & text') throw Error('Proposal text/escaping changed');
          if (proposal.some(el => getComputedStyle(el).color !== 'rgb(232, 232, 234)')) throw Error('Proposal color changed');
          const dots = statuses.map((status, i) => {
            const dot = document.querySelector('[data-k="fixture' + i + '"] .tdot');
            const color = getComputedStyle(dot).backgroundColor;
            const expected = ({ working: 'rgb(63, 185, 107)', done: 'rgb(63, 185, 107)', stalled: 'rgb(217, 161, 59)', waiting: 'rgb(79, 140, 255)' })[status] || 'rgb(91, 91, 99)';
            if (color !== expected) throw Error('Status cue changed: ' + status + ' ' + color);
            return { status, color };
          });
          proof.push({ id, view, accent: color, dots, proposal: proposal.map(el => el.textContent) });
          delete A[id];
        }
        return proof;
      } finally {
        A = saved.A; cur = saved.cur; window.fetch = saved.fetch; post = saved.post; act = saved.act; controlGoal = saved.controlGoal; connect = saved.connect;
        render();
        await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
      }
    });
    assert.deepEqual(evidence.requests.slice(before).filter(r => r.method !== 'GET'), [], 'Template fixtures must make no mutations');
    assert.deepEqual(inlineConsole(), []);
    assert.deepEqual(inlineEvents(), []);
  }
  const db = new DatabaseSync(f.filename, { readOnly: true });
  evidence.counts = {};
  for (const name of ['tasks', 'relay_task_links', 'task_proposals', 'task_executions', 'task_proposal_decisions']) {
    evidence.counts[name] = db.prepare(`SELECT COUNT(*) AS n FROM ${name}`).get().n;
    assert.equal(evidence.counts[name], ['tasks', 'relay_task_links'].includes(name) ? 1 : 0);
  }
  db.close();
  const relayDb = new DatabaseSync(f.relayFilename, { readOnly: true });
  evidence.references = relayDb.prepare('SELECT * FROM mesh_task_references').all();
  assert.equal(evidence.references.length, 1);
  assert.equal(evidence.references[0].task_id, ref.taskId);
  assert.equal(relayDb.prepare('SELECT COUNT(*) AS n FROM messages').get().n, 1);
  assert.equal(relayDb.prepare('SELECT COUNT(*) AS n FROM outbox').get().n, 0);
  relayDb.close();
  assert.deepEqual(evidence.requests.filter(r => r.method === 'POST').map(r => r.path).sort(),
    ['/api/trial-session/bootstrap', '/api/relay/message', '/api/relay/reconnect'].sort());
  await page.locator('#demo-end').click();
  await page.waitForFunction(() => document.getElementById('task-identity').textContent === '' && document.getElementById('demo-end').disabled);
  assert.equal(await page.locator('#tasks button').count(), 0);
  assert.equal(await page.locator('#relay-links button').count(), 0);
  assert.equal(await page.locator('#relay-terminal').getAttribute('srcdoc'), '');
  evidence.logoutCleared = true;
  assert.deepEqual(evidence.errors, []);
  evidence.passed = true;
  console.log((baseline ? 'BASELINE CSP REPRODUCED' : 'NATIVE CSP FIX PASS') + ' ' + ref.taskId);
} catch (e) {
  evidence.failure = e.stack;
  throw e;
} finally {
  if (browser) await browser.close();
  if (server) await server.close();
  for (const fn of after) await fn();
  evidence.meshOutput = app?.output();
  evidence.meshErrors = app?.errors();
  await writeFile(path.join(f.dir, 'native-proof.json'), JSON.stringify(evidence, null, 2));
}
