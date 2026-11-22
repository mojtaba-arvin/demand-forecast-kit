"""Supplier order constraints applied after demand-based replenishment sizing."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SupplierConstraints:
    """Minimum, maximum, multiple, and available supplier capacity."""

    minimum_order_quantity: int = 0
    maximum_order_quantity: int | None = None
    order_multiple: int = 1
    available_capacity: int | None = None

    def __post_init__(self) -> None:
        if type(self.minimum_order_quantity) is not int or self.minimum_order_quantity < 0:
            raise ValueError("minimum_order_quantity must be a non-negative integer")
        if type(self.order_multiple) is not int or self.order_multiple < 1:
            raise ValueError("order_multiple must be a positive integer")
        for name, value in (
            ("maximum_order_quantity", self.maximum_order_quantity),
            ("available_capacity", self.available_capacity),
        ):
            if value is not None and (type(value) is not int or value < 0):
                raise ValueError(f"{name} must be a non-negative integer")
        if (
            self.maximum_order_quantity is not None
            and self.minimum_order_quantity > self.maximum_order_quantity
        ):
            raise ValueError("minimum order quantity exceeds supplier maximum")


@dataclass(frozen=True, slots=True)
class ConstrainedOrder:
    """Requested quantity after applying supplier feasibility constraints."""

    requested_quantity: int
    order_quantity: int
    unmet_quantity: int
    constraint_limited: bool


def apply_supplier_constraints(
    requested_quantity: int,
    constraints: SupplierConstraints,
) -> ConstrainedOrder:
    """Apply MOQ, order multiple, maximum order, and available capacity.

    A zero demand-based order remains zero; MOQ does not force an unnecessary
    purchase. When capacity prevents a feasible MOQ, the function returns the
    feasible quantity and exposes the unmet amount instead of hiding the limit.
    """
    if type(requested_quantity) is not int or requested_quantity < 0:
        raise ValueError("requested_quantity must be a non-negative integer")
    if requested_quantity == 0:
        return ConstrainedOrder(0, 0, 0, False)

    multiple = constraints.order_multiple
    desired = max(requested_quantity, constraints.minimum_order_quantity)
    rounded = ((desired + multiple - 1) // multiple) * multiple
    limits = [
        value
        for value in (constraints.maximum_order_quantity, constraints.available_capacity)
        if value is not None
    ]
    upper = min(limits) if limits else None
    feasible = rounded if upper is None else (upper // multiple) * multiple
    quantity = max(0, feasible)
    if quantity < constraints.minimum_order_quantity and upper is not None:
        quantity = 0
    return ConstrainedOrder(
        requested_quantity=requested_quantity,
        order_quantity=quantity,
        unmet_quantity=max(0, requested_quantity - quantity),
        constraint_limited=quantity < rounded,
    )
