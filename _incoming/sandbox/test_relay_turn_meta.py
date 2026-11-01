import tempfile
import unittest
from pathlib import Path
import relay_store
import relay_turn_meta as meta

class TurnMetaTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = relay_store.RelayStore(Path(self.tmp.name)/'state.db')
    def tearDown(self):
        self.tmp.cleanup()
    def test_paper_reply_and_files_survive_reopen(self):
        meta.save(self.store,'run_one','relay-test','full input','note','paper',{'id':'msg-old','who':'Echo','text':'previous'},['file_one'])
        other = relay_store.RelayStore(self.store.path)
        turn = meta.decorate(other,'relay-test',[{'who':'Eddie','text':'full input'}])[0]
        self.assertEqual(turn['paper'],'paper')
        self.assertEqual(turn['reply']['id'],'msg-old')
        self.assertEqual(turn['files'],['file_one'])
        self.assertEqual(turn['id'],'msg-u-run_one')
    def test_metadata_is_room_scoped(self):
        meta.save(self.store,'run_one','relay-test','same','note','private')
        turn = meta.decorate(self.store,'relay-other',[{'who':'Eddie','text':'same'}])[0]
        self.assertNotIn('paper',turn)
    def test_local_photo_result_survives_reopen(self):
        meta.save(self.store,'relay_local','relay-test','photo','photo',output='visible pixels')
        self.assertEqual(meta.local_result(relay_store.RelayStore(self.store.path),'relay_local'),'visible pixels')
    def test_screenshot_marker_restores_photo(self):
        meta.save(self.store,'relay_local','relay-test','caption','caption',files=['file_one'])
        turn = meta.decorate(self.store,'relay-test',[{'who':'Eddie','text':'caption\n[screenshot]'}])[0]
        self.assertEqual(turn['files'],['file_one'])
    def test_reply_requires_stable_identifier(self):
        with self.assertRaises(ValueError):
            meta.save(self.store,'run_one','relay-test','input','note',reply={'text':'missing id'})
    def test_output_updates_and_decorates_reply_target(self):
        meta.save(self.store,'run_one','relay-test','input','note')
        meta.set_output(self.store,'run_one','reply')
        turn = meta.decorate(self.store,'relay-test',[{'who':'Echo','text':'reply'}])[0]
        self.assertEqual(turn['id'],'msg-a-run_one')

if __name__ == '__main__': unittest.main()
