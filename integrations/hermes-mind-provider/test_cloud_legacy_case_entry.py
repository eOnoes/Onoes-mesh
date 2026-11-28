"""Exact legacy-case window tests for cloud_install_entry (synthetic data only).

All fixture I/O lives under tmp_path: the policy helper is copied there and
entry.__file__ is moved so the adjacent pinned helper is this owned copy. Only
entry.digest is patched for the two synthetic original-attempt files, mapped by
their exact Path values to the retained historical hashes; every other path
forwards to the real digest. The validator and the assertions are never patched.
"""
import copy
import hashlib
import json
from pathlib import Path

import pytest

import cloud_install_entry as entry
import cloud_legacy_case_policy as policy

SOURCE = Path(entry.__file__).resolve().parent
HELPER_BYTES = (SOURCE / "cloud_legacy_case_policy.py").read_bytes()
ATTEMPT_HASHES = {a["label"]: a["originalAttemptSha256"]
                  for a in policy.EXPECTED_ACTORS}
PLAN_SCHEMA = "onoes-cloud-install-window/v1"
V1_SCHEMA = "onoes-cloud-install-authorization/v1"
V2_SCHEMA = "onoes-cloud-install-authorization/v2"
V1_DECISION = "approve_cyony_private_home_and_mesh_reader"
ACCOUNTING_SCHEMA = "onoes-cloud-test-accounting/v2"
DISPOSITION_SCHEMA = "onoes-cloud-legacy-test-disposition/v1"


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False)


def raw_hash(body):
    return hashlib.sha256(body).hexdigest()


def policy_fixture():
    return {"schema": policy.POLICY_SCHEMA, "caseId": policy.CASE_ID,
            "sourceManifestSha256": policy.SOURCE_MANIFEST_SHA256,
            "actors": copy.deepcopy(list(policy.EXPECTED_ACTORS)),
            "residualAssumptionsAccepted": list(policy.REQUIRED_ASSUMPTIONS)}


def accounting_body():
    return {"schema": ACCOUNTING_SCHEMA,
            "otherTests": {"remaining": 0, "verified": True},
            "quarantinedTests": [
                {"label": a["label"],
                 "originalAttemptSha256": a["originalAttemptSha256"],
                 "retirement": "UNKNOWN"} for a in policy.EXPECTED_ACTORS]}


def v2_auth(plan_sha256, policy_sha256):
    return {"schema": V2_SCHEMA, "owner": policy.AUTH_OWNER,
            "decision": policy.AUTH_DECISION, "planSha256": plan_sha256,
            "legacyCaseSha256": policy_sha256}


def v1_auth(plan_sha256):
    return {"schema": V1_SCHEMA, "owner": policy.AUTH_OWNER,
            "decision": V1_DECISION, "planSha256": plan_sha256}


@pytest.fixture
def window(tmp_path, monkeypatch):
    """Synthetic legacy plan confined to tmp_path, with an owned helper copy."""
    helper = tmp_path / "cloud_legacy_case_policy.py"
    helper.write_bytes(HELPER_BYTES)
    monkeypatch.setattr(entry, "__file__",
                        str(tmp_path / "cloud_install_entry.py"))
    helper_hash = raw_hash(HELPER_BYTES)

    policy_path = tmp_path / "legacy-case-policy.json"
    policy_body = canonical(policy_fixture()).encode("ascii")
    policy_path.write_bytes(policy_body)
    policy_sha = raw_hash(policy_body)

    accounting_path = tmp_path / "test-accounting.json"
    accounting_body_bytes = json.dumps(accounting_body(), sort_keys=True).encode()
    accounting_path.write_bytes(accounting_body_bytes)

    attempts = {}
    for label, expected in ATTEMPT_HASHES.items():
        attempt_path = tmp_path / (label + "-original-attempt.json")
        attempt_path.write_bytes(
            json.dumps({"fixture": label + "-synthetic-original"}).encode())
        attempts[label] = {"path": str(attempt_path), "sha256": expected}

    plan = {"schema": PLAN_SCHEMA,
            "legacyCasePolicy": {"path": str(policy_path),
                                 "sha256": policy_sha,
                                 "originalAttempts": attempts},
            "remoteTestRetirement": {"path": str(accounting_path),
                                     "sha256": raw_hash(accounting_body_bytes)},
            "sourcePins": {str(helper): helper_hash}}
    plan_hash = raw_hash(canonical(plan).encode("ascii"))

    real_digest = entry.digest
    synthetic = {Path(item["path"]): ATTEMPT_HASHES[label]
                 for label, item in attempts.items()}

    def patched_digest(path):
        return synthetic.get(Path(path), real_digest(path))

    monkeypatch.setattr(entry, "digest", patched_digest)
    loads = []
    real_load = entry.load

    def spy_load(path, name, pin):
        loads.append((str(path), name, pin))
        return real_load(path, name, pin)

    monkeypatch.setattr(entry, "load", spy_load)
    return {"tmp": tmp_path, "plan": plan, "pin": plan_hash,
            "auth": v2_auth(plan_hash, policy_sha), "helper": helper,
            "helper_hash": helper_hash, "policy_path": policy_path,
            "policy_body": policy_body, "policy_sha": policy_sha,
            "accounting_path": accounting_path,
            "accounting_body": accounting_body_bytes, "attempts": attempts,
            "loads": loads, "real_digest": real_digest}


def call(window, plan=None, pin=None, auth=None):
    return entry.test_accounting(plan if plan is not None else window["plan"],
                                 pin if pin is not None else window["pin"],
                                 auth if auth is not None else window["auth"])


def repin(window, plan, body):
    """Write new policy bytes, pin the descriptor and recompute v2 auth."""
    window["policy_path"].write_bytes(body)
    plan["legacyCasePolicy"]["sha256"] = raw_hash(body)
    pin = raw_hash(canonical(plan).encode("ascii"))
    return plan, pin, v2_auth(pin, plan["legacyCasePolicy"]["sha256"])


def test_canonical_window_yields_exact_quarantine_disposition(window):
    d = call(window)
    assert d["schema"] == DISPOSITION_SCHEMA
    assert d["caseId"] == policy.CASE_ID
    assert d["planSha256"] == window["pin"]
    assert d["policySha256"] == window["policy_sha"]
    assert d["productionRetirement"] == "REQUIRED_SEPARATELY"
    assert d["namesReserved"] is True and d["rerunAllowed"] is False
    assert [q["retirement"] for q in d["quarantinedTests"]] == ["UNKNOWN", "UNKNOWN"]
    assert window["loads"] == [(str(window["helper"]),
                                "cloud_legacy_case_policy", window["helper_hash"])]


def test_descriptor_is_exact_path_sha256_original_attempts(window):
    descriptor = window["plan"]["legacyCasePolicy"]
    assert set(descriptor) == {"path", "sha256", "originalAttempts"}
    assert set(descriptor["originalAttempts"]) == {"r12", "r13"}
    for label, item in descriptor["originalAttempts"].items():
        assert set(item) == {"path", "sha256"}
        actor = next(a for a in policy.EXPECTED_ACTORS if a["label"] == label)
        assert item["sha256"] == actor["originalAttemptSha256"]


def test_null_or_empty_descriptor_holds_without_fallback(window):
    for descriptor in (None, {}):
        plan = copy.deepcopy(window["plan"])
        plan["legacyCasePolicy"] = descriptor
        plan_hash = raw_hash(canonical(plan).encode("ascii"))
        auth = v2_auth(plan_hash, "b" * 64)
        with pytest.raises(entry.InstallHeld):
            entry.owner_authorization(plan, plan_hash, auth)
        with pytest.raises(entry.InstallHeld):
            entry.test_accounting(plan, plan_hash, auth)


def test_changed_missing_or_extra_descriptor_key_holds(window):
    plan = copy.deepcopy(window["plan"])
    plan["legacyCasePolicy"]["extra"] = "x"
    plan_hash = raw_hash(canonical(plan).encode("ascii"))
    with pytest.raises(entry.InstallHeld):
        entry.test_accounting(plan, plan_hash,
                              v2_auth(plan_hash,
                                      plan["legacyCasePolicy"]["sha256"]))
    for key in ("path", "sha256", "originalAttempts"):
        plan = copy.deepcopy(window["plan"])
        del plan["legacyCasePolicy"][key]
        plan_hash = raw_hash(canonical(plan).encode("ascii"))
        auth = v2_auth(plan_hash, plan["legacyCasePolicy"].get("sha256", "b" * 64))
        with pytest.raises(entry.InstallHeld):
            entry.test_accounting(plan, plan_hash, auth)


def test_old_v1_development_or_wrong_hash_auth_rejected(window):
    with pytest.raises(entry.InstallHeld):
        entry.owner_authorization(window["plan"], window["pin"],
                                  v1_auth(window["pin"]))
    with pytest.raises(entry.InstallHeld):
        call(window, auth=v1_auth(window["pin"]))
    with pytest.raises(entry.InstallHeld):
        call(window, auth={**window["auth"], "decision": "source_review"})
    with pytest.raises(entry.InstallHeld):
        entry.owner_authorization(window["plan"], window["pin"],
                                  v2_auth("f" * 64, window["policy_sha"]))
    with pytest.raises(entry.InstallHeld):
        call(window, auth=v2_auth(window["pin"], "e" * 64))


def test_missing_helper_sourcepin_holds_before_load(window):
    plan = copy.deepcopy(window["plan"])
    del plan["sourcePins"][str(window["helper"])]
    plan_hash = raw_hash(canonical(plan).encode("ascii"))
    with pytest.raises(entry.InstallHeld):
        entry.test_accounting(plan, plan_hash,
                              v2_auth(plan_hash, window["policy_sha"]))
    assert window["loads"] == []


def test_mismatched_helper_pin_refuses_before_helper_execution(window):
    # entry.load itself checks the SHA before exec_module, so a mismatched pin
    # may reach the (spied) load call but must never execute the helper.
    helper = window["helper"]
    helper.write_bytes(HELPER_BYTES
                       + b"\nraise AssertionError('stale-pin helper executed')\n")
    plan = copy.deepcopy(window["plan"])
    plan["sourcePins"][str(helper)] = "0" * 64
    plan_hash = raw_hash(canonical(plan).encode("ascii"))
    with pytest.raises(entry.InstallHeld):
        entry.test_accounting(plan, plan_hash,
                              v2_auth(plan_hash, window["policy_sha"]))
    assert not any("stale-pin helper executed" in repr(item)
                   for item in window["loads"])


def test_duplicate_or_noncanonical_or_newline_policy_holds(window):
    path = window["policy_path"]
    shared = json.loads(path.read_bytes())
    plan, pin, auth = repin(window, copy.deepcopy(window["plan"]),
                            b'{"schema":"dup-schema",' + canonical(shared)[1:].encode("ascii"))
    with pytest.raises(entry.InstallHeld):
        entry.test_accounting(plan, pin, auth)
    body = canonical(policy_fixture()).encode("ascii")
    plan, pin, auth = repin(window, copy.deepcopy(window["plan"]), body + b"\n")
    with pytest.raises(entry.InstallHeld):
        entry.test_accounting(plan, pin, auth)
    plan, pin, auth = repin(window, copy.deepcopy(window["plan"]),
                            json.dumps(policy_fixture(), indent=2).encode("ascii"))
    with pytest.raises(entry.InstallHeld):
        entry.test_accounting(plan, pin, auth)


def test_exact_case_and_extra_actor_policy_rejected_by_gate(window):
    tampered = policy_fixture()
    tampered["actors"] = tampered["actors"] + [copy.deepcopy(tampered["actors"][0])]
    plan, pin, auth = repin(window, copy.deepcopy(window["plan"]),
                            canonical(tampered).encode("ascii"))
    with pytest.raises(entry.InstallHeld):
        entry.test_accounting(plan, pin, auth)


def test_tampered_policy_accounting_or_raw_original_holds(window, monkeypatch):
    path = window["policy_path"]
    tampered = policy_fixture()
    tampered["caseId"] = tampered["caseId"] + "-tampered"
    plan, pin, auth = repin(window, copy.deepcopy(window["plan"]),
                            canonical(tampered).encode("ascii"))
    with pytest.raises(entry.InstallHeld):
        entry.test_accounting(plan, pin, auth)
    plan = copy.deepcopy(window["plan"])
    bad = json.dumps({**accounting_body(),
                      "otherTests": {"remaining": 1, "verified": False}},
                     sort_keys=True).encode()
    window["accounting_path"].write_bytes(bad)
    plan["remoteTestRetirement"]["sha256"] = raw_hash(bad)
    plan_hash = raw_hash(canonical(plan).encode("ascii"))
    with pytest.raises(entry.InstallHeld):
        entry.test_accounting(plan, plan_hash,
                              v2_auth(plan_hash, window["policy_sha"]))

    def hostile_digest(p):
        if Path(p) in {Path(item["path"])
                       for item in window["attempts"].values()}:
            return "0" * 64
        return window["real_digest"](p)

    monkeypatch.setattr(entry, "digest", hostile_digest)
    with pytest.raises(entry.InstallHeld):
        call(window)


@pytest.mark.parametrize("mutate", [
    lambda a: a.pop("r13"),
    lambda a: a.update(r14={"path": "unused", "sha256": "c" * 64}),
    lambda a: a["r12"].pop("sha256"),
    lambda a: a["r12"].update(sha256="9" * 64),
    lambda a: a["r13"].pop("path"),
])
def test_changed_missing_or_extra_attempt_descriptor_holds(window, mutate):
    plan = copy.deepcopy(window["plan"])
    mutate(plan["legacyCasePolicy"]["originalAttempts"])
    plan_hash = raw_hash(canonical(plan).encode("ascii"))
    with pytest.raises(entry.InstallHeld):
        entry.test_accounting(plan, plan_hash,
                              v2_auth(plan_hash,
                                      plan["legacyCasePolicy"]["sha256"]))


def test_strict_without_legacy_accepts_genuine_zero_and_old_v1_auth(window):
    plan = copy.deepcopy(window["plan"])
    del plan["legacyCasePolicy"]
    genuine = {"remaining": 0, "verified": True}
    body = json.dumps(genuine, sort_keys=True).encode()
    window["accounting_path"].write_bytes(body)
    plan["remoteTestRetirement"]["sha256"] = raw_hash(body)
    plan_hash = raw_hash(canonical(plan).encode("ascii"))
    assert entry.test_accounting(plan, plan_hash, v1_auth(plan_hash)) is None
    assert window["loads"] == []


def test_strict_without_genuine_proof_fails_and_never_loads_policy(window):
    plan = copy.deepcopy(window["plan"])
    del plan["legacyCasePolicy"]
    body = json.dumps({"remaining": 1, "verified": True}, sort_keys=True).encode()
    window["accounting_path"].write_bytes(body)
    plan["remoteTestRetirement"]["sha256"] = raw_hash(body)
    plan_hash = raw_hash(canonical(plan).encode("ascii"))
    with pytest.raises(entry.InstallHeld):
        entry.test_accounting(plan, plan_hash, v1_auth(plan_hash))
    assert window["loads"] == []


class _FakeLauncher:
    abandoned = False

    def assert_held(self):
        return True


class _FakeTask:
    def assert_paused(self):
        return True


class _Roles:
    def __init__(self, alive):
        self._alive = alive

    def same_process_alive(self, pid, creation_ticks):
        return self._alive


def _production_window(tmp_path, *, result, alive):
    """CombinedWindow via __new__ with synthetic root/workspace only."""
    windows = tmp_path / "windows"
    windows.mkdir()
    workspace = tmp_path / "copied-mesh"
    (workspace / "integrations").mkdir(parents=True)
    owner_path = windows / "old-owner.json"
    owner_body = json.dumps({"fixture": "production-owner"},
                            sort_keys=True).encode()
    owner_path.write_bytes(owner_body)
    owner_sha = raw_hash(owner_body)
    (windows / "old-retire-ATTEMPT.json").write_bytes(json.dumps(
        {"ownerSha256": owner_sha, "pid": 33, "creationTicks": 330,
         "peers": {"peer": {"pid": 44, "creationTicks": 440}}},
        sort_keys=True).encode())
    if result is not None:
        (windows / "old-retire-RESULT.json").write_bytes(
            json.dumps(result, sort_keys=True).encode())
    window = entry.CombinedWindow.__new__(entry.CombinedWindow)
    window.plan = {"workspace": str(workspace)}
    window.root = {"windows": windows}
    window.task = _FakeTask()
    window.roles = _Roles(alive)
    window.test_disposition = {
        "schema": DISPOSITION_SCHEMA, "caseId": policy.CASE_ID,
        "planSha256": "a" * 64, "policySha256": "b" * 64,
        "quarantinedTests": [
            {"label": a["label"],
             "originalAttemptSha256": a["originalAttemptSha256"],
             "retirement": "UNKNOWN"} for a in policy.EXPECTED_ACTORS],
        "productionRetirement": "REQUIRED_SEPARATELY", "namesReserved": True,
        "rerunAllowed": False, "cleanupAllowed": False}
    return window


def test_assert_retired_requires_actual_old_retirement_result(tmp_path):
    window = _production_window(tmp_path, result=None, alive=False)
    # The unchanged read() raises FileNotFoundError for the missing RESULT file.
    with pytest.raises((entry.InstallHeld, FileNotFoundError)):
        window.assert_retired(_FakeLauncher())


def test_assert_retired_rejects_result_with_actor_still_alive(tmp_path):
    window = _production_window(tmp_path, alive=True,
                                result={"verified": True,
                                        "ownerSha256": raw_hash(json.dumps({"fixture": "production-owner"}, sort_keys=True).encode())})
    with pytest.raises(entry.InstallHeld):
        window.assert_retired(_FakeLauncher())


def test_assert_retired_accepts_result_with_all_actors_dead(tmp_path):
    owner_sha = raw_hash(json.dumps({"fixture": "production-owner"},
                                    sort_keys=True).encode())
    window = _production_window(tmp_path, alive=False,
                                result={"verified": True, "ownerSha256": owner_sha})
    assert window.assert_retired(_FakeLauncher()) is True


def test_optional_synthetic_disposition_cannot_waive_assert_retired(tmp_path):
    window = _production_window(tmp_path, result=None, alive=False)
    assert window.test_disposition["productionRetirement"] == "REQUIRED_SEPARATELY"
    with pytest.raises((entry.InstallHeld, FileNotFoundError)):
        entry.CombinedWindow.assert_retired(window, _FakeLauncher())
