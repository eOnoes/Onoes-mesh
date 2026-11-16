"""Real source-pinned child operator, synthetic private profiles/stores only."""
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import unittest
from unittest.mock import patch

import test_recall_process_candidate as fixtures
import recall_process_candidate as roles
import project_operator_process_candidate as project


@unittest.skipUnless(sys.platform == 'win32','Windows owned process handles')
class ProjectOperatorProcessTests(unittest.TestCase):
    def setUp(self):
        self.base=fixtures.NativeRoleProcessTests();self.base.setUp()
        self.addCleanup(self.base.doCleanups)
        old=self.base.operator_data;root=self.base.fixture.backup
        binding={key:old['binding'][key] for key in ('database_path','file_device','file_inode','store_id','environment','authority_ref')}
        runtime=old['runtime']
        self.value=dict(schema=project.SCHEMA,ownerSid=old['ownerSid'],runtime=runtime,
            sourceHashes={str(p):project.digest(p) for p in project.source_paths(runtime)},binding=binding,
            projects=[['project-A','Synthetic project']],mode='first_setup',operationId='fixture-project-operation',
            reviewRef='fixture:project-process',credentialPath=str(root/'project-service.json'),
            outcomePath=str(root/'project-outcome.json'),terminalPath=str(root/'project-terminal.json'),
            attemptPath=str(root/'project-attempt.json'),keyEnrollmentPath=old['keyEnrollmentPath'],
            authorityBindingPath=old['authorityBindingPath'],historyPath=old['historyPath'])
        self.profile=root/'project-operator.json';self.approval=root/'project-approval.json'
        self.write()

    def write(self):
        self.profile.write_text(json.dumps(self.value,indent=2),encoding='utf-8');self.sha=project.digest(self.profile)
        self.approval.write_text(json.dumps(dict(decision=project.DECISION,ownerSid=self.value['ownerSid'],profiles=[self.sha],
            storeId=self.value['binding']['store_id'],scopeId=project.SCOPE,projects=['project-A'],
            reviewRef=self.value['reviewRef'],actions=['first_setup'])),encoding='utf-8')

    def cli(self,*,run=False,approval=False,input_text=None,env=None):
        args=[sys.executable,'-I',str(Path(project.__file__).resolve()),'--profile',str(self.profile),'--sha256',self.sha]
        if run:args+=['--run']
        if approval:args+=['--approval',str(self.approval)]
        return subprocess.run(args,input=input_text,text=True,capture_output=True,timeout=45,env=env,
                              creationflags=subprocess.CREATE_NO_WINDOW)

    def project_principals(self):
        db=sqlite3.connect(self.base.database)
        try:return db.execute("SELECT count(*) FROM principals WHERE principal_id='mesh-project-sync'").fetchone()[0]
        finally:db.close()

    def test_preview_missing_approval_and_missing_parent_handshake_create_no_attempt_or_access(self):
        env={k:v for k,v in os.environ.items() if k.upper() not in ('PYTHONPATH','PYTHONHOME')}
        preview=self.cli(env=env);self.assertEqual(preview.returncode,0,preview.stdout+preview.stderr)
        self.assertTrue(json.loads(preview.stdout)['createsNothing'])
        self.assertEqual(self.cli(run=True).returncode,1)
        self.assertEqual(self.cli(run=True,approval=True,input_text='').returncode,1)
        self.assertEqual(self.project_principals(),0)
        for name in ('attemptPath','outcomePath','terminalPath','credentialPath'):
            self.assertFalse(Path(self.value[name]).exists(),name)

    def test_owned_operator_terminal_receipt_requires_actual_exit_and_no_repeat(self):
        child,stamp=project.launch_operator(self.profile,self.sha,self.approval);self.base.children.append(child)
        self.assertIsNone(child.poll())
        with self.assertRaises(project.ProjectProcessError):project.finish_operator(child,stamp,self.profile,self.sha,self.approval)
        self.assertFalse(Path(self.value['terminalPath']).exists())
        self.assertEqual(child.wait(timeout=120),0)
        terminal=project.finish_operator(child,stamp,self.profile,self.sha,self.approval)
        self.assertEqual(terminal['pid'],child.pid);self.assertEqual(terminal['creationTicks'],stamp)
        self.assertEqual(terminal['exitCode'],0)
        outcome=json.loads(Path(self.value['outcomePath']).read_text())
        self.assertEqual(outcome['status'],'provisioned_inactive');self.assertFalse(outcome['serviceStarted'])
        self.assertEqual(self.project_principals(),1)
        actual=project.subprocess.Popen
        def no_operator(args,*a,**kw):
            if str(Path(project.__file__).resolve()) in args: raise AssertionError('No repeat child')
            return actual(args,*a,**kw)
        with patch.object(project.subprocess,'Popen',side_effect=no_operator) as spawn:
            with self.assertRaises(Exception):project.launch_operator(self.profile,self.sha,self.approval)
            self.assertFalse(any(str(Path(project.__file__).resolve()) in c.args[0] for c in spawn.call_args_list))

    def test_unknown_identity_retains_same_child_pid_marker_and_never_sends_start(self):
        actual=project.subprocess.Popen
        with patch.object(roles,'creation_ticks',side_effect=OSError('synthetic identity failure')),\
             patch.object(project.subprocess,'Popen',wraps=actual) as spawn:
            with self.assertRaises(project.OperatorLaunchUnknown) as caught:
                project.launch_operator(self.profile,self.sha,self.approval)
            child=caught.exception.child;self.base.children.append(child)
            self.assertEqual(sum(str(Path(project.__file__).resolve()) in c.args[0] for c in spawn.call_args_list),1)
        record=json.loads(Path(self.value['attemptPath']).read_text())
        self.assertEqual(record['pid'],child.pid);self.assertIsNone(record['creationTicks'])
        self.assertEqual(record['state'],'identity_pending')
        self.assertEqual(child.wait(timeout=120),1)
        self.assertEqual(self.project_principals(),0)
        self.assertFalse(Path(self.value['outcomePath']).exists())
        self.assertFalse(Path(self.value['terminalPath']).exists())

    def test_readonly_approval_or_changed_or_missing_dependency_refuses_before_child(self):
        self.approval.write_text(json.dumps(self.base.approval_data),encoding='utf-8')
        actual=project.subprocess.Popen
        def no_operator(args,*a,**kw):
            if str(Path(project.__file__).resolve()) in args: raise AssertionError('No unapproved child')
            return actual(args,*a,**kw)
        with patch.object(project.subprocess,'Popen',side_effect=no_operator) as spawn:
            with self.assertRaises(project.ProjectProcessError):project.launch_operator(self.profile,self.sha,self.approval)
            self.assertFalse(any(str(Path(project.__file__).resolve()) in c.args[0] for c in spawn.call_args_list))
        self.value['sourceHashes'][str(Path(project.__file__).resolve())]='0'*64;self.write()
        with self.assertRaises(project.ProjectProcessError):project.launch_operator(self.profile,self.sha,self.approval)
        self.value['sourceHashes']={str(p):project.digest(p) for p in project.source_paths(self.value['runtime'])}
        self.value['sourceHashes'].pop(str(Path(project.__file__).parent/'provision_project_sync_candidate.py'));self.write()
        with self.assertRaises(project.ProjectProcessError):project.launch_operator(self.profile,self.sha,self.approval)
        self.assertFalse(Path(self.value['attemptPath']).exists());self.assertEqual(self.project_principals(),0)
