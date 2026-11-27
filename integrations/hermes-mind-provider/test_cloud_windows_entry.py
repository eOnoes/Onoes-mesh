"""Focused unit tests for maintenance_paused in cloud_windows_entry.

No real process is launched, no executable is read, and no scheduled task is
touched. Monkeypatched digest and subprocess.run keep everything synthetic.
"""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

sys.path.insert(0, os.environ['MESH_PROVIDER_SOURCE'])

import cloud_windows_entry as entry


FIXED_POWERSHELL = 'C:/Windows/System32/WindowsPowerShell/v1.0/powershell.exe'
SYNTHETIC_POWERSHELL_SHA = 'a' * 64
SYNTHETIC_DISABLED_DEFINITION_SHA = 'b' * 64
TASK_NAME = 'ONOes Mesh Workroom Recovery'


def make_plan(powershell=FIXED_POWERSHELL,
              powershell_sha=SYNTHETIC_POWERSHELL_SHA,
              disabled_definition_sha=SYNTHETIC_DISABLED_DEFINITION_SHA):
    """Complete independent plan dictionary built only from the three allowed keys."""
    return {
        'maintenance': {
            'powershell': powershell,
            'powershellSha256': powershell_sha,
            'disabledDefinitionSha256': disabled_definition_sha,
        },
    }


class FakeCompleted:
    def __init__(self, stdout=b'', returncode=0, stderr=b''):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def install_fakes(monkeypatch, fake_run):
    """Synthetic digest (never reads a real executable) + recording fake run."""
    monkeypatch.setattr(entry, 'digest', lambda path: SYNTHETIC_POWERSHELL_SHA)
    monkeypatch.setattr(entry.subprocess, 'run', fake_run)


def recording_fake(payload, encoding='utf-8'):
    """Return (fake_run, calls). The fake never launches a process."""
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append((cmd, kwargs))
        return subprocess.CompletedProcess(cmd, 0,
                                           stdout=payload.encode(encoding),
                                           stderr=b'')

    return fake_run, calls


def task_state_json(enabled, state, definition_sha):
    return json.dumps({'enabled': enabled, 'state': state,
                       'definitionSha256': definition_sha})


@pytest.mark.parametrize('encoding', ['utf-8', 'utf-8-sig'])
def test_maintenance_accepts_exact_disabled_task(monkeypatch, encoding):
    payload = task_state_json(False, 'Disabled', SYNTHETIC_DISABLED_DEFINITION_SHA)
    fake_run, calls = recording_fake(payload, encoding)
    install_fakes(monkeypatch, fake_run)

    plan = make_plan()
    plan['maintenance']['taskName'] = 'INJECTED_MARKER_TASK_NAME'

    assert entry.maintenance_paused(plan) is True

    assert len(calls) == 1
    cmd, kwargs = calls[0]
    # Compare normalized Path identity, not raw slash spelling: str(Path(...))
    # yields Windows backslashes while FIXED_POWERSHELL uses forward slashes.
    # This keeps the full fixed-path constraint (directory + executable), not a
    # basename comparison.
    assert Path(cmd[0]) == Path(FIXED_POWERSHELL)
    assert '-NoProfile' in cmd
    assert '-NonInteractive' in cmd
    assert kwargs['stdin'] is subprocess.DEVNULL

    script = cmd[-1]
    assert TASK_NAME in script
    assert r"-TaskPath '\'" in script
    # The caller-supplied taskName must never reach the script.
    assert 'INJECTED_MARKER_TASK_NAME' not in script
    # This helper only GETs/EXPORTs the existing task; it never mutates it.
    for forbidden in ('Disable-ScheduledTask', 'Enable-ScheduledTask',
                      'Start-ScheduledTask', 'Stop-ScheduledTask',
                      'Register-ScheduledTask', 'Unregister-ScheduledTask',
                      'Set-ScheduledTask'):
        assert forbidden not in script


@pytest.mark.parametrize('case', [
    {
        'name': 'enabled-true',
        'state': {'enabled': True, 'state': 'Disabled',
                  'definitionSha256': SYNTHETIC_DISABLED_DEFINITION_SHA},
    },
    {
        'name': 'enabled-numeric-zero',
        'state': {'enabled': 0, 'state': 'Disabled',
                  'definitionSha256': SYNTHETIC_DISABLED_DEFINITION_SHA},
    },
    {
        'name': 'state-running',
        'state': {'enabled': False, 'state': 'Running',
                  'definitionSha256': SYNTHETIC_DISABLED_DEFINITION_SHA},
    },
    {
        'name': 'state-queued',
        'state': {'enabled': False, 'state': 'Queued',
                  'definitionSha256': SYNTHETIC_DISABLED_DEFINITION_SHA},
    },
    {
        'name': 'definition-drift',
        'state': {'enabled': False, 'state': 'Disabled',
                  'definitionSha256': 'c' * 64},
    },
])
def test_maintenance_rejects_running_enabled_or_drift(monkeypatch, case):
    payload = json.dumps(case['state'])
    fake_run, calls = recording_fake(payload)
    install_fakes(monkeypatch, fake_run)

    with pytest.raises(entry.PhaseHeld):
        entry.maintenance_paused(make_plan())

    # The fake invocation remains strictly read-only.
    assert len(calls) == 1
    cmd, kwargs = calls[0]
    script = cmd[-1]
    assert 'Get-ScheduledTask' in script
    assert 'Export-ScheduledTask' in script
    assert kwargs['stdin'] is subprocess.DEVNULL


def test_maintenance_bad_program_or_pin_never_launches(monkeypatch):
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append((cmd, kwargs))
        raise AssertionError('no process may launch when the program or pin is wrong')

    monkeypatch.setattr(entry, 'digest', lambda path: SYNTHETIC_POWERSHELL_SHA)
    monkeypatch.setattr(entry.subprocess, 'run', fake_run)

    # Changed PowerShell path: refused before any invocation.
    with pytest.raises(entry.PhaseHeld):
        entry.maintenance_paused(make_plan(powershell='C:/Windows/System32/WindowsPowerShell/v1.0/pwsh.exe'))

    # Wrong executable hash pin: refused before any invocation.
    with pytest.raises(entry.PhaseHeld):
        entry.maintenance_paused(make_plan(powershell_sha='d' * 64))

    assert calls == []


def test_maintenance_process_error_has_no_private_detail(monkeypatch):
    private_marker = 'SYNTHETIC-PRIVATE-DETAIL-MARKER'
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append((cmd, kwargs))
        return FakeCompleted(returncode=1, stdout=b'', stderr=private_marker.encode('utf-8'))

    monkeypatch.setattr(entry, 'digest', lambda path: SYNTHETIC_POWERSHELL_SHA)
    monkeypatch.setattr(entry.subprocess, 'run', fake_run)

    with pytest.raises(entry.PhaseHeld) as excinfo:
        entry.maintenance_paused(make_plan())

    assert len(calls) == 1
    assert private_marker not in str(excinfo.value)
