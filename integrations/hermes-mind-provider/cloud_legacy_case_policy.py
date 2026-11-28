"""Phase-1 pure validation of the cloud legacy case policy (r12/r13 test accounting).

Pure functions only: no filesystem, subprocess, network, SDK or environment access.
This validates reference-matched metadata. It is NOT live adoption, NOT a general
quarantine engine, and it proves nothing about production retirement (enforced
separately by the unchanged native window). Reference metadata is NOT proof of
retirement; r12 FAILED and r13 UNKNOWN timeout facts stay unchanged.
"""

import hashlib
import json

CASE_ID = "cyony-native-client-tests-20261126-r12-r13"
SOURCE_MANIFEST_SHA256 = (
    "30fea3c63049ef068e21169a696e5f384e6cce9a33f95c1d8710c45af37b21dc"
)

POLICY_SCHEMA = "onoes-cloud-legacy-case-policy/v1"
AUTH_SCHEMA = "onoes-cloud-install-authorization/v2"
ACCOUNTING_SCHEMA = "onoes-cloud-test-accounting/v2"
DISPOSITION_SCHEMA = "onoes-cloud-legacy-test-disposition/v1"

AUTH_OWNER = "Eddie"
AUTH_DECISION = (
    "approve_cyony_private_home_and_mesh_reader_with_exact_legacy_case_policy"
)

_IMAGE = (
    "nousresearch/hermes-agent@sha256:"
    "adb7890916de63245523492be8f68f9d2095fecbec4e2a6dab7960381f0fc002"
)

_R12_PINS = {
    "cloud_client_entry.py": "7d9d75561b525835ee6c9dcd8437a261a8a38ede1f660ebfc086a65d528bb5cf",
    "cloud_gateway_entry.py": "c9edd609826772fb4ea8bc731cb157d5904576c7f9903f99cb1c3e50c8c12fbf",
    "cloud_native_gateway.py": "b199e9539ec842afc1351ebdb5a51ac06c081dba40918849d07456902fe9c6cd",
    "native_cloud_gateway_fixture.py": "2b5e57e43888750d2a9d33d76da3acfb83e5e8d6a34fd4e5a711b3fcf5ab996f",
    "native_cloud_client_fixture.py": "100ef55c7c3bc8ea1cea23ee85521572ed72b2e32b4dfc986698036cdc1730c4",
    "cloud_client_package.py": "5f942398bbd68640fdb3b6f0b2ecd70987ddad1c453988c1edb961648b98c519",
    "cloud_curated_transfer.py": "a062e98f782c55af607df2669bcc285b7045b584b222370351a9fc46a8da6b35",
    "cloud_custody_delivery.py": "4be63e90274d91bc97da0b43a3bfeea5e7cc03a0bde8d1e9cf71ed4de41fa997",
    "portable_owner_switch.py": "aa38bd999f685f50f1a36922b36b679c6245e41e9ecfc9e919f72ca5e228eb6d",
    "owner_profile_switch.py": "4d87a23eea281892cc57862f0b91110db45b1749533aab9d623ce5e3305a6962",
}

_R13_PINS = {
    "cloud_client_entry.py": "948a5993fb038dff88e5d0867e492df872a318fe6e88f2db4927686b09a98a1d",
    "cloud_gateway_entry.py": "c9edd609826772fb4ea8bc731cb157d5904576c7f9903f99cb1c3e50c8c12fbf",
    "cloud_native_gateway.py": "b199e9539ec842afc1351ebdb5a51ac06c081dba40918849d07456902fe9c6cd",
    "native_cloud_gateway_fixture.py": "2b5e57e43888750d2a9d33d76da3acfb83e5e8d6a34fd4e5a711b3fcf5ab996f",
    "native_cloud_client_fixture.py": "100ef55c7c3bc8ea1cea23ee85521572ed72b2e32b4dfc986698036cdc1730c4",
    "cloud_client_package.py": "5f942398bbd68640fdb3b6f0b2ecd70987ddad1c453988c1edb961648b98c519",
    "cloud_curated_transfer.py": "a062e98f782c55af607df2669bcc285b7045b584b222370351a9fc46a8da6b35",
    "cloud_custody_delivery.py": "4be63e90274d91bc97da0b43a3bfeea5e7cc03a0bde8d1e9cf71ed4de41fa997",
    "portable_owner_switch.py": "aa38bd999f685f50f1a36922b36b679c6245e41e9ecfc9e919f72ca5e228eb6d",
    "owner_profile_switch.py": "4d87a23eea281892cc57862f0b91110db45b1749533aab9d623ce5e3305a6962",
}

# Actor order is r12 then r13. FAILED / UNKNOWN outcomes, UNKNOWN
# immutableContainerId and UNKNOWN retirement are deliberately preserved.
EXPECTED_ACTORS = (
    {
        "label": "r12",
        "reservedName": "mesh-mind-client-fixture-20261126-r12",
        "requestedImage": _IMAGE,
        "originalAttemptSha256": "4e66faf0cfc0476631f37df9d8e2256dd379e25f162caa690f9b36e6b594f12d",
        "submittedSourcePins": _R12_PINS,
        "seedBundleSha256": "c31222e0233116092b2687cada7fad932fdd39fb49a0ca013527f6ecdef00ea8",
        "observedOutcome": "FAILED_CLIENT_RETURN_RECORDED_NOT_RETIREMENT",
        "immutableContainerId": "UNKNOWN",
        "retirement": "UNKNOWN",
        "holdReleased": False,
        "rerunAllowed": False,
        "cleanupAllowed": False,
    },
    {
        "label": "r13",
        "reservedName": "mesh-mind-client-fixture-20261126-r13",
        "requestedImage": _IMAGE,
        "originalAttemptSha256": "9284c61c71d7cbcff8ef8e7b428752bb9b1c72ffdca1c06b3281595eefa8a3fd",
        "submittedSourcePins": _R13_PINS,
        "seedBundleSha256": "c31222e0233116092b2687cada7fad932fdd39fb49a0ca013527f6ecdef00ea8",
        "observedOutcome": "UNKNOWN_600_SECOND_LOCAL_TIMEOUT",
        "immutableContainerId": "UNKNOWN",
        "retirement": "UNKNOWN",
        "holdReleased": False,
        "rerunAllowed": False,
        "cleanupAllowed": False,
    },
)

REQUIRED_ASSUMPTIONS = (
    "original_recipe_effective",
    "anonymous_volume_separate",
    "historical_ssh_attribution",
    "transitive_dependencies_bounded",
    "residual_resource_usage",
)

EXPECTED_OTHER_TESTS = {"remaining": 0, "verified": True}


class PolicyHeld(ValueError):
    """Raised for any validation failure. Message is constant and sanitized."""

    MESSAGE = "legacy case policy validation failed: sanitized rejection"

    def __init__(self):
        super().__init__(self.MESSAGE)


def _hold():
    raise PolicyHeld()


def _canonical_json(value):
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )
    except (TypeError, ValueError):
        _hold()


def _json_safe(value):
    """Reject non-JSON shapes and any NaN/Infinity before any comparison."""
    _canonical_json(value)


def _sha256_hex(value):
    if type(value) is not str:
        _hold()
    if len(value) != 64:
        _hold()
    if any(char not in "0123456789abcdef" for char in value):
        _hold()
    return value


def _exact_keys(obj, keys):
    if type(obj) is not dict:
        _hold()
    if set(obj) != set(keys):
        _hold()
    return obj


def _exact_fields(got, want):
    """Compare a dict against a reference dict: exact keys, types, values.

    Type checks precede value comparison so bool never passes where an int is
    required and vice versa.
    """
    if type(got) is not dict:
        _hold()
    if set(got) != set(want):
        _hold()
    for key in want:
        if type(got[key]) is not type(want[key]):
            _hold()
        if got[key] != want[key]:
            _hold()


def _exact_flat_fields(got, want):
    """Same as _exact_fields, plus nested list/dict values are rejected."""
    _exact_fields(got, want)
    for key in want:
        if type(got[key]) in (list, dict):
            _hold()


def _exact_list(value, expected):
    """Require the exact reference list of dicts (order, keys, types, values)."""
    if type(value) is not list:
        _hold()
    if len(value) != len(expected):
        _hold()
    for got, want in zip(value, expected):
        _exact_fields(got, want)


def _exact_string_list(value, expected):
    """Require the exact reference list of strings (order, type, value)."""
    if type(value) is not list:
        _hold()
    if len(value) != len(expected):
        _hold()
    for got, want in zip(value, expected):
        if type(got) is not str or got != want:
            _hold()


def _validate_policy(policy):
    _json_safe(policy)
    _exact_keys(
        policy,
        ("schema", "caseId", "sourceManifestSha256", "actors",
         "residualAssumptionsAccepted"),
    )
    if policy["schema"] != POLICY_SCHEMA:
        _hold()
    if policy["caseId"] != CASE_ID:
        _hold()
    if policy["sourceManifestSha256"] != SOURCE_MANIFEST_SHA256:
        _hold()
    actors = policy["actors"]
    if type(actors) is not list or len(actors) != len(EXPECTED_ACTORS):
        _hold()
    for got, want in zip(actors, EXPECTED_ACTORS):
        if type(got) is not dict:
            _hold()
        if set(got) != set(want):
            _hold()
        # submittedSourcePins is a nested dict of strings; compare it apart
        # from the flat scalar fields so type checks stay strict.
        pins = got["submittedSourcePins"]
        want_pins = want["submittedSourcePins"]
        if type(pins) is not dict or set(pins) != set(want_pins):
            _hold()
        for key in want_pins:
            if type(pins[key]) is not str or pins[key] != want_pins[key]:
                _hold()
        flat_got = {k: v for k, v in got.items() if k != "submittedSourcePins"}
        flat_want = {k: v for k, v in want.items() if k != "submittedSourcePins"}
        _exact_fields(flat_got, flat_want)
    _exact_string_list(policy["residualAssumptionsAccepted"],
                       REQUIRED_ASSUMPTIONS)


def _validate_accounting(accounting):
    """TEST accounting only; production retirement is not provable here."""
    _json_safe(accounting)
    _exact_keys(accounting, ("schema", "otherTests", "quarantinedTests"))
    if accounting["schema"] != ACCOUNTING_SCHEMA:
        _hold()
    other = accounting["otherTests"]
    _exact_keys(other, ("remaining", "verified"))
    if type(other["remaining"]) is not int or other["remaining"] != 0:
        _hold()
    if other["verified"] is not True:
        _hold()
    _exact_list(
        accounting["quarantinedTests"],
        [
            {
                "label": a["label"],
                "originalAttemptSha256": a["originalAttemptSha256"],
                "retirement": "UNKNOWN",
            }
            for a in EXPECTED_ACTORS
        ],
    )


def _validate_authorization(authorization, plan_sha256, policy_sha256):
    _json_safe(authorization)
    _exact_flat_fields(
        authorization,
        {
            "schema": AUTH_SCHEMA,
            "owner": AUTH_OWNER,
            "decision": AUTH_DECISION,
            "planSha256": plan_sha256,
            "legacyCaseSha256": policy_sha256,
        },
    )
    # Exact schema/decision above reject the old v1 approval and any
    # development/source-review approval; exact hash fields bind this run.


def _validate_hashes(plan_sha256, policy_sha256):
    plan_sha256 = _sha256_hex(plan_sha256)
    policy_sha256 = _sha256_hex(policy_sha256)
    if plan_sha256 == policy_sha256:
        _hold()
    return plan_sha256, policy_sha256


def _policy_hash_matches(policy, policy_sha256):
    canonical = _canonical_json(policy).encode("ascii")
    digest = hashlib.sha256(canonical).hexdigest()
    if digest != policy_sha256:
        _hold()


def validate_policy(policy, accounting, authorization, *, plan_sha256,
                    policy_sha256):
    """Validate all inputs strictly; return a NEW JSON-safe disposition.

    Inputs are never mutated. Hashes are supplied by the installer, already
    verified against their files; this pure function does not read files and
    does not pretend to. Any malformed shape, type or extra/missing field is
    rejected with PolicyHeld carrying only a sanitized constant message.
    """
    plan_sha256, policy_sha256 = _validate_hashes(plan_sha256, policy_sha256)
    _validate_policy(policy)
    _policy_hash_matches(policy, policy_sha256)
    _validate_accounting(accounting)
    _validate_authorization(authorization, plan_sha256, policy_sha256)
    quarantined = [dict(entry) for entry in accounting["quarantinedTests"]]
    return {
        "schema": DISPOSITION_SCHEMA,
        "caseId": CASE_ID,
        "planSha256": plan_sha256,
        "policySha256": policy_sha256,
        "quarantinedTests": quarantined,
        "productionRetirement": "REQUIRED_SEPARATELY",
        "namesReserved": True,
        "rerunAllowed": False,
        "cleanupAllowed": False,
    }