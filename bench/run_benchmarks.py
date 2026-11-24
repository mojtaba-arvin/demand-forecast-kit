"""Reproducible offline performance workloads; no targets are asserted as achieved."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import statistics
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import polars as pl

from demand_forecast_kit.data import scan_history, validate_history
from demand_forecast_kit.models.seasonal_naive import SeasonalNaiveAdapter
from demand_forecast_kit.run_service import RunService
from demand_forecast_kit.api import create_app


def _measure(operation: Any, repeats: int) -> dict[str, Any]:
    samples: list[float] = []
    for _ in range(repeats):
        started = time.perf_counter()
        operation()
        samples.append(time.perf_counter() - started)
    ordered = sorted(samples)
    p95_index = min(len(ordered) - 1, int(0.95 * len(ordered)))
    return {
        "samples_seconds": samples,
        "median_seconds": statistics.median(samples),
        "p95_seconds": ordered[p95_index],
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_parquet(path: Path, rows: int, series_count: int, seed: int) -> str:
    row = pl.int_range(0, rows, eager=True)
    frame = pl.DataFrame({"row": row}).with_columns(
        ("sku-" + (pl.col("row") % series_count).cast(pl.String)).alias("series_id"),
        (
            pl.lit(datetime(2020, 1, 1))
            + pl.duration(days=pl.col("row") // series_count)
        ).alias("timestamp"),
        (((pl.col("row") * (17 + seed)) % 23).cast(pl.Float64)).alias("demand"),
    ).select("series_id", "timestamp", "demand")
    frame.write_parquet(path, compression="zstd")
    return _sha256(path)


def _streaming_memory(path: Path) -> dict[str, int]:
    child = """
import json
import platform
import resource
import sys
import polars as pl
from demand_forecast_kit.data import scan_history
count = scan_history(sys.argv[1]).select(pl.len()).collect(engine="streaming").item()
rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
print(json.dumps({"row_count": int(count), "peak_rss_bytes": int(rss if platform.system() == "Darwin" else rss * 1024)}))
"""
    completed = subprocess.run(
        [sys.executable, "-c", child, str(path)],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


def _benchmark_series(series_count: int, history_size: int, horizon: int) -> None:
    adapter = SeasonalNaiveAdapter(season_length=7)
    for index in range(series_count):
        history = tuple(float((step * 17 + index) % 23) for step in range(history_size))
        adapter.predict(
            f"sku-{index}",
            history,
            horizon=horizon,
            quantile_levels=(0.1, 0.5, 0.9),
            seed=42,
        )


def _api_health(requests: int, state_dir: Path) -> dict[str, Any]:
    from fastapi.testclient import TestClient

    app = create_app(RunService(state_dir))
    with TestClient(app) as client:
        latencies: list[float] = []
        history = [float((index * 7) % 13) for index in range(56)]
        for index in range(requests):
            started = time.perf_counter()
            response = client.post(
                "/v1/forecasts",
                json={
                    "series_id": f"api-bench-{index}",
                    "history": history,
                    "horizon": 7,
                    "season_length": 7,
                },
            )
            latencies.append(time.perf_counter() - started)
            if response.status_code != 200:
                raise RuntimeError(f"forecast endpoint returned {response.status_code}")
    ordered = sorted(latencies)
    p95 = ordered[min(len(ordered) - 1, int(0.95 * len(ordered)))]
    return {
        "requests": requests,
        "median_seconds": statistics.median(latencies),
        "p50_seconds": statistics.median(latencies),
        "p95_seconds": p95,
        "p99_seconds": ordered[min(len(ordered) - 1, int(0.99 * len(ordered)))],
    }


def run(profile: str, output: Path, repeats: int) -> dict[str, Any]:
    full = profile == "full"
    rows = 10_000_000 if full else 10_000
    series_count = 100_000 if full else 1_000
    history_size = 56
    horizon = 14
    api_requests = 1_000 if full else 100
    seed = 20261124

    with tempfile.TemporaryDirectory(prefix="demand-forecast-bench-") as directory:
        root = Path(directory)
        parquet_path = root / "history.parquet"
        dataset_sha = _write_parquet(parquet_path, rows, min(series_count, 10_000), seed)

        parquet_result = _measure(
            lambda: validate_history(scan_history(parquet_path)),
            repeats,
        )
        memory_result = _streaming_memory(parquet_path)
        quality = validate_history(scan_history(parquet_path))
        if not quality.is_valid or quality.row_count != rows or memory_result["row_count"] != rows:
            raise RuntimeError("generated Parquet benchmark workload failed validation")

        series_result = _measure(
            lambda: _benchmark_series(series_count, history_size, horizon),
            repeats,
        )

        cli_result = _measure(
            lambda: subprocess.run(
                ["demand-forecast", "--help"],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            ),
            repeats,
        )
        api_result = _api_health(api_requests, root / "api-state")

        return {
            "schema_version": 1,
            "profile": profile,
            "seed": seed,
            "source_revision": os.environ.get("GITHUB_SHA"),
            "environment": {
                "python": platform.python_version(),
                "implementation": platform.python_implementation(),
                "platform": platform.platform(),
                "machine": platform.machine(),
                "processor": platform.processor(),
                "cpu_count": os.cpu_count(),
                "polars": pl.__version__,
            },
            "workloads": {
                "cli_cold_start": {
                    **cli_result,
                    "repeats": repeats,
                    "command": ["demand-forecast", "--help"],
                },
                "parquet_scan_validation": {
                    **parquet_result,
                    "rows": rows,
                    "series_count_in_file": min(series_count, 10_000),
                    "file_sha256": dataset_sha,
                    "file_size_bytes": parquet_path.stat().st_size,
                    "quality_report": {
                        "row_count": quality.row_count,
                        "series_count": quality.series_count,
                    },
                },
                "statistical_series_throughput": {
                    **series_result,
                    "series_count": series_count,
                    "history_size": history_size,
                    "horizon": horizon,
                    "adapter": "seasonal-naive",
                    "series_per_second": series_count / series_result["median_seconds"],
                },
                "api_forecast_latency": api_result,
                "streaming_scan_memory": {
                    "peak_rss_bytes": memory_result["peak_rss_bytes"],
                    "row_count": memory_result["row_count"],
                    "rows": rows,
                },
            },
            "interpretation": {
                "performance_targets_enforced": False,
                "reason": "Reference-runner variance and baseline stability must be characterized first.",
                "comparison_requires_matching_environment": True,
            },
        }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", choices=("smoke", "full"), default="smoke")
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--output", type=Path, default=Path("artifacts/performance-baseline.json"))
    args = parser.parse_args()
    if args.repeats < 3:
        parser.error("repeats must be >= 3 to characterize run-to-run variance")
    result = run(args.profile, args.output, args.repeats)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, sort_keys=True, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    print(f"benchmark_artifact={args.output}")
    print(f"dataset_sha256={result['workloads']['parquet_scan_validation']['file_sha256']}")


if __name__ == "__main__":
    main()
