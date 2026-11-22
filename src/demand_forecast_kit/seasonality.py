"""Conservative automatic season-length detection from univariate history."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from math import isfinite


@dataclass(frozen=True, slots=True)
class SeasonalityResult:
    """Selected period and candidate autocorrelation evidence."""

    season_length: int | None
    strength: float
    candidate_strengths: dict[int, float]


def detect_season_length(
    history: Sequence[float],
    *,
    candidates: Sequence[int] = (7, 14, 28),
    minimum_strength: float = 0.3,
) -> SeasonalityResult:
    """Select the strongest configured lag when enough history supports it.

    This deliberately small diagnostic is not a general seasonal decomposition:
    callers must choose domain-relevant candidate periods and validate the
    selection inside each training fold to avoid temporal leakage.
    """
    values = tuple(float(value) for value in history)
    if len(values) < 3 or any(not isfinite(value) for value in values):
        raise ValueError("history must contain at least three finite observations")
    periods = tuple(candidates)
    if not periods or any(type(period) is not int or period < 2 for period in periods):
        raise ValueError("candidates must contain positive integer periods >= 2")
    if len(set(periods)) != len(periods):
        raise ValueError("candidate periods must be unique")
    if not isfinite(minimum_strength) or not 0.0 <= minimum_strength <= 1.0:
        raise ValueError("minimum_strength must be between zero and one")

    mean = sum(values) / len(values)
    centered = tuple(value - mean for value in values)
    denominator = sum(value * value for value in centered)
    strengths: dict[int, float] = {}
    if denominator == 0.0:
        strengths = {period: 0.0 for period in periods if period < len(values)}
    else:
        for period in periods:
            if period >= len(values):
                continue
            numerator = sum(
                centered[index] * centered[index - period]
                for index in range(period, len(values))
            )
            strengths[period] = numerator / denominator

    if not strengths:
        raise ValueError("history is too short for every candidate season length")
    best_period = max(strengths, key=lambda period: (strengths[period], -period))
    strength = strengths[best_period]
    selected = best_period if strength >= minimum_strength else None
    return SeasonalityResult(selected, strength, strengths)
