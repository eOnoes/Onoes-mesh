"""Pure arithmetic helper for reporting token-traffic share routed to a local worker.

This module computes observed share of token traffic only. It never claims or
measures Codex quota, cost, or inference-compute savings: no matched
Codex-only counterfactual run exists, and unequal model tokenizers and
processing costs prevent converting token shares into savings.

No file, network, or process access. Inputs are never mutated.
"""

_REQUIRED_KEYS = frozenset(
    {"uncached_input_tokens", "cached_input_tokens", "output_tokens"}
)


def _validate_comparable(comparable):
    if not isinstance(comparable, bool):
        raise ValueError(
            "comparable must be a bool, got "
            f"{type(comparable).__name__}"
        )


def _validate_usage(usage, name):
    """Validate a usage dict without mutating it.

    A valid usage dict has exactly the three required keys, each mapping to a
    nonnegative integer. bool is NOT an integer for this API.
    """
    if not isinstance(usage, dict):
        raise ValueError(f"{name} must be a dict, got {type(usage).__name__}")

    keys = set(usage.keys())
    if not all(isinstance(key, str) for key in keys):
        raise ValueError(f"{name} has non-string keys")
    missing = _REQUIRED_KEYS - keys
    if missing:
        raise ValueError(
            f"{name} is missing keys: {', '.join(sorted(missing))}"
        )
    if keys - _REQUIRED_KEYS:
        raise ValueError(f"{name} has unexpected keys")

    for key in sorted(_REQUIRED_KEYS):
        value = usage[key]
        # bool is explicitly not accepted as an integer here.
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(
                f"{name}[{key!r}] must be an int, got "
                f"{type(value).__name__}"
            )
        if value < 0:
            raise ValueError(
                f"{name}[{key!r}] must be nonnegative, got {value}"
            )


def _fresh_tokens(usage):
    """uncached input + output. Cached input is NOT part of fresh tokens."""
    return usage["uncached_input_tokens"] + usage["output_tokens"]


def _reported_tokens(usage):
    """uncached input + cached input + output.

    output_tokens already includes reasoning; reasoning is not counted again.
    """
    return (
        usage["uncached_input_tokens"]
        + usage["cached_input_tokens"]
        + usage["output_tokens"]
    )


def _share_percent(numerator, denominator):
    return round(100.0 * numerator / denominator, 2)


def usage_share(local, cloud, *, comparable):
    """Compute observed token-traffic share routed to the local worker.

    Args:
        local: dict with exactly the keys ``uncached_input_tokens``,
            ``cached_input_tokens`` and ``output_tokens``, each a nonnegative
            int (bool is not an int here). May not be None.
        cloud: same shape as local, or None when cloud usage is unavailable.
        comparable: bool. Share percentages are computed only when this is
            True, cloud usage is available, and the relevant denominator > 0.

    Returns:
        dict with keys:
            localFreshTokens, cloudFreshTokens (None if cloud is None),
            localReportedTokens, cloudReportedTokens (None if cloud is None),
            localFreshTokenSharePercent, localReportedTokenSharePercent,
            actualCodexSavingsPercent (always None),
            savingsMeasured (always False),
            metricMeaning (plain-language scope note).

    Raises:
        ValueError: on malformed dicts, missing/extra keys, negative, bool or
            non-int values, a None local, or a non-bool comparable.
    """
    _validate_comparable(comparable)

    if local is None:
        raise ValueError("local must not be None")
    _validate_usage(local, "local")
    if cloud is not None:
        _validate_usage(cloud, "cloud")

    local_fresh = _fresh_tokens(local)
    local_reported = _reported_tokens(local)

    if cloud is None:
        cloud_fresh = None
        cloud_reported = None
    else:
        cloud_fresh = _fresh_tokens(cloud)
        cloud_reported = _reported_tokens(cloud)

    can_compare = comparable and cloud is not None

    if can_compare and (local_fresh + cloud_fresh) > 0:
        local_fresh_share = _share_percent(local_fresh, local_fresh + cloud_fresh)
    else:
        local_fresh_share = None

    if can_compare and (local_reported + cloud_reported) > 0:
        local_reported_share = _share_percent(
            local_reported, local_reported + cloud_reported
        )
    else:
        local_reported_share = None

    return {
        "localFreshTokens": local_fresh,
        "cloudFreshTokens": cloud_fresh,
        "localReportedTokens": local_reported,
        "cloudReportedTokens": cloud_reported,
        "localFreshTokenSharePercent": local_fresh_share,
        "localReportedTokenSharePercent": local_reported_share,
        # No matched Codex-only counterfactual exists, so actual Codex
        # savings are never measured by this helper.
        "actualCodexSavingsPercent": None,
        "savingsMeasured": False,
        "metricMeaning": (
            "Observed token-traffic share routed locally is not measured "
            "Codex quota, cost, or inference-compute savings. No matched "
            "Codex-only counterfactual run exists, and unequal model "
            "tokenizers and processing costs prevent converting token "
            "shares into savings."
        ),
    }
