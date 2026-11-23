"""Command-line rolling-origin evaluation for canonical CSV/Parquet history."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from demand_forecast_kit.backtesting import BacktestConfig, run_backtest
from demand_forecast_kit.data import scan_history
from demand_forecast_kit.models.seasonal_naive import SeasonalNaiveAdapter
from demand_forecast_kit.run_service import RunService


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
    parser.add_argument("--state-dir", type=Path, default=Path(".demand-forecast-kit"))
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

    service = RunService(args.state_dir)
    report_payload = report.to_dict()
    model = report.model_summaries[0]
    config = {
        "initial_train_size": config.initial_train_size,
        "horizon": config.horizon,
        "step": config.step,
        "season_length": config.season_length,
        "quantile_levels": list(config.quantile_levels),
        "coverage_levels": list(config.coverage_levels),
        "seed": config.seed,
    }
    run = service.record_run(
        idempotency_key=service.idempotency_key(
            dataset_fingerprint=report.dataset_fingerprint,
            model_id=model.model_id,
            model_version=model.model_version,
            config=config,
        ),
        dataset_fingerprint=report.dataset_fingerprint,
        model_id=model.model_id,
        model_version=model.model_version,
        config=config,
        result=report_payload,
        artifact_payload=report.to_json_bytes(),
    )
    payload = json.dumps(
        {**report_payload, "run": run.to_dict()},
        ensure_ascii=False,
        sort_keys=True,
        indent=2,
        allow_nan=False,
    ) + "\\n"
    if args.output is None:
        print(payload, end="")
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
