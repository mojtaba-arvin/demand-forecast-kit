# SPDX-FileCopyrightText: 2026 Mojtaba Arvin
# SPDX-License-Identifier: MIT
"""Tests for the opt-in UCI Online Retail benchmark preprocessing."""

from datetime import date, datetime

import polars as pl
import pytest

from evals.run_uci_online_retail_benchmark import build_cohort_panel, prepare_daily_demand


def test_prepare_daily_demand_excludes_cancellations_and_returns() -> None:
    source = pl.DataFrame(
        {
            "InvoiceNo": ["10001", "10002", "C10003", "10004", "10005"],
            "StockCode": ["A", "A", "A", "B", "B"],
            "Quantity": [2, 3, 8, -1, 4],
            "InvoiceDate": [
                datetime(2011, 1, 1),
                datetime(2011, 1, 1),
                datetime(2011, 1, 2),
                datetime(2011, 1, 2),
                datetime(2011, 1, 3),
            ],
        }
    )

    actual = prepare_daily_demand(source)

    assert actual.to_dicts() == [
        {"series_id": "A", "day": date(2011, 1, 1), "demand": 5.0},
        {"series_id": "B", "day": date(2011, 1, 3), "demand": 4.0},
    ]


def test_build_cohort_panel_fills_no_sale_days_and_is_deterministic() -> None:
    start = date(2011, 1, 1)
    rows = []
    for day in range(200):
        rows.append(
            {
                "series_id": "dense",
                "day": start.fromordinal(start.toordinal() + day),
                "demand": 1.0,
            }
        )
    for day in range(0, 200, 4):
        rows.append(
            {
                "series_id": "intermittent",
                "day": start.fromordinal(start.toordinal() + day),
                "demand": 2.0,
            }
        )
    for day in range(0, 200, 25):
        rows.append(
            {
                "series_id": "very-intermittent",
                "day": start.fromordinal(start.toordinal() + day),
                "demand": 1.0,
            }
        )
    daily = pl.DataFrame(rows)

    first, counts = build_cohort_panel(daily, max_skus_per_cohort=5)
    second, _ = build_cohort_panel(daily, max_skus_per_cohort=5)

    assert counts == {"dense": 1, "intermittent": 1, "very-intermittent": 1}
    assert first.equals(second)
    assert first.height == 600
    dense_zero = (
        first.filter(
            (pl.col("series_id") == "intermittent") & (pl.col("timestamp") == date(2011, 1, 2))
        )
        .get_column("demand")
        .item()
    )
    assert dense_zero == 0.0


def test_build_cohort_panel_rejects_invalid_sample_size() -> None:
    daily = pl.DataFrame({"series_id": ["A"], "day": [date(2011, 1, 1)], "demand": [1.0]})
    with pytest.raises(ValueError, match="positive integer"):
        build_cohort_panel(daily, max_skus_per_cohort=0)


def test_cohort_assignment_uses_only_initial_training_window() -> None:
    start = date(2011, 1, 1)
    rows = [
        {
            "series_id": "stable-intermittent",
            "day": start.fromordinal(start.toordinal() + day),
            "demand": 1.0,
        }
        for day in range(0, 180, 9)
    ]
    rows.extend(
        {
            "series_id": "future-only-burst",
            "day": start.fromordinal(start.toordinal() + day),
            "demand": 1.0,
        }
        for day in range(180, 200)
    )

    panel, counts = build_cohort_panel(pl.DataFrame(rows), max_skus_per_cohort=5)

    assert counts == {"dense": 0, "intermittent": 1, "very-intermittent": 0}
    assert panel.get_column("series_id").unique().to_list() == ["stable-intermittent"]
    assert panel.height == 200


def test_build_cohort_panel_requires_full_assignment_window() -> None:
    daily = pl.DataFrame(
        {
            "series_id": ["A"] * 10,
            "day": [date(2011, 1, day) for day in range(1, 11)],
            "demand": [1.0] * 10,
        }
    )
    with pytest.raises(ValueError, match="at least 180 are required"):
        build_cohort_panel(daily)
