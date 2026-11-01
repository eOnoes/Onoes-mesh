"""Overview collector and live handler contracts; no listening server or live writes."""
import ctypes
import io
import json
import unittest
from email.message import Message
from unittest import mock

import server

sd = server.system_dashboard


class CpuLoadTests(unittest.TestCase):
    def test_cpu_uses_two_samples_and_busy_over_total(self):
        with mock.patch.object(sd, "_get_system_times", side_effect=[(100, 300, 200), (140, 400, 300)]) as probe, mock.patch.object(sd.time, "sleep") as sleep:
            result = sd.get_cpu_metrics()
        self.assertEqual(probe.call_count, 2)
        sleep.assert_called_once_with(0.2)
        self.assertTrue(result["load_available"])
        self.assertEqual(result["load_percent"], 80.0)
        for key in ("temperature_c", "fan_percent", "fan_rpm", "power_w"):
            self.assertIsNone(result[key])

    def test_failed_cpu_probe_has_no_number(self):
        for samples in ([OSError("failed")], [(1, 2, 3), OSError("failed")]):
            with self.subTest(samples=samples), mock.patch.object(sd, "_get_system_times", side_effect=samples), mock.patch.object(sd.time, "sleep"):
                result = sd.get_cpu_metrics()
                self.assertFalse(result["load_available"])
                self.assertIsNone(result["load_percent"])
                self.assertIn("failed", result["load_reason"])

    def test_empty_or_invalid_cpu_delta_has_no_number(self):
        for after in ((100, 300, 200), (99, 400, 300), (400, 310, 210)):
            with self.subTest(after=after), mock.patch.object(sd, "_get_system_times", side_effect=[(100, 300, 200), after]), mock.patch.object(sd.time, "sleep"):
                result = sd.get_cpu_metrics()
                self.assertFalse(result["load_available"])
                self.assertIsNone(result["load_percent"])

    def test_kernel32_failure_is_unavailable(self):
        with mock.patch.object(ctypes.windll.kernel32, "GetSystemTimes", return_value=0):
            result = sd.get_cpu_metrics()
        self.assertFalse(result["load_available"])
        self.assertIsNone(result["load_percent"])

    def test_filetime_high_words_are_preserved(self):
        def probe(*pointers):
            for index, pointer in enumerate(pointers):
                pointer._obj.dwHighDateTime = index + 1
                pointer._obj.dwLowDateTime = 7
            return 1
        with mock.patch.object(ctypes.windll.kernel32, "GetSystemTimes", side_effect=probe):
            self.assertEqual(sd._get_system_times(), ((1 << 32) + 7, (2 << 32) + 7, (3 << 32) + 7))

    def test_missing_gpu_command_is_unavailable(self):
        with mock.patch.object(sd, "subprocess_run", side_effect=FileNotFoundError("missing")):
            self.assertFalse(sd.get_gpu_metrics()["available"])


class OverviewRouteTests(unittest.TestCase):
    def call(self, method, path, host="emitchell.tail8c4a75.ts.net:8450", origin=None):
        handler = object.__new__(server.Handler)
        handler.path = path
        handler.headers = Message()
        handler.headers.add_header("Host", host)
        if origin is not None:
            handler.headers.add_header("Origin", origin)
        handler.wfile = io.BytesIO()
        handler.rfile = io.BytesIO(b"{}")
        handler.send_response = mock.Mock()
        handler.send_header = mock.Mock()
        handler.end_headers = mock.Mock()
        getattr(handler, "do_" + method)()
        status = handler.send_response.call_args.args[0]
        headers = dict(call.args for call in handler.send_header.call_args_list)
        return status, headers, json.loads(handler.wfile.getvalue())

    def test_get_reuses_collector_and_never_persists(self):
        state = {"metrics": {"cpu": {"load_available": False, "load_percent": None}, "drives": []}, "llm": [{"engine": "strata", "status": "unavailable"}]}
        with mock.patch.object(sd, "collect_state", return_value=state) as collect, mock.patch.object(sd, "persist_sample", side_effect=AssertionError("must not persist")), mock.patch.object(server, "read_state", side_effect=AssertionError("must not read relay state")):
            status, headers, body = self.call("GET", "/api/system/metrics?read=1", origin="https://emitchell.tail8c4a75.ts.net:8450")
        self.assertEqual(status, 200)
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertEqual(body, {**state["metrics"], "llm": state["llm"]})
        collect.assert_called_once_with()
        self.assertEqual(sd.ROOT, server.ROOT / "mesh-system-dashboard")

    def test_host_and_origin_checks_run_before_collection(self):
        with mock.patch.object(sd, "collect_state") as collect:
            for host, origin in (("evil.example", None), ("127.0.0.1:8771", "https://evil.example")):
                with self.subTest(host=host, origin=origin):
                    status, headers, _ = self.call("GET", "/api/system/metrics", host, origin)
                    self.assertEqual(status, 403)
                    self.assertEqual(headers["Cache-Control"], "no-store")
            collect.assert_not_called()

    def test_metrics_is_get_only(self):
        with mock.patch.object(sd, "collect_state") as collect, mock.patch.object(server, "read_state", side_effect=AssertionError("must not read state")):
            status, headers, _ = self.call("POST", "/api/system/metrics")
        self.assertEqual(status, 404)
        self.assertEqual(headers["Cache-Control"], "no-store")
        collect.assert_not_called()

    def test_live_server_has_no_system_control_or_stream_routes(self):
        paths = ["/api/system/" + action for action in ("pause", "unload", "unload-all", "stop", "kill", "suspend", "restart", "events", "llm/strata/pause", "llm/strata/unload")]
        with mock.patch.object(sd, "collect_state") as collect, mock.patch.object(server, "read_state", side_effect=AssertionError("must not read state")), mock.patch.object(server, "atomic_json", side_effect=AssertionError("must not write")):
            for method in ("GET", "POST"):
                for path in paths:
                    with self.subTest(method=method, path=path):
                        status, headers, _ = self.call(method, path)
                        self.assertEqual(status, 404)
                        self.assertEqual(headers["Cache-Control"], "no-store")
            collect.assert_not_called()


if __name__ == "__main__":
    unittest.main()
