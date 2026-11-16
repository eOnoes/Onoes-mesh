"""Synthetic pipe peer for candidate tests; never starts a listener or live store."""
import json
from pathlib import Path
import sys
import tempfile
from contextlib import ExitStack
import os

sys.stdin.reconfigure(encoding="utf-8", errors="strict")
sys.stdout.reconfigure(encoding="utf-8", errors="strict")
sys.dont_write_bytecode = True
sys.path[:0] = [sys.argv[1], str(Path(__file__).resolve().parents[1] / "integrations" / "mind-recovery-candidate")]
from onoes_mind.ledger import Ledger
from onoes_mind.recall_binding import prepare_store_identity
from project_events_candidate import ProjectEventsCandidate, EventBinding, PRINCIPAL, SCOPE


def emit(value):
    print(json.dumps(value, ensure_ascii=True), flush=True)


with ExitStack() as stack:
    persistent = len(sys.argv) > 2
    if persistent:
        root = Path(sys.argv[2]).resolve()
        if root.parent != Path(tempfile.gettempdir()).resolve() or not root.name.startswith("mesh-project-sync-process-"):
            raise ValueError("Owned process-fixture directory required.")
        temp = str(root)
    else:
        temp = stack.enter_context(tempfile.TemporaryDirectory(prefix="mesh-project-sync-fixture-"))
    path = Path(temp).resolve() / "synthetic.sqlite"
    state_file = Path(temp) / "synthetic-access.json"
    state = json.loads(state_file.read_text()) if persistent and state_file.exists() else None
    if path.exists() != (state is not None):
        raise ValueError("Refuse unknown fixture state.")
    ledger = Ledger(path, environment_id="synthetic")
    try:
        store = state["storeId"] if state else prepare_store_identity(ledger, environment="synthetic", authority_ref="synthetic-owner")
        stat = path.stat()
        binding = EventBinding(str(path.resolve()), state["device"] if state else stat.st_dev,
                               state["inode"] if state else stat.st_ino, store, "synthetic", "synthetic-owner")
        writer = ProjectEventsCandidate(ledger, binding)
        if state:
            token = state["token"]
        else:
            writer.initialize()
            writer.register_project("project-A", "Synthetic project")
            token = writer.enroll(["project-A"])
            if persistent:
                # Synthetic-only fixture credential, never an actual user key.
                state_file.write_text(json.dumps({"storeId":store,"device":stat.st_dev,"inode":stat.st_ino,"token":token}))
        emit({"storeId": store})
        for line in sys.stdin:
            try:
                command = json.loads(line)
                if command["op"] == "close":
                    emit({"closed": True})
                    break
                if command["op"] in {"submit", "submit_then_exit"}:
                    result = writer.submit(token, command["event"])
                    if command["op"] == "submit_then_exit":
                        os._exit(73)  # Owned synthetic writer dies after durable commit, before reply.
                elif command["op"] == "lookup":
                    result = writer.lookup(token, project_id=command["projectId"], event_id=command["eventId"])
                    if result is None:
                        result = {"schema": "onoes-mind-project-absence/v1", "storeId": store,
                                  "scope": SCOPE, "principal": PRINCIPAL, "found": False,
                                  "projectId": command["projectId"], "eventId": command["eventId"]}
                elif command["op"] == "stats":
                    result = {"records": ledger.db.execute("SELECT COUNT(*) FROM memory_records").fetchone()[0],
                              "receipts": ledger.db.execute("SELECT COUNT(*) FROM receipts").fetchone()[0]}
                else:
                    result = {"error": "operation_refused"}
                emit(result)
            except Exception:
                emit({"error": "candidate_refused"})
    finally:
        ledger.close()
