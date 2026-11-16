"""Synthetic pipe peer for candidate tests; never starts a listener or live store."""
import json
from pathlib import Path
import sys
import tempfile

sys.stdin.reconfigure(encoding="utf-8", errors="strict")
sys.stdout.reconfigure(encoding="utf-8", errors="strict")
sys.dont_write_bytecode = True
sys.path[:0] = [sys.argv[1], str(Path(__file__).resolve().parents[1] / "integrations" / "mind-recovery-candidate")]
from onoes_mind.ledger import Ledger
from onoes_mind.recall_binding import prepare_store_identity
from project_events_candidate import ProjectEventsCandidate, EventBinding, PRINCIPAL, SCOPE


def emit(value):
    print(json.dumps(value, ensure_ascii=True), flush=True)


with tempfile.TemporaryDirectory(prefix="mesh-project-sync-fixture-") as temp:
    path = Path(temp) / "synthetic.sqlite"
    ledger = Ledger(path)
    try:
        store = prepare_store_identity(ledger, environment="synthetic", authority_ref="synthetic-owner")
        stat = path.stat()
        binding = EventBinding(str(path.resolve()), stat.st_dev, stat.st_ino, store, "synthetic", "synthetic-owner")
        writer = ProjectEventsCandidate(ledger, binding)
        writer.initialize()
        writer.register_project("project-A", "Synthetic project")
        token = writer.enroll(["project-A"])
        emit({"storeId": store})
        for line in sys.stdin:
            try:
                command = json.loads(line)
                if command["op"] == "close":
                    emit({"closed": True})
                    break
                if command["op"] == "submit":
                    result = writer.submit(token, command["event"])
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
