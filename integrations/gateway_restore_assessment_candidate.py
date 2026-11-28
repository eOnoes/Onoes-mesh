"""Assessment of whether an original gateway process may be restored.

Pure function over trusted coordinator-supplied observations. It gathers no
proof, authorizes nothing, and never executes a restore. Standard library
only; no file, network, or process access.
"""

_SHA_LEN = 64
_HEX_DIGITS = frozenset("0123456789abcdef")
_EXPECTED_SUPERVISOR_FIELDS = ["false", "-1", "false", "0", "-1"]
_ESRCH = 3

_EXPECTED_KEYS = (
    "planSha256",
    "configSha256",
    "originalPid",
    "originalStart",
    "principal",
    "slotIdentity",
)

_OBSERVED_KEYS = (
    "planSha256",
    "configSha256",
    "attemptPid",
    "attemptStart",
    "attemptPrincipal",
    "drainedPid",
    "drainedStart",
    "drainedAggregateIdle",
    "drainedMarkerAcknowledged",
    "ownedMarker",
    "sourcePinsMatch",
    "slotIdentity",
    "supervisorFields",
    "kernelPidfdErrno",
    "profileIdentityAbsent",
    "runtimeGatewayState",
    "runtimeDesiredState",
    "startAttemptExists",
    "stoppedReceiptExists",
    "exactOperationActors",
    "operationLockHeld",
)


def _require_dict(value, label):
    if type(value) is not dict:
        raise ValueError("%s must be a plain dict" % label)


def _check_exact_keys(data, required, label):
    missing = [k for k in required if k not in data]
    extra = [k for k in data if k not in required]
    if missing:
        raise ValueError("%s missing keys: %s" % (label, ", ".join(sorted(missing))))
    if extra:
        raise ValueError("%s unexpected keys: %s" % (label, ", ".join(sorted(map(str, extra)))))


def _require_sha(value, label):
    if type(value) is not str:
        raise ValueError("%s must be a string" % label)
    if len(value) != _SHA_LEN:
        raise ValueError("%s must be a 64-character SHA256 hex string" % label)
    if any(ch not in _HEX_DIGITS for ch in value):
        raise ValueError("%s must be lowercase hex" % label)


def _require_positive_int(value, label):
    if type(value) is not int:
        raise ValueError("%s must be an exact int (bool not allowed)" % label)
    if value <= 0:
        raise ValueError("%s must be positive" % label)


def _require_positive_start(value, label):
    if type(value) is bool or type(value) not in (int, float):
        raise ValueError("%s must be an exact int or float (bool not allowed)" % label)
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            raise ValueError("%s must be finite" % label)
    if value <= 0:
        raise ValueError("%s must be positive" % label)


def _require_nonempty_str(value, label):
    if type(value) is not str:
        raise ValueError("%s must be a string" % label)
    if not value:
        raise ValueError("%s must be nonempty" % label)


def _require_slot(value, label):
    if type(value) is not list or len(value) != 2:
        raise ValueError("%s must be a list of exactly two positive ints" % label)
    for i, item in enumerate(value):
        _require_positive_int(item, "%s[%d]" % (label, i))


def _require_true(value, label):
    if value is not True:
        raise ValueError("%s must be exactly True" % label)


def _require_false(value, label):
    if value is not False:
        raise ValueError("%s must be exactly False" % label)


def _validate_expected(expected):
    _require_dict(expected, "expected")
    _check_exact_keys(expected, _EXPECTED_KEYS, "expected")
    _require_sha(expected["planSha256"], "expected.planSha256")
    _require_sha(expected["configSha256"], "expected.configSha256")
    _require_positive_int(expected["originalPid"], "expected.originalPid")
    _require_positive_start(expected["originalStart"], "expected.originalStart")
    _require_nonempty_str(expected["principal"], "expected.principal")
    _require_slot(expected["slotIdentity"], "expected.slotIdentity")


def _validate_observed(observed):
    _require_dict(observed, "observed")
    _check_exact_keys(observed, _OBSERVED_KEYS, "observed")


def assess_original_restore(observed, expected):
    """Assess coordinator observations for original-restore eligibility.

    Both arguments must be plain dicts with exactly the specified keys.
    Malformed data raises ValueError. Inputs are never mutated.
    """
    _validate_expected(expected)
    _validate_observed(observed)

    o = observed

    for key in ("planSha256", "configSha256"):
        _require_sha(o[key], "observed.%s" % key)
        if o[key] != expected[key]:
            raise ValueError("observed.%s does not match expected.%s" % (key, key))

    for key in ("attemptPid", "drainedPid"):
        _require_positive_int(o[key], "observed.%s" % key)
        if o[key] != expected["originalPid"]:
            raise ValueError("observed.%s does not match expected.originalPid" % key)

    for key in ("attemptStart", "drainedStart"):
        _require_positive_start(o[key], "observed.%s" % key)
        if o[key] != expected["originalStart"]:
            raise ValueError("observed.%s does not match expected.originalStart" % key)

    _require_nonempty_str(o["attemptPrincipal"], "observed.attemptPrincipal")
    if o["attemptPrincipal"] != expected["principal"]:
        raise ValueError("observed.attemptPrincipal does not match expected.principal")

    _require_slot(o["slotIdentity"], "observed.slotIdentity")
    if o["slotIdentity"] != expected["slotIdentity"]:
        raise ValueError("observed.slotIdentity does not match expected.slotIdentity")

    if type(o["supervisorFields"]) is not list or any(type(item) is not str for item in o["supervisorFields"]) or o["supervisorFields"] != _EXPECTED_SUPERVISOR_FIELDS:
        raise ValueError("observed.supervisorFields must be exactly %s" % (_EXPECTED_SUPERVISOR_FIELDS,))

    if type(o["kernelPidfdErrno"]) is not int or o["kernelPidfdErrno"] != _ESRCH:
        raise ValueError("observed.kernelPidfdErrno must be exactly 3 (ESRCH); absent process is not retained-original-pidfd proof")

    for key in ("drainedAggregateIdle", "drainedMarkerAcknowledged", "ownedMarker", "sourcePinsMatch", "profileIdentityAbsent", "operationLockHeld"):
        _require_true(o[key], "observed.%s" % key)

    for key in ("startAttemptExists", "stoppedReceiptExists"):
        _require_false(o[key], "observed.%s" % key)

    if type(o["exactOperationActors"]) is not list or len(o["exactOperationActors"]) != 0:
        raise ValueError("observed.exactOperationActors must be an empty list")

    if o["runtimeGatewayState"] != "stopped":
        raise ValueError("observed.runtimeGatewayState must be 'stopped'")

    desired = o["runtimeDesiredState"]
    if desired not in ("running", "stopped"):
        raise ValueError("observed.runtimeDesiredState must be 'running' or 'stopped'")

    return {
        "eligibleForOriginalRestore": True,
        "proofMethod": "post-stop-kernel-absence-and-native-clean-exit",
        "originalRetainedPidfdProof": False,
        "originalInstallerCompleted": False,
        "finalizeStoppedIntent": bool(desired == "running"),
        "planSha256": expected["planSha256"],
        "originalPid": expected["originalPid"],
    }
