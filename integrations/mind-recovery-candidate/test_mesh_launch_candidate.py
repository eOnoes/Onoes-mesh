"""Early launcher refusals use no ledger, credential, process or service."""
import copy
import json
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
            with patch.object(launch,'checked_launch',return_value=(p,fake)),patch.object(launch.subprocess,'Popen',wraps=actual) as spawn:
                with self.assertRaises(roles.RoleLaunchUnknown) as caught:launch.launch_mesh('unused','synthetic-profile','unused')
                child=caught.exception.child
                try:
                    self.assertEqual(spawn.call_count,1);self.assertIsNone(caught.exception.creation_ticks)
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
