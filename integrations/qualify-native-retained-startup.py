"""Exercise native initialization, profile recovery and restart using disposable state.
Only the owned synthetic crash peer is terminated. No live service is restarted.
"""
import hashlib
import argparse
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import tarfile
import shutil
import time
from datetime import datetime, timezone


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
    native = Path('C:/Users/eMitchell109/AppData/Local/hermes/hermes-agent')
    executable = Path('C:/Users/eMitchell109/AppData/Local/hermes/tools/python-3.14.9+20261021-win32-x64/python.exe')
    helper = Path(__file__).with_name('qualify-native-retained-peer.py')
    helper_names = ['qualify-native-retained-startup.py', 'qualify-native-retained-peer.py', 'qualify-native-retained-recovery.py']
    helper_hashes = {name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest() for name in helper_names}
    names = ['gateway/session_authority.py','gateway/session_unattended_unknown.py','gateway/run_runtime.py',
        'gateway/session_local_recovery.py','gateway/session_bot.py','gateway/session_envelope.py',
        'hermes_state.py','hermes_state_runtime.py','hermes_state_runtime_workers.py',
        'gateway/run_bootstrap.py','gateway/control_socket.py','gateway/runtime_ownership.py',
        'gateway/runtime_bootstrap_windows.py','gateway/session_hosted_service.py']
    hashes = {name: hashlib.sha256((native / name).read_bytes()).hexdigest() for name in names}
    # Existing Mesh environment builder provisions isolated homes and compatible installed libraries.
    spec = importlib.util.spec_from_file_location('mesh_native_environment', Path(__file__).with_name('qualify_hermes_runtime.py'))
    environment_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(environment_module)
    root = Path(tempfile.mkdtemp(prefix='mesh-native-retained-', dir=workspace / 'data'))
    for name in ['home','state','workspace','temp']:
        (root / name).mkdir()
    # Archive committed source and overlay existing tracked edits. No live user state is copied.
    snapshot = root / 'source'
    snapshot.mkdir()
    archive = root / 'native-source.tar'
    with archive.open('wb') as output:
        subprocess.run(['git','-C',str(native),'archive','--format=tar','HEAD'],stdout=output,check=True,
            creationflags=subprocess.CREATE_NO_WINDOW)
    with tarfile.open(archive) as bundle:
        for member in bundle.getmembers():
            target = (snapshot / member.name).resolve()
            if not target.is_relative_to(snapshot): raise RuntimeError('Unsafe archive member')
            if member.isfile():
                target.parent.mkdir(parents=True,exist_ok=True)
                with bundle.extractfile(member) as data: target.write_bytes(data.read())
    changed = subprocess.check_output(['git','-C',str(native),'diff','--name-only','HEAD','-z'],creationflags=subprocess.CREATE_NO_WINDOW).decode().split('\0')
    for relative in filter(None,changed):
        original, target = native / relative, snapshot / relative
        if not target.resolve().is_relative_to(snapshot): raise RuntimeError('Unsafe tracked edit path')
        if original.is_file():
            target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(original,target)
        elif target.is_file(): target.unlink()
    shutil.copyfile(helper,root / helper.name)
    shutil.copyfile(helper.with_name('qualify-native-retained-recovery.py'),root / 'qualify-native-retained-recovery.py')
    env = environment_module.runtime_environment(root, str(native), str(executable), ['--safe-mode'])
    env['PYTHONPATH'] = str(snapshot) + os.pathsep + env.get('PYTHONPATH', '')
    env.update(HERMES_HOME=str(root / "state"), HOME=str(root / "home"), USERPROFILE=str(root / "home"),
        MESH_NATIVE_RETAINED_ROOT=str(root), MESH_NATIVE_SOURCE=str(snapshot),
        HERMES_RUNTIME_DIR=str(root / 'runtime'), PYTHONDONTWRITEBYTECODE='1', NO_PROXY='*',
        PYTHONUNBUFFERED='1', AUTHORITY_PROBE_MODE='crash')
    command = [str(executable), str(root / helper.name)]
    with (root / 'owner.log').open('w', encoding='utf-8') as log:
        process = subprocess.Popen(command, cwd=root, env=env, stdin=subprocess.DEVNULL,
            stdout=log, stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            deadline = time.monotonic() + 70
            while not (root / 'state/crash-ready.json').exists():
                if process.poll() is not None or time.monotonic() > deadline:
                    raise RuntimeError('Native crash fixture failed; see ' + str(root / 'owner.log'))
                time.sleep(.1)
            process.kill()  # Exact handle created above, only the disposable source/state owner.
            crash_exit = process.wait(timeout=10)
            assert crash_exit != 0
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=10)
    runs = []
    env['AUTHORITY_PROBE_MODE'] = 'recover'
    for index, expected in enumerate([1, 0], 1):
        with (root / ('recover-' + str(index) + '.log')).open('w', encoding='utf-8') as log:
            result = subprocess.run(command, cwd=root, env=env, stdin=subprocess.DEVNULL,
                stdout=log, stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NO_WINDOW, timeout=65)
        if result.returncode:
            raise RuntimeError('Native recovery fixture failed; see ' + str(root / ('recover-' + str(index) + '.log')))
        receipt = json.loads((root / 'state/recovery-receipt.json').read_text())
        assert receipt['coordinatorIsPrimaryRecovery'] is True
        assert receipt['model_calls'] == expected and receipt['gatewayCoordinatorPreservedRows'] is True
        assert sorted(receipt['recovery'].values()) == (['ready','unknown_execution'] if index == 1 else ['unknown_execution'])
        (root / ('recovery-receipt-' + str(index) + '.json')).write_text(json.dumps(receipt,indent=2)+'\n')
        runs.append({'startup':index,'syntheticModelCalls':expected,'unknownRemainedPaused':True,
            'blockedFollowerRemainedQueued':True,'safeRequestCompleted':True,'gatewayCoordinatorPreservedRows':True,
            'coordinatorIsPrimaryRecovery':receipt['coordinatorIsPrimaryRecovery']})
    first = json.loads((root / 'recovery-receipt-1.json').read_text())
    second = json.loads((root / 'recovery-receipt-2.json').read_text())
    assert first['safe'] == second['safe'] and first['blocked'] == second['blocked']
    assert all(hashlib.sha256((native / name).read_bytes()).hexdigest() == digest for name,digest in hashes.items())
    assert all(hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest() == digest for name,digest in helper_hashes.items())
    proof = {'schema':'mesh/native-retained-startup-qualification/v1','observedAt':datetime.now(timezone.utc).isoformat(),
        'directory':str(root),'sourceSha256':hashes,'ownedFixtureCrashExitCode':crash_exit,'recoveries':runs,
        'helperSha256':helper_hashes,
        'coordinatorIsPrimaryRecovery':all(run['coordinatorIsPrimaryRecovery'] for run in runs),
        'sourceArchiveSha256':hashlib.sha256(archive.read_bytes()).hexdigest(),
        'liveStoreOpened':False,'liveServiceRestarted':False,'originalWorkerRetirementEstablished':False,
        'limits':['Real profile ownership, GatewayRunner/SessionDB/runtime initialization, Windows control server, API startup and full native recovery coordinator; synthetic messaging adapter and local fake model.',
            'Does not run the whole gateway service entry point or prove loaded production bytes, original worker retirement or remote writer coverage.',
            'No retained-record exemption or live recovery activation authorized.']}
    output = output_directory / 'native-retained-startup-qualification.json'
    with output.open('x' if args.output_dir is not None else 'w', encoding='utf-8') as stream:
        stream.write(json.dumps(proof,indent=2)+'\n')
    print(json.dumps({'proof':str(output),'directory':str(root),'recoveries':runs}))


if __name__ == '__main__': main()
