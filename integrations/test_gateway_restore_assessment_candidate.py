import copy
import unittest

from gateway_restore_assessment_candidate import assess_original_restore


SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_BAD_UPPER = "A" * 64
SHA_BAD_SHORT = "a" * 63
SHA_BAD_HEX = "g" * 64


class _DictSubclass(dict):
    """Dict subclass with valid fields; must be rejected as not a plain dict."""


def base_expected():
    return {
        "planSha256": SHA_A,
        "configSha256": SHA_B,
        "originalPid": 4321,
        "originalStart": 1700000000,
        "principal": "svc-gateway",
        "slotIdentity": [7, 11],
    }


def base_observed():
    return {
        "planSha256": SHA_A,
        "configSha256": SHA_B,
        "attemptPid": 4321,
        "attemptStart": 1700000000,
        "attemptPrincipal": "svc-gateway",
        "drainedPid": 4321,
        "drainedStart": 1700000000,
        "drainedAggregateIdle": True,
        "drainedMarkerAcknowledged": True,
        "ownedMarker": True,
        "sourcePinsMatch": True,
        "slotIdentity": [7, 11],
        "supervisorFields": ["false", "-1", "false", "0", "-1"],
        "kernelPidfdErrno": 3,
        "profileIdentityAbsent": True,
        "runtimeGatewayState": "stopped",
        "runtimeDesiredState": "stopped",
        "startAttemptExists": False,
        "stoppedReceiptExists": False,
        "exactOperationActors": [],
        "operationLockHeld": True,
    }


_UNSET = object()


class _MarkerSubclass(list):
    """List subclass holding the valid marker fields; must be rejected."""


def _observed_or(value):
    return base_observed() if value is _UNSET else value


def _expected_or(value):
    return base_expected() if value is _UNSET else value


def accept(observed=_UNSET, expected=_UNSET):
    return assess_original_restore(_observed_or(observed), _expected_or(expected))


def reject(observed=_UNSET, expected=_UNSET):
    with unittest.TestCase().assertRaises(ValueError):
        assess_original_restore(_observed_or(observed), _expected_or(expected))


def mutate(field, value):
    obs = base_observed()
    obs[field] = value
    return reject(obs, base_expected())


def mutate_expected(field, value):
    exp = base_expected()
    exp[field] = value
    return reject(base_observed(), exp)


class TestAccepted(unittest.TestCase):
    def _check_disclaimers(self, result, desired):
        self.assertIs(result["eligibleForOriginalRestore"], True)
        self.assertEqual(result["proofMethod"], "post-stop-kernel-absence-and-native-clean-exit")
        self.assertIs(result["originalRetainedPidfdProof"], False)
        self.assertIs(result["originalInstallerCompleted"], False)
        self.assertIs(result["finalizeStoppedIntent"], desired == "running")
        self.assertEqual(result["planSha256"], SHA_A)
        self.assertEqual(result["originalPid"], 4321)

    def test_desired_stopped(self):
        obs = base_observed()
        obs["runtimeDesiredState"] = "stopped"
        self._check_disclaimers(accept(obs, base_expected()), "stopped")

    def test_desired_running(self):
        obs = base_observed()
        obs["runtimeDesiredState"] = "running"
        self._check_disclaimers(accept(obs, base_expected()), "running")

    def test_inputs_not_mutated(self):
        obs = base_observed()
        exp = base_expected()
        obs_copy = copy.deepcopy(obs)
        exp_copy = copy.deepcopy(exp)
        accept(obs, exp)
        self.assertEqual(obs, obs_copy)
        self.assertEqual(exp, exp_copy)


class TestIdentityRejections(unittest.TestCase):
    def test_plan_sha_mismatch(self):
        mutate("planSha256", SHA_B)

    def test_config_sha_mismatch(self):
        mutate("configSha256", SHA_A)

    def test_expected_plan_sha_mismatch_with_observed(self):
        reject(base_observed(), {**base_expected(), "planSha256": SHA_B})

    def test_pid_mismatch(self):
        mutate("attemptPid", 9999)
        mutate("drainedPid", 9999)

    def test_principal_mismatch(self):
        mutate("attemptPrincipal", "someone-else")

    def test_slot_mismatch(self):
        mutate("slotIdentity", [7, 12])

    def test_malformed_sha(self):
        mutate("planSha256", SHA_BAD_UPPER)
        mutate("configSha256", SHA_BAD_SHORT)
        mutate("planSha256", SHA_BAD_HEX)

    def test_nonmatching_starts(self):
        mutate("attemptStart", 1700000001)
        mutate("drainedStart", 1699999999)


class TestSupervisorAndKernel(unittest.TestCase):
    def test_supervisor_exitcode_nonzero(self):
        mutate("supervisorFields", ["false", "-1", "false", "1", "-1"])

    def test_supervisor_signum_nonzero(self):
        mutate("supervisorFields", ["false", "-1", "false", "0", "9"])

    def test_supervisor_up_true(self):
        mutate("supervisorFields", ["true", "-1", "false", "0", "-1"])

    def test_supervisor_wantedup_true(self):
        mutate("supervisorFields", ["false", "-1", "true", "0", "-1"])

    def test_supervisor_wrong_length(self):
        mutate("supervisorFields", ["false", "-1", "false"])

    def test_supervisor_nonstring_items(self):
        mutate("supervisorFields", [False, -1, False, 0, -1])

    def test_supervisor_list_subclass(self):
        mutate("supervisorFields", _MarkerSubclass(["false", "-1", "false", "0", "-1"]))

    def test_kernel_errno_wrong(self):
        mutate("kernelPidfdErrno", 0)

    def test_kernel_errno_bool(self):
        mutate("kernelPidfdErrno", True)

    def test_kernel_errno_nonint(self):
        mutate("kernelPidfdErrno", "3")


class TestStateAndReceipts(unittest.TestCase):
    def test_runtime_state_not_stopped(self):
        mutate("runtimeGatewayState", "running")

    def test_runtime_desired_invalid(self):
        mutate("runtimeDesiredState", "paused")

    def test_profile_identity_present(self):
        mutate("profileIdentityAbsent", False)

    def test_foreign_marker(self):
        mutate("ownedMarker", False)

    def test_drain_not_idle(self):
        mutate("drainedAggregateIdle", False)

    def test_marker_not_acknowledged(self):
        mutate("drainedMarkerAcknowledged", False)

    def test_source_pins_mismatch(self):
        mutate("sourcePinsMatch", False)

    def test_active_operation_actors(self):
        mutate("exactOperationActors", ["op-1"])

    def test_operation_lock_not_held(self):
        mutate("operationLockHeld", False)

    def test_prior_start_attempt(self):
        mutate("startAttemptExists", True)

    def test_stopped_receipt_exists(self):
        mutate("stoppedReceiptExists", True)

    def test_bool_instead_of_true(self):
        mutate("ownedMarker", 1)


class TestStructure(unittest.TestCase):
    def test_missing_observed_key(self):
        obs = base_observed()
        del obs["kernelPidfdErrno"]
        reject(obs, base_expected())

    def test_extra_observed_key(self):
        obs = base_observed()
        obs["extra"] = 1
        reject(obs, base_expected())

    def test_missing_expected_key(self):
        exp = base_expected()
        del exp["slotIdentity"]
        reject(base_observed(), exp)

    def test_extra_expected_key(self):
        exp = base_expected()
        exp["extra"] = 1
        reject(base_observed(), exp)

    def test_non_dict_inputs(self):
        reject([], base_expected())
        reject(base_observed(), "nope")
        reject(None, base_expected())
        reject(base_observed(), None)
        reject(None, None)
        reject(4321, base_expected())
        reject(base_observed(), 4321)
        reject(_DictSubclass(base_observed()), base_expected())
        reject(base_observed(), _DictSubclass(base_expected()))

    def test_nonstring_dict_key(self):
        obs = base_observed()
        obs[7] = 7
        reject(obs, base_expected())

    def test_bool_pid(self):
        mutate("attemptPid", True)
        mutate_expected("originalPid", True)

    def test_bool_slot(self):
        mutate("slotIdentity", [True, 11])
        reject(base_observed(), {**base_expected(), "slotIdentity": [7, True]})

    def test_wrong_field_types(self):
        mutate("slotIdentity", "7-11")
        mutate("supervisorFields", "false,-1,false,0,-1")
        mutate("exactOperationActors", set())
        mutate("attemptPrincipal", 5)
        mutate("planSha256", 0)

    def test_nonpositive_starts_and_pids(self):
        mutate("attemptStart", 0)
        mutate("drainedStart", -5)
        mutate("attemptPid", -1)

    def test_nonfinite_starts(self):
        mutate("attemptStart", float("inf"))
        mutate("drainedStart", float("nan"))
        reject(base_observed(), {**base_expected(), "originalStart": float("inf")})

    def test_bool_start(self):
        mutate("attemptStart", True)
        reject(base_observed(), {**base_expected(), "originalStart": False})

    def test_empty_principal(self):
        reject(base_observed(), {**base_expected(), "principal": ""})
        mutate("attemptPrincipal", "")


if __name__ == "__main__":
    unittest.main()
