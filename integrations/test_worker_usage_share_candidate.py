"""Unittests for worker_usage_share_candidate.usage_share."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from worker_usage_share_candidate import usage_share


def _usage(uncached, cached, output):
    return {
        "uncached_input_tokens": uncached,
        "cached_input_tokens": cached,
        "output_tokens": output,
    }


class TestUsageShareValid(unittest.TestCase):
    def test_documented_example(self):
        local = _usage(30, 70, 20)
        cloud = _usage(30, 270, 20)
        result = usage_share(local, cloud, comparable=True)

        self.assertEqual(result["localFreshTokens"], 50)
        self.assertEqual(result["cloudFreshTokens"], 50)
        self.assertEqual(result["localReportedTokens"], 120)
        self.assertEqual(result["cloudReportedTokens"], 320)
        self.assertEqual(result["localFreshTokenSharePercent"], 50.0)
        self.assertEqual(result["localReportedTokenSharePercent"], 27.27)
        self.assertIsNone(result["actualCodexSavingsPercent"])
        self.assertFalse(result["savingsMeasured"])

    def test_cached_input_only_counts_in_reported_totals(self):
        local = _usage(0, 100, 0)
        cloud = _usage(0, 100, 0)
        result = usage_share(local, cloud, comparable=True)

        self.assertEqual(result["localFreshTokens"], 0)
        self.assertEqual(result["cloudFreshTokens"], 0)
        self.assertEqual(result["localReportedTokens"], 100)
        self.assertEqual(result["cloudReportedTokens"], 100)
        # Fresh denominator is zero -> no fresh share despite comparability.
        self.assertIsNone(result["localFreshTokenSharePercent"])
        self.assertEqual(result["localReportedTokenSharePercent"], 50.0)

    def test_zero_denominators(self):
        result = usage_share(_usage(0, 0, 0), _usage(0, 0, 0), comparable=True)
        self.assertEqual(result["localFreshTokens"], 0)
        self.assertEqual(result["localReportedTokens"], 0)
        self.assertEqual(result["cloudFreshTokens"], 0)
        self.assertEqual(result["cloudReportedTokens"], 0)
        self.assertIsNone(result["localFreshTokenSharePercent"])
        self.assertIsNone(result["localReportedTokenSharePercent"])

    def test_cloud_none(self):
        result = usage_share(_usage(30, 70, 20), None, comparable=True)
        self.assertEqual(result["localFreshTokens"], 50)
        self.assertIsNone(result["cloudFreshTokens"])
        self.assertEqual(result["localReportedTokens"], 120)
        self.assertIsNone(result["cloudReportedTokens"])
        self.assertIsNone(result["localFreshTokenSharePercent"])
        self.assertIsNone(result["localReportedTokenSharePercent"])

    def test_comparable_false(self):
        result = usage_share(_usage(30, 70, 20), _usage(30, 270, 20),
                             comparable=False)
        self.assertEqual(result["localFreshTokens"], 50)
        self.assertEqual(result["cloudReportedTokens"], 320)
        self.assertIsNone(result["localFreshTokenSharePercent"])
        self.assertIsNone(result["localReportedTokenSharePercent"])

    def test_no_input_mutation(self):
        local = _usage(30, 70, 20)
        cloud = _usage(30, 270, 20)
        local_copy = dict(local)
        cloud_copy = dict(cloud)
        usage_share(local, cloud, comparable=True)
        self.assertEqual(local, local_copy)
        self.assertEqual(cloud, cloud_copy)

    def test_no_savings_claim_survives_all_valid_cases(self):
        cases = [
            (_usage(30, 70, 20), _usage(30, 270, 20), True),
            (_usage(1000, 0, 500), _usage(0, 0, 1), True),
            (_usage(0, 0, 0), _usage(1, 1, 1), True),
            (_usage(5, 5, 5), None, True),
            (_usage(5, 5, 5), _usage(5, 5, 5), False),
        ]
        for local, cloud, comparable in cases:
            result = usage_share(local, cloud, comparable=comparable)
            self.assertIsNone(result["actualCodexSavingsPercent"])
            self.assertFalse(result["savingsMeasured"])
            self.assertIn("not measured", result["metricMeaning"])


class TestUsageShareValidation(unittest.TestCase):
    def test_local_none_rejected(self):
        with self.assertRaises(ValueError):
            usage_share(None, _usage(1, 1, 1), comparable=True)

    def test_malformed_usage_not_dict(self):
        for bad in ([], "usage", 42):
            with self.assertRaises(ValueError):
                usage_share(bad, _usage(1, 1, 1), comparable=True)
            with self.assertRaises(ValueError):
                usage_share(_usage(1, 1, 1), bad, comparable=True)

    def test_missing_keys(self):
        with self.assertRaises(ValueError):
            usage_share({"uncached_input_tokens": 1, "output_tokens": 1},
                        _usage(1, 1, 1), comparable=True)

    def test_extra_keys(self):
        usage = _usage(1, 1, 1)
        usage["reasoning_tokens"] = 5
        with self.assertRaises(ValueError):
            usage_share(usage, _usage(1, 1, 1), comparable=True)

    def test_non_string_and_mixed_type_keys_rejected(self):
        # All three required keys plus an integer key 7.
        with_integer_key = _usage(1, 0, 1)
        with_integer_key[7] = 2
        # All three required keys plus mixed integer and string extras.
        with_mixed_keys = _usage(1, 0, 1)
        with_mixed_keys[7] = 2
        with_mixed_keys["reasoning_tokens"] = 5

        for bad in (with_integer_key, with_mixed_keys):
            with self.assertRaises(ValueError):
                usage_share(dict(bad), _usage(1, 1, 1), comparable=True)
            with self.assertRaises(ValueError):
                usage_share(_usage(1, 1, 1), dict(bad), comparable=True)

    def test_negative_values(self):
        for idx in range(3):
            values = [1, 1, 1]
            values[idx] = -1
            usage = _usage(*values)
            with self.assertRaises(ValueError):
                usage_share(usage, _usage(1, 1, 1), comparable=True)

    def test_bool_values_rejected(self):
        for idx in range(3):
            values = [1, 1, 1]
            values[idx] = True
            usage = _usage(*values)
            with self.assertRaises(ValueError):
                usage_share(usage, _usage(1, 1, 1), comparable=True)

    def test_float_values_rejected(self):
        for idx in range(3):
            values = [1, 1, 1]
            values[idx] = 1.5
            usage = _usage(*values)
            with self.assertRaises(ValueError):
                usage_share(usage, _usage(1, 1, 1), comparable=True)

    def test_comparable_must_be_bool(self):
        for bad in (1, 0, "true", None):
            with self.assertRaises(ValueError):
                usage_share(_usage(1, 1, 1), _usage(1, 1, 1),
                            comparable=bad)


if __name__ == "__main__":
    unittest.main()
