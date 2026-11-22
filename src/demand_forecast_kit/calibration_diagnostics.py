"""Small-sample uncertainty diagnostics for empirical interval coverage."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite, sqrt
from collections.abc import Sequence


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
    if not isfinite(confidence_z) or confidence_z <= 0.0:
        raise ValueError("confidence_z must be finite and positive")
    n = len(covered)
    successes = sum(bool(value) for value in covered)
    proportion = successes / n
    z2 = confidence_z * confidence_z
    denominator = 1.0 + z2 / n
    center = (proportion + z2 / (2.0 * n)) / denominator
    margin = (
        confidence_z
        * sqrt(proportion * (1.0 - proportion) / n + z2 / (4.0 * n * n))
        / denominator
    )
    return CoverageEstimate(
        successes=successes,
        observations=n,
        coverage=proportion,
        lower=max(0.0, center - margin),
        upper=min(1.0, center + margin),
    )
