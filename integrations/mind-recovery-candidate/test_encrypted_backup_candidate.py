"""Actual canonical Mind packages and verified 7za; synthetic records/keys only."""
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import unittest
import uuid
from unittest.mock import patch

import test_checkpointed_ledger_candidate as fixtures
from onoes_mind.enrollment_store import prepare_and_save_enrollment
from onoes_mind.runtime_keys import unprotect_runtime_keys
from checkpoint_candidate import publish_snapshot_candidate
from checkpointed_ledger_candidate import restore_checkpointed_candidate
import encrypted_backup_candidate as archive

EVIDENCE=Path(__file__).resolve().parents[2].parent/'mesh-workroom-ab/data'
TOOL_PROOF=EVIDENCE/'sevenzip-tool-proof-20261115.json'


@unittest.skipUnless(sys.platform=='win32' and TOOL_PROOF.is_file(),'Qualified Windows fixture tool required')
class EncryptedBackupTests(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.CheckpointedLedgerTests();self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root=self.fixture.root
        self.source=self.private('backup-source');self.stage=self.private('archive-stage');self.output=self.private('readback')
        tool_proof=json.loads(TOOL_PROOF.read_text());self.tool=Path(tool_proof['tool'])
        self.assertEqual(archive.TOOL_SHA256,tool_proof['toolSha256'])
        self.password='fixture-long-passphrase-\u00e9-2026'
        self.snapshot=self.source/'first-empty-snapshot.sqlite'
        self.publication=publish_snapshot_candidate(self.fixture.ledger,self.snapshot,self.fixture.authority,
            store_id=self.fixture.store_id,environment=self.fixture.environment)
        prepare_and_save_enrollment(directory=self.source,**self.fixture.keys,
            store_id=self.fixture.store_id,environment_id=self.fixture.environment,
            password=self.password,confirmation=self.password)
        (self.source/'key-enrollment.json').rename(self.source/'encrypted-key-enrollment.json')
        shutil.copyfile(self.fixture.history,self.source/'snapshot-deletion-history.jsonl')
        self.target_root=Path('E:/App-Backups/Onoes-Mesh/Candidates/Mind-encrypted-backup-trial-2026-11-15')
        self.target_root.mkdir(parents=True,exist_ok=True)
        self.destination=self.target_root/(self._testMethodName+'-'+str(uuid.uuid4())+'.7z')

    def private(self,name):
        folder=self.root/name;folder.mkdir()
        script=self.root.parent/'fixture-private-acl.ps1'
        subprocess.run([shutil.which('pwsh'),'-NoProfile','-NonInteractive','-File',str(script),'-Path',str(folder)],
            capture_output=True,check=True,creationflags=subprocess.CREATE_NO_WINDOW)
        return folder

    def export(self,**overrides):
        args=dict(publication=self.publication);args.update(overrides)
        return archive.export_encrypted_backup_candidate(self.source,self.stage,self.destination,
            self.tool,self.password,**args)

    def unpack(self,receipt,password=None,path=None):
        return archive.unpack_encrypted_backup_candidate(path or self.destination,self.output,self.tool,
            self.password if password is None else password,
            expected_archive_sha256=receipt['archiveSha256'],publication=self.publication)

    def test_real_E_archive_restores_keys_and_data_after_source_loss_without_reviving_deletion(self):
        self.fixture.purge()
        (self.source/'snapshot-deletion-history.jsonl').write_bytes(self.fixture.history.read_bytes())
        calls=[];actual=archive.subprocess.run
        def observe(command,**kwargs):
            if str(command[0])==str(self.tool):calls.append((command,kwargs.get('input',b'')))
            return actual(command,**kwargs)
        with patch.object(archive.subprocess,'run',side_effect=observe):
            receipt=self.export();self.fixture.ledger.close()
            self.fixture.database.rename(self.root/'unavailable-source.sqlite')
            self.fixture.history.rename(self.root/'unavailable-history.jsonl')
            for name in ('first-empty-snapshot.sqlite','first-empty-snapshot.sqlite.meta',
                         'encrypted-key-enrollment.json','snapshot-deletion-history.jsonl'):
                (self.source/name).rename(self.source/(name+'.fixture-unavailable'))
            self.fixture.keys=None
            extracted=self.unpack(receipt)
        self.assertFalse(extracted['activated']);self.assertFalse(extracted['currentAuthorityQualified'])
        self.assertTrue(calls)
        for command,sensitive_input in calls:
            self.assertNotIn(self.password,' '.join(command));self.assertIn(self.password.encode(),sensitive_input)
            self.assertFalse(any(a.startswith('-p') and a!='-p' for a in command))
        package=json.loads((self.output/'encrypted-key-enrollment.json').read_text())
        recovered_keys=unprotect_runtime_keys(package['runtime_envelope'],store_id=self.fixture.store_id,
            environment_id=self.fixture.environment)
        restored=restore_checkpointed_candidate(self.output/'snapshot.sqlite',self.output/'restored.sqlite',None,
            self.fixture.authority,**recovered_keys,store_id=self.fixture.store_id,
            environment=self.fixture.environment,review_ref='fixture:archive-readback')
        try:self.assertEqual(restored.search(self.fixture.token,'banana'),[])
        finally:restored.close()
        public=json.dumps(receipt)
        for secret in (self.password,'runtime_envelope','recovery_envelope','fixture banana'):
            self.assertNotIn(secret,public)
        denied=subprocess.run([str(self.tool),'l','-slt','--',str(self.destination)],input=b'wrong-fixture-password\n',
            capture_output=True,creationflags=subprocess.CREATE_NO_WINDOW,timeout=30)
        self.assertNotEqual(denied.returncode,0)
        self.assertNotIn(b'encrypted-key-enrollment.json',denied.stdout+denied.stderr)
        result_path=EVIDENCE/('mind-encrypted-E-roundtrip-result-20261115-'+str(uuid.uuid4())+'.json')
        result_path.write_text(json.dumps({
            'archive':str(self.destination),'archiveSha256':receipt['archiveSha256'],
            'snapshotStoreId':self.fixture.store_id,'originalFilesUnavailable':True,
            'keysRecoveredFromArchive':True,'laterDeletionStillAbsent':True,
            'archiveHeadersEncrypted':True,'passwordAbsentFromArguments':True,
            'activated':False,'syntheticDataOnly':True},indent=2)+'\n')
        print('ROUNDTRIP_PROOF='+str(result_path),flush=True)

    def test_wrong_password_writes_no_recovery_files(self):
        receipt=self.export()
        with self.assertRaises(archive.EncryptedBackupError):self.unpack(receipt,password='wrong-fixture-password')
        self.assertEqual(list(self.output.iterdir()),[])

    def test_changed_source_prevents_E_publication(self):
        actual=archive.run_tool
        def changed(tool,arguments,password,**kwargs):
            result=actual(tool,arguments,password,**kwargs)
            if arguments[0]=='a':
                with (self.source/'snapshot-deletion-history.jsonl').open('ab') as stream:stream.write(b'fixture-change')
            return result
        with patch.object(archive,'run_tool',side_effect=changed):
            with self.assertRaises(archive.EncryptedBackupError):self.export()
        self.assertFalse(self.destination.exists())

    def test_existing_archive_is_preserved_without_tool_call(self):
        self.destination.write_bytes(b'preserve this synthetic marker')
        with patch.object(archive,'run_tool') as tool:
            with self.assertRaises(archive.EncryptedBackupError):self.export()
            tool.assert_not_called()
        self.assertEqual(self.destination.read_bytes(),b'preserve this synthetic marker')

    def test_changed_tool_refused_before_execution(self):
        fake=self.root/'changed-tool.exe';fake.write_bytes(b'not an executable')
        with patch.object(archive.subprocess,'run') as process:
            with self.assertRaises(archive.EncryptedBackupError):archive.run_tool(fake,['i'],self.password)
            process.assert_not_called()

    def test_changed_archive_fingerprint_refuses_before_decryption_or_writes(self):
        receipt=self.export();damaged=self.target_root/('damaged-'+str(uuid.uuid4())+'.7z')
        data=bytearray(self.destination.read_bytes());data[len(data)//2]^=1;damaged.write_bytes(data)
        with patch.object(archive,'run_tool') as tool:
            with self.assertRaises(archive.EncryptedBackupError):self.unpack(receipt,path=damaged)
            tool.assert_not_called()
        self.assertEqual(list(self.output.iterdir()),[])

    def test_wrong_store_package_refuses_before_staging_or_export(self):
        wrong=replace(self.publication,store_id=str(uuid.uuid4()))
        with self.assertRaises(archive.EncryptedBackupError):self.export(publication=wrong)
        self.assertFalse(self.destination.exists());self.assertEqual(list(self.stage.iterdir()),[])


if __name__=='__main__':unittest.main()
