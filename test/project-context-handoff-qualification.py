"""Cross-repo acceptance. Put the Mind checkout and its tests on PYTHONPATH."""
import asyncio
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "integrations/mind-recovery-candidate"))

from mcp.shared.memory import create_connected_server_and_client_session
from onoes_mind.context_tool import TOOL_NAME, project_tool_server
from project_events_candidate import EventBinding, ProjectEventsCandidate
from test_project_events_candidate import event
from test_agent_context import channel, context_store


def test_recorded_card_edit_reaches_independent_agent_and_replay_keeps_revision(context_store):
    ledger, binding, open_reader, _ = context_store
    path = Path(binding.database_path)
    info = path.stat()
    writer = ProjectEventsCandidate(ledger, EventBinding(
        str(path), info.st_dev, info.st_ino, binding.store_id, "synthetic", "fixture:owner"))
    writer.initialize()
    writer.register_project("project-A", "Desktop tray")
    token = writer.enroll(["project-A"])
    first, revised = event(1), event(2)
    for change, width, ref in [(first, 90, "tray-v1.step"), (revised, 95, "tray-v2.step")]:
        change["snapshot"].update(title="Desk tray", goal=f"Tray width {width} mm")
        change["evidence"][0]["ref"] = ref
    writer.submit(token, first)
    echo = channel(open_reader("echo", "project-A"))
    nims = channel(open_reader("nims", "project-A"), "nims", "telegram", "synthetic-context-nims")
    def grant(bound, name):
        return (bound.principal_id, bound.project_id, name) == ("context-nims", "project-A", TOOL_NAME)

    async def trial():
        async with create_connected_server_and_client_session(project_tool_server(nims, grant)) as client:
            async def current():
                result = await client.call_tool(TOOL_NAME, {"query": "tray"})
                assert not result.isError
                row, = json.loads(result.content[0].text)["records"]
                echo_row, = json.loads(echo.read({"query": "tray"}))["records"]
                assert row == echo_row
                return row
            before = await current()
            assert json.loads(before["claim"])["goal"] == "Tray width 90 mm"
            receipt = writer.submit(token, revised)
            after = await current()
            assert before["record_id"] == after["record_id"]
            assert before["revision_id"] != after["revision_id"]
            assert json.loads(after["claim"])["goal"] == "Tray width 95 mm"
            assert [ref["ref"] for ref in after["provenance"]] == ["tray-v2.step"]
            assert writer.submit(token, revised) == receipt
            assert await current() == after
    asyncio.run(trial())
