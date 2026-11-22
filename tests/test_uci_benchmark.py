# SPDX-FileCopyrightText: 2026 Mojtaba Arvin
# SPDX-License-Identifier: MIT
"""Tests for the opt-in UCI Online Retail benchmark preprocessing."""

from datetime import date, datetime

import polars as pl
import pytest

from demand_forecast_kit.backtesting import BacktestConfig, BacktestReport, FoldEvaluation
from evals.run_uci_online_retail_benchmark import (
    _coverage_diagnostics,
    _prequential_baseline_error,
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


def test_prequential_baseline_error_uses_only_calibration_eligible_origins() -> None:
    config = BacktestConfig(
        initial_train_size=180,
        horizon=14,
        step=14,
        season_length=7,
        quantile_levels=(0.1, 0.5, 0.9),
        coverage_levels=(0.8,),
    )
    evaluations = []
    start = date(2020, 1, 1)
    for fold in range(1, 9):
        test_start = start.fromordinal(start.toordinal() + (fold - 1) * 14)
        test_end = start.fromordinal(test_start.toordinal() + 13)
        evaluations.append(
            FoldEvaluation(
                model_id="croston-sba",
                model_version="1",
                series_id="SKU-1",
                fold=fold,
                train_size=180 + (fold - 1) * 14,
                train_end_timestamp=start.fromordinal(test_start.toordinal() - 1).isoformat(),
                test_start_timestamp=test_start.isoformat(),
                test_end_timestamp=test_end.isoformat(),
                actuals=(3.0,) * 14,
                quantile_forecasts={
                    0.1: (0.0,) * 14,
                    0.5: (1.0,) * 14,
                    0.9: (2.0,) * 14,
                },
                mase=None,
                wql=None,
                pinball_losses={0.1: 0.0, 0.5: 0.0, 0.9: 0.0},
                interval_coverages={0.8: 0.0},
            )
        )
    report = BacktestReport(
        dataset_fingerprint="fixture",
        config=config,
        evaluations=tuple(evaluations),
        skipped_series=(),
        model_summaries=(),
        series_history_ranges={},
    )

    summary = _prequential_baseline_error(
        report,
        series_id="SKU-1",
        model_id="croston-sba",
        lead_time=7,
    )

    assert summary == {
        "origin_count": 2,
        "mean_error": 14.0,
        "median_error": 14.0,
        "mean_absolute_error": 14.0,
        "underforecast_rate": 1.0,
    }
