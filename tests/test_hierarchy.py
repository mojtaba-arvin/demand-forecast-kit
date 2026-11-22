from __future__ import annotations

from datetime import datetime

import polars as pl
import pytest

from demand_forecast_kit.hierarchy import build_hierarchical_history


def test_hierarchical_history_builds_leaf_and_both_aggregate_axes() -> None:
    source = pl.DataFrame(
        {
            "sku_id": ["sku-1", "sku-1", "sku-2"],
            "location_id": ["north", "south", "north"],
            "timestamp": [datetime(2024, 1, 1)] * 3,
            "demand": [2.0, 3.0, 5.0],
        }
    )

    result = build_hierarchical_history(source)
    sku_total = result.filter(pl.col("hierarchy_level") == "sku").filter(
        pl.col("series_id") == 'sku:["sku-1"]'
    )
    location_total = result.filter(pl.col("hierarchy_level") == "location").filter(
        pl.col("series_id") == 'location:["north"]'
    )
    leaf = result.filter(pl.col("hierarchy_level") == "sku-location").row(0, named=True)

    assert sku_total["demand"].item() == 5.0
    assert location_total["demand"].item() == 7.0
    assert len(leaf["parent_series_ids"]) == 2


def test_hierarchy_identifiers_are_collision_safe() -> None:
    source = pl.DataFrame(
        {
            "sku_id": ["a|b", "a"],
            "location_id": ["c", "b|c"],
            "timestamp": [datetime(2024, 1, 1)] * 2,
            "demand": [1.0, 2.0],
        }
    )

    result = build_hierarchical_history(source).filter(pl.col("hierarchy_level") == "sku-location")
    assert result["series_id"].n_unique() == 2


def test_hierarchy_rejects_duplicate_and_invalid_rows() -> None:
    source = pl.DataFrame(
        {
            "sku_id": ["sku-1", "sku-1"],
            "location_id": ["north", "north"],
            "timestamp": [datetime(2024, 1, 1)] * 2,
            "demand": [1.0, 2.0],
        }
    )
    with pytest.raises(ValueError, match="duplicate"):
        build_hierarchical_history(source)

    invalid = source.head(1).with_columns(pl.lit(-1.0).alias("demand"))
    with pytest.raises(ValueError, match="valid and finite"):
        build_hierarchical_history(invalid)
