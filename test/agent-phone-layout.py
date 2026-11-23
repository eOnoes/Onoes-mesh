"""Exercise the Agent tab with long task titles using only local Mesh assets."""
import mimetypes
import re
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import sync_playwright


PUBLIC = Path(__file__).resolve().parents[1] / "public"
ORIGIN = "https://mesh.test"


def local_asset(route):
    url = urlsplit(route.request.url)
    if url.netloc != "mesh.test":
        route.abort()
        return
    path = (PUBLIC / (url.path.lstrip("/") or "index.html")).resolve()
    if not path.is_relative_to(PUBLIC) or not path.is_file():
        route.fulfill(status=404)
        return
    if path.name == "index.html":
        # Load the real shell without starting its live session or feeder clients.
        shell = re.sub(r"<script\b[^>]*>.*?</script>", "", path.read_text(encoding="utf-8"), flags=re.S)
        route.fulfill(body=shell, content_type="text/html")
    else:
        content_type = "text/javascript" if path.suffix == ".mjs" else mimetypes.guess_type(path.name)[0]
        route.fulfill(body=path.read_bytes(), content_type=content_type or "application/octet-stream")


with sync_playwright() as pw:
    browser = pw.chromium.launch(channel="chrome")
    page = browser.new_page(is_mobile=True, has_touch=True)
    page.route("**/*", local_asset)
    page.goto(ORIGIN)
    page.evaluate("""async () => {
        const {renderAgentWorkspace} = await import('/agent-workspace.mjs');
        document.querySelectorAll('[role=tabpanel]').forEach(p => p.hidden = p.id !== 'panel-agent');
        const snapshot = {agents:[{id:'echo', name:'Echo', conversation_id:'e'.repeat(60)}]};
        const tasks = [{id:'card', title:'Review ' + 'prototype'.repeat(12), messages:[{agentId:'echo'}]}];
        renderAgentWorkspace(document.querySelector('#agent-workspace'), snapshot, tasks,
            id => document.body.dataset.opened = id);
    }""")
    button = page.locator("#agent-workspace article button")
    for width in (360, 390, 820):
        page.set_viewport_size({"width": width, "height": 844})
        for size in ("default", "large"):
            page.evaluate("size => document.documentElement.dataset.textSize = size", size)
            box = button.bounding_box()
            assert box and 0 <= box["x"] and box["x"] + box["width"] <= width, (width, size, box)
            assert button.evaluate("e => e.scrollWidth <= e.clientWidth + 1"), (width, size, "clipped label")
            page.evaluate("delete document.body.dataset.opened")
            button.tap()
            assert page.locator("body").get_attribute("data-opened") == "card"
    browser.close()
print("Agent task label fits and opens the correct card in all six layouts.")
