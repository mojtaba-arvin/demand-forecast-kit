"""Build a variance-aware baseline from independent full-profile artifacts."""

from __future__ import annotations

import argparse
import json
import math
import statistics
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from bench.compare_baselines import _WORKLOAD_IDENTITY_FIELDS

_WORKLOAD_METRICS = {
    "cli_cold_start": "median_seconds",
    "parquet_scan_validation": "median_seconds",
    "statistical_series_throughput": "median_seconds",
    "api_forecast_latency": "median_seconds",
    "streaming_scan_memory": "peak_rss_bytes",
}


def calibrate(
    artifacts: list[dict[str, Any]],
    *,
    minimum_runs: int = 10,
    minimum_tolerance: float = 0.05,
    sigma_multiplier: float = 3.0,
) -> dict[str, Any]:
    if minimum_runs < 10:
        raise ValueError("minimum_runs must be >= 10")
    if len(artifacts) < minimum_runs:
        raise ValueError(f"at least {minimum_runs} independent artifacts are required")
    if not 0.0 <= minimum_tolerance < 1.0:
        raise ValueError("minimum_tolerance must be in [0, 1)")
    if not math.isfinite(sigma_multiplier) or sigma_multiplier <= 0.0:
        raise ValueError("sigma_multiplier must be finite and > 0")

    execution_ids = [item.get("execution_id") for item in artifacts]
    if any(not isinstance(value, str) or not value for value in execution_ids):
        raise ValueError("every artifact must contain a non-empty execution_id")
    if len(set(execution_ids)) != len(execution_ids):
        raise ValueError("artifacts must have distinct execution_id values")

    first = artifacts[0]
    if first.get("schema_version") != 2 or first.get("profile") != "full":
        raise ValueError("calibration requires schema version 2 full-profile artifacts")
    source_revision = first.get("source_revision")
    if not isinstance(source_revision, str) or not source_revision:
        raise ValueError("artifacts must identify a source_revision")
    environment = first.get("environment")
    workload_sha256 = first.get("workload_sha256")
    seed = first.get("seed")
    workloads = first.get("workloads")
    if not isinstance(environment, dict) or not isinstance(workloads, dict):
        raise ValueError("artifact environment and workloads must be objects")
    if not isinstance(workload_sha256, str) or not workload_sha256:
        raise ValueError("artifacts must include workload_sha256")

    for index, artifact in enumerate(artifacts):
        if artifact.get("schema_version") != 2 or artifact.get("profile") != "full":
            raise ValueError(f"artifact {index} is not a schema version 2 full-profile run")
        if artifact.get("environment") != environment:
            raise ValueError("benchmark environments differ; calibration is not valid")
        if artifact.get("source_revision") != source_revision:
            raise ValueError("source revisions differ; calibration is not valid")
        if artifact.get("workload_sha256") != workload_sha256:
            raise ValueError("workload fingerprints differ; calibration is not valid")
        if artifact.get("seed") != seed:
            raise ValueError("benchmark seeds differ; calibration is not valid")
        if set(artifact.get("workloads", {})) != set(workloads):
            raise ValueError("benchmark workload sets differ")

    calibrated_workloads: dict[str, dict[str, Any]] = {}
    for name, metric in _WORKLOAD_METRICS.items():
        if name not in workloads:
            raise ValueError(f"required benchmark workload is missing: {name}")
        identity_fields = _WORKLOAD_IDENTITY_FIELDS[name]
        samples: list[float] = []
        for index, artifact in enumerate(artifacts):
            workload = artifact["workloads"][name]
            reference = workloads[name]
            for field in identity_fields:
                if field not in workload or field not in reference:
                    raise ValueError(f"workload {name} is missing identity field {field}")
                if workload[field] != reference[field]:
                    raise ValueError(f"workload {name} identity differs at {field}")
            value = workload.get(metric)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"artifact {index} has invalid {metric} for {name}")
            numeric = float(value)
            if not math.isfinite(numeric) or numeric <= 0.0:
                raise ValueError(f"artifact {index} has non-positive or non-finite {metric}")
            samples.append(numeric)

        center = statistics.median(samples)
        mad = statistics.median(abs(value - center) for value in samples)
        robust_sigma = 1.4826 * mad
        relative_noise = robust_sigma / center
        calibrated_tolerance = max(minimum_tolerance, sigma_multiplier * relative_noise)
        calibrated_workloads[name] = {
            **{field: workloads[name][field] for field in identity_fields},
            metric: center,
            "sample_count": len(samples),
            "samples": samples,
            "median_absolute_deviation": mad,
            "robust_sigma": robust_sigma,
            "relative_noise": relative_noise,
            "calibrated_tolerance": calibrated_tolerance,
        }

    return {
        "schema_version": 1,
        "baseline_type": "calibrated-performance-baseline",
        "calibrated_at": datetime.now(timezone.utc).isoformat(),
        "sample_count": len(artifacts),
        "execution_ids": execution_ids,
        "source_revision": source_revision,
        "workload_sha256": workload_sha256,
        "profile": "full",
        "seed": seed,
        "environment": environment,
        "calibration_method": "median_of_independent_runs_with_scaled_mad",
        "minimum_tolerance": minimum_tolerance,
        "sigma_multiplier": sigma_multiplier,
        "workloads": calibrated_workloads,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("artifacts", nargs="+", type=Path)
    parser.add_argument("--minimum-runs", type=int, default=10)
    parser.add_argument("--minimum-tolerance", type=float, default=0.05)
    parser.add_argument("--sigma-multiplier", type=float, default=3.0)
    parser.add_argument("--output", type=Path, default=Path("artifacts/calibrated-baseline.json"))
    args = parser.parse_args()

    reports = [json.loads(path.read_text(encoding="utf-8")) for path in args.artifacts]
    baseline = calibrate(
        reports,
        minimum_runs=args.minimum_runs,
        minimum_tolerance=args.minimum_tolerance,
        sigma_multiplier=args.sigma_multiplier,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(baseline, sort_keys=True, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    print(f"calibrated_baseline={args.output}")
    print(f"independent_runs={baseline['sample_count']}")
    for name, workload in baseline["workloads"].items():
        print(f"{name}: tolerance={workload['calibrated_tolerance']:.4%}")


if __name__ == "__main__":
    main()
