"""Small, deterministic demand-regime diagnostics for model monitoring."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from math import isfinite


@dataclass(frozen=True, slots=True)
class LevelShiftDiagnostic:
    """Robust comparison of adjacent historical windows."""

    prior_median: float
    recent_median: float
    relative_change: float
    detected: bool


def detect_level_shift(
    history: Sequence[float],
    *,
    window: int,
    relative_threshold: float = 0.5,
    scale_floor: float = 1.0,
) -> LevelShiftDiagnostic:
    """Detect a material median-level change between adjacent windows.

    This is a transparent monitoring signal, not a hypothesis test or an
    automatic model switch. Callers must calculate it from history available
    at the forecast origin; never include the evaluation horizon.
    """
    values = tuple(float(value) for value in history)
    if type(window) is not int or window < 2:
        raise ValueError("window must be an integer >= 2")
    if len(values) < 2 * window:
        raise ValueError("history must contain at least two complete windows")
    if any(not isfinite(value) or value < 0.0 for value in values):
        raise ValueError("history must contain finite non-negative demand")
    if not isfinite(relative_threshold) or relative_threshold <= 0.0:
        raise ValueError("relative_threshold must be finite and positive")
    if not isfinite(scale_floor) or scale_floor <= 0.0:
        raise ValueError("scale_floor must be finite and positive")

    prior = sorted(values[-2 * window : -window])
    recent = sorted(values[-window:])

    def median(ordered: list[float]) -> float:
        middle = len(ordered) // 2
        if len(ordered) % 2:
            return ordered[middle]
        return (ordered[middle - 1] + ordered[middle]) / 2.0

    prior_median = median(prior)
    recent_median = median(recent)
    relative_change = abs(recent_median - prior_median) / max(abs(prior_median), scale_floor)
    return LevelShiftDiagnostic(
        prior_median=prior_median,
        recent_median=recent_median,
        relative_change=relative_change,
        detected=relative_change >= relative_threshold,
    )
