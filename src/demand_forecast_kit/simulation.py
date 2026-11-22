"""Deterministic periodic-review stockout and backorder simulation."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from math import isfinite


@dataclass(frozen=True, slots=True)
class InventorySimulationConfig:
    """Fixed policy inputs for a single-item replenishment simulation."""

    initial_on_hand: float
    reorder_point: float
    order_quantity: float
    lead_time_days: int
    allow_backorders: bool = True

    def __post_init__(self) -> None:
        for name, value in (
            ("initial_on_hand", self.initial_on_hand),
            ("reorder_point", self.reorder_point),
            ("order_quantity", self.order_quantity),
        ):
            if not isfinite(value) or value < 0.0:
                raise ValueError(f"{name} must be finite and non-negative")
        if self.order_quantity <= 0.0:
            raise ValueError("order_quantity must be positive")
        if type(self.lead_time_days) is not int or self.lead_time_days < 1:
            raise ValueError("lead_time_days must be a positive integer")


@dataclass(frozen=True, slots=True)
class DailyInventoryState:
    """End-of-day stock and service state."""

    day: int
    demand: float
    received: float
    ordered: float
    fulfilled: float
    lost_sales: float
    backorders: float
    on_hand: float
    inventory_position: float


@dataclass(frozen=True, slots=True)
class InventorySimulationReport:
    """Aggregate service and stock outcomes for one demand sequence."""

    days: tuple[DailyInventoryState, ...]
    total_demand: float
    total_fulfilled: float
    total_lost_sales: float
    ending_backorders: float
    ending_on_hand: float
    total_ordered: float
    fill_rate: float
    stockout_days: int


def simulate_inventory_policy(
    demand: Sequence[float],
    config: InventorySimulationConfig,
) -> InventorySimulationReport:
    """Simulate daily demand, fixed-lot reorder decisions, and delayed receipts.

    Receipts arrive at the start of the day exactly lead_time_days after
    ordering. Reorder decisions use on-hand + outstanding inbound - backorders.
    Backorders are fulfilled before same-day demand; lost-sales mode never
    carries unmet demand forward. This is a single-item, deterministic
    periodic-review simulation, not a multi-echelon or stochastic simulator.
    """
    values = tuple(float(value) for value in demand)
    if not values:
        raise ValueError("demand must contain at least one day")
    if any(not isfinite(value) or value < 0.0 for value in values):
        raise ValueError("demand values must be finite and non-negative")

    arrivals: dict[int, float] = defaultdict(float)
    on_hand = config.initial_on_hand
    backorders = 0.0
    pipeline = 0.0
    total_ordered = 0.0
    total_fulfilled = 0.0
    total_lost_sales = 0.0
    stockout_days = 0
    states: list[DailyInventoryState] = []

    for day, quantity in enumerate(values):
        received = arrivals.pop(day, 0.0)
        pipeline -= received
        on_hand += received

        if config.allow_backorders:
            fulfilled_backorders = min(on_hand, backorders)
            on_hand -= fulfilled_backorders
            backorders -= fulfilled_backorders
            fulfilled_today = min(on_hand, quantity)
            on_hand -= fulfilled_today
            unmet = quantity - fulfilled_today
            backorders += unmet
            fulfilled = fulfilled_backorders + fulfilled_today
            lost_sales = 0.0
        else:
            fulfilled = min(on_hand, quantity)
            on_hand -= fulfilled
            lost_sales = quantity - fulfilled
            unmet = lost_sales

        if unmet > 0.0:
            stockout_days += 1
        total_fulfilled += fulfilled
        total_lost_sales += lost_sales

        inventory_position = on_hand + pipeline - backorders
        ordered = 0.0
        if inventory_position <= config.reorder_point:
            ordered = config.order_quantity
            arrivals[day + config.lead_time_days] += ordered
            pipeline += ordered
            total_ordered += ordered
            inventory_position += ordered

        states.append(
            DailyInventoryState(
                day=day,
                demand=quantity,
                received=received,
                ordered=ordered,
                fulfilled=fulfilled,
                lost_sales=lost_sales,
                backorders=backorders,
                on_hand=on_hand,
                inventory_position=inventory_position,
            )
        )

    total_demand = sum(values)
    return InventorySimulationReport(
        days=tuple(states),
        total_demand=total_demand,
        total_fulfilled=total_fulfilled,
        total_lost_sales=total_lost_sales,
        ending_backorders=backorders,
        ending_on_hand=on_hand,
        total_ordered=total_ordered,
        fill_rate=1.0 if total_demand == 0.0 else total_fulfilled / total_demand,
        stockout_days=stockout_days,
    )
