"""Composed owner rollout rehearsal; real processes, disposable canonical store.

No model or real gateway is started. Fresh actual Hermes managers exercise the
memory side of gateway cache retirement; a live idle gateway reload remains a
separate deployment acceptance check.
"""
from copy import deepcopy
from dataclasses import asdict
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import unittest

MIND=Path(os.environ['MIND_SOURCE']).resolve()
HERMES=Path(os.environ['HERMES_SOURCE']).resolve()
sys.path[:0]=[str(MIND),str(HERMES),str(Path(__file__).resolve().parent.parent/'mind-recovery-candidate')]
import project_service_process_candidate as service
import project_operator_process_candidate as operator
import native_project_sync_candidate as native
import test_project_service_process_candidate as fixtures
from persistent_authority import AuthorityBinding,PersistentAuthorityCandidate
from onoes_mind.agent_home import AgentHome,AgentHomeBinding,WindowsAgentHomeCustody,enroll_agent_home
from onoes_mind.agent_home_http import AgentHomeClient,AgentHomeTransportError,home_binding_sha256
from onoes_mind.curated_home_import import prepare_curated_import,import_curated_home
from onoes_mind.ledger import LedgerError
from onoes_mind.recall_binding import RecallBinding
from onoes_mind.runtime_keys import unprotect_runtime_keys
from test_provider import scope,loaded,call,ACL,canonical
from owner_profile_switch import prepare_switch,install_switch,rollback_switch


class EchoRolloutTests(unittest.TestCase):
    def setUp(self):
        self.base=fixtures.ProjectServiceProcessTests();self.base.setUp()
        self.addCleanup(self.base.doCleanups)
        owner=self.base.base
        owner.value['runtime']['mindSource']=str(MIND)
        owner.value['sourceHashes']={str(p):operator.digest(p) for p in operator.source_paths(owner.value['runtime'])}
        owner.write();self.base.value['operatorProfileSha256']=owner.sha
        self.base.write(actions=['first_setup','run_service'])
        self.base.prepare()
        self.root=self.base.profile.parent
        self.proof=[]

    def observe(self,phase):
        self.proof.append(phase)
        print(json.dumps({'phase':phase}),flush=True)

    def start(self):
        child,stamp=service.launch_service(self.base.profile,self.base.sha,self.base.base.approval)
        self.base.children.append((child,stamp));state=self.base.ready(child)
        return child,state

    def stop(self,child):
        service.request_stop(self.base.profile,self.base.sha,self.base.base.approval)
        self.assertEqual(child.wait(timeout=120),0)
        state=service.service_state(self.base.profile,self.base.sha,self.base.base.approval)
        self.assertEqual(state['state'],'stopped');self.assertFalse(state['processLive'])

    def owner_host(self):
        owner=self.base.base;p=owner.value
        keys=unprotect_runtime_keys(json.loads(Path(p['keyEnrollmentPath']).read_bytes())['runtime_envelope'],
            store_id=p['binding']['store_id'],environment_id=p['binding']['environment'])
        authority=PersistentAuthorityCandidate(AuthorityBinding(**json.loads(Path(p['authorityBindingPath']).read_bytes())))
        host=native.NativeProjectSyncHost(binding=operator.checked_profile(owner.profile,owner.sha)[1],
            history_path=p['historyPath'],authority=authority,**keys,credential_path=p['credentialPath'],
            project_ids=tuple(row[0] for row in p['projects']),review_ref=p['reviewRef'])
        self.addCleanup(host.close);host.start();return host

    def test_import_current_context_restart_and_project_only_rollback(self):
        # Establish the old project-only route and durable receipt before adding
        # any home. Preserve its profile/approval for the actual rollback start.
        old_value=deepcopy(self.base.value)
        old_profile=self.base.profile;old_sha=self.base.sha
        old_approval=self.base.base.approval.read_bytes()
        child,state=self.start();self.assertNotIn('agentHomes',state)
        receipt=self.base.send(service.native_options(self.base.profile,self.base.sha,self.base.base.approval))
        self.stop(child);self.observe('original_project_receipt_saved_and_writer_stopped')

        # Only disposable native saved notes/preferences are read and retained.
        home=self.root/'echo-hermes';home.mkdir()
        (home/'memories').mkdir()
        original_files={'MEMORY.md':b'Saved fact: the example enclosure has removable armor.',
            'USER.md':b'Saved preference: concise progress summaries.'}
        for name,raw in original_files.items():(home/'memories'/name).write_bytes(raw)
        private=[home/name for name in ('custody','intents','review','backup')]
        for path in private:path.mkdir()
        script=self.root/'private-rollout-test.ps1';script.write_text(ACL,encoding='utf-8')
        command="& '"+str(script).replace("'","''")+"' -Paths @("+','.join("'"+str(p).replace("'","''")+"'" for p in private)+')'
        subprocess.run([shutil.which('pwsh'),'-NoProfile','-NonInteractive','-Command',command],
            check=True,capture_output=True,timeout=30,creationflags=subprocess.CREATE_NO_WINDOW)
        shutil.copytree(Path(__file__).with_name('onoes_mind_provider'),home/'plugins/onoes_mind',
            ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
        b=self.base.base.value['binding']
        store=RecallBinding(b['database_path'],b['store_id'],b['environment'],b['authority_ref'],
            'project/onoes-mind/shared',b['file_device'],b['file_inode'],
            'fixture:echo-custody','fixture:revoke','fixture:rollout')
        binding=AgentHomeBinding(store,'echo');custody=WindowsAgentHomeCustody(home/'custody',binding)
        prepared=prepare_curated_import(binding,hermes_home=home,
            expected_sha256={name:service.digest(home/'memories'/name) for name in original_files})
        host=self.owner_host()
        try:
            with host.writer_lock:
                with host.ledger._transaction(immediate=True):
                    host.ledger.create_principal('operator')
                    host.ledger.issue_credential('operator','fixture-rollout-owner')
                enroll_agent_home(host.ledger,binding,operator_token='fixture-rollout-owner',save_new_token=custody.save_new)
                admitted=import_curated_home(host.ledger,binding,operator_token='fixture-rollout-owner',
                    home_token=custody.read(),prepared=prepared)
                self.assertTrue(admitted['durable'])
        finally:host.close()
        self.observe('finite_curated_bootstrap_committed_under_existing_writer_lease')

        # Reuse the existing v5 launcher, not a second server or test-only route.
        with socket.socket() as probe:probe.bind(('127.0.0.1',0));port=probe.getsockname()[1]
        runtime=self.root/'echo-home-runtime.json'
        runtime.write_text(json.dumps(self.base.base.value),encoding='utf-8')
        self.base.profile=self.root/'echo-home-service.json'
        self.base.value={**old_value,'schema':service.AGENT_HOME_SCHEMA,
            'serviceRuntimeProfilePath':str(runtime),'serviceRuntimeProfileSha256':service.digest(runtime),
            'enrolledMeshSourceDirectory':str(service.HERE),'agentHomeBindings':[asdict(binding)],'agentHomePort':port}
        for name in ('attemptPath','readyPath','stopPath'):self.base.value[name]=str(self.root/('echo-'+name+'.json'))
        self.base.write(actions=['run_service','run_agent_homes'])
        approval=json.loads(self.base.base.approval.read_bytes());approval['agentHomes']=service.home_approval(self.base.value)
        self.base.base.approval.write_text(json.dumps(approval))
        endpoint=f'http://127.0.0.1:{port}'
        client=AgentHomeClient(endpoint,agent_id='echo',binding_sha256=home_binding_sha256(binding),
            credential_provider=custody.read,timeout=10)
        child,state=self.start();self.assertEqual(state['agentHomes']['baseUrl'],endpoint)

        pins={p.relative_to(MIND).as_posix():service.digest(p)
            for pattern in ('*.py','*.ps1','*.mjs','migrations/*.sql') for p in (MIND/'onoes_mind').glob(pattern)}
        body={'schema':'onoes-mind-hermes-provider/v1','hermes_home':str(home),'agent_id':'echo',
            'mind_source':str(MIND),'source_hashes':pins,'store_binding':asdict(store),
            'credential_directory':str(home/'custody'),'journal_directory':str(home/'intents'),
            'home_endpoint':endpoint,'review_ref':'fixture:echo-rollout','max_context_bytes':8192,
            'shared_project_tool':'mcp__onoes_mind_mesh__read_project_context'}
        profile=home/'review/provider.json';profile.write_bytes(canonical(body))
        config=home/'config.yaml'
        native_config={'memory':{'memory_enabled':True,'user_profile_enabled':True},
            'mcp_servers':{'onoes-mind-mesh':{'command':'fixture-existing-reader'}},'model':{'default':'unchanged'}}
        config.write_bytes(canonical(native_config))
        with scope(home):
            plan=prepare_switch(home=home,profile=profile,profile_sha256=service.digest(profile),expected_config_sha256=service.digest(config))
            switched=install_switch(plan,backup_directory=home/'backup',assert_quiescent=lambda:True)
            for iteration in range(2):
                _,manager=loaded({'home':home})
                try:
                    context=manager.prefetch_all('What should I know?')
                    self.assertTrue(all(raw.decode() in context for raw in original_files.values()))
                    self.assertIn(prepared.event_id,context)
                    if iteration==0:
                        saved=call(manager,'remember',event_id='echo-rollout-marker',text='Selected fact: example latch is keyed.')
                        self.assertTrue(saved['ok'])
                    self.assertIn('example latch is keyed',manager.prefetch_all('What about the example latch?'))
                finally:manager.shutdown_all()
                if iteration==0:
                    self.stop(child);self.observe('fresh_hermes_session_reads_canonical_bootstrap_and_new_fact')
                    child,state=self.start();self.assertEqual(state['agentHomes']['baseUrl'],endpoint)
            self.stop(child);self.observe('same_endpoint_restart_retains_both_private_and_project_receipts')
            rollback_switch(plan,switched,assert_quiescent=lambda:True)
            from hermes_cli.config import require_readable_config_before_write
            self.assertEqual(require_readable_config_before_write(config),native_config)
        self.assertTrue(all((home/'memories'/name).read_bytes()==raw for name,raw in original_files.items()))

        # Owner revokes only new home credentials. Facts remain canonical, while
        # old project custody/receipt are preserved for the original service.
        host=self.owner_host()
        try:
            with host.writer_lock:
                with host.ledger._transaction(immediate=True):host.ledger.rotate_credentials('echo')
                with self.assertRaises(LedgerError):AgentHome(host.ledger,binding).recall(custody.read(),{'query':'removable'})
                self.assertEqual(host.ledger.db.execute("SELECT COUNT(*) FROM principals WHERE principal_id='echo'").fetchone()[0],1)
                self.assertEqual(host.ledger.db.execute("SELECT COUNT(*) FROM memory_records WHERE principal_id='echo' AND state='active'").fetchone()[0],2)
        finally:host.close()
        self.base.profile=old_profile;self.base.sha=old_sha;self.base.value=old_value
        self.base.base.approval.write_bytes(old_approval)
        child,state=self.start();self.assertNotIn('agentHomes',state)
        replay=self.base.send(service.native_options(self.base.profile,self.base.sha,self.base.base.approval))
        self.assertEqual(replay['receiptId'],receipt['receiptId'])
        with self.assertRaises(AgentHomeTransportError):client.call('recall',{'query':'removable'})
        self.stop(child);self.observe('private_access_revoked_and_original_project_receipt_replayed_after_rollback')
        self.assertEqual(len(self.proof),5)
