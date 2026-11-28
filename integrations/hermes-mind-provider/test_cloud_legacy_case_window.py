"""Composition-seam tests: real entry gates + real NativePhases + finite window.

Synthetic orchestration coverage only. All inputs are tmp_path-owned fake files;
no deployed cloud, model call or real credential is touched. The real
entry.test_accounting, entry.CombinedWindow.assert_retired and
entry.CombinedWindow.hold_for_rollback run unpatched; the cases.window fixture
retains its limited synthetic original-attempt hash mapping.
"""
import copy
import json
from pathlib import Path

import pytest

import cloud_install_entry as entry
from cloud_install_window import CloudWindowHeld, install_once
from cloud_phase_runner import NativePhases

import test_cloud_legacy_case_entry as cases
# Explicit fixture import: pytest discovers fixtures only from the test module
# namespace (or conftest), so re-export the existing cases.window fixture here.
from test_cloud_legacy_case_entry import window
from test_cloud_install_window import Adapter, SECRET, receipts

TRANSPORT_MARKER = "synthetic-private-transport-value-must-not-reach-receipts"


class CompositionAdapter(Adapter):
    """Real preflight (accounting + actual NativePhases construction), then the
    existing synthetic operations. install_source and hold_for_rollback route
    through the actual CombinedWindow gate; nothing else is real.

    retire_windows is a synthetic stand-in for the actual production retirement
    (the real windows/retire task operations are out of this seam's scope), so
    the real retirement evidence must already be valid at source-install time.
    """

    def __init__(self, plan, pin, auth, transport_dir, production=None):
        super().__init__()
        self.plan = plan
        self.pin = pin
        self.auth = auth
        self.transport_dir = Path(transport_dir)
        self.transport_dir.mkdir()
        self.production = production
        self.disposition = None
        self.phases = None
        # Separate marker list: install_once's step() journal only appends to
        # adapter.calls when the SYNTHETIC operation runs, so this records that
        # the actual source gate itself was reached even when it refuses.
        self.source_gate_checks = []
        self.hold_rollback_gate = True
        self.rollback_gate_checks = []

    def preflight(self, pin, evidence):
        self.calls.append('preflight')
        self.disposition = entry.test_accounting(self.plan, self.pin, self.auth)
        self.phases = NativePhases(self.plan, self.pin, self.auth, self.transport_dir)
        return True

    def install_source(self):
        if self.production is not None:
            self.source_gate_checks.append('source-install')
            entry.CombinedWindow.assert_retired(self.production, cases._FakeLauncher())
        return Adapter.__getattr__(self, 'install_source')()

    def hold_for_rollback(self):
        if self.production is not None:
            # Uncertainty guard first: the real hold_for_rollback refuses while
            # any *-TRANSPORT-UNKNOWN.json exists in the transport root, before
            # any gateway rehold or task/window field is consulted.
            self.production.root['transport'] = self.transport_dir
            if self.hold_rollback_gate:
                self.rollback_gate_checks.append("production-retirement")
                entry.CombinedWindow.assert_retired(self.production, cases._FakeLauncher())
            self.rollback_gate_checks.append("transport-uncertainty")
            return entry.CombinedWindow.hold_for_rollback(self.production)
        return Adapter.__getattr__(self, 'hold_for_rollback')()


def extended_plan(window):
    """cases.window plan plus the constants the actual NativePhases constructor
    demands. Nothing else changes; hash and v2 auth are recomputed exactly."""
    plan = copy.deepcopy(window["plan"])
    plan["schema"] = cases.PLAN_SCHEMA
    plan["agentId"] = "cyony"
    plan["readerPrincipal"] = "context-cyony"
    plan["sharedProject"] = "onoes-mesh"
    plan["modelCalls"] = 0
    plan["maintenanceTask"] = "ONOes Mesh Workroom Recovery"
    pin = cases.raw_hash(cases.canonical(plan).encode("ascii"))
    auth = cases.v2_auth(pin, plan["legacyCasePolicy"]["sha256"])
    return plan, pin, auth


def make_adapter(window, tmp_path, production=None):
    plan, pin, auth = extended_plan(window)
    adapter = CompositionAdapter(plan, pin, auth, tmp_path / "transport", production)
    return adapter, pin


def prepare_production(tmp_path, *, alive):
    """Actual synthetic production object FIRST, so old-owner.json exists before
    any owner hash is computed; the result is then written with the real save."""
    production_root = tmp_path / "case-production"
    production_root.mkdir()
    production = cases._production_window(production_root, result=None, alive=alive)
    return production_root, production


def valid_retire_result(production_root):
    """ownerSha256 computed from the ACTUAL old-owner.json bytes, never arbitrary.

    The entry digest is patched only for the two synthetic original-attempt
    files, so this real digest of the synthetic owner file is consistent with
    the unchanged assert_retired digest check.
    """
    return {"verified": True,
            "ownerSha256": entry.digest(production_root / "windows" / "old-owner.json")}


def write_synthetic_json(path, value):
    """Write only tmp_path fixture data, like cases._production_window.

    Native private-storage writes are outside this synthetic orchestration seam.
    Actual accounting, retirement and transport-uncertainty gates stay unpatched.
    """
    Path(path).write_bytes(json.dumps(value, sort_keys=True).encode("utf-8"))


def write_retire_result(production_root):
    write_synthetic_json(production_root / "windows" / "old-retire-RESULT.json",
                         valid_retire_result(production_root))


def ordered_before(calls, first, second):
    return first in calls and second in calls and calls.index(first) < calls.index(second)


def test_valid_v2_case_with_real_retirement_proof_reaches_finite_complete(window, tmp_path):
    production_root, production = prepare_production(tmp_path, alive=False)
    write_retire_result(production_root)
    adapter, pin = make_adapter(window, tmp_path, production)
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    result = install_once(adapter, evidence, pin)
    assert result == {"installed": True, "restored": False, "modelCalls": 0}
    # The real accounting accepted the real v2 auth and the actual NativePhases
    # constructor accepted the same auth for this composition.
    assert adapter.disposition["schema"] == cases.DISPOSITION_SCHEMA
    assert adapter.disposition["planSha256"] == pin
    assert adapter.phases is not None and adapter.phases.plan["agentId"] == "cyony"
    assert (adapter.disposition["quarantinedTests"][0]["retirement"] == "UNKNOWN"
            and adapter.disposition["productionRetirement"] == "REQUIRED_SEPARATELY"
            and adapter.disposition["namesReserved"] is True
            and adapter.disposition["rerunAllowed"] is False
            and adapter.disposition["cleanupAllowed"] is False)
    calls = adapter.calls
    assert ordered_before(calls, 'retire_windows', 'install_source')
    assert ordered_before(calls, 'install_source', 'admit_cyony')
    assert ordered_before(calls, 'admit_cyony', 'deliver_client')
    assert json.loads((evidence / "COMPLETE.json").read_bytes())["realModelAcceptance"] == "NOT_RUN"


@pytest.mark.parametrize("auth_kind", ["v1", "development"])
def test_old_v1_or_development_auth_refuses_at_actual_preflight(window, tmp_path, auth_kind):
    plan, pin, auth = extended_plan(window)
    if auth_kind == "v1":
        auth = cases.v1_auth(pin)
    else:
        auth = {**auth, "schema": "onoes-cloud-install-authorization/v2-development",
                "decision": "development_only"}
    adapter = CompositionAdapter(plan, pin, auth, tmp_path / "transport")
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    with pytest.raises(CloudWindowHeld):
        install_once(adapter, evidence, pin)
    # Refused inside the real entry gate: no WINDOW-ATTEMPT, no synthetic step.
    assert not list(evidence.iterdir())
    assert adapter.calls == ["preflight"]
    assert adapter.phases is None and adapter.disposition is None


def test_missing_old_retire_result_holds_source_gate_and_rollback(window, tmp_path):
    production_root, production = prepare_production(tmp_path, alive=False)
    # RESULT stays absent: the approved legacy policy never waives the real gate.
    adapter, pin = make_adapter(window, tmp_path, production)
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    with pytest.raises(CloudWindowHeld):
        install_once(adapter, evidence, pin)
    assert (evidence / "source-install-FAILED.json").exists()
    assert (evidence / "ROLLBACK-HELD.json").exists()
    assert not (evidence / "COMPLETE.json").exists()
    assert not (evidence / "RESTORED.json").exists()
    # The actual source gate was reached (marker appended before the real
    # assert_retired) yet its refusal stopped the synthetic mutation:
    assert adapter.source_gate_checks == ['source-install']
    assert adapter.rollback_gate_checks == ["production-retirement"]
    assert (production_root / "windows" / "old-retire-RESULT.json").exists() is False
    # Rollback hold invoked the same actual gate, so no pretend revocation or
    # restoration operation ran:
    assert not any(name in adapter.calls for name in
                   ('install_source', 'admit_cyony', 'revoke_new_access',
                    'restore_configuration', 'restore_windows',
                    'release_original_gateway'))


def test_alive_production_actor_fails_actual_gate_despite_correct_owner_hash(window, tmp_path):
    production_root, production = prepare_production(tmp_path, alive=True)
    write_retire_result(production_root)
    adapter, pin = make_adapter(window, tmp_path, production)
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    with pytest.raises(CloudWindowHeld):
        install_once(adapter, evidence, pin)
    # Not an unrelated wrong-hash failure: the exact actual retirement result
    # (owner hash, verified) was accepted; only same-process-alive refused.
    attempt = json.loads((production_root / "windows" / "old-retire-ATTEMPT.json").read_bytes())
    result = json.loads((production_root / "windows" / "old-retire-RESULT.json").read_bytes())
    assert result["ownerSha256"] == attempt["ownerSha256"]
    assert result["verified"] is True
    assert adapter.source_gate_checks == ['source-install']
    assert adapter.rollback_gate_checks == ["production-retirement"]
    assert not any(name in adapter.calls for name in
                   ('install_source', 'admit_cyony', 'revoke_new_access',
                    'restore_configuration', 'restore_windows'))
    assert (evidence / "ROLLBACK-HELD.json").exists()


def test_transport_unknown_blocks_real_hold_before_any_synthetic_rollback(window, tmp_path):
    production_root, production = prepare_production(tmp_path, alive=False)
    write_retire_result(production_root)
    adapter, pin = make_adapter(window, tmp_path, production)
    # Uncertainty mode: the real hold_for_rollback must be what refuses, so the
    # already-verified source gate is not repeated ahead of its transport guard.
    adapter.hold_rollback_gate = False
    gateway_calls = []

    def forbidden_gateway(*args, **kwargs):
        gateway_calls.append((args, kwargs))
        raise AssertionError("synthetic gateway must remain untouched")

    production.gateway = forbidden_gateway
    # Synthetic sequence stays default: new_access becomes True only through the
    # actual synthetic admit_cyony as install_once progresses to qualify_held.
    evidence = tmp_path / "evidence"
    evidence.mkdir()

    def uncertain_qualify():
        write_synthetic_json(adapter.transport_dir / "client-deliver-TRANSPORT-UNKNOWN.json",
                   {"errorType": "TimeoutError", "marker": TRANSPORT_MARKER,
                    "remoteActorRetirement": "NOT_PROVEN", "automaticRetry": False})
        raise entry.InstallHeld("Native transport uncertain; reconcile existing receipts")

    adapter.qualify_held = uncertain_qualify
    with pytest.raises(CloudWindowHeld):
        install_once(adapter, evidence, pin)
    assert list(adapter.transport_dir.glob("*-TRANSPORT-UNKNOWN.json"))
    assert adapter.rollback_gate_checks == ["transport-uncertainty"]
    assert gateway_calls == []
    # Uncertainty mode: the real hold_for_rollback checked the transport unknown
    # FIRST and refused, so no synthetic gateway rehold/revoke/config restore ran.
    assert adapter.source_gate_checks == ['source-install']
    assert not any(name in adapter.calls for name in
                   ('hold_for_rollback', 'revoke_new_access', 'restore_configuration',
                    'restore_windows', 'release_original_gateway'))
    assert adapter.records == ["original-record", "curated-record"]
    assert adapter.new_access is True and adapter.config == "new"
    assert (evidence / "ROLLBACK-HELD.json").exists()
    assert not (evidence / "COMPLETE.json").exists()
    assert not (evidence / "RESTORED.json").exists()
    held = json.loads((evidence / "ROLLBACK-HELD.json").read_bytes())
    assert held["automaticRetry"] is False
    assert json.loads((evidence / "WINDOW-FAILED.json").read_bytes())["automaticRetry"] is False
    assert SECRET.encode() not in receipts(evidence)
    assert TRANSPORT_MARKER.encode() not in receipts(evidence)
    assert not any(TRANSPORT_MARKER.encode() in p.read_bytes()
                   for p in evidence.iterdir())
    before = {p.name: p.read_bytes() for p in evidence.iterdir()}
    calls = list(adapter.calls)
    with pytest.raises(CloudWindowHeld):
        install_once(adapter, evidence, pin)
    assert adapter.calls == calls
    assert before == {p.name: p.read_bytes() for p in evidence.iterdir()}
