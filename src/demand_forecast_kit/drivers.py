"""Exploratory price and promotion association diagnostics for demand history."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from math import fsum, isfinite


@dataclass(frozen=True, slots=True)
class DemandDriverObservation:
    """One historical demand observation with contemporaneous commercial drivers."""

    demand: float
    price: float
    promoted: bool


@dataclass(frozen=True, slots=True)
class DemandDriverEffects:
    """OLS associations; coefficients are not causal estimates."""

    intercept: float
    price_effect: float
    promotion_effect: float
    r_squared: float
    observation_count: int


def _solve_three_by_three(matrix: list[list[float]], vector: list[float]) -> tuple[float, ...]:
    augmented = [row[:] + [value] for row, value in zip(matrix, vector, strict=True)]
    for column in range(3):
        pivot = max(range(column, 3), key=lambda row: abs(augmented[row][column]))
        if abs(augmented[pivot][column]) < 1e-12:
            raise ValueError("price and promotion features are collinear or insufficiently varied")
        augmented[column], augmented[pivot] = augmented[pivot], augmented[column]
        divisor = augmented[column][column]
        augmented[column] = [value / divisor for value in augmented[column]]
        for row in range(3):
            if row == column:
                continue
            factor = augmented[row][column]
            augmented[row] = [
                value - factor * pivot_value
                for value, pivot_value in zip(augmented[row], augmented[column], strict=True)
            ]
    return tuple(augmented[index][3] for index in range(3))


def estimate_demand_driver_effects(
    observations: Sequence[DemandDriverObservation],
) -> DemandDriverEffects:
    """Fit demand ~ intercept + price + promotion on caller-supplied training rows.

    Pass only observations available before the forecast origin. The fitted
    coefficients describe conditional linear associations, not causal lift:
    pricing and promotion decisions are often confounded by seasonality,
    availability, marketing, and other omitted business variables.
    """
    if len(observations) < 4:
        raise ValueError("at least four demand-driver observations are required")
    demand = tuple(float(item.demand) for item in observations)
    price = tuple(float(item.price) for item in observations)
    promoted = tuple(float(item.promoted) for item in observations)
    if any(not isfinite(value) or value < 0.0 for value in demand):
        raise ValueError("demand must be finite and non-negative")
    if any(not isfinite(value) or value <= 0.0 for value in price):
        raise ValueError("price must be finite and positive")
    if any(type(item.promoted) is not bool for item in observations):
        raise ValueError("promoted must be boolean")
    if len(set(promoted)) != 2 or len(set(price)) < 2:
        raise ValueError("both promotion states and at least two price levels are required")

    rows = tuple(
        (1.0, price_value, promo) for price_value, promo in zip(price, promoted, strict=True)
    )
    matrix = [
        [fsum(row[left] * row[right] for row in rows) for right in range(3)] for left in range(3)
    ]
    vector = [
        fsum(row[index] * actual for row, actual in zip(rows, demand, strict=True))
        for index in range(3)
    ]
    intercept, price_effect, promotion_effect = _solve_three_by_three(matrix, vector)
    predicted = tuple(intercept + price_effect * row[1] + promotion_effect * row[2] for row in rows)
    mean_demand = fsum(demand) / len(demand)
    total = fsum((actual - mean_demand) ** 2 for actual in demand)
    residual = fsum(
        (actual - estimate) ** 2 for actual, estimate in zip(demand, predicted, strict=True)
    )
    r_squared = (
        1.0
        if total <= 1e-12 and residual <= 1e-12
        else (0.0 if total <= 1e-12 else 1.0 - residual / total)
    )
    return DemandDriverEffects(
        intercept=intercept,
        price_effect=price_effect,
        promotion_effect=promotion_effect,
        r_squared=r_squared,
        observation_count=len(observations),
    )
