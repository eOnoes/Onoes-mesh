"""Actual Windows custody + actual native Mesh factory/read-only reader, TEMP only."""
from dataclasses import replace
import json
from pathlib import Path
import shutil
import socket
import sqlite3
import subprocess
import sys
import unittest
from unittest.mock import patch

from onoes_mind.ledger import Ledger
from onoes_mind.recall_binding import (RecallBinding, prepare_store_identity,
    prepare_mesh_principal, issue_mesh_recall_credential)
import native_recall_candidate as native
import test_operator_setup_candidate as fixtures


NODE = """
import {pathToFileURL} from 'node:url';
const {configureMindRecall}=await import(pathToFileURL(process.argv[1]));
let input='';for await(const chunk of process.stdin)input+=chunk;
try {const setup=configureMindRecall({standalone:false,approvedOptions:JSON.parse(input)});
 const result=await setup.client.recall({query:'sentinel',limit:8});
 console.log(JSON.stringify({ok:true,source:setup.source,result}));
}catch{console.log(JSON.stringify({ok:false}));}
"""


@unittest.skipUnless(sys.platform=='win32','Native Windows current-user custody')
class NativeRecallTests(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.OperatorSetupCandidateTests();self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.path=(self.fixture.data/'reader-fixture.sqlite').resolve()
        self.writer=Ledger(self.path);self.addCleanup(self.writer.close)
        for principal in ('operator','echo'):
            self.writer.create_principal(principal)
            self.writer.issue_credential(principal,principal+'-synthetic-token')
        store=prepare_store_identity(self.writer,environment='synthetic',authority_ref='fixture:owner')
        prepare_mesh_principal(self.writer,scope_id=native.SCOPE)
        self.token=issue_mesh_recall_credential(self.writer,token='fixture-mesh-read-only-token')
        stat=self.path.stat()
        self.binding=RecallBinding(str(self.path),store,'synthetic','fixture:owner',native.SCOPE,
            stat.st_dev,stat.st_ino,'fixture:custodian','fixture:revoke','fixture:review')
        self.credential=self.fixture.authority/'mesh-recall.json'
        self.host=native.NativeRecallHost(binding=self.binding,credential_path=self.credential)
        self.addCleanup(self.host.close)

    def seal(self):
        return native.seal_service_credential(self.credential,self.token,binding=self.binding)

    def call_node(self,options):
        result=subprocess.run([shutil.which('node'),'--input-type=module','-e',NODE,
            str(Path(__file__).resolve().parents[2]/'lib/mind-recall.mjs')],
            input=json.dumps(options),text=True,capture_output=True,timeout=15,
            creationflags=subprocess.CREATE_NO_WINDOW)
        self.assertEqual(result.returncode,0,result.stderr)
        return json.loads(result.stdout)

    def test_real_current_user_dpapi_roundtrip_never_persists_plaintext(self):
        receipt=self.seal();self.assertTrue(receipt['protected'])
        self.assertNotIn(self.token.encode(),self.credential.read_bytes())
        self.assertNotIn(self.token,json.dumps(receipt))
        self.assertEqual(native.load_service_credential(self.credential,binding=self.binding),self.token)

    def test_store_environment_inode_scope_and_review_context_cannot_be_swapped(self):
        self.seal();before=self.credential.read_bytes()
        for changes in ({'store_id':'00000000-0000-4000-8000-000000000001'},
                        {'environment':'other'},{'file_inode':self.binding.file_inode+1},
                        {'scope_id':'project/other/shared'},{'review_ref':'fixture:another-review'}):
            with self.assertRaises(native.NativeRecallError):
                native.load_service_credential(self.credential,binding=replace(self.binding,**changes))
        self.assertEqual(self.credential.read_bytes(),before)

    def test_tamper_is_refused_without_native_exception_or_token_echo(self):
        self.seal();envelope=json.loads(self.credential.read_text())
        encrypted=envelope['ciphertext'];envelope['ciphertext']=('A' if encrypted[0]!='A' else 'B')+encrypted[1:]
        self.credential.write_text(json.dumps(envelope));attempt=self.credential.read_bytes()
        with self.assertRaises(native.NativeRecallError) as failure:
            native.load_service_credential(self.credential,binding=self.binding)
        self.assertNotIn(self.token,str(failure.exception));self.assertEqual(self.credential.read_bytes(),attempt)

    def test_existing_file_is_preserved_and_weak_folder_never_calls_crypto(self):
        self.credential.write_bytes(b'preserve synthetic existing file')
        with patch.object(native,'_crypt') as crypt:
            with self.assertRaises(native.NativeRecallError):self.seal()
            crypt.assert_not_called()
        self.assertEqual(self.credential.read_bytes(),b'preserve synthetic existing file')
        weak=self.fixture.root/'weak-default-inheritance';weak.mkdir()
        with patch.object(native,'_crypt') as crypt:
            with self.assertRaises(native.NativeRecallError):
                native.seal_service_credential(weak/'refused.json',self.token,binding=self.binding)
            crypt.assert_not_called()
        self.assertEqual(list(weak.iterdir()),[])

    def test_ordinary_writer_token_cannot_be_sealed_as_mesh_recall(self):
        with self.assertRaises(native.NativeRecallError):
            native.seal_service_credential(self.credential,'echo-synthetic-token',binding=self.binding)
        self.assertFalse(self.credential.exists())

    def test_actual_native_options_feed_mesh_factory_and_owned_close_releases_resources(self):
        self.seal()
        self.writer.remember('operator-synthetic-token',dict(event_id='fixture-shared',kind='project_fact',
            project_id='fixture',claim='sentinel native shared fact',requested_visibility='shared',
            evidence_refs=[dict(type='fixture',ref='fixture:shared',content_hash='a'*64)]))
        status=self.host.start();self.assertTrue(status['readOnly']);self.assertTrue(status['running'])
        self.assertNotIn(self.token,json.dumps(status))
        result=self.call_node(self.host.native_options());self.assertTrue(result['ok'])
        self.assertEqual(result['source'],'canonical_ledger')
        self.assertEqual([r['claim'] for r in result['result']['records']],['sentinel native shared fact'])
        address=self.host._server.address;reader=self.host._reader
        self.host.close();self.assertFalse(self.host.status()['running']);self.host.close()
        with self.assertRaises(sqlite3.ProgrammingError):reader.db.execute('SELECT 1')
        with socket.socket() as probe:self.assertNotEqual(probe.connect_ex(address),0)
        with self.assertRaises(native.NativeRecallError):self.host.native_options()

    def test_revoked_token_is_refused_by_running_reader_and_no_new_native_options_exported(self):
        self.seal();self.host.start();options=self.host.native_options()
        self.assertTrue(self.call_node(options)['ok'])
        self.writer.rotate_credentials('mesh-recall')
        self.assertFalse(self.call_node(options)['ok'])
        with self.assertRaises(native.NativeRecallError):self.host.native_options()
        self.assertTrue(self.host.status()['running'])  # Running listener is not an authorization claim.

    def test_bad_credential_never_constructs_a_server_and_errors_are_fixed(self):
        self.seal()
        with patch.object(native,'_crypt',side_effect=ValueError('fixture-secret-native-error')), \
             patch.object(native,'RecallServer') as server:
            with self.assertRaises(native.NativeRecallError) as failure:self.host.start()
            server.assert_not_called()
        self.assertNotIn('fixture-secret',str(failure.exception));self.assertFalse(self.host.status()['running'])
        self.assertTrue(self.credential.is_file())

    def test_duplicate_json_fields_are_refused_before_decrypt(self):
        self.credential.write_text('{"schema":"first","schema":"second"}')
        with patch.object(native,'_crypt') as crypt:
            with self.assertRaises(native.NativeRecallError):
                native.load_service_credential(self.credential,binding=self.binding)
            crypt.assert_not_called()


if __name__=='__main__':unittest.main()
