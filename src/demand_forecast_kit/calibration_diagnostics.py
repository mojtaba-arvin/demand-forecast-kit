"""Small-sample uncertainty diagnostics for empirical interval coverage."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from math import isfinite, sqrt


@dataclass(frozen=True, slots=True)
class CoverageEstimate:
    """Empirical coverage and Wilson score interval."""

    successes: int
    observations: int
    coverage: float
    lower: float
    upper: float


def wilson_coverage_interval(
    covered: Sequence[bool],
    *,
    confidence_z: float = 1.959963984540054,
) -> CoverageEstimate:
    """Estimate interval coverage with a two-sided Wilson score interval.

    The Wilson interval behaves better than a normal approximation for small
    samples and proportions near zero or one. It assumes independent Bernoulli
    observations; overlapping forecast origins require block-level resampling
    instead and must not be treated as independent here.
    """
    if not covered:
        raise ValueError("at least one coverage observation is required")
    if any(type(value) is not bool for value in covered):
        raise ValueError("coverage observations must be booleans")
    if not isfinite(confidence_z) or confidence_z <= 0.0:
        raise ValueError("confidence_z must be finite and positive")
    n = len(covered)
    successes = sum(bool(value) for value in covered)
    proportion = successes / n
    z2 = confidence_z * confidence_z
    denominator = 1.0 + z2 / n
    center = (proportion + z2 / (2.0 * n)) / denominator
    margin = (
        confidence_z * sqrt(proportion * (1.0 - proportion) / n + z2 / (4.0 * n * n)) / denominator
    )
    return CoverageEstimate(
        successes=successes,
        observations=n,
        coverage=proportion,
        lower=max(0.0, center - margin),
        upper=min(1.0, center + margin),
    )


def quantile_coverage_estimates(
    actuals: Sequence[float],
    forecasts: Mapping[float, Sequence[float]],
    *,
    confidence_z: float = 1.959963984540054,
) -> dict[float, CoverageEstimate]:
    """Estimate empirical hit rates and Wilson intervals for each forecast quantile.

    A hit is defined as actual <= predicted quantile. This is the marginal
    quantile calibration diagnostic; it does not imply joint path calibration.
    Forecasts must be monotone across quantile levels at every observation.
    """
    observed = tuple(float(value) for value in actuals)
    if not observed or any(not isfinite(value) for value in observed):
        raise ValueError("actuals must contain at least one finite value")
    if not forecasts:
        raise ValueError("at least one quantile forecast is required")

    normalized: dict[float, tuple[float, ...]] = {}
    for raw_level, raw_values in forecasts.items():
        level = float(raw_level)
        values = tuple(float(value) for value in raw_values)
        if not isfinite(level) or not 0.0 < level < 1.0:
            raise ValueError("quantile levels must be finite and strictly between 0 and 1")
        if level in normalized:
            raise ValueError("quantile levels must be unique")
        if len(values) != len(observed):
            raise ValueError("each quantile forecast must match the actuals length")
        if any(not isfinite(value) for value in values):
            raise ValueError("quantile forecasts must contain only finite values")
        normalized[level] = values

    levels = tuple(sorted(normalized))
    for index in range(len(observed)):
        at_step = tuple(normalized[level][index] for level in levels)
        if any(lower > upper for lower, upper in zip(at_step, at_step[1:], strict=False)):
            raise ValueError("quantile forecasts must be non-decreasing at every observation")

    return {
        level: wilson_coverage_interval(
            tuple(
                actual <= predicted
                for actual, predicted in zip(observed, normalized[level], strict=True)
            ),
            confidence_z=confidence_z,
        )
        for level in levels
    }
