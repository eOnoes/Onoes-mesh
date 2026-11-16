"""Native attempt compatibility, secret exclusion and service identity binding."""
import copy
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest

from mesh_native_recovery import valid_memory_peers, identified_native_attempt
sys.path.insert(0,str(Path(__file__).resolve().parent/'mind-recovery-candidate'))
import mesh_launch_candidate as launch


class NativePeerTests(unittest.TestCase):
    def setUp(self):
        self.reader=dict(ready=True,pid=100,creationTicks=1000,baseUrl='http://127.0.0.1:45001/')
        self.roles=SimpleNamespace(reader_state=lambda *args:self.reader)
        self.p=dict(readerProfile='reader',readerProfileSha256='a'*64,
                    projectSync=dict(serviceProfileSha256='b'*64))
        self.options=dict(mindRecallOptions=dict(baseUrl=self.reader['baseUrl'],token='synthetic-reader-secret'),
            projectSyncOptions=dict(destination=dict(token='synthetic-writer-secret',peer=dict(
                pid=200,creationTicks='2000',profileSha256='b'*64,runId='1'*32))))
        self.record=dict(schema='onoes-mesh-native-child/v1',profileSha256='c'*64,pid=300,
            creationTicks=3000,state='input_sent',credentialsInRecord=False,executable='fixed-node',entryPoint='fixed-entry')

    def peers(self):return launch.native_peers(self.p,self.roles,'approved-reader',self.options)

    def test_peer_snapshot_excludes_all_secrets_and_normalizes_birth_ticks(self):
        before=copy.deepcopy(self.options);peers=self.peers()
        self.assertTrue(valid_memory_peers(peers));self.assertEqual(peers['writer']['creationTicks'],2000)
        self.assertNotIn('synthetic-reader-secret',json.dumps(peers))
        self.assertNotIn('synthetic-writer-secret',json.dumps(peers));self.assertEqual(self.options,before)

    def test_both_delivered_attempt_versions_are_supported(self):
        self.assertTrue(identified_native_attempt(self.record))
        self.record.update(schema='onoes-mesh-native-child/v2',peers=self.peers())
        self.assertTrue(identified_native_attempt(self.record))

    def test_unknown_peer_fields_or_missing_peers_are_not_accepted(self):
        self.record['schema']='onoes-mesh-native-child/v2'
        self.assertFalse(identified_native_attempt(self.record))
        self.record['peers']=self.peers();self.record['peers']['reader']['token']='must-not-be-recorded'
        self.assertFalse(identified_native_attempt(self.record))
        self.record.update(schema='onoes-mesh-native-child/v1',peers=self.peers())
        self.assertFalse(identified_native_attempt(self.record))

    def test_unknown_input_is_held_in_both_versions(self):
        for version in (1,2):
            record=copy.deepcopy(self.record);record['schema']=f'onoes-mesh-native-child/v{version}'
            if version==2:record['peers']=self.peers()
            record['state']='input_pending';self.assertFalse(identified_native_attempt(record))

    def test_unready_or_different_reader_endpoint_cannot_be_recorded(self):
        self.reader['ready']=False
        with self.assertRaises(launch.LaunchError):self.peers()
        self.reader['ready']=True;self.reader['baseUrl']='http://127.0.0.1:45002/'
        with self.assertRaises(launch.LaunchError):self.peers()

    def test_writer_identity_must_belong_to_the_selected_profile(self):
        self.options['projectSyncOptions']['destination']['peer']['profileSha256']='d'*64
        with self.assertRaises(launch.LaunchError):self.peers()

    def test_invalid_or_boolean_identifiers_cannot_select_a_process(self):
        for name,value in (('pid',True),('pid',0),('pid',2**32),('creationTicks',True),
                           ('creationTicks',0),('creationTicks',2**64),('profileSha256','other')):
            peer=self.peers();peer['reader'][name]=value
            with self.subTest(field=name,value=value):self.assertFalse(valid_memory_peers(peer))


if __name__=='__main__':unittest.main()
