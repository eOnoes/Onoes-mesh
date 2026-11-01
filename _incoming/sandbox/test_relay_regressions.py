"""Isolated regression contracts. No native calls or owner-store writes."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
import relay_chat
import relay_store
import relay_decisions
import relay_turn_meta

ROOM = 'relay-eddie-echo-regression'

class RecoveryRegressionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = relay_store.RelayStore(Path(self.tmp.name)/'state.db')
        self.decisions = relay_decisions.DecisionStore(Mock(), store=self.store)
        self.addCleanup(patch.stopall)
        patch.object(relay_chat, 'STORE', self.store).start()
        patch.object(relay_chat, 'DECISIONS', self.decisions).start()
    def record(self, rid, state='running'):
        self.decisions.associate_run(ROOM,rid)
        self.decisions.begin(rid)
        self.store.update_run_state(rid,state)
    def test_completed_memory_run_does_not_recover(self):
        self.record('run_finished','completed')
        self.assertNotEqual(self.decisions.run_snapshot('run_finished')['state'],'completed')
        state = relay_chat.decision_snapshot(ROOM)
        self.assertEqual(state['state'],'idle')
        self.assertEqual(state['run_id'],'')
    def test_all_terminal_states_are_idle(self):
        for terminal in ('completed','failed','cancelled','interrupted','expired','unavailable'):
            self.record('run_'+terminal,terminal)
        self.assertEqual(relay_chat.decision_snapshot(ROOM)['state'],'idle')
    def test_durable_active_run_beats_stale_memory_selection(self):
        self.record('run_new_active')
        self.record('run_old_finished','completed')
        self.assertEqual(self.decisions.selected_run(ROOM),'run_old_finished')
        state = relay_chat.decision_snapshot(ROOM)
        self.assertEqual(state['run_id'],'run_new_active')
        self.assertEqual(state['state'],'running')
    def test_pending_approval_remains_recoverable(self):
        self.record('run_approval')
        self.decisions.accept_event({'event':'approval.request','run_id':'run_approval',
            'request_id':'req_regression','command':'synthetic display only',
            'choices':['once','deny']})
        state = relay_chat.decision_snapshot(ROOM)
        self.assertEqual(state['state'],'decision_blocked')
        self.assertEqual(state['pending'][0]['request_id'],'req_regression')
    def test_terminal_pump_without_output_uses_native_completion(self):
        self.record('run_empty_pump')
        driver=Mock()
        driver.snapshot.return_value={'status':'completed','output':''}
        with patch.object(relay_chat,'runners',return_value=driver), patch.object(relay_chat,'_call',return_value=(200,{'status':'completed','output':'REAL-OUTPUT'})) as native:
            result=relay_chat.status('run_empty_pump',session_id=ROOM)
        native.assert_called_once()
        self.assertEqual(result['output'],'REAL-OUTPUT')
        self.assertTrue(result['done'])
        self.assertEqual(relay_chat.decision_snapshot(ROOM)['state'],'idle')

class PhotoStatusRegressionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = relay_store.RelayStore(Path(self.tmp.name)/'state.db')
        self.addCleanup(patch.stopall)
        patch.object(relay_chat, 'STORE', self.store).start()
    def test_empty_session_chat_result_is_completed_no_reply_text(self):
        run_id='relay_empty_result_000000000000000000000000'
        relay_turn_meta.save(self.store,run_id,ROOM,'caption','caption',files=['file_one'],output='')
        self.store.begin_run(run_id,ROOM)
        state=relay_chat.status(run_id,session_id=ROOM)
        self.assertTrue(state['done'])
        self.assertEqual(state['status'],'completed')
        self.assertEqual(state['output'],'')
        self.assertEqual(state['error'],'')
    def test_missing_session_chat_result_is_unknown_not_failed(self):
        run_id='relay_missing_result_000000000000000000000000'
        self.store.begin_run(run_id,ROOM)
        state=relay_chat.status(run_id,session_id=ROOM)
        self.assertFalse(state['done'])
        self.assertEqual(state['status'],'unknown')

if __name__ == '__main__': unittest.main()
