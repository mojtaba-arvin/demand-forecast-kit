"""Calibration-only conformal corrections for predictive intervals."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from math import ceil, isfinite


@dataclass(frozen=True, slots=True)
class CalibratedIntervals:
    """Adjusted interval bounds for one forecast batch."""

    lower: tuple[float, ...]
    upper: tuple[float, ...]


@dataclass(frozen=True, slots=True)
class AdaptiveIntervalCalibrator:
    """Global interval correction with sufficiently sampled regime adjustments.

    Fit this object only on a chronological calibration partition that precedes
    the evaluation/production forecast origins. The finite-sample order statistic
    is conformal-style; serial dependence and regime drift weaken exchangeability
    assumptions, so empirical future coverage must still be reported.
    """

    coverage: float
    global_correction: float
    regime_corrections: dict[str, float]
    calibration_count: int

    def apply(
        self,
        lower: Sequence[float],
        upper: Sequence[float],
        *,
        regimes: Sequence[str] | None = None,
    ) -> CalibratedIntervals:
        """Expand each interval using its regime correction or global fallback."""
        low = tuple(float(value) for value in lower)
        high = tuple(float(value) for value in upper)
        if not low or len(low) != len(high):
            raise ValueError("lower and upper bounds must have the same non-zero length")
        if any(not isfinite(a) or not isfinite(b) or a > b for a, b in zip(low, high, strict=True)):
            raise ValueError("interval bounds must be finite and lower <= upper")
        labels = tuple(regimes) if regimes is not None else ("__global__",) * len(low)
        if len(labels) != len(low) or any(not label.strip() for label in labels):
            raise ValueError("regimes must be non-blank and match the interval length")

        adjusted_lower: list[float] = []
        adjusted_upper: list[float] = []
        for lo, hi, label in zip(low, high, labels, strict=True):
            correction = self.regime_corrections.get(label, self.global_correction)
            adjusted_lower.append(max(0.0, lo - correction))
            adjusted_upper.append(hi + correction)
        return CalibratedIntervals(tuple(adjusted_lower), tuple(adjusted_upper))


def _finite_sample_correction(scores: Sequence[float], coverage: float) -> float:
    ordered = sorted(scores)
    rank = ceil((len(ordered) + 1) * coverage)
    if rank > len(ordered):
        raise ValueError(
            "insufficient calibration observations for requested finite-sample coverage"
        )
    return ordered[rank - 1]


def fit_adaptive_interval_calibrator(
    actuals: Sequence[float],
    lower: Sequence[float],
    upper: Sequence[float],
    *,
    coverage: float = 0.8,
    regimes: Sequence[str] | None = None,
    min_regime_samples: int = 20,
) -> AdaptiveIntervalCalibrator:
    """Fit additive interval corrections using calibration observations only.

    The nonconformity score is the distance of an actual value outside its
    predicted interval (zero for an in-interval observation). A global correction
    is always fitted. A regime-specific correction is fitted only when that
    regime has at least min_regime_samples observations and enough samples for
    the requested finite-sample order statistic; otherwise it falls back globally.
    """
    observed = tuple(float(value) for value in actuals)
    low = tuple(float(value) for value in lower)
    high = tuple(float(value) for value in upper)
    if not observed or len(observed) != len(low) or len(observed) != len(high):
        raise ValueError("actuals and interval bounds must have the same non-zero length")
    if not isfinite(coverage) or not 0.0 < coverage < 1.0:
        raise ValueError("coverage must be finite and strictly between 0 and 1")
    if type(min_regime_samples) is not int or min_regime_samples < 2:
        raise ValueError("min_regime_samples must be an integer >= 2")
    if any(not isfinite(value) or value < 0.0 for value in observed):
        raise ValueError("actuals must be finite and non-negative")
    if any(
        not isfinite(a) or not isfinite(b) or a < 0.0 or a > b
        for a, b in zip(low, high, strict=True)
    ):
        raise ValueError("calibration intervals must be finite, non-negative, and ordered")

    labels = tuple(regimes) if regimes is not None else ("__global__",) * len(observed)
    if len(labels) != len(observed) or any(not label.strip() for label in labels):
        raise ValueError("regimes must be non-blank and match the calibration length")

    scores = tuple(
        max(lo - actual, actual - hi, 0.0)
        for actual, lo, hi in zip(observed, low, high, strict=True)
    )
    global_correction = _finite_sample_correction(scores, coverage)
    grouped: dict[str, list[float]] = defaultdict(list)
    for label, score in zip(labels, scores, strict=True):
        grouped[label].append(score)

    regime_corrections: dict[str, float] = {}
    for label, values in grouped.items():
        if len(values) < min_regime_samples:
            continue
        try:
            regime_corrections[label] = _finite_sample_correction(values, coverage)
        except ValueError:
            continue

    return AdaptiveIntervalCalibrator(
        coverage=coverage,
        global_correction=global_correction,
        regime_corrections=dict(sorted(regime_corrections.items())),
        calibration_count=len(observed),
    )
