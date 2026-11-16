"""Real Windows DPAPI and protected canonical synthetic ledgers only."""
from dataclasses import replace, asdict
import http.client
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

import test_checkpointed_ledger_candidate as fixtures
from project_events_candidate import ProjectEventsCandidate, EventBinding
import native_project_sync_candidate as native
from test_project_events_candidate import event
from onoes_mind.ledger import LedgerError
from onoes_mind.recall_binding import prepare_mesh_principal, issue_mesh_recall_credential


@unittest.skipUnless(sys.platform == 'win32', 'Windows current-user DPAPI')
class ProjectCredentialTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.CheckpointedLedgerTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.ledger = self.fixture.ledger
        self.events = self.bind(self.ledger)
        self.events.initialize()
        self.events.register_project('project-A', 'Synthetic project')
        self.token = self.events.enroll(['project-A'])
        self.path = self.fixture.root / 'project-credential.json'
        self.options = dict(events=self.events, project_ids=('project-A',), review_ref='fixture:project-review')

    def bind(self, ledger):
        stat = ledger.path.stat()
        return ProjectEventsCandidate(ledger, EventBinding(str(ledger.path.resolve()), stat.st_dev,
            stat.st_ino, self.fixture.store_id, self.fixture.environment, 'fixture:source'))

    def seal(self):
        return native.seal_project_credential(self.path, self.token, **self.options)

    def test_actual_dpapi_and_protected_reopen_preserve_purpose_credential_without_plaintext(self):
        result = self.seal()
        self.assertTrue(result['protected'])
        self.assertNotIn(self.token.encode(), self.path.read_bytes())
        self.assertNotIn(self.token, json.dumps(result))
        self.ledger.close()
        reopened = self.fixture.open_host()
        self.addCleanup(reopened.close)
        events = self.bind(reopened)
        token = native.load_project_credential(self.path, **{**self.options, 'events':events})
        receipt = events.submit(token, event())
        self.assertTrue(receipt['durable'])
        self.assertEqual(receipt['principal'], 'mesh-project-sync')
        with self.assertRaises(LedgerError): reopened.authenticate(token)

    def test_revoked_epoch_and_removed_grant_refuse_load_without_reissuing(self):
        self.seal(); original = self.path.read_bytes()
        with self.ledger._transaction(immediate=True):
            self.ledger.rotate_credentials('mesh-project-sync')
        with self.assertRaises(native.ProjectCredentialError):
            native.load_project_credential(self.path, **self.options)
        self.assertEqual(self.path.read_bytes(), original)
        self.assertEqual(self.ledger.db.execute('SELECT count(*) FROM project_sync_credentials').fetchone()[0], 1)

    def test_project_grant_withdrawal_and_broadening_are_refused(self):
        self.seal()
        self.events.register_project('project-B', 'Another synthetic project')
        self.ledger.db.execute("INSERT INTO project_sync_grants VALUES('mesh-project-sync','project-B',1)")
        with self.assertRaises(native.ProjectCredentialError):
            native.load_project_credential(self.path, **self.options)
        self.ledger.db.execute("UPDATE project_sync_grants SET active=0")
        with self.assertRaises(native.ProjectCredentialError):
            native.load_project_credential(self.path, **self.options)

    def test_review_and_projects_and_store_binding_cannot_be_substituted(self):
        self.seal(); original = self.path.read_bytes()
        for change in ({'review_ref':'fixture:other'}, {'project_ids':('project-B',)}, {'project_ids':[]}):
            with self.assertRaises(native.ProjectCredentialError):
                native.load_project_credential(self.path, **{**self.options, **change})
        prior = self.events.binding
        self.events.binding = replace(prior, environment='wrong-environment')
        try:
            with self.assertRaises(native.ProjectCredentialError):
                native.load_project_credential(self.path, **self.options)
        finally:
            self.events.binding = prior
        self.assertEqual(self.path.read_bytes(), original)

    def test_plain_operator_token_and_existing_or_weak_destination_are_refused(self):
        with self.assertRaises(native.ProjectCredentialError):
            native.seal_project_credential(self.path, self.fixture.token, **self.options)
        self.assertFalse(self.path.exists())
        prepare_mesh_principal(self.ledger, scope_id=native.SCOPE)
        read_token = issue_mesh_recall_credential(self.ledger)
        with self.assertRaises(native.ProjectCredentialError):
            native.seal_project_credential(self.path, read_token, **self.options)
        self.assertFalse(self.path.exists())
        self.path.write_bytes(b'preserve existing file')
        with patch.object(native, '_crypt') as crypt:
            with self.assertRaises(native.ProjectCredentialError): self.seal()
            crypt.assert_not_called()
        self.assertEqual(self.path.read_bytes(), b'preserve existing file')
        weak = self.fixture.root.parent / 'weak-folder'; weak.mkdir()
        with patch.object(native, '_crypt') as crypt:
            with self.assertRaises(native.ProjectCredentialError):
                native.seal_project_credential(weak/'refused.json', self.token, **self.options)
            crypt.assert_not_called()
        self.assertEqual(list(weak.iterdir()), [])

    def test_tamper_duplicate_keys_and_recall_purpose_are_refused_without_secret_echo(self):
        self.seal(); original = self.path.read_bytes()
        envelope = json.loads(original)
        for changed in ({**envelope, 'schema':'onoes-mind-mesh-recall-credential/v1'},
                        {**envelope, 'ciphertext':'AAAA'}):
            self.path.write_text(json.dumps(changed), encoding='utf-8')
            with self.assertRaises(native.ProjectCredentialError) as failed:
                native.load_project_credential(self.path, **self.options)
            self.assertNotIn(self.token, str(failed.exception))
        self.path.write_text(original.decode().replace('"ciphertext":', '"ciphertext":"AAAA", "ciphertext":'), encoding='utf-8')
        with patch.object(native, '_crypt') as crypt:
            with self.assertRaises(native.ProjectCredentialError):
                native.load_project_credential(self.path, **self.options)
            crypt.assert_not_called()

    def test_unresolved_deletion_authority_blocks_credential_export(self):
        self.seal()
        with self.fixture.authority.hold(self.fixture.store_id, self.fixture.environment) as lease:
            head = lease.current()
        self.fixture.authority.begin_purge('synthetic-pending', 'a'*64, head)
        with self.assertRaises(native.ProjectCredentialError):
            native.load_project_credential(self.path, **self.options)


@unittest.skipUnless(sys.platform == 'win32', 'Windows lifetime lock')
class ProjectHostTests(unittest.TestCase):
    setUp = ProjectCredentialTests.setUp
    bind = ProjectCredentialTests.bind
    seal = ProjectCredentialTests.seal

    def host(self):
        return native.NativeProjectSyncHost(binding=self.events.binding,
            history_path=self.fixture.history, authority=self.fixture.authority,
            **self.fixture.keys, credential_path=self.path, project_ids=self.options['project_ids'],
            review_ref=self.options['review_ref'])

    def test_owned_service_serves_receipts_refuses_second_owner_and_reopens_after_close(self):
        self.seal(); self.ledger.close()
        host = self.host(); self.addCleanup(host.close)
        self.assertEqual(host.start(), {'ready':True})
        other = self.host(); self.addCleanup(other.close)
        with self.assertRaises(native.ProjectCredentialError): other.start()
        options = host.native_options()
        port = int(options['baseUrl'].split(':')[-1].strip('/'))
        connection = http.client.HTTPConnection('127.0.0.1', port, timeout=4)
        try:
            connection.request('POST', '/v1/project-events/submit', body=json.dumps(event()),
                headers={'Authorization':'Bearer '+options['token'], 'Content-Type':'application/json'})
            response = connection.getresponse()
            self.assertEqual(response.status, 200)
            receipt = json.loads(response.read())
            self.assertEqual(receipt['eventId'], 'event-1')
            self.assertTrue(receipt['durable'])
        finally: connection.close()
        host.close(); self.assertEqual(host.status(), {'ready':False})
        with self.assertRaises(native.ProjectCredentialError): host.start()
        fresh = self.host(); self.addCleanup(fresh.close)
        self.assertEqual(fresh.start(), {'ready':True})
        self.assertEqual(fresh.events.lookup(fresh.native_options()['token'], project_id='project-A',
                                          event_id='event-1')['receiptId'], receipt['receiptId'])
        # Cached native credentials cannot expand the running host's fixed route
        # even if an operator later adds a grant in the canonical database.
        fresh.events.register_project('project-B', 'Another synthetic project')
        fresh.ledger.db.execute("INSERT INTO project_sync_grants VALUES('mesh-project-sync','project-B',1)")
        port = int(fresh.server.address[1])
        connection = http.client.HTTPConnection('127.0.0.1', port, timeout=4)
        try:
            connection.request('POST', '/v1/project-events/submit', body=json.dumps(event(projectId='project-B',cardId='other-card')),
                headers={'Authorization':'Bearer '+options['token'], 'Content-Type':'application/json'})
            response = connection.getresponse()
            self.assertEqual(response.status, 403)
            response.read()
        finally: connection.close()
        self.assertEqual(fresh.ledger.db.execute('SELECT count(*) FROM project_sync_events').fetchone()[0], 1)

    def test_invalid_credential_never_starts_listener_and_preserves_lock_file(self):
        self.ledger.close()
        host = self.host(); self.addCleanup(host.close)
        with patch.object(native, 'ProjectEventsServerCandidate') as server:
            with self.assertRaises(native.ProjectCredentialError): host.start()
            server.assert_not_called()
        path = self.fixture.root / '.project-sync-service.lock'
        self.assertEqual(path.read_bytes(), native.ProjectServiceLease.HEADER)
        lease = native.ProjectServiceLease(self.events.binding)
        lease.close()

    def test_owned_process_exit_releases_kernel_lock_without_deleting_lock_file(self):
        code = '''
import json, os, sys
sys.path.insert(0, sys.argv[1])
from native_project_sync_candidate import ProjectServiceLease
from project_events_candidate import EventBinding
lease = ProjectServiceLease(EventBinding(**json.loads(sys.stdin.readline())))
print('LOCKED', flush=True)
if sys.stdin.readline().strip() == 'EXIT': os._exit(73)
lease.close()
'''
        child = subprocess.Popen([sys.executable, '-B', '-c', code, str(Path(__file__).resolve().parent)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            child.stdin.write(json.dumps(asdict(self.events.binding))+'\n'); child.stdin.flush()
            self.assertEqual(child.stdout.readline().strip(), 'LOCKED')
            with self.assertRaises(native.ProjectCredentialError): native.ProjectServiceLease(self.events.binding)
            child.stdin.write('EXIT\n'); child.stdin.flush()
            self.assertEqual(child.wait(timeout=10), 73)
            path = self.fixture.root / '.project-sync-service.lock'
            before = path.stat()
            lease = native.ProjectServiceLease(self.events.binding)
            lease.close()
            after = path.stat()
            self.assertEqual((before.st_dev,before.st_ino), (after.st_dev,after.st_ino))
        finally:
            if child.poll() is None:
                child.kill(); child.wait(timeout=10)
            child.stdin.close(); child.stdout.close(); child.stderr.close()


@unittest.skipUnless(sys.platform == 'win32', 'Windows client custody')
class ClientCredentialTests(unittest.TestCase):
    setUp = ProjectCredentialTests.setUp
    bind = ProjectCredentialTests.bind
    seal = ProjectCredentialTests.seal

    def client(self):
        return native.load_project_client_credential(self.path,binding=self.events.binding,
            project_ids=('project-A',),review_ref=self.options['review_ref'])

    def test_same_envelope_reloads_with_readonly_metadata_without_writer_or_fact_reads(self):
        self.seal(); original=self.path.read_bytes(); before=self.ledger.path.read_bytes()
        expected=json.dumps(dict(purpose='onoes-mind-project-sync-credential/v1',principal='mesh-project-sync',
            scope='project/onoes-mind/shared',binding=asdict(self.events.binding),projects=('project-A',),
            reviewRef=self.options['review_ref']),sort_keys=True,separators=(',',':')).encode('utf-8')
        self.assertEqual(json.loads(original)['bindingSha256'],hashlib.sha256(expected).hexdigest())
        queries=[];connections=[];connect=native.sqlite3.connect
        def readonly(*args,**kwargs):
            self.assertTrue(kwargs['uri']);self.assertTrue(args[0].endswith('?mode=ro'))
            db=connect(*args,**kwargs);db.set_trace_callback(queries.append);connections.append(db);return db
        with patch.object(native.sqlite3,'connect',side_effect=readonly),\
             patch.object(native,'CheckpointedLedgerCandidate',side_effect=AssertionError('No writer may open')):
            self.assertEqual(self.client(),self.token)
        self.assertEqual(len(connections),1)
        self.assertFalse(any('memory_records' in q or 'memory_revisions' in q or 'provenance_refs' in q for q in queries))
        self.assertFalse(any(q.startswith(('INSERT','UPDATE','DELETE','CREATE')) for q in queries))
        self.assertEqual(self.path.read_bytes(),original);self.assertEqual(self.ledger.path.read_bytes(),before)

    def test_revoked_and_broadened_grants_are_refused_without_changing_custody(self):
        self.seal();original=self.path.read_bytes()
        self.events.register_project('project-B','Another synthetic project')
        self.ledger.db.execute("INSERT INTO project_sync_grants VALUES('mesh-project-sync','project-B',1)")
        with self.assertRaises(native.ProjectCredentialError):self.client()
        self.ledger.db.execute("UPDATE project_sync_grants SET active=0 WHERE project_id='project-B'")
        with self.ledger._transaction(immediate=True):self.ledger.rotate_credentials('mesh-project-sync')
        with self.assertRaises(native.ProjectCredentialError):self.client()
        self.assertEqual(self.path.read_bytes(),original)

    def test_client_export_is_not_deletion_authority_and_receiver_stays_blocked(self):
        self.seal()
        with self.fixture.authority.hold(self.fixture.store_id,self.fixture.environment) as lease:head=lease.current()
        self.fixture.authority.begin_purge('fixture-pending','a'*64,head)
        token=self.client()
        from project_events_candidate import EventError
        with self.assertRaises(EventError):self.events.submit(token,event())
        self.assertEqual(self.ledger.db.execute('SELECT count(*) FROM project_sync_events').fetchone()[0],0)
