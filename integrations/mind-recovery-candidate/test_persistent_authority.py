"""Real private TEMP journals and owned crashing children; never a live Mind path."""
from dataclasses import asdict, replace
from pathlib import Path
import json
import hashlib
import secrets
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
import uuid

sys.path.insert(0, 'D:/Dev/Onoes-Mind')
from onoes_mind import Ledger
from onoes_mind.recall_binding import prepare_store_identity
from checkpoint_candidate import (CheckpointRecoveryError, Head, history_view,
    publish_snapshot_candidate, purge_checkpoint_candidate, restore_checkpoint_candidate)
from persistent_authority import PersistentAuthorityCandidate

PRIVATE_ACL = r'''param([string]$Path)
$ErrorActionPreference='Stop'
$acl=[Security.AccessControl.DirectorySecurity]::new()
$acl.SetAccessRuleProtection($true,$false)
$owner=[Security.Principal.WindowsIdentity]::GetCurrent().User
$acl.SetOwner($owner)
foreach($sid in @($owner.Value,'S-1-5-18','S-1-5-32-544')){
 $id=[Security.Principal.SecurityIdentifier]::new($sid)
 $rule=[Security.AccessControl.FileSystemAccessRule]::new($id,'FullControl','ContainerInherit,ObjectInherit','None','Allow')
 $acl.AddAccessRule($rule)
}
Set-Acl -LiteralPath $Path -AclObject $acl
'''

CRASH = r'''
import sys,json,os,sqlite3
from unittest.mock import patch
from onoes_mind import Ledger
from persistent_authority import PersistentAuthorityCandidate,AuthorityBinding
from checkpoint_candidate import purge_checkpoint_candidate
r=json.loads(sys.stdin.read())
keys={k:bytes.fromhex(v) for k,v in r['keys'].items()}
ledger=Ledger(r['source'],deletion_ledger_path=r['history'],environment_id=r['environment'],**keys)
authority=PersistentAuthorityCandidate(AuthorityBinding(**r['binding']))
original=authority.ack_purge
def acknowledge(*args):
 if r['phase']=='before_ack':os._exit(47)
 if r['phase']=='during_commit':
  connect=sqlite3.connect
  class InterruptedCommit:
   def __init__(self,db):self.db=db
   def __getattr__(self,name):return getattr(self.db,name)
   def commit(self):os._exit(47)
  with patch('persistent_authority.sqlite3.connect',side_effect=lambda *a,**kw:InterruptedCommit(connect(*a,**kw))):
   return original(*args)
 original(*args)
 os._exit(47)
authority.ack_purge=acknowledge
purge_checkpoint_candidate(ledger,r['token'],r['record'],'PURGE:'+r['record'],authority,
 operation_id='owned-crash-operation',store_id=r['store_id'],environment=r['environment'])
raise AssertionError('owned crash point not reached')
'''


@unittest.skipUnless(sys.platform == 'win32', 'Windows private-storage qualification')
class PersistentAuthorityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.private = self.root / 'synthetic-private-authority';self.private.mkdir()
        script = self.root / 'fixture-private-acl.ps1';script.write_text(PRIVATE_ACL)
        require_private = self.private.resolve().is_relative_to(self.root)
        self.assertTrue(require_private)
        subprocess.run([shutil.which('pwsh'),'-NoProfile','-NonInteractive','-File',str(script),
                        '-Path',str(self.private)],check=True,capture_output=True,
                       creationflags=subprocess.CREATE_NO_WINDOW)
        self.keys = dict(audit_key=secrets.token_bytes(32),deletion_key=secrets.token_bytes(32))
        self.environment = 'synthetic-persistent-checkpoint'
        self.history = self.root / 'synthetic-history.jsonl'
        self.source = self.root / 'synthetic-source.sqlite'
        self.ledger = Ledger(self.source,deletion_ledger_path=self.history,
                             environment_id=self.environment,**self.keys)
        self.store_id = prepare_store_identity(self.ledger,environment=self.environment,
                                               authority_ref='fixture:explicit-independent-source')
        self.authority = PersistentAuthorityCandidate.create(self.private,self.ledger,
            store_id=self.store_id,environment=self.environment,review_ref='fixture:source-selection')
        self.binding = self.authority.binding
        self.snapshot,self.target = self.root/'backup.sqlite',self.root/'restored.sqlite'
        self.ledger.create_principal('operator')
        self.token = self.ledger.issue_credential('operator','fixture-only-operator-token')
        self.record = self.ledger.remember(self.token,dict(event_id='fixture-record',claim='fixture banana',
            kind='project_fact',project_id='onoes-mind',requested_visibility='shared'))['record_id']

    def tearDown(self):
        self.ledger.close();self.temp.cleanup()

    def publish(self):
        return publish_snapshot_candidate(self.ledger,self.snapshot,self.authority,
                                           store_id=self.store_id,environment=self.environment)

    def restore(self):
        return restore_checkpoint_candidate(self.snapshot,self.target,self.history,self.authority,
            store_id=self.store_id,environment=self.environment,review_ref='fixture:restore',**self.keys)

    def purge(self):
        return purge_checkpoint_candidate(self.ledger,self.token,self.record,'PURGE:'+self.record,
            self.authority,operation_id='owned-crash-operation',store_id=self.store_id,environment=self.environment)

    def crash_child(self,phase):
        payload=dict(keys={k:v.hex() for k,v in self.keys.items()},source=str(self.source),history=str(self.history),
            environment=self.environment,binding=asdict(self.binding),store_id=self.store_id,
            token=self.token,record=self.record,phase=phase)
        env=dict(__import__('os').environ)
        env['PYTHONPATH']=str(Path(__file__).parent)+';D:/Dev/Onoes-Mind'
        env['PYTHONDONTWRITEBYTECODE']='1'
        child=subprocess.run([sys.executable,'-B','-c',CRASH],input=json.dumps(payload),text=True,
            capture_output=True,env=env,timeout=30,creationflags=subprocess.CREATE_NO_WINDOW)
        self.assertEqual(child.returncode,47,child.stderr[-1200:])
        self.assertEqual(child.stdout,'')
        self.authority=PersistentAuthorityCandidate(self.binding)

    def test_registered_equal_history_survives_real_journal_reopen(self):
        self.publish();self.authority=PersistentAuthorityCandidate(self.binding)
        restored=self.restore()
        try:self.assertEqual(len(restored.search(self.token,'banana')),1)
        finally:restored.close()

    def test_later_purge_survives_reopen_and_is_replayed_before_recall(self):
        self.publish();receipt=self.purge();self.assertTrue(receipt['checkpointAcknowledged'])
        self.authority=PersistentAuthorityCandidate(self.binding)
        restored=self.restore()
        try:self.assertEqual(restored.search(self.token,'banana'),[])
        finally:restored.close()

    def test_owned_process_crash_before_ack_stays_blocked(self):
        self.publish();self.crash_child('before_ack')
        with self.assertRaises(CheckpointRecoveryError):self.restore()
        self.assertFalse(self.target.exists())
        self.assertEqual(self.ledger.search(self.token,'banana'),[])

    def test_owned_process_crash_during_ack_commit_rolls_back_to_blocked_intent(self):
        self.publish();self.crash_child('during_commit')
        with self.assertRaises(CheckpointRecoveryError):self.restore()
        self.assertFalse(self.target.exists())

    def test_owned_process_crash_after_ack_returns_exact_receipt_on_retry(self):
        self.publish();self.crash_child('after_ack')
        first=self.purge();self.authority=PersistentAuthorityCandidate(self.binding)
        self.assertEqual(self.purge(),first)
        self.assertEqual(len(self.history.read_text().splitlines())-1,1)
        restored=self.restore()
        try:self.assertEqual(restored.search(self.token,'banana'),[])
        finally:restored.close()

    def test_copied_journal_is_not_silently_adopted_under_original_binding(self):
        copied=self.private/'copied-journal.sqlite';shutil.copyfile(self.authority.path,copied)
        with self.assertRaises(CheckpointRecoveryError):
            PersistentAuthorityCandidate(replace(self.binding,path=str(copied)))

    def test_missing_journal_does_not_create_a_replacement(self):
        missing=self.private/'missing-journal.sqlite'
        with self.assertRaises(FileNotFoundError):
            PersistentAuthorityCandidate(replace(self.binding,path=str(missing)))
        self.assertFalse(missing.exists())

    def test_wrong_authority_or_store_binding_is_refused(self):
        for changed in ({'authority_id':str(uuid.uuid4())},{'store_id':str(uuid.uuid4())}):
            with self.subTest(changed=changed),self.assertRaises(CheckpointRecoveryError):
                PersistentAuthorityCandidate(replace(self.binding,**changed))

    def test_expired_lease_cannot_register_or_read(self):
        with self.authority.hold(self.store_id,self.environment) as lease:pass
        with self.assertRaises(CheckpointRecoveryError):lease.current()

    def test_held_journal_excludes_a_second_managed_purge(self):
        self.publish()
        with self.authority.hold(self.store_id,self.environment):
            with self.assertRaises(sqlite3.OperationalError):self.purge()
        self.assertEqual(len(self.ledger.search(self.token,'banana')),1)

    def test_ack_cannot_skip_a_head_and_uncertainty_remains_blocked(self):
        actual,_=history_view(self.ledger,self.history,self.store_id,self.environment)
        admitted=self.authority.begin_purge('fixture-operation','a'*64,actual)
        with self.assertRaises(CheckpointRecoveryError):
            self.authority.ack_purge('fixture-operation','a'*64,admitted['ticket'],
                Head(self.store_id,self.environment,actual.sequence+2,'b'*64))
        with self.assertRaises(CheckpointRecoveryError):
            with self.authority.hold(self.store_id,self.environment):self.fail('uncertainty cleared')

    def test_second_create_preserves_existing_journal(self):
        original=self.authority.path.read_bytes()
        with self.assertRaises(CheckpointRecoveryError):
            PersistentAuthorityCandidate.create(self.private,self.ledger,store_id=self.store_id,
                environment=self.environment,review_ref='fixture:second-create')
        self.assertEqual(self.authority.path.read_bytes(),original)

    def test_inherited_nonprivate_directory_is_refused_before_any_journal(self):
        ordinary=self.root/'ordinary';ordinary.mkdir()
        with self.assertRaises(Exception):
            PersistentAuthorityCandidate.create(ordinary,self.ledger,store_id=self.store_id,
                environment=self.environment,review_ref='fixture:wrong-storage')
        self.assertEqual(list(ordinary.iterdir()),[])

    def test_missing_logical_head_is_refused_even_when_sqlite_integrity_passes(self):
        db=sqlite3.connect(self.authority.path)
        try:
            db.execute('DELETE FROM head');db.commit()
            self.assertEqual(db.execute('PRAGMA integrity_check').fetchone()[0],'ok')
        finally:db.close()
        with self.assertRaises(CheckpointRecoveryError):PersistentAuthorityCandidate(self.binding)

    def test_malformed_head_is_not_accepted_as_current(self):
        actual,_=history_view(self.ledger,self.history,self.store_id,self.environment)
        db=sqlite3.connect(self.authority.path)
        try:
            body=asdict(actual);body['sequence']=False
            db.execute('UPDATE head SET body=?',(json.dumps(body),));db.commit()
        finally:db.close()
        with self.assertRaises(CheckpointRecoveryError):PersistentAuthorityCandidate(self.binding)

    def test_lost_original_database_and_history_restore_from_retained_chain(self):
        self.publish();self.purge()
        expected = self.history.read_bytes()
        self.ledger.close()
        self.source.rename(self.root/'unavailable-original.sqlite')
        self.history.rename(self.root/'unavailable-original-history.jsonl')
        self.assertFalse(self.source.exists());self.assertFalse(self.history.exists())
        self.authority=PersistentAuthorityCandidate(self.binding)
        restored=restore_checkpoint_candidate(self.snapshot,self.target,None,self.authority,
            store_id=self.store_id,environment=self.environment,review_ref='fixture:lost-source',**self.keys)
        try:
            self.assertEqual(restored.search(self.token,'banana'),[])
            self.assertEqual(restored.integrity_report()['status'],'PASS')
            self.assertEqual(restored.deletion_ledger_path.read_bytes(),expected)
        finally:restored.close()

    def test_retained_chain_replays_multiple_deletions_after_history_loss(self):
        other=self.ledger.remember(self.token,dict(event_id='fixture-other',claim='fixture orange',
            kind='project_fact',project_id='onoes-mind',requested_visibility='shared'))['record_id']
        self.publish();self.purge()
        purge_checkpoint_candidate(self.ledger,self.token,other,'PURGE:'+other,self.authority,
            operation_id='second-purge',store_id=self.store_id,environment=self.environment)
        self.history.rename(self.root/'unavailable-history.jsonl')
        restored=restore_checkpoint_candidate(self.snapshot,self.target,None,self.authority,
            store_id=self.store_id,environment=self.environment,review_ref='fixture:lost-history',**self.keys)
        try:
            self.assertEqual(restored.search(self.token,'banana'),[])
            self.assertEqual(restored.search(self.token,'orange'),[])
            self.assertEqual(len(restored.deletion_ledger_path.read_bytes().splitlines()),3)
        finally:restored.close()

    def test_missing_or_stale_retained_chain_refuses_reopen(self):
        initial=self.history.read_bytes();self.publish();self.purge()
        for raw in (initial,b'broken\n'):
            db=sqlite3.connect(self.authority.path)
            try:db.execute('UPDATE history SET body=?',(raw,));db.commit()
            finally:db.close()
            with self.assertRaises(CheckpointRecoveryError):PersistentAuthorityCandidate(self.binding)
        self.assertFalse(self.target.exists())

    def test_ack_without_full_history_keeps_intent_blocked(self):
        actual,_=history_view(self.ledger,self.history,self.store_id,self.environment)
        admitted=self.authority.begin_purge('no-chain','a'*64,actual)
        self.ledger.purge(self.token,self.record,'PURGE:'+self.record)
        head,_=history_view(self.ledger,self.history,self.store_id,self.environment)
        with self.assertRaises(CheckpointRecoveryError):
            self.authority.ack_purge('no-chain','a'*64,admitted['ticket'],head)
        with self.assertRaises(CheckpointRecoveryError):
            with self.authority.hold(self.store_id,self.environment):self.fail('missing chain acknowledged')

    def test_crash_after_ack_retains_full_chain_for_source_free_restore(self):
        self.publish();self.crash_child('after_ack')
        self.history.rename(self.root/'unavailable-history.jsonl')
        restored=restore_checkpoint_candidate(self.snapshot,self.target,None,self.authority,
            store_id=self.store_id,environment=self.environment,review_ref='fixture:after-crash',**self.keys)
        try:self.assertEqual(restored.search(self.token,'banana'),[])
        finally:restored.close()

    def test_expired_lease_cannot_export_retained_history(self):
        with self.authority.hold(self.store_id,self.environment) as lease:
            self.assertEqual(lease.history(),self.history.read_bytes())
        with self.assertRaises(CheckpointRecoveryError):lease.history()

    def test_retained_chain_hash_alone_cannot_replace_canonical_authentication(self):
        self.publish();self.purge()
        lines=self.history.read_bytes().splitlines(keepends=True)
        entry=json.loads(lines[-1]);entry['record_fingerprint']='f'*64
        lines[-1]=(json.dumps(entry)+'\n').encode()
        raw=b''.join(lines)
        head=Head(self.store_id,self.environment,1,hashlib.sha256(raw).hexdigest())
        db=sqlite3.connect(self.authority.path)
        try:
            db.execute('UPDATE history SET body=?',(raw,))
            db.execute('UPDATE head SET body=?',(json.dumps(asdict(head)),));db.commit()
        finally:db.close()
        # An internally consistent hash/head still fails the actual HMAC chain.
        with self.assertRaises(CheckpointRecoveryError):
            restore_checkpoint_candidate(self.snapshot,self.target,None,self.authority,
                store_id=self.store_id,environment=self.environment,review_ref='fixture:bad-chain',**self.keys)
        self.assertFalse(self.target.exists())
        self.assertFalse(Path(str(self.target)+'.deletions.jsonl').exists())

    def test_divergent_history_cannot_acknowledge_pending_purge(self):
        actual,_=history_view(self.ledger,self.history,self.store_id,self.environment)
        admitted=self.authority.begin_purge('divergent','a'*64,actual)
        self.ledger.purge(self.token,self.record,'PURGE:'+self.record)
        raw=self.history.read_bytes().replace(b'\n',b' \n',1)
        head=Head(self.store_id,self.environment,1,hashlib.sha256(raw).hexdigest())
        with self.assertRaises(CheckpointRecoveryError):
            self.authority.ack_purge('divergent','a'*64,admitted['ticket'],head,raw)
        with self.assertRaises(CheckpointRecoveryError):
            with self.authority.hold(self.store_id,self.environment):self.fail('divergence acknowledged')

    def test_recovered_history_never_overwrites_existing_destination_history(self):
        self.publish();self.purge()
        existing=Path(str(self.target)+'.deletions.jsonl');existing.write_bytes(b'preserve me')
        with self.assertRaises(CheckpointRecoveryError):
            restore_checkpoint_candidate(self.snapshot,self.target,None,self.authority,
                store_id=self.store_id,environment=self.environment,review_ref='fixture:occupied',**self.keys)
        self.assertEqual(existing.read_bytes(),b'preserve me');self.assertFalse(self.target.exists())


if __name__=='__main__':unittest.main()
