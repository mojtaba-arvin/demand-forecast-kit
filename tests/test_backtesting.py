from collections.abc import Sequence
from datetime import date, timedelta
from pathlib import Path

import polars as pl
import pytest

from demand_forecast_kit.backtesting import (
    BacktestConfig,
    rolling_origin_splits,
    run_backtest,
    write_evaluation_artifact,
)
from demand_forecast_kit.contracts import QuantileForecast
from demand_forecast_kit.models.seasonal_naive import SeasonalNaiveAdapter


class MeanAdapter:
    model_id = "mean-reference"
    model_version = "test-1"

    def __init__(self) -> None:
        self.received_histories: list[tuple[str, tuple[float, ...]]] = []

    def predict(
        self,
        series_id: str,
        history: Sequence[float],
        *,
        horizon: int,
        quantile_levels: Sequence[float],
        seed: int,
    ) -> QuantileForecast:
        training = tuple(history)
        self.received_histories.append((series_id, training))
        center = sum(training) / len(training)
        forecasts = {
            level: tuple(center * (1.0 + (level - 0.5) * 0.4) for _ in range(horizon))
            for level in quantile_levels
        }
        return QuantileForecast(series_id, forecasts)


def make_history() -> pl.DataFrame:
    rows: list[dict[str, object]] = []
    start = date(2024, 1, 1)
    for series_index in range(2):
        for day in range(10):
            rows.append(
                {
                    "series_id": f"sku-{series_index + 1}",
                    "timestamp": start + timedelta(days=day),
                    "demand": float(10 + series_index * 5 + day),
                }
            )
    return pl.DataFrame(rows)


def test_rolling_origin_splits_are_chronological_and_sliding_when_limited() -> None:
    config = BacktestConfig(initial_train_size=4, horizon=2, step=2, season_length=2)
    splits = rolling_origin_splits(10, config)

    assert [
        (item.train_start, item.train_end, item.test_start, item.test_end) for item in splits
    ] == [(0, 4, 4, 6), (0, 6, 6, 8), (0, 8, 8, 10)]

    sliding = rolling_origin_splits(
        10,
        BacktestConfig(
            initial_train_size=4,
            horizon=2,
            step=2,
            season_length=2,
            max_train_size=5,
        ),
    )
    assert (sliding[-1].train_start, sliding[-1].train_end) == (3, 8)


def test_rolling_origin_splits_reject_invalid_sizes() -> None:
    config = BacktestConfig(initial_train_size=4, horizon=2)
    with pytest.raises(ValueError, match="n_observations"):
        rolling_origin_splits(0, config)
    with pytest.raises(ValueError, match="not enough"):
        rolling_origin_splits(5, config)


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"initial_train_size": 0, "horizon": 2}, "initial_train_size"),
        ({"initial_train_size": 4, "horizon": 0}, "horizon"),
        ({"initial_train_size": 4, "horizon": 2, "step": 0}, "step"),
        ({"initial_train_size": 4, "horizon": 2, "season_length": 0}, "season_length"),
        ({"initial_train_size": 4, "horizon": 2, "seed": -1}, "seed"),
        ({"initial_train_size": 4, "horizon": 2, "max_train_size": 3}, "max_train_size"),
        ({"initial_train_size": 4, "horizon": 2, "quantile_levels": (0.1, 0.9)}, "include 0.5"),
        (
            {
                "initial_train_size": 4,
                "horizon": 2,
                "quantile_levels": (0.05, 0.5, 0.95),
            },
            "include 0.1",
        ),
    ],
)
def test_backtest_config_rejects_invalid_values(kwargs: dict[str, object], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        BacktestConfig(**kwargs)  # type: ignore[arg-type]


def test_run_backtest_uses_identical_causal_splits_for_multiple_models() -> None:
    history = make_history()
    mean_adapter = MeanAdapter()
    report = run_backtest(
        history,
        [mean_adapter, SeasonalNaiveAdapter(season_length=2)],
        BacktestConfig(initial_train_size=4, horizon=2, step=2, season_length=2, seed=11),
    )

    assert len(report.evaluations) == 12
    assert len(report.model_summaries) == 2
    assert all(item.wql is not None for item in report.evaluations)
    assert all(item.mase is not None for item in report.evaluations)
    assert all(set(item.interval_coverages) == {0.8, 0.9} for item in report.evaluations)
    assert [item.train_size for item in report.evaluations[:3]] == [4, 6, 8]
    assert report.model_summaries[0].model_id == "mean-reference"
    assert report.model_summaries[0].fold_count == 6

    assert len(mean_adapter.received_histories) == 6
    assert [len(values) for _, values in mean_adapter.received_histories] == [4, 6, 8, 4, 6, 8]
    assert mean_adapter.received_histories[0][1] == (10.0, 11.0, 12.0, 13.0)


def test_run_backtest_is_reproducible_and_writes_a_digest_checked_artifact(
    tmp_path: Path,
) -> None:
    config = BacktestConfig(initial_train_size=4, horizon=2, step=2, season_length=2)
    first = run_backtest(make_history(), [MeanAdapter()], config)
    second = run_backtest(make_history(), [MeanAdapter()], config)

    assert first.dataset_fingerprint == second.dataset_fingerprint
    assert first.to_json_bytes() == second.to_json_bytes()
    assert first.schema_version == 2
    assert first.series_history_ranges == {
        "sku-1": ("2024-01-01T00:00:00", "2024-01-10T00:00:00"),
        "sku-2": ("2024-01-01T00:00:00", "2024-01-10T00:00:00"),
    }
    assert first.to_dict()["series_history_ranges"]["sku-1"] == {
        "start_timestamp": "2024-01-01T00:00:00",
        "end_timestamp": "2024-01-10T00:00:00",
    }

    destination = tmp_path / "nested" / "evaluation.json"
    metadata = write_evaluation_artifact(first, destination)
    assert destination.read_bytes() == first.to_json_bytes()
    assert metadata.size_bytes == len(destination.read_bytes())
    assert len(metadata.sha256) == 64
    assert not destination.with_name(destination.name + ".tmp").exists()


def test_run_backtest_reports_short_series_as_skipped() -> None:
    history = make_history().filter(
        (pl.col("series_id") == "sku-1") | (pl.col("timestamp") <= date(2024, 1, 5))
    )
    report = run_backtest(
        history,
        [MeanAdapter()],
        BacktestConfig(initial_train_size=4, horizon=2, season_length=2),
    )
    assert len(report.skipped_series) == 1
    assert report.skipped_series[0].series_id == "sku-2"


def test_run_backtest_rejects_invalid_history_and_adapters() -> None:
    config = BacktestConfig(initial_train_size=4, horizon=2, season_length=2)
    with pytest.raises(ValueError, match="at least one"):
        run_backtest(make_history(), [], config)

    duplicate = pl.concat([make_history(), make_history().head(1)])
    with pytest.raises(ValueError, match="invalid history"):
        run_backtest(duplicate, [MeanAdapter()], config)

    with pytest.raises(ValueError, match="duplicate model_id"):
        run_backtest(make_history(), [MeanAdapter(), MeanAdapter()], config)

    missing_columns = pl.DataFrame({"series_id": ["sku-1"]})
    with pytest.raises(ValueError, match="missing canonical columns"):
        run_backtest(missing_columns, [MeanAdapter()], config)


def test_run_backtest_rejects_adapter_output_mismatch() -> None:
    class WrongSeriesAdapter(MeanAdapter):
        model_id = "wrong-series"

        def predict(
            self,
            series_id: str,
            history: Sequence[float],
            *,
            horizon: int,
            quantile_levels: Sequence[float],
            seed: int,
        ) -> QuantileForecast:
            return QuantileForecast(
                "wrong",
                {level: tuple(1.0 for _ in range(horizon)) for level in quantile_levels},
            )

    class WrongHorizonAdapter(MeanAdapter):
        model_id = "wrong-horizon"

        def predict(
            self,
            series_id: str,
            history: Sequence[float],
            *,
            horizon: int,
            quantile_levels: Sequence[float],
            seed: int,
        ) -> QuantileForecast:
            return QuantileForecast(
                series_id,
                {level: tuple(1.0 for _ in range(horizon - 1)) for level in quantile_levels},
            )

    with pytest.raises(ValueError, match="returned series_id"):
        run_backtest(
            make_history(),
            [WrongSeriesAdapter()],
            BacktestConfig(initial_train_size=4, horizon=2, season_length=2),
        )
    with pytest.raises(ValueError, match="returned horizon"):
        run_backtest(
            make_history(),
            [WrongHorizonAdapter()],
            BacktestConfig(initial_train_size=4, horizon=2, season_length=2),
        )


def test_run_backtest_rejects_no_evaluable_series() -> None:
    too_short = make_history().filter(pl.col("timestamp") < date(2024, 1, 5))
    with pytest.raises(ValueError, match="no series"):
        run_backtest(
            too_short,
            [MeanAdapter()],
            BacktestConfig(initial_train_size=4, horizon=2, season_length=2),
        )


def test_run_backtest_reports_undefined_metrics_for_zero_demand() -> None:
    zero_history = make_history().with_columns(pl.lit(0.0).alias("demand"))
    report = run_backtest(
        zero_history,
        [MeanAdapter()],
        BacktestConfig(
            initial_train_size=4,
            horizon=2,
            season_length=2,
            coverage_levels=(),
        ),
    )
    assert all(item.mase is None and item.wql is None for item in report.evaluations)
    assert report.model_summaries[0].mean_mase is None
    assert report.model_summaries[0].mean_wql is None
