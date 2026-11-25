"""Explicit operator CLI for reconciling a complete ERPNext warehouse snapshot."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from demand_forecast_kit.erpnext import ERPNextClient
from demand_forecast_kit.operations import OperationalStore


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--tenant-id", required=True)
    parser.add_argument("--warehouse-id", required=True)
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--page-size", type=int, default=500)
    parser.add_argument(
        "--confirm-full-snapshot",
        action="store_true",
        help="confirm that this operation may reconcile records absent from the full ERPNext snapshot",
    )
    parser.add_argument(
        "--allow-empty-snapshot",
        action="store_true",
        help="allow empty ERPNext resources after independently verifying API permissions and source state",
    )
    args = parser.parse_args()
    if not args.confirm_full_snapshot:
        parser.error("--confirm-full-snapshot is required for destructive local reconciliation")

    required_environment = (
        "DEMAND_FORECAST_ERPNEXT_URL",
        "DEMAND_FORECAST_ERPNEXT_API_KEY",
        "DEMAND_FORECAST_ERPNEXT_API_SECRET",
    )
    missing = [name for name in required_environment if not os.environ.get(name)]
    if missing:
        parser.error(f"missing required environment variables: {', '.join(missing)}")

    client = ERPNextClient(
        os.environ["DEMAND_FORECAST_ERPNEXT_URL"],
        os.environ["DEMAND_FORECAST_ERPNEXT_API_KEY"],
        os.environ["DEMAND_FORECAST_ERPNEXT_API_SECRET"],
        timeout=args.timeout,
        page_size=args.page_size,
    )
    store = OperationalStore(args.database)
    result = client.reconcile_warehouse(\n        store,\n        args.tenant_id,\n        args.warehouse_id,\n        allow_empty_snapshot=args.allow_empty_snapshot,\n    )
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
