from __future__ import annotations

from datetime import date, timedelta

import polars as pl
import pytest

from demand_forecast_kit.backtesting import BacktestConfig, run_backtest
from demand_forecast_kit.bias import estimate_temporal_bias_correction
from demand_forecast_kit.models.seasonal_naive import SeasonalNaiveAdapter


def _report():
    start = date(2024, 1, 1)
    history = pl.DataFrame(
        {
            "series_id": ["sku-1"] * 20,
            "timestamp": [start + timedelta(days=index) for index in range(20)],
            "demand": [10.0] * 20,
        }
    )
    return run_backtest(
        history,
        [SeasonalNaiveAdapter(season_length=2)],
        BacktestConfig(
            initial_train_size=4,
            horizon=2,
            step=2,
            season_length=2,
            quantile_levels=(0.1, 0.5, 0.9),
            coverage_levels=(),
        ),
    )


def test_bias_correction_uses_only_pre_origin_completed_folds() -> None:
    report = _report()
    correction = estimate_temporal_bias_correction(
        report,
        series_id="sku-1",
        model_id="seasonal-naive",
        forecast_origin="2024-01-21",
        expected_model_version="1.0.0",
    )

    assert correction.calibration_path_count > 2
    assert correction.latest_calibration_end < correction.forecast_origin
    assert correction.correction == 0.0
    assert correction.apply([10, 10]) == (10.0, 10.0)


def test_bias_correction_rejects_origins_without_enough_history() -> None:
    with pytest.raises(ValueError, match="no eligible pre-origin"):
        estimate_temporal_bias_correction(
            _report(),
            series_id="sku-1",
            model_id="seasonal-naive",
            forecast_origin="2024-01-02",
        )
