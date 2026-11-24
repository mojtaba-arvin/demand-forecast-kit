"""Explicit reorder-point and safety-stock calculations."""

from __future__ import annotations

from collections.abc import Mapping
from math import isfinite


def reorder_point(
    lead_time_demand_quantiles: Mapping[float, float],
    *,
    service_level: float,
) -> float:
    """Interpolate the cumulative lead-time demand quantile at a target service level.

    The mapping must describe cumulative lead-time demand, not marginal daily
    quantiles. The requested service level must be bracketed by supplied levels.
    """
    level = float(service_level)
    if not isfinite(level) or not 0.0 < level < 1.0:
        raise ValueError("service_level must be finite and strictly between 0 and 1")
    if not lead_time_demand_quantiles:
        raise ValueError("at least one lead-time demand quantile is required")

    normalized: dict[float, float] = {}
    for raw_level, raw_demand in lead_time_demand_quantiles.items():
        quantile_level = float(raw_level)
        demand = float(raw_demand)
        if not isfinite(quantile_level) or not 0.0 < quantile_level < 1.0:
            raise ValueError("quantile levels must be finite and strictly between 0 and 1")
        if quantile_level in normalized:
            raise ValueError("quantile levels must be unique")
        if not isfinite(demand) or demand < 0.0:
            raise ValueError("lead-time demand quantiles must be finite and non-negative")
        normalized[quantile_level] = demand

    levels = tuple(sorted(normalized))
    values = tuple(normalized[item] for item in levels)
    if any(lower > upper for lower, upper in zip(values, values[1:], strict=False)):
        raise ValueError("lead-time demand quantiles must be non-decreasing")
    if level < levels[0] or level > levels[-1]:
        raise ValueError("quantile curve must bracket the requested service level")

    for index, candidate in enumerate(levels):
        if candidate == level:
            return values[index]
        if candidate > level:
            lower_level, upper_level = levels[index - 1], candidate
            lower_value, upper_value = values[index - 1], values[index]
            weight = (level - lower_level) / (upper_level - lower_level)
            return lower_value + weight * (upper_value - lower_value)
    raise AssertionError("bracketed service level must resolve to a quantile")


def safety_stock(
    *,
    reorder_point_value: float,
    expected_lead_time_demand: float,
) -> float:
    """Return the non-negative buffer above expected cumulative lead-time demand."""
    reorder = float(reorder_point_value)
    expected = float(expected_lead_time_demand)
    if not isfinite(reorder) or reorder < 0.0:
        raise ValueError("reorder_point_value must be finite and non-negative")
    if not isfinite(expected) or expected < 0.0:
        raise ValueError("expected_lead_time_demand must be finite and non-negative")
    return max(0.0, reorder - expected)
