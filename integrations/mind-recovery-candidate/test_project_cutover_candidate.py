"""Opt-in disposable installed-runtime cutover; never runs against the live workspace."""
import copy
import importlib.util
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import unittest
from unittest.mock import patch

import test_project_mesh_input_candidate as fixtures
import mesh_launch_candidate as launch
import project_operator_process_candidate as operator
import project_service_process_candidate as service
import recall_process_candidate as roles


@unittest.skipUnless(os.name=='nt' and os.environ.get('MESH_OVERLAY_CUTOVER_FIXTURE'),'Explicit disposable cutover fixture only')
class InstalledCutoverTests(unittest.TestCase):
    def test_owned_stop_revocation_exact_code_rollback_and_readonly_restart(self):
        config=json.loads(Path(os.environ['MESH_OVERLAY_CUTOVER_FIXTURE']).read_text())
        workspace=Path(config['workspace']);run=workspace.parent
        self.assertEqual(launch.ROOT,workspace);self.assertTrue(run.name.startswith('mesh-overlay-cutover-'))
        self.assertTrue(config['syntheticOnly']);self.assertNotEqual(str(workspace),config['liveWorkspace'])
        spec=importlib.util.spec_from_file_location('cutover_overlay',config['tool'])
        overlay=importlib.util.module_from_spec(spec);spec.loader.exec_module(overlay)
        self.assertEqual(overlay.digest(config['tool']),config['toolSha256'])
        case=fixtures.ProjectMeshLauncherTests();case.setUp();self.addCleanup(case.doCleanups)
        # Adapt this private fixture before any service launches, preserving the
        # actual attempt/receipt identity instead of relaxing the plan contract.
        case.fixture.value['attemptPath']=str(case.root/'fixture-service-attempt.json')
        case.fixture.write()
        state={};actual_launch=launch.launch_mesh
        reader_credential=Path(case.reader.reader_data['credentialPath'])

        def stopped_service(child):
            service.request_stop(case.fixture.profile,case.fixture.sha,case.fixture.base.approval)
            self.assertEqual(child.wait(timeout=60),0)
            record=service.service_state(case.fixture.profile,case.fixture.sha,case.fixture.base.approval)
            self.assertEqual(record['state'],'stopped');self.assertFalse(record['processLive'])
            self.assertEqual(roles.creation_ticks(child._handle),record['creationTicks'])
            return record

        def install_before_mesh(profile,sha,approval):
            self.assertFalse(state)
            service_child,_=case.fixture.children[-1]
            stopped_service(service_child)
            # Fixture preparation loaded candidate helpers without a Mesh child.
            # Restore exact originals before the actual guarded installation.
            for f in config['files']:
                target=workspace/f['relativePath'];self.assertEqual(target.resolve(),target)
                self.assertEqual(overlay.digest(target),f['afterSha256'])
                if f['beforeSha256'] is None:target.unlink()
                else:target.write_bytes((Path(config['beforeRoot'])/f['relativePath']).read_bytes())
            child=subprocess.Popen([sys.executable,'-c','pass'],creationflags=subprocess.CREATE_NO_WINDOW)
            stamp=roles.creation_ticks(child._handle);self.assertEqual(child.wait(timeout=10),0)
            with socket.socket() as port:port.bind(('127.0.0.1',0));number=port.getsockname()[1]
            native=json.loads(Path(profile).read_text())
            plan=dict(schema='onoes-mesh-runtime-overlay/v2',workspace=str(workspace),payloadRoot=config['payloadRoot'],
                journalRoot=str(run/'journal'),toolSha256=config['toolSha256'],observerSha256=overlay.digest(overlay.observer_path()),
                runtime=dict(meshPid=child.pid,meshCreationTicks=stamp,gatewayPort=number,
                    serviceAttemptPath=case.fixture.value['attemptPath'],serviceProfileSha256=case.fixture.sha,
                    freshLaunchAttempts=[dict(kind='mesh',path=native['attemptPath'],profileSha256=sha)]),files=config['files'])
            self.assertTrue(overlay.inspect_overlay(plan)['createsNothing'])
            self.assertEqual(overlay.apply_overlay(plan,dict(decision='approve_exact_mesh_runtime_overlay',planSha256=overlay.plan_hash(plan)))['state'],'installed')
            state.update(plan=plan,meshProfile=str(profile),meshSha=sha)
            restarted,ticks=service.launch_service(case.fixture.profile,case.fixture.sha,case.fixture.base.approval)
            case.fixture.children.append((restarted,ticks));case.fixture.ready(restarted)
            state['serviceChild']=restarted
            return actual_launch(profile,sha,approval)

        with patch.object(launch,'launch_mesh',side_effect=install_before_mesh):
            case.test_exact_profiles_preflight_then_owned_gateway_delivers_only_approved_fields()
        credential_before=roles.digest(reader_credential)
        # Simulate a failed qualification decision after proven delivery. This
        # exercises conditional rollback without manufacturing an ambiguous send.
        frame=launch.native_frame(*launch.checked_launch(state['meshProfile'],state['meshSha'],case.reader.approval),case.reader.approval,state['meshSha'])
        project_token=frame['projectSyncOptions']['destination']['token'];frame=None
        self.assertIsNone(case.mesh.poll());mesh_stamp=roles.creation_ticks(case.mesh._handle)
        case.mesh.terminate();case.mesh.wait(timeout=30)
        self.assertEqual(roles.creation_ticks(case.mesh._handle),mesh_stamp)
        stopped=stopped_service(state['serviceChild'])
        base=case.fixture.base;revoke=copy.deepcopy(base.value)
        revoke.update(mode='revoke',operationId='fixture-cutover-revoke',credentialPath=None,
            attemptPath=str(case.root/'revoke-attempt.json'),outcomePath=str(case.root/'revoke-outcome.json'),terminalPath=str(case.root/'revoke-terminal.json'))
        revoke_profile=case.root/'revoke-profile.json';revoke_profile.write_text(json.dumps(revoke),encoding='utf-8');revoke_sha=operator.digest(revoke_profile)
        approved=json.loads(base.approval.read_text());approved['profiles'].append(revoke_sha);approved['actions'].append('revoke')
        base.approval.write_text(json.dumps(approved),encoding='utf-8')
        child,stamp=operator.launch_operator(revoke_profile,revoke_sha,base.approval)
        case.reader.children.append(child);self.assertEqual(child.wait(timeout=180),0)
        terminal=operator.finish_operator(child,stamp,revoke_profile,revoke_sha,base.approval)
        self.assertEqual(terminal['mode'],'revoke');self.assertEqual(terminal['operationId'],revoke['operationId'])
        self.assertEqual(roles.digest(reader_credential),credential_before)
        self.assertTrue(roles.reader_state(case.reader.reader,case.reader.reader_sha,case.reader.approval)['ready'])
        from onoes_mind.runtime_keys import unprotect_runtime_keys
        from checkpointed_ledger_candidate import CheckpointedLedgerCandidate
        from persistent_authority import AuthorityBinding,PersistentAuthorityCandidate
        from project_events_candidate import EventBinding,ProjectEventsCandidate,EventError
        package=json.loads(Path(base.value['keyEnrollmentPath']).read_text())
        keys=unprotect_runtime_keys(package['runtime_envelope'],store_id=revoke['binding']['store_id'],environment_id=revoke['binding']['environment'])
        authority=PersistentAuthorityCandidate(AuthorityBinding(**json.loads(Path(base.value['authorityBindingPath']).read_text())))
        ledger=CheckpointedLedgerCandidate(revoke['binding']['database_path'],base.value['historyPath'],authority,
            store_id=revoke['binding']['store_id'],environment=revoke['binding']['environment'],**keys)
        try:
            stored_event=ledger.db.execute('SELECT event_id FROM project_sync_events LIMIT 1').fetchone()[0]
            with self.assertRaises(EventError):ProjectEventsCandidate(ledger,EventBinding(**revoke['binding'])).lookup(project_token,project_id='project-A',event_id=stored_event)
            self.assertEqual(ledger.db.execute('SELECT count(*) FROM project_sync_events').fetchone()[0],2)
        finally:ledger.close();keys=None;project_token=None
        self.assertEqual(overlay.rollback_overlay(state['plan'],dict(decision='approve_exact_mesh_runtime_rollback',planSha256=overlay.plan_hash(state['plan'])))['state'],'original')
        self.assertTrue(all(overlay.digest(workspace/f['relativePath'])==f['beforeSha256'] for f in config['files']))
        # Import the actual restored launcher, not the candidate cached above.
        spec=importlib.util.spec_from_file_location('restored_readonly_launcher',workspace/'integrations/mind-recovery-candidate/mesh_launch_candidate.py')
        old=importlib.util.module_from_spec(spec);spec.loader.exec_module(old)
        fallback=json.loads(Path(state['meshProfile']).read_text());fallback['schema']='onoes-mesh-native-launch/v1';fallback.pop('projectSync')
        fallback['sourceHashes']={str(n):old.digest(n) for n in old.source_paths()}
        for key,name in [('attemptPath','fallback-attempt.json'),('stdoutPath','fallback-out.log'),('stderrPath','fallback-err.log')]:fallback[key]=str(case.root/name)
        fallback_profile=case.root/'fallback-profile.json';fallback_profile.write_text(json.dumps(fallback),encoding='utf-8');fallback_sha=old.digest(fallback_profile)
        approved=json.loads(case.reader.approval.read_text());approved['profiles'].append(fallback_sha);case.reader.approval.write_text(json.dumps(approved),encoding='utf-8')
        case.mesh,_,record=old.launch_mesh(fallback_profile,fallback_sha,case.reader.approval)
        self.assertEqual(record['state'],'input_sent')
        def listening():
            for line in Path(fallback['stdoutPath']).read_text().splitlines():
                try:row=json.loads(line)
                except ValueError:continue
                if row.get('event')=='mesh_listening':return row
        address=case.wait_for(listening,case.mesh);request=fixtures.admitted_http(address['url'])
        session=request('/api/trial-session/bootstrap',{});csrf=session['csrfToken']
        status=request('/api/mind/status',csrf=csrf,method='GET')
        self.assertTrue(status['configured']);self.assertEqual(status['source'],'canonical_ledger')
        result=request('/api/mind/recall',dict(query='launcher',limit=10),csrf)
        def claims(value):
            if isinstance(value,dict):
                if isinstance(value.get('claim'),str):yield value['claim']
                for v in value.values():yield from claims(v)
            elif isinstance(value,list):
                for v in value:yield from claims(v)
        self.assertTrue(any('Composed launcher saved title' in value for value in claims(result)))
        import sqlite3
        source=sqlite3.connect(Path(fallback['settings']['MESH_DATA_DIR']).is_absolute() and Path(fallback['settings']['MESH_DATA_DIR'])/'tasks.sqlite' or workspace/fallback['settings']['MESH_DATA_DIR']/'tasks.sqlite')
        try:self.assertEqual(source.execute('SELECT count(*) FROM mind_project_outbox').fetchone()[0],2)
        finally:source.close()
        request('/api/trial-session/logout',{},csrf)
        for key in ('stdoutPath','stderrPath'):(run/Path(fallback[key]).name).write_bytes(Path(fallback[key]).read_bytes())
        proof=dict(schema='onoes-mesh-disposable-cutover/v1',syntheticOnly=True,installedDeliveryPassed=True,
            ownedMeshRetired=True,ownedWriterStopped=stopped['state']=='stopped',revocationTerminalVerified=True,
            revokedCredentialRejected=True,canonicalProjectReceiptsPreserved=2,sourceOutboxPreserved=2,
            readCredentialUnchanged=True,allOriginalCodeRestored=True,readOnlyFallbackListening=True,
            readOnlyCanonicalRecallPassed=True,planSha256=overlay.plan_hash(state['plan']),newFileCount=sum(f['beforeSha256'] is None for f in config['files']),liveChanged=False)
        (run/'CUTOVER-PROOF.json').write_text(json.dumps(proof,indent=2)+'\n',encoding='utf-8')


if __name__=='__main__':unittest.main()
