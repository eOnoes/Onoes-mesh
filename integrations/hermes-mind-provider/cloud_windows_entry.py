"""Cold-SDK entry for existing Windows cutover controls; no startup changes.

The enclosing finite installer pauses the existing recovery task and delivers
the exact owner-approved plan. Each phase verifies that pause independently,
holds the existing launcher mutex and retains the native process identities.
"""
from contextlib import ExitStack
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys


class PhaseHeld(RuntimeError):
    pass


def require(ok):
    if not ok:
        raise PhaseHeld('Windows cloud phase differs from the reviewed window; preserve evidence')


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result)
            result[key] = value
        return result
    result = json.loads(Path(path).read_bytes(), object_pairs_hook=unique)
    require(type(result) is dict)
    return result


def load(path, name, pin):
    path = Path(path)
    require(path.is_absolute() and path.resolve(strict=True) == path and digest(path) == pin)
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    sys.modules[name] = result
    spec.loader.exec_module(result)
    return result


def maintenance_paused(plan):
    """Read-only check of the existing task; never disable/start/register it."""
    powershell = Path(plan['maintenance']['powershell'])
    require(powershell == Path('C:/Windows/System32/WindowsPowerShell/v1.0/powershell.exe')
            and digest(powershell) == plan['maintenance']['powershellSha256'])
    # Fixed task identity. No command text, task name or shell fragment is
    # accepted from a model, profile or command-line argument.
    script = r"""$ErrorActionPreference='Stop'
$t=Get-ScheduledTask -TaskName 'ONOes Mesh Workroom Recovery' -TaskPath '\'
$xml=Export-ScheduledTask -TaskName 'ONOes Mesh Workroom Recovery' -TaskPath '\'
$sha=[System.Security.Cryptography.SHA256]::Create()
$hex=([BitConverter]::ToString($sha.ComputeHash([Text.Encoding]::UTF8.GetBytes($xml)))).Replace('-','').ToLowerInvariant()
@{enabled=[bool]$t.Settings.Enabled;state=[string]$t.State;definitionSha256=$hex}|ConvertTo-Json -Compress
"""
    done = subprocess.run([str(powershell), '-NoLogo', '-NoProfile', '-NonInteractive', '-Command', script],
                          stdin=subprocess.DEVNULL, capture_output=True, timeout=20,
                          creationflags=subprocess.CREATE_NO_WINDOW)
    require(done.returncode == 0)
    state = json.loads(done.stdout.decode('utf-8-sig'))
    require(state['enabled'] is False and state['state'] not in ('Running', 'Queued')
            and state['definitionSha256'] == plan['maintenance']['disabledDefinitionSha256'])
    return True


def approved_inputs(phase, plan_path, pin, authorization_path):
    require(os.name == 'nt' and sys.flags.isolated == 1 and sys.dont_write_bytecode
            and type(pin) is str and re.fullmatch('[a-f0-9]{64}', pin))
    require(digest(plan_path) == pin)
    plan = read(plan_path)
    require(read(authorization_path) == {'schema':'onoes-cloud-windows-authorization/v1',
            'planSha256':pin,'owner':'Eddie','decision':'approve_scoped_cloud_mind_window'})
    require(plan['schema'] == 'onoes-cloud-windows-phases/v1'
            and plan['agentId'] == 'cyony' and plan['modelCalls'] == 0
            and phase in ('inspect-old','retire-old','start-new','inspect-new','retire-new',
                          'restore-original','start-original'))
    require(Path(sys.executable).resolve() == Path(plan['python']).resolve(strict=True))
    workspace = Path(plan['workspace'])
    require(workspace.is_absolute() and workspace.resolve(strict=True) == workspace)
    require(digest(__file__) == plan['entrySha256'])
    selected = plan['new' if phase in ('start-new','inspect-new','retire-new') else 'old']
    sdk=Path(selected['mindSource'])
    require(sdk.is_absolute() and sdk.resolve(strict=True)==sdk)
    required={workspace/'integrations'/name for name in ('mesh_startup_candidate.py','mesh_launcher_window.py','mesh_recovery_candidate.py')}
    required.update(workspace/'integrations/mind-recovery-candidate'/name for name in (
        'project_service_process_candidate.py','reader_service_process_candidate.py',
        'recall_process_candidate.py'))
    required.update((sdk/'onoes_mind').rglob('*.py'))
    required.update((sdk/'onoes_mind/migrations').glob('*.sql'))
    require(sdk/'onoes_mind/__init__.py' in required
            and all(str(path) in selected['sourcePins'] for path in required))
    for name, expected in selected['sourcePins'].items():
        candidate = Path(name)
        require(candidate.is_absolute() and candidate.resolve(strict=True) == candidate
                and digest(candidate) == expected)
    # This check happens before SDK imports, attempt receipts or process actions.
    maintenance_paused(plan)
    return plan, selected


def run_phase(phase, plan_path, pin, authorization_path):
    plan, selected = approved_inputs(phase, plan_path, pin, authorization_path)
    workspace = Path(plan['workspace']);sdk = Path(selected['mindSource'])
    require(sdk.is_absolute() and sdk.resolve(strict=True) == sdk)
    sys.path[:0] = [str(workspace/'integrations'), str(workspace/'integrations/mind-recovery-candidate'),str(sdk)]
    import onoes_mind
    require(Path(onoes_mind.__file__).resolve().parents[1] == sdk)
    from onoes_mind.enrollment_store import qualify_private_storage
    for p in (plan_path,authorization_path):qualify_private_storage(Path(p),kind='file')
    evidence = qualify_private_storage(Path(plan['evidence']))
    import mesh_startup_candidate as startup
    import project_service_process_candidate as writer
    import reader_service_process_candidate as reader
    import recall_process_candidate as roles
    import mesh_recovery_candidate as recovery
    from mesh_launcher_window import MeshLauncherWindow
    require(startup.ROOT == workspace)
    cutover = load(Path(__file__).with_name('cloud_windows_cutover.py'),
                   'approved_cloud_windows_cutover',plan['cutoverSha256'])
    controls = load(plan['nativeControlsPath'],'approved_cloud_native_mind_roles',plan['nativeControlsSha256'])
    retained = []
    with ExitStack() as stack:
        window = stack.enter_context(MeshLauncherWindow(workspace,plan['launcherSha256']))
        require(not window.abandoned and maintenance_paused(plan))
        control = controls.MindRoles(evidence=evidence,retained=retained)
        def close_observations():
            # Observation cleanup never terminates a gateway or memory service.
            for actor in reversed(retained):
                if isinstance(actor,recovery.ProcessObservation):actor.close()
        stack.callback(close_observations)
        common = dict(window=window,startup=startup,roles=roles,
            startup_path=selected['startupPath'],startup_sha=selected['startupSha256'],evidence=evidence)
        if phase.startswith('inspect-'):
            handoff,profiles,_,_,_=cutover.selection(**common)
            owner=startup.owner_record(window,handoff,profiles,roles)
            require(owner and owner['live'] and owner['mode']=='connected')
            return {'verified':True,'ownerSha256':owner['receiptSha256'],
                    'pid':owner['record']['pid'],'creationTicks':owner['record']['creationTicks']}
        if phase == 'restore-original':
            return cutover.restore_owner_beforeimage(**common,expected_owner_sha256=plan['originalOwnerSha256'])
        common.update(writer=writer,reader=reader,control=control,retained=retained)
        if phase in ('retire-old','retire-new'):
            expected=plan['originalOwnerSha256'] if phase=='retire-old' else read(evidence/'new-start-RESULT.json')['ownerSha256']
            return cutover.retire_selection(**common,label='old' if phase=='retire-old' else 'new',
                                            expected_owner_sha256=expected)
        return cutover.start_selection(**common,label='new' if phase=='start-new' else 'restored')


def main():
    require(len(sys.argv)==5)
    print(json.dumps(run_phase(*sys.argv[1:]),sort_keys=True),flush=True)


if __name__=='__main__':
    try:main()
    except Exception:
        print('Windows cloud phase held; retain exact receipts. Do not repeat uncertain work.',file=sys.stderr)
        raise SystemExit(1)
