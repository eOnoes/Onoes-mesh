"""Phase-1 exact-case gate for cloud_legacy_case_policy (synthetic inputs only).

Pure-function tests: no filesystem, subprocess, network or live store. Fixture
policy/auth/accounting derive from the module's published constants, so these
tests do not by themselves detect constant drift; the module constants were
crosschecked separately and independently by the coordinator.
"""
import copy
import hashlib
import json

import pytest

import cloud_legacy_case_policy as policy


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False)


def canonical_hash(value):
    return hashlib.sha256(canonical(value).encode("ascii")).hexdigest()


def fixture_policy():
    return {
        "schema": policy.POLICY_SCHEMA,
        "caseId": policy.CASE_ID,
        "sourceManifestSha256": policy.SOURCE_MANIFEST_SHA256,
        "actors": copy.deepcopy(list(policy.EXPECTED_ACTORS)),
        "residualAssumptionsAccepted": list(policy.REQUIRED_ASSUMPTIONS),
    }


def fixture_accounting():
    return {
        "schema": policy.ACCOUNTING_SCHEMA,
        "otherTests": {"remaining": 0, "verified": True},
        "quarantinedTests": [
            {"label": a["label"],
             "originalAttemptSha256": a["originalAttemptSha256"],
             "retirement": "UNKNOWN"}
            for a in policy.EXPECTED_ACTORS
        ],
    }


PLAN_HASH = "a" * 64


def fixture_auth(plan_sha256=PLAN_HASH, policy_sha256=None):
    return {
        "schema": policy.AUTH_SCHEMA,
        "owner": policy.AUTH_OWNER,
        "decision": policy.AUTH_DECISION,
        "planSha256": plan_sha256,
        "legacyCaseSha256": policy_sha256 if policy_sha256 is not None
        else canonical_hash(fixture_policy()),
    }


def validate(policy_value, accounting, authorization, plan_sha256=PLAN_HASH,
             policy_sha256=None):
    if policy_sha256 is None:
        policy_sha256 = canonical_hash(policy_value)
    return policy.validate_policy(policy_value, accounting, authorization,
                                  plan_sha256=plan_sha256,
                                  policy_sha256=policy_sha256)


def test_canonical_ascii_json_hash_matches_spec():
    body = canonical(fixture_policy())
    assert body == json.dumps(json.loads(body), sort_keys=True,
                              separators=(",", ":"))
    assert body.isascii()
    assert hashlib.sha256(body.encode("ascii")).hexdigest() == \
        canonical_hash(fixture_policy())


def test_correct_inputs_yield_quarantine_disposition():
    p, a = fixture_policy(), fixture_accounting()
    ph = canonical_hash(p)
    d = validate(p, a, fixture_auth(policy_sha256=ph), policy_sha256=ph)
    assert d["schema"] == policy.DISPOSITION_SCHEMA
    assert d["caseId"] == policy.CASE_ID
    assert d["planSha256"] == PLAN_HASH and d["policySha256"] == ph
    assert d["productionRetirement"] == "REQUIRED_SEPARATELY"
    assert d["namesReserved"] is True
    assert d["rerunAllowed"] is False and d["cleanupAllowed"] is False
    # Not a retirement or production claim anywhere in the disposition.
    assert "RETIRED" not in json.dumps(d)
    assert "retired" not in json.dumps(d).lower()


def test_owner_authorization_bound_to_both_hashes():
    p = fixture_policy()
    ph = canonical_hash(p)
    auth = fixture_auth(policy_sha256=ph)
    assert validate(p, fixture_accounting(), auth, policy_sha256=ph)
    for field, value in (("planSha256", "b" * 64), ("legacyCaseSha256", "c" * 64)):
        shifted = dict(auth)
        shifted[field] = value
        with pytest.raises(policy.PolicyHeld):
            validate(p, fixture_accounting(), shifted, policy_sha256=ph)


def test_accounting_exact_other_tests_and_quarantined_unknowns():
    a = fixture_accounting()
    assert a["otherTests"] == {"remaining": 0, "verified": True}
    assert type(a["otherTests"]["remaining"]) is int
    assert a["otherTests"]["verified"] is True
    assert len(a["quarantinedTests"]) == 2
    for entry in a["quarantinedTests"]:
        assert entry["retirement"] == "UNKNOWN"
        assert set(entry) == {"label", "originalAttemptSha256", "retirement"}


def test_inputs_unchanged_and_output_copy_isolation():
    p, a = fixture_policy(), fixture_accounting()
    p_before, a_before = copy.deepcopy(p), copy.deepcopy(a)
    ph = canonical_hash(p)
    auth = fixture_auth(policy_sha256=ph)
    auth_before = copy.deepcopy(auth)
    d = validate(p, a, auth, policy_sha256=ph)
    d["quarantinedTests"][0]["retirement"] = "RETIRED"
    d["caseId"] = "tampered"
    assert p == p_before and a == a_before and auth == auth_before
    assert all(entry["retirement"] == "UNKNOWN"
               for entry in fixture_accounting()["quarantinedTests"])


def test_no_remaining_zero_or_verified_retirement_claim_at_top():
    p, a = fixture_policy(), fixture_accounting()
    ph = canonical_hash(p)
    d = validate(p, a, fixture_auth(policy_sha256=ph), policy_sha256=ph)
    assert "remaining" not in d and "verified" not in d
    assert d["productionRetirement"] == "REQUIRED_SEPARATELY"


def _altered_case(**mutations):
    """Mutate the policy, then recompute its canonical hash AND the auth
    legacyCaseSha256 so a rejection proves exact-case binding, not staleness."""
    p = fixture_policy()
    for path, value in mutations.items():
        head, _, tail = path.partition(".")
        if tail:
            p["actors"][int(head)][tail] = value
        else:
            p[head] = value
    ph = canonical_hash(p)
    return p, ph, fixture_auth(policy_sha256=ph)


@pytest.mark.parametrize("path,value", [
    ("caseId", "cyony-native-client-tests-20261126-r12-r14"),
    ("caseId", policy.CASE_ID.upper()),
    ("caseId", 42),
    ("sourceManifestSha256", "f" * 64),
    ("sourceManifestSha256", policy.SOURCE_MANIFEST_SHA256.upper()),
    ("0.originalAttemptSha256", "0" * 64),
    ("0.seedBundleSha256", "1" * 64),
    ("1.seedBundleSha256", "2" * 64),
    ("0.requestedImage", "nousresearch/hermes-agent:latest"),
    ("1.requestedImage", "nousresearch/hermes-agent@sha256:" + "a" * 64),
    ("0.observedOutcome", "SUCCESS"),
    ("1.observedOutcome", "SUCCESS"),
    ("0.retirement", "RETIRED"),
    ("1.retirement", "RETIRED"),
    ("0.immutableContainerId", "guessed-cid-12345"),
    ("1.immutableContainerId", "guessed-cid-12345"),
    ("0.holdReleased", True),
    ("1.holdReleased", True),
    ("0.rerunAllowed", True),
    ("1.rerunAllowed", True),
    ("0.cleanupAllowed", True),
    ("1.cleanupAllowed", True),
    ("0.reservedName", "mesh-mind-client-fixture-20261126-r13"),
    ("0.label", "r13"),
    ("1.label", "r12"),
])
def test_case_identity_mutations_rejected_even_with_recomputed_hashes(path, value):
    p, ph, auth = _altered_case(**{path: value})
    with pytest.raises(policy.PolicyHeld):
        validate(p, fixture_accounting(), auth, policy_sha256=ph)


def test_actor_order_swapped_rejected_with_recomputed_hashes():
    p = fixture_policy()
    p["actors"][0], p["actors"][1] = p["actors"][1], p["actors"][0]
    ph = canonical_hash(p)
    with pytest.raises(policy.PolicyHeld):
        validate(p, fixture_accounting(), fixture_auth(policy_sha256=ph),
                 policy_sha256=ph)


def test_actor_missing_extra_or_renamed_production_writer_rejected():
    p = fixture_policy()
    p["actors"] = p["actors"][:1]
    ph = canonical_hash(p)
    with pytest.raises(policy.PolicyHeld):
        validate(p, fixture_accounting(), fixture_auth(policy_sha256=ph),
                 policy_sha256=ph)
    p = fixture_policy()
    p["actors"] = p["actors"] + [copy.deepcopy(p["actors"][0])]
    ph = canonical_hash(p)
    with pytest.raises(policy.PolicyHeld):
        validate(p, fixture_accounting(), fixture_auth(policy_sha256=ph),
                 policy_sha256=ph)
    p = fixture_policy()
    p["actors"][0]["reservedName"] = "mesh-mind-production-writer"
    ph = canonical_hash(p)
    with pytest.raises(policy.PolicyHeld):
        validate(p, fixture_accounting(), fixture_auth(policy_sha256=ph),
                 policy_sha256=ph)


def test_bool_int_substitutions_in_case_fields_rejected():
    for path, value in (("0.holdReleased", 0), ("0.rerunAllowed", 1),
                        ("1.cleanupAllowed", 0), ("0.observedOutcome", 1)):
        p, ph, auth = _altered_case(**{path: value})
        with pytest.raises(policy.PolicyHeld):
            validate(p, fixture_accounting(), auth, policy_sha256=ph)


@pytest.mark.parametrize("assumptions", [
    ["original_recipe_effective", "anonymous_volume_separate",
     "historical_ssh_attribution", "transitive_dependencies_bounded"],
    list(policy.REQUIRED_ASSUMPTIONS) + ["retirement_implied"],
    list(policy.REQUIRED_ASSUMPTIONS)[::-1],
    list(policy.REQUIRED_ASSUMPTIONS)[:-1] + ["residual_resource_use"],
    [True, "anonymous_volume_separate", "historical_ssh_attribution",
     "transitive_dependencies_bounded", "residual_resource_usage"],
])
def test_missing_or_altered_residual_assumption_rejected(assumptions):
    p = fixture_policy()
    p["residualAssumptionsAccepted"] = assumptions
    ph = canonical_hash(p)
    with pytest.raises(policy.PolicyHeld):
        validate(p, fixture_accounting(), fixture_auth(policy_sha256=ph),
                 policy_sha256=ph)


def test_source_pin_change_inside_case_rejected_with_recomputed_hashes():
    p = fixture_policy()
    key = next(iter(p["actors"][0]["submittedSourcePins"]))
    p["actors"][0]["submittedSourcePins"][key] = "9" * 64
    ph = canonical_hash(p)
    with pytest.raises(policy.PolicyHeld):
        validate(p, fixture_accounting(), fixture_auth(policy_sha256=ph),
                 policy_sha256=ph)


@pytest.mark.parametrize("mutate", [
    lambda a: a["otherTests"].update(remaining=1),
    lambda a: a["otherTests"].update(verified=False),
    lambda a: a["otherTests"].update(verified=1),
    lambda a: a["otherTests"].update(remaining=True),
    lambda a: a["otherTests"].pop("verified"),
    lambda a: a["otherTests"].update(verifiedRetired=True),
    lambda a: a["quarantinedTests"].append(
        {"label": "r14", "originalAttemptSha256": "d" * 64,
         "retirement": "UNKNOWN"}),
    lambda a: a["quarantinedTests"].pop(),
    lambda a: a["quarantinedTests"][0].update(retirement="RETIRED"),
    lambda a: a["quarantinedTests"][0].update(label="production-writer"),
])
def test_bad_accounting_rejected(mutate):
    a = fixture_accounting()
    mutate(a)
    p = fixture_policy()
    ph = canonical_hash(p)
    with pytest.raises(policy.PolicyHeld):
        validate(p, a, fixture_auth(policy_sha256=ph), policy_sha256=ph)


def test_wrong_auth_schema_decision_or_window_hash_rejected():
    p = fixture_policy()
    ph = canonical_hash(p)
    auth = fixture_auth(policy_sha256=ph)
    for field, value in (
        ("schema", "onoes-cloud-install-authorization/v1"),
        ("decision", "approve_cyony_private_home_and_mesh_reader"),
        ("owner", "NotEddie"),
    ):
        shifted = dict(auth)
        shifted[field] = value
        with pytest.raises(policy.PolicyHeld):
            validate(p, fixture_accounting(), shifted, policy_sha256=ph)
    v1 = {"schema": "onoes-cloud-install-authorization/v1", "owner": "Eddie",
          "decision": "approve_cyony_private_home_and_mesh_reader",
          "planSha256": PLAN_HASH}
    with pytest.raises(policy.PolicyHeld):
        validate(p, fixture_accounting(), v1, policy_sha256=ph)
    other_window = {"schema": policy.AUTH_SCHEMA, "owner": "Eddie",
                    "decision": policy.AUTH_DECISION,
                    "planSha256": "e" * 64, "legacyCaseSha256": ph}
    with pytest.raises(policy.PolicyHeld):
        validate(p, fixture_accounting(), other_window, policy_sha256=ph)
    extra = dict(auth)
    extra["scope"] = "everything"
    with pytest.raises(policy.PolicyHeld):
        validate(p, fixture_accounting(), extra, policy_sha256=ph)


def test_wrong_policy_hash_supplied_rejected():
    p = fixture_policy()
    ph = canonical_hash(p)
    with pytest.raises(policy.PolicyHeld):
        validate(p, fixture_accounting(), fixture_auth(policy_sha256=ph),
                 policy_sha256="c" * 64)


def test_plan_and_policy_hash_must_differ():
    p = fixture_policy()
    ph = canonical_hash(p)
    with pytest.raises(policy.PolicyHeld):
        validate(p, fixture_accounting(), fixture_auth(policy_sha256=ph),
                 plan_sha256=ph, policy_sha256=ph)


@pytest.mark.parametrize("shape", [
    None, [], "policy-string", 7, 3.5, True, {},
    {"schema": policy.POLICY_SCHEMA},
    {**fixture_policy(), "extra": "field"},
    {**fixture_policy(), "actors": None},
    {**fixture_policy(), "actors": {}},
    {**fixture_policy(), "actors": ["r12", "r13"]},
    {**fixture_policy(), "residualAssumptionsAccepted": None},
])
def test_malformed_policy_shape_sanitizes_to_policy_held(shape):
    ph = canonical_hash(fixture_policy())
    with pytest.raises(policy.PolicyHeld) as caught:
        validate(shape, fixture_accounting(), fixture_auth(policy_sha256=ph),
                 policy_sha256=ph)
    assert caught.value.MESSAGE == "legacy case policy validation failed: sanitized rejection"
    assert str(shape)[:40] not in str(caught.value)


@pytest.mark.parametrize("bad_hash", [
    None, 0, True, "", "a" * 63, "a" * 65, "z" * 64,
    "A" * 64, " " + "a" * 63, "a" * 61 + " ", "ab" * 31 + "ag",
])
def test_whitespace_plus_minus_uppercase_nonhex_and_bool_hashes_rejected(bad_hash):
    bad_text = bad_hash if isinstance(bad_hash, str) else "a" * 64
    good_text = "b" * 64 if bad_text == "a" * 64 else "a" * 64
    with pytest.raises(policy.PolicyHeld):
        validate(fixture_policy(), fixture_accounting(),
                 fixture_auth(policy_sha256=good_text),
                 plan_sha256=bad_text, policy_sha256=good_text)
    with pytest.raises(policy.PolicyHeld):
        validate(fixture_policy(), fixture_accounting(),
                 fixture_auth(policy_sha256=good_text),
                 plan_sha256=good_text, policy_sha256=bad_text)
