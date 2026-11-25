# SPDX-FileCopyrightText: 2026 Mojtaba Arvin
# SPDX-License-Identifier: MIT
"""Tests for the local M5/Walmart retail data adapter."""

from datetime import date, timedelta
from pathlib import Path

import polars as pl
import pytest

from demand_forecast_kit.retail_benchmark import (
    build_cohort_panel,
    prepare_m5_daily_demand,
    sha256_file,
)


def _write_m5_fixture(root: Path) -> tuple[Path, Path]:
    start = date(2011, 1, 29)
    day_count = 194
    rows: list[dict[str, object]] = []

    def add_series(item_id: str, store_id: str, values: list[int]) -> None:
        row: dict[str, object] = {
            "id": f"{item_id}_{store_id}_evaluation",
            "item_id": item_id,
            "store_id": store_id,
        }
        row.update({f"d_{index + 1}": value for index, value in enumerate(values)})
        rows.append(row)

    add_series("ITEM_DENSE", "CA_1", [1] * 90 + [0] * 90 + [2] * 14)
    intermittent = [1 if index % 10 == 0 else 0 for index in range(180)] + [1] * 14
    add_series("ITEM_INTERMITTENT", "TX_1", intermittent)
    add_series("ITEM_VERY_SPARSE", "WI_1", [1] * 8 + [0] * 186)
    add_series("ITEM_TOO_SPARSE", "CA_2", [1] * 7 + [0] * 187)

    sales_path = root / "sales_train_evaluation.csv"
    calendar_path = root / "calendar.csv"
    pl.DataFrame(rows).write_csv(sales_path)
    pl.DataFrame(
        {
            "d": [f"d_{index + 1}" for index in range(day_count)],
            "date": [(start + timedelta(days=index)).isoformat() for index in range(day_count)],
        }
    ).write_csv(calendar_path)
    return sales_path, calendar_path


def test_m5_adapter_selects_frozen_deterministic_item_store_cohorts(tmp_path: Path) -> None:
    sales_path, calendar_path = _write_m5_fixture(tmp_path)

    daily, counts, provenance = prepare_m5_daily_demand(
        sales_path,
        calendar_path,
        max_series_per_cohort=1,
    )
    panel, panel_counts = build_cohort_panel(
        daily,
        max_skus_per_cohort=1,
        cohort_window_days=180,
    )

    assert counts == {"dense": 1, "intermittent": 1, "very-intermittent": 1}, provenance
    assert panel_counts == counts
    assert daily.height == 144
    assert panel.height == 3 * 194
    assert provenance["series_count"] == 3
    assert provenance["day_count"] == 194
    assert provenance["sales_sha256"] == sha256_file(sales_path)
    assert provenance["calendar_sha256"] == sha256_file(calendar_path)
    assert "ITEM_TOO_SPARSE::CA_2" not in daily.get_column("series_id").unique().to_list()
    assert set(panel.get_column("cohort").unique().to_list()) == {
        "dense",
        "intermittent",
        "very-intermittent",
    }


def test_m5_adapter_rejects_incomplete_calendar_mapping(tmp_path: Path) -> None:
    sales_path, calendar_path = _write_m5_fixture(tmp_path)
    calendar = pl.read_csv(calendar_path).filter(pl.col("d") != "d_194")
    calendar.write_csv(calendar_path)

    with pytest.raises(ValueError, match="map every sales day column"):
        prepare_m5_daily_demand(sales_path, calendar_path, max_series_per_cohort=1)


def test_m5_adapter_rejects_negative_selected_sales(tmp_path: Path) -> None:
    sales_path, calendar_path = _write_m5_fixture(tmp_path)
    sales = pl.read_csv(sales_path).with_columns(
        pl.when(pl.col("item_id") == "ITEM_DENSE")
        .then(pl.lit(-1))
        .otherwise(pl.col("d_194"))
        .alias("d_194")
    )
    sales.write_csv(sales_path)

    with pytest.raises(ValueError, match="invalid daily sales values"):
        prepare_m5_daily_demand(sales_path, calendar_path, max_series_per_cohort=1)
