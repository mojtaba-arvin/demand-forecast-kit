from __future__ import annotations

import pytest

from demand_forecast_kit.comparison import (
    aggregate_macro_and_volume_weighted,
    compare_paired_series_metrics,
)


def test_paired_cluster_comparison_is_deterministic_and_directional() -> None:
    baseline = {f"sku-{index}": 10.0 + index for index in range(12)}
    candidate = {key: value - 2.0 for key, value in baseline.items()}

    result = compare_paired_series_metrics(
        baseline,
        candidate,
        bootstrap_samples=500,
        permutation_samples=500,
        seed=7,
    )
    repeated = compare_paired_series_metrics(
        baseline,
        candidate,
        bootstrap_samples=500,
        permutation_samples=500,
        seed=7,
    )

    assert result == repeated
    assert result.mean_difference == -2.0
    assert result.confidence_interval == (-2.0, -2.0)
    assert result.p_value < 0.05


def test_macro_and_volume_weighted_aggregation_are_distinct() -> None:
    result = aggregate_macro_and_volume_weighted(
        {"small": 10.0, "large": 2.0},
        {"small": 1.0, "large": 9.0},
    )

    assert result.macro_average == 6.0
    assert result.volume_weighted_average == 2.8
    assert result.total_weight == 10.0


def test_comparison_rejects_mismatched_series_and_invalid_weights() -> None:
    with pytest.raises(ValueError, match="same non-empty"):
        compare_paired_series_metrics({"a": 1.0}, {"b": 1.0})
    with pytest.raises(ValueError, match="weights must be finite"):
        aggregate_macro_and_volume_weighted({"a": 1.0}, {"a": -1.0})
    with pytest.raises(ValueError, match="positive"):
        aggregate_macro_and_volume_weighted({"a": 1.0}, {"a": 0.0})
