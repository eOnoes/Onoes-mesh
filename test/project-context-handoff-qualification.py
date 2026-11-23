"""Cross-repo acceptance. Put the canonical Mind checkout on PYTHONPATH."""
import asyncio
from contextlib import ExitStack
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys

MESH = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(MESH / "integrations/mind-recovery-candidate"))

from mcp.shared.memory import create_connected_server_and_client_session
from onoes_mind import Ledger
from onoes_mind.agent_context import AgentContextBinding, ProjectContextReader
from onoes_mind.context_channel import ContextChannelAdapter
from onoes_mind.context_enrollment import enroll_context_reader
from onoes_mind.context_tool import TOOL_NAME, project_tool_server
from onoes_mind.project_tool_grant import ReviewedProjectToolGrant
from onoes_mind.recall_binding import RecallBinding, prepare_mesh_principal, prepare_store_identity
from project_events_candidate import EventBinding, ProjectEventsCandidate


def read_revised_fixture(tmp_path, *, keep_board=False):
    options = ["--keep-fixture"] if keep_board else []
    run = subprocess.run(["node", str(MESH / "test/print-card-events.mjs"), *options], cwd=tmp_path,
                         capture_output=True, encoding="utf-8", timeout=30,
                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    assert run.returncode == 0, run.stderr
    first, revised = json.loads(run.stdout)
    assert [first["kind"], revised["kind"]] == ["created", "progress"]
    assert "PRIVATE" not in run.stdout
    path = tmp_path / "canonical.sqlite"
    with ExitStack() as resources:
        ledger = Ledger(path, environment_id="synthetic")
        resources.callback(ledger.close)
        ledger.create_principal("operator")
        operator = ledger.issue_credential("operator", secrets.token_urlsafe(32))
        store_id = prepare_store_identity(ledger, environment="synthetic", authority_ref="fixture:owner")
        scope = "project/onoes-mind/shared"
        prepare_mesh_principal(ledger, scope_id=scope)
        info = path.stat()
        store = RecallBinding(str(path), store_id, "synthetic", "fixture:owner", scope, info.st_dev,
                              info.st_ino, "fixture:custodian", "fixture:revoke", "fixture:review")
        writer = ProjectEventsCandidate(ledger, EventBinding(str(path), info.st_dev, info.st_ino,
                                                               store_id, "synthetic", "fixture:owner"))
        writer.initialize()
        writer.register_project("project-A", "Desktop tray")
        writer_token = writer.enroll(["project-A"])

        def channel(agent, transport):
            binding = AgentContextBinding(store, "context-"+agent, "project-A")
            custody = {}
            def save_new(token):
                assert not custody
                custody["token"] = token
                return True
            enroll_context_reader(ledger, binding, operator_token=operator, save_new_token=save_new)
            reader = ProjectContextReader(path, binding=binding)
            resources.callback(reader.close)
            return ContextChannelAdapter(reader, agent, transport, lambda: custody["token"])

        echo = channel("echo", "relay")
        nims = channel("nims", "telegram")
        grant = ReviewedProjectToolGrant(tmp_path/"grant.json", nims.reader.context_binding, "fixture:tool")
        server = project_tool_server(nims, grant)
        writer.submit(writer_token, first)

        async def trial():
            async with create_connected_server_and_client_session(server) as client:
                query = {"query": "tray"}
                assert (await client.list_tools()).tools == []
                grant.path.write_bytes(grant.document())
                async def current():
                    result = await client.call_tool(TOOL_NAME, query)
                    assert not result.isError
                    row, = json.loads(result.content[0].text)["records"]
                    echo_row, = json.loads(echo.read(query))["records"]
                    assert row == echo_row
                    return row
                before = await current()
                assert json.loads(before["claim"])["goal"] == first["snapshot"]["goal"]
                receipt = writer.submit(writer_token, revised)
                after = await current()
                assert before["record_id"] == after["record_id"] and before["revision_id"] != after["revision_id"]
                assert json.loads(after["claim"])["goal"] == "Tray width 95 mm ±0.2 mm. CAD tray-v2.step"
                assert after["provenance"] == revised["evidence"]
                assert after["provenance"][0]["ref"].startswith("card:"+first["cardId"]+"@")
                assert writer.submit(writer_token, revised) == receipt
                assert await current() == after
                grant.path.unlink()
                assert (await client.call_tool(TOOL_NAME, query)).isError
                assert json.loads(echo.read(query))["records"] == [after]
                return after
        return asyncio.run(trial())


def test_recorded_card_edit_reaches_independent_agent_and_replay_keeps_revision(tmp_path):
    read_revised_fixture(tmp_path)


def test_offline_worker_can_use_only_the_selected_assignment_brief(tmp_path):
    import pytest
    image = os.environ.get("MESH_TEST_WORKER_IMAGE")
    if not image:
        pytest.skip("Set MESH_TEST_WORKER_IMAGE to the local Node image digest for this Docker check")
    record = read_revised_fixture(tmp_path, keep_board=True)
    assert record["project_id"] == "project-A"
    brief = {
        "project": record["project_id"],
        "revision": record["revision_id"],
        "source": record["provenance"][0]["ref"],
        "spec": json.loads(record["claim"])["goal"],
    }
    run = subprocess.run(["node", str(MESH / "test/print-worker-roundtrip.mjs"), sys.executable],
                         cwd=tmp_path, input=json.dumps(brief), encoding="utf-8",
                         capture_output=True, timeout=120)
    assert run.returncode == 0, run.stderr
    receipt = json.loads(run.stdout)
    assert receipt["result"] == "tray-v2.step: 94.8–95.2 mm"
    assert receipt["evidence"] == f'{brief["source"]} / {brief["revision"]}'
    assert receipt["dispatches"] == 1 and receipt["decision"] == "pending"
