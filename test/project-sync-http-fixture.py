"""Owned ephemeral HTTP peer. Credentials travel only over captured test pipes."""
import json
from pathlib import Path
import sys

sys.stdin.reconfigure(encoding="utf-8", errors="strict")
sys.stdout.reconfigure(encoding="utf-8", errors="strict")
sys.dont_write_bytecode = True
sys.path[:0] = [sys.argv[1], str(Path(__file__).resolve().parents[1] / "integrations" / "mind-recovery-candidate")]
from test_project_events_candidate import ProjectEventsTests
from project_events_http_candidate import ProjectEventsServerCandidate

fixture = ProjectEventsTests("test_canonical_records_provenance_and_exact_receipt_survive_reopen")
fixture.setUp()
server = ProjectEventsServerCandidate(fixture.writer)
try:
    server.start()
    print(json.dumps({"baseUrl":f"http://127.0.0.1:{server.address[1]}/", "token":fixture.token,
                      "storeId":fixture.binding.store_id}), flush=True)
    for line in sys.stdin:
        command = json.loads(line)
        if command["op"] == "close":
            print('{"closed":true}', flush=True)
            break
        if command["op"] == "revoke":
            fixture.ledger.rotate_credentials("mesh-project-sync")
            value = {"revoked":True}
        else:
            value = {"records":fixture.ledger.db.execute("SELECT count(*) FROM memory_records").fetchone()[0],
                     "receipts":fixture.ledger.db.execute("SELECT count(*) FROM receipts").fetchone()[0]}
        print(json.dumps(value), flush=True)
finally:
    server.close()
    fixture.tearDown()
