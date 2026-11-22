# SPDX-FileCopyrightText: 2026 Mojtaba Arvin
# SPDX-License-Identifier: MIT
"""Tests for leakage-aware lead-time residual-path calibration."""

from datetime import date, datetime, timedelta

import pytest

from demand_forecast_kit.backtesting import BacktestConfig, BacktestReport, FoldEvaluation
from demand_forecast_kit.inventory import evaluate_inventory_policy
from demand_forecast_kit.lead_time import (
    backtest_lead_time_calibration,
    calibrate_lead_time_demand,
    to_inventory_scenario,
)


def _report(fold_count: int = 12) -> BacktestReport:
    config = BacktestConfig(
        initial_train_size=4,
        horizon=2,
        step=3,
        season_length=1,
        coverage_levels=(),
    )
    evaluations = []
    start = datetime(2024, 1, 1)
    residuals = (-2.0, -1.0, 0.0, 1.0, 2.0, 3.0, -3.0, 4.0, -4.0, 2.0, 1.0, -1.0)
    for index in range(fold_count):
        test_start = start + timedelta(days=index * 3)
        test_end = test_start + timedelta(days=1)
        residual = residuals[index % len(residuals)]
        evaluations.append(
            FoldEvaluation(
                model_id="seasonal-naive",
                model_version="1.0",
                series_id="sku-1",
                fold=index + 1,
                train_size=4 + index * 3,
                train_end_timestamp=(test_start - timedelta(days=1)).isoformat(),
                test_start_timestamp=test_start.isoformat(),
                test_end_timestamp=test_end.isoformat(),
                actuals=(10.0 + residual, 10.0 + residual),
                quantile_forecasts={
                    0.1: (7.0, 7.0),
                    0.5: (10.0, 10.0),
                    0.9: (13.0, 13.0),
                },
                mase=1.0,
                wql=1.0,
                pinball_losses={0.1: 1.0, 0.5: 1.0, 0.9: 1.0},
                interval_coverages={},
            )
        )
    return BacktestReport(
        dataset_fingerprint="a" * 64,
        config=config,
        evaluations=tuple(evaluations),
        skipped_series=(),
        model_summaries=(),
        series_history_ranges={
            "sku-1": (start.isoformat(), (start + timedelta(days=40)).isoformat())
        },
    )


def test_calibration_uses_only_completed_non_overlapping_same_series_paths() -> None:
    report = _report()
    origin = date(2024, 1, 16)
    distribution = calibrate_lead_time_demand(
        report,
        series_id="sku-1",
        model_id="seasonal-naive",
        forecast_origin=origin,
        baseline_median=(10.0, 10.0),
        expected_model_version="1.0",
        lead_time=2,
        quantile_levels=(0.1, 0.5, 0.9),
        bootstrap_samples=500,
        min_calibration_paths=5,
        seed=7,
    )

    assert distribution.calibration_path_count == 5
    assert distribution.bootstrap_sample_count == 500
    assert distribution.forecast_origin == "2024-01-16T00:00:00"
    assert distribution.quantiles[0.1] <= distribution.quantiles[0.5]
    assert distribution.quantiles[0.5] <= distribution.quantiles[0.9]
    assert distribution.quantiles[0.5] == pytest.approx(20.0)


def test_calibration_is_deterministic_and_preserves_full_path_residual_sum() -> None:
    report = _report()
    kwargs = {
        "series_id": "sku-1",
        "model_id": "seasonal-naive",
        "forecast_origin": "2024-02-15T00:00:00",
        "baseline_median": (10.0, 10.0),
        "expected_model_version": "1.0",
        "lead_time": 2,
        "bootstrap_samples": 200,
        "min_calibration_paths": 5,
        "seed": 123,
    }
    first = calibrate_lead_time_demand(report, **kwargs)
    second = calibrate_lead_time_demand(report, **kwargs)
    assert first == second


def test_calibration_rejects_future_leakage_and_insufficient_paths() -> None:
    with pytest.raises(ValueError, match="insufficient non-overlapping"):
        calibrate_lead_time_demand(
            _report(),
            series_id="sku-1",
            model_id="seasonal-naive",
            forecast_origin="2024-01-05T00:00:00",
            baseline_median=(10.0, 10.0),
            lead_time=2,
            min_calibration_paths=5,
        )


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"series_id": " ", "model_id": "seasonal-naive"}, "non-blank"),
        ({"series_id": "sku-1", "model_id": "missing"}, "insufficient non-overlapping"),
        ({"series_id": "sku-1", "model_id": "seasonal-naive", "lead_time": 3}, "lead_time"),
    ],
)
def test_calibration_rejects_invalid_identity_and_horizon(
    kwargs: dict[str, object], message: str
) -> None:
    arguments: dict[str, object] = {
        "series_id": "sku-1",
        "model_id": "seasonal-naive",
        "forecast_origin": "2024-02-15",
        "baseline_median": (10.0, 10.0),
        "lead_time": 2,
    }
    arguments.update(kwargs)
    with pytest.raises(ValueError, match=message):
        calibrate_lead_time_demand(_report(), **arguments)  # type: ignore[arg-type]


def test_distribution_adapts_to_inventory_scenario_and_policy_evaluation() -> None:
    distribution = calibrate_lead_time_demand(
        _report(),
        series_id="sku-1",
        model_id="seasonal-naive",
        forecast_origin="2024-02-15",
        baseline_median=(10.0, 10.0),
        expected_model_version="1.0",
        lead_time=2,
        min_calibration_paths=5,
    )
    scenario = to_inventory_scenario(
        distribution,
        scenario_id="sku-1-origin-1",
        realized_lead_time_demand=21.0,
        inventory_position=5.0,
    )
    report = evaluate_inventory_policy(
        [scenario],
        underage_cost=9.0,
        overage_cost=1.0,
        holding_cost_per_unit=0.5,
        shortage_cost_per_unit=4.0,
    )
    assert report.scenario_count == 1
    assert report.total_demand == 21.0


def test_prequential_backtest_uses_prior_folds_only_and_reports_coverage() -> None:
    result = backtest_lead_time_calibration(
        _report(),
        series_id="sku-1",
        model_id="seasonal-naive",
        lead_time=2,
        quantile_levels=(0.1, 0.5, 0.9),
        bootstrap_samples=200,
        min_calibration_paths=5,
        seed=19,
    )
    assert result.origin_count >= 5
    assert set(result.quantile_coverage) == {0.1, 0.5, 0.9}
    assert set(result.mean_pinball_loss) == {0.1, 0.5, 0.9}


def test_calibration_rejects_model_version_mismatch() -> None:
    with pytest.raises(ValueError, match="model version mismatch"):
        calibrate_lead_time_demand(
            _report(),
            series_id="sku-1",
            model_id="seasonal-naive",
            forecast_origin="2024-02-15",
            baseline_median=(10.0, 10.0),
            expected_model_version="2.0",
            lead_time=2,
            min_calibration_paths=5,
        )
