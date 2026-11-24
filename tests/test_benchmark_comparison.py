from __future__ import annotations

import pytest

from bench.compare_baselines import compare


def make_report(seconds: float, *, machine: str = "x86_64") -> dict[str, object]:
    return {
        "profile": "smoke",
        "environment": {"python": "3.13", "machine": machine},
        "workloads": {
            "cli_cold_start": {"median_seconds": seconds},
            "parquet_scan_validation": {"median_seconds": seconds * 2},
        },
    }


def test_benchmark_comparison_flags_only_regressions_above_tolerance() -> None:
    result = compare(make_report(1.06), make_report(1.0), tolerance=0.05)
    assert result["regressions"] == ["cli_cold_start", "parquet_scan_validation"]


def test_benchmark_comparison_rejects_incompatible_environment_and_profile() -> None:
    with pytest.raises(ValueError, match="environments differ"):
        compare(make_report(1.0), make_report(1.0, machine="arm64"))
    baseline = make_report(1.0)
    baseline["profile"] = "full"
    with pytest.raises(ValueError, match="profiles differ"):
        compare(make_report(1.0), baseline)


def test_benchmark_comparison_rejects_invalid_tolerance() -> None:
    with pytest.raises(ValueError, match="tolerance"):
        compare(make_report(1.0), make_report(1.0), tolerance=1.0)
