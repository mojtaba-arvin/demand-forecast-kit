import pytest

from demand_forecast_kit.diagnostics import detect_level_shift


def test_detect_level_shift_flags_a_material_increase() -> None:
    result = detect_level_shift(
        [10.0] * 8 + [20.0] * 8,
        window=8,
        relative_threshold=0.5,
    )

    assert result.prior_median == 10.0
    assert result.recent_median == 20.0
    assert result.relative_change == 1.0
    assert result.detected


def test_detect_level_shift_does_not_flag_stable_history() -> None:
    result = detect_level_shift([0.0, 2.0, 1.0, 2.0, 0.0, 2.0, 1.0, 2.0], window=4)

    assert not result.detected
    assert result.relative_change == 0.0


def test_detect_level_shift_rejects_insufficient_or_invalid_history() -> None:
    with pytest.raises(ValueError, match="two complete windows"):
        detect_level_shift([1.0, 2.0, 3.0], window=2)
    with pytest.raises(ValueError, match="non-negative"):
        detect_level_shift([1.0, -1.0, 2.0, 3.0], window=2)
    with pytest.raises(ValueError, match="relative_threshold"):
        detect_level_shift([1.0, 2.0, 3.0, 4.0], window=2, relative_threshold=0.0)
