"""Finite cloud-side entry for the reviewed native gateway phases.

No model calls, service registration or automatic retry. The enclosing owner
installer delivers the private plan/authorization and records held qualification
before the separate, deliberate admission-release command.
"""
import hashlib
import importlib.util
import json
import os
from contextlib import contextmanager
from pathlib import Path
import re
import stat
import sys
import threading
import traceback

_WINDOW_SCOPES={}


class EntryHeld(RuntimeError):
    pass


def require(ok):
    if not ok:
        raise EntryHeld('Cloud phase inputs or evidence differ; preserve the original window')


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


@contextmanager
def operation_scope(evidence,plan_sha256):
    """One finite remote actor at a time, including after an uncertain SSH reply.

    The lock inode is retained. Only this source-bound operation family uses
    it; it is not evidence of machine-wide writer retirement. Nested stopped
    checks on the same owner thread reuse its held descriptor.
    """
    import fcntl
    root=Path(evidence)
    require(os.name=='posix' and root.is_absolute() and root.resolve(strict=True)==root)
    info=root.stat();require(info.st_uid==os.geteuid() and stat.S_ISDIR(info.st_mode)
        and not stat.S_IMODE(info.st_mode)&0o077)
    key=(os.getpid(),threading.get_ident(),str(root),plan_sha256)
    path=root/'WINDOW-OPERATION.lock'
    if key in _WINDOW_SCOPES:
        fd,identity=_WINDOW_SCOPES[key]
        require((path.stat().st_dev,path.stat().st_ino)==identity)
        yield
        return
    fd=os.open(path,os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600)
    try:
        state=os.fstat(fd);require(stat.S_ISREG(state.st_mode) and state.st_uid==os.geteuid()
            and stat.S_IMODE(state.st_mode)==0o600 and state.st_nlink==1 and state.st_size==0
            and (path.stat().st_dev,path.stat().st_ino)==(state.st_dev,state.st_ino))
        try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise EntryHeld('Another exact window operation remains active; preserve the hold') from None
        _WINDOW_SCOPES[key]=(fd,(state.st_dev,state.st_ino))
        try:yield
        finally:
            del _WINDOW_SCOPES[key]
            fcntl.flock(fd,fcntl.LOCK_UN)
    finally:os.close(fd)


def private_file(path, *, limit=65536):
    path = Path(path)
    require(path.is_absolute() and path.resolve(strict=True) == path)
    info = path.stat()
    require(stat.S_ISREG(info.st_mode) and info.st_uid == os.geteuid()
            and not stat.S_IMODE(info.st_mode) & 0o077 and info.st_size <= limit)
    return path.read_bytes()


def read_private(path):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result)
            result[key] = value
        return result
    value = json.loads(private_file(path), object_pairs_hook=unique)
    require(type(value) is dict)
    return value


def approved_inputs(plan_path, pin, authorization_path):
    """Validate before importing native code or asking a service to do anything."""
    require(os.name == 'posix' and sys.flags.isolated == 1 and sys.dont_write_bytecode
            and type(pin) is str and re.fullmatch('[a-f0-9]{64}', pin))
    raw = private_file(plan_path)
    require(hashlib.sha256(raw).hexdigest() == pin)
    plan = read_private(plan_path)
    authorization = read_private(authorization_path)
    require(authorization == {'schema': 'onoes-cloud-native-window-authorization/v1',
            'planSha256': pin, 'decision': 'approve_scoped_cloud_mind_window', 'owner': 'Eddie'})
    require(plan['schema'] == 'onoes-cloud-native-window/v1'
            and plan['agentId'] == 'cyony' and plan['service'] == 'gateway-default'
            and type(plan['modelCalls']) is int and plan['modelCalls'] == 0
            and type(plan['windowId']) is str and re.fullmatch('[a-z0-9-]{1,71}', plan['windowId']))
    for name in ('home', 'evidence', 'nativeSource', 'scandir', 'python'):
        value = Path(plan[name])
        require(value.is_absolute() and value.resolve(strict=True) == value)
    home = Path(plan['home'])
    evidence = Path(plan['evidence'])
    require(Path(os.environ.get('HERMES_HOME', '/opt/data')) == home
            and evidence.is_relative_to(home) and evidence != home
            and Path(plan_path).parent == evidence and Path(authorization_path).parent == evidence
            and Path(sys.executable).resolve() == Path(plan['python']))
    info = evidence.stat()
    require(info.st_uid == os.geteuid() and stat.S_ISDIR(info.st_mode)
            and not stat.S_IMODE(info.st_mode) & 0o077)
    entries = plan['entryPins']
    require(set(entries) == {'cloud_gateway_entry.py', 'cloud_native_gateway.py'})
    for name, expected in entries.items():
        candidate = Path(__file__).with_name(name)
        require(candidate.resolve(strict=True) == candidate and digest(candidate) == expected)
    native = Path(plan['nativeSource'])
    required = {'gateway/status.py', 'gateway/drain_control.py', 'hermes_cli/service_manager.py',
                'gateway/run.py', 'gateway/run_shutdown.py', 'gateway/run_bootstrap.py',
                'gateway/run_inbound.py', 'hermes_constants.py'}
    require(required <= set(plan['sourcePins']) and set(plan['slotPins']) == {'run', 'finish'})
    for name, expected in plan['sourcePins'].items():
        candidate = native / name
        require(not Path(name).is_absolute() and '..' not in Path(name).parts
                and candidate.resolve(strict=True) == candidate and digest(candidate) == expected)
    for name, expected in plan['slotPins'].items():
        candidate = Path(plan['scandir']) / plan['service'] / name
        require(candidate.resolve(strict=True) == candidate and digest(candidate) == expected)
    for key, minimum in (('releasePins', 3), ('originalReleasePins', 1)):
        require(type(plan[key]) is dict and len(plan[key]) >= minimum)
        for name, expected in plan[key].items():
            candidate = Path(name)
            require(candidate.is_absolute() and candidate.is_relative_to(home) and '..' not in candidate.parts
                    and re.fullmatch('[a-f0-9]{64}', expected))
    rollback = evidence / 'rollback'
    require(rollback.resolve(strict=True) == rollback)
    info = rollback.stat()
    require(info.st_uid == os.geteuid() and stat.S_ISDIR(info.st_mode)
            and not stat.S_IMODE(info.st_mode) & 0o077)
    return plan


def require_qualification(plan, pin, *, original=False):
    """Distinguish new Mind readback from an exact original-file restoration."""
    name = 'ORIGINAL-HELD-QUALIFICATION.json' if original else 'HELD-QUALIFICATION.json'
    result = read_private(Path(plan['evidence']) / name)
    expected = {'schema': 'onoes-cloud-original-held-qualification/v1', 'planSha256': pin,
            'verified': True, 'originalConfigurationReadback': True,
            'originalReleaseFilesReadback': True, 'nativeGatewayRetired': True,
            'modelCalls': 0} if original else {'schema': 'onoes-cloud-held-qualification/v1', 'planSha256': pin,
            'verified': True, 'hostReadback': True, 'clientReadback': True,
            'sharedMcpReadback': True, 'modelCalls': 0}
    require(result == expected)
    pins = plan['originalReleasePins'] if original else plan['releasePins']
    for name, expected in pins.items():
        candidate = Path(name)
        require(candidate.resolve(strict=True) == candidate and digest(candidate) == expected)


def _run_phase(phase, plan_path, pin, authorization_path):
    require(phase in ('stop', 'verify-stopped', 'release', 'verify-running',
                     'rehold', 'verify-rollback-stopped', 'release-original', 'verify-original-running'))
    plan = approved_inputs(plan_path, pin, authorization_path)
    # Every source is checked before a native module is imported. These imports
    # reuse the deployed image's manager/locks/status rather than another service.
    sys.path.insert(0, plan['nativeSource'])
    from hermes_constants import set_hermes_home_override
    set_hermes_home_override(Path(plan['home']))
    from hermes_cli.service_manager import S6ServiceManager
    control = Path(__file__).with_name('cloud_native_gateway.py')
    spec = importlib.util.spec_from_file_location('approved_cloud_native_gateway', control)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    binding = dict(home=plan['home'], evidence=plan['evidence'], window_id=plan['windowId'],
                   plan_sha256=pin, native_source=plan['nativeSource'], source_pins=plan['sourcePins'],
                   slot_pins=plan['slotPins'], manager=S6ServiceManager(scandir=Path(plan['scandir'])),
                   api_port=plan['apiPort'])
    gate = None
    try:
        if phase == 'stop':
            gate = module.NativeGateway(**binding)
            return gate.quiesce_and_stop(seconds=plan['stopSeconds'])
        root = Path(plan['evidence'])
        original = phase in ('release-original', 'verify-original-running')
        rollback = phase in ('rehold', 'verify-rollback-stopped') or (original and (root/'rollback/GATEWAY-STOPPED.json').exists())
        if rollback:
            # A conditional rollback is a distinct generation, never a replay of
            # an initial stop/start. It must retire the exact owner we released.
            binding.update(evidence=str(root/'rollback'), window_id=plan['windowId']+'-rollback')
        if phase == 'rehold':
            if not (root/'GATEWAY-START-ATTEMPT.json').exists():
                # Failure before release: the original stopped gate remains.
                initial = module.NativeGateway.resume_stopped(**{**binding,
                    'evidence':str(root),'window_id':plan['windowId']})
                try:require(initial.assert_stopped())
                finally:initial.close()
                return {'verified': True, 'originalGateStillHeld': True, 'modelCalls': 0}
            # Missing result after a start request is uncertain, not absence.
            started = read_private(root/'GATEWAY-STARTED.json')
            gate = module.NativeGateway(**binding)
            require(gate.identity() == (started['pid'], started['start']))
            return gate.quiesce_and_stop(seconds=plan['stopSeconds'])
        if phase in ('verify-running', 'verify-original-running'):
            gate = module.NativeGateway(**binding)
            active = Path(binding['evidence'])
            receipt = read_private(active / 'GATEWAY-STARTED.json')
            stopped = read_private(active / 'GATEWAY-STOPPED.json')
            attempt = read_private(active / 'GATEWAY-START-ATTEMPT.json')
            require(stopped['planSha256'] == pin and stopped['principal'] == gate.principal
                    and stopped['slotIdentity'] == list(gate.slot_identity)
                    and attempt['service'] == plan['service'] and attempt['automaticRetry'] is False)
            identity = gate.identity()
            require(receipt['verified'] is True and identity == (receipt['pid'], receipt['start']))
            state = gate._snapshot(identity)
            require(state.get('gateway_state') in ('running', 'degraded')
                    and state.get('desired_state') == 'running' and not os.path.lexists(gate.marker))
            require_qualification(plan, pin, original=original)
            return {'verified': True, 'sameNativeService': True, 'modelCalls': 0}
        gate = module.NativeGateway.resume_stopped(**binding)
        if phase in ('verify-stopped', 'verify-rollback-stopped'):
            require(gate.assert_stopped())
            return {'verified': True, 'nativeOwnerRetired': True, 'modelCalls': 0}
        require_qualification(plan, pin, original=original)
        return gate.release_and_start(seconds=plan['startSeconds'])
    finally:
        if gate is not None:
            gate.close()


def run_phase(phase,plan_path,pin,authorization_path):
    plan=approved_inputs(plan_path,pin,authorization_path)
    with operation_scope(plan['evidence'],pin):
        return _run_phase(phase,plan_path,pin,authorization_path)


def main():
    require(len(sys.argv) == 5)
    result = run_phase(*sys.argv[1:])
    # Only public lifecycle metadata; never credentials, config or native errors.
    print(json.dumps(result, sort_keys=True), flush=True)


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print('Cloud phase held; preserve exact receipts. Do not repeat uncertain work.', file=sys.stderr)
        print(json.dumps({'errorType':type(error).__name__,'frames':[
            {'file':Path(f.filename).name,'function':f.name,'line':f.lineno}
            for f in traceback.extract_tb(error.__traceback__)[-12:]],'messagesAndLocalsExcluded':True}),file=sys.stderr)
        raise SystemExit(1)
