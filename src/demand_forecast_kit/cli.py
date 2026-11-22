"""Command-line interface for deterministic single-machine forecasting."""

from __future__ import annotations

from collections.abc import Sequence
import argparse
import json
from pathlib import Path

from demand_forecast_kit.data import scan_history, validate_history
from demand_forecast_kit.models.seasonal_naive import SeasonalNaiveAdapter


def _quantiles(raw: str) -> tuple[float, ...]:
    try:
        values = tuple(float(item.strip()) for item in raw.split(","))
    except ValueError as exc:
        raise argparse.ArgumentTypeError("quantiles must be comma-separated numbers") from exc
    if not values or any(not 0.0 < value < 1.0 for value in values):
        raise argparse.ArgumentTypeError("quantiles must be strictly between 0 and 1")
    if len(set(values)) != len(values):
        raise argparse.ArgumentTypeError("quantiles must be unique")
    return tuple(sorted(values))


def main(argv: Sequence[str] | None = None) -> int:
    """Run a seasonal-naive forecast from a CSV or Parquet history file."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="CSV or Parquet demand history")
    parser.add_argument("--horizon", type=int, default=14)
    parser.add_argument("--season-length", type=int, default=7)
    parser.add_argument("--quantiles", type=_quantiles, default=(0.1, 0.5, 0.9))
    parser.add_argument("--output", type=Path, help="write JSON to this path instead of stdout")
    args = parser.parse_args(argv)
    if args.horizon < 1 or args.season_length < 1:
        parser.error("horizon and season-length must be positive")

    history = scan_history(args.input).collect()
    quality = validate_history(history)
    if not quality.is_valid:
        parser.error("invalid demand history: " + "; ".join(quality.issues))

    adapter = SeasonalNaiveAdapter(season_length=args.season_length)
    forecasts = []
    for series in history.sort(["series_id", "timestamp"]).partition_by(
        "series_id", maintain_order=True
    ):
        series_id = str(series["series_id"][0])
        forecast = adapter.predict(
            series_id,
            series["demand"].to_list(),
            horizon=args.horizon,
            quantile_levels=args.quantiles,
            seed=0,
        )
        forecasts.append({
            "series_id": series_id,
            "model_id": adapter.model_id,
            "model_version": adapter.model_version,
            "horizon": forecast.horizon,
            "quantiles": {str(level): list(values) for level, values in forecast.quantiles.items()},
        })
    payload = json.dumps(
        {"schema_version": 1, "forecasts": forecasts},
        sort_keys=True,
        indent=2,
        allow_nan=False,
    ) + "\n"
    if args.output is None:
        print(payload, end="")
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
