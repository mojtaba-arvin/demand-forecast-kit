"""Authenticated HTTP API for tenant-scoped inventory and model operations."""
# FastAPI dependency injection intentionally uses Depends in endpoint defaults.
# ruff: noqa: B008

import hashlib
import hmac
import json
import os
from datetime import datetime
from typing import Any

from demand_forecast_kit.operations import OperationalStore


def build_operations_router(service: Any) -> Any:
    """Build the operations router without making FastAPI a core dependency."""
    try:
        from fastapi import APIRouter, Depends, Header, HTTPException
        from pydantic import BaseModel, ConfigDict, Field
    except ImportError as exc:
        raise RuntimeError("install demand-forecast-kit[api] to use the HTTP API") from exc

    store = OperationalStore(service.state_dir / "operations.sqlite")
    router = APIRouter(prefix="/v1/ops", tags=["operations"])
    configured = os.environ.get("DEMAND_FORECAST_API_KEYS", "").strip()
    environment = os.environ.get("DEMAND_FORECAST_ENV", "development").lower()
    if not configured and environment == "production":
        raise RuntimeError("DEMAND_FORECAST_API_KEYS must be configured in production")
    try:
        key_records = json.loads(configured) if configured else []
    except json.JSONDecodeError as exc:
        raise RuntimeError("DEMAND_FORECAST_API_KEYS must be valid JSON") from exc
    if not isinstance(key_records, list):
        raise RuntimeError("DEMAND_FORECAST_API_KEYS must be a JSON array")
    keys: dict[str, dict[str, Any]] = {}
    for record in key_records:
        if not isinstance(record, dict):
            raise RuntimeError("each API key record must be an object")
        key_id = record.get("key_id")
        digest = record.get("token_sha256")
        tenant = record.get("tenant_id")
        scopes = record.get("scopes")
        if (
            not isinstance(key_id, str) or not key_id.strip()
            or not isinstance(digest, str) or len(digest) != 64
            or not isinstance(tenant, str) or not tenant.strip()
            or not isinstance(scopes, list) or not all(isinstance(item, str) for item in scopes)
        ):
            raise RuntimeError(
                "API key records require key_id, SHA-256 token digest, tenant_id, scopes"
            )
        if key_id in keys:
            raise RuntimeError("API key identifiers must be unique")
        keys[key_id] = {"digest": digest.lower(), "tenant_id": tenant, "scopes": set(scopes)}

    def principal(authorization: str | None = Header(default=None)) -> dict[str, Any]:
        if not keys:
            return {"key_id": "local-development", "tenant_id": "local", "scopes": {"*"}}
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="bearer token required")
        token = authorization[7:].strip()
        digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
        match = next(
            (item for item in keys.values() if hmac.compare_digest(item["digest"], digest)),
            None,
        )
        if match is None:
            raise HTTPException(status_code=401, detail="invalid API token")
        return {"key_id": "configured-key", "tenant_id": match["tenant_id"],
                "scopes": match["scopes"]}

    def authorize(user: dict[str, Any], scope: str) -> str:
        scopes = user["scopes"]
        implied = (
            scope == "ops:read" and ("ops:write" in scopes or "ops:admin" in scopes)
        ) or (scope == "ops:write" and "ops:admin" in scopes)
        if "*" not in scopes and scope not in scopes and not implied:
            raise HTTPException(status_code=403, detail="insufficient API key scope")
        return str(user["tenant_id"])

    class StrictModel(BaseModel):
        model_config = ConfigDict(extra="forbid")

    class WarehouseInput(StrictModel):
        warehouse_id: str = Field(min_length=1, max_length=128)
        name: str = Field(min_length=1, max_length=200)
        location_code: str = Field(min_length=1, max_length=128)

    class InventoryInput(StrictModel):
        warehouse_id: str = Field(min_length=1)
        sku_id: str = Field(min_length=1)
        quantity: float = Field(ge=0)
        reserved: float = Field(default=0, ge=0)
        backorders: float = Field(default=0, ge=0)
        as_of: datetime | None = None
        source: str = Field(default="manual", min_length=1, max_length=128)

    class PurchaseLine(StrictModel):
        sku_id: str = Field(min_length=1)
        quantity: float = Field(gt=0)
        unit_cost: float | None = Field(default=None, ge=0)

    class PurchaseOrderInput(StrictModel):
        order_id: str = Field(min_length=1, max_length=128)
        supplier_id: str = Field(min_length=1, max_length=128)
        warehouse_id: str = Field(min_length=1)
        expected_at: datetime | None = None
        lines: list[PurchaseLine] = Field(min_length=1, max_length=1000)

    class ReceiptInput(StrictModel):
        lines: list[PurchaseLine] = Field(min_length=1, max_length=1000)

    class DemandInput(StrictModel):
        warehouse_id: str = Field(min_length=1)
        sku_id: str = Field(min_length=1)
        observed_at: datetime
        demand: float = Field(ge=0)
        source: str = Field(default="manual", min_length=1, max_length=128)

    class OutcomeInput(StrictModel):
        warehouse_id: str = Field(min_length=1)
        sku_id: str = Field(min_length=1)
        model_id: str = Field(min_length=1)
        model_version: str = Field(min_length=1)
        forecast_origin: datetime
        target_at: datetime
        predicted: float = Field(ge=0)
        actual: float = Field(ge=0)

    class BaselineInput(StrictModel):
        warehouse_id: str = Field(min_length=1)
        sku_id: str = Field(min_length=1)
        model_id: str = Field(min_length=1)
        model_version: str = Field(min_length=1)
        baseline_mae: float = Field(ge=0)
        sample_count: int = Field(ge=1)

    class HealthInput(StrictModel):
        warehouse_id: str = Field(min_length=1)
        sku_id: str = Field(min_length=1)
        model_id: str = Field(min_length=1)
        model_version: str = Field(min_length=1)
        window: int = Field(default=30, ge=1, le=1000)
        min_samples: int = Field(default=10, ge=1, le=1000)
        degradation_ratio: float = Field(default=1.5, gt=0)

    class ScheduleInput(StrictModel):
        job_type: str
        payload: dict[str, Any] = Field(default_factory=dict)
        interval_seconds: int = Field(ge=60)
        first_run_at: datetime | None = None

    def call(operation: Any, *args: Any, **kwargs: Any) -> Any:
        try:
            return operation(*args, **kwargs)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc).strip("'")) from exc
        except (ValueError, TypeError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.get("/warehouses")
    def list_warehouses(user: dict[str, Any] = Depends(principal)) -> dict[str, Any]:
        tenant = authorize(user, "ops:read")
        return {"warehouses": store.list_warehouses(tenant)}

    @router.post("/warehouses", status_code=201)
    def create_warehouse(
        request: WarehouseInput, user: dict[str, Any] = Depends(principal)
    ) -> dict[str, Any]:
        tenant = authorize(user, "ops:write")
        return call(store.create_warehouse, tenant, request.warehouse_id,
                    request.name, request.location_code)

    @router.post("/inventory/snapshots", status_code=201)
    def record_inventory(
        request: InventoryInput, user: dict[str, Any] = Depends(principal)
    ) -> dict[str, Any]:
        tenant = authorize(user, "ops:write")
        return call(
            store.record_inventory, tenant, request.warehouse_id, request.sku_id,
            request.quantity, reserved=request.reserved, backorders=request.backorders,
            as_of=request.as_of, source=request.source,
        )

    @router.get("/inventory/{warehouse_id}/{sku_id}")
    def inventory_position(
        warehouse_id: str, sku_id: str, user: dict[str, Any] = Depends(principal)
    ) -> dict[str, Any]:
        tenant = authorize(user, "ops:read")
        return call(store.inventory_position, tenant, warehouse_id, sku_id)

    @router.post("/purchase-orders", status_code=201)
    def create_purchase_order(
        request: PurchaseOrderInput, user: dict[str, Any] = Depends(principal)
    ) -> dict[str, Any]:
        tenant = authorize(user, "ops:write")
        return call(
            store.create_purchase_order, tenant, order_id=request.order_id,
            supplier_id=request.supplier_id, warehouse_id=request.warehouse_id,
            expected_at=request.expected_at,
            lines=[line.model_dump() for line in request.lines],
        )

    @router.get("/purchase-orders/{order_id}")
    def get_purchase_order(
        order_id: str, user: dict[str, Any] = Depends(principal)
    ) -> dict[str, Any]:
        tenant = authorize(user, "ops:read")
        return call(store.get_purchase_order, tenant, order_id)

    @router.post("/purchase-orders/{order_id}/receipts")
    def receive_purchase_order(
        order_id: str, request: ReceiptInput, user: dict[str, Any] = Depends(principal)
    ) -> dict[str, Any]:
        tenant = authorize(user, "ops:write")
        return call(store.receive_purchase_order, tenant, order_id,
                    [line.model_dump(exclude={"unit_cost"}) for line in request.lines])

    @router.post("/demand/observations", status_code=201)
    def record_demand(
        request: DemandInput, user: dict[str, Any] = Depends(principal)
    ) -> dict[str, Any]:
        tenant = authorize(user, "ops:write")
        return call(store.record_demand, tenant, request.warehouse_id, request.sku_id,
                    request.demand, observed_at=request.observed_at, source=request.source)

    @router.get("/demand/history/{warehouse_id}/{sku_id}")
    def demand_history(
        warehouse_id: str, sku_id: str, limit: int = 365,
        user: dict[str, Any] = Depends(principal),
    ) -> dict[str, Any]:
        tenant = authorize(user, "ops:read")
        return call(store.demand_history, tenant, warehouse_id, sku_id, limit=limit)

    @router.post("/monitoring/outcomes", status_code=201)
    def record_outcome(
        request: OutcomeInput, user: dict[str, Any] = Depends(principal)
    ) -> dict[str, Any]:
        tenant = authorize(user, "ops:write")
        return call(store.record_outcome, tenant, **request.model_dump())

    @router.post("/monitoring/baselines", status_code=201)
    def set_baseline(
        request: BaselineInput, user: dict[str, Any] = Depends(principal)
    ) -> dict[str, str]:
        tenant = authorize(user, "ops:admin")
        call(store.set_model_baseline, tenant, **request.model_dump())
        return {"status": "stored"}

    @router.post("/monitoring/health")
    def model_health(
        request: HealthInput, user: dict[str, Any] = Depends(principal)
    ) -> dict[str, Any]:
        tenant = authorize(user, "ops:read")
        result = call(store.model_health, tenant, **request.model_dump())
        if result.get("alert"):
            result["retraining_request"] = call(
                store.queue_retraining, tenant, warehouse_id=request.warehouse_id,
                sku_id=request.sku_id, model_id=request.model_id,
                model_version=request.model_version, reason="rolling_mae_degradation",
            )
        return result

    @router.post("/schedules", status_code=201)
    def create_schedule(
        request: ScheduleInput, user: dict[str, Any] = Depends(principal)
    ) -> dict[str, Any]:
        tenant = authorize(user, "ops:admin")
        return call(store.create_schedule, tenant, **request.model_dump())

    @router.get("/schedules")
    def list_schedules(user: dict[str, Any] = Depends(principal)) -> dict[str, Any]:
        tenant = authorize(user, "ops:read")
        return {"schedules": store.list_schedules(tenant)}

    @router.post("/schedules/claim-due")
    def claim_due_schedules(
        limit: int = 20, user: dict[str, Any] = Depends(principal)
    ) -> dict[str, Any]:
        tenant = authorize(user, "ops:admin")
        return {"jobs": call(store.claim_due_schedules, tenant, limit=limit)}

    @router.post("/schedules/{job_id}/complete")
    def complete_schedule(
        job_id: str, user: dict[str, Any] = Depends(principal)
    ) -> dict[str, Any]:
        tenant = authorize(user, "ops:admin")
        return call(store.complete_schedule, tenant, job_id)

    @router.get("/retraining-requests")
    def list_retraining_requests(user: dict[str, Any] = Depends(principal)) -> dict[str, Any]:
        tenant = authorize(user, "ops:admin")
        # A bounded query is intentionally exposed through a dedicated store method.
        return {"requests": store.list_retraining_requests(tenant)}

    @router.post("/retraining-requests/{request_id}/claim")
    def claim_retraining(
        request_id: str, user: dict[str, Any] = Depends(principal)
    ) -> dict[str, Any]:
        tenant = authorize(user, "ops:admin")
        return call(store.claim_retraining, tenant, request_id)

    @router.post("/retraining-requests/{request_id}/finish")
    def finish_retraining(
        request_id: str, success: bool, user: dict[str, Any] = Depends(principal)
    ) -> dict[str, Any]:
        tenant = authorize(user, "ops:admin")
        return call(store.finish_retraining, tenant, request_id, success=success)

    class PolicyOutcomeInput(StrictModel):
        warehouse_id: str = Field(min_length=1)
        sku_id: str = Field(min_length=1)
        policy_id: str = Field(min_length=1)
        decision_key: str = Field(min_length=1)
        inventory_position: float
        ordered_quantity: float = Field(ge=0)
        realized_demand: float = Field(ge=0)
        holding_cost_per_unit: float = Field(ge=0)
        shortage_cost_per_unit: float = Field(ge=0)

    class PolicySelectionInput(StrictModel):
        warehouse_id: str = Field(min_length=1)
        sku_id: str = Field(min_length=1)
        min_samples: int = Field(default=5, ge=1, le=1000)
        window: int = Field(default=100, ge=1, le=10000)
        fallback_policy_id: str = Field(default="newsvendor-default", min_length=1)

    class ModelSelectionInput(StrictModel):
        warehouse_id: str = Field(min_length=1)
        sku_id: str = Field(min_length=1)
        min_samples: int = Field(default=5, ge=1, le=1000)
        window: int = Field(default=100, ge=1, le=10000)
        fallback_model_id: str = Field(default="seasonal-naive", min_length=1)

    @router.post("/monitoring/model-selection")
    def select_model(
        request: ModelSelectionInput, user: dict[str, Any] = Depends(principal)
    ) -> dict[str, Any]:
        tenant = authorize(user, "ops:read")
        candidates = call(
            store.rank_models, tenant, warehouse_id=request.warehouse_id,
            sku_id=request.sku_id, min_samples=request.min_samples, window=request.window,
        )
        if candidates:
            selected = candidates[0]
            return {"selected": selected, "used_fallback": False, "candidates": candidates}
        return {
            "selected": {"model_id": request.fallback_model_id, "model_version": None,
                         "mae": None, "sample_count": 0},
            "used_fallback": True, "candidates": [],
            "reason": "insufficient_out_of_sample_evidence",
        }

    @router.post("/monitoring/policy-outcomes", status_code=201)
    def record_policy_outcome(
        request: PolicyOutcomeInput, user: dict[str, Any] = Depends(principal)
    ) -> dict[str, Any]:
        tenant = authorize(user, "ops:write")
        return call(store.record_policy_outcome, tenant, **request.model_dump())

    @router.post("/monitoring/policy-selection")
    def select_policy(
        request: PolicySelectionInput, user: dict[str, Any] = Depends(principal)
    ) -> dict[str, Any]:
        tenant = authorize(user, "ops:read")
        candidates = call(
            store.rank_policies, tenant, warehouse_id=request.warehouse_id,
            sku_id=request.sku_id, min_samples=request.min_samples, window=request.window,
        )
        if candidates:
            return {"selected": candidates[0], "used_fallback": False, "candidates": candidates}
        return {
            "selected": {"policy_id": request.fallback_policy_id, "mean_cost": None,
                         "sample_count": 0},
            "used_fallback": True, "candidates": [],
            "reason": "insufficient_realized_outcome_evidence",
        }

    @router.post("/erpnext/sync/{warehouse_id}")
    def sync_erpnext(
        warehouse_id: str, user: dict[str, Any] = Depends(principal)
    ) -> dict[str, Any]:
        tenant = authorize(user, "ops:admin")
        base_url = os.environ.get("DEMAND_FORECAST_ERPNEXT_URL", "").strip()
        api_key = os.environ.get("DEMAND_FORECAST_ERPNEXT_API_KEY", "").strip()
        api_secret = os.environ.get("DEMAND_FORECAST_ERPNEXT_API_SECRET", "").strip()
        if not all((base_url, api_key, api_secret)):
            raise HTTPException(status_code=503, detail="ERPNext connector is not configured")
        try:
            from demand_forecast_kit.erpnext import ERPNextClient
            store.get_warehouse(tenant, warehouse_id)
            result = ERPNextClient(base_url, api_key, api_secret).sync_warehouse(
                store, tenant, warehouse_id
            )
            return {"warehouse_id": warehouse_id, **result}
        except (ValueError, KeyError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    return router


def install_api_auth(app: Any) -> None:
    """Require configured bearer keys for API routes outside local development.

    Operational routes enforce tenant scopes themselves. Legacy run/forecast
    endpoints are explicitly shared-state endpoints and require the
    runs:shared scope when API keys are configured.
    """
    configured = os.environ.get("DEMAND_FORECAST_API_KEYS", "").strip()
    if not configured:
        if os.environ.get("DEMAND_FORECAST_ENV", "development").lower() == "production":
            raise RuntimeError("DEMAND_FORECAST_API_KEYS must be configured in production")
        return
    try:
        records = json.loads(configured)
    except json.JSONDecodeError as exc:
        raise RuntimeError("DEMAND_FORECAST_API_KEYS must be valid JSON") from exc
    if not isinstance(records, list):
        raise RuntimeError("DEMAND_FORECAST_API_KEYS must be a JSON array")
    tokens: list[tuple[str, set[str]]] = []
    for record in records:
        if not isinstance(record, dict):
            raise RuntimeError("each API key record must be an object")
        digest, scopes = record.get("token_sha256"), record.get("scopes")
        if (
            not isinstance(digest, str) or len(digest) != 64
            or not isinstance(scopes, list) or not all(isinstance(scope, str) for scope in scopes)
        ):
            raise RuntimeError("API key records require token_sha256 and scopes")
        tokens.append((digest.lower(), set(scopes)))
    if not tokens:
        raise RuntimeError("at least one API key must be configured in production")

    @app.middleware("http")
    async def authenticate_api_request(request: Any, call_next: Any) -> Any:
        path = request.url.path
        if path == "/health" or not path.startswith("/v1/"):
            return await call_next(request)
        authorization = request.headers.get("authorization", "")
        token = authorization[7:].strip() if authorization.startswith("Bearer ") else ""
        digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
        scopes = next(
            (allowed for expected, allowed in tokens if hmac.compare_digest(expected, digest)),
            None,
        )
        if scopes is None:
            from fastapi.responses import JSONResponse
            return JSONResponse(status_code=401, content={"detail": "invalid or missing API token"})
        if not path.startswith("/v1/ops/") and "*" not in scopes and "runs:shared" not in scopes:
            from fastapi.responses import JSONResponse
            return JSONResponse(status_code=403, content={"detail": "runs:shared scope required"})
        return await call_next(request)
