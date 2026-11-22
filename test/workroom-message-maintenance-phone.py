"""Phone-width check with a disposable Mesh board and a synthetic Relay directory."""
import json
import os
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
from urllib.parse import urlsplit

from playwright.sync_api import expect, sync_playwright


ROOT = Path(__file__).resolve().parents[1]
SERVER = """
import {createInterface} from 'node:readline';
import {resolve} from 'node:path';
import {startApp} from './server.mjs';
import {openTaskStore} from './lib/task-store.mjs';
const dataDir = process.argv[1];
const store = openTaskStore(resolve(dataDir, 'tasks.sqlite'));
const card = store.create({title:'Maintenance test', description:'Saved card'});
const brief = {project:'Mesh', criteria:'', owner:'echo', team:'local_build'};
if (process.env.MESH_SIMPLE_FLOW === '1') {
  store.workroom.save(card.id, {...brief,stage:'working',revision:store.workroom.get(card.id).workroom.revision});
}
const app = await startApp({dataDir, relayEnabled:false});
let pause = app.dispatch.pause();
console.log(JSON.stringify({url:app.url, id:card.id}));
for await (const action of createInterface({input:process.stdin})) {
  if (action === 'resume') app.dispatch.resume(pause.generation);
  if (action === 'pause') pause = app.dispatch.pause();
  if (action === 'finish' || action === 'update') {
    const task=store.workroom.get(card.id);
    const saved=store.workroom.saveProgress(card.id,{goal:'Saved inspection goal',checklist:[{id:'step',text:'Read saved steps',status:'done'}],
      result:'Result read from this PC',evidence:'Local fixture',reviewer:'Independent reviewer',decision:action==='finish'?'approved':'pending',
      revision:task.progress.revision,taskRevision:task.revision,briefRevision:task.workroom.revision});
    if(action==='finish')store.workroom.save(card.id,{...brief,stage:'done',revision:saved.workroom.revision});
    console.log('saved '+action);
  }
  console.log('gate ' + app.dispatch.status().state);
}
await app.close();
store.close();
"""


def check(server, page, base, card):
    peers = [{"id": "echo", "name": "Echo", "conversation_id": "fixture", "backend": "hermes"}]
    sends = []
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))

    def route(req):
        url = urlsplit(req.request.url)
        if url.netloc != urlsplit(base).netloc:
            req.abort()
        elif url.path == "/api/relay/native/api/agents":
            req.fulfill(json=peers)
        elif url.path == f"/api/workroom/{card}/message":
            sends.append(req.request.post_data_json)
            req.fulfill(status=503, json={"error": "Synthetic recipient"})
        else:
            req.continue_()

    page.route("**/*", route)
    page.goto(base + "/#task=" + card)
    page.locator("#rail-menu").tap()
    page.locator("#demo-start").tap()
    sheet = page.get_by_role("dialog", name="Task details")
    expect(sheet).to_be_visible()
    sheet.get_by_text("Conversation and history", exact=True).tap()
    draft = sheet.get_by_label("Message", exact=True)
    send = sheet.get_by_role("button", name="Send in this task")
    plan = sheet.get_by_role("button", name="Ask for a plan", exact=False)
    review = sheet.get_by_role("button", name="Request independent review")
    expect(send).to_be_disabled()
    expect(plan).to_be_disabled()
    draft.fill("First words")
    draft.evaluate("el => el.form.requestSubmit()")
    expect(sheet.get_by_text("Sending is paused. You can keep drafting here.")).to_be_visible()
    assert sends == []
    draft.fill("Keep this edited draft")

    def change(action, state):
        server.stdin.write(action+"\n")
        server.stdin.flush()
        for line in server.stdout:
            if line.strip() == "gate "+state:
                break
        else:
            raise RuntimeError("Disposable gateway closed before the change")
        page.evaluate("window.dispatchEvent(new Event('mesh-tasks-refreshed'))")

    change("resume", "open")
    expect(send).to_be_enabled()
    expect(plan).to_be_enabled()
    expect(review).to_be_disabled()
    expect(draft).to_have_value("Keep this edited draft")
    sheet.get_by_role("button", name="Prepare worker request").click()
    expect(sheet.get_by_role("button", name="Start this worker")).to_be_visible()
    change("pause", "paused")
    expect(sheet.get_by_role("button", name="Start this worker")).to_have_count(0)
    expect(send).to_be_disabled()
    expect(sheet.get_by_text("Sending is paused. You can keep drafting here.")).to_be_visible()
    expect(draft).to_have_value("Keep this edited draft")
    change("resume", "open")
    expect(send).to_be_enabled()
    with page.expect_request(lambda r: urlsplit(r.url).path == f"/api/workroom/{card}/message"):
        send.tap()
    assert [s["text"] for s in sends] == ["Keep this edited draft"]
    peers.clear()
    sheet.get_by_role("button", name="Close card", exact=True).tap()
    page.get_by_role("button", name="Maintenance test", exact=False).first.tap()
    sheet.get_by_text("Conversation and history", exact=True).tap()
    expect(sheet.get_by_label("Agent for this task message").locator("option")).to_have_count(0)
    expect(send).to_be_disabled()
    expect(sheet.get_by_text("No connected agent is available for this task message.")).to_be_visible()
    assert errors == []


def check_progress(server, page, base, card):
    requests = []
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.on("request", lambda r: requests.append((r.method, urlsplit(r.url).path)))
    page.route("**/*", lambda r: r.continue_() if urlsplit(r.request.url).netloc == urlsplit(base).netloc else r.abort())
    page.route(base + f"/api/workroom/{card}/sync",
               lambda r: r.fulfill(status=503, json={"error":"Fixture: Relay unavailable"}))
    page.goto(base + "/#task=" + card)
    page.locator("#rail-menu").tap()
    page.locator("#demo-start").tap()
    sheet = page.get_by_role("dialog", name="Task details")
    expect(sheet.get_by_label("Card status: In progress")).to_be_visible()
    sheet.get_by_text("Advanced controls and history", exact=True).tap()
    sheet.get_by_text("Conversation and history", exact=True).tap()
    draft = sheet.get_by_label("Message", exact=True)
    draft.fill("Unsent message")
    draft.blur()
    with page.expect_response(lambda r: urlsplit(r.url).path == f"/api/workroom/{card}/sync") as sync:
        sheet.get_by_role("button", name="Refresh agent replies").tap()
    assert sync.value.status == 503
    for action in ["update", "finish"]:
        server.stdin.write(action + "\n")
        server.stdin.flush()
        for line in server.stdout:
            if line.strip() == "saved " + action:
                break
        else:
            raise RuntimeError("Disposable board edit failed")
        requests.clear()
        sheet.get_by_role("button", name="Check progress").tap()
        expect(sheet.locator(".workroom-card-summary")).to_contain_text("Result read from this PC")
        expect(sheet.locator(".workroom-card-summary")).to_contain_text("Read saved steps")
        if action == "finish":
            expect(sheet.get_by_label("Card status: Done")).to_be_visible()
            expect(sheet.get_by_role("button", name="Accept result")).to_be_visible()
        assert ("GET", f"/api/workroom/{card}") in requests
        assert not any(path.endswith("/sync") or path.startswith("/api/relay/") or
                       (method != "GET" and path.startswith("/api/workroom")) for method, path in requests), requests
        expect(draft).to_have_value("Unsent message")
    sheet.get_by_role("button", name="Edit card").tap()
    expect(sheet.get_by_label("Goal", exact=True)).to_have_value("Saved inspection goal")
    assert errors == []


def run(scenario, managed=False):
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith("MESH_")}
    env["MESH_SIMPLE_FLOW"] = "1" if managed else "0"
    (ROOT / "data").mkdir(exist_ok=True)
    with TemporaryDirectory(prefix="phone-message-gate-", dir=ROOT / "data") as folder:
        child = subprocess.Popen(
            ["node", "--input-type=module", "-e", SERVER, Path(folder).relative_to(ROOT).as_posix()],
            cwd=ROOT, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        try:
            ready = json.loads(child.stdout.readline())
            assert urlsplit(ready["url"]).hostname == "127.0.0.1"
            with sync_playwright() as pw:
                browser = pw.chromium.launch(channel="msedge", headless=True)
                page = browser.new_page(viewport={"width": 390, "height": 844}, has_touch=True, is_mobile=True)
                page.set_default_timeout(10000)
                scenario(child, page, ready["url"], ready["id"])
                browser.close()
        finally:
            child.stdin.close()
            try:
                child.wait(timeout=20)
            except subprocess.TimeoutExpired:
                child.terminate()
                child.wait(timeout=10)


if __name__ == "__main__":
    run(check)
    run(check_progress, managed=True)
    print("PASS: paused send, preserved draft and read-only saved progress through Done with Relay unavailable.")
