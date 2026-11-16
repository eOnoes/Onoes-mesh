"""Explicit loopback-only event transport; no CLI, enrollment or automatic start."""
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import sqlite3
import threading

from project_events_candidate import ProjectEventsCandidate, EventError, PRINCIPAL, SCOPE, identifier

ERROR_SCHEMA = "onoes-mind-project-error/v1"


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key")
        result[key] = value
    return result


class ProjectEventsServerCandidate:
    def __init__(self, writer, *, port=0, project_ids=None):
        if type(writer) is not ProjectEventsCandidate or type(port) is not int or not 0 <= port <= 65535:
            raise ValueError("Explicit candidate writer and loopback port required.")
        self.writer, self.port = writer, port
        if project_ids is not None and (type(project_ids) is not tuple or not project_ids
                or len(project_ids) > 8 or any(not identifier(p) for p in project_ids)
                or tuple(sorted(set(project_ids))) != project_ids):
            raise ValueError("Explicit fixed project binding required.")
        self.project_ids = project_ids
        self.server = self.thread = None

    @property
    def address(self):
        if self.server is None:
            raise ValueError("Server is not started.")
        return self.server.server_address

    def start(self):
        if self.server is not None:
            raise ValueError("Server already started.")
        owner = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def setup(self):
                super().setup()
                self.connection.settimeout(2)

            def log_message(self, *_args):
                pass

            def reply(self, status, value):
                data = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
                if len(data) > 4096:
                    status, data = 503, b'{"schema":"onoes-mind-project-error/v1","code":"unavailable"}'
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("Connection", "close")
                self.end_headers()
                self.close_connection = True
                try:
                    self.wfile.write(data)
                except OSError:
                    pass

            def error(self, status, code):
                return self.reply(status, {"schema": ERROR_SCHEMA, "code": code})

            def do_POST(self):
                if self.path not in {"/v1/project-events/submit", "/v1/project-events/lookup"}:
                    return self.error(404, "route_not_found")
                if self.headers.get_all("Host") != [f"127.0.0.1:{owner.address[1]}"] or any(
                    name.lower() in {"origin", "referer"} or name.lower().startswith("sec-fetch-") for name in self.headers
                ):
                    return self.error(403, "server_only")
                auth = self.headers.get_all("Authorization", [])
                if len(auth) != 1 or not auth[0].startswith("Bearer ") or not 20 <= len(auth[0][7:]) <= 256:
                    return self.error(401, "unauthorized")
                if self.headers.get_all("Transfer-Encoding"):
                    return self.error(400, "invalid_framing")
                lengths = self.headers.get_all("Content-Length", [])
                if len(lengths) != 1 or not lengths[0].isascii() or not lengths[0].isdigit():
                    return self.error(411, "invalid_framing")
                if len(lengths[0]) > 6 or int(lengths[0]) > 16384:
                    return self.error(413, "request_too_large")
                if self.headers.get_all("Content-Type") != ["application/json"]:
                    return self.error(415, "json_required")
                try:
                    raw = self.rfile.read(int(lengths[0]))
                    if len(raw) != int(lengths[0]):
                        raise ValueError("Incomplete body")
                    body = json.loads(raw.decode("utf-8", errors="strict"), object_pairs_hook=unique_object,
                                      parse_constant=lambda _v: (_ for _ in ()).throw(ValueError("Invalid constant")))
                except (ValueError, UnicodeError, RecursionError, TimeoutError):
                    return self.error(400, "invalid_json")
                if owner.project_ids is not None and (type(body) is not dict
                        or body.get("projectId") not in owner.project_ids):
                    return self.error(403, "project_not_permitted")
                try:
                    if self.path.endswith("/submit"):
                        result = owner.writer.submit(auth[0][7:], body)
                    else:
                        if type(body) is not dict or set(body) != {"schema", "eventId", "projectId"} or body["schema"] != "onoes-mind-project-lookup/v1":
                            return self.error(400, "invalid_event")
                        result = owner.writer.lookup(auth[0][7:], project_id=body["projectId"], event_id=body["eventId"])
                        if result is None:
                            result = {"schema": "onoes-mind-project-absence/v1", "storeId": owner.writer.binding.store_id,
                                      "scope": SCOPE, "principal": PRINCIPAL, "found": False,
                                      "projectId": body["projectId"], "eventId": body["eventId"]}
                except EventError as exc:
                    message = str(exc)
                    if message in {"Unauthorized project sync.", "Ordinary credential collision."}:
                        return self.error(401, "unauthorized")
                    if message == "Project not permitted.":
                        return self.error(403, "project_not_permitted")
                    if message.startswith("Store ") or message in {"Canonical receipt binding mismatch.", "Shared storage unavailable.", "Deletion authority unavailable.", "Project-event format unavailable."}:
                        return self.error(503, "unavailable")
                    if message in {"Event payload conflict.", "Card project conflict.", "Event sequence conflict.",
                                   "Stale source revisions.", "Project is deleted.", "Deleted card history blocks replay.",
                                   "Card already registered.", "Initial linked snapshot required."}:
                        return self.error(409, "event_conflict")
                    return self.error(400, "invalid_event")
                except (sqlite3.Error, OSError):
                    return self.error(503, "unavailable")
                except Exception:
                    return self.error(400, "invalid_event")
                return self.reply(200, result)

            def do_GET(self):
                return self.error(405, "method_not_allowed")

            do_HEAD = do_PUT = do_PATCH = do_DELETE = do_OPTIONS = do_GET

        class LocalServer(HTTPServer):
            allow_reuse_address = False
            request_queue_size = 4

            def handle_error(self, *_args):
                pass

        self.server = LocalServer(("127.0.0.1", self.port), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def close(self):
        if self.server:
            self.server.shutdown()
            self.server.server_close()
            self.thread.join(timeout=3)
            self.server = self.thread = None
