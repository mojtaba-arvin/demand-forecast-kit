import pytest

from demand_forecast_kit.seasonality import detect_season_length


def test_detect_season_length_selects_repeating_weekly_profile() -> None:
    pattern = [1.0, 3.0, 2.0, 8.0, 4.0, 2.0, 1.0]
    result = detect_season_length(pattern * 12, candidates=(7, 14, 28))

    assert result.season_length == 7
    assert result.strength > 0.3


def test_detect_season_length_returns_none_for_constant_history() -> None:
    result = detect_season_length([4.0] * 50, candidates=(7, 14))

    assert result.season_length is None
    assert result.strength == 0.0


def test_detect_season_length_rejects_invalid_candidates_and_short_history() -> None:
    with pytest.raises(ValueError, match="too short"):
        detect_season_length([1.0, 2.0, 3.0], candidates=(7,))
    with pytest.raises(ValueError, match="unique"):
        detect_season_length([1.0] * 20, candidates=(7, 7))
