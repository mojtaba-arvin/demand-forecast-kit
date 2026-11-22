from __future__ import annotations

import pytest

from demand_forecast_kit.calibration import fit_adaptive_interval_calibrator


def test_global_conformal_correction_expands_only_outside_errors() -> None:
    calibrator = fit_adaptive_interval_calibrator(
        [1, 2, 3, 4, 10],
        [1, 1, 1, 1, 1],
        [3, 3, 3, 3, 3],
        coverage=0.8,
    )

    result = calibrator.apply([0, 2], [2, 4])

    assert calibrator.global_correction == 7
    assert result.lower == (0, 0)
    assert result.upper == (9, 11)


def test_regime_specific_correction_and_global_fallback() -> None:
    actuals = [1.0] * 5 + [10.0] * 5
    lower = [1.0] * 10
    upper = [2.0] * 10
    regimes = ["dense"] * 5 + ["intermittent"] * 5
    calibrator = fit_adaptive_interval_calibrator(
        actuals,
        lower,
        upper,
        coverage=0.8,
        regimes=regimes,
        min_regime_samples=5,
    )

    result = calibrator.apply([1, 1, 1], [2, 2, 2], regimes=["dense", "intermittent", "new"])

    assert calibrator.regime_corrections["dense"] == 0
    assert calibrator.regime_corrections["intermittent"] == 8
    assert result.upper == (2, 10, 10)


def test_insufficient_calibration_data_is_rejected() -> None:
    with pytest.raises(ValueError, match="insufficient calibration"):
        fit_adaptive_interval_calibrator(
            [1, 2, 3],
            [0, 0, 0],
            [1, 1, 1],
            coverage=0.9,
        )


def test_calibrator_validates_bounds_and_regime_lengths() -> None:
    with pytest.raises(ValueError, match="same non-zero length"):
        fit_adaptive_interval_calibrator([1, 2], [0], [2])
    calibrator = fit_adaptive_interval_calibrator(
        [1, 2, 3, 4, 5],
        [0] * 5,
        [2] * 5,
    )
    with pytest.raises(ValueError, match="match the interval length"):
        calibrator.apply([0, 0], [2, 2], regimes=["dense"])
