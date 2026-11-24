from __future__ import annotations

from datetime import datetime

import polars as pl
import pytest

from demand_forecast_kit.hierarchy import build_hierarchical_history
from demand_forecast_kit.reconciliation import MinTReconciler


def make_reconciler() -> MinTReconciler:
    return MinTReconciler(
        node_ids=("total", "a", "b"),
        bottom_ids=("a", "b"),
        summing_matrix=((1, 1), (1, 0), (0, 1)),
    )


def test_mint_reconciles_known_identity_weight_case() -> None:
    reconciler = make_reconciler().fit(
        ((1, 0, 0), (-1, 0, 0), (0, 1, -1), (0, -1, 1))
    )
    actual = reconciler.reconcile_samples(((10, 4, 8),))[0]
    assert actual[0] == pytest.approx(actual[1] + actual[2])
    assert actual[0] == pytest.approx(10.6666666, rel=1e-6)
    assert actual[1] == pytest.approx(3.3333333, rel=1e-6)
    assert actual[2] == pytest.approx(7.3333333, rel=1e-6)


def test_mint_handles_singular_residual_covariance_with_shrinkage_and_ridge() -> None:
    reconciler = make_reconciler().fit(((1, 1, 1), (1, 1, 1), (1, 1, 1)))
    result = reconciler.reconcile_samples(((8, -2, 3), (10, 4, 6)))
    assert all(row[0] == pytest.approx(row[1] + row[2]) for row in result)
    assert all(value >= 0 for row in result for value in row)


def test_quantiles_are_derived_after_path_reconciliation() -> None:
    reconciler = make_reconciler().fit(
        ((1, 0, 0), (-1, 0, 0), (0, 1, -1), (0, -1, 1))
    )
    samples = (
        ((9, 4, 7), (10, 5, 6)),
        ((10, 5, 8), (11, 6, 7)),
        ((11, 6, 8), (12, 7, 7)),
        ((12, 8, 9), (13, 8, 8)),
    )
    forecasts = reconciler.reconcile_quantile_paths(samples, quantile_levels=(0.1, 0.5, 0.9))
    assert set(forecasts) == {"total", "a", "b"}
    for step in range(2):
        assert forecasts["total"].quantiles[0.5][step] == pytest.approx(
            forecasts["a"].quantiles[0.5][step] + forecasts["b"].quantiles[0.5][step]
        )
    for forecast in forecasts.values():
        for step in range(forecast.horizon):
            values = [forecast.quantiles[level][step] for level in (0.1, 0.5, 0.9)]
            assert values == sorted(values)
            assert all(value >= 0 for value in values)


def test_reconciler_builds_summing_matrix_from_existing_hierarchy_dag() -> None:
    source = pl.DataFrame(
        {
            "sku_id": ["sku-1", "sku-1", "sku-2"],
            "location_id": ["north", "south", "north"],
            "timestamp": [datetime(2024, 1, 1)] * 3,
            "demand": [2.0, 3.0, 5.0],
        }
    )
    history = build_hierarchical_history(source)
    reconciler = MinTReconciler.from_hierarchical_history(history)
    assert len(reconciler.bottom_ids) == 3
    assert len(reconciler.node_ids) == 7
    assert all(sum(row) > 0 for row in reconciler.summing_matrix)


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"node_ids": (), "bottom_ids": ("a",), "summing_matrix": ()}, "non-empty"),
        (
            {"node_ids": ("total", "a"), "bottom_ids": ("a",), "summing_matrix": ((1, 1), (1,))},
            "dimensions",
        ),
        (
            {"node_ids": ("a",), "bottom_ids": ("a",), "summing_matrix": ((0,),)},
            "identity",
        ),
    ],
)
def test_mint_rejects_invalid_hierarchy(kwargs: dict[str, object], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        MinTReconciler(**kwargs)  # type: ignore[arg-type]


def test_mint_rejects_bad_residuals_and_requires_fit() -> None:
    reconciler = make_reconciler()
    with pytest.raises(RuntimeError, match="fit"):
        reconciler.reconcile_samples(((1, 1, 1),))
    with pytest.raises(ValueError, match="at least two"):
        reconciler.fit(((1, 2, 3),))
    with pytest.raises(ValueError, match="one value per hierarchy node"):
        reconciler.fit(((1, 2), (2, 3)))
