import json
from urllib.parse import urlsplit

from demand_forecast_kit.erpnext import ERPNextClient
from demand_forecast_kit.operations import OperationalStore


def test_erpnext_bin_import_does_not_overwrite_manual_inventory(tmp_path) -> None:
    def transport(url, method, headers, body, timeout):
        doctype = urlsplit(url).path.rsplit("/", 1)[-1]
        if doctype == "Bin":
            data = [
                {
                    "item_code": "SKU-1",
                    "warehouse": "WH-1",
                    "actual_qty": 20,
                    "reserved_qty": 2,
                    "modified": "2026-11-25 09:00:00",
                }
            ]
        else:
            data = []
        return json.dumps({"data": data}).encode()

    store = OperationalStore(tmp_path / "manual-inventory.sqlite")
    store.create_warehouse("tenant-a", "WH-1", "Main", "main")
    store.record_inventory("tenant-a", "WH-1", "SKU-1", 99, reserved=4, source="manual")
    client = ERPNextClient("https://erp.example", "key", "secret", transport=transport)

    result = client.sync_warehouse(store, "tenant-a", "WH-1")

    assert result["inventory_items"] == 0
    position = store.inventory_position("tenant-a", "WH-1", "SKU-1")
    assert position["on_hand"] == 99
    assert position["reserved"] == 4
