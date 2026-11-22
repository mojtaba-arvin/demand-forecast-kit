"""Create a deterministic synthetic artifact for the model-routing pipeline."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import timedelta
from pathlib import Path

from demand_forecast_kit.backtesting import BacktestConfig, run_backtest
from demand_forecast_kit.contracts import QuantileForecast
from demand_forecast_kit.models.seasonal_naive import SeasonalNaiveAdapter
from demand_forecast_kit.routing import ModelRouter, write_routing_artifact
from demand_forecast_kit.synthetic import generate_synthetic_history


class RecentMeanAdapter:
    """Small deterministic challenger used only by the routing smoke workflow."""

    @property
    def model_id(self) -> str:
        return "recent-mean-smoke"

    @property
    def model_version(self) -> str:
        return "smoke-1"

    def predict(
        self,
        series_id: str,
        history: Sequence[float],
        *,
        horizon: int,
        quantile_levels: Sequence[float],
        seed: int,
    ) -> QuantileForecast:
        center = sum(history[-14:]) / min(len(history), 14)
        return QuantileForecast(
            series_id,
            {
                level: tuple(max(0.0, center * (1.0 + 0.2 * (level - 0.5))) for _ in range(horizon))
                for level in sorted(quantile_levels)
            },
        )


def main() -> None:
    history = generate_synthetic_history(series_count=3, periods=84, seed=2026)
    report = run_backtest(
        history,
        [
            SeasonalNaiveAdapter(season_length=7),
            RecentMeanAdapter(),
        ],
        BacktestConfig(
            initial_train_size=35,
            horizon=7,
            step=7,
            season_length=7,
            seed=2026,
        ),
    )

    router: ModelRouter = ModelRouter(
        [SeasonalNaiveAdapter(season_length=7), RecentMeanAdapter()],
        metric="wql",
        min_folds=3,
        fallback_model_id="seasonal-naive",
    )
    latest_timestamp = history.get_column("timestamp").max()
    forecast_origin = latest_timestamp + timedelta(days=1)
    decisions = tuple(
        router.select(
            report,
            series_id=series_id,
            forecast_origin=forecast_origin,
        )
        for series_id in sorted(history.get_column("series_id").unique().to_list())
    )
    artifact = write_routing_artifact(
        decisions,
        Path("artifacts") / "synthetic-model-routing.json",
    )
    print(f"dataset_fingerprint={report.dataset_fingerprint}")
    print(f"routing_artifact_sha256={artifact.sha256}")
    print(f"routing_artifact_size_bytes={artifact.size_bytes}")
    for decision in decisions:
        print(
            f"series={decision.series_id} selected={decision.chosen_model_id} "
            f"fallback={decision.used_fallback} score={decision.score}"
        )


if __name__ == "__main__":
    main()
