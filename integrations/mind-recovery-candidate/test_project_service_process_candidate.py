"""Owned long-lived project service process, synthetic profiles/data only."""
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import time
import unittest
from unittest.mock import patch
import urllib.request

import test_project_operator_process_candidate as fixtures
import project_operator_process_candidate as operator
import project_service_process_candidate as service
import recall_process_candidate as roles
from test_project_events_candidate import event


@unittest.skipUnless(sys.platform=='win32','Windows owned project service')
class ProjectServiceProcessTests(unittest.TestCase):
    def setUp(self):
        self.base=fixtures.ProjectOperatorProcessTests();self.base.setUp()
        self.addCleanup(self.base.doCleanups)
        root=self.base.profile.parent
        self.profile=root/'project-service-profile.json'
        self.value=dict(schema=service.SCHEMA,sourceHashes={str(p):service.digest(p) for p in (
            Path(service.__file__).resolve(),Path(operator.__file__).resolve())},
            operatorProfilePath=str(self.base.profile),operatorProfileSha256=self.base.sha,
            attemptPath=str(root/'service-attempt.json'),readyPath=str(root/'service-ready.json'),stopPath=str(root/'service-stop.json'))
        self.write();self.children=[];self.addCleanup(self.close_children)

    def write(self,actions=None):
        self.profile.write_text(json.dumps(self.value,indent=2),encoding='utf-8');self.sha=service.digest(self.profile)
        a=json.loads(self.base.approval.read_text());a['profiles']=[self.base.sha,self.sha]
        a['actions']=actions or ['first_setup','run_service'];self.base.approval.write_text(json.dumps(a),encoding='utf-8')

    def close_children(self):
        for child,stamp in self.children:
            if child.poll() is None:
                try:service.request_stop(self.profile,self.sha,self.base.approval);child.wait(timeout=20)
                except Exception:
                    # These are exact fresh test-owned handles, never an app or
                    # production process selected by PID/name/port.
                    child.terminate();child.wait(timeout=15)

    def prepare(self):
        child,stamp=operator.launch_operator(self.base.profile,self.base.sha,self.base.approval)
        self.base.base.children.append(child)
        self.assertEqual(child.wait(timeout=120),0)
        return operator.finish_operator(child,stamp,self.base.profile,self.base.sha,self.base.approval)

    def ready(self,child):
        deadline=time.monotonic()+90
        while time.monotonic()<deadline:
            self.assertIsNone(child.poll(),'Owned service exited before readiness')
            try:
                state=service.service_state(self.profile,self.sha,self.base.approval)
                if state['ready']:return state
            except (OSError,ValueError,service.ServiceProcessError):pass
            time.sleep(0.2)
        self.fail('Owned service readiness did not settle; no replacement launched')

    def send(self,options):
        destination=options['destination']
        request=urllib.request.Request(destination['baseUrl']+'v1/project-events/submit',data=json.dumps(event()).encode(),
            headers={'Authorization':'Bearer '+destination['token'],'Content-Type':'application/json'},method='POST')
        with urllib.request.urlopen(request,timeout=10) as response:
            self.assertEqual(response.status,200);return json.load(response)

    def test_relocated_shell_serves_original_enrollment_with_service_only_approval(self):
        self.prepare()
        original = json.loads(self.base.profile.read_bytes())
        artifacts = [self.base.profile] + [Path(original[key]) for key in
                    ('credentialPath','terminalPath','outcomePath','attemptPath')]
        before = [service.digest(path) for path in artifacts]
        runtime_path = self.profile.parent / 'reviewed-service-runtime.json'
        view = json.loads(self.base.profile.read_bytes())
        old_shell = Path(view['runtime']['pwsh'])
        self.assertTrue((old_shell.parent / 'pwsh.dll').is_file())
        relocated = self.profile.parent / 'relocated-shell'
        shutil.copytree(old_shell.parent, relocated)
        new_shell = relocated / old_shell.name
        view['runtime']['pwsh'] = str(new_shell)
        view['sourceHashes'] = {str(p): service.digest(p) for p in operator.source_paths(view['runtime'])}

        def select_view():
            runtime_path.write_text(json.dumps(view), encoding='utf-8')
            self.value.update(schema='onoes-mind-project-service/v2',
                              serviceRuntimeProfilePath=str(runtime_path),
                              serviceRuntimeProfileSha256=service.digest(runtime_path))
            self.write(actions=['run_service'])

        select_view()
        with self.assertRaises(operator.ProjectProcessError):
            operator.checked_profile(runtime_path, service.digest(runtime_path), self.base.approval)
        self.write(actions=['replace','run_service'])
        with patch.object(operator,'checked_profile',side_effect=AssertionError('unapproved runtime inspected')):
            with self.assertRaises(service.ServiceProcessError):
                service.checked_profile(self.profile,self.sha,self.base.approval)
            with self.assertRaises(service.ServiceProcessError):
                service.checked_profile(self.profile,self.sha)
        view['projects'].append(['extra','Other project'])
        select_view()
        with self.assertRaises(service.ServiceProcessError):
            service.checked_profile(self.profile,self.sha,self.base.approval)
        view['projects'].pop()
        view['sourceHashes'][str(new_shell)] = '0'*64
        select_view()
        with self.assertRaises(service.ServiceProcessError):
            service.checked_profile(self.profile,self.sha,self.base.approval)
        self.assertFalse(Path(self.value['attemptPath']).exists())

        view['sourceHashes'][str(new_shell)] = service.digest(new_shell)
        select_view()
        child, stamp = service.launch_service(self.profile,self.sha,self.base.approval)
        self.children.append((child,stamp))
        self.ready(child)
        receipt = self.send(service.native_options(self.profile,self.sha,self.base.approval))
        self.assertTrue(receipt['receiptId'])
        service.request_stop(self.profile,self.sha,self.base.approval)
        self.assertEqual(child.wait(timeout=120),0)
        self.assertEqual([service.digest(path) for path in artifacts],before)

    def test_terminal_operator_then_service_readonly_reload_exact_stop_and_retired_restart(self):
        self.prepare()
        child,stamp=service.launch_service(self.profile,self.sha,self.base.approval);self.children.append((child,stamp))
        first=self.ready(child)
        from onoes_mind import runtime_keys
        with patch.object(runtime_keys,'unprotect_runtime_keys',side_effect=AssertionError('Client reload must not open integrity keys')):
            options=service.native_options(self.profile,self.sha,self.base.approval)
        self.assertEqual(options['peer']['pid'],child.pid);self.assertEqual(options['peer']['creationTicks'],str(stamp))
        token=options['destination']['token']
        self.assertNotIn(token,Path(self.value['readyPath']).read_text())
        self.assertNotIn(token,Path(self.value['attemptPath']).read_text())
        # The live test socket is owned by this exact child. General connection-
        # level peer verification remains a separate Mesh transport gate.
        receipt=self.send(options)
        service.request_stop(self.profile,self.sha,self.base.approval)
        self.assertEqual(child.wait(timeout=120),0)
        self.assertFalse(service.service_state(self.profile,self.sha,self.base.approval)['processLive'])
        with self.assertRaises(service.ServiceProcessError):service.native_options(self.profile,self.sha,self.base.approval)
        replacement,replacement_stamp=service.launch_service(self.profile,self.sha,self.base.approval)
        self.children.append((replacement,replacement_stamp));second=self.ready(replacement)
        self.assertNotEqual(first['runId'],second['runId'])
        self.assertTrue(Path(self.value['attemptPath']+'.retired-'+first['runId']).is_file())
        self.assertTrue(Path(self.value['readyPath']+'.retired-'+first['runId']).is_file())
        self.assertTrue(Path(str(service.stop_target(self.value,first['runId']))+'.retired-'+first['runId']).is_file())
        again=service.native_options(self.profile,self.sha,self.base.approval)
        self.assertEqual(again['destination']['token'],token)
        self.assertEqual(self.send(again)['receiptId'],receipt['receiptId'])
        db=sqlite3.connect(self.base.base.database)
        try:self.assertEqual(db.execute('SELECT count(*) FROM project_sync_events').fetchone()[0],1)
        finally:db.close()
        service.request_stop(self.profile,self.sha,self.base.approval);self.assertEqual(replacement.wait(timeout=120),0)

    def test_preview_missing_terminal_or_action_refuses_without_service_attempt(self):
        preview=subprocess.run([sys.executable,'-I',str(Path(service.__file__).resolve()),'--profile',str(self.profile),'--sha256',self.sha],
            capture_output=True,text=True,timeout=45,creationflags=subprocess.CREATE_NO_WINDOW)
        self.assertEqual(preview.returncode,0,preview.stdout+preview.stderr)
        self.assertTrue(json.loads(preview.stdout)['createsNothing'])
        with self.assertRaises(Exception):service.launch_service(self.profile,self.sha,self.base.approval)
        self.assertFalse(Path(self.value['attemptPath']).exists())
        self.write(actions=['first_setup'])
        with self.assertRaises(service.ServiceProcessError):service.launch_service(self.profile,self.sha,self.base.approval)
        self.assertFalse(Path(self.value['attemptPath']).exists())

    def test_uncertain_service_identity_retains_original_attempt_and_blocks_relaunch(self):
        self.prepare();actual=service.subprocess.Popen;creation=roles.creation_ticks;owned=[]
        def spawn_child(args,*a,**kw):
            child=actual(args,*a,**kw)
            if str(Path(service.__file__).resolve()) in args:owned.append(child)
            return child
        def fail_new_child(handle):
            if any(int(handle)==int(child._handle) for child in owned):
                raise OSError('synthetic new-service identity failure')
            return creation(handle)
        with patch.object(roles,'creation_ticks',side_effect=fail_new_child),\
             patch.object(service.subprocess,'Popen',side_effect=spawn_child) as spawn:
            with self.assertRaises(service.ServiceLaunchUnknown) as caught:
                service.launch_service(self.profile,self.sha,self.base.approval)
            child=caught.exception.child;self.children.append((child,None))
            self.assertEqual(sum(str(Path(service.__file__).resolve()) in c.args[0] for c in spawn.call_args_list),1)
        record=json.loads(Path(self.value['attemptPath']).read_text())
        self.assertEqual(record['pid'],child.pid);self.assertIsNone(record['creationTicks'])
        self.assertEqual(record['state'],'identity_pending');self.assertEqual(child.wait(timeout=120),1)
        with self.assertRaises(service.ServiceProcessError):service.launch_service(self.profile,self.sha,self.base.approval)
        self.assertFalse(Path(self.value['readyPath']).exists())
