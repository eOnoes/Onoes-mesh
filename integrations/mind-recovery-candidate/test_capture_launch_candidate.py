"""Offline source policy preflight uses only the local Workroom database."""
import copy
from contextlib import closing
import json
from pathlib import Path
import shutil
import sqlite3
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
