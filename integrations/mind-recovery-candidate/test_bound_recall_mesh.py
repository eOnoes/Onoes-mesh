"""Actual Mesh JS client -> canonical bound reader, synthetic TEMP store only.

Run explicitly with the reviewed canonical Mind package on PYTHONPATH. This is
not a production launcher, credential installer, correction API or writer-host
qualification. No live paths/defaults, external URLs or real credentials occur.
"""
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import subprocess
import tempfile
import unittest

from onoes_mind.ledger import Ledger, _payload_hash
from onoes_mind.recall_binding import (RecallBinding, BoundRecallLedger,
    prepare_store_identity, prepare_mesh_principal, issue_mesh_recall_credential)
from onoes_mind.recall_http import RecallServer


NODE_CLIENT = """
import {pathToFileURL} from 'node:url';
const {createMindRecallClient}=await import(pathToFileURL(process.argv[1]));
let text='';for await(const chunk of process.stdin)text+=chunk;
const fixture=JSON.parse(text);let requests=0;
try {
 const client=createMindRecallClient({baseUrl:fixture.baseUrl,token:fixture.token,
  fetchImpl:async(url,options)=>{
   if(String(url)!==new URL('/v1/recall',fixture.baseUrl).href)throw Error('Fixture transport refused');
   requests++;return fetch(url,options);
  }});
 const result=await client.recall(fixture.input);
 console.log(JSON.stringify({ok:true,requests,result}));
}catch(error){console.log(JSON.stringify({ok:false,requests,message:error.message}));}
"""


class BoundRecallMeshTests(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory(prefix='mind-mesh-bound-fixture-')
        self.addCleanup(self.folder.cleanup)
        self.path=(Path(self.folder.name)/'synthetic.sqlite').resolve()
        self.writer=Ledger(self.path);self.addCleanup(self.writer.close)
        for principal in ('operator','echo'):
            self.writer.create_principal(principal)
            self.writer.issue_credential(principal,principal+'-synthetic-token')
        store_id=prepare_store_identity(self.writer,environment='synthetic',authority_ref='fixture:owner')
        prepare_mesh_principal(self.writer,scope_id='project/onoes-mind/shared')
        self.token=issue_mesh_recall_credential(self.writer,token='mesh-synthetic-token')
        stat=self.path.stat()
        self.binding=RecallBinding(str(self.path),store_id,'synthetic','fixture:owner',
            'project/onoes-mind/shared',stat.st_dev,stat.st_ino,'fixture:custodian',
            'fixture:revoke','fixture:review')
        self.reader=BoundRecallLedger(self.path,binding=self.binding)
        self.addCleanup(self.reader.close)
        self.bridge=RecallServer(self.reader);self.bridge.start();self.addCleanup(self.bridge.close)
        host,port=self.bridge.address
        self.base_url=f'http://{host}:{port}/'
        self.client=Path(__file__).resolve().parents[2]/'lib/mind-recall.mjs'
        self.node=shutil.which('node')
        self.assertIsNotNone(self.node,'Explicit qualification requires Node.')

    def remember(self,event,*,principal='operator',shared=True):
        return self.writer.remember(principal+'-synthetic-token',dict(
            event_id=event,kind='project_fact',project_id='fixture',claim='sentinel '+event,
            requested_visibility='shared' if shared else 'private',
            evidence_refs=[dict(type='fixture',ref='fixture:'+event,content_hash='a'*64)]))

    def call(self,query='sentinel',*,token=None,extra=None):
        body=dict(query=query,limit=8);body.update(extra or {})
        result=subprocess.run([self.node,'--input-type=module','-e',NODE_CLIENT,str(self.client)],
            input=json.dumps(dict(baseUrl=self.base_url,token=token or self.token,input=body)),
            text=True,capture_output=True,timeout=15,
            creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        self.assertEqual(result.returncode,0,result.stderr)
        return json.loads(result.stdout)

    def test_actual_mesh_client_reads_one_shared_scope_and_preserves_provenance_without_writes(self):
        self.remember('allowed')
        self.remember('private',principal='echo',shared=False)
        other=self.remember('other')
        # Deliberate synthetic admission to an out-of-scope project.
        self.writer.db.execute('UPDATE memory_records SET scope_id=? WHERE record_id=?',
            ('project/other/shared',other['record_id']))
        before=hashlib.sha256(self.path.read_bytes()).hexdigest()
        changes=self.writer.db.total_changes
        result=self.call();self.assertTrue(result['ok']);self.assertEqual(result['requests'],1)
        rows=result['result']['records']
        self.assertEqual([r['claim'] for r in rows],['sentinel allowed'])
        self.assertEqual(rows[0]['provenance'][0]['ref'],'fixture:allowed')
        self.assertEqual(self.writer.db.total_changes,changes)
        self.assertEqual(hashlib.sha256(self.path.read_bytes()).hexdigest(),before)
        with self.assertRaises(sqlite3.OperationalError):self.reader.db.execute('DELETE FROM memory_records')

    def test_client_blocks_caller_scope_before_transport_and_server_refuses_writer_token(self):
        result=self.call(extra={'scope':'agent/echo/private'})
        self.assertFalse(result['ok']);self.assertEqual(result['requests'],0)
        result=self.call(token='echo-synthetic-token')
        self.assertFalse(result['ok']);self.assertEqual(result['requests'],1)
        self.assertNotIn('echo-synthetic-token',result['message'])

    def test_additional_or_write_grant_and_credential_revocation_fail_on_next_client_read(self):
        self.remember('allowed');self.assertTrue(self.call()['ok'])
        self.writer.db.execute('INSERT INTO scope_grants VALUES (?,?,1,0)',('mesh-recall','agent/echo/private'))
        self.assertFalse(self.call()['ok'])
        self.writer.db.execute('DELETE FROM scope_grants WHERE principal_id=? AND scope_id=?',
            ('mesh-recall','agent/echo/private'))
        self.assertTrue(self.call()['ok'])
        self.writer.db.execute('UPDATE scope_grants SET can_write=1 WHERE principal_id=?',('mesh-recall',))
        self.assertFalse(self.call()['ok'])
        self.writer.db.execute('UPDATE scope_grants SET can_write=0 WHERE principal_id=?',('mesh-recall',))
        self.assertTrue(self.call()['ok'])
        self.writer.rotate_credentials('mesh-recall');self.assertFalse(self.call()['ok'])

    def test_committed_revision_and_supersession_are_visible_to_actual_mesh_client(self):
        record=self.remember('original');rid=record['record_id']
        self.assertEqual(self.call('original')['result']['records'][0]['claim'],'sentinel original')
        # Synthetic writer transaction; this does not claim a production correction API.
        with self.writer._transaction(immediate=True):
            self.writer.db.execute('UPDATE memory_revisions SET is_current=0 WHERE record_id=?',(rid,))
            current=self.writer.db.execute('INSERT INTO memory_revisions(record_id,claim,is_current,source_class,observed_at) VALUES (?,?,1,?,?)',
                (rid,'sentinel corrected','fixture','2026-11-15T00:00:00Z'))
            self.writer.db.execute('UPDATE memory_records SET payload_hash=? WHERE record_id=?',
                (_payload_hash('sentinel corrected','project_fact','fixture'),rid))
            self.writer.db.execute('DELETE FROM memory_fts WHERE record_id=?',(rid,))
            self.writer.db.execute('INSERT INTO memory_fts(record_id,claim) VALUES (?,?)',(rid,'sentinel corrected'))
            self.writer.db.execute('INSERT INTO provenance_refs(record_id,revision_id,evidence_type,locator,content_hash) VALUES (?,?,?,?,?)',
                (rid,current.lastrowid,'fixture','fixture:corrected','b'*64))
        self.assertEqual(self.call('original')['result']['records'],[])
        rows=self.call('corrected')['result']['records']
        self.assertEqual([r['claim'] for r in rows],['sentinel corrected'])
        self.assertEqual([p['ref'] for p in rows[0]['provenance']],['fixture:corrected'])
        self.writer.db.execute("UPDATE memory_records SET state='superseded' WHERE record_id=?",(rid,))
        self.assertEqual(self.call()['result']['records'],[])

    def test_purge_is_absent_on_next_actual_client_read(self):
        record=self.remember('purge');rid=record['record_id']
        self.assertTrue(self.call()['result']['records'])
        self.writer.purge('operator-synthetic-token',rid,'PURGE:'+rid)
        self.assertEqual(self.call()['result']['records'],[])

    def test_changed_identity_and_compatible_clone_are_refused(self):
        self.remember('allowed');self.assertTrue(self.call()['ok'])
        self.writer.db.execute("UPDATE recall_store_identity SET environment='changed-fixture'")
        self.assertFalse(self.call()['ok'])
        clone=(Path(self.folder.name)/'clone.sqlite').resolve()
        db=sqlite3.connect(clone)
        try:self.writer.db.backup(db)
        finally:db.close()
        # Even a fully matching copied identity needs its own reviewed file binding.
        with self.assertRaises(ValueError):
            BoundRecallLedger(clone,binding=replace(self.binding,database_path=str(clone),environment='changed-fixture'))


if __name__=='__main__':unittest.main()
