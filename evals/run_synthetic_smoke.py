"""Generate a small, deterministic baseline report for CI artifact inspection."""

from pathlib import Path

from demand_forecast_kit.backtesting import BacktestConfig, run_backtest, write_evaluation_artifact
from demand_forecast_kit.models.seasonal_naive import SeasonalNaiveAdapter
from demand_forecast_kit.synthetic import generate_synthetic_history


def main() -> None:
    history = generate_synthetic_history(series_count=3, periods=84, seed=2026)
    report = run_backtest(
        history,
        [SeasonalNaiveAdapter(season_length=7)],
        BacktestConfig(
            initial_train_size=42,
            horizon=14,
            step=14,
            season_length=7,
            seed=2026,
        ),
    )
    artifact = write_evaluation_artifact(
        report,
        Path("artifacts") / "synthetic-baseline-evaluation.json",
    )
    print(f"dataset_fingerprint={report.dataset_fingerprint}")
    print(f"artifact_sha256={artifact.sha256}")
    print(f"artifact_size_bytes={artifact.size_bytes}")


if __name__ == "__main__":
    main()
