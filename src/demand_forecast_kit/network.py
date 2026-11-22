"""Tree-based multi-echelon inventory position calculations."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from math import isfinite


@dataclass(frozen=True, slots=True)
class InventoryNode:
    """One stocking location in a parent-child replenishment network."""

    node_id: str
    parent_id: str | None
    on_hand: float
    confirmed_inbound: float = 0.0
    backorders: float = 0.0


@dataclass(frozen=True, slots=True)
class EchelonPosition:
    """Local and downstream inventory position for one network node."""

    node_id: str
    local_position: float
    downstream_position: float
    echelon_position: float


def calculate_echelon_positions(nodes: Sequence[InventoryNode]) -> tuple[EchelonPosition, ...]:
    """Calculate local and cumulative downstream inventory positions.

    The input must describe one or more rooted trees. Every node contributes
    on-hand plus confirmed inbound minus backorders. A parent's echelon
    position includes the positions of all descendant stocking locations.
    """
    if not nodes:
        raise ValueError("at least one inventory node is required")
    by_id: dict[str, InventoryNode] = {}
    children: dict[str, list[str]] = {}
    for node in nodes:
        if not node.node_id.strip() or node.node_id in by_id:
            raise ValueError("node identifiers must be non-blank and unique")
        for name, value in (
            ("on_hand", node.on_hand),
            ("confirmed_inbound", node.confirmed_inbound),
            ("backorders", node.backorders),
        ):
            if not isfinite(value) or value < 0.0:
                raise ValueError(f"{name} must be finite and non-negative")
        by_id[node.node_id] = node
        children[node.node_id] = []
    roots: list[str] = []
    for node in nodes:
        if node.parent_id is None:
            roots.append(node.node_id)
        elif node.parent_id not in by_id:
            raise ValueError(f"unknown parent_id: {node.parent_id}")
        else:
            children[node.parent_id].append(node.node_id)
    if not roots:
        raise ValueError("inventory network must contain at least one root")

    local = {
        node.node_id: node.on_hand + node.confirmed_inbound - node.backorders
        for node in nodes
    }
    visiting: set[str] = set()
    calculated: dict[str, float] = {}

    def visit(node_id: str) -> float:
        if node_id in visiting:
            raise ValueError("inventory network contains a cycle")
        if node_id in calculated:
            return calculated[node_id]
        visiting.add(node_id)
        downstream = sum(visit(child) for child in children[node_id])
        visiting.remove(node_id)
        calculated[node_id] = local[node_id] + downstream
        return calculated[node_id]

    for root in roots:
        visit(root)
    if len(calculated) != len(nodes):
        raise ValueError("inventory network contains a disconnected cycle")
    return tuple(
        EchelonPosition(
            node_id=node.node_id,
            local_position=local[node.node_id],
            downstream_position=calculated[node.node_id] - local[node.node_id],
            echelon_position=calculated[node.node_id],
        )
        for node in nodes
    )
