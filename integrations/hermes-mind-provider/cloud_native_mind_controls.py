"""Inert bridge over existing, approved native reader/writer lifecycle APIs."""
import os
import re
import sys
import time
from pathlib import Path
from types import ModuleType

_TIMEOUT_SECONDS = 60.0


class MindRolesHeld(Exception):
    pass


def require(ok, reason):
    if not ok:
        raise MindRolesHeld(reason)


def positive(value):
    return type(value) is int and value > 0


class MindRoles:
    def __init__(self, *, evidence, retained, window):
        require(type(retained) is list, 'Caller-owned retained list required.')
        window.assert_held()
        self.window, self.retained = window, retained
        self.evidence = Path(evidence)
        require(self.evidence.is_absolute() and self.evidence.is_dir(), 'Existing evidence directory required.')
        import mesh_recovery_candidate as recovery
        import recall_process_candidate as roles
        from onoes_mind.enrollment_store import qualify_private_storage
        root = Path(window.workspace).resolve(strict=True)
        native = root / 'integrations' / 'mind-recovery-candidate'
        for module, expected in ((recovery, root / 'integrations' / 'mesh_recovery_candidate.py'),
                                 (roles, native / 'recall_process_candidate.py')):
            require(Path(module.__file__).resolve() == expected.resolve(), 'Native SDK origin mismatch.')
        qualify_private_storage(self.evidence, kind='directory')
        self.recovery, self.roles = recovery, roles
        self.modules = {str((native / name).resolve()): role for name, role in (
            ('project_service_process_candidate.py', 'writer'),
            ('reader_service_process_candidate.py', 'reader'))}

    def _inputs(self, module, descriptor, approval):
        self.window.assert_held()
        require(isinstance(module, ModuleType), 'Native module required.')
        role = self.modules.get(str(Path(module.__file__).resolve()))
        require(role is not None, 'Native role module origin mismatch.')
        require(type(descriptor) is dict and set(descriptor) == {'targetPath', 'sha256'}, 'Invalid profile descriptor.')
        require(type(approval) is dict and set(approval) == {'targetPath'}, 'Invalid approval descriptor.')
        args = descriptor['targetPath'], descriptor['sha256'], approval['targetPath']
        require(type(args[1]) is str and re.fullmatch('[a-f0-9]{64}', args[1]), 'Invalid profile digest.')
        for item in (args[0], args[2]):
            require(type(item) is str and Path(item).is_absolute(), 'Absolute profile/approval path required.')
            require(Path(item).is_file() and not Path(item).is_symlink(), 'Regular profile/approval file required.')
        checked = module.checked_profile(*args)
        require(type(checked) is tuple and len(checked) == 3, 'Native checked_profile tuple required.')
        p, base, _binding = checked
        require(type(p) is dict and type(base) is dict, 'Native profile dictionaries required.')
        ready = p.get('readyPath') if role == 'writer' else base.get('readyPath')
        paths = [p.get('attemptPath'), ready, p.get('stopPath')]
        require(all(type(x) is str and Path(x).is_absolute() for x in paths), 'Native footprint paths required.')
        require(all(not Path(x).is_symlink() for x in paths), 'Linked footprint refused.')
        return role, args, p, tuple(Path(x) for x in paths)

    def _state(self, module, args, p, paths, *, waiting=False):
        attempt, ready, stop = paths
        exists = os.path.lexists(attempt), os.path.lexists(ready)
        if not any(exists):
            run = p.get('runId')
            orphan = os.path.lexists(stop)
            if type(run) is str and re.fullmatch('[a-f0-9]{32}', run):
                orphan = orphan or os.path.lexists(stop.with_name(stop.name + '.' + run))
            require(not orphan, 'Orphan stop marker; refusing unused-slot inference.')
            return None
        if exists != (True, True):
            if waiting and exists == (True, False):
                return None
            raise MindRolesHeld('Partial native service footprint.')
        value = module.service_state(*args)
        require(type(value) is dict, 'Native state dictionary required.')
        require(positive(value.get('pid')) and positive(value.get('creationTicks')), 'Invalid native process identity.')
        require(type(value.get('runId')) is str and re.fullmatch('[a-f0-9]{32}', value['runId']), 'Invalid native run ID.')
        require(type(value.get('ready')) is bool and type(value.get('processLive')) is bool, 'Invalid native state flags.')
        require(value.get('state') in ('starting', 'running', 'stopped', 'failed'), 'Invalid native state.')
        require(not value['ready'] or (value['processLive'] and value['state'] == 'running'), 'Inconsistent ready state.')
        require(value['processLive'] or value['state'] in ('stopped', 'failed'), 'Inconsistent retired state.')
        return value

    def state(self, module, descriptor, approval):
        _role, args, p, paths = self._inputs(module, descriptor, approval)
        return self._state(module, args, p, paths)

    def _receipt(self, label, role, operation, stage, sha, **extra):
        path = self.evidence / (role + '-' + operation.upper() + '-' + label + '-' + stage + '.json')
        try:
            self.roles.private_new_json(path, dict(schema='onoes-mind-native-role-operation/v1',
                label=label, role=role, operation=operation, stage=stage, profileSHA=sha, **extra))
        except FileExistsError:
            raise MindRolesHeld('Operation attempt/result already exists; no retry.') from None

    def _operation(self, module, descriptor, approval, label, operation):
        values = self._inputs(module, descriptor, approval)
        role, args, p, paths = values
        require(type(label) is str and re.fullmatch('(old|new|restored)-' + role + '-' + operation, label), 'Invalid operation label.')
        state = self._state(module, args, p, paths)
        return values, state

    def _retain(self, module, args, pid, ticks):
        self.window.assert_held()
        argv = [sys.executable, '-I', str(Path(module.__file__).resolve()), '--profile', args[0],
                '--sha256', args[1], '--approval', args[2], '--run']
        observation = self.recovery.ProcessObservation(self.window, self.roles, pid, ticks, argv, allow_terminate=False)
        self.retained.append(observation)
        return observation

    @staticmethod
    def _same(state, pid, ticks):
        require(state is not None and (state['pid'], state['creationTicks']) == (pid, ticks), 'Native role identity drift.')

    def stop(self, module, descriptor, approval, label):
        (role, args, p, paths), state = self._operation(module, descriptor, approval, label, 'stop')
        require(state is not None and state['ready'] and state['processLive'], 'Ready native service required for stop.')
        pid, ticks = state['pid'], state['creationTicks']
        self._receipt(label, role, 'stop', 'ATTEMPT', args[1], pid=pid, creationTicks=ticks, runId=state['runId'])
        observed = self._retain(module, args, pid, ticks)
        self._same(self._state(module, args, p, paths), pid, ticks)
        self.window.assert_held()
        module.request_stop(*args)
        deadline = time.monotonic() + _TIMEOUT_SECONDS
        while observed.poll() is None:
            require(time.monotonic() < deadline, 'Graceful stop timed out; retain evidence, no kill or retry.')
            time.sleep(0.05)
        self.window.assert_held()
        final = self._state(module, args, p, paths)
        self._same(final, pid, ticks)
        require(final['state'] == 'stopped' and not final['processLive'], 'Native stopped receipt required.')
        self._receipt(label, role, 'stop', 'RESULT', args[1], pid=pid, creationTicks=ticks,
                      verified=True, kernelRetired=True, nativeExitCodeClaimed=False)
        return dict(verified=True, kernelRetired=True)

    def start(self, module, descriptor, approval, label):
        (role, args, p, paths), state = self._operation(module, descriptor, approval, label, 'start')
        require(state is None or (state['state'] == 'stopped' and not state['processLive']), 'Unused or stopped native slot required.')
        self._receipt(label, role, 'start', 'ATTEMPT', args[1])
        unknown = getattr(module, 'ServiceLaunchUnknown' if role == 'writer' else 'ReaderLaunchUnknown')
        self.window.assert_held()
        try:
            launched = module.launch_service(*args)
        except unknown as failure:
            self.retained.append(failure)
            child = getattr(failure, 'child', None)
            if child is not None:
                self.retained.append(child)
            raise
        require(type(launched) is tuple and len(launched) == 2, 'Native launch tuple required; do not retry.')
        child, ticks = launched
        self.retained.append(child)
        require(positive(getattr(child, 'pid', None)) and positive(ticks), 'Launch identity unknown; original child retained.')
        observed = self._retain(module, args, child.pid, ticks)
        deadline = time.monotonic() + _TIMEOUT_SECONDS
        while True:
            self.window.assert_held()
            require(observed.poll() is None, 'Child retired before readiness; no retry.')
            current = self._state(module, args, p, paths, waiting=True)
            if current is not None:
                self._same(current, child.pid, ticks)
                require(current['processLive'] and current['state'] in ('starting', 'running'), 'Native service failed startup.')
                if current['ready']:
                    break
            require(time.monotonic() < deadline, 'Readiness timed out; original child retained, no retry.')
            time.sleep(0.05)
        self._receipt(label, role, 'start', 'RESULT', args[1], pid=child.pid, creationTicks=ticks,
                      verified=True, readinessBoundToOwnChild=True)
        return dict(verified=True, pid=child.pid, creationTicks=ticks)
