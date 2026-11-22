"""Synthetic one-shot setup/recovery with real private storage and DPAPI."""
import json
import sys
import unittest
from unittest.mock import patch

import test_checkpointed_ledger_candidate as fixtures
import provision_project_sync_candidate as provision
from native_project_sync_candidate import load_project_credential, NativeProjectSyncHost, ProjectCredentialError
from project_events_candidate import ProjectEventsCandidate, EventBinding, EventError
from checkpoint_candidate import publish_snapshot_candidate
from checkpointed_ledger_candidate import restore_checkpointed_candidate
from onoes_mind.recall_binding import prepare_mesh_principal, issue_mesh_recall_credential
from test_project_events_candidate import event


@unittest.skipUnless(sys.platform == 'win32', 'Windows private custody')
class ProjectProvisionTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.CheckpointedLedgerTests(); self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.ledger = self.fixture.ledger
        prepare_mesh_principal(self.ledger, scope_id='project/onoes-mind/shared')
        issue_mesh_recall_credential(self.ledger)
        self.reader_before = self.reader_state(self.ledger)
        self.events = self.bind(self.ledger)
        self.credential = self.fixture.root/'project-service.json'
        self.outcome = self.fixture.root/'project-setup-outcome.json'
        self.projects = (('project-A','Synthetic project'),)

    def bind(self, ledger):
        stat = ledger.path.stat()
        return ProjectEventsCandidate(ledger, EventBinding(str(ledger.path.resolve()),stat.st_dev,
            stat.st_ino,self.fixture.store_id,self.fixture.environment,'fixture:source'))

    def reader_state(self, ledger):
        return ([tuple(r) for r in ledger.db.execute("SELECT kind,credential_epoch FROM principals WHERE principal_id='mesh-recall'")],
                [tuple(r) for r in ledger.db.execute("SELECT * FROM recall_service_credentials WHERE principal_id='mesh-recall'")],
                [tuple(r) for r in ledger.db.execute("SELECT * FROM scope_grants WHERE principal_id='mesh-recall'")])

    def prepare(self, **overrides):
        options = dict(mode='first_setup',projects=self.projects,credential_path=self.credential,
            outcome_path=self.outcome,operation_id='fixture-setup',review_ref='fixture:setup')
        return provision.prepare_project_service(self.events, **{**options,**overrides})

    def load(self, path=None, events=None, review='fixture:setup'):
        return load_project_credential(path or self.credential,events=events or self.events,
            project_ids=('project-A',),review_ref=review)

    def addition(self, name='add', **changes):
        root = self.fixture.root
        options = dict(mode='add_project', projects=self.projects + (('project-B', 'Second design'),),
                       added_project_id='project-B', credential_path=root/(name+'-key.json'),
                       outcome_path=root/(name+'-outcome.json'), operation_id=name, review_ref='fixture:add')
        return self.prepare(**{**options, **changes})

    def test_add_one_project_preserves_history_and_reader_and_rotates_the_original_token(self):
        self.prepare()
        original = self.load()
        first = self.events.submit(original, event())
        result = self.addition()
        self.assertEqual(result['status'], 'project_added_inactive')
        self.assertEqual(result['addedProjectId'], 'project-B')
        self.assertFalse(result['serviceStarted'])
        fresh = load_project_credential(self.fixture.root/'add-key.json', events=self.events,
                                        project_ids=('project-A','project-B'), review_ref='fixture:add')
        self.assertEqual(self.events.submit(fresh, event())['receiptId'], first['receiptId'])
        self.assertTrue(self.events.submit(fresh, event(projectId='project-B', cardId='card-B',
                                                      eventId='new-design'))['receiptId'])
        for project in ('project-A','project-B'):
            with self.assertRaises(EventError):
                self.events.lookup(original, project_id=project, event_id='event-1')
        with self.assertRaises(EventError):
            self.events.submit(fresh, event(projectId='project-C', cardId='card-C', eventId='third-design'))
        with self.assertRaises(provision.ProjectProvisionError):
            self.addition('duplicate', operation_id='add')
        self.assertEqual(self.reader_state(self.ledger), self.reader_before)

    def test_staging_failure_and_invalid_scope_leave_original_authority_intact(self):
        self.prepare()
        original = self.load()
        with patch.object(provision, '_stage_project_credential', side_effect=OSError('storage fault')):
            with self.assertRaises(provision.ProjectProvisionError): self.addition()
        for name, changes in (
            ('rename', dict(projects=(('project-A','Renamed'),('project-B','Second design')))),
            ('multi', dict(projects=self.projects + (('project-B','Second design'),('project-C','Third')))),
            ('wrong-mode', dict(mode='replace', added_project_id=None))):
            with self.subTest(name=name), self.assertRaises(provision.ProjectProvisionError):
                self.addition(name, **changes)
        self.assertEqual(self.load(), original)
        self.assertEqual([r[0] for r in self.events.db.execute('SELECT project_id FROM project_sync_projects')],
                         ['project-A'])
        self.events.register_project('project-B', 'Existing registration')
        with self.assertRaises(provision.ProjectProvisionError): self.addition('existing')
        self.events.db.execute("UPDATE project_sync_projects SET deleted=1 WHERE project_id='project-B'")
        with self.assertRaises(provision.ProjectProvisionError): self.addition('deleted')
        self.prepare(mode='revoke', credential_path=None, outcome_path=self.fixture.root/'revoked.json',
                     operation_id='revoke')
        with self.assertRaises(provision.ProjectProvisionError):
            self.addition('revoked', projects=self.projects + (('project-C','Third'),), added_project_id='project-C')

    def test_database_failure_after_private_file_readback_restores_original_grants_and_epoch(self):
        self.prepare()
        original = self.load()
        original_audit = self.ledger._audit
        def fail_rotation_audit(action, *args):
            if action == 'project_service_credential_replaced':
                raise OSError('fixture failure before commit')
            return original_audit(action, *args)
        with patch.object(self.ledger, '_audit', side_effect=fail_rotation_audit):
            with self.assertRaises(provision.ProjectProvisionError): self.addition()
        staged = self.fixture.root/'add-key.json'
        self.assertTrue(staged.is_file())
        with self.assertRaises(ProjectCredentialError):
            load_project_credential(staged, events=self.events, project_ids=('project-A','project-B'),
                                    review_ref='fixture:add')
        self.assertEqual(self.load(), original)
        self.assertEqual([r[0] for r in self.events.db.execute('SELECT project_id FROM project_sync_projects')],
                         ['project-A'])
        self.assertEqual(json.loads((self.fixture.root/'add-outcome.json').read_text())['status'], 'outcome_unknown')

    def test_first_setup_is_nonsecret_inactive_purpose_only_and_preserves_reader(self):
        result = self.prepare(); token = self.load()
        self.assertEqual(result['status'],'provisioned_inactive')
        self.assertFalse(result['serviceStarted']); self.assertFalse(result['runtimeEnrollment'])
        self.assertNotIn(token,json.dumps(result)); self.assertNotIn(token,self.outcome.read_text())
        self.assertNotIn(token.encode(),self.credential.read_bytes())
        self.assertEqual(self.reader_state(self.ledger),self.reader_before)
        self.assertEqual(self.ledger.db.execute('SELECT count(*) FROM memory_records').fetchone()[0],1)
        self.assertEqual(self.ledger.db.execute("SELECT state FROM project_sync_admin_operations").fetchone()[0],'complete')
        self.assertEqual(self.ledger.db.execute("SELECT count(*) FROM credentials WHERE principal_id='mesh-project-sync'").fetchone()[0],0)
        self.assertEqual(self.ledger.db.execute("SELECT count(*) FROM scope_grants WHERE principal_id='mesh-project-sync'").fetchone()[0],0)
        self.assertEqual(self.events.submit(token,event())['principal'],'mesh-project-sync')

    def test_existing_file_or_unresolved_authority_refuses_before_schema_or_grant(self):
        self.outcome.write_bytes(b'preserve existing owner outcome')
        with self.assertRaises(provision.ProjectProvisionError): self.prepare()
        self.assertEqual(self.outcome.read_bytes(),b'preserve existing owner outcome')
        self.assertFalse(self.ledger.db.execute("SELECT 1 FROM sqlite_schema WHERE name='project_sync_format'").fetchone())
        with self.fixture.authority.hold(self.fixture.store_id,self.fixture.environment) as lease: head=lease.current()
        self.fixture.authority.begin_purge('fixture-pending','a'*64,head)
        with self.assertRaises(provision.ProjectProvisionError):
            self.prepare(outcome_path=self.fixture.root/'never-created.json')
        self.assertFalse((self.fixture.root/'never-created.json').exists())
        self.assertFalse(self.ledger.db.execute("SELECT 1 FROM principals WHERE principal_id='mesh-project-sync'").fetchone())

    def test_partial_setup_preserves_unknown_operation_and_cannot_repeat_with_new_files(self):
        with patch.object(provision,'seal_project_credential',side_effect=OSError('synthetic storage fault')):
            with self.assertRaises(provision.ProjectProvisionError): self.prepare()
        receipt=json.loads(self.outcome.read_text()); self.assertEqual(receipt['status'],'outcome_unknown')
        self.assertEqual(self.ledger.db.execute('SELECT state FROM project_sync_admin_operations').fetchone()[0],'unknown')
        with self.assertRaises(provision.ProjectProvisionError):
            self.prepare(credential_path=self.fixture.root/'retry-key.json',outcome_path=self.fixture.root/'retry-outcome.json')
        self.assertFalse((self.fixture.root/'retry-outcome.json').exists())
        self.assertEqual(self.ledger.db.execute('SELECT count(*) FROM project_sync_credentials').fetchone()[0],1)

    def test_reviewed_replacement_rejects_old_token_keeps_receipts_and_cannot_reuse_operation_id(self):
        self.prepare(); old_token=self.load(); receipt=self.events.submit(old_token,event())
        with self.ledger._transaction(immediate=True): self.ledger.rotate_credentials('mesh-project-sync')
        credential=self.fixture.root/'replacement.json'; outcome=self.fixture.root/'replacement-outcome.json'
        result=self.prepare(mode='replace',credential_path=credential,outcome_path=outcome,
            operation_id='fixture-replace',review_ref='fixture:replace')
        new_token=self.load(credential,review='fixture:replace')
        self.assertNotEqual(new_token,old_token); self.assertEqual(result['status'],'replaced_inactive')
        with self.assertRaises(EventError): self.events.lookup(old_token,project_id='project-A',event_id='event-1')
        self.assertEqual(self.events.lookup(new_token,project_id='project-A',event_id='event-1'),receipt)
        self.assertEqual(self.reader_state(self.ledger),self.reader_before)
        epoch=self.ledger.db.execute("SELECT credential_epoch FROM principals WHERE principal_id='mesh-project-sync'").fetchone()[0]
        with self.assertRaises(provision.ProjectProvisionError):
            self.prepare(mode='replace',credential_path=self.fixture.root/'repeat.json',outcome_path=self.fixture.root/'repeat-outcome.json',
                operation_id='fixture-replace',review_ref='fixture:replace')
        self.assertEqual(self.ledger.db.execute("SELECT credential_epoch FROM principals WHERE principal_id='mesh-project-sync'").fetchone()[0],epoch)

    def test_restored_store_requires_fresh_binding_and_token_without_resurrecting_deleted_fact(self):
        self.prepare(); old_token=self.load(); receipt=self.events.submit(old_token,event())
        snapshot=self.fixture.root/'service-snapshot.sqlite'
        publish_snapshot_candidate(self.ledger,snapshot,self.fixture.authority,store_id=self.fixture.store_id,environment=self.fixture.environment)
        record=self.ledger.db.execute('SELECT record_id FROM project_sync_events').fetchone()[0]
        self.ledger.purge(self.fixture.token,record,'PURGE:'+record,operation_id='fixture-later-delete')
        self.ledger.close()
        restored=restore_checkpointed_candidate(snapshot,self.fixture.root/'recovered.sqlite',None,self.fixture.authority,
            **self.fixture.keys,store_id=self.fixture.store_id,environment=self.fixture.environment,review_ref='fixture:restore')
        self.addCleanup(restored.close); events=self.bind(restored)
        with self.assertRaises(ProjectCredentialError): self.load(events=events)
        credential=self.fixture.root/'restored-service.json'
        result=provision.prepare_project_service(events,mode='replace',projects=self.projects,
            credential_path=credential,outcome_path=self.fixture.root/'restored-operation.json',
            operation_id='fixture-restored-replace',review_ref='fixture:restored-review')
        token=self.load(credential,events=events,review='fixture:restored-review')
        self.assertNotEqual(token,old_token); self.assertFalse(result['previousRuntimeRetirementQualified'])
        with self.assertRaises(EventError): events.lookup(old_token,project_id='project-A',event_id='event-1')
        readback=events.lookup(token,project_id='project-A',event_id='event-1')
        self.assertEqual(readback['receiptId'],receipt['receiptId']); self.assertEqual(readback['recordState'],'purged')
        with self.assertRaises(EventError): events.submit(token,event(2))
        self.assertEqual(self.reader_state(restored),self.reader_before)

    def test_active_service_blocks_replacement_and_failed_seal_consumes_operation(self):
        self.prepare(); old_token=self.load()
        host=NativeProjectSyncHost(binding=self.events.binding,history_path=self.fixture.history,authority=self.fixture.authority,
            **self.fixture.keys,credential_path=self.credential,project_ids=('project-A',),review_ref='fixture:setup')
        self.addCleanup(host.close); host.start()
        with self.assertRaises(provision.ProjectProvisionError):
            self.prepare(mode='replace',credential_path=self.fixture.root/'blocked.json',outcome_path=self.fixture.root/'blocked-outcome.json',
                operation_id='fixture-blocked',review_ref='fixture:blocked')
        self.assertFalse((self.fixture.root/'blocked-outcome.json').exists()); host.close()
        with patch.object(provision,'seal_project_credential',side_effect=OSError('synthetic storage fault')):
            with self.assertRaises(provision.ProjectProvisionError):
                self.prepare(mode='replace',credential_path=self.fixture.root/'failed-replace.json',outcome_path=self.fixture.root/'failed-replace-outcome.json',
                    operation_id='fixture-consumed',review_ref='fixture:replacement')
        with self.assertRaises(EventError): self.events.replace_credential(('project-A',),'fixture-consumed')
        with self.assertRaises(EventError): self.events.lookup(old_token,project_id='project-A',event_id='event-1')

    def test_reviewed_revocation_invalidates_service_preserves_reader_facts_and_credential_file(self):
        self.prepare(); token=self.load(); receipt=self.events.submit(token,event())
        original=self.credential.read_bytes()
        outcome=self.fixture.root/'revocation-outcome.json'
        result=provision.revoke_project_service(self.events,projects=self.projects,outcome_path=outcome,
            operation_id='fixture-revoke',review_ref='fixture:revoke')
        self.assertEqual(result['status'],'revoked_inactive'); self.assertFalse(result['credentialIssued'])
        self.assertEqual(result['epochAfter'],result['epochBefore']+1)
        self.assertEqual(self.credential.read_bytes(),original)
        self.assertEqual(self.reader_state(self.ledger),self.reader_before)
        with self.assertRaises(EventError): self.events.lookup(token,project_id='project-A',event_id='event-1')
        with self.assertRaises(ProjectCredentialError): self.load()
        self.assertEqual(self.ledger.db.execute('SELECT receipt_id FROM project_sync_events').fetchone()[0],receipt['receiptId'])
        self.assertEqual(self.ledger.db.execute("SELECT count(*) FROM memory_records WHERE state='active'").fetchone()[0],2)
        with self.assertRaises(provision.ProjectProvisionError):
            provision.revoke_project_service(self.events,projects=self.projects,outcome_path=self.fixture.root/'repeated-revoke.json',
                operation_id='fixture-revoke',review_ref='fixture:revoke')
        self.assertEqual(self.ledger.db.execute("SELECT credential_epoch FROM principals WHERE principal_id='mesh-project-sync'").fetchone()[0],result['epochAfter'])

    def test_failure_after_revocation_keeps_consumed_unknown_operation_without_reissue(self):
        self.prepare(); token=self.load(); original_audit=self.ledger._audit
        def fail_completion(action,*args):
            if action=='project_service_revoked': raise OSError('synthetic completion fault')
            return original_audit(action,*args)
        outcome=self.fixture.root/'uncertain-revoke.json'
        with patch.object(self.ledger,'_audit',side_effect=fail_completion):
            with self.assertRaises(provision.ProjectProvisionError):
                provision.revoke_project_service(self.events,projects=self.projects,outcome_path=outcome,
                    operation_id='fixture-uncertain-revoke',review_ref='fixture:revoke')
        self.assertEqual(json.loads(outcome.read_text())['status'],'outcome_unknown')
        self.assertEqual(self.ledger.db.execute("SELECT state FROM project_sync_admin_operations WHERE operation_id='fixture-uncertain-revoke'").fetchone()[0],'unknown')
        with self.assertRaises(EventError): self.events.lookup(token,project_id='project-A',event_id='event-1')
