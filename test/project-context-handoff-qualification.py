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


def read_revised_fixture(tmp_path, *, keep_board=False, missing_tolerance=False, check_width=False):
    options = ["--keep-fixture"] if keep_board else ["--private-edit"]
    if missing_tolerance:
        options.append("--missing-tolerance")
    run = subprocess.run(["node", str(MESH / "test/print-card-events.mjs"), *options], cwd=tmp_path,
                         capture_output=True, encoding="utf-8", timeout=30,
                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    assert run.returncode == 0, run.stderr
    first, revised, *private_edits = json.loads(run.stdout)
    assert len(private_edits) == (0 if keep_board else 1)
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

        def channel(agent, transport, project="project-A"):
            binding = AgentContextBinding(store, "context-"+agent, project)
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
        if check_width:
            from onoes_mind.project_tool_grant import PRINT_WIDTH_TOOL_NAME
            width_grant = ReviewedProjectToolGrant(tmp_path/"width.json", nims.reader.context_binding,
                                                  "fixture:width", PRINT_WIDTH_TOOL_NAME)
            server = project_tool_server(nims, grant, print_width_grant=width_grant)
        else:
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
                def revision(row):
                    return {key: row[key] for key in ("record_id", "revision_id")}
                if check_width:
                    assert (await client.call_tool(PRINT_WIDTH_TOOL_NAME, revision(before))).isError
                    width_grant.path.write_bytes(width_grant.document())
                    assert [t.name for t in (await client.list_tools()).tools] == [TOOL_NAME, PRINT_WIDTH_TOOL_NAME]
                receipt = writer.submit(writer_token, revised)
                after = await current()
                assert before["record_id"] == after["record_id"] and before["revision_id"] != after["revision_id"]
                expected_goal = "Tray width 95 mm" + ("" if missing_tolerance else " ±0.2 mm") + ". CAD tray-v2.step"
                assert json.loads(after["claim"])["goal"] == expected_goal
                assert after["provenance"] == revised["evidence"]
                assert after["provenance"][0]["ref"].startswith("card:"+first["cardId"]+"@")
                assert writer.submit(writer_token, revised) == receipt
                assert await current() == after
                if private_edits:
                    private_edit, = private_edits
                    assert private_edit["kind"] == "progress"
                    assert private_edit["revisions"]["progress"] == revised["revisions"]["progress"] + 1
                    assert private_edit["snapshot"] == revised["snapshot"]
                    assert private_edit["snapshot"]["result"] == ""
                    private_receipt = writer.submit(writer_token, private_edit)
                    last = await current()
                    assert last["record_id"] == after["record_id"] and last["revision_id"] != after["revision_id"]
                    assert last["provenance"] == private_edit["evidence"] and "PRIVATE" not in json.dumps(last)
                    assert json.loads(last["claim"])["goal"] == expected_goal
                    assert writer.submit(writer_token, private_edit) == private_receipt
                    assert await current() == last
                    after = last
                if check_width:
                    assert (await client.call_tool(PRINT_WIDTH_TOOL_NAME, revision(before))).isError
                    choice = revision(after)
                    for invalid in (dict(choice, width=123), dict(choice, revision_id=True),
                                    dict(choice, record_id="rec_mesh_"+"0"*64)):
                        assert (await client.call_tool(PRINT_WIDTH_TOOL_NAME, invalid)).isError
                    result = await client.call_tool(PRINT_WIDTH_TOOL_NAME, choice)
                    assert not result.isError
                    report = json.loads(result.content[0].text)
                    assert report["provenance"] == after["provenance"] and report["revision_id"] == after["revision_id"]
                    if missing_tolerance:
                        assert report["status"] == "needs_clarification" and "minimum_mm" not in report
                    else:
                        assert (report["status"], report["cad_filename"], report["minimum_mm"], report["maximum_mm"]) == (
                            "calculated", "tray-v2.step", "94.8", "95.2")
                    other = channel("local", "relay", project="separate-project")
                    def width_server(adapter):
                        grant = ReviewedProjectToolGrant(tmp_path/(adapter.reader.context_binding.principal_id+".json"),
                                                         adapter.reader.context_binding, "fixture:width", PRINT_WIDTH_TOOL_NAME)
                        grant.path.write_bytes(grant.document())
                        return project_tool_server(adapter, lambda *_: False, print_width_grant=grant)
                    echo_tools = width_server(echo)
                    other_tools = width_server(other)
                    async with create_connected_server_and_client_session(echo_tools) as echo_client:
                        reply = await echo_client.call_tool(PRINT_WIDTH_TOOL_NAME, choice)
                        assert not reply.isError and json.loads(reply.content[0].text) == report
                    async with create_connected_server_and_client_session(other_tools) as other_client:
                        assert (await other_client.call_tool(PRINT_WIDTH_TOOL_NAME, choice)).isError
                    width_grant.path.unlink()
                    assert (await client.call_tool(PRINT_WIDTH_TOOL_NAME, choice)).isError
                    assert await current() == after
                grant.path.unlink()
                assert (await client.call_tool(TOOL_NAME, query)).isError
                assert json.loads(echo.read(query))["records"] == [after]
                return after
        return asyncio.run(trial())


def test_recorded_card_edit_reaches_independent_agent_and_replay_keeps_revision(tmp_path):
    read_revised_fixture(tmp_path)


def test_both_agents_can_check_the_current_print_width_with_its_own_grant(tmp_path):
    read_revised_fixture(tmp_path, check_width=True)


def test_print_width_returns_a_question_when_tolerance_is_missing(tmp_path):
    read_revised_fixture(tmp_path, check_width=True, missing_tolerance=True)


def test_offline_worker_can_use_only_the_selected_assignment_brief(tmp_path):
    receipt = run_offline_assignment(tmp_path)
    assert receipt["result"] == "tray-v2.step: 94.8–95.2 mm"
    assert [step["status"] for step in receipt["checklist"]] == ["done"]


def test_model_leaves_incomplete_spec_pending_on_the_original_card(tmp_path):
    import pytest
    if not os.environ.get("MESH_TEST_PRINT_GGUF"):
        pytest.skip("Requires the qualified local model")
    receipt = run_offline_assignment(tmp_path, missing_tolerance=True)
    assert receipt["result"].startswith("Clarification requested")
    assert [step["status"] for step in receipt["checklist"]] == ["pending"]


def run_offline_assignment(tmp_path, *, missing_tolerance=False):
    import pytest
    image = os.environ.get("MESH_TEST_WORKER_IMAGE")
    if not image:
        pytest.skip("Set MESH_TEST_WORKER_IMAGE to the local Node image digest for this Docker check")
    record = read_revised_fixture(tmp_path, keep_board=True, missing_tolerance=missing_tolerance)
    assert record["project_id"] == "project-A"
    brief = {
        "project": record["project_id"],
        "revision": record["revision_id"],
        "source": record["provenance"][0]["ref"],
        "spec": json.loads(record["claim"])["goal"],
    }
    run = subprocess.run(["node", str(MESH / "test/print-worker-roundtrip.mjs"), sys.executable],
                         cwd=tmp_path, input=json.dumps(brief), encoding="utf-8",
                         capture_output=True, timeout=195 if os.environ.get("MESH_TEST_PRINT_GGUF") else 120)
    assert run.returncode == 0, run.stderr
    receipt = json.loads(run.stdout)
    evidence = f'{brief["source"]} / {brief["revision"]}'
    if os.environ.get("MESH_TEST_PRINT_GGUF"):
        evidence += " / TinyLlama 1.1B (CPU)"
    assert receipt["evidence"] == evidence
    assert receipt["dispatches"] == 1 and receipt["decision"] == "pending"
    return receipt
