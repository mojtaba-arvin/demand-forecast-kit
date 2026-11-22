"""Reproducible local CPU/memory smoke profile for the reference adapter."""

from __future__ import annotations

import argparse
import json
import platform
import time
import tracemalloc

from demand_forecast_kit.models.seasonal_naive import SeasonalNaiveAdapter


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--series", type=int, default=100)
    parser.add_argument("--history", type=int, default=365)
    parser.add_argument("--horizon", type=int, default=28)
    args = parser.parse_args()
    if min(args.series, args.history, args.horizon) < 1:
        parser.error("series, history, and horizon must be positive")

    adapter = SeasonalNaiveAdapter(season_length=7)
    tracemalloc.start()
    started = time.perf_counter()
    for index in range(args.series):
        history = [float((step + index) % 11) for step in range(args.history)]
        adapter.predict(
            f"sku-{index}",
            history,
            horizon=args.horizon,
            quantile_levels=(0.1, 0.5, 0.9),
            seed=42,
        )
    elapsed = time.perf_counter() - started
    _, peak_bytes = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    print(json.dumps({
        "python": platform.python_version(),
        "platform": platform.platform(),
        "adapter": adapter.model_id,
        "series": args.series,
        "history": args.history,
        "horizon": args.horizon,
        "elapsed_seconds": round(elapsed, 6),
        "series_per_second": round(args.series / elapsed, 3),
        "peak_traced_bytes": peak_bytes,
    }, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
