# SPDX-FileCopyrightText: 2026 Mojtaba Arvin
# SPDX-License-Identifier: MIT
"""Tests for the opt-in UCI Online Retail benchmark preprocessing."""

from datetime import date, datetime
import hashlib

import polars as pl
import pytest

from demand_forecast_kit.retail_benchmark import sha256_file

from evals.run_uci_online_retail_benchmark import (
    _baseline_error_summary,
    _coverage_diagnostics,
    _temporal_scale_experiment,
    build_cohort_panel,
    prepare_daily_demand,
)


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


def test_coverage_diagnostics_exposes_sku_dispersion_and_tail_miscalibration() -> None:
    rows = [
        {
            "cohort": "dense",
            "series_id": "A",
            "model_id": "croston-sba",
            "lead_time": 7,
            "interval_coverage": {"0.8": 0.5},
            "quantile_coverage": {"0.1": 0.2, "0.5": 0.4, "0.9": 0.85},
            "baseline_median_error": {
                "mean_error": 2.0,
                "mean_absolute_error": 3.0,
            },
        },
        {
            "cohort": "dense",
            "series_id": "B",
            "model_id": "croston-sba",
            "lead_time": 7,
            "interval_coverage": {"0.8": 1.0},
            "quantile_coverage": {"0.1": 0.0, "0.5": 0.6, "0.9": 0.95},
            "baseline_median_error": {
                "mean_error": -1.0,
                "mean_absolute_error": 2.0,
            },
        },
    ]

    summary = _coverage_diagnostics(rows)

    assert summary == [
        {
            "cohort": "dense",
            "model_id": "croston-sba",
            "lead_time": 7,
            "series_count": 2,
            "macro_interval_coverage": 0.75,
            "min_series_interval_coverage": 0.5,
            "max_series_interval_coverage": 1.0,
            "series_below_nominal_p80": 1,
            "macro_quantile_coverage": {"0.1": 0.1, "0.5": 0.5, "0.9": 0.8999999999999999},
            "macro_baseline_median_error": 0.5,
            "macro_baseline_median_absolute_error": 2.5,
            "series_with_mean_underforecast": 1,
            "series_with_mean_overforecast": 1,
        }
    ]


def test_baseline_error_summary_uses_actual_minus_uncalibrated_median() -> None:
    summary = _baseline_error_summary(
        [
            {"actual": 12.0, "baseline_median": 10.0},
            {"actual": 8.0, "baseline_median": 10.0},
        ]
    )

    assert summary == {
        "origin_count": 2,
        "mean_error": 0.0,
        "median_error": 0.0,
        "mean_absolute_error": 2.0,
        "underforecast_rate": 0.5,
    }


def test_temporal_scale_experiment_keeps_holdout_out_of_scale_fitting() -> None:
    start = date(2020, 1, 1)

    def build_rows(holdout_actual: float) -> list[dict[str, object]]:
        rows = []
        for offset in range(16):
            rows.append(
                {
                    "cohort": "dense",
                    "series_id": "SKU-1",
                    "model_id": "croston-sba",
                    "lead_time": 7,
                    "fold": offset + 1,
                    "forecast_origin": (
                        start.fromordinal(start.toordinal() + offset * 7).isoformat()
                    ),
                    "actual": holdout_actual if offset in (10, 12, 14) else 10.0,
                    "q10": 8.0,
                    "q50": 10.0,
                    "q90": 12.0,
                    "calibration_path_count": 5 + offset,
                }
            )
        return rows

    first = _temporal_scale_experiment(build_rows(20.0))[0]
    changed_holdout = _temporal_scale_experiment(build_rows(200.0))[0]

    assert first["status"] == "evaluated"
    assert first["calibration_observation_count"] == 4
    assert first["holdout_observation_count"] == 3
    assert first["purged_origin_count_per_series"] == 9
    assert first["fitted_width_scale"] == changed_holdout["fitted_width_scale"]
    assert first["fitted_median_shift"] == changed_holdout["fitted_median_shift"]
    assert first["holdout_baseline"] != changed_holdout["holdout_baseline"]


def test_prepare_daily_demand_accepts_online_retail_ii_invoice_column() -> None:
    source = pl.DataFrame(
        {
            "Invoice": ["10001", "C10002"],
            "StockCode": ["A", "A"],
            "Quantity": [3, 7],
            "InvoiceDate": [datetime(2010, 1, 1), datetime(2010, 1, 2)],
        }
    )

    actual = prepare_daily_demand(source)

    assert actual.to_dicts() == [
        {"series_id": "A", "day": date(2010, 1, 1), "demand": 3.0}
    ]


def test_prepare_daily_demand_requires_an_invoice_identifier_column() -> None:
    source = pl.DataFrame(
        {
            "StockCode": ["A"],
            "Quantity": [1],
            "InvoiceDate": [datetime(2010, 1, 1)],
        }
    )
    with pytest.raises(ValueError, match="InvoiceNo or Invoice"):
        prepare_daily_demand(source)


def test_sha256_file_hashes_source_bytes(tmp_path) -> None:
    source = tmp_path / "dataset.xlsx"
    source.write_bytes(b"workbook bytes")

    assert sha256_file(source) == hashlib.sha256(b"workbook bytes").hexdigest()
