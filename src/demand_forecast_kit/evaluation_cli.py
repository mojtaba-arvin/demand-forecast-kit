"""Command-line rolling-origin evaluation for canonical CSV/Parquet history."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path

from demand_forecast_kit.backtesting import BacktestConfig, run_backtest
from demand_forecast_kit.data import scan_history
from demand_forecast_kit.models.seasonal_naive import SeasonalNaiveAdapter


def main(argv: Sequence[str] | None = None) -> int:
    """Evaluate the seasonal-naive adapter with leakage-aware rolling origins."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="CSV or Parquet demand history")
    parser.add_argument("--initial-train-size", type=int, default=30)
    parser.add_argument("--horizon", type=int, default=7)
    parser.add_argument("--step", type=int, default=1)
    parser.add_argument("--season-length", type=int, default=7)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--output", type=Path, help="write canonical JSON to this path")
    args = parser.parse_args(argv)

    try:
        config = BacktestConfig(
            initial_train_size=args.initial_train_size,
            horizon=args.horizon,
            step=args.step,
            season_length=args.season_length,
            seed=args.seed,
        )
        history = scan_history(args.input)
        report = run_backtest(
            history,
            [SeasonalNaiveAdapter(season_length=args.season_length)],
            config,
        )
    except (OSError, ValueError) as exc:
        parser.error(str(exc))

    payload = report.to_json_bytes()
    if args.output is None:
        print(payload.decode("utf-8"), end="")
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_bytes(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
