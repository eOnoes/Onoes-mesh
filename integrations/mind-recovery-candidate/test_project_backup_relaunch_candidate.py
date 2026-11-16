"""Synthetic successful backup + fresh writer-profile relaunch acceptance."""
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import sqlite3
import sys
import time
import unittest
import uuid
from unittest.mock import patch

import project_backup_entry as window
import project_operator_process_candidate as operator
import project_service_process_candidate as service
import recall_process_candidate as roles
import test_project_backup_entry as backup_fixtures
import test_project_service_process_candidate as service_fixtures


@unittest.skipUnless(os.name=='nt','Windows exact ownership/DPAPI fixture')
class BackupRelaunchTests(unittest.TestCase):
    def test_backup_then_fresh_profile_reuses_grant_and_original_receipt(self):
        case=backup_fixtures.BackupWindowTests();case.setUp();self.addCleanup(case.doCleanups)
        native=case.fixture;root=case.root;children=[]
        def note(phase):print('BACKUP_RELAUNCH_PHASE='+phase,file=sys.stderr,flush=True)
        note('fixture_ready')
        p=case.value;runtime=p['runtime']
        op=dict(schema=operator.SCHEMA,ownerSid=p['ownerSid'],runtime=runtime,
            sourceHashes={str(n):operator.digest(n) for n in operator.source_paths(runtime)},binding=p['binding'],
            projects=[['project-A','Synthetic backup/relaunch project']],mode='first_setup',operationId='fixture-backup-relaunch-grant',
            reviewRef='fixture:backup-relaunch',credentialPath=str(root/'success-credential.json'),outcomePath=str(root/'success-outcome.json'),
            terminalPath=str(root/'success-terminal.json'),attemptPath=str(root/'success-operator-attempt.json'),
            keyEnrollmentPath=p['keyEnrollmentPath'],authorityBindingPath=p['authorityBindingPath'],historyPath=p['historyPath'])
        op_profile=root/'success-operator.json';op_profile.write_text(json.dumps(op,indent=2),encoding='utf-8');op_sha=operator.digest(op_profile)
        profiles=[]
        for suffix in ('before-backup','after-backup'):
            value=dict(schema=service.SCHEMA,sourceHashes={str(n):service.digest(n) for n in
                (Path(service.__file__).resolve(),Path(operator.__file__).resolve())},operatorProfilePath=str(op_profile),operatorProfileSha256=op_sha,
                attemptPath=str(root/('success-'+suffix+'-service-attempt.json')),readyPath=str(root/('success-'+suffix+'-ready.json')),
                stopPath=str(root/('success-'+suffix+'-stop.json')))
            file=root/('success-service-'+suffix+'.json');file.write_text(json.dumps(value,indent=2),encoding='utf-8')
            profiles.append((file,service.digest(file),value))
        approval=root/'success-lifecycle-approval.json'
        grant=dict(decision=operator.DECISION,ownerSid=p['ownerSid'],profiles=[op_sha,*[v[1] for v in profiles]],
            storeId=case.store,scopeId=operator.SCOPE,projects=['project-A'],reviewRef=op['reviewRef'],actions=['first_setup','run_service'])
        approval.write_text(json.dumps(grant),encoding='utf-8')
        def ready(file,sha,child):
            from onoes_mind.enrollment_store import EnrollmentStorageError
            deadline=time.monotonic()+120
            while time.monotonic()<deadline:
                self.assertIsNone(child.poll(),'Owned synthetic writer exited before readiness')
                try:
                    value=service.service_state(file,sha,approval)
                    if value['ready']:return value
                except (FileNotFoundError,service.ServiceProcessError,EnrollmentStorageError,json.JSONDecodeError):pass
                time.sleep(.1)
            self.fail('Owned synthetic writer did not become ready; retained handle belongs to this fixture')
        def stop(file,sha,child,stamp):
            service.request_stop(file,sha,approval);self.assertEqual(child.wait(timeout=120),0)
            state=service.service_state(file,sha,approval)
            self.assertEqual((state['state'],state['processLive']),('stopped',False))
            self.assertEqual(roles.creation_ticks(child._handle),stamp)
        def cleanup_services():
            for file,sha,child,stamp in reversed(children):
                if child.poll() is None:stop(file,sha,child,stamp)
        self.addCleanup(cleanup_services)
        child,stamp=operator.launch_operator(op_profile,op_sha,approval);native.children.append(child)
        self.assertEqual(child.wait(timeout=180),0);operator.finish_operator(child,stamp,op_profile,op_sha,approval)
        grant_terminal_sha=operator.digest(op['terminalPath']);credential_sha=operator.digest(op['credentialPath'])
        key_sha=operator.digest(p['keyEnrollmentPath']);note('grant_provisioned_once')
        first_file,first_sha,first_value=profiles[0]
        first,first_stamp=service.launch_service(first_file,first_sha,approval);native.children.append(first)
        children.append((first_file,first_sha,first,first_stamp));first_state=ready(first_file,first_sha,first)
        first_options=service.native_options(first_file,first_sha,approval)
        token_hash=hashlib.sha256(first_options['destination']['token'].encode()).hexdigest()
        receipt=service_fixtures.ProjectServiceProcessTests.send(self,first_options);first_options=None
        note('first_receipt_saved')
        stop(first_file,first_sha,first,first_stamp);note('first_writer_retired')
        case.value['writerGate']=dict(kind='stopped',attemptPath=first_value['attemptPath'],readyPath=first_value['readyPath'],profileSha256=first_sha)
        target=Path('E:/App-Backups/Onoes-Mind/Candidates/Backup-and-relaunch-2026-11-16');target.mkdir(parents=True,exist_ok=True)
        case.value['encryptedBackup']=str(target/('Same-grant-fresh-writer-'+uuid.uuid4().hex+'.7z'));case.write()
        output=io.StringIO()
        with patch('getpass.getpass',side_effect=[case.password,case.password]),contextlib.redirect_stdout(output):
            self.assertEqual(window.main(['--profile',str(case.profile),'--sha',case.sha,'--approval',str(case.approval),'--run']),0)
        backup=json.loads(Path(case.value['resultPath']).read_text())
        self.assertEqual(backup['projectReceiptCount'],1);self.assertEqual(backup['status'],'backup_complete_inactive')
        self.assertFalse(backup['newKeysCreated']);self.assertFalse(backup['newCredentialsCreated']);self.assertFalse(backup['serviceStarted'])
        self.assertEqual(operator.digest(op['terminalPath']),grant_terminal_sha)
        self.assertEqual(operator.digest(op['credentialPath']),credential_sha);self.assertEqual(operator.digest(p['keyEnrollmentPath']),key_sha)
        self.assertNotIn(case.password,output.getvalue());note('encrypted_backup_and_rehearsal_complete')
        second_file,second_sha,second_value=profiles[1];self.assertNotEqual(second_sha,first_sha)
        held=dict(grant,profiles=[op_sha,first_sha]);approval.write_text(json.dumps(held),encoding='utf-8')
        try:
            with self.assertRaises((operator.ProjectProcessError,service.ServiceProcessError)):
                service.launch_service(second_file,second_sha,approval)
            self.assertFalse(Path(second_value['attemptPath']).exists())
        finally:approval.write_text(json.dumps(grant),encoding='utf-8')
        second,second_stamp=service.launch_service(second_file,second_sha,approval);native.children.append(second)
        children.append((second_file,second_sha,second,second_stamp));second_state=ready(second_file,second_sha,second)
        self.assertNotEqual((second.pid,second_stamp),(first.pid,first_stamp));self.assertNotEqual(second_state['runId'],first_state['runId'])
        second_options=service.native_options(second_file,second_sha,approval)
        self.assertEqual(second_options['peer']['pid'],second.pid);self.assertEqual(second_options['peer']['creationTicks'],str(second_stamp))
        self.assertEqual(second_options['peer']['profileSha256'],second_sha)
        self.assertEqual(hashlib.sha256(second_options['destination']['token'].encode()).hexdigest(),token_hash)
        again=service_fixtures.ProjectServiceProcessTests.send(self,second_options);second_options=None
        self.assertEqual(again['receiptId'],receipt['receiptId']);note('fresh_profile_same_grant_same_receipt')
        db=sqlite3.connect(native.database.as_uri()+'?mode=ro',uri=True)
        try:self.assertEqual(db.execute('SELECT count(*) FROM project_sync_events').fetchone()[0],1)
        finally:db.close()
        stop(second_file,second_sha,second,second_stamp);note('fresh_writer_retired')
        result=dict(schema='onoes-mesh-backup-relaunch-proof/v1',syntheticOnly=True,liveChanged=False,grantProvisionedOnce=True,
            firstWriterRetiredBeforeBackup=True,archive=backup['archive'],archiveSha256=backup['archiveSha256'],
            archiveRehearsal=backup['archiveRehearsal'],projectReceiptReadback=backup['projectReceiptReadback'],
            recoveredReceiptCount=1,canonicalReceiptCountAfterRetry=1,sameReceiptIdAfterRelaunch=True,
            grantTerminalUnchanged=True,wrappedKeyPackageUnchanged=True,credentialFileUnchanged=True,
            sameCredentialAfterRelaunch=True,freshProfileShaChanged=True,freshPeerIdentityVerified=True,
            missingFreshProfileApprovalRefused=True,freshWriterRetiredAtEnd=True,credentialRecoveryQualified=False)
        proof=Path(__file__).resolve().parents[2]/'data/project-backup-relaunch-proof-20261116.json'
        proof.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')


if __name__=='__main__':unittest.main()
