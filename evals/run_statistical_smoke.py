"""Compare the statistical adapters with the seasonal-naive baseline on synthetic data."""

from __future__ import annotations

import random
from datetime import date, timedelta
from pathlib import Path

import polars as pl

from demand_forecast_kit.backtesting import BacktestConfig, run_backtest, write_evaluation_artifact
from demand_forecast_kit.models.seasonal_naive import SeasonalNaiveAdapter
from demand_forecast_kit.models.statistical import (
    AutoARIMAAdapter,
    AutoETSAdapter,
    CrostonAdapter,
    ThetaAdapter,
    TSBAdapter,
)
from demand_forecast_kit.synthetic import generate_synthetic_history


def generate_intermittent_history(periods: int = 84, seed: int = 2026) -> pl.DataFrame:
    rng = random.Random(seed)
    start = date(2024, 1, 1)
    rows: list[dict[str, object]] = []
    for index in range(periods):
        occurs = rng.random() < 0.22
        demand = float(rng.randint(3, 15)) if occurs else 0.0
        rows.append(
            {
                "series_id": "intermittent-sku",
                "timestamp": start + timedelta(days=index),
                "demand": demand,
            }
        )
    return pl.DataFrame(
        rows,
        schema={
            "series_id": pl.String,
            "timestamp": pl.Date,
            "demand": pl.Float64,
        },
    )


def main() -> None:
    config = BacktestConfig(
        initial_train_size=56,
        horizon=7,
        step=7,
        season_length=7,
        seed=2026,
    )
    dense_report = run_backtest(
        generate_synthetic_history(series_count=1, periods=84, seed=2026),
        [
            SeasonalNaiveAdapter(season_length=7),
            AutoETSAdapter(season_length=7),
            AutoARIMAAdapter(
                season_length=7,
                max_p=2,
                max_q=2,
                max_P=1,
                max_Q=1,
                max_order=4,
                nmodels=20,
            ),
            ThetaAdapter(season_length=7, decomposition_type="additive"),
        ],
        config,
    )
    sparse_report = run_backtest(
        generate_intermittent_history(),
        [
            SeasonalNaiveAdapter(season_length=7),
            CrostonAdapter(variant="optimized"),
            TSBAdapter(alpha_d=0.2, alpha_p=0.2),
        ],
        config,
    )

    output_dir = Path("artifacts")
    dense_artifact = write_evaluation_artifact(
        dense_report,
        output_dir / "dense-statistical-adapter-evaluation.json",
    )
    sparse_artifact = write_evaluation_artifact(
        sparse_report,
        output_dir / "intermittent-statistical-adapter-evaluation.json",
    )
    print(f"dense_dataset_fingerprint={dense_report.dataset_fingerprint}")
    print(f"dense_artifact_sha256={dense_artifact.sha256}")
    print(f"intermittent_dataset_fingerprint={sparse_report.dataset_fingerprint}")
    print(f"intermittent_artifact_sha256={sparse_artifact.sha256}")


if __name__ == "__main__":
    main()
