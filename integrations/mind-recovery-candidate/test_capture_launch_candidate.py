"""Offline source policy preflight uses only the local Workroom database."""
import copy
from contextlib import closing
import json
from pathlib import Path
import shutil
import sqlite3
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import mesh_launch_candidate as launch
from project_mesh_input_candidate import node_source_identity


@unittest.skipUnless(shutil.which('node'), 'Existing Node runtime required')
class CaptureFrameTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name).resolve();self.addCleanup(patch.stopall)
        patch.object(launch,'ROOT',self.root).start()
        data=self.root/'data'/'cards';data.mkdir(parents=True);self.db=data/'tasks.sqlite'
        with closing(sqlite3.connect(self.db)) as db, db:
            db.executescript('CREATE TABLE mind_project_links(cardId,projectId,storeId,approvalRef);'
                             'CREATE TABLE mind_project_capture_policy(cardId,fields);')
            db.execute('INSERT INTO mind_project_links VALUES(?,?,?,?)',('card','project','store','approved'))
            db.execute('INSERT INTO mind_project_capture_policy VALUES(?,?)',('card',json.dumps(['title','stage'])))
        node=str(Path(shutil.which('node')).resolve())
        self.p=dict(schema=launch.CAPTURE_SCHEMA,workspace=str(self.root),nodeExecutable=node,
                    nodeSha256=launch.digest(node),settings={'MESH_DATA_DIR':'data/cards'})
        self.p['projectCapture']=dict(schema='onoes-mesh-native-project-capture/v1',
            storeId='store',source=dict(databasePath=str(self.db),**node_source_identity(self.p,self.db)),
            links=[dict(cardId='card',projectId='project',approvalRef='approved',fields=['title','stage'])])

    def test_frame_needs_no_reader_writer_credentials_or_canonical_store(self):
        before=launch.digest(self.db)
        frame=launch.native_frame(self.p,object(),'unused-approval','unused-sha')
        self.assertEqual(set(frame),{'schema','projectCaptureOptions'})
        self.assertEqual(frame['schema'],'onoes-mesh-native-capture-input/v1')
        self.assertEqual(before,launch.digest(self.db))
        self.assertNotIn('token',json.dumps(frame))

    def test_paused_rook_enrollment_uses_the_same_board_and_survives_capture_only_startup(self):
        lib = self.root / 'lib'
        lib.mkdir()
        shutil.copyfile(Path(__file__).resolve().parents[2] / 'lib/database-identity.mjs', lib / 'database-identity.mjs')
        self.p['sourceHashes']={str(lib/'database-identity.mjs'):launch.digest(lib/'database-identity.mjs')}
        identity = subprocess.check_output([self.p['nodeExecutable'], '--input-type=module', '-e',
            "import {databaseFileIdentity} from './lib/database-identity.mjs';console.log(databaseFileIdentity(process.argv[1]))",
            str(self.db)], cwd=self.root, text=True, creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0)).strip()
        record = dict(id='rook', mode='paused', destination='mesh_relay_inbox', boardIdentity=identity)
        self.p['rookEnrollment'] = record
        before = launch.digest(self.db)
        digest = 'b' * 64
        actual = launch.native_frame(self.p, object(), 'unused', digest)
        self.assertEqual(actual['rookEnrollment'], dict(record, boardPath=str(self.db), approvalRef=digest))
        self.assertEqual(set(actual), {'schema','projectCaptureOptions','rookEnrollment'})
        self.assertEqual(launch.digest(self.db), before)
        for extra in ({'id':'nims'}, {'mode':'running'}, {'mode':'active'}, {'token':'fixture'}, {'boardIdentity':'c'*64}):
            with self.subTest(extra=extra), self.assertRaises(launch.LaunchError):
                launch.rook_frame_fields(dict(self.p, rookEnrollment=dict(record, **extra)), digest)
        active = dict(record, mode='active')
        connected = dict(self.p, schema='onoes-mesh-native-launch/v2', rookEnrollment=active,
            settings={**self.p['settings'], 'MESH_NATIVE_WORKER_RECORD':'fixture', 'MESH_NATIVE_WORKER_RECORD_SHA256':'b'*64,
                      'MESH_RELAY':'1', 'MESH_RELAY_MODE':'http', 'MESH_NIMS':'1'})
        self.assertEqual(launch.rook_frame_fields(connected, digest)['rookEnrollment']['mode'], 'active')
        for missing in ['MESH_NATIVE_WORKER_RECORD','MESH_NATIVE_WORKER_RECORD_SHA256','MESH_RELAY','MESH_RELAY_MODE','MESH_NIMS']:
            with self.subTest(missing=missing), self.assertRaises(launch.LaunchError):
                launch.rook_frame_fields(dict(connected, settings={k:v for k,v in connected['settings'].items() if k!=missing}), digest)
        self.assertEqual(launch.digest(self.db), before)

    def test_changed_store_and_broader_fields_are_refused(self):
        for update in (dict(storeId='another-store'),dict(links=[dict(
                cardId='card',projectId='project',approvalRef='approved',fields=['title','stage','goal'])])):
            p=copy.deepcopy(self.p);p['projectCapture'].update(update)
            with self.assertRaises(launch.LaunchError):launch.capture_frame(p)

    def test_changed_source_identity_is_refused(self):
        self.p['projectCapture']['source']['fileInode']='0'
        with self.assertRaises(launch.LaunchError):launch.capture_frame(self.p)

    def test_missing_schema_is_never_created(self):
        with closing(sqlite3.connect(self.db)) as db, db:db.execute('DROP TABLE mind_project_capture_policy')
        before=launch.digest(self.db)
        with self.assertRaises(sqlite3.OperationalError):launch.capture_frame(self.p)
        self.assertEqual(before,launch.digest(self.db))

    def test_credential_or_destination_fields_cannot_enter_offline_frame(self):
        for key in ('token','destination','readerProfile'):
            p=copy.deepcopy(self.p);p['projectCapture'][key]='forbidden'
            with self.assertRaises(launch.LaunchError):launch.capture_frame(p)

    def test_bad_profile_or_missing_explicit_approval_refuses_before_roles(self):
        path=self.root/'profile.json';path.write_text(json.dumps(self.p))
        with self.assertRaises(launch.LaunchError):launch.inspect_launch(path,launch.digest(path),'missing')


if __name__=='__main__':unittest.main()
