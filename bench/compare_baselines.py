"""Compare benchmark artifacts only when their execution environments match."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

_WORKLOAD_IDENTITY_FIELDS = {
    "cli_cold_start": ("command",),
    "parquet_scan_validation": ("rows", "series_count_in_file", "file_sha256"),
    "statistical_series_throughput": ("series_count", "history_size", "horizon", "adapter"),
    "api_forecast_latency": ("requests",),
    "streaming_scan_memory": ("rows",),
}


def compare(
    current: dict[str, Any], baseline: dict[str, Any], tolerance: float = 0.05
) -> dict[str, Any]:
    if not 0.0 <= tolerance < 1.0:
        raise ValueError("tolerance must be in [0, 1)")
    if current.get("environment") != baseline.get("environment"):
        raise ValueError("benchmark environments differ; comparison is not valid")
    if current.get("profile") != baseline.get("profile"):
        raise ValueError("benchmark profiles differ; comparison is not valid")
    current_workloads = current.get("workloads", {})
    baseline_workloads = baseline.get("workloads", {})
    if set(current_workloads) != set(baseline_workloads):
        raise ValueError("benchmark workload sets differ")
    results: dict[str, dict[str, float | bool]] = {}
    regressions: list[str] = []
    for name in sorted(current_workloads):
        current_workload = current_workloads[name]
        baseline_workload = baseline_workloads[name]
        identity_fields = _WORKLOAD_IDENTITY_FIELDS.get(name)
        if identity_fields is None:
            raise ValueError(f"unknown benchmark workload identity: {name}")
        for field in identity_fields:
            if field not in current_workload or field not in baseline_workload:
                raise ValueError(f"workload {name} is missing identity field {field}")
            if current_workload[field] != baseline_workload[field]:
                raise ValueError(f"benchmark workload {name} differs at {field}")
        metric = "peak_rss_bytes" if name == "streaming_scan_memory" else "median_seconds"
        current_value = float(current_workload[metric])
        baseline_value = float(baseline_workload[metric])
        if baseline_value <= 0.0 or current_value < 0.0:
            raise ValueError(f"invalid benchmark measurement for {name}")
        change = current_value / baseline_value - 1.0
        regressed = change > tolerance
        results[name] = {
            "metric": metric,
            "current_value": current_value,
            "baseline_value": baseline_value,
            "relative_change": change,
            "regressed": regressed,
        }
        if regressed:
            regressions.append(name)
    return {"tolerance": tolerance, "regressions": regressions, "workloads": results}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("current", type=Path)
    parser.add_argument("baseline", type=Path)
    parser.add_argument("--tolerance", type=float, default=0.05)
    args = parser.parse_args()
    result = compare(
        json.loads(args.current.read_text(encoding="utf-8")),
        json.loads(args.baseline.read_text(encoding="utf-8")),
        args.tolerance,
    )
    print(json.dumps(result, sort_keys=True, indent=2))
    if result["regressions"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
