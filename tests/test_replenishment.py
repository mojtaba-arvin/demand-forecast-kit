import pytest

from demand_forecast_kit.replenishment import reorder_point, safety_stock


def test_reorder_point_uses_cumulative_lead_time_quantiles() -> None:
    assert reorder_point({0.1: 10.0, 0.5: 20.0, 0.9: 40.0}, service_level=0.7) == 30.0
    assert reorder_point({0.1: 10.0, 0.5: 20.0, 0.9: 40.0}, service_level=0.5) == 20.0


def test_reorder_point_rejects_unbracketed_or_crossing_quantiles() -> None:
    with pytest.raises(ValueError, match="bracket"):
        reorder_point({0.1: 10.0, 0.5: 20.0}, service_level=0.9)
    with pytest.raises(ValueError, match="non-decreasing"):
        reorder_point({0.1: 20.0, 0.9: 10.0}, service_level=0.5)
    with pytest.raises(ValueError, match="unique"):
        reorder_point({0.5: 10.0, 0.5000000000000000: 11.0}, service_level=0.5)


def test_safety_stock_is_non_negative_and_validates_inputs() -> None:
    assert safety_stock(reorder_point_value=30.0, expected_lead_time_demand=20.0) == 10.0
    assert safety_stock(reorder_point_value=10.0, expected_lead_time_demand=20.0) == 0.0
    with pytest.raises(ValueError, match="expected_lead_time_demand"):
        safety_stock(reorder_point_value=10.0, expected_lead_time_demand=-1.0)
