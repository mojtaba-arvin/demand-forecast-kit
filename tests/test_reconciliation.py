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
        shrinkage=1.0,
    )


def test_mint_reconciles_known_identity_weight_case() -> None:
    reconciler = make_reconciler().fit(((1, 0, 0), (-1, 0, 0), (0, 1, -1), (0, -1, 1)))
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
    reconciler = make_reconciler().fit(((1, 0, 0), (-1, 0, 0), (0, 1, -1), (0, -1, 1)))
    samples = (
        ((9, 4, 7), (10, 5, 6)),
        ((10, 5, 8), (11, 6, 7)),
        ((11, 6, 8), (12, 7, 7)),
        ((12, 8, 9), (13, 8, 8)),
    )
    forecasts = reconciler.reconcile_quantile_paths(samples, quantile_levels=(0.1, 0.5, 0.9))
    assert set(forecasts) == {"total", "a", "b"}
    # Marginal quantiles are not additive in general. Coherence is guaranteed
    # for each reconciled sample path, while each node's marginal quantiles stay ordered.
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


def test_prequential_reconciliation_never_uses_current_origin_residual() -> None:
    from demand_forecast_kit.reconciliation import prequential_reconcile

    residuals = (
        (1.0, 0.0, 0.0),
        (-1.0, 0.0, 0.0),
        (0.0, 1.0, -1.0),
        (0.0, -1.0, 1.0),
    )
    samples = (
        ((10.0, 4.0, 8.0),),
        ((10.0, 4.0, 8.0),),
        ((10.0, 4.0, 8.0),),
        ((10.0, 4.0, 8.0),),
    )
    kwargs = {
        "node_ids": ("total", "a", "b"),
        "bottom_ids": ("a", "b"),
        "summing_matrix": ((1, 1), (1, 0), (0, 1)),
        "shrinkage": 1.0,
    }
    first = prequential_reconcile(
        **kwargs, residuals_by_origin=residuals, base_samples_by_origin=samples
    )
    changed_current = (residuals[0], residuals[1], (1000.0, -500.0, 700.0), residuals[3])
    second = prequential_reconcile(
        **kwargs, residuals_by_origin=changed_current, base_samples_by_origin=samples
    )
    assert first[0].origin_index == 2
    assert first[0].residual_count == 2
    assert first[0].samples == second[0].samples
    assert first[1].residual_count == 3
    assert first[1].samples != second[1].samples


def test_mint_rejects_invalid_identifiers_covariance_and_empty_nodes() -> None:
    with pytest.raises(ValueError, match="must not be blank"):
        MinTReconciler(("", "a"), ("a",), ((1,), (1,)))
    with pytest.raises(ValueError, match="must be unique"):
        MinTReconciler(("total", "a", "a"), ("a",), ((1,), (1,), (1,)))
    with pytest.raises(ValueError, match="must also appear"):
        MinTReconciler(("total",), ("missing",), ((1,),))
    with pytest.raises(ValueError, match="0/1"):
        MinTReconciler(("total", "a"), ("a",), ((2,), (1,)))
    with pytest.raises(ValueError, match="shrinkage"):
        MinTReconciler(("total", "a"), ("a",), ((1,), (1,)), shrinkage=0.0)
    with pytest.raises(ValueError, match="ridge"):
        MinTReconciler(("total", "a"), ("a",), ((1,), (1,)), ridge=0.0)
    with pytest.raises(ValueError, match="at least one bottom"):
        MinTReconciler(("total", "a", "empty"), ("a",), ((1,), (1,), (0,)))


def test_mint_hierarchy_metadata_fails_closed() -> None:
    with pytest.raises(ValueError, match="missing hierarchy metadata"):
        MinTReconciler.from_hierarchical_history(pl.DataFrame({"series_id": ["x"]}))
    no_bottoms = pl.DataFrame(
        {
            "series_id": ["total"],
            "parent_series_ids": [[]],
            "hierarchy_level": ["sku"],
        }
    )
    with pytest.raises(ValueError, match="no sku-location"):
        MinTReconciler.from_hierarchical_history(no_bottoms)
    unknown_parent = pl.DataFrame(
        {
            "series_id": ["leaf"],
            "parent_series_ids": [["missing"]],
            "hierarchy_level": ["sku-location"],
        }
    )
    with pytest.raises(ValueError, match="unknown parent"):
        MinTReconciler.from_hierarchical_history(unknown_parent)
    orphan_leaf = pl.DataFrame(
        {
            "series_id": ["leaf"],
            "parent_series_ids": [[]],
            "hierarchy_level": ["sku-location"],
        }
    )
    with pytest.raises(ValueError, match="must reference"):
        MinTReconciler.from_hierarchical_history(orphan_leaf)
    aggregate_parent = pl.DataFrame(
        {
            "series_id": ["leaf", "total"],
            "parent_series_ids": [["total"], ["leaf"]],
            "hierarchy_level": ["sku-location", "sku"],
        }
    )
    with pytest.raises(ValueError, match="only sku-location"):
        MinTReconciler.from_hierarchical_history(aggregate_parent)
    inconsistent = pl.DataFrame(
        {
            "series_id": ["leaf", "leaf"],
            "parent_series_ids": [["total"], ["other"]],
            "hierarchy_level": ["sku-location", "sku-location"],
        }
    )
    with pytest.raises(ValueError, match="inconsistent hierarchy"):
        MinTReconciler.from_hierarchical_history(inconsistent)


def test_mint_rejects_nonfinite_residuals_and_invalid_base_samples() -> None:
    reconciler = make_reconciler()
    with pytest.raises(ValueError, match="finite"):
        reconciler.fit(((1, 2, 3), (1, float("inf"), 3)))
    fitted = reconciler.fit(((1, 0, 0), (-1, 0, 0), (0, 1, -1)))
    with pytest.raises(ValueError, match="must not be empty"):
        fitted.reconcile_samples(())
    with pytest.raises(ValueError, match="one value per hierarchy node"):
        fitted.reconcile_samples(((1, 2),))
    with pytest.raises(ValueError, match="must be finite"):
        fitted.reconcile_samples(((1, float("nan"), 3),))


def test_mint_quantile_paths_reject_invalid_levels_and_shapes() -> None:
    fitted = make_reconciler().fit(((1, 0, 0), (-1, 0, 0), (0, 1, -1)))
    with pytest.raises(ValueError, match="non-empty and unique"):
        fitted.reconcile_quantile_paths((((1, 2, 3),),), quantile_levels=())
    with pytest.raises(ValueError, match="non-empty and unique"):
        fitted.reconcile_quantile_paths((((1, 2, 3),),), quantile_levels=(0.5, 0.5))
    with pytest.raises(ValueError, match="strictly between"):
        fitted.reconcile_quantile_paths((((1, 2, 3),),), quantile_levels=(1.0,))
    with pytest.raises(ValueError, match="non-empty path"):
        fitted.reconcile_quantile_paths(((),))
    with pytest.raises(ValueError, match="same horizon"):
        fitted.reconcile_quantile_paths((((1, 2, 3),), ((1, 2, 3), (2, 3, 4))))


def test_mint_linear_solver_and_prequential_inputs_fail_closed() -> None:
    from demand_forecast_kit.reconciliation import _solve, prequential_reconcile

    with pytest.raises(ValueError, match="square"):
        _solve(((1.0, 2.0),), (1.0, 2.0))
    with pytest.raises(ValueError, match="rank deficient"):
        _solve(((1.0, 1.0), (1.0, 1.0)), (1.0, 2.0))
    kwargs = {
        "node_ids": ("total", "a", "b"),
        "bottom_ids": ("a", "b"),
        "summing_matrix": ((1, 1), (1, 0), (0, 1)),
    }
    with pytest.raises(ValueError, match="equal lengths"):
        prequential_reconcile(
            **kwargs,
            residuals_by_origin=((1, 0, 0), (0, 1, 0), (0, 0, 1)),
            base_samples_by_origin=(((1, 1, 1),),),
        )
    with pytest.raises(ValueError, match="at least three"):
        prequential_reconcile(
            **kwargs,
            residuals_by_origin=((1, 0, 0), (0, 1, 0)),
            base_samples_by_origin=(((1, 1, 1),), ((1, 1, 1),)),
        )
