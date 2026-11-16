"""Owned synthetic protected writer/read service. Secret outputs are pipes only."""
import json
from pathlib import Path
import sys
import threading

sys.path.insert(0, sys.argv[1])
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'integrations/mind-recovery-candidate'))
import test_checkpointed_ledger_candidate as fixtures
from project_events_candidate import ProjectEventsCandidate, EventBinding
from native_project_sync_candidate import NativeProjectSyncHost, seal_project_credential
from native_recall_candidate import NativeRecallHost, seal_service_credential, SCOPE
from onoes_mind.recall_binding import RecallBinding, prepare_mesh_principal, issue_mesh_recall_credential

fixture = fixtures.CheckpointedLedgerTests()
project = reader = None
release = threading.Event()
committed = threading.Event()
try:
    fixture.setUp()
    ledger = fixture.ledger
    stat = ledger.path.stat()
    binding = EventBinding(str(ledger.path.resolve()), stat.st_dev, stat.st_ino,
        fixture.store_id, fixture.environment, 'fixture:source')
    events = ProjectEventsCandidate(ledger, binding)
    events.initialize(); events.register_project('project-A', 'Synthetic Mesh project')
    token = events.enroll(['project-A'])
    credential = fixture.root/'project-credential.json'
    seal_project_credential(credential, token, events=events, project_ids=('project-A',), review_ref='fixture:project')
    token = None
    prepare_mesh_principal(ledger, scope_id=SCOPE)
    read_token = issue_mesh_recall_credential(ledger)
    read_binding = RecallBinding(str(ledger.path.resolve()), fixture.store_id, fixture.environment,
        'fixture:source', SCOPE, stat.st_dev, stat.st_ino, 'fixture:custodian', 'fixture:revoke', 'fixture:read')
    read_credential = fixture.root/'read-credential.json'
    seal_service_credential(read_credential, read_token, binding=read_binding)
    read_token = None
    ledger.close()
    reader = NativeRecallHost(binding=read_binding, credential_path=read_credential)
    reader.start()

    def start_project():
        host = NativeProjectSyncHost(binding=binding, history_path=fixture.history, authority=fixture.authority,
            **fixture.keys, credential_path=credential, project_ids=('project-A',), review_ref='fixture:project')
        host.start()
        return host

    def output(value):
        print(json.dumps(value), flush=True)

    project = start_project()
    output(dict(project=project.native_options(), recall=reader.native_options()))
    for line in sys.stdin:
        op = json.loads(line)['op']
        if op == 'stats':
            db = project.ledger.db
            output(dict(records=db.execute("SELECT count(*) FROM memory_records WHERE principal_id='mesh-project-sync'").fetchone()[0],
                        receipts=db.execute('SELECT count(*) FROM project_sync_events').fetchone()[0]))
        elif op == 'stop':
            project.close(); output(dict(stopped=True))
        elif op == 'restart':
            project = start_project(); output(dict(project=project.native_options(), recall=reader.native_options()))
        elif op == 'revoke':
            with project.ledger._transaction(immediate=True): project.ledger.rotate_credentials('mesh-project-sync')
            output(dict(revoked=True))
        elif op == 'holdNextReply':
            original = project.events.submit
            release.clear(); committed.clear()
            def held_submit(token, event):
                receipt = original(token, event)
                committed.set()
                if not release.wait(timeout=10): raise RuntimeError('Synthetic reply release timeout')
                return receipt
            project.events.submit = held_submit
            output(dict(armed=True))
        elif op == 'committed': output(dict(committed=committed.is_set()))
        elif op == 'release': release.set(); output(dict(released=True))
        elif op == 'close':
            release.set(); project.close(); reader.close(); output(dict(closed=True)); break
        else: raise ValueError('Unknown synthetic fixture operation')
finally:
    release.set()
    if project is not None: project.close()
    if reader is not None: reader.close()
    fixture.doCleanups()
