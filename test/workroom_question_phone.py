"""Check pending questions on compact cards using the disposable Workroom server."""
import json
import os
import re
from pathlib import Path
import subprocess
from urllib.parse import urlsplit

from playwright.sync_api import expect, sync_playwright


ROOT = Path(__file__).resolve().parents[1]
LAUNCH = """await import('./test/serve-team-policy-fixture.mjs');
process.stdin.resume(); process.stdin.on('end', () => process.emit('SIGTERM'));"""
QUESTION = "Which tray width should Echo use for the revised print?"
CHANGE_FLOW = r"""
import assert from 'node:assert/strict';
import {join} from 'node:path';
import {openTaskStore} from './lib/task-store.mjs';
const [dir, question] = process.argv.slice(1);
assert.match(dir, /^data\/team-policy-browser-[a-f0-9-]{36}$/);
const store = openTaskStore(join(dir, 'tasks.sqlite'));
try {
  const card = store.list().find(t => t.title.startsWith('Mesh folder'));
  if (question) store.workroom.flow.question(card.id, question);
  else store.workroom.flow.enqueue(card.id);
} finally { store.close(); }
"""


def check(browser, managed):
    env = {k: v for k, v in os.environ.items() if not k.startswith(("MESH_", "NODE_"))}
    env.update(MESH_SIMPLE_FLOW=str(int(managed)), MESH_RELAY="0", MESH_NIMS="0")
    with subprocess.Popen(["node", "--input-type=module", "-e", LAUNCH], cwd=ROOT, env=env,
                          text=True, stdin=subprocess.PIPE, stdout=subprocess.PIPE) as server:
        try:
            fixture = json.loads(server.stdout.readline())
            assert urlsplit(fixture["url"]).hostname == "127.0.0.1"

            def change(question):
                subprocess.run(["node", "--input-type=module", "-e", CHANGE_FLOW,
                                fixture["dataDir"], question], cwd=ROOT, env=env, check=True)

            change(QUESTION)
            context = browser.new_context(viewport={"width": 390, "height": 844},
                                          is_mobile=True, has_touch=True)
            try:
                page = context.new_page()
                page.set_default_timeout(10000)
                page.goto(fixture["url"])
                page.locator("#rail-menu").tap()
                page.get_by_role("button", name="Start local session", exact=True).tap()
                if page.locator("#rail-menu").get_attribute("aria-expanded") == "true":
                    page.locator("#tab-workroom").tap()
                card = page.locator("button[data-task-id]").filter(has_text="Mesh folder")
                question = card.get_by_text(QUESTION, exact=False)
                expect(question).to_be_visible()
                expect(card).to_have_accessible_description(re.compile("Which tray width"))
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                card.tap()
                sheet = page.get_by_role("dialog", name="Task details")
                expect(sheet.get_by_text(QUESTION, exact=True)).to_be_visible()
                if managed:
                    sheet.get_by_role("button", name="Answer question").tap()
                    goal = sheet.get_by_role("textbox", name="Goal", exact=True)
                    expect(goal).to_be_focused()
                    sheet.get_by_text(QUESTION, exact=True).tap()
                    sheet.get_by_role("button", name="Save changes").tap()
                    expect(sheet).to_be_hidden()
                    expect(page.get_by_text("The question is still open.", exact=False)).to_be_visible()
                    expect(question).to_be_visible()
                    card.tap()
                    sheet.get_by_role("button", name="Answer question").tap()
                    answer = "Use a 95 mm tray width."
                    revised_goal = goal.input_value() + " " + answer
                    goal.fill(revised_goal)
                    sheet.get_by_text(QUESTION, exact=True).tap()
                    sheet.get_by_role("button", name="Save changes").tap()
                    expect(sheet).to_be_hidden()
                    expect(page.get_by_text("Answer saved. The updated request is queued for another look.", exact=True)).to_be_visible()
                    page.reload()
                    card.tap()
                    expect(sheet.get_by_text(revised_goal, exact=True)).to_be_visible()
                    sheet.get_by_role("button", name="Close card").tap()
                else:
                    sheet.get_by_role("button", name="Close card").tap()
                    change("")
                    page.get_by_role("button", name="Refresh board").tap()
                expect(question).to_have_count(0)
                if not managed:
                    expect(card.get_by_text("0/1 steps", exact=True)).to_be_visible()
            finally:
                context.close()
        finally:
            server.stdin.close()
            server.wait(timeout=15)


if __name__ == "__main__":
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="msedge", headless=True)
        for managed in (False, True):
            check(browser, managed)
        browser.close()
    print("Pending and resolved questions passed on manual and managed phone boards.")
