"""Private homes attached to the existing protected writer, disposable data only."""
from dataclasses import replace
import http.client
import json
import os
from pathlib import Path
import sys
import threading
import unittest
from unittest.mock import patch

MIND = Path(os.environ["MIND_SOURCE"]).resolve()
sys.path.insert(0,str(MIND))
import onoes_mind
from onoes_mind.agent_home import AgentHomeBinding, enroll_agent_home
from onoes_mind.agent_home_http import AgentHomeClient, AgentHomeServer, AgentHomeTransportError
from onoes_mind.recall_binding import RecallBinding
assert Path(onoes_mind.__file__).resolve().parents[1] == MIND
sys.path.insert(0,str(Path(__file__).resolve().parent.parent/"mind-recovery-candidate"))
import test_native_project_sync_candidate as fixtures
from test_project_events_candidate import event
import native_project_sync_candidate as native


class SharedWriterHomeTests(unittest.TestCase):
    def setUp(self):
        self.base=fixtures.ProjectCredentialTests();self.base.setUp()
        self.addCleanup(self.base.doCleanups)
        b=self.base.events.binding
        store=RecallBinding(b.database_path,b.store_id,b.environment,"fixture:source",
            "project/onoes-mind/shared",b.file_device,b.file_inode,
            "fixture:custodian","fixture:revoke","fixture:review")
        self.home_binding=AgentHomeBinding(store,"nims")
        tokens=[]
        enroll_agent_home(self.base.ledger,self.home_binding,operator_token=self.base.fixture.token,
            save_new_token=lambda token:tokens.append(token) is None)
        self.token=tokens[0]
        self.base.seal();self.original_credential=self.base.path.read_bytes()
        self.base.ledger.close()

    def host(self,bindings=None):
        host=native.NativeProjectSyncHost(binding=self.base.events.binding,
            history_path=self.base.fixture.history,authority=self.base.fixture.authority,
            **self.base.fixture.keys,credential_path=self.base.path,
            project_ids=self.base.options["project_ids"],review_ref=self.base.options["review_ref"],
            agent_home_bindings=(self.home_binding,) if bindings is None else bindings)
        self.addCleanup(host.close)
        return host

    def client(self,host):
        options=host.agent_home_options()
        return AgentHomeClient(options["baseUrl"],agent_id="nims",
            binding_sha256=options["agents"]["nims"],credential_provider=lambda:self.token,timeout=10)

    @staticmethod
    def project_call(options,body,path="submit"):
        from urllib.parse import urlsplit
        url=urlsplit(options["baseUrl"])
        connection=http.client.HTTPConnection(url.hostname,url.port,timeout=10)
        try:
            connection.request("POST","/v1/project-events/"+path,json.dumps(body),
                {"Authorization":"Bearer "+options["token"],"Content-Type":"application/json"})
            response=connection.getresponse()
            return response.status,json.loads(response.read())
        finally:connection.close()

    def test_two_interfaces_share_writer_lock_and_survive_reopen(self):
        host=self.host();self.assertEqual(host.start(),{"ready":True})
        self.assertIs(host.server.writer_lock,host.writer_lock)
        self.assertIs(host.home_server._lock,host.writer_lock)
        self.assertIs(host.home_server.homes["nims"].ledger,host.ledger)
        other=self.host()
        with self.assertRaises(native.ProjectCredentialError):other.start()
        client=self.client(host);options=host.native_options()
        entered,release,project_entered=threading.Event(),threading.Event(),threading.Event()
        home=host.home_server.homes["nims"];remember=home.remember;submit=host.events.submit
        results={};errors=[]
        def hold_home(*args,**kwargs):
            entered.set()
            if not release.wait(10):raise RuntimeError("test release did not arrive")
            return remember(*args,**kwargs)
        def see_project(*args,**kwargs):
            project_entered.set();return submit(*args,**kwargs)
        def run(name,callback):
            try:results[name]=callback()
            except Exception as error:errors.append(error)
        with patch.object(home,"remember",hold_home),patch.object(host.events,"submit",see_project):
            first=threading.Thread(target=run,args=("home",lambda:client.call("remember",
                {"event_id":"shared-writer-home","text":"Lighthouse private selected fact"})))
            second=threading.Thread(target=run,args=("project",lambda:self.project_call(options,event())))
            first.start()
            try:
                self.assertTrue(entered.wait(10));second.start()
                self.assertFalse(project_entered.wait(.2))
            finally:release.set();first.join(20)
            second.join(20)
        self.assertFalse(first.is_alive() or second.is_alive());self.assertEqual(errors,[])
        self.assertTrue(results["home"]["durable"])
        self.assertEqual(results["project"][0],200);self.assertTrue(results["project"][1]["durable"])
        self.assertTrue(project_entered.is_set())
        self.assertEqual(host.ledger.integrity_report()["status"],"PASS")
        host.close();self.assertEqual(host.status(),{"ready":False})
        reopened=self.host();self.assertEqual(reopened.start(),{"ready":True})
        row,=self.client(reopened).call("recall",{"query":"lighthouse"})["records"]
        self.assertEqual(row["record_id"],results["home"]["record_id"])
        lookup={"schema":"onoes-mind-project-lookup/v1","projectId":"project-A","eventId":"event-1"}
        status,receipt=self.project_call(reopened.native_options(),lookup,"lookup")
        self.assertEqual(status,200);self.assertEqual(receipt["receiptId"],results["project"][1]["receiptId"])
        self.assertEqual(self.base.path.read_bytes(),self.original_credential)

    def test_missing_or_wrong_store_home_never_enables_a_listener(self):
        wrong=replace(self.home_binding,store=replace(self.home_binding.store,store_id="00000000-0000-0000-0000-000000000000"))
        host=self.host((wrong,))
        with patch.object(native.ProjectEventsServerCandidate,"start") as start:
            with self.assertRaises(native.ProjectCredentialError):host.start()
            start.assert_not_called()
        self.assertIsNone(host.ledger);self.assertIsNone(host.lease);self.assertIsNone(host.home_server)
        self.assertEqual(self.base.path.read_bytes(),self.original_credential)
        healthy=self.host();self.assertEqual(healthy.start(),{"ready":True})

    def test_failed_home_listener_retires_both_before_releasing_lease(self):
        host=self.host()
        with patch.object(AgentHomeServer,"start",side_effect=OSError("synthetic listener failure")):
            with self.assertRaises(native.ProjectCredentialError):host.start()
        self.assertIsNone(host.home_server);self.assertIsNone(host.server)
        self.assertIsNone(host.ledger);self.assertIsNone(host.lease)
        healthy=self.host();self.assertEqual(healthy.start(),{"ready":True})

    def test_home_revocation_is_immediate_and_does_not_change_project_grants(self):
        host=self.host();host.start();client=self.client(host)
        self.assertTrue(client.call("remember",{"event_id":"revoked","text":"Private revocation fact"})["durable"])
        with host.writer_lock:
            with host.ledger._transaction(immediate=True):host.ledger.rotate_credentials("nims")
        with self.assertRaises(AgentHomeTransportError):client.call("recall",{"query":"revocation"})
        status,result=self.project_call(host.native_options(),event())
        self.assertEqual(status,200);self.assertTrue(result["durable"])
        self.assertTrue(host.status()["ready"])

    def test_managed_purge_and_authority_reopen_cover_home_records(self):
        host=self.host();host.start();client=self.client(host)
        created=client.call("remember",{"event_id":"purge-home","text":"Purgemarker private fact"})
        record_id=created["record_id"]
        with host.writer_lock:
            receipt=host.ledger.purge(self.base.fixture.token,record_id,"PURGE:"+record_id,operation_id="home-purge")
        self.assertTrue(receipt["checkpointAcknowledged"])
        self.assertEqual(client.call("recall",{"query":"purgemarker"})["records"],[])
        host.close();reopened=self.host();reopened.start()
        self.assertEqual(self.client(reopened).call("recall",{"query":"purgemarker"})["records"],[])
        self.assertEqual(reopened.ledger.integrity_report()["status"],"PASS")

    def test_default_host_keeps_private_home_interface_off(self):
        host=self.host(())
        self.assertEqual(host.start(),{"ready":True});self.assertIsNone(host.home_server)
        with self.assertRaises(native.ProjectCredentialError):host.agent_home_options()
        self.assertEqual(self.project_call(host.native_options(),event())[0],200)
