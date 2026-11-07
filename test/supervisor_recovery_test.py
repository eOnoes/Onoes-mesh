import unittest
import uuid
from test.supervisor_mesh_control_test import Fixture, resident
from lib.supervisor_mesh_control import ControlRefused, MeshControlGate, MeshSupervisorRoutes


class RecoveryTests(unittest.TestCase):
    def request(self, fixture, command, original_boot=None):
        return {"command": command, "originalBootId": original_boot or fixture.gate.boot_id,
                "currentExpected": fixture.gate.status()["expected"]}

    def test_never_delivered_command_is_fenced_without_owner_call_and_cannot_execute_late(self):
        f = Fixture()
        command = f.command()
        body = self.request(f, command)
        proof = f.gate.recover(body)
        self.assertEqual(proof["recovery"]["outcome"], "UNKNOWN")
        self.assertEqual(f.calls, [])
        self.assertEqual(f.queue, [])
        self.assertEqual(f.gate.recover(body), proof)
        with self.assertRaises(ControlRefused):
            f.gate.submit(command)
        self.assertTrue(f.gate.status()["unload"])
        self.assertNotEqual(f.gate.status()["expected"], command["expected"])

    def test_accepted_handle_is_returned_not_fenced_and_other_active_work_blocks_recovery(self):
        f = Fixture()
        command = f.command()
        f.gate.submit(command)
        self.assertEqual(f.gate.recover(self.request(f, command))["receipt"]["state"], "ACCEPTED")
        with self.assertRaisesRegex(ControlRefused, "OPERATION_IN_PROGRESS"):
            f.gate.recover(self.request(f, {**command, "id": str(uuid.uuid4())}))
        self.assertEqual(len(f.queue), 1)
        f.queue.pop()()
        self.assertEqual(f.gate.recover(self.request(f, command))["receipt"]["state"], "COMPLETED")
        self.assertEqual(len(f.calls), 1)

    def test_new_boot_can_fence_old_binding_but_busy_uncertain_or_stale_owner_cannot(self):
        f = Fixture()
        command, old_boot = f.command(), f.gate.boot_id
        f.gate = MeshControlGate(f.lock, lambda: f.value, f.perform, f.queue.append)
        body = self.request(f, command, old_boot)
        f.value = {"state": "uncertain"}
        with self.assertRaises(ControlRefused):
            f.gate.recover(body)
        f.value = resident()
        body = self.request(f, command, old_boot)
        with self.assertRaisesRegex(ControlRefused, "OWNER_CHANGED"):
            f.gate.recover({**body, "currentExpected": "0" * 64})
        f.lock.acquire()
        try:
            with self.assertRaisesRegex(ControlRefused, "OWNER_BUSY"):
                f.gate.recover(body)
        finally:
            f.lock.release()
        proof = f.gate.recover(body)["recovery"]
        self.assertEqual(proof["originalBootId"], old_boot)
        self.assertEqual(proof["active"], None)
        self.assertEqual(f.calls, [])

    def test_fence_eviction_and_new_boot_still_reject_original_late_request(self):
        f = Fixture()
        first = f.command()
        f.gate.recover(self.request(f, first))
        for _ in range(65):
            f.gate.recover(self.request(f, f.command()))
        self.assertLessEqual(len(f.gate._fences), 64)
        with self.assertRaises(ControlRefused):
            f.gate.submit(first)
        f.gate = MeshControlGate(f.lock, lambda: f.value, f.perform, f.queue.append)
        with self.assertRaises(ControlRefused):
            f.gate.submit(first)
        self.assertEqual(f.calls, [])

    def test_route_is_strict_and_bound_to_the_nemotron_lane(self):
        import json
        f = Fixture()
        routes = MeshSupervisorRoutes(f.gate, supervisor_sha256="b" * 64)
        body = json.dumps(self.request(f, f.command())).encode()
        status, result = routes.handle(8099, "POST", "/mesh/v1/recover", body, "application/json")
        self.assertEqual(status, 200)
        self.assertEqual(result["bootId"], f.gate.boot_id)
        self.assertEqual(result["supervisorSha256"], "b" * 64)
        self.assertEqual(routes.handle(8098, "POST", "/mesh/v1/recover", body, "application/json")[0], 404)
        self.assertEqual(routes.handle(8099, "GET", "/mesh/v1/recover")[0], 405)
        self.assertEqual(routes.handle(8099, "POST", "/mesh/v1/recover", b'{"command":{},"command":{}}', "application/json")[0], 400)


if __name__ == '__main__':
    unittest.main()
