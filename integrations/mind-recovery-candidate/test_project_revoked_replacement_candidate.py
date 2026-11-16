"""Synthetic revoked-purpose replacement; no production path or credentials."""
import copy
import json
import os
from pathlib import Path
import sqlite3
import time
import unittest
import urllib.error

import test_project_service_process_candidate as fixtures
import project_operator_process_candidate as operator
import project_service_process_candidate as service
import recall_process_candidate as roles


@unittest.skipUnless(os.name=='nt','Actual protected Windows role lifecycle')
class RevokedPurposeReplacementTests(unittest.TestCase):
    def test_revoke_then_replace_preserves_same_event_receipt_and_rejects_old_token(self):
        fixture=fixtures.ProjectServiceProcessTests();fixture.setUp();self.addCleanup(fixture.doCleanups)
        base=fixture.base;root=base.profile.parent
        self.assertNotEqual(base.value['binding']['store_id'],'3b97853b-0c38-4df0-97ab-217005facf03')
        fixture.prepare()
        first,first_ticks=service.launch_service(fixture.profile,fixture.sha,base.approval)
        fixture.children.append((first,first_ticks));fixture.ready(first)
        options=service.native_options(fixture.profile,fixture.sha,base.approval)
        original_token=options['destination']['token']
        original_receipt=fixture.send(options)
        service.request_stop(fixture.profile,fixture.sha,base.approval)
        self.assertEqual(first.wait(timeout=120),0)
        old_state=service.service_state(fixture.profile,fixture.sha,base.approval)
        self.assertEqual(old_state['state'],'stopped');self.assertFalse(old_state['processLive'])
        self.assertEqual(roles.creation_ticks(first._handle),first_ticks)

        def operation(mode):
            value=copy.deepcopy(base.value)
            value.update(mode=mode,operationId='fixture-revoked-purpose-'+mode,
                credentialPath=None if mode=='revoke' else str(root/'replacement-credential.json'),
                attemptPath=str(root/(mode+'-attempt.json')),outcomePath=str(root/(mode+'-outcome.json')),
                terminalPath=str(root/(mode+'-terminal.json')))
            path=root/(mode+'-profile.json');path.write_text(json.dumps(value),encoding='utf-8')
            fingerprint=operator.digest(path)
            approved=json.loads(base.approval.read_text())
            approved['profiles']=list(dict.fromkeys(approved['profiles']+[fingerprint]))
            approved['actions']=list(dict.fromkeys(approved['actions']+[mode]))
            base.approval.write_text(json.dumps(approved),encoding='utf-8')
            child,ticks=operator.launch_operator(path,fingerprint,base.approval)
            base.base.children.append(child)
            self.assertEqual(child.wait(timeout=180),0)
            terminal=operator.finish_operator(child,ticks,path,fingerprint,base.approval)
            self.assertEqual(terminal['mode'],mode)
            self.assertEqual(roles.creation_ticks(child._handle),ticks)
            return path,fingerprint,terminal

        _,_,revoked=operation('revoke')
        replacement_profile,replacement_sha,replaced=operation('replace')
        self.assertEqual(revoked['storeId'],replaced['storeId'])
        value=copy.deepcopy(fixture.value)
        value.update(operatorProfilePath=str(replacement_profile),operatorProfileSha256=replacement_sha,
                     attemptPath=str(root/'replacement-service-attempt.json'),
                     readyPath=str(root/'replacement-service-ready.json'),stopPath=str(root/'replacement-service-stop.json'))
        fixture.profile=root/'replacement-service-profile.json'
        fixture.profile.write_text(json.dumps(value),encoding='utf-8');fixture.value=value
        fixture.sha=service.digest(fixture.profile)
        approved=json.loads(base.approval.read_text());approved['profiles'].append(fixture.sha)
        base.approval.write_text(json.dumps(approved),encoding='utf-8')
        second,second_ticks=service.launch_service(fixture.profile,fixture.sha,base.approval)
        fixture.children.append((second,second_ticks));fixture.ready(second)
        new_options=service.native_options(fixture.profile,fixture.sha,base.approval)
        self.assertTrue(new_options['destination']['token']!=original_token,'The replacement must rotate its service token.')
        denied=copy.deepcopy(new_options);denied['destination']['token']=original_token
        with self.assertRaises(urllib.error.HTTPError) as error:fixture.send(denied)
        try:self.assertIn(error.exception.code,(401,403))
        finally:error.exception.close()
        same=fixture.send(new_options)
        self.assertEqual(same['receiptId'],original_receipt['receiptId'])
        db=sqlite3.connect(base.base.database)
        try:self.assertEqual(db.execute('SELECT count(*) FROM project_sync_events').fetchone()[0],1)
        finally:db.close()
        service.request_stop(fixture.profile,fixture.sha,base.approval)
        self.assertEqual(second.wait(timeout=120),0)
        state=service.service_state(fixture.profile,fixture.sha,base.approval)
        self.assertEqual(state['state'],'stopped');self.assertFalse(state['processLive'])
        self.assertEqual(roles.creation_ticks(second._handle),second_ticks)
        proof=dict(schema='onoes-mesh-revoked-purpose-replacement-proof/v1',syntheticOnly=True,
            firstWriterRetired=True,revocationTerminalVerified=True,replacementTerminalVerified=True,
            sameCanonicalStore=True,originalTokenRejected=True,rotatedTokenQualified=True,
            originalReceiptIdPreserved=True,canonicalEventCount=1,replacementWriterRetired=True,
            liveChanged=False)
        target=Path(__file__).resolve().parents[2]/'data/project-revoked-purpose-replacement-proof-20261116.json'
        with target.open('x',encoding='utf-8') as output:json.dump(proof,output,indent=2)


if __name__=='__main__':unittest.main()
