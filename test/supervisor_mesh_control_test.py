import copy
import json
import threading
import unittest
import uuid
from lib.supervisor_mesh_control import MeshControlGate, ControlRefused, MODEL, NemotronSupervisorOwner, MeshSupervisorRoutes
from types import SimpleNamespace


def resident(pid=123, model=MODEL):
    return {"state": "resident", "modelId": model, "ownerVerified": True,
            "identity": {"pid": pid, "createdAt": "2026-11-07T12:00:00Z",
                         "executable": "D:/models/nemotron/tools/llama-server.exe",
                         "executableSha256": "a" * 64, "argvHash": "b" * 64}}


class Fixture:
    def __init__(self, initial=None):
        self.value = initial or resident()
        self.queue = []
        self.calls = []
        self.lock = threading.Lock()
        self.gate = MeshControlGate(self.lock, lambda: self.value, self.perform, self.queue.append)

    def perform(self, action, original):
        self.calls.append((action, original))
        self.value = {"state": "empty", "clear": True, "identity": None} if action == "unload" else resident(456)

    def command(self, action="unload"):
        return {"id": str(uuid.uuid4()), "action": action, "expected": self.gate.status()["expected"]}


class SupervisorGateTests(unittest.TestCase):
    def test_only_fixed_nemotron_or_verified_empty_is_eligible(self):
        for value in [resident(model="other-model"), {**resident(), "ownerVerified": False},
                      {"state": "uncertain"}, {"state": "empty", "identity": None, "clear": False}]:
            f = Fixture(value)
            for action in ["load", "unload"]:
                with self.assertRaises(ControlRefused):
                    f.gate.submit(f.command(action))
            self.assertEqual(f.calls, [])

    def test_exact_owner_stop_and_load_require_fresh_token_and_readback(self):
        f = Fixture()
        command = f.command()
        self.assertEqual(f.gate.submit(command)["state"], "ACCEPTED")
        self.assertFalse(f.gate.status()["unload"])
        f.queue.pop()()
        receipt = f.gate.receipt(command["id"])
        self.assertEqual(receipt["state"], "COMPLETED")
        self.assertTrue(receipt["readBackVerified"])
        self.assertEqual(f.calls[0][1]["identity"]["pid"], 123)
        load = f.command("load")
        f.gate.submit(load)
        f.queue.pop()()
        self.assertEqual(f.gate.receipt(load["id"])["state"], "COMPLETED")

    def test_duplicate_is_receipt_only_and_changed_payload_conflicts(self):
        f = Fixture()
        command = f.command()
        f.gate.submit(command)
        self.assertEqual(f.gate.submit(command)["state"], "ACCEPTED")
        self.assertEqual(len(f.queue), 1)
        with self.assertRaises(ControlRefused):
            f.gate.submit({**command, "action": "load"})
        f.queue.pop()()
        self.assertEqual(f.gate.submit(command)["state"], "COMPLETED")
        self.assertEqual(len(f.calls), 1)

    def test_concurrent_duplicate_reservations_advance_one_job_only(self):
        f=Fixture();command=f.command();rendezvous=threading.Barrier(2)
        class ContendedLock:
            inner=threading.Lock()
            def acquire(self, timeout):
                if threading.current_thread().name.startswith("submit-"):
                    rendezvous.wait(timeout=2)
                return self.inner.acquire(timeout=timeout)
            def release(self):self.inner.release()
        f.gate._owner=ContendedLock();answers=[];errors=[]
        def submit():
            try:answers.append(f.gate.submit(copy.deepcopy(command)))
            except Exception as error:errors.append(error)
        workers=[threading.Thread(target=submit,name="submit-"+str(i)) for i in range(2)]
        for worker in workers:worker.start()
        for worker in workers:worker.join(timeout=3)
        self.assertTrue(all(not worker.is_alive() for worker in workers));self.assertEqual(errors,[])
        self.assertEqual(len(answers),2);self.assertEqual(len(f.queue),1)
        f.queue.pop()();self.assertEqual(len(f.calls),1)

    def test_owner_change_before_submit_or_before_worker_never_stops_new_process(self):
        f = Fixture()
        command = f.command()
        f.value = resident(999)
        with self.assertRaises(ControlRefused):
            f.gate.submit(command)
        self.assertEqual(f.calls, [])
        command = f.command()
        f.gate.submit(command)
        f.value = resident(777)
        f.queue.pop()()
        self.assertEqual(f.gate.receipt(command["id"])["state"], "REFUSED")
        self.assertFalse(f.gate.receipt(command["id"])["ownerCallStarted"])
        self.assertEqual(f.calls, [])

    def test_owner_busy_and_second_operation_fail_closed(self):
        f = Fixture()
        command = f.command()
        f.lock.acquire()
        try:
            with self.assertRaises(ControlRefused):
                f.gate.submit(command)
        finally:
            f.lock.release()
        f.gate.submit(command)
        with self.assertRaises(ControlRefused):
            f.gate.submit(f.command())
        self.assertEqual(f.calls, [])

    def test_restart_and_evicted_receipts_cannot_authorize_old_command(self):
        f = Fixture()
        old = f.command()
        f.gate.submit(old)
        f.queue.pop()()
        restarted = Fixture()
        with self.assertRaises(ControlRefused):
            restarted.gate.submit(old)
        for index in range(66):
            action = "load" if f.value["state"] == "empty" else "unload"
            f.gate.submit(f.command(action))
            f.queue.pop()()
        before = len(f.calls)
        with self.assertRaises(ControlRefused):
            f.gate.submit(old)
        self.assertEqual(len(f.calls), before)

    def test_failed_dispatch_or_unverified_result_never_retries_or_claims_success(self):
        f = Fixture()
        f.gate._launch = lambda work: (_ for _ in ()).throw(RuntimeError("private error"))
        command = f.command()
        self.assertEqual(f.gate.submit(command)["state"], "UNKNOWN")
        self.assertEqual(f.gate.submit(command)["state"], "UNKNOWN")
        self.assertEqual(f.calls, [])
        f = Fixture()
        f.gate._perform = lambda action, value: None
        command = f.command()
        f.gate.submit(command)
        f.queue.pop()()
        self.assertFalse(f.gate.receipt(command["id"])["readBackVerified"])

    def test_malformed_identity_or_extra_capture_data_never_becomes_control_authority(self):
        for key, value in [("pid", "123"), ("pid", True), ("createdAt", "bad"), ("executable", "relative.exe"), ("argvHash", "bad")]:
            source = resident()
            source["identity"][key] = value
            f = Fixture(source)
            self.assertFalse(f.gate.status()["unload"])
            with self.assertRaises(ControlRefused):
                f.gate.submit(f.command())
        f = Fixture({**resident(), "prompt": "private content"})
        with self.assertRaises(ControlRefused):
            f.gate.status()

    def test_command_schema_refuses_paths_profiles_extra_fields_and_invalid_ids(self):
        f = Fixture()
        good = f.command()
        for command in [{**good, "path": "somewhere"}, {**good, "profile": "other"},
                        {**good, "action": "shutdown"}, {**good, "id": "bad"}, {**good, "expected": None}]:
            with self.assertRaises(ControlRefused):
                f.gate.submit(command)
        self.assertEqual(f.calls, [])


class NativeBindingTests(unittest.TestCase):
    def fixture(self, loaded=True):
        argv = [str(NemotronSupervisorOwner.EXECUTABLE), "-m", str(NemotronSupervisorOwner.MODEL_FILE),
                "--alias", MODEL, "--host", "127.0.0.1", "--port", "8199"]
        original = SimpleNamespace(pid=123, poll=lambda: None)
        owner = SimpleNamespace(proc=original if loaded else None, port=8099 if loaded else None,
                                loading=False, ident={"pid":123,"created":1700000000.0,"exe":argv[0],"cmdline":argv})
        facts = {"created":1700000000.0,"cmdline":list(argv),"hash":"a"*64,"listening":True,"orphan":False,"health":True}
        calls = []
        live = SimpleNamespace(create_time=lambda:facts["created"],exe=lambda:argv[0],cmdline=lambda:facts["cmdline"],
            cwd=lambda:"D:/models/nemotron/tools/llama-b11669-cuda12.4",
            net_connections=lambda **kw:[SimpleNamespace(status="LISTEN",laddr=SimpleNamespace(ip="127.0.0.1",port=8199))] if facts["listening"] else [])
        def ensure(port):
            calls.append(("ensure",port));owner.proc=original;owner.port=8099;return True,"ok"
        def unload(reason):
            calls.append(("unload",reason));owner.proc=None;owner.port=None
        owner.ensure=ensure;owner.unload=unload
        binding=NemotronSupervisorOwner(owner,argv,"a"*64,process_reader=lambda pid:live,
            port_clear=lambda:not facts["orphan"],hash_executable=lambda path:facts["hash"],health=lambda:facts["health"])
        return owner,facts,calls,binding

    def test_native_binding_uses_retained_owner_and_exact_model_runtime_listener(self):
        owner,facts,calls,binding=self.fixture()
        self.assertEqual(binding.capture()["state"],"resident")
        for key,value in [("created",1700000001.0),("cmdline",["different"]),("hash","b"*64),("listening",False)]:
            old=facts[key];facts[key]=value;self.assertEqual(binding.capture(),{"state":"uncertain"});facts[key]=old
        owner.port=18090;self.assertEqual(binding.capture(),{"state":"uncertain"});self.assertEqual(calls,[])

    def test_native_binding_never_adopts_or_evicts_an_unowned_listener(self):
        owner,facts,calls,binding=self.fixture(False)
        facts["orphan"]=True
        self.assertEqual(binding.capture(),{"state":"uncertain"});self.assertEqual(calls,[])
        with self.assertRaises(ControlRefused):binding.perform("load",{"state":"empty","clear":True,"identity":None})
        self.assertEqual(calls,[])

    def test_native_binding_calls_only_fixed_owner_load_and_original_owner_unload(self):
        owner,facts,calls,binding=self.fixture(False)
        queue=[];gate=MeshControlGate(threading.Lock(),binding.capture,binding.perform,queue.append)
        command={"id":str(uuid.uuid4()),"action":"load","expected":gate.status()["expected"]}
        gate.submit(command);queue.pop()();self.assertTrue(gate.receipt(command["id"])["readBackVerified"])
        self.assertEqual(calls,[("ensure",8099)])
        command={"id":str(uuid.uuid4()),"action":"unload","expected":gate.status()["expected"]}
        gate.submit(command);queue.pop()();self.assertTrue(gate.receipt(command["id"])["readBackVerified"])
        self.assertEqual(calls[-1][0],"unload");self.assertIsNone(owner.proc)

    def test_health_failure_or_replaced_owner_stays_unknown_without_another_action(self):
        owner,facts,calls,binding=self.fixture(False)
        facts["health"]=False;queue=[];gate=MeshControlGate(threading.Lock(),binding.capture,binding.perform,queue.append)
        command={"id":str(uuid.uuid4()),"action":"load","expected":gate.status()["expected"]}
        gate.submit(command);queue.pop()();self.assertEqual(gate.receipt(command["id"])["state"],"UNKNOWN")
        self.assertEqual(gate.submit(command)["state"],"UNKNOWN");self.assertEqual(len(calls),1)
        before=binding.capture();facts["created"]+=1
        with self.assertRaises(ControlRefused):binding.perform("unload",before)
        self.assertEqual(len(calls),1)

    def test_changed_binary_cannot_launch_even_from_an_empty_lane(self):
        owner,facts,calls,binding=self.fixture(False)
        facts["hash"]="b"*64
        self.assertEqual(binding.capture(),{"state":"uncertain"})
        with self.assertRaises(ControlRefused):binding.perform("load",{"state":"empty","identity":None,"clear":True})
        self.assertEqual(calls,[])

    def test_profile_constructor_refuses_other_model_engine_alias_or_network(self):
        owner,facts,calls,binding=self.fixture()
        for before,after in [(str(binding.EXECUTABLE),"C:/other.exe"),(str(binding.MODEL_FILE),"D:/other.gguf"),
                             (MODEL,"other-model"),("127.0.0.1","0.0.0.0"),("8199","8094")]:
            args=[after if arg==before else arg for arg in binding.argv]
            with self.assertRaises(ValueError):NemotronSupervisorOwner(owner,args,"a"*64)
        self.assertEqual(calls,[])


class RouteTests(unittest.TestCase):
    def test_status_is_read_only_and_commands_require_json_exact_scope_and_current_owner(self):
        f=Fixture();routes=MeshSupervisorRoutes(f.gate)
        code,status=routes.handle(8099,"GET","/mesh/v1/status")
        self.assertEqual(code,200);self.assertEqual(status["modelId"],MODEL);self.assertEqual(f.calls,[])
        body=json.dumps({"id":str(uuid.uuid4()),"action":"unload","expected":status["expected"]}).encode()
        self.assertEqual(routes.handle(8099,"POST","/mesh/v1/commands",body)[0],415)
        code,accepted=routes.handle(8099,"POST","/mesh/v1/commands",body,"application/json")
        self.assertEqual(code,202);operation=accepted["receipt"]["id"]
        self.assertEqual(routes.handle(8099,"GET","/mesh/v1/receipts/"+operation)[1]["receipt"]["state"],"ACCEPTED")
        self.assertEqual(len(f.queue),1);f.queue.pop()()
        self.assertEqual(routes.handle(8099,"POST","/mesh/v1/commands",body,"application/json")[0],200)
        self.assertEqual(len(f.calls),1)

    def test_other_ports_legacy_routes_methods_and_malformed_commands_cannot_dispatch(self):
        f=Fixture();routes=MeshSupervisorRoutes(f.gate)
        self.assertIsNone(routes.handle(8099,"POST","/admin/unload"))
        self.assertEqual(routes.handle(18090,"GET","/mesh/v1/status")[0],404)
        self.assertEqual(routes.handle(8099,"GET","/mesh/v1/commands")[0],405)
        for body,code in [(b"bad",400),(b"x"*4097,413),(b'{"action":"load","action":"unload"}',400),
                          (b'{"path":"D:/arbitrary","action":"load"}',400)]:
            self.assertEqual(routes.handle(8099,"POST","/mesh/v1/commands",body,"application/json")[0],code)
        self.assertEqual(f.calls,[]);self.assertEqual(f.queue,[])

    def test_busy_and_missing_receipts_fail_without_leaking_owner_exception(self):
        f=Fixture();routes=MeshSupervisorRoutes(f.gate)
        f.lock.acquire()
        try:self.assertEqual(routes.handle(8099,"GET","/mesh/v1/status")[0],409)
        finally:f.lock.release()
        self.assertEqual(routes.handle(8099,"GET","/mesh/v1/receipts/"+str(uuid.uuid4()))[0],404)
        f.gate._capture=lambda:(_ for _ in ()).throw(RuntimeError("private local path"))
        code,body=routes.handle(8099,"GET","/mesh/v1/status")
        self.assertEqual(code,503);self.assertNotIn("private",json.dumps(body))
        self.assertEqual(body["bootId"],f.gate.boot_id);self.assertEqual(body["schemaVersion"],routes.SCHEMA)


if __name__ == "__main__":
    unittest.main()
