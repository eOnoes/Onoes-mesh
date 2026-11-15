"""Operator entry boundaries plus one real native TEMP setup/backup/rehearsal."""
import io
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

import test_operator_setup_candidate as fixtures
import operator_setup_entry as entry


class TerminalInput(io.StringIO):
    def isatty(self):return True


@unittest.skipUnless(sys.platform=='win32','Native Windows key protection')
class OperatorSetupEntryTests(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.OperatorSetupCandidateTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.args=[]
        for key,value in self.fixture.args.items():
            self.args+=['--'+key.replace('_','-'),str(value)]
        self.initialize_args=self.args+['--initialize','--approval-ref','fixture:owner-approved-TEMP-only']

    def empty(self):
        for root in (self.fixture.data,self.fixture.authority,self.fixture.backup):
            self.assertEqual(list(root.iterdir()),[])

    def test_default_preview_creates_nothing_and_never_initializes(self):
        output=io.StringIO()
        with patch.object(entry,'initialize') as initialize:
            self.assertEqual(entry.main(self.args,input_stream=io.StringIO(),output=output),0)
            initialize.assert_not_called()
        plan=json.loads(output.getvalue());self.assertTrue(plan['createsNothing'])
        self.assertFalse(plan['activated']);self.assertTrue(plan['ownerApprovalRequired']);self.empty()

    def test_no_approval_reference_refuses_before_enrollment(self):
        with patch.object(entry,'initialize') as initialize:
            self.assertEqual(entry.main(self.args+['--initialize'],input_stream=TerminalInput(),output=io.StringIO()),1)
            initialize.assert_not_called()
        self.empty()

    def test_noninteractive_initialization_is_refused(self):
        with patch.object(entry,'initialize') as initialize:
            self.assertEqual(entry.main(self.initialize_args,input_stream=io.StringIO('CREATE EMPTY MIND STORE\n'),
                                       output=io.StringIO()),1)
            initialize.assert_not_called()
        self.empty()

    def test_cancel_confirmation_does_not_open_native_enrollment(self):
        with patch.object(entry,'initialize') as initialize:
            self.assertEqual(entry.main(self.initialize_args,input_stream=TerminalInput('\n'),output=io.StringIO()),2)
            initialize.assert_not_called()
        self.empty()

    def test_destination_change_during_confirmation_refuses_and_preserves_marker(self):
        marker=self.fixture.data/'later-file.txt'
        class ChangedInput(TerminalInput):
            def readline(self):
                marker.write_text('preserve this file')
                return 'CREATE EMPTY MIND STORE\n'
        with patch.object(entry,'initialize') as initialize:
            self.assertEqual(entry.main(self.initialize_args,input_stream=ChangedInput(),output=io.StringIO()),1)
            initialize.assert_not_called()
        self.assertEqual(marker.read_text(),'preserve this file')

    def test_exception_text_is_not_echoed_or_retried(self):
        output=io.StringIO()
        with patch.object(entry,'initialize',side_effect=ValueError('fixture-secret-must-not-echo')) as initialize:
            self.assertEqual(entry.main(self.initialize_args,input_stream=TerminalInput('CREATE EMPTY MIND STORE\n'),
                                       output=output),1)
            self.assertEqual(initialize.call_count,1)
        self.assertNotIn('fixture-secret',output.getvalue());self.empty()

    def test_native_complete_journey_through_entry_prints_only_inactive_summary(self):
        output=io.StringIO()
        with patch('onoes_mind.operator_setup.show_recovery_setup',side_effect=self.fixture.native_entry):
            self.assertEqual(entry.main(self.initialize_args,input_stream=TerminalInput('CREATE EMPTY MIND STORE\n'),
                                       output=output),0,output.getvalue())
        receipt=json.loads((self.fixture.data/'checkpointed-initialization-receipt.json').read_text())
        self.assertEqual(receipt['candidateRehearsal'],'PASS');self.assertFalse(receipt['activated'])
        self.assertTrue((self.fixture.backup/'restore-rehearsal.sqlite').is_file())
        self.assertIn('setup_complete_inactive',output.getvalue())
        for value in (self.fixture.password,'recovery_envelope','runtime_envelope','audit_key','deletion_key'):
            self.assertNotIn(value,output.getvalue())

    def test_native_cancellation_returns_no_completion_and_no_files(self):
        output=io.StringIO()
        with patch('onoes_mind.operator_setup.show_recovery_setup',return_value=None):
            self.assertEqual(entry.main(self.initialize_args,input_stream=TerminalInput('CREATE EMPTY MIND STORE\n'),
                                       output=output),2)
        self.assertNotIn('setup_complete_inactive',output.getvalue());self.empty()

    def test_help_subprocess_needs_no_mind_import_or_initialization(self):
        result=subprocess.run([sys.executable,str(Path(entry.__file__)),'--help'],capture_output=True,text=True,
                              creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn('Preview is read-only',result.stdout);self.empty()


if __name__=='__main__':unittest.main()
