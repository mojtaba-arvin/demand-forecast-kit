"""Compare benchmark artifacts only when their execution environments match."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

_WORKLOAD_IDENTITY_FIELDS = {
    "cli_cold_start": ("command",),
    "parquet_scan_validation": ("rows", "series_count_in_file", "file_sha256"),
    "statistical_series_throughput": ("series_count", "history_size", "horizon", "adapter"),
    "api_forecast_latency": ("requests",),
    "streaming_scan_memory": ("rows",),
}


def _measurement(value: Any, *, name: str, metric: str, allow_zero: bool) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"invalid {metric} measurement for {name}")
    numeric = float(value)
    if not math.isfinite(numeric) or numeric < 0.0 or (numeric == 0.0 and not allow_zero):
        raise ValueError(f"invalid {metric} measurement for {name}")
    return numeric


def compare(
    current: dict[str, Any], baseline: dict[str, Any], tolerance: float = 0.05
) -> dict[str, Any]:
    if not math.isfinite(tolerance) or not 0.0 <= tolerance < 1.0:
        raise ValueError("tolerance must be finite and in [0, 1)")
    if current.get("environment") != baseline.get("environment"):
        raise ValueError("benchmark environments differ; comparison is not valid")
    if current.get("profile") != baseline.get("profile"):
        raise ValueError("benchmark profiles differ; comparison is not valid")
    calibrated = baseline.get("baseline_type") == "calibrated-performance-baseline"
    if calibrated:
        sample_count = baseline.get("sample_count")
        if isinstance(sample_count, bool) or not isinstance(sample_count, int) or sample_count < 10:
            raise ValueError("calibrated baseline must contain at least 10 independent runs")
        for field in ("workload_sha256", "seed"):
            if current.get(field) != baseline.get(field):
                raise ValueError(f"benchmark {field} differs; comparison is not valid")
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
        current_value = _measurement(
            current_workload.get(metric), name=name, metric=metric, allow_zero=True
        )
        baseline_value = _measurement(
            baseline_workload.get(metric), name=name, metric=metric, allow_zero=False
        )
        raw_tolerance = (
            baseline_workload.get("calibrated_tolerance")
            if calibrated
            else baseline_workload.get("calibrated_tolerance", tolerance)
        )
        if isinstance(raw_tolerance, bool) or not isinstance(raw_tolerance, (int, float)):
            raise ValueError(f"invalid calibrated tolerance for {name}")
        workload_tolerance = float(raw_tolerance)
        if not math.isfinite(workload_tolerance) or not 0.0 <= workload_tolerance < 1.0:
            raise ValueError(f"invalid calibrated tolerance for {name}")
        change = current_value / baseline_value - 1.0
        regressed = change > workload_tolerance
        results[name] = {
            "metric": metric,
            "current_value": current_value,
            "baseline_value": baseline_value,
            "relative_change": change,
            "tolerance": workload_tolerance,
            "regressed": regressed,
        }
        if regressed:
            regressions.append(name)
    return {
        "tolerance": tolerance,
        "current_source_revision": current.get("source_revision"),
        "baseline_source_revision": baseline.get("source_revision"),
        "regressions": regressions,
        "workloads": results,
    }


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
    print(json.dumps(result, sort_keys=True, indent=2, allow_nan=False))
    if result["regressions"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
