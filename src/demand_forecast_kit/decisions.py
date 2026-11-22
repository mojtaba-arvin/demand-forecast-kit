"""Inventory replenishment decisions from demand quantile curves."""

from __future__ import annotations

from bisect import bisect_left
from collections.abc import Mapping
from dataclasses import dataclass
from math import ceil, isfinite


@dataclass(frozen=True, slots=True)
class OrderRecommendation:
    """Newsvendor order decision, base-stock target, and selected service level."""

    quantity: int
    target_stock_level: float
    inventory_position: float
    target_service_level: float
    unrounded_quantity: float


def newsvendor_order(
    lead_time_demand_quantiles: Mapping[float, float],
    *,
    underage_cost: float,
    overage_cost: float,
    inventory_position: float,
    pack_size: int = 1,
) -> OrderRecommendation:
    """Return a pack-size-rounded order quantity using the newsvendor critical fractile.

    The input must describe the quantiles of cumulative demand over the
    replenishment lead time. Summing per-step marginal quantiles is not a
    statistically valid substitute.

    Inventory position is on-hand stock plus confirmed/on-order stock minus
    backorders. The raw order is the positive difference between the target
    base-stock level and this position; the result is then rounded up to a pack.
    """
    if (
        not isfinite(underage_cost)
        or not isfinite(overage_cost)
        or underage_cost <= 0.0
        or overage_cost <= 0.0
    ):
        raise ValueError("underage_cost and overage_cost must be finite and positive")
    if not isfinite(inventory_position):
        raise ValueError("inventory_position must be finite")
    if isinstance(pack_size, bool) or not isinstance(pack_size, int) or pack_size < 1:
        raise ValueError("pack_size must be a positive integer")
    if not lead_time_demand_quantiles:
        raise ValueError("at least one lead-time demand quantile is required")

    normalized: dict[float, float] = {}
    for raw_level, raw_value in lead_time_demand_quantiles.items():
        level = float(raw_level)
        value = float(raw_value)
        if not isfinite(level) or not 0.0 < level < 1.0:
            raise ValueError("quantile levels must be finite and strictly between 0 and 1")
        if level in normalized:
            raise ValueError("quantile levels must be unique")
        if not isfinite(value) or value < 0.0:
            raise ValueError("demand quantiles must be finite and non-negative")
        normalized[level] = value

    levels = tuple(sorted(normalized))
    values = tuple(normalized[level] for level in levels)
    if any(
        left > right for left, right in zip(values, values[1:], strict=False)
    ):
        raise ValueError("demand values must be non-decreasing across quantile levels")

    target_service_level = underage_cost / (underage_cost + overage_cost)
    if target_service_level < levels[0] or target_service_level > levels[-1]:
        raise ValueError("quantile curve must bracket the target service level")

    upper_index = bisect_left(levels, target_service_level)
    if levels[upper_index] == target_service_level:
        target_stock_level = values[upper_index]
    else:
        lower_index = upper_index - 1
        lower_level, upper_level = levels[lower_index], levels[upper_index]
        weight = (target_service_level - lower_level) / (upper_level - lower_level)
        target_stock_level = values[lower_index] + weight * (
            values[upper_index] - values[lower_index]
        )

    unrounded_quantity = max(0.0, target_stock_level - inventory_position)
    rounded_quantity = (
        ceil(unrounded_quantity / pack_size) * pack_size if unrounded_quantity else 0
    )
    return OrderRecommendation(
        quantity=rounded_quantity,
        target_stock_level=target_stock_level,
        inventory_position=inventory_position,
        target_service_level=target_service_level,
        unrounded_quantity=unrounded_quantity,
    )
