import http.client
import json
import socket
import unittest

from test_project_events_candidate import ProjectEventsTests, event
from project_events_http_candidate import ProjectEventsServerCandidate


class ProjectEventsHttpTests(unittest.TestCase):
    def setUp(self):
        ProjectEventsTests.setUp(self)
        self.server = ProjectEventsServerCandidate(self.writer)
        self.server.start()

    def tearDown(self):
        self.server.close()
        ProjectEventsTests.tearDown(self)

    def call(self, path, body, *, token=None, headers=None, raw=False, method="POST"):
        data = body if raw else json.dumps(body, ensure_ascii=False).encode("utf-8")
        connection = http.client.HTTPConnection(*self.server.address, timeout=4)
        try:
            hdr = {"Content-Type": "application/json", "Authorization": "Bearer " + (token or self.token), **(headers or {})}
            connection.request(method, path, body=data, headers=hdr)
            reply = connection.getresponse()
            return reply.status, json.loads(reply.read()), dict(reply.getheaders())
        finally:
            connection.close()

    def test_real_submit_exact_lookup_and_unknown_lookup(self):
        status, receipt, headers = self.call("/v1/project-events/submit", event())
        self.assertEqual(status, 200)
        self.assertEqual(headers["Cache-Control"], "no-store")
        status, found, _ = self.call("/v1/project-events/lookup", {"schema":"onoes-mind-project-lookup/v1","projectId":"project-A","eventId":"event-1"})
        self.assertEqual(status, 200)
        self.assertEqual(receipt, found)
        _, absent, _ = self.call("/v1/project-events/lookup", {"schema":"onoes-mind-project-lookup/v1","projectId":"project-A","eventId":"absent"})
        self.assertIs(absent["found"], False)

    def test_browser_and_bad_host_requests_are_denied_without_writes(self):
        for headers in ({"Origin":"https://example.invalid"},{"Referer":"https://example.invalid"},
                        {"Sec-Fetch-Mode":"cors"},{"Host":"localhost:1234"}):
            with self.subTest(headers=headers):
                self.assertEqual(self.call("/v1/project-events/submit", event(), headers=headers)[0], 403)
        self.assertEqual(self.ledger.db.execute("SELECT count(*) FROM memory_records").fetchone()[0], 0)

    def test_duplicates_invalid_utf8_and_nan_are_rejected(self):
        for raw in (b'{"schema":1,"schema":2}', b'\xff', b'{"schema":NaN}'):
            self.assertEqual(self.call("/v1/project-events/submit", raw, raw=True)[0], 400)

    def test_duplicate_length_and_chunked_framing_are_refused(self):
        for extra in ("Content-Length: 2\r\nContent-Length: 2", "Content-Length: 2\r\nTransfer-Encoding: chunked"):
            with socket.create_connection(self.server.address, timeout=4) as sock:
                payload=(f"POST /v1/project-events/submit HTTP/1.1\r\nHost: 127.0.0.1:{self.server.address[1]}\r\nAuthorization: Bearer {self.token}\r\nContent-Type: application/json\r\n{extra}\r\n\r\n{{}}")
                sock.sendall(payload.encode())
                response=sock.recv(4096).split(b"\r\n",1)[0]
                self.assertIn(response.split()[1], [b"400",b"411"])

    def test_bound_and_type_and_method_rejections_do_not_echo_content(self):
        private = "SYNTHETIC-PRIVATE-" + "x" * 17000
        status, body, _ = self.call("/v1/project-events/submit", private.encode(), raw=True)
        self.assertEqual(status, 413)
        self.assertNotIn("SYNTHETIC-PRIVATE", json.dumps(body))
        self.assertEqual(self.call("/v1/project-events/submit", event(), headers={"Content-Type":"text/plain"})[0],415)
        self.assertEqual(self.call("/v1/project-events/submit", {}, method="GET")[0],405)

    def test_revoked_token_and_wrong_project_are_stable_denials(self):
        self.assertEqual(self.call("/v1/project-events/submit", event(projectId="project-B"))[0],403)
        self.assertEqual(self.call("/v1/project-events/submit", event(), token="x"*43)[0],401)
        self.ledger.rotate_credentials("mesh-project-sync")
        self.assertEqual(self.call("/v1/project-events/submit", event())[0],401)

    def test_payload_conflict_and_store_drift_never_report_success(self):
        self.call("/v1/project-events/submit",event())
        changed=event();changed["evidence"][0]["content_hash"]="sha256:changed"
        self.assertEqual(self.call("/v1/project-events/submit",changed)[0],409)
        self.ledger.db.execute("UPDATE recall_store_identity SET authority_ref='drifted'")
        self.assertEqual(self.call("/v1/project-events/submit",event(2))[0],503)

    def test_caller_selected_scope_or_principal_cannot_broaden_event(self):
        for key,value in (("scope","agent/echo/private"),("principal","operator")):
            self.assertEqual(self.call("/v1/project-events/submit",event(**{key:value}))[0],400)


if __name__ == "__main__":
    unittest.main()
