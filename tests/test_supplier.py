import pytest

from demand_forecast_kit.supplier import SupplierConstraints, apply_supplier_constraints


def test_supplier_constraints_apply_moq_and_order_multiple() -> None:
    result = apply_supplier_constraints(
        11,
        SupplierConstraints(minimum_order_quantity=12, order_multiple=5),
    )

    assert result.order_quantity == 15
    assert result.unmet_quantity == 0
    assert not result.constraint_limited


def test_supplier_capacity_limits_order_and_reports_unmet_demand() -> None:
    result = apply_supplier_constraints(
        23,
        SupplierConstraints(order_multiple=5, available_capacity=17),
    )

    assert result.order_quantity == 15
    assert result.unmet_quantity == 8
    assert result.constraint_limited


def test_moq_is_not_forced_when_no_order_is_needed() -> None:
    result = apply_supplier_constraints(
        0,
        SupplierConstraints(minimum_order_quantity=20),
    )

    assert result.order_quantity == 0


def test_infeasible_minimum_order_returns_zero_and_exposes_shortfall() -> None:
    result = apply_supplier_constraints(
        12,
        SupplierConstraints(minimum_order_quantity=10, order_multiple=5, available_capacity=8),
    )

    assert result.order_quantity == 0
    assert result.unmet_quantity == 12
    assert result.constraint_limited


def test_supplier_constraints_reject_invalid_limits() -> None:
    with pytest.raises(ValueError, match="exceeds"):
        SupplierConstraints(minimum_order_quantity=10, maximum_order_quantity=5)
