"""Isolated installed-Relay startup qualification; never import the live deployment.

Copies source modules only, uses a fresh synthetic store/config, blocks networking,
then exercises actual import, startup loops, shutdown and restart. No peer is used.
"""
import asyncio
import argparse
import hashlib
import importlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone


def child():
    print('stage: child entry',file=sys.stderr,flush=True)
    fixture = Path.cwd().resolve()
    if not fixture.name.startswith('mesh-relay-retained-') or Path(__file__).resolve().parent != fixture:
        raise RuntimeError('Child mode requires the copied disposable fixture')
    allowed = [fixture, Path(sys.prefix).resolve(), Path(sys.base_prefix).resolve()]
    loop = asyncio.new_event_loop()  # Establish asyncio self-pipe before forbidding application networking.
    connections = []
    def audit(event, args):
        if event in ('socket.connect', 'socket.getaddrinfo', 'subprocess.Popen', 'os.system'):
            connections.append(event)
            raise RuntimeError('Qualification forbids network and subprocess calls')
        if event == 'open' and isinstance(args[0], (str, bytes, os.PathLike)):
            target = Path(os.fsdecode(args[0])).resolve()
            if not any(target.is_relative_to(root) for root in allowed):
                raise RuntimeError('Qualification refuses file outside isolated roots')
    sys.addaudithook(audit)
    import socket
    with socket.socket() as connection:
        try: connection.connect(('127.0.0.1', 9))
        except RuntimeError: pass
        else: raise AssertionError('Network boundary did not reject its control')
    try: subprocess.Popen([sys.executable, '-c', 'raise SystemExit(99)'])
    except RuntimeError: pass
    else: raise AssertionError('Process boundary did not reject its control')
    try: open('C:/Windows/win.ini', 'rb')
    except RuntimeError: pass
    else: raise AssertionError('File boundary did not reject its control')
    assert connections == ['socket.connect', 'subprocess.Popen']
    connections.clear()
    sys.path.insert(0, str(fixture))
    from relay_sessions import SessionStore
    store = SessionStore(fixture / 'sessions.sqlite3')
    ids = {'dsh': 'fixture-old-dsh', 'cyony': 'fixture-old-cyony'}
    for aid, send in ids.items():
        session = store.ensure_agent(aid)
        store.outbox_enqueue(aid, session['id'], 'Synthetic retained request', attachments=[], idem_key=send)
    store.db.execute("UPDATE outbox SET state='retrying',attempts=1,next_attempt_at=NULL")
    store.db.commit()
    def retained():
        store.db.row_factory = __import__('sqlite3').Row
        return [dict(row) for row in store.db.execute('SELECT * FROM outbox WHERE idem_key IN (?,?) ORDER BY idem_key', tuple(ids.values()))]
    before = retained()
    store.db.close()
    print('stage: importing copied Relay',file=sys.stderr,flush=True)
    relay = importlib.import_module('relay_server')
    print('stage: copied Relay imported',file=sys.stderr,flush=True)
    calls = []
    async def no_transport(agent, *args, **kwargs):
        calls.append(agent.id)
    relay.run_turn = no_transport  # Transport boundary spy, actual startup/routes remain intact.
    class Request:
        def __init__(self, body): self.body = body
        async def json(self): return self.body
    async def exercise():
        results = []
        for boot in range(2):
            nonlocal relay
            if boot:
                relay.SESSIONS.db.close()
                relay = importlib.reload(relay)
                relay.run_turn = no_transport
            baseline = len(calls)
            assert all(not a.message_queue and not a.running() for a in relay.AGENTS.values())
            print('stage: startup '+str(boot),file=sys.stderr,flush=True)
            await relay.startup()
            try:
                print('stage: startup returned',file=sys.stderr,flush=True)
                await asyncio.sleep(5.3)  # Real watchdog and desktop/notification loops execute.
                print('stage: loop delay complete',file=sys.stderr,flush=True)
                tasks = [relay.WATCHDOG_TASK, relay.HERMES_DESKTOP_TASK, relay.NOTIFICATION_TASK]
                assert all(t and not t.done() for t in tasks), 'A startup task failed or did not start'
                assert len(calls) == baseline, 'Startup dispatched retained work'
                for aid, send in ids.items():
                    response = await relay.message(aid, Request({'id': send, 'text': 'Synthetic retained request',
                        'expectedConversationId': relay.AGENTS[aid].conversation_id}))
                    assert json.loads(response.body)['duplicate'] is True
                assert len(calls) == baseline, 'Duplicate old ID dispatched work'
                rows = [dict(row) for row in relay.SESSIONS.db.execute('SELECT * FROM outbox WHERE idem_key IN (?,?) ORDER BY idem_key', tuple(ids.values()))]
                assert rows == before, 'Retained records changed'
                # Positive control: a deliberate fresh request reaches the transport spy.
                print('stage: old IDs checked',file=sys.stderr,flush=True)
                response = await relay.message('dsh', Request({'id': 'fixture-fresh-' + str(boot), 'text': 'New deliberate fixture request'}))
                assert json.loads(response.body)['ok'] is True
                print('stage: fresh queued',file=sys.stderr,flush=True)
                await asyncio.wait_for(relay.AGENTS['dsh'].run_task, timeout=3)
                assert len(calls) == baseline + 1
                results.append({'boot': boot + 1, 'startupTransportCalls': 0, 'duplicateTransportCalls': 0,
                    'freshRequestTransportCalls': 1, 'retainedRowsUnchanged': True, 'backgroundTasksRunning': 3})
            finally:
                print('stage: shutdown',file=sys.stderr,flush=True)
                await asyncio.wait_for(relay.shutdown(), timeout=3)
        return results
    try:
        results = loop.run_until_complete(exercise())
    finally:
        loop.close()
    assert not connections, 'An unexpected network or process attempt occurred'
    print(json.dumps({'cases': results, 'networkOrProcessAttempts': 0, 'boundaryRejectionControlsPassed': 3}))


def main():
    workspace = Path(__file__).resolve().parent.parent
    if Path.cwd().resolve() != workspace:
        raise RuntimeError('Run from the Mesh workspace')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path)
    args = parser.parse_args()
    output_directory = workspace / 'data'
    if args.output_dir is not None:
        selected = args.output_dir.absolute()
        resolved = selected.resolve(strict=True)
        if selected != resolved or not resolved.is_dir() or not resolved.is_relative_to(workspace / 'data') or resolved == workspace / 'data' or any(resolved.iterdir()):
            raise RuntimeError('Output must be a fresh, empty directory inside workspace data.')
        output_directory = resolved
    source = Path('D:/Dev/Onoes-Relay')
    helper_bytes = Path(__file__).read_bytes()
    python = source / '.venv/Scripts/python.exe'
    if not python.is_file(): raise RuntimeError('Installed Relay interpreter is missing')
    with tempfile.TemporaryDirectory(prefix='mesh-relay-retained-', dir=workspace / 'data') as temporary:
        fixture = Path(temporary)
        # Source files only: never copy live config, credentials, databases or history.
        source_files = [source / 'relay_server.py', *sorted(source.glob('relay_*.py'))]
        source_files = list(dict.fromkeys(source_files))
        hashes = {}
        for file in source_files:
            data = file.read_bytes()
            hashes[file.name] = hashlib.sha256(data).hexdigest()
            (fixture / file.name).write_bytes(data)
        (fixture / 'qualification.py').write_bytes(helper_bytes)
        (fixture / 'static').mkdir()
        config = {'agents': {aid: {'name': aid, 'backend': 'a2a', 'url': 'http://127.0.0.1:9',
            'api_key': 'synthetic-fixture-key-not-a-credential', 'demo_fallback': False} for aid in ['dsh', 'cyony']}}
        (fixture / 'config.json').write_text(json.dumps(config), encoding='utf-8')
        env = {k: v for k,v in os.environ.items() if k.upper() in ['SYSTEMROOT','WINDIR','PATH','TEMP','TMP','COMSPEC','PATHEXT','SYSTEMDRIVE']}
        env.update(HOME=str(fixture), USERPROFILE=str(fixture), APPDATA=str(fixture / 'appdata'),
            LOCALAPPDATA=str(fixture / 'local'), RELAY_CONFIG_PATH=str(fixture / 'config.json'),
            RELAY_SESSION_DB=str(fixture / 'sessions.sqlite3'), PYTHONDONTWRITEBYTECODE='1', PYTHONUTF8='1')
        child_log = output_directory / 'relay-retained-startup-child.log'
        with child_log.open('x' if args.output_dir is not None else 'w', encoding='utf-8') as output:
            result = subprocess.run([str(python), '-X', 'utf8', str(fixture / 'qualification.py'), '--child'],
                cwd=fixture, env=env, stdout=output, stderr=subprocess.STDOUT, text=True, timeout=30,
                creationflags=subprocess.CREATE_NO_WINDOW)
        result.stdout = child_log.read_text(encoding='utf-8')
        result.stderr = result.stdout
        if result.returncode:
            raise RuntimeError('Isolated startup qualification failed:\n' + result.stderr[-6000:])
        actual = json.loads(result.stdout.strip().splitlines()[-1])
        assert all(hashlib.sha256(file.read_bytes()).hexdigest() == hashes[file.name] for file in source_files)
        assert Path(__file__).read_bytes() == helper_bytes
        proof = {'schema': 'mesh/relay-retained-startup-qualification/v1', 'observedAt': datetime.now(timezone.utc).isoformat(),
            'sourceSha256': hashes, 'qualificationHelperSha256': hashlib.sha256(helper_bytes).hexdigest(),
            **actual, 'liveDeploymentChanged': False, 'liveStoreOpened': False,
            'limitations': ['Actual copied Relay import/startup/loops/message/shutdown/restart, synthetic A2A agents and rows; transport replaced by a spy.',
                'No OpenClaw agent or Hermes backend in this fixture; no full native-gateway startup, loaded-version or prior-writer retirement proof.',
                'Does not authorize retained-record exclusions or recovery activation.']}
        output = output_directory / 'relay-retained-startup-qualification.json'
        with output.open('x' if args.output_dir is not None else 'w', encoding='utf-8') as stream:
            stream.write(json.dumps(proof, indent=2) + '\n')
        print(json.dumps({'output': str(output), 'cases': actual['cases']}))


if __name__ == '__main__':
    if sys.argv[1:] == ['--child']: child()
    else: main()
