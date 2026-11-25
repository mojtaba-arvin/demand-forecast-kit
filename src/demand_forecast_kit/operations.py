"""Tenant-scoped operational data, replenishment inputs, and durable schedules.

The SQLite backend is intentionally single-machine. It provides transactional
consistency for a local deployment; it is not a distributed database.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Generator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from math import isfinite
from pathlib import Path
from typing import Any
from uuid import uuid4


def _now() -> datetime:
    return datetime.now(UTC)


def _iso(value: datetime | str) -> str:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise ValueError("timestamps must include timezone information")
        return value.astimezone(UTC).isoformat()
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("timestamp must be ISO-8601") from exc
    if parsed.tzinfo is None:
        raise ValueError("timestamps must include timezone information")
    return parsed.astimezone(UTC).isoformat()


def _positive(value: float, name: str, *, allow_zero: bool = True) -> float:
    number = float(value)
    if not isfinite(number) or (number < 0 if allow_zero else number <= 0):
        qualifier = "non-negative" if allow_zero else "positive"
        raise ValueError(f"{name} must be finite and {qualifier}")
    return number


class OperationalStore:
    """Persist tenant-isolated warehouses, inventory, purchase orders and jobs."""

    def __init__(self, database: str | Path) -> None:
        self.database = str(database)
        Path(self.database).expanduser().parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS warehouses (
                    tenant_id TEXT NOT NULL, warehouse_id TEXT NOT NULL,
                    name TEXT NOT NULL, location_code TEXT NOT NULL,
                    active INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL,
                    PRIMARY KEY (tenant_id, warehouse_id),
                    UNIQUE (tenant_id, location_code)
                );
                CREATE TABLE IF NOT EXISTS inventory_snapshots (
                    tenant_id TEXT NOT NULL, warehouse_id TEXT NOT NULL,
                    sku_id TEXT NOT NULL, quantity REAL NOT NULL CHECK(quantity >= 0),
                    reserved REAL NOT NULL CHECK(reserved >= 0),
                    backorders REAL NOT NULL DEFAULT 0 CHECK(backorders >= 0),
                    as_of TEXT NOT NULL, source TEXT NOT NULL,
                    PRIMARY KEY (tenant_id, warehouse_id, sku_id, as_of),
                    FOREIGN KEY (tenant_id, warehouse_id)
                      REFERENCES warehouses(tenant_id, warehouse_id)
                );
                CREATE INDEX IF NOT EXISTS inventory_latest
                  ON inventory_snapshots(tenant_id, warehouse_id, sku_id, as_of DESC);
                CREATE TABLE IF NOT EXISTS purchase_orders (
                    tenant_id TEXT NOT NULL, order_id TEXT NOT NULL,
                    supplier_id TEXT NOT NULL, warehouse_id TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN
                      ('draft','submitted','partially_received','received','cancelled')),
                    expected_at TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                    PRIMARY KEY (tenant_id, order_id),
                    FOREIGN KEY (tenant_id, warehouse_id)
                      REFERENCES warehouses(tenant_id, warehouse_id)
                );
                CREATE TABLE IF NOT EXISTS purchase_order_lines (
                    tenant_id TEXT NOT NULL, order_id TEXT NOT NULL,
                    sku_id TEXT NOT NULL, ordered REAL NOT NULL CHECK(ordered > 0),
                    received REAL NOT NULL DEFAULT 0 CHECK(received >= 0 AND received <= ordered),
                    unit_cost REAL,
                    PRIMARY KEY (tenant_id, order_id, sku_id),
                    FOREIGN KEY (tenant_id, order_id)
                      REFERENCES purchase_orders(tenant_id, order_id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS demand_observations (
                    tenant_id TEXT NOT NULL, warehouse_id TEXT NOT NULL,
                    sku_id TEXT NOT NULL, observed_at TEXT NOT NULL,
                    demand REAL NOT NULL CHECK(demand >= 0), source TEXT NOT NULL,
                    PRIMARY KEY (tenant_id, warehouse_id, sku_id, observed_at),
                    FOREIGN KEY (tenant_id, warehouse_id)
                      REFERENCES warehouses(tenant_id, warehouse_id)
                );
                CREATE INDEX IF NOT EXISTS demand_history
                  ON demand_observations(tenant_id, warehouse_id, sku_id, observed_at);
                CREATE TABLE IF NOT EXISTS forecast_outcomes (
                    outcome_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tenant_id TEXT NOT NULL, warehouse_id TEXT NOT NULL, sku_id TEXT NOT NULL,
                    model_id TEXT NOT NULL, model_version TEXT NOT NULL,
                    forecast_origin TEXT NOT NULL, target_at TEXT NOT NULL,
                    predicted REAL NOT NULL, actual REAL NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(tenant_id, warehouse_id, sku_id, model_id, model_version,
                           forecast_origin, target_at)
                );
                CREATE INDEX IF NOT EXISTS outcome_window
                  ON forecast_outcomes(tenant_id, warehouse_id, sku_id, model_id, created_at);
                CREATE TABLE IF NOT EXISTS policy_outcomes (
                    outcome_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tenant_id TEXT NOT NULL, warehouse_id TEXT NOT NULL, sku_id TEXT NOT NULL,
                    policy_id TEXT NOT NULL, decision_key TEXT NOT NULL,
                    inventory_position REAL NOT NULL, ordered_quantity REAL NOT NULL,
                    realized_demand REAL NOT NULL, holding_cost_per_unit REAL NOT NULL,
                    shortage_cost_per_unit REAL NOT NULL, created_at TEXT NOT NULL,
                    UNIQUE(tenant_id, warehouse_id, sku_id, policy_id, decision_key)
                );
                CREATE INDEX IF NOT EXISTS policy_outcome_window
                  ON policy_outcomes(tenant_id, warehouse_id, sku_id, policy_id, created_at);
                CREATE TABLE IF NOT EXISTS model_baselines (
                    tenant_id TEXT NOT NULL, warehouse_id TEXT NOT NULL, sku_id TEXT NOT NULL,
                    model_id TEXT NOT NULL, model_version TEXT NOT NULL,
                    baseline_mae REAL NOT NULL CHECK(baseline_mae >= 0),
                    sample_count INTEGER NOT NULL CHECK(sample_count > 0),
                    created_at TEXT NOT NULL,
                    PRIMARY KEY(tenant_id, warehouse_id, sku_id, model_id, model_version)
                );
                CREATE TABLE IF NOT EXISTS retraining_requests (
                    request_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL,
                    warehouse_id TEXT NOT NULL, sku_id TEXT NOT NULL,
                    model_id TEXT NOT NULL, model_version TEXT NOT NULL,
                    reason TEXT NOT NULL, status TEXT NOT NULL CHECK(status IN
                      ('queued','claimed','completed','failed')),
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                );
                CREATE UNIQUE INDEX IF NOT EXISTS one_active_retraining_request
                  ON retraining_requests(tenant_id, warehouse_id, sku_id, model_id, model_version)
                  WHERE status IN ('queued', 'claimed');
                CREATE TABLE IF NOT EXISTS scheduled_jobs (
                    tenant_id TEXT NOT NULL, job_id TEXT NOT NULL,
                    job_type TEXT NOT NULL, payload_json TEXT NOT NULL,
                    interval_seconds INTEGER NOT NULL CHECK(interval_seconds > 0),
                    next_run_at TEXT NOT NULL, last_run_at TEXT,
                    lease_until TEXT, enabled INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY(tenant_id, job_id)
                );
                """
            )
            inventory_columns = {
                str(row["name"]) for row in db.execute("PRAGMA table_info(inventory_snapshots)")
            }
            if "backorders" not in inventory_columns:
                db.execute(
                    "ALTER TABLE inventory_snapshots ADD COLUMN backorders REAL NOT NULL DEFAULT 0"
                )

    @contextmanager
    def _connect(self) -> Generator[sqlite3.Connection]:
        db = sqlite3.connect(self.database, timeout=15.0)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys = ON")
        db.execute("PRAGMA busy_timeout = 15000")
        try:
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def _tenant(tenant_id: str) -> str:
        if not tenant_id or not tenant_id.strip():
            raise ValueError("tenant_id must not be blank")
        return tenant_id.strip()

    def create_warehouse(
        self, tenant_id: str, warehouse_id: str, name: str, location_code: str
    ) -> dict[str, Any]:
        tenant = self._tenant(tenant_id)
        values = (warehouse_id, name, location_code)
        if any(not value or not value.strip() for value in values):
            raise ValueError("warehouse_id, name, and location_code must not be blank")
        with self._connect() as db:
            db.execute(
                """INSERT INTO warehouses
                   (tenant_id, warehouse_id, name, location_code, created_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (
                    tenant,
                    warehouse_id.strip(),
                    name.strip(),
                    location_code.strip(),
                    _now().isoformat(),
                ),
            )
        return self.get_warehouse(tenant, warehouse_id)

    def get_warehouse(self, tenant_id: str, warehouse_id: str) -> dict[str, Any]:
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM warehouses WHERE tenant_id=? AND warehouse_id=?",
                (self._tenant(tenant_id), warehouse_id),
            ).fetchone()
        if row is None:
            raise KeyError("warehouse not found")
        return dict(row)

    def list_warehouses(self, tenant_id: str) -> list[dict[str, Any]]:
        with self._connect() as db:
            rows = db.execute(
                "SELECT * FROM warehouses WHERE tenant_id=? ORDER BY warehouse_id",
                (self._tenant(tenant_id),),
            ).fetchall()
        return [dict(row) for row in rows]

    def record_inventory(
        self,
        tenant_id: str,
        warehouse_id: str,
        sku_id: str,
        quantity: float,
        *,
        reserved: float = 0,
        backorders: float = 0,
        as_of: datetime | str | None = None,
        source: str = "manual",
    ) -> dict[str, Any]:
        tenant = self._tenant(tenant_id)
        if not sku_id.strip() or not source.strip():
            raise ValueError("sku_id and source must not be blank")
        qty = _positive(quantity, "quantity")
        held = _positive(reserved, "reserved")
        owed = _positive(backorders, "backorders")
        if held > qty:
            raise ValueError("reserved cannot exceed on-hand quantity")
        timestamp = _iso(as_of or _now())
        with self._connect() as db:
            exists = db.execute(
                "SELECT 1 FROM warehouses WHERE tenant_id=? AND warehouse_id=?",
                (tenant, warehouse_id),
            ).fetchone()
            if exists is None:
                raise KeyError("warehouse not found")
            db.execute(
                """INSERT INTO inventory_snapshots
                   (tenant_id, warehouse_id, sku_id, quantity, reserved, backorders, as_of, source)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(tenant_id, warehouse_id, sku_id, as_of)
                   DO UPDATE SET quantity=excluded.quantity, reserved=excluded.reserved,
                     backorders=excluded.backorders, source=excluded.source""",
                (tenant, warehouse_id, sku_id.strip(), qty, held, owed, timestamp, source.strip()),
            )
        return self.inventory_position(tenant, warehouse_id, sku_id)

    def inventory_position(self, tenant_id: str, warehouse_id: str, sku_id: str) -> dict[str, Any]:
        tenant = self._tenant(tenant_id)
        with self._connect() as db:
            warehouse = db.execute(
                "SELECT 1 FROM warehouses WHERE tenant_id=? AND warehouse_id=?",
                (tenant, warehouse_id),
            ).fetchone()
            if warehouse is None:
                raise KeyError("warehouse not found")
            stock = db.execute(
                """SELECT quantity, reserved, backorders, as_of, source FROM inventory_snapshots
                   WHERE tenant_id=? AND warehouse_id=? AND sku_id=?
                   ORDER BY as_of DESC LIMIT 1""",
                (tenant, warehouse_id, sku_id),
            ).fetchone()
            inbound = db.execute(
                """SELECT COALESCE(SUM(l.ordered-l.received), 0) AS inbound
                   FROM purchase_order_lines l JOIN purchase_orders p
                   ON p.tenant_id=l.tenant_id AND p.order_id=l.order_id
                   WHERE p.tenant_id=? AND p.warehouse_id=? AND l.sku_id=?
                     AND p.status IN ('submitted','partially_received')""",
                (tenant, warehouse_id, sku_id),
            ).fetchone()
        on_hand = 0.0 if stock is None else float(stock["quantity"])
        reserved = 0.0 if stock is None else float(stock["reserved"])
        backorders = 0.0 if stock is None else float(stock["backorders"])
        confirmed_inbound = float(inbound["inbound"])
        return {
            "tenant_id": tenant,
            "warehouse_id": warehouse_id,
            "sku_id": sku_id,
            "on_hand": on_hand,
            "reserved": reserved,
            "backorders": backorders,
            "confirmed_inbound": confirmed_inbound,
            "inventory_position": on_hand - reserved + confirmed_inbound - backorders,
            "as_of": None if stock is None else str(stock["as_of"]),
            "source": None if stock is None else str(stock["source"]),
        }

    def create_purchase_order(
        self,
        tenant_id: str,
        *,
        order_id: str,
        supplier_id: str,
        warehouse_id: str,
        lines: list[dict[str, Any]],
        expected_at: datetime | str | None = None,
    ) -> dict[str, Any]:
        tenant = self._tenant(tenant_id)
        if not order_id.strip() or not supplier_id.strip() or not lines:
            raise ValueError("order_id, supplier_id, and at least one line are required")
        normalized: list[tuple[str, float, float | None]] = []
        seen: set[str] = set()
        for line in lines:
            sku = str(line.get("sku_id", "")).strip()
            qty = _positive(line.get("quantity", 0), "line quantity", allow_zero=False)
            cost_raw = line.get("unit_cost")
            cost = None if cost_raw is None else _positive(cost_raw, "unit_cost")
            if not sku or sku in seen:
                raise ValueError("purchase order SKU identifiers must be non-blank and unique")
            seen.add(sku)
            normalized.append((sku, qty, cost))
        expected = None if expected_at is None else _iso(expected_at)
        now = _now().isoformat()
        with self._connect() as db:
            warehouse = db.execute(
                "SELECT 1 FROM warehouses WHERE tenant_id=? AND warehouse_id=?",
                (tenant, warehouse_id),
            ).fetchone()
            if warehouse is None:
                raise KeyError("warehouse not found")
            db.execute(
                """INSERT INTO purchase_orders
                   (tenant_id, order_id, supplier_id, warehouse_id, status, expected_at,
                    created_at, updated_at) VALUES (?, ?, ?, ?, 'submitted', ?, ?, ?)""",
                (tenant, order_id, supplier_id, warehouse_id, expected, now, now),
            )
            db.executemany(
                """INSERT INTO purchase_order_lines
                   (tenant_id, order_id, sku_id, ordered, unit_cost)
                   VALUES (?, ?, ?, ?, ?)""",
                [(tenant, order_id, sku, qty, cost) for sku, qty, cost in normalized],
            )
        return self.get_purchase_order(tenant, order_id)

    def get_purchase_order(self, tenant_id: str, order_id: str) -> dict[str, Any]:
        tenant = self._tenant(tenant_id)
        with self._connect() as db:
            order = db.execute(
                "SELECT * FROM purchase_orders WHERE tenant_id=? AND order_id=?",
                (tenant, order_id),
            ).fetchone()
            if order is None:
                raise KeyError("purchase order not found")
            lines = db.execute(
                """SELECT sku_id, ordered, received, unit_cost FROM purchase_order_lines
                   WHERE tenant_id=? AND order_id=? ORDER BY sku_id""",
                (tenant, order_id),
            ).fetchall()
        return {**dict(order), "lines": [dict(line) for line in lines]}

    def sync_purchase_order(
        self,
        tenant_id: str,
        *,
        order_id: str,
        supplier_id: str,
        warehouse_id: str,
        lines: list[dict[str, Any]],
        expected_at: datetime | str | None = None,
    ) -> dict[str, Any]:
        """Idempotently import an ERP purchase order without double-counting received stock."""
        tenant = self._tenant(tenant_id)
        if not order_id.strip() or not supplier_id.strip() or not lines:
            raise ValueError("order_id, supplier_id, and at least one line are required")
        normalized: list[tuple[str, float, float, float | None]] = []
        seen: set[str] = set()
        for line in lines:
            sku = str(line.get("sku_id", "")).strip()
            ordered = _positive(line.get("quantity", 0), "line quantity", allow_zero=False)
            received = _positive(line.get("received_quantity", 0), "received quantity")
            if not sku or sku in seen:
                raise ValueError("purchase order SKU identifiers must be non-blank and unique")
            if received > ordered:
                raise ValueError("received quantity cannot exceed ordered quantity")
            seen.add(sku)
            raw_cost = line.get("unit_cost")
            cost = None if raw_cost is None else _positive(raw_cost, "unit_cost")
            normalized.append((sku, ordered, received, cost))
        expected = None if expected_at is None else _iso(expected_at)
        if all(received >= ordered for _sku, ordered, received, _cost in normalized):
            status = "received"
        elif any(received > 0 for _sku, _ordered, received, _cost in normalized):
            status = "partially_received"
        else:
            status = "submitted"
        now = _now().isoformat()
        with self._connect() as db:
            warehouse = db.execute(
                "SELECT 1 FROM warehouses WHERE tenant_id=? AND warehouse_id=?",
                (tenant, warehouse_id),
            ).fetchone()
            if warehouse is None:
                raise KeyError("warehouse not found")
            existing = db.execute(
                "SELECT * FROM purchase_orders WHERE tenant_id=? AND order_id=?",
                (tenant, order_id),
            ).fetchone()
            if existing is None:
                db.execute(
                    """INSERT INTO purchase_orders
                       (tenant_id, order_id, supplier_id, warehouse_id, status, expected_at,
                        created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (tenant, order_id, supplier_id, warehouse_id, status, expected, now, now),
                )
            else:
                if str(existing["warehouse_id"]) != warehouse_id:
                    raise ValueError("an imported purchase order cannot move between warehouses")
                db.execute(
                    """UPDATE purchase_orders SET supplier_id=?, status=?, expected_at=?,
                       updated_at=? WHERE tenant_id=? AND order_id=?""",
                    (supplier_id, status, expected, now, tenant, order_id),
                )
            sku_placeholders = ", ".join("?" for _ in normalized)
            db.execute(
                f"""DELETE FROM purchase_order_lines
                    WHERE tenant_id=? AND order_id=? AND sku_id NOT IN ({sku_placeholders})""",
                (tenant, order_id, *(sku for sku, _ordered, _received, _cost in normalized)),
            )
            for sku, ordered, received, cost in normalized:
                current = db.execute(
                    """SELECT ordered, received FROM purchase_order_lines
                       WHERE tenant_id=? AND order_id=? AND sku_id=?""",
                    (tenant, order_id, sku),
                ).fetchone()
                if current is None:
                    db.execute(
                        """INSERT INTO purchase_order_lines
                           (tenant_id, order_id, sku_id, ordered, received, unit_cost)
                           VALUES (?, ?, ?, ?, ?, ?)""",
                        (tenant, order_id, sku, ordered, received, cost),
                    )
                else:
                    if received < float(current["received"]):
                        raise ValueError("ERP-reported received quantity cannot move backwards")
                    if ordered < received:
                        raise ValueError("received quantity cannot exceed revised ordered quantity")
                    db.execute(
                        """UPDATE purchase_order_lines SET ordered=?, received=?, unit_cost=?
                           WHERE tenant_id=? AND order_id=? AND sku_id=?""",
                        (ordered, received, cost, tenant, order_id, sku),
                    )
        return self.get_purchase_order(tenant, order_id)

    def receive_purchase_order(
        self, tenant_id: str, order_id: str, receipts: list[dict[str, Any]]
    ) -> dict[str, Any]:
        tenant = self._tenant(tenant_id)
        if not receipts:
            raise ValueError("at least one receipt line is required")
        now = _now().isoformat()
        with self._connect() as db:
            order = db.execute(
                "SELECT status, warehouse_id FROM purchase_orders WHERE tenant_id=? AND order_id=?",
                (tenant, order_id),
            ).fetchone()
            if order is None:
                raise KeyError("purchase order not found")
            if order["status"] not in ("submitted", "partially_received"):
                raise ValueError("only submitted purchase orders can receive stock")
            warehouse_id = str(order["warehouse_id"])
            received_skus: set[str] = set()
            for receipt in receipts:
                sku = str(receipt.get("sku_id", "")).strip()
                if not sku or sku in received_skus:
                    raise ValueError("receipt SKU identifiers must be non-blank and unique")
                received_skus.add(sku)
                qty = _positive(receipt.get("quantity", 0), "received quantity", allow_zero=False)
                cursor = db.execute(
                    """UPDATE purchase_order_lines SET received=received+?
                       WHERE tenant_id=? AND order_id=? AND sku_id=?
                         AND received+? <= ordered""",
                    (qty, tenant, order_id, sku, qty),
                )
                if cursor.rowcount != 1:
                    raise ValueError(f"receipt exceeds ordered quantity or SKU is unknown: {sku}")
                current = db.execute(
                    """SELECT quantity, reserved, backorders FROM inventory_snapshots
                       WHERE tenant_id=? AND warehouse_id=? AND sku_id=?
                       ORDER BY as_of DESC LIMIT 1""",
                    (tenant, warehouse_id, sku),
                ).fetchone()
                on_hand = qty if current is None else float(current["quantity"]) + qty
                reserved = 0.0 if current is None else float(current["reserved"])
                backorders = 0.0 if current is None else float(current["backorders"])
                db.execute(
                    """INSERT INTO inventory_snapshots
                       (tenant_id, warehouse_id, sku_id, quantity, reserved, backorders,
                        as_of, source) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        tenant,
                        warehouse_id,
                        sku,
                        on_hand,
                        reserved,
                        backorders,
                        now,
                        f"purchase-order:{order_id}",
                    ),
                )
            remaining = db.execute(
                """SELECT COUNT(*) FROM purchase_order_lines
                   WHERE tenant_id=? AND order_id=? AND received < ordered""",
                (tenant, order_id),
            ).fetchone()[0]
            status = "partially_received" if remaining else "received"
            db.execute(
                """UPDATE purchase_orders SET status=?, updated_at=?
                   WHERE tenant_id=? AND order_id=?""",
                (status, now, tenant, order_id),
            )
        return self.get_purchase_order(tenant, order_id)

    def record_demand(
        self,
        tenant_id: str,
        warehouse_id: str,
        sku_id: str,
        demand: float,
        *,
        observed_at: datetime | str,
        source: str = "manual",
    ) -> dict[str, Any]:
        tenant = self._tenant(tenant_id)
        value = _positive(demand, "demand")
        if not sku_id.strip() or not source.strip():
            raise ValueError("sku_id and source must not be blank")
        timestamp = _iso(observed_at)
        with self._connect() as db:
            exists = db.execute(
                "SELECT 1 FROM warehouses WHERE tenant_id=? AND warehouse_id=?",
                (tenant, warehouse_id),
            ).fetchone()
            if exists is None:
                raise KeyError("warehouse not found")
            db.execute(
                """INSERT INTO demand_observations
                   (tenant_id, warehouse_id, sku_id, observed_at, demand, source)
                   VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(tenant_id, warehouse_id, sku_id, observed_at)
                   DO UPDATE SET demand=excluded.demand, source=excluded.source""",
                (tenant, warehouse_id, sku_id.strip(), timestamp, value, source.strip()),
            )
        return {
            "tenant_id": tenant,
            "warehouse_id": warehouse_id,
            "sku_id": sku_id.strip(),
            "observed_at": timestamp,
            "demand": value,
        }

    def demand_history(
        self, tenant_id: str, warehouse_id: str, sku_id: str, *, limit: int = 365
    ) -> list[dict[str, Any]]:
        if type(limit) is not int or not 1 <= limit <= 100_000:
            raise ValueError("limit must be between 1 and 100000")
        with self._connect() as db:
            rows = db.execute(
                """SELECT observed_at, demand, source FROM demand_observations
                   WHERE tenant_id=? AND warehouse_id=? AND sku_id=?
                   ORDER BY observed_at DESC LIMIT ?""",
                (self._tenant(tenant_id), warehouse_id, sku_id, limit),
            ).fetchall()
        return [dict(row) for row in reversed(rows)]

    def record_outcome(
        self,
        tenant_id: str,
        *,
        warehouse_id: str,
        sku_id: str,
        model_id: str,
        model_version: str,
        forecast_origin: datetime | str,
        target_at: datetime | str,
        predicted: float,
        actual: float,
    ) -> dict[str, Any]:
        tenant = self._tenant(tenant_id)
        for name, value in (("predicted", predicted), ("actual", actual)):
            _positive(value, name)
        if not all(item.strip() for item in (warehouse_id, sku_id, model_id, model_version)):
            raise ValueError("warehouse, SKU, model, and model version must not be blank")
        origin, target = _iso(forecast_origin), _iso(target_at)
        if target <= origin:
            raise ValueError("target_at must be later than forecast_origin")
        with self._connect() as db:
            warehouse = db.execute(
                "SELECT 1 FROM warehouses WHERE tenant_id=? AND warehouse_id=?",
                (tenant, warehouse_id),
            ).fetchone()
            if warehouse is None:
                raise KeyError("warehouse not found")
            db.execute(
                """INSERT INTO forecast_outcomes
                   (tenant_id, warehouse_id, sku_id, model_id, model_version,
                    forecast_origin, target_at, predicted, actual, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(tenant_id, warehouse_id, sku_id, model_id, model_version,
                               forecast_origin, target_at) DO NOTHING""",
                (
                    tenant,
                    warehouse_id,
                    sku_id,
                    model_id,
                    model_version,
                    origin,
                    target,
                    float(predicted),
                    float(actual),
                    _now().isoformat(),
                ),
            )
            row = db.execute(
                """SELECT * FROM forecast_outcomes
                   WHERE tenant_id=? AND warehouse_id=? AND sku_id=? AND model_id=?
                     AND model_version=? AND forecast_origin=? AND target_at=?""",
                (tenant, warehouse_id, sku_id, model_id, model_version, origin, target),
            ).fetchone()
        assert row is not None
        if float(row["predicted"]) != float(predicted) or float(row["actual"]) != float(actual):
            raise ValueError("forecast outcome identity is already bound to different values")
        return {
            "outcome_id": int(row["outcome_id"]),
            "tenant_id": tenant,
            "warehouse_id": warehouse_id,
            "sku_id": sku_id,
            "model_id": model_id,
            "model_version": model_version,
            "forecast_origin": origin,
            "target_at": target,
            "predicted": float(predicted),
            "actual": float(actual),
        }

    def set_model_baseline(
        self,
        tenant_id: str,
        *,
        warehouse_id: str,
        sku_id: str,
        model_id: str,
        model_version: str,
        baseline_mae: float,
        sample_count: int,
    ) -> None:
        value = _positive(baseline_mae, "baseline_mae")
        if type(sample_count) is not int or sample_count < 1:
            raise ValueError("sample_count must be a positive integer")
        with self._connect() as db:
            warehouse = db.execute(
                "SELECT 1 FROM warehouses WHERE tenant_id=? AND warehouse_id=?",
                (self._tenant(tenant_id), warehouse_id),
            ).fetchone()
            if warehouse is None:
                raise KeyError("warehouse not found")
            db.execute(
                """INSERT INTO model_baselines VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(tenant_id, warehouse_id, sku_id, model_id, model_version)
                   DO UPDATE SET baseline_mae=excluded.baseline_mae,
                     sample_count=excluded.sample_count, created_at=excluded.created_at""",
                (
                    self._tenant(tenant_id),
                    warehouse_id,
                    sku_id,
                    model_id,
                    model_version,
                    value,
                    sample_count,
                    _now().isoformat(),
                ),
            )

    def model_health(
        self,
        tenant_id: str,
        *,
        warehouse_id: str,
        sku_id: str,
        model_id: str,
        model_version: str,
        window: int = 30,
        min_samples: int = 10,
        degradation_ratio: float = 1.5,
    ) -> dict[str, Any]:
        if type(window) is not int or window < 1 or type(min_samples) is not int or min_samples < 1:
            raise ValueError("window and min_samples must be positive integers")
        ratio = _positive(degradation_ratio, "degradation_ratio", allow_zero=False)
        tenant = self._tenant(tenant_id)
        with self._connect() as db:
            baseline = db.execute(
                """SELECT baseline_mae, sample_count FROM model_baselines
                   WHERE tenant_id=? AND warehouse_id=? AND sku_id=?
                     AND model_id=? AND model_version=?""",
                (tenant, warehouse_id, sku_id, model_id, model_version),
            ).fetchone()
            rows = db.execute(
                """SELECT predicted, actual FROM forecast_outcomes
                   WHERE tenant_id=? AND warehouse_id=? AND sku_id=?
                     AND model_id=? AND model_version=?
                   ORDER BY target_at DESC LIMIT ?""",
                (tenant, warehouse_id, sku_id, model_id, model_version, window),
            ).fetchall()
        if baseline is None:
            return {"status": "baseline_missing", "sample_count": len(rows), "alert": False}
        if int(baseline["sample_count"]) < min_samples:
            return {
                "status": "baseline_insufficient",
                "sample_count": len(rows),
                "baseline_sample_count": int(baseline["sample_count"]),
                "required_baseline_samples": min_samples,
                "alert": False,
            }
        errors = [abs(float(row["predicted"]) - float(row["actual"])) for row in rows]
        mae = sum(errors) / len(errors) if errors else None
        enough = len(errors) >= min_samples
        baseline_mae = float(baseline["baseline_mae"])
        degraded = bool(
            enough
            and mae is not None
            and (
                (baseline_mae == 0 and mae > 0) or (baseline_mae > 0 and mae > baseline_mae * ratio)
            )
        )
        return {
            "status": "degraded" if degraded else ("healthy" if enough else "insufficient_samples"),
            "sample_count": len(errors),
            "required_samples": min_samples,
            "baseline_mae": baseline_mae,
            "rolling_mae": mae,
            "degradation_ratio": None if mae is None or baseline_mae == 0 else mae / baseline_mae,
            "alert": degraded,
        }

    def queue_retraining(
        self,
        tenant_id: str,
        *,
        warehouse_id: str,
        sku_id: str,
        model_id: str,
        model_version: str,
        reason: str,
    ) -> dict[str, Any]:
        tenant = self._tenant(tenant_id)
        if not reason.strip():
            raise ValueError("reason must not be blank")
        now = _now().isoformat()
        with self._connect() as db:
            warehouse = db.execute(
                "SELECT 1 FROM warehouses WHERE tenant_id=? AND warehouse_id=?",
                (tenant, warehouse_id),
            ).fetchone()
            if warehouse is None:
                raise KeyError("warehouse not found")
            existing = db.execute(
                """SELECT * FROM retraining_requests WHERE tenant_id=? AND warehouse_id=?
                   AND sku_id=? AND model_id=? AND model_version=?
                     AND status IN ('queued','claimed')""",
                (tenant, warehouse_id, sku_id, model_id, model_version),
            ).fetchone()
            if existing:
                return dict(existing)
            request_id = str(uuid4())
            db.execute(
                """INSERT INTO retraining_requests
                   VALUES (?, ?, ?, ?, ?, ?, ?, 'queued', ?, ?)""",
                (
                    request_id,
                    tenant,
                    warehouse_id,
                    sku_id,
                    model_id,
                    model_version,
                    reason,
                    now,
                    now,
                ),
            )
            row = db.execute(
                "SELECT * FROM retraining_requests WHERE request_id=?", (request_id,)
            ).fetchone()
        assert row is not None
        return dict(row)

    def record_policy_outcome(
        self,
        tenant_id: str,
        *,
        warehouse_id: str,
        sku_id: str,
        policy_id: str,
        decision_key: str,
        inventory_position: float,
        ordered_quantity: float,
        realized_demand: float,
        holding_cost_per_unit: float,
        shortage_cost_per_unit: float,
    ) -> dict[str, Any]:
        tenant = self._tenant(tenant_id)
        if not all(value.strip() for value in (warehouse_id, sku_id, policy_id, decision_key)):
            raise ValueError("warehouse, SKU, policy, and decision identifiers must not be blank")
        position = float(inventory_position)
        if not isfinite(position):
            raise ValueError("inventory_position must be finite")
        ordered = _positive(ordered_quantity, "ordered_quantity")
        demand = _positive(realized_demand, "realized_demand")
        holding = _positive(holding_cost_per_unit, "holding_cost_per_unit")
        shortage_rate = _positive(shortage_cost_per_unit, "shortage_cost_per_unit")
        now = _now().isoformat()
        with self._connect() as db:
            warehouse = db.execute(
                "SELECT 1 FROM warehouses WHERE tenant_id=? AND warehouse_id=?",
                (tenant, warehouse_id),
            ).fetchone()
            if warehouse is None:
                raise KeyError("warehouse not found")
            db.execute(
                """INSERT INTO policy_outcomes
                   (tenant_id, warehouse_id, sku_id, policy_id, decision_key,
                    inventory_position, ordered_quantity, realized_demand,
                    holding_cost_per_unit, shortage_cost_per_unit, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(tenant_id, warehouse_id, sku_id, policy_id, decision_key)
                   DO NOTHING""",
                (
                    tenant,
                    warehouse_id,
                    sku_id,
                    policy_id,
                    decision_key,
                    position,
                    ordered,
                    demand,
                    holding,
                    shortage_rate,
                    now,
                ),
            )
            row = db.execute(
                """SELECT * FROM policy_outcomes WHERE tenant_id=? AND warehouse_id=?
                   AND sku_id=? AND policy_id=? AND decision_key=?""",
                (tenant, warehouse_id, sku_id, policy_id, decision_key),
            ).fetchone()
        assert row is not None
        expected = (position, ordered, demand, holding, shortage_rate)
        stored = tuple(
            float(row[name])
            for name in (
                "inventory_position",
                "ordered_quantity",
                "realized_demand",
                "holding_cost_per_unit",
                "shortage_cost_per_unit",
            )
        )
        if stored != expected:
            raise ValueError("policy outcome identity is already bound to different values")
        available = max(0.0, position + ordered)
        fulfilled = min(demand, available)
        shortage = max(0.0, demand - available)
        ending = max(0.0, available - demand)
        holding_cost = ending * holding
        shortage_cost = shortage * shortage_rate
        return {
            "outcome_id": int(row["outcome_id"]),
            "tenant_id": tenant,
            "warehouse_id": warehouse_id,
            "sku_id": sku_id,
            "policy_id": policy_id,
            "decision_key": decision_key,
            "fulfilled_demand": fulfilled,
            "shortage_units": shortage,
            "ending_inventory": ending,
            "fill_rate": 1.0 if demand == 0 else fulfilled / demand,
            "cycle_service_level": shortage == 0.0,
            "total_cost": holding_cost + shortage_cost,
        }

    def rank_policies(
        self,
        tenant_id: str,
        *,
        warehouse_id: str,
        sku_id: str,
        min_samples: int = 5,
        window: int = 100,
    ) -> list[dict[str, Any]]:
        if type(min_samples) is not int or min_samples < 1:
            raise ValueError("min_samples must be a positive integer")
        if type(window) is not int or not 1 <= window <= 10000:
            raise ValueError("window must be between 1 and 10000")
        with self._connect() as db:
            rows = db.execute(
                """SELECT * FROM policy_outcomes WHERE tenant_id=? AND warehouse_id=?
                   AND sku_id=? ORDER BY created_at DESC LIMIT ?""",
                (self._tenant(tenant_id), warehouse_id, sku_id, window * 100),
            ).fetchall()
        grouped: dict[str, list[dict[str, float]]] = {}
        for row in rows:
            policy_id = str(row["policy_id"])
            observations = grouped.setdefault(policy_id, [])
            if len(observations) >= window:
                continue
            position = float(row["inventory_position"])
            ordered = float(row["ordered_quantity"])
            demand = float(row["realized_demand"])
            available = max(0.0, position + ordered)
            fulfilled = min(demand, available)
            shortage = max(0.0, demand - available)
            ending = max(0.0, available - demand)
            cost = ending * float(row["holding_cost_per_unit"]) + shortage * float(
                row["shortage_cost_per_unit"]
            )
            observations.append(
                {
                    "cost": cost,
                    "fill_rate": 1.0 if demand == 0 else fulfilled / demand,
                    "cycle_service": 1.0 if shortage == 0 else 0.0,
                }
            )
        ranked: list[dict[str, Any]] = []
        for policy_id, observations in grouped.items():
            if len(observations) < min_samples:
                continue
            count = len(observations)
            ranked.append(
                {
                    "policy_id": policy_id,
                    "sample_count": count,
                    "mean_cost": sum(item["cost"] for item in observations) / count,
                    "fill_rate": sum(item["fill_rate"] for item in observations) / count,
                    "cycle_service_level": sum(item["cycle_service"] for item in observations)
                    / count,
                }
            )
        return sorted(ranked, key=lambda item: (item["mean_cost"], item["policy_id"]))

    def list_retraining_requests(self, tenant_id: str, *, limit: int = 100) -> list[dict[str, Any]]:
        if type(limit) is not int or not 1 <= limit <= 1000:
            raise ValueError("limit must be between 1 and 1000")
        with self._connect() as db:
            rows = db.execute(
                """SELECT * FROM retraining_requests WHERE tenant_id=?
                   ORDER BY created_at DESC LIMIT ?""",
                (self._tenant(tenant_id), limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def rank_models(
        self,
        tenant_id: str,
        *,
        warehouse_id: str,
        sku_id: str,
        min_samples: int = 5,
        window: int = 100,
    ) -> list[dict[str, Any]]:
        if type(min_samples) is not int or min_samples < 1:
            raise ValueError("min_samples must be a positive integer")
        if type(window) is not int or not 1 <= window <= 10000:
            raise ValueError("window must be between 1 and 10000")
        with self._connect() as db:
            rows = db.execute(
                """SELECT model_id, model_version, predicted, actual, target_at
                   FROM forecast_outcomes
                   WHERE tenant_id=? AND warehouse_id=? AND sku_id=?
                   ORDER BY target_at DESC LIMIT ?""",
                (self._tenant(tenant_id), warehouse_id, sku_id, window * 100),
            ).fetchall()
        grouped: dict[tuple[str, str], list[float]] = {}
        for row in rows:
            key = (str(row["model_id"]), str(row["model_version"]))
            errors = grouped.setdefault(key, [])
            if len(errors) < window:
                errors.append(abs(float(row["predicted"]) - float(row["actual"])))
        ranked = [
            {
                "model_id": model_id,
                "model_version": version,
                "mae": sum(errors) / len(errors),
                "sample_count": len(errors),
            }
            for (model_id, version), errors in grouped.items()
            if len(errors) >= min_samples
        ]
        return sorted(
            ranked, key=lambda item: (item["mae"], item["model_id"], item["model_version"])
        )

    def recover_stale_retraining(
        self,
        tenant_id: str,
        *,
        stale_after_seconds: int = 3600,
        now: datetime | None = None,
    ) -> int:
        """Requeue claims abandoned by a crashed worker after a bounded lease."""
        if type(stale_after_seconds) is not int or stale_after_seconds < 1:
            raise ValueError("stale_after_seconds must be a positive integer")
        current = now or _now()
        if current.tzinfo is None:
            raise ValueError("now must include timezone information")
        cutoff = (current.astimezone(UTC) - timedelta(seconds=stale_after_seconds)).isoformat()
        with self._connect() as db:
            cursor = db.execute(
                """UPDATE retraining_requests SET status='queued', updated_at=?
                   WHERE tenant_id=? AND status='claimed' AND updated_at<=?""",
                (current.astimezone(UTC).isoformat(), self._tenant(tenant_id), cutoff),
            )
        return cursor.rowcount

    def claim_retraining(self, tenant_id: str, request_id: str) -> dict[str, Any]:
        now = _now().isoformat()
        with self._connect() as db:
            cursor = db.execute(
                """UPDATE retraining_requests SET status='claimed', updated_at=?
                   WHERE tenant_id=? AND request_id=? AND status='queued'""",
                (now, self._tenant(tenant_id), request_id),
            )
            if cursor.rowcount != 1:
                raise ValueError("retraining request is missing or already claimed")
            row = db.execute(
                "SELECT * FROM retraining_requests WHERE tenant_id=? AND request_id=?",
                (self._tenant(tenant_id), request_id),
            ).fetchone()
        assert row is not None
        return dict(row)

    def finish_retraining(
        self, tenant_id: str, request_id: str, *, success: bool
    ) -> dict[str, Any]:
        with self._connect() as db:
            cursor = db.execute(
                """UPDATE retraining_requests SET status=?, updated_at=?
                   WHERE tenant_id=? AND request_id=? AND status='claimed'""",
                (
                    "completed" if success else "failed",
                    _now().isoformat(),
                    self._tenant(tenant_id),
                    request_id,
                ),
            )
            if cursor.rowcount != 1:
                raise ValueError("only a claimed retraining request can be completed")
            row = db.execute(
                "SELECT * FROM retraining_requests WHERE tenant_id=? AND request_id=?",
                (self._tenant(tenant_id), request_id),
            ).fetchone()
        assert row is not None
        return dict(row)

    def create_schedule(
        self,
        tenant_id: str,
        *,
        job_type: str,
        payload: dict[str, Any],
        interval_seconds: int,
        first_run_at: datetime | str | None = None,
    ) -> dict[str, Any]:
        tenant = self._tenant(tenant_id)
        supported_types = {
            "forecast_refresh",
            "replenishment_review",
            "model_health",
            "policy_review",
        }
        if job_type not in supported_types:
            raise ValueError("unsupported scheduled job type")
        if type(interval_seconds) is not int or interval_seconds < 60:
            raise ValueError("interval_seconds must be at least 60")
        try:
            payload_json = json.dumps(
                payload, sort_keys=True, separators=(",", ":"), allow_nan=False
            )
        except (TypeError, ValueError) as exc:
            raise ValueError("schedule payload must be finite JSON data") from exc
        now = _now()
        next_run = _iso(first_run_at) if first_run_at is not None else now.isoformat()
        job_id = str(uuid4())
        with self._connect() as db:
            db.execute(
                """INSERT INTO scheduled_jobs
                   (tenant_id, job_id, job_type, payload_json, interval_seconds,
                    next_run_at, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    tenant,
                    job_id,
                    job_type,
                    payload_json,
                    interval_seconds,
                    next_run,
                    now.isoformat(),
                ),
            )
            row = db.execute(
                "SELECT * FROM scheduled_jobs WHERE tenant_id=? AND job_id=?",
                (tenant, job_id),
            ).fetchone()
        assert row is not None
        return self._schedule_record(row)

    def list_schedules(self, tenant_id: str) -> list[dict[str, Any]]:
        with self._connect() as db:
            rows = db.execute(
                "SELECT * FROM scheduled_jobs WHERE tenant_id=? ORDER BY created_at",
                (self._tenant(tenant_id),),
            ).fetchall()
        return [self._schedule_record(row) for row in rows]

    def claim_due_schedules(
        self,
        tenant_id: str,
        *,
        now: datetime | None = None,
        lease_seconds: int = 300,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        current = now or _now()
        if current.tzinfo is None or lease_seconds < 1 or not 1 <= limit <= 100:
            raise ValueError("invalid scheduler claim parameters")
        claimed: list[dict[str, Any]] = []
        with self._connect() as db:
            rows = db.execute(
                """SELECT * FROM scheduled_jobs WHERE tenant_id=? AND enabled=1
                   AND next_run_at<=? AND (lease_until IS NULL OR lease_until<=?)
                   ORDER BY next_run_at LIMIT ?""",
                (
                    self._tenant(tenant_id),
                    current.astimezone(UTC).isoformat(),
                    current.astimezone(UTC).isoformat(),
                    limit,
                ),
            ).fetchall()
            lease = (current + timedelta(seconds=lease_seconds)).astimezone(UTC).isoformat()
            for row in rows:
                cursor = db.execute(
                    """UPDATE scheduled_jobs SET lease_until=?
                       WHERE tenant_id=? AND job_id=?
                         AND (lease_until IS NULL OR lease_until<=?)""",
                    (
                        lease,
                        self._tenant(tenant_id),
                        row["job_id"],
                        current.astimezone(UTC).isoformat(),
                    ),
                )
                if cursor.rowcount:
                    claimed_row = db.execute(
                        "SELECT * FROM scheduled_jobs WHERE tenant_id=? AND job_id=?",
                        (self._tenant(tenant_id), row["job_id"]),
                    ).fetchone()
                    assert claimed_row is not None
                    claimed.append(self._schedule_record(claimed_row))
        return claimed

    def complete_schedule(
        self, tenant_id: str, job_id: str, *, completed_at: datetime | None = None
    ) -> dict[str, Any]:
        current = completed_at or _now()
        if current.tzinfo is None:
            raise ValueError("completed_at must include timezone information")
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM scheduled_jobs WHERE tenant_id=? AND job_id=?",
                (self._tenant(tenant_id), job_id),
            ).fetchone()
            if row is None:
                raise KeyError("scheduled job not found")
            next_run = (current + timedelta(seconds=int(row["interval_seconds"]))).astimezone(UTC)
            cursor = db.execute(
                """UPDATE scheduled_jobs SET last_run_at=?, next_run_at=?, lease_until=NULL
                   WHERE tenant_id=? AND job_id=? AND lease_until IS NOT NULL""",
                (
                    current.astimezone(UTC).isoformat(),
                    next_run.isoformat(),
                    self._tenant(tenant_id),
                    job_id,
                ),
            )
            if cursor.rowcount != 1:
                raise ValueError("scheduled job has no active lease")
            updated = db.execute(
                "SELECT * FROM scheduled_jobs WHERE tenant_id=? AND job_id=?",
                (self._tenant(tenant_id), job_id),
            ).fetchone()
        assert updated is not None
        return self._schedule_record(updated)

    def release_schedule(
        self, tenant_id: str, job_id: str, *, retry_after_seconds: int = 60
    ) -> dict[str, Any]:
        if type(retry_after_seconds) is not int or retry_after_seconds < 1:
            raise ValueError("retry_after_seconds must be a positive integer")
        retry_at = (_now() + timedelta(seconds=retry_after_seconds)).isoformat()
        with self._connect() as db:
            cursor = db.execute(
                """UPDATE scheduled_jobs SET next_run_at=?, lease_until=NULL
                   WHERE tenant_id=? AND job_id=? AND lease_until IS NOT NULL""",
                (retry_at, self._tenant(tenant_id), job_id),
            )
            if cursor.rowcount != 1:
                raise ValueError("scheduled job has no active lease")
            row = db.execute(
                "SELECT * FROM scheduled_jobs WHERE tenant_id=? AND job_id=?",
                (self._tenant(tenant_id), job_id),
            ).fetchone()
        assert row is not None
        return self._schedule_record(row)

    @staticmethod
    def _schedule_record(row: sqlite3.Row) -> dict[str, Any]:
        record = dict(row)
        record["payload"] = json.loads(record.pop("payload_json"))
        record["enabled"] = bool(record["enabled"])
        return record
