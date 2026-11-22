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


def test_quantile_coverage_estimates_report_each_level_and_uncertainty() -> None:
    from demand_forecast_kit.calibration_diagnostics import quantile_coverage_estimates

    estimates = quantile_coverage_estimates(
        [1.0, 2.0, 3.0, 4.0],
        {
            0.1: [1.0, 2.0, 3.0, 3.0],
            0.5: [2.0, 3.0, 4.0, 5.0],
            0.8: [3.0, 4.0, 5.0, 6.0],
            0.9: [4.0, 5.0, 6.0, 7.0],
        },
    )

    assert tuple(estimates) == (0.1, 0.5, 0.8, 0.9)
    assert estimates[0.1].coverage == 0.75
    assert estimates[0.5].coverage == 1.0
    assert estimates[0.8].coverage == 1.0
    assert estimates[0.9].coverage == 1.0
    assert estimates[0.1].lower < estimates[0.1].coverage < estimates[0.1].upper


def test_quantile_coverage_rejects_misaligned_and_crossing_forecasts() -> None:
    from demand_forecast_kit.calibration_diagnostics import quantile_coverage_estimates

    with pytest.raises(ValueError, match="match the actuals length"):
        quantile_coverage_estimates([1.0, 2.0], {0.5: [1.0]})
    with pytest.raises(ValueError, match="non-decreasing"):
        quantile_coverage_estimates(
            [1.0, 2.0],
            {0.1: [2.0, 1.0], 0.9: [1.0, 2.0]},
        )
    with pytest.raises(ValueError, match="booleans"):
        wilson_coverage_interval([1, 0])  # type: ignore[list-item]
