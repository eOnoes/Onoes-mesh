"""Run with python -B test/workroom_card_link_browser.py (Playwright and Edge required)."""
from pathlib import Path
import json
import os
import subprocess
import tempfile
from urllib.parse import urlsplit
from playwright.sync_api import sync_playwright, expect
repo = Path(__file__).resolve().parents[1]
node = """
import {startApp} from './server.mjs';
import {openTaskStore} from './lib/task-store.mjs';
import path from 'node:path';
const dataDir=process.argv[1],store=openTaskStore(path.join(dataDir,'tasks.sqlite'));
const ids=['Build checklist fixture','Second saved card'].map(title=>store.create({title,owner:'nims'}).id);
store.close();
const app=await startApp({port:0,dataDir,standalone:true,relayEnabled:false});
console.log(JSON.stringify({url:app.url,ids}));
process.stdin.resume();process.stdin.on('end',async()=>{await app.close()});
"""
env = {k: v for k, v in os.environ.items() if not k.upper().startswith(('MESH_', 'NODE_'))}
env.update(MESH_STANDALONE='1', MESH_RELAY='0', MESH_SIMPLE_FLOW='0')

def check_card_links():
    (repo / 'data').mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='card-link-', dir=repo / 'data') as temp:
        data = Path(temp)
        proc = subprocess.Popen(['node', '--input-type=module', '-e', node, data.relative_to(repo).as_posix()], cwd=repo, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        try:
            info = json.loads(proc.stdout.readline())
            base = info['url']
            first, second = info['ids']
            with sync_playwright() as pw:
                browser = pw.chromium.launch(channel='msedge', headless=True)
                ctx = browser.new_context(viewport={'width': 390, 'height': 844}, is_mobile=True, has_touch=True)
                ctx.route('**/*', lambda r: r.continue_() if urlsplit(r.request.url).netloc == urlsplit(base).netloc else r.abort())
                page = ctx.new_page()
                page.set_default_timeout(12000)
                problems = []
                calls = []
                page.on('pageerror', lambda e: problems.append(str(e)))
                page.on('request', lambda r: calls.append((r.method, urlsplit(r.url).path)))
                page.goto(base + '/#task=' + first)
                expect(page.locator('#tab-workroom')).to_have_attribute('aria-selected', 'true')
                expect(page.get_by_role('dialog')).to_have_count(0)
                expect(page).to_have_url(base + '/#task=' + first)
                assert not any((p.endswith(first) for _, p in calls))
                menu = page.locator('#rail-menu')
                menu.tap()
                page.get_by_role('button', name='Start local session', exact=True).tap()
                sheet = page.get_by_role('dialog', name='Task details')
                expect(sheet).to_be_visible()
                expect(sheet).to_contain_text('Build checklist fixture')
                expect(page.locator('#inspection-heading')).to_contain_text('Build checklist fixture')
                expect(page).to_have_url(base + '/#workroom')
                sheet.get_by_role('button', name='Edit card', exact=True).tap()
                goal = sheet.get_by_label('Goal', exact=True)
                goal.fill('Unsaved phone draft')
                page.evaluate('(id)=>{location.hash="task="+id}', second)
                expect(goal).to_have_value('Unsaved phone draft')
                expect(page).to_have_url(base + '/#task=' + second)
                sheet.get_by_role('button', name='Close card', exact=True).tap()
                expect(sheet).to_contain_text('Second saved card')
                expect(page).to_have_url(base + '/#workroom')
                sheet.get_by_role('button', name='Close card', exact=True).tap()
                missing = '00000000-0000-4000-a000-000000000000'
                page.evaluate('(id)=>{location.hash="task="+id}', missing)
                expect(page.get_by_text('This card is unavailable. Choose another card from the board.', exact=True)).to_be_visible()
                expect(page.locator('.workroom-card')).to_have_count(2)
                page.evaluate("()=>{history.replaceState=()=>{throw Error('History unavailable')}}")
                page.evaluate('(id)=>{location.hash="task="+id}', first)
                expect(sheet).to_contain_text('Build checklist fixture')
                sheet.get_by_role('button', name='Close card', exact=True).tap()
                # Refreshing with unavailable history must not reopen a dismissed card.
                if menu.get_attribute('aria-expanded') == 'true':
                    menu.tap()
                with page.expect_response(lambda r: r.url.endswith('/api/workroom') and r.request.method == 'GET'):
                    page.get_by_role('button', name='Refresh board', exact=True).tap()
                expect(sheet).to_have_count(0)
                assert not problems, problems
                writes = [(m, p) for m, p in calls if m in ('PATCH', 'PUT', 'DELETE') or (m == 'POST' and any((t in p for t in ('dispatch', 'claim', 'assign', 'send', 'approve'))))]
                assert not writes, writes
                browser.close()
                print('PASS: locked link, exact sheet and inspector after admission, in-page link, preserved draft, missing card, dismissal with unavailable history, no work dispatched.')
        finally:
            proc.stdin.close()
            try:
                proc.wait(timeout=12)
            except subprocess.TimeoutExpired:
                proc.terminate()
                proc.wait(timeout=10)
if __name__ == '__main__':
    check_card_links()
