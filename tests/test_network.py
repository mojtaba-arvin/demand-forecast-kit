import pytest

from demand_forecast_kit.network import InventoryNode, calculate_echelon_positions


def test_echelon_position_includes_all_descendant_locations() -> None:
    result = calculate_echelon_positions(
        [
            InventoryNode("dc", None, on_hand=100, confirmed_inbound=20),
            InventoryNode("store-a", "dc", on_hand=10, backorders=2),
            InventoryNode("store-b", "dc", on_hand=5, confirmed_inbound=3),
        ]
    )
    by_id = {item.node_id: item for item in result}

    assert by_id["dc"].local_position == 120
    assert by_id["dc"].downstream_position == 16
    assert by_id["dc"].echelon_position == 136
    assert by_id["store-a"].echelon_position == 8


def test_echelon_position_rejects_unknown_parent_and_cycles() -> None:
    with pytest.raises(ValueError, match="unknown parent"):
        calculate_echelon_positions([InventoryNode("a", "missing", 1)])
    with pytest.raises(ValueError, match="cycle"):
        calculate_echelon_positions(
            [
                InventoryNode("a", "b", 1),
                InventoryNode("b", "a", 1),
            ]
        )


def test_echelon_position_rejects_invalid_stock_values() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        calculate_echelon_positions([InventoryNode("root", None, -1)])
