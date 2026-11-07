"""Disposable actual-candidate HTTP fixture. Never imports the live supervisor."""
import json
import sys
from test.supervisor_candidate_http_test import CandidateHTTPTests

CandidateHTTPTests.setUpClass()
fixture = CandidateHTTPTests()
try:
    fixture.setUp()
    fixture.owner["identity"].update(
        executable="D:/models/nemotron/tools/llama-b11669-cuda12.4/llama-server.exe",
        executableSha256="f" * 64,
        cwd="D:/models/nemotron/tools/llama-b11669-cuda12.4")
    routes = fixture.module._MESH_ROUTES
    print(json.dumps({"origin": fixture.origin,
                      "moduleSha256": fixture.guard._MODULE_SHA256,
                      "supervisorSha256": routes.supervisor_sha256}), flush=True)
    for line in sys.stdin:
        request = json.loads(line)
        if request == {"action": "finish-and-evict"}:
            fixture.queue.pop()()
            # Simulate a completed receipt evicted before Mesh observed it.
            fixture.gate._receipts.clear()
        elif request != {"action": "inspect"}:
            raise ValueError("Unknown fixture action")
        print(json.dumps({"calls": len(fixture.calls), "queued": len(fixture.queue), "chats": len(fixture.chat_calls)}), flush=True)
finally:
    if hasattr(fixture, "server"):
        fixture.tearDown()
    CandidateHTTPTests.tearDownClass()
