import pytest

from demand_forecast_kit.data import validate_history
from demand_forecast_kit.synthetic import generate_synthetic_history


def test_synthetic_history_is_seeded_and_valid() -> None:
    first = generate_synthetic_history(series_count=2, periods=14, seed=9)
    second = generate_synthetic_history(series_count=2, periods=14, seed=9)

    assert first.equals(second)
    assert first.height == 28
    assert validate_history(first).is_valid


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"series_count": 0}, "series_count"),
        ({"periods": 0}, "periods"),
        ({"series_count": True}, "series_count"),
        ({"seed": -1}, "seed"),
    ],
)
def test_synthetic_history_rejects_invalid_parameters(
    kwargs: dict[str, object], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        generate_synthetic_history(**kwargs)  # type: ignore[arg-type]
