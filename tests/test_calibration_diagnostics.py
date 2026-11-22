import pytest

from demand_forecast_kit.calibration_diagnostics import wilson_coverage_interval


def test_wilson_interval_reports_empirical_coverage_and_bounds() -> None:
    estimate = wilson_coverage_interval([True] * 8 + [False] * 2)

    assert estimate.successes == 8
    assert estimate.observations == 10
    assert estimate.coverage == 0.8
    assert 0.0 <= estimate.lower < estimate.coverage < estimate.upper <= 1.0


def test_wilson_interval_handles_all_successes_without_degenerate_bounds() -> None:
    estimate = wilson_coverage_interval([True] * 5)

    assert estimate.coverage == 1.0
    assert estimate.lower < 1.0
    assert estimate.upper == 1.0


def test_wilson_interval_rejects_empty_and_invalid_confidence() -> None:
    with pytest.raises(ValueError, match="at least one"):
        wilson_coverage_interval([])
    with pytest.raises(ValueError, match="confidence_z"):
        wilson_coverage_interval([True], confidence_z=0.0)
