"""Early launcher refusals use no ledger, credential, process or service."""
import copy
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import subprocess
import contextlib
import io
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import mesh_launch_candidate as launch


class MeshLaunchRefusalTests(unittest.TestCase):
    def test_laptop_observation_is_an_optional_boolean_in_the_profile(self):
        settings={k:'0' for k in launch.SETTINGS}
        settings.update(MESH_DATA_DIR='data/cards',MESH_RELAY_MODE='http',MESH_GATE_KEY_FILE=str(Path.cwd()/'gate'))
        launch.check_settings(settings)
        for value in ('0','1'):
            launch.check_settings(dict(settings,MESH_TRIPP_HARDWARE=value))
        enrolled=dict(settings,MESH_AI_BOX_WINDOWS_SENSOR_HOST='PRINT-HOST')
        launch.check_settings(enrolled)
        launch.check_settings(dict(enrolled,MESH_TRIPP_HARDWARE='1'))
        self.assertEqual(launch.source_paths(settings=enrolled)-launch.source_paths(),
                         {launch.ROOT/'config/nodes.json',launch.ROOT/'integrations/tripp-hardware.ps1'})
        for extra in ({'MESH_TRIPP_HARDWARE':'yes'}, {'MESH_TRIPP_HARDWARE':1}, {'MESH_TRIPP_HOST':'other'},
                      {'MESH_AI_BOX_WINDOWS_SENSOR_HOST':''}, {'MESH_AI_BOX_WINDOWS_SENSOR_HOST':'not a host'}):
            with self.subTest(extra=extra), self.assertRaises(launch.LaunchError):
                launch.check_settings(dict(settings,**extra))
        with self.assertRaises(launch.LaunchError):
            launch.check_settings({k:v for k,v in settings.items() if k!='MESH_SIMPLE_FLOW'})

    def test_connected_worker_profile_requires_both_settings_and_the_pinned_bridge(self):
        settings={k:'0' for k in launch.SETTINGS}
        settings.update(MESH_DATA_DIR='data/cards',MESH_RELAY='1',MESH_RELAY_MODE='http',
                        MESH_NIMS='1',MESH_GATE_KEY_FILE=str(launch.ROOT/'gate'))
        record='MESH_NATIVE_WORKER_RECORD'
        sha='MESH_NATIVE_WORKER_RECORD_SHA256'
        approved={**settings,record:str(launch.ROOT/'worker-record.json'),sha:'a'*64}
        launch.check_settings(approved,allow_native_worker=True)
        self.assertEqual(launch.source_paths(project=True,settings=approved)-launch.source_paths(project=True),
                         {launch.ROOT/'integrations/native_gateway_transport.py'})
        with self.assertRaises(launch.LaunchError):
            launch.check_settings(approved)
        for changed in ({record:'relative.json'}, {sha:'A'*64}, {'MESH_RELAY':'0'},
                        {'MESH_RELAY_MODE':'child'}, {'MESH_SIMPLE_FLOW':'1'}, {'MESH_NIMS':'0'}):
            with self.subTest(changed=changed), self.assertRaises(launch.LaunchError):
                launch.check_settings({**approved,**changed},allow_native_worker=True)
        for key in (record,sha):
            with self.subTest(missing=key), self.assertRaises(launch.LaunchError):
                launch.check_settings({k:v for k,v in approved.items() if k!=key},allow_native_worker=True)

    def test_worker_preflight_reads_the_exact_record_without_starting_the_bridge(self):
        with tempfile.TemporaryDirectory(prefix='mesh-worker-launch-') as directory:
            runtime=Path(directory).resolve()
            record=runtime/'record.json'
            python=runtime/'unexecutable-python-fixture'
            python.write_bytes(b'The transport must not execute this file.')
            data={'schema':'mesh-native-worker-enrollment/v1',
                  'profile':{'profileRef':'fixture','identityRef':'fixture-echo','provider':'openai-codex',
                             'model':'gpt-6-luna','workspace':str(launch.ROOT),'toolProfile':'build-check-v1'},
                  'runtime':{'home':str(runtime),'nativeRoot':str(runtime),'pythonExecutable':str(python)}}
            record.write_text(json.dumps(data),encoding='utf-8')
            settings={'MESH_RELAY':'1','MESH_RELAY_MODE':'http','MESH_SIMPLE_FLOW':'0',
                      'MESH_NATIVE_WORKER_RECORD':str(record),'MESH_NATIVE_WORKER_RECORD_SHA256':launch.digest(record)}
            profile={'settings':settings,'nodeExecutable':shutil.which('node')}
            checks=[]
            def qualify(path, *, kind):
                checks.append((path,kind))
            with patch.dict(os.environ,{'MESH_STANDALONE':'1','MESH_NATIVE_WORKER_RECORD':'ambient-value',
                                        'NODE_OPTIONS':'--require=unavailable-module'}):
                launch.check_native_worker(profile,qualify)
            self.assertEqual(checks,[(record,'file')])
            outside=runtime/'outside-workspace'
            outside.mkdir()
            data['profile']['workspace']=str(outside)
            record.write_text(json.dumps(data),encoding='utf-8')
            with self.assertRaises(launch.LaunchError):
                launch.check_native_worker(profile,qualify)
            settings['MESH_NATIVE_WORKER_RECORD_SHA256']=launch.digest(record)
            with self.assertRaises(launch.LaunchError):
                launch.check_native_worker(profile,qualify)
            self.assertEqual(launch.approved_environment({'MESH_RELAY':'1'})['MESH_RELAY'],'1')

    def test_preflight_authentication_failure_refuses_before_stop_without_echoing_details(self):
        with tempfile.TemporaryDirectory(prefix='mesh-preflight-auth-') as directory:
            root=Path(directory)
            p={n:str(root/n) for n in ('attemptPath','stdoutPath','stderrPath','readerProfile')}
            p['readerProfileSha256']='synthetic'
            fake=SimpleNamespace(native_options=lambda *args:(_ for _ in ()).throw(RuntimeError('synthetic-secret-marker')))
            output=io.StringIO()
            with patch.object(launch,'checked_launch',return_value=(p,fake)),patch.object(sys,'argv',
                ['launcher','--profile','unused','--sha256','unused','--approval','unused']),contextlib.redirect_stdout(output):
                self.assertEqual(launch.main(),1)
            self.assertFalse(json.loads(output.getvalue())['ready'])
            self.assertNotIn('synthetic-secret-marker',output.getvalue())
            self.assertFalse(Path(p['attemptPath']).exists())

    @unittest.skipUnless(sys.platform=='win32','Windows test-owned launch handle')
    def test_uncertain_identity_keeps_original_child_and_durable_pid_without_delivering_input(self):
        import recall_process_candidate as roles
        with tempfile.TemporaryDirectory(prefix='mesh-launch-uncertain-') as directory:
            root=Path(directory)
            p=dict(nodeExecutable=shutil.which('node'),settings={'MESH_PREVIEW_PORT':'0'},
                attemptPath=str(root/'attempt'),stdoutPath=str(root/'out'),stderrPath=str(root/'err'),
                readerProfile='synthetic-reader',readerProfileSha256='synthetic-reader-hash')
            fake=SimpleNamespace(new_role_file=lambda path:Path(path),native_options=lambda *args:{'token':'synthetic-not-delivered'},
                creation_ticks=lambda handle:(_ for _ in ()).throw(RuntimeError('synthetic observation error')),
                RoleLaunchUnknown=roles.RoleLaunchUnknown)
            actual=launch.subprocess.Popen
            with patch.dict(os.environ,{'MESH_TRIPP_HARDWARE':'1'}),patch.object(launch,'checked_launch',return_value=(p,fake)),patch.object(launch.subprocess,'Popen',wraps=actual) as spawn:
                with self.assertRaises(roles.RoleLaunchUnknown) as caught:launch.launch_mesh('unused','synthetic-profile','unused')
                child=caught.exception.child
                try:
                    self.assertEqual(spawn.call_count,1);self.assertIsNone(caught.exception.creation_ticks)
                    self.assertNotIn('MESH_TRIPP_HARDWARE',spawn.call_args.kwargs['env'])
                    record=json.loads((root/'attempt').read_text());self.assertEqual(record['pid'],child.pid)
                    self.assertEqual(record['state'],'identity_pending');self.assertNotIn('synthetic-not-delivered',json.dumps(record))
                    # Closing the undelivered pipe lets the fixed entry refuse;
                    # no replacement child, port/name kill or retry is performed.
                    self.assertEqual(child.wait(timeout=15),1)
                finally:
                    if child.poll() is None:child.terminate();child.wait(timeout=15)

    def test_powershell_parses_and_all_native_preflight_checks_precede_any_stop(self):
        target=str(launch.ROOT/'integrations/restart-workroom-preview.ps1').replace("'","''")
        script="$target='"+target+"';"+r'''
        $tokens=$null;$errors=$null
        $ast=[System.Management.Automation.Language.Parser]::ParseFile($target,[ref]$tokens,[ref]$errors)
        if($errors.Count){throw 'Launcher syntax error'}
        $stops=@($ast.FindAll({param($n) $n -is [System.Management.Automation.Language.CommandAst] -and $n.GetCommandName() -eq 'Stop-Process'},$true))
        $checks=@($ast.FindAll({param($n) $n -is [System.Management.Automation.Language.IfStatementAst] -and $n.Clauses[0].Item1.Extent.Text -eq '$nativeMindRequested'},$true))
        if($stops.Count -ne 1 -or $checks.Count -ne 2){throw 'Unexpected launcher control structure'}
        if($checks[0].Extent.EndOffset -ge $stops[0].Extent.StartOffset){throw 'Preflight must complete before stopping Mesh'}
        if($checks[0].Extent.Text -notmatch '--approval' -or $checks[0].Extent.Text -match '--launch'){throw 'Preflight must check approval without starting a child'}
        if($checks[1].Extent.Text -notmatch '--launch' -or $checks[1].Extent.Text -notmatch 'ToFileTimeUtc'){throw 'Launch must confirm the returned process creation identity'}
        'PASS: parsed launcher; native preflight before stop; exact process identity after launch'
        '''
        result=subprocess.run([shutil.which('pwsh'),'-NoLogo','-NoProfile','-NonInteractive','-Command',script],
            capture_output=True,text=True,timeout=20,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertIn('PASS:',result.stdout)

    def test_changed_or_widened_source_profile_runtime_and_reader_cannot_start_a_child(self):
        with tempfile.TemporaryDirectory(prefix='mesh-launch-refusal-') as directory:
            root=Path(directory);reader=root/'reader.json';reader.write_text('{}')
            node=Path(shutil.which('node')).resolve()
            p=dict(schema='onoes-mesh-native-launch/v1',workspace=str(launch.ROOT),
                pythonExecutable=sys.executable,nodeExecutable=str(node),
                pythonSha256=launch.digest(sys.executable),nodeSha256=launch.digest(node),
                sourceHashes={str(n):launch.digest(n) for n in launch.source_paths()},
                readerProfile=str(reader),readerProfileSha256=launch.digest(reader),
                settings={},attemptPath=str(root/'attempt.json'),stdoutPath=str(root/'out'),stderrPath=str(root/'err'))
            variants=[]
            for key,value in [('extra',True),('workspace',str(root)),('pythonSha256','0'*64),
                              ('nodeSha256','0'*64),('readerProfileSha256','0'*64)]:
                q=copy.deepcopy(p);q[key]=value;variants.append(q)
            q=copy.deepcopy(p);q['sourceHashes'][str(launch.ROOT/'serve.mjs')]='0'*64;variants.append(q)
            q=copy.deepcopy(p);q['sourceHashes'].pop(str(launch.ROOT/'serve.mjs'));variants.append(q)
            profile=root/'launch.json'
            with patch.object(launch.subprocess,'Popen',side_effect=AssertionError('No child is allowed')) as spawn:
                for q in variants:
                    profile.write_text(json.dumps(q))
                    with self.subTest(changed=set(q)^set(p)):
                        with self.assertRaises(launch.LaunchError):launch.launch_mesh(profile,launch.digest(profile),root/'not-an-approval')
                    self.assertFalse((root/'attempt.json').exists())
                profile.write_text(json.dumps(p))
                with self.assertRaises(launch.LaunchError):launch.launch_mesh(profile,'0'*64,root/'not-an-approval')
                profile.write_text('{"schema":"first","schema":"duplicate"}')
                with self.assertRaises(launch.LaunchError):launch.launch_mesh(profile,launch.digest(profile),root/'not-an-approval')
                spawn.assert_not_called()


if __name__=='__main__':unittest.main()
