from __future__ import annotations

from copy import deepcopy

import pytest

from bench.calibrate_baseline import calibrate
from bench.compare_baselines import compare


def make_artifact(index: int, *, seconds: float = 1.0) -> dict[str, object]:
    return {
        "schema_version": 2,
        "execution_id": f"run-{index}",
        "profile": "full",
        "source_revision": "a" * 40,
        "workload_sha256": "workload-hash",
        "seed": 42,
        "environment": {
            "python": "3.13.1",
            "machine": "x86_64",
            "cpu_model": "reference-cpu",
            "runner": {"RUNNER_OS": "Linux", "ImageVersion": "2026.11"},
        },
        "workloads": {
            "cli_cold_start": {"median_seconds": seconds, "command": ["demand-forecast", "--help"]},
            "parquet_scan_validation": {
                "median_seconds": seconds * 2,
                "rows": 10_000_000,
                "series_count_in_file": 10_000,
                "file_sha256": "dataset-hash",
            },
            "statistical_series_throughput": {
                "median_seconds": seconds * 3,
                "series_count": 100_000,
                "history_size": 56,
                "horizon": 14,
                "adapter": "seasonal-naive",
            },
            "api_forecast_latency": {"median_seconds": seconds * 4, "requests": 1_000},
            "streaming_scan_memory": {"peak_rss_bytes": seconds * 1024, "rows": 10_000_000},
        },
    }


def test_calibration_requires_ten_independent_full_runs() -> None:
    with pytest.raises(ValueError, match="at least 10"):
        calibrate([make_artifact(index) for index in range(9)])


def test_calibration_rejects_duplicate_run_ids_and_mismatched_provenance() -> None:
    reports = [make_artifact(index) for index in range(10)]
    duplicate = deepcopy(reports)
    duplicate[1]["execution_id"] = duplicate[0]["execution_id"]  # type: ignore[index]
    with pytest.raises(ValueError, match="distinct execution_id"):
        calibrate(duplicate)

    mismatch = deepcopy(reports)
    mismatch[1]["environment"]["cpu_model"] = "different-cpu"  # type: ignore[index]
    with pytest.raises(ValueError, match="environments differ"):
        calibrate(mismatch)


def test_calibration_rejects_different_source_or_workload() -> None:
    reports = [make_artifact(index) for index in range(10)]
    changed_source = deepcopy(reports)
    changed_source[1]["source_revision"] = "b" * 40
    with pytest.raises(ValueError, match="source revisions differ"):
        calibrate(changed_source)

    changed_workload = deepcopy(reports)
    changed_workload[1]["workload_sha256"] = "other-workload"
    with pytest.raises(ValueError, match="workload fingerprints differ"):
        calibrate(changed_workload)


def test_calibration_uses_median_and_increases_tolerance_for_noisy_runs() -> None:
    values = [0.90, 0.95, 1.00, 1.00, 1.00, 1.00, 1.00, 1.05, 1.10, 1.20]
    baseline = calibrate([make_artifact(i, seconds=value) for i, value in enumerate(values)])
    assert baseline["sample_count"] == 10
    workload = baseline["workloads"]["cli_cold_start"]
    assert workload["median_seconds"] == 1.0
    assert workload["calibrated_tolerance"] > 0.05
    assert workload["sample_count"] == 10


def test_comparator_uses_per_workload_calibrated_tolerance() -> None:
    baseline = make_artifact(100)
    baseline["workloads"]["cli_cold_start"]["calibrated_tolerance"] = 0.15  # type: ignore[index]
    current = make_artifact(101, seconds=1.10)
    result = compare(current, baseline, tolerance=0.05)
    assert result["workloads"]["cli_cold_start"]["regressed"] is False
    assert result["workloads"]["cli_cold_start"]["tolerance"] == 0.15


def test_calibration_rejects_invalid_measurements() -> None:
    reports = [make_artifact(index) for index in range(10)]
    reports[0]["workloads"]["cli_cold_start"]["median_seconds"] = float("nan")  # type: ignore[index]
    with pytest.raises(ValueError, match="non-positive or non-finite"):
        calibrate(reports)


def test_comparator_rejects_calibrated_baseline_provenance_mismatch() -> None:
    current = make_artifact(101)
    baseline = make_artifact(100)
    baseline["baseline_type"] = "calibrated-performance-baseline"
    baseline["sample_count"] = 10
    baseline["workload_sha256"] = "expected-workload"
    with pytest.raises(ValueError, match="workload_sha256 differs"):
        compare(current, baseline)


def test_comparator_allows_new_source_revision_against_calibrated_baseline() -> None:
    current = make_artifact(101)
    current["source_revision"] = "b" * 40
    baseline = make_artifact(100)
    baseline["baseline_type"] = "calibrated-performance-baseline"
    baseline["sample_count"] = 10
    result = compare(current, baseline)
    assert result["current_source_revision"] == "b" * 40
    assert result["baseline_source_revision"] == "a" * 40
