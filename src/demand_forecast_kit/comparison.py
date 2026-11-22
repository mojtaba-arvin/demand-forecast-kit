"""Cluster-aware confidence intervals and paired model comparisons."""

from __future__ import annotations

import random
from collections.abc import Mapping
from dataclasses import dataclass
from math import ceil, isfinite


@dataclass(frozen=True, slots=True)
class PairedMetricComparison:
    """Candidate-minus-baseline difference with cluster bootstrap and sign-flip test."""

    baseline: str
    candidate: str
    series_count: int
    mean_difference: float
    confidence_level: float
    confidence_interval: tuple[float, float]
    p_value: float


@dataclass(frozen=True, slots=True)
class MetricAggregation:
    """Macro and volume-weighted averages over the same evaluated series."""

    series_count: int
    total_weight: float
    macro_average: float
    volume_weighted_average: float


def _paired_values(
    baseline: Mapping[str, float],
    candidate: Mapping[str, float],
) -> tuple[float, ...]:
    if not baseline or set(baseline) != set(candidate):
        raise ValueError("baseline and candidate must contain the same non-empty series IDs")
    values: list[float] = []
    for series_id in sorted(baseline):
        left = float(baseline[series_id])
        right = float(candidate[series_id])
        if not isfinite(left) or not isfinite(right):
            raise ValueError("paired metric values must be finite")
        values.append(right - left)
    return tuple(values)


def compare_paired_series_metrics(
    baseline: Mapping[str, float],
    candidate: Mapping[str, float],
    *,
    baseline_name: str = "baseline",
    candidate_name: str = "candidate",
    confidence_level: float = 0.95,
    bootstrap_samples: int = 2000,
    permutation_samples: int = 5000,
    seed: int = 42,
) -> PairedMetricComparison:
    """Compare one metric per independent series using paired resampling.

    Aggregate any overlapping rolling-origin folds within each series before
    calling this function. The bootstrap and sign-flip test resample series as
    clusters, not individual folds, to avoid treating correlated origins as
    independent observations. Negative differences favor the candidate when
    lower metric values are better.
    """
    if not baseline_name.strip() or not candidate_name.strip():
        raise ValueError("model names must not be blank")
    if not isfinite(confidence_level) or not 0.0 < confidence_level < 1.0:
        raise ValueError("confidence_level must be finite and strictly between 0 and 1")
    if type(bootstrap_samples) is not int or bootstrap_samples < 100:
        raise ValueError("bootstrap_samples must be an integer >= 100")
    if type(permutation_samples) is not int or permutation_samples < 100:
        raise ValueError("permutation_samples must be an integer >= 100")
    if type(seed) is not int or seed < 0:
        raise ValueError("seed must be a non-negative integer")

    differences = _paired_values(baseline, candidate)
    count = len(differences)
    observed = sum(differences) / count
    rng = random.Random(seed)
    bootstrap_means = sorted(
        sum(rng.choices(differences, k=count)) / count for _ in range(bootstrap_samples)
    )
    alpha = 1.0 - confidence_level

    def percentile(probability: float) -> float:
        position = probability * (len(bootstrap_means) - 1)
        lower = int(position)
        upper = min(lower + 1, len(bootstrap_means) - 1)
        fraction = position - lower
        return bootstrap_means[lower] + fraction * (
            bootstrap_means[upper] - bootstrap_means[lower]
        )

    extreme = 0
    for _ in range(permutation_samples):
        permuted = sum(value * rng.choice((-1.0, 1.0)) for value in differences) / count
        if abs(permuted) >= abs(observed):
            extreme += 1
    p_value = (extreme + 1) / (permutation_samples + 1)
    return PairedMetricComparison(
        baseline=baseline_name,
        candidate=candidate_name,
        series_count=count,
        mean_difference=observed,
        confidence_level=confidence_level,
        confidence_interval=(percentile(alpha / 2.0), percentile(1.0 - alpha / 2.0)),
        p_value=p_value,
    )


def aggregate_macro_and_volume_weighted(
    values: Mapping[str, float],
    weights: Mapping[str, float],
) -> MetricAggregation:
    """Report unweighted series macro mean beside a volume-weighted mean."""
    if not values or set(values) != set(weights):
        raise ValueError("values and weights must contain the same non-empty series IDs")
    normalized_values = tuple(float(value) for value in values.values())
    normalized_weights = tuple(float(weight) for weight in weights.values())
    if any(not isfinite(value) for value in normalized_values):
        raise ValueError("metric values must be finite")
    if any(not isfinite(weight) or weight < 0.0 for weight in normalized_weights):
        raise ValueError("weights must be finite and non-negative")
    total_weight = sum(normalized_weights)
    if total_weight <= 0.0:
        raise ValueError("at least one series weight must be positive")
    return MetricAggregation(
        series_count=len(normalized_values),
        total_weight=total_weight,
        macro_average=sum(normalized_values) / len(normalized_values),
        volume_weighted_average=sum(
            value * weight
            for value, weight in zip(normalized_values, normalized_weights, strict=True)
        )
        / total_weight,
    )
