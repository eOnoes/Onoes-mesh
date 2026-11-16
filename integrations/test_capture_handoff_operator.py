"""Operator command dispatch must preserve approvals, pause and unknown state."""
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, Mock, patch

import mesh_recovery_candidate as recovery


class OperatorTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name).resolve();self.addCleanup(patch.stopall)
        patch.object(recovery,'ROOT',self.root).start()
        self.roles=object();self.launch=SimpleNamespace(checked_launch=Mock(return_value=({},self.roles)))
        self.service=object();self.window=object();self.context=MagicMock()
        self.context.__enter__.return_value=self.window
        self.make_window=Mock(return_value=self.context)
        self.approved={'capture':{'profilePath':'capture-profile','profileSha256':'c'*64,'approvalPath':'capture-approval'},
            'sourceHashes':{str(self.root/'integrations/restart-workroom-preview.ps1'):'pinned-launcher'}}
        self.check=patch.object(recovery,'checked_handoff_approval',return_value=self.approved).start()
        patch.dict(sys.modules,{'mesh_launch_candidate':self.launch,'project_service_process_candidate':self.service,
            'mesh_launcher_window':SimpleNamespace(MeshLauncherWindow=self.make_window)}).start()
        self.handoff=patch.object(recovery,'handoff_capture_to_connected',return_value=({'state':'connected','pid':123},object())).start()
        self.argv=['--handoff-capture-to-connected','--handoff-approval','private-approval','--handoff-sha256','a'*64]

    def call(self):
        output=io.StringIO()
        with redirect_stdout(output):code=recovery.handoff_main(self.argv)
        return code,json.loads(output.getvalue())

    def test_exact_command_executes_under_same_launcher_window(self):
        code,result=self.call();self.assertEqual(code,0);self.assertEqual(result['state'],'connected')
        self.handoff.assert_called_once_with(self.window,launch=self.launch,service=self.service,roles=self.roles,
            approval_path='private-approval',approval_sha='a'*64)
        self.context.__exit__.assert_called_once()

    def test_pause_does_not_attempt_handoff(self):
        sentinel=self.root/'data/workroom-preview/recovery-paused';sentinel.parent.mkdir(parents=True);sentinel.touch()
        code,result=self.call();self.assertEqual(code,0);self.assertEqual(result['state'],'paused')
        self.handoff.assert_not_called()

    def test_failed_approval_never_loads_capture_or_opens_window(self):
        self.check.side_effect=RuntimeError('PRIVATE-DETAIL-DO-NOT-EXPOSE')
        code,result=self.call();self.assertEqual(code,1);self.assertEqual(result['state'],'held')
        self.assertNotIn('PRIVATE-DETAIL',json.dumps(result));self.launch.checked_launch.assert_not_called()
        self.make_window.assert_not_called();self.handoff.assert_not_called()

    def test_unknown_attempt_is_reported_held_without_fallback_or_second_send(self):
        pair=SimpleNamespace(mesh=object());self.handoff.side_effect=recovery.CaptureHandoffUnknown(pair)
        code,result=self.call();self.assertEqual(code,1);self.assertEqual(result['state'],'held')
        self.assertIn('do not relaunch',result['message']);self.handoff.assert_called_once()

    def test_duplicate_or_mixed_commands_cannot_reach_approval(self):
        self.argv+=['--handoff-capture-to-connected']
        code,result=self.call();self.assertEqual(code,1);self.assertEqual(result['state'],'held')
        self.check.assert_not_called();self.handoff.assert_not_called()

    def test_real_isolated_cli_refuses_missing_approval_before_any_participant(self):
        script=Path(recovery.__file__).resolve()
        run=subprocess.run([sys.executable,'-I',str(script),'--handoff-capture-to-connected',
            '--handoff-approval',str(self.root/'missing.json'),'--handoff-sha256','0'*64],
            capture_output=True,text=True,timeout=15,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        self.assertEqual(run.returncode,1);self.assertEqual(json.loads(run.stdout)['state'],'held')
        self.assertNotIn('Traceback',run.stderr);self.assertFalse((self.root/'missing.json').exists())


if __name__=='__main__':unittest.main()
