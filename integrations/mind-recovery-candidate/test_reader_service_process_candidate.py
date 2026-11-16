"""Managed-reader refusals and opt-in actual unchanged-enrollment restart."""
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from types import SimpleNamespace, ModuleType
import unittest
import uuid
from unittest.mock import patch

import reader_service_process_candidate as service
import recall_process_candidate as roles


class ReaderServiceBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name).resolve();self.profile=self.root/'managed-reader.json'
        self.base_path=self.root/'reader.json';self.base_path.write_text('{}')
        self.approval=self.root/'approval.json'
        self.base=dict(role='reader',**{name:str(self.root/name) for name in
            ('readyPath','stopPath','credentialPath','outcomePath','terminalPath')})
        self.binding=SimpleNamespace(store_id='synthetic-store',scope_id='shared',database_path=str(self.root/'ledger.sqlite'))
        self.p=dict(schema=service.SCHEMA,sourceHashes={str(p):service.digest(p) for p in
            (Path(service.__file__).resolve(),service.HERE/'recall_process_candidate.py')},
            readerProfilePath=str(self.base_path),readerProfileSha256='base-hash',
            attemptPath=str(self.root/'managed-attempt'),stopPath=str(self.root/'managed-stop'))
        fake=ModuleType('onoes_mind.enrollment_store')
        def qualify(path,kind='directory'):
            if kind=='file' and not Path(path).is_file():raise ValueError('Missing private file')
            return Path(path).resolve(strict=True)
        fake.qualify_private_storage=qualify
        for context in (patch.dict(sys.modules,{'onoes_mind.enrollment_store':fake}),
                        patch.object(roles,'approved_profile',return_value=(self.base,self.binding)),
                        patch.object(roles,'terminal_proof',return_value=None),
                        patch.object(roles,'plain_json',side_effect=lambda path,limit=65536:json.loads(Path(path).read_text()))):
            context.start();self.addCleanup(context.stop)
        self.write()

    def write(self):
        self.profile.write_text(json.dumps(self.p));self.sha=service.digest(self.profile)
        self.approval.write_text(json.dumps(dict(profiles=['base-hash',self.sha])))

    def seed(self):
        attempt=dict(schema='onoes-mind-reader-service-attempt/v1',profileSha256=self.sha,
            runId='a'*32,pid=101,creationTicks=2020,state='started')
        owner=dict(schema='onoes-mind-reader-owner/v1',profileSha256='base-hash',
            managedBy=self.sha,runId='a'*32,pid=101,creationTicks=2020,state='running',
            storeId='synthetic-store',scopeId='shared')
        Path(self.p['attemptPath']).write_text(json.dumps(attempt));Path(self.base['readyPath']).write_text(json.dumps(owner))
        return attempt,owner

    def test_exact_wrapper_profile_never_changes_original_enrollment(self):
        before=self.base_path.read_bytes()
        p,base,binding=service.checked_profile(self.profile,self.sha,self.approval)
        self.assertEqual(p,self.p);self.assertEqual(base,self.base);self.assertIs(binding,self.binding)
        self.assertEqual(self.base_path.read_bytes(),before)
        self.assertFalse(Path(self.p['attemptPath']).exists())

    def test_wrong_source_missing_approval_or_colliding_runtime_paths_refuse(self):
        variants=[]
        bad=copy.deepcopy(self.p);bad['sourceHashes'][str(Path(service.__file__).resolve())]='0'*64;variants.append(bad)
        bad=copy.deepcopy(self.p);bad['attemptPath']=self.base['credentialPath'];variants.append(bad)
        bad=copy.deepcopy(self.p);bad['stopPath']=bad['attemptPath'];variants.append(bad)
        bad=copy.deepcopy(self.p);bad['extra']=True;variants.append(bad)
        for bad in variants:
            self.p=bad;self.write()
            with self.assertRaises(service.ReaderServiceError):service.checked_profile(self.profile,self.sha,self.approval)
        with self.assertRaises(service.ReaderServiceError):service.checked_profile(self.profile,self.sha,None)

    def test_live_or_unobserved_process_blocks_archival(self):
        self.seed();before=Path(self.p['attemptPath']).read_bytes()
        with patch.object(roles,'same_process_alive',return_value=True):
            with self.assertRaises(service.ReaderServiceError):service._retire_previous(self.p,self.base,self.binding,self.sha,self.approval)
        with patch.object(roles,'same_process_alive',side_effect=PermissionError):
            with self.assertRaises(PermissionError):service._retire_previous(self.p,self.base,self.binding,self.sha,self.approval)
        self.assertEqual(Path(self.p['attemptPath']).read_bytes(),before)

    def test_partial_attempt_and_ready_identity_mismatch_stay_held(self):
        attempt,owner=self.seed();attempt['state']='identity_pending'
        Path(self.p['attemptPath']).write_text(json.dumps(attempt))
        with self.assertRaises(service.ReaderServiceError):service._attempt(self.p,self.sha)
        attempt['state']='started';owner['pid']=999
        Path(self.p['attemptPath']).write_text(json.dumps(attempt));Path(self.base['readyPath']).write_text(json.dumps(owner))
        with patch.object(roles,'same_process_alive',return_value=False):
            with self.assertRaises(service.ReaderServiceError):service._retire_previous(self.p,self.base,self.binding,self.sha,self.approval)
        self.assertTrue(Path(self.p['attemptPath']).exists())

    def test_exact_retired_evidence_is_preserved_not_deleted(self):
        self.seed();paths=[Path(self.p['attemptPath']),Path(self.base['readyPath'])];before=[p.read_bytes() for p in paths]
        with patch.object(roles,'same_process_alive',return_value=False):
            service._retire_previous(self.p,self.base,self.binding,self.sha,self.approval)
        self.assertEqual([p.with_name(p.name+'.retired-'+'a'*32).read_bytes() for p in paths],before)
        self.assertFalse(any(p.exists() for p in paths))

    def test_interrupted_archive_retains_blocking_attempt(self):
        self.seed();actual=service.os.rename;calls=[]
        def fail_second(source,target):
            calls.append(source)
            if len(calls)==2:raise OSError('Synthetic archive interruption')
            actual(source,target)
        with patch.object(roles,'same_process_alive',return_value=False),patch.object(service.os,'rename',side_effect=fail_second):
            with self.assertRaises(OSError):service._retire_previous(self.p,self.base,self.binding,self.sha,self.approval)
        self.assertTrue(Path(self.p['attemptPath']).exists())

    @unittest.skipUnless(os.name=='nt','Windows kernel lease')
    def test_another_thread_cannot_take_the_reader_lifetime_lease(self):
        first=service.ReaderLease(self.binding);results=[]
        def second():
            try:
                lease=service.ReaderLease(self.binding)
                try:results.append('unexpected-owner')
                finally:lease.close()
            except service.ReaderServiceError:results.append('held')
        try:
            thread=threading.Thread(target=second);thread.start();thread.join(timeout=5)
            self.assertFalse(thread.is_alive());self.assertEqual(results,['held'])
        finally:first.close()


@unittest.skipUnless(os.name=='nt' and os.environ.get('MESH_MANAGED_READER_QUALIFY')=='1',
                     'Explicit synthetic managed reader qualification only')
class ManagedReaderProcessTests(unittest.TestCase):
    def test_legacy_reader_then_two_managed_generations_keep_enrollment_and_read_scope(self):
        import test_recall_process_candidate as fixtures
        case=fixtures.NativeRoleProcessTests();self.addCleanup(case.doCleanups);case.setUp()
        self.assertEqual(case.environment,'synthetic-process-handoff')
        self.assertTrue(case.database.is_relative_to(case.fixture.root))
        def phase(value):print('Synthetic managed reader phase: '+value,flush=True)
        phase('enrollment_start')
        operator,ticks=roles.launch_operator(case.operator,case.operator_sha,case.approval);case.children.append(operator)
        self.assertEqual(operator.wait(timeout=120),0);roles.finish_operator(operator,ticks,case.operator,case.operator_sha,case.approval)
        parked=case.key_package.with_name('key-enrollment.unavailable-to-reader-test')
        self.assertTrue(case.key_package.resolve().is_relative_to(case.fixture.root.resolve()))
        self.assertTrue(parked.resolve().is_relative_to(case.fixture.root.resolve()))
        case.key_package.rename(parked)
        credential=Path(case.reader_data['credentialPath']);credential_sha=roles.digest(credential)
        ledger_sha=roles.digest(case.database);terminal_sha=roles.digest(case.reader_data['terminalPath'])
        old,old_ticks=roles.launch_reader(case.reader,case.reader_sha,case.approval);case.children.append(old)
        def wait(action,child,timeout=90):
            until=time.monotonic()+timeout
            while time.monotonic()<until:
                self.assertIsNone(child.poll(),'Owned reader exited before qualification')
                try:value=action()
                except (FileNotFoundError,json.JSONDecodeError):value=None
                if value:return value
                time.sleep(.2)
            self.fail('Same owned reader did not become ready; no replacement launched')
        def legacy_ready():
            raw=json.loads(Path(case.reader_data['readyPath']).read_text())
            return roles.reader_state(case.reader,case.reader_sha,case.approval)['ready'] if raw.get('state')=='running' else None
        wait(legacy_ready,old)
        roles.request_stop(case.reader,case.reader_sha,case.approval);self.assertEqual(old.wait(timeout=30),0)
        root=case.reader.parent;profile=root/'managed-reader.json'
        p=dict(schema=service.SCHEMA,sourceHashes={str(p):service.digest(p) for p in
            (Path(service.__file__).resolve(),service.HERE/'recall_process_candidate.py')},
            readerProfilePath=str(case.reader),readerProfileSha256=case.reader_sha,
            attemptPath=str(root/'managed-reader-attempt.json'),stopPath=str(root/'managed-reader-stop'))
        roles.private_new_json(profile,p);sha=service.digest(profile)
        accepted=json.loads(case.approval.read_text());accepted['profiles'].append(sha);case.approval.write_text(json.dumps(accepted))
        def start():
            try:child,stamp=service.launch_service(profile,sha,case.approval)
            except service.ReaderLaunchUnknown as error:case.children.append(error.child);raise
            case.children.append(child);return child,stamp
        def ready(child):
            def observe():
                value=service.service_state(profile,sha,case.approval)
                return value if value['ready'] else None
            return wait(observe,child)
        first,first_ticks=start();first_state=ready(first);phase('legacy_evidence_preserved_first_managed_reader_ready')
        self.assertEqual(first_state['pid'],first.pid);self.assertEqual(first_state['creationTicks'],first_ticks)
        self.assertTrue(Path(case.reader_data['readyPath']+'.retired-legacy-'+str(old.pid)+'-'+str(old_ticks)).exists())
        actual_popen=service.subprocess.Popen;duplicate_starts=[]
        def observe_launch(args,*positional,**kwargs):
            if isinstance(args,(list,tuple)) and str(Path(service.__file__).resolve()) in args and '--run' in args:
                duplicate_starts.append(args);raise AssertionError('No duplicate reader process')
            return actual_popen(args,*positional,**kwargs)
        with patch.object(service.subprocess,'Popen',side_effect=observe_launch):
            with self.assertRaises(service.ReaderServiceError):service.launch_service(profile,sha,case.approval)
        self.assertEqual(duplicate_starts,[])
        first.terminate();first.wait(timeout=30)
        second,second_ticks=start();second_state=ready(second);phase('crashed_reader_restarted_same_credential')
        self.assertNotEqual((second.pid,second_ticks),(first.pid,first_ticks))
        self.assertNotEqual(second_state['runId'],first_state['runId'])
        stale=service.stop_target(p,first_state['runId'])
        roles.private_new_json(stale,dict(profileSha256=sha,runId=first_state['runId'],pid=first.pid,creationTicks=first_ticks,stop=True))
        options=roles.native_options(case.reader,case.reader_sha,case.approval)
        result=subprocess.run([shutil.which('node'),'--input-type=module','-e',fixtures.NODE,
            str(Path(__file__).resolve().parents[2]/'lib/mind-recall.mjs')],input=json.dumps(options),
            capture_output=True,text=True,timeout=30,creationflags=subprocess.CREATE_NO_WINDOW)
        self.assertEqual(result.returncode,0,result.stderr);response=json.loads(result.stdout)
        self.assertTrue(response['ok']);self.assertEqual(response['result']['records'],[])
        self.assertIsNone(second.poll());self.assertEqual(roles.digest(credential),credential_sha)
        self.assertEqual(roles.digest(case.database),ledger_sha);self.assertEqual(roles.digest(case.reader_data['terminalPath']),terminal_sha)
        for path in (Path(p['attemptPath']),Path(case.reader_data['readyPath'])):
            self.assertNotIn(options['token'],path.read_text())
        service.request_stop(profile,sha,case.approval);self.assertEqual(second.wait(timeout=30),0)
        final=service.service_state(profile,sha,case.approval)
        self.assertEqual(final['state'],'stopped');self.assertFalse(final['processLive'])
        proof=dict(schema='onoes-mesh-synthetic-managed-reader/v1',syntheticOnly=True,liveChanged=False,
            originalEnrollmentUnchanged=True,credentialUnchanged=True,canonicalLedgerBytesUnchanged=True,
            originalOperatorTerminalUnchanged=True,writerKeyPackageUnavailable=True,
            legacyRetirementPreserved=True,actualCrashRestartPassed=True,staleGenerationStopIgnored=True,
            actualMeshReadClientPassed=True,emptyScopedReadPassed=True,noDuplicateWhileAlive=True,
            ownedCleanStopPassed=True,sourceSha256=service.digest(service.__file__))
        target=Path(__file__).resolve().parents[2]/('data/managed-reader-qualification-'+uuid.uuid4().hex+'.json')
        with target.open('x',encoding='utf-8') as output:json.dump(proof,output,indent=2)
        phase('qualified_and_owned_processes_stopped');print('Synthetic managed reader proof: '+str(target),flush=True)


if __name__=='__main__':unittest.main()
